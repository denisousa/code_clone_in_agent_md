"""
resolve_submodule_failures.py

For each fetch_error in clone_terms_failed.json, attempt to recover the file
content by detecting git submodules in the parent repository.

How it works
------------
A URL like:
  https://raw.githubusercontent.com/getsentry/sentry-godot/{sha}/modules/gdUnit4/CLAUDE.md

fails because modules/gdUnit4 is actually a *separate* git repository pinned as
a submodule.  The file therefore lives at:
  https://raw.githubusercontent.com/{submodule_owner}/{submodule_repo}/{sub_sha}/CLAUDE.md

Resolution pipeline (per failed entry):
  1. Parse owner / repo / sha / path from the raw URL.
  2. Fetch .gitmodules from the parent repo at the recorded SHA.
  3. Find the submodule whose 'path' is a prefix of the failing file path.
  4. Query the GitHub Contents API to get the submodule's pinned commit SHA.
  5. Build a new raw.githubusercontent.com URL with the submodule's coords.
  6. Fetch the file content and search for clone terms.
  7. Write matches → submodule_resolved_report.json
     Write still-unresolved entries → submodule_still_failed.json

Requires GITHUB_TOKEN in environment (or .env file).
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import requests
from dotenv import load_dotenv

from main_ai_config import (
    CLEAN_TERMS,
    DELAY_BETWEEN_REQUESTS,
    RESULTS_DIR,
    apply_regex,
    build_headers,
    extract_snippets,
    fetch_raw_content,
    handle_rate_limit,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

FAILED_PATH       = RESULTS_DIR / "clone_terms_failed.json"
REPORT_PATH       = RESULTS_DIR / "clone_terms_report.json"
NEW_REPORT_PATH   = RESULTS_DIR / "new_clone_terms_report.json"
RESOLVED_PATH     = RESULTS_DIR / "submodule_resolved_report.json"
STILL_FAILED_PATH = RESULTS_DIR / "submodule_still_failed.json"

# ---------------------------------------------------------------------------
# Parse a raw.githubusercontent.com URL
# ---------------------------------------------------------------------------

RAW_URL_PATTERN = re.compile(
    r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)"
)


def parse_raw_url(raw_url: str) -> tuple[str, str, str, str] | None:
    """Return (owner, repo, sha, path) or None if the URL doesn't match."""
    m = RAW_URL_PATTERN.match(raw_url)
    if m:
        return m.group(1), m.group(2), m.group(3), m.group(4)
    return None


# ---------------------------------------------------------------------------
# Extract GitHub owner/repo from various remote URL formats
# ---------------------------------------------------------------------------

def github_owner_repo(remote_url: str) -> tuple[str, str] | None:
    """
    Accept any of:
      https://github.com/owner/repo
      https://github.com/owner/repo.git
      git@github.com:owner/repo.git
    Return (owner, repo) or None for non-GitHub remotes.
    """
    # HTTPS
    m = re.match(r"https://github\.com/([^/]+)/([^/.]+)(?:\.git)?/?$", remote_url)
    if m:
        return m.group(1), m.group(2)
    # SSH
    m = re.match(r"git@github\.com:([^/]+)/([^/.]+)(?:\.git)?$", remote_url)
    if m:
        return m.group(1), m.group(2)
    return None


# ---------------------------------------------------------------------------
# Fetch and parse .gitmodules
# ---------------------------------------------------------------------------

def fetch_gitmodules(
    owner: str, repo: str, sha: str, headers: dict
) -> str | None:
    """Fetch .gitmodules text from the parent repo at the given SHA."""
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{sha}/.gitmodules"
    while True:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
        except requests.RequestException as exc:
            print(f"    [REQUEST ERROR] fetching .gitmodules: {exc}")
            return None

        if resp.status_code == 200:
            return resp.text
        if resp.status_code in (429, 403) and "rate limit" in resp.text.lower():
            handle_rate_limit(resp)
            continue
        return None  # 404 or other — no .gitmodules


def parse_gitmodules(content: str) -> dict[str, str]:
    """
    Parse .gitmodules and return a dict mapping submodule path → remote URL.

    .gitmodules uses a git-config format:
        [submodule "name"]
            path = some/path
            url  = https://github.com/owner/repo
    """
    submodules: dict[str, str] = {}
    current_path: str | None = None
    current_url: str | None = None

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("path"):
            current_path = stripped.split("=", 1)[1].strip()
        elif stripped.startswith("url"):
            current_url = stripped.split("=", 1)[1].strip()

        if current_path and current_url:
            submodules[current_path] = current_url
            current_path = None
            current_url = None

    return submodules


def find_submodule(file_path: str, submodules: dict[str, str]) -> tuple[str, str] | None:
    """
    Find the submodule whose path is the longest prefix of file_path.
    Returns (submodule_path, remote_url) or None.
    """
    best: tuple[str, str] | None = None
    for sub_path, remote_url in submodules.items():
        if file_path == sub_path or file_path.startswith(sub_path + "/"):
            if best is None or len(sub_path) > len(best[0]):
                best = (sub_path, remote_url)
    return best


# ---------------------------------------------------------------------------
# Get the pinned commit SHA of a submodule via GitHub Contents API
# ---------------------------------------------------------------------------

def get_submodule_sha(
    owner: str, repo: str, submodule_path: str, ref: str, headers: dict
) -> str | None:
    """
    Call GET /repos/{owner}/{repo}/contents/{path}?ref={sha} and return
    the submodule's pinned commit SHA (the 'sha' field when type=='submodule').
    """
    api_url = (
        f"https://api.github.com/repos/{owner}/{repo}"
        f"/contents/{submodule_path}?ref={ref}"
    )
    while True:
        try:
            resp = requests.get(api_url, headers=headers, timeout=15)
        except requests.RequestException as exc:
            print(f"    [REQUEST ERROR] Contents API: {exc}")
            return None

        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and data.get("type") == "submodule":
                return data.get("sha")
            return None  # path exists but is not a submodule
        if resp.status_code in (429, 403) and "rate limit" in resp.text.lower():
            handle_rate_limit(resp)
            continue
        return None


# ---------------------------------------------------------------------------
# Core resolution logic for a single failed entry
# ---------------------------------------------------------------------------

def resolve_entry(entry: dict, headers: dict, gitmodules_cache: dict) -> dict:
    """
    Try to resolve a single failed entry via submodule detection.

    Returns a result dict with keys:
      status          "resolved" | "no_gitmodules" | "no_submodule_match"
                      | "not_github" | "parse_error" | "fetch_error"
      new_raw_url     the reconstructed URL (only when status=="resolved")
      hits            list of matched term dicts (only when resolved + match)
      ...original entry fields
    """
    base = {
        "csv":       entry["csv"],
        "repo_name": entry["repo_name"],
        "file_path": entry["file_path"],
        "raw_url":   entry["raw_url"],
    }

    parsed = parse_raw_url(entry["raw_url"])
    if not parsed:
        return {**base, "status": "parse_error"}

    owner, repo, sha, file_path = parsed

    # Cache key to avoid re-fetching .gitmodules for the same parent repo/sha
    cache_key = (owner, repo, sha)
    if cache_key not in gitmodules_cache:
        print(f"    Fetching .gitmodules for {owner}/{repo}@{sha[:8]}…")
        raw_gm = fetch_gitmodules(owner, repo, sha, headers)
        time.sleep(DELAY_BETWEEN_REQUESTS)
        gitmodules_cache[cache_key] = parse_gitmodules(raw_gm) if raw_gm else None

    submodules = gitmodules_cache[cache_key]
    if submodules is None:
        return {**base, "status": "no_gitmodules"}

    match = find_submodule(file_path, submodules)
    if not match:
        return {**base, "status": "no_submodule_match"}

    sub_path, remote_url = match
    owner_repo = github_owner_repo(remote_url)
    if not owner_repo:
        return {**base, "status": "not_github", "remote_url": remote_url}

    sub_owner, sub_repo = owner_repo

    # Get the pinned commit SHA for this submodule
    sub_sha = get_submodule_sha(owner, repo, sub_path, sha, headers)
    time.sleep(DELAY_BETWEEN_REQUESTS)

    if not sub_sha:
        # Fall back to the parent SHA (less accurate, but worth a try)
        print(f"    [WARN] Could not get submodule SHA; falling back to parent SHA.")
        sub_sha = sha

    # The file path relative to the submodule root
    remaining = file_path[len(sub_path):].lstrip("/")
    new_raw_url = (
        f"https://raw.githubusercontent.com/{sub_owner}/{sub_repo}/{sub_sha}/{remaining}"
    )

    print(f"    New URL: {new_raw_url}")
    content = fetch_raw_content(new_raw_url, headers)
    time.sleep(DELAY_BETWEEN_REQUESTS)

    if content is None:
        return {**base, "status": "fetch_error", "new_raw_url": new_raw_url}

    hits = apply_regex(content)
    return {
        **base,
        "status":      "resolved",
        "new_raw_url": new_raw_url,
        "submodule_repo": f"{sub_owner}/{sub_repo}",
        "submodule_sha":  sub_sha,
        "total_occurrences": sum(h.count for h in hits),
        "terms": [
            {
                "term":     h.term,
                "count":    h.count,
                "snippets": h.snippets[:3],
            }
            for h in hits
        ],
    }


# ---------------------------------------------------------------------------
# Merge resolved entries into a new full report
# ---------------------------------------------------------------------------

def save_new_report(resolved_with_hits: list[dict]) -> None:
    """
    Load clone_terms_report.json, merge newly resolved submodule matches into
    the matching CSV source, and write new_clone_terms_report.json.

    Each resolved entry is converted to the same match format used by the
    original report, with an extra `submodule_repo` field for traceability.
    """
    from pathlib import Path as _Path

    original = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    # Index sources by CSV name for fast lookup
    sources_by_csv: dict[str, dict] = {s["csv"]: s for s in original["sources"]}

    # Group resolved hits by CSV
    new_matches_by_csv: dict[str, list[dict]] = {}
    for r in resolved_with_hits:
        csv_name = r["csv"]
        # Reconstruct a match entry in the same shape as the original report
        match_entry = {
            "repo_name":       r["repo_name"],
            "file_name":       _Path(r["file_path"]).name,
            "file_path":       r["file_path"],
            "raw_url":         r["new_raw_url"],
            "submodule_repo":  r["submodule_repo"],
            "total_occurrences": r["total_occurrences"],
            "terms":           r["terms"],
        }
        new_matches_by_csv.setdefault(csv_name, []).append(match_entry)

    # Merge into a deep copy of the original sources
    import copy
    merged_sources = copy.deepcopy(original["sources"])
    for source in merged_sources:
        extras = new_matches_by_csv.get(source["csv"], [])
        if extras:
            source["matches"].extend(extras)
            source["total_md_files_with_match"] += len(extras)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": merged_sources,
    }
    NEW_REPORT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[SAVED] New combined report → {NEW_REPORT_PATH}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    start = perf_counter()

    # Load failed entries
    failed_data = json.loads(FAILED_PATH.read_text(encoding="utf-8"))
    all_failed: list[dict] = failed_data["failed"]
    fetch_errors = [e for e in all_failed if e["reason"] == "fetch_error"]

    print("=" * 60)
    print("  Submodule URL resolver")
    print("=" * 60)
    print(f"  Total failed entries  : {len(all_failed)}")
    print(f"  fetch_error entries   : {len(fetch_errors)}")
    print(f"  Estimated runtime     : ~{len(fetch_errors) * 3}s  (≤3 API calls/entry)")
    print("=" * 60)

    headers = build_headers()
    gitmodules_cache: dict = {}

    resolved_matches: list[dict] = []
    still_failed: list[dict] = []

    for i, entry in enumerate(fetch_errors, start=1):
        print(f"\n[{i}/{len(fetch_errors)}] {entry['repo_name']} / {entry['file_path']}")
        result = resolve_entry(entry, headers, gitmodules_cache)
        status = result["status"]
        print(f"    → status: {status}")

        if status == "resolved":
            resolved_matches.append(result)
        else:
            still_failed.append(result)

    # --- Save resolved report ---
    RESULTS_DIR.mkdir(exist_ok=True)

    resolved_with_hits   = [r for r in resolved_matches if r["total_occurrences"] > 0]
    resolved_no_hits     = [r for r in resolved_matches if r["total_occurrences"] == 0]

    resolved_output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_resolved": len(resolved_matches),
        "resolved_with_clone_terms": len(resolved_with_hits),
        "resolved_no_clone_terms": len(resolved_no_hits),
        "matches": resolved_with_hits,
        "no_matches": resolved_no_hits,
    }
    RESOLVED_PATH.write_text(
        json.dumps(resolved_output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[SAVED] Resolved report → {RESOLVED_PATH}")

    # --- Save still-failed report ---
    still_failed_output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_still_failed": len(still_failed),
        "entries": still_failed,
    }
    STILL_FAILED_PATH.write_text(
        json.dumps(still_failed_output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[SAVED] Still-failed report → {STILL_FAILED_PATH}")

    # --- Build new_clone_terms_report.json ---
    save_new_report(resolved_with_hits)

    # --- Summary ---
    elapsed = perf_counter() - start
    elapsed_min, elapsed_sec = divmod(elapsed, 60)
    print(f"\n{'='*60}")
    print(f"  Entries processed  : {len(fetch_errors)}")
    print(f"  Resolved           : {len(resolved_matches)}")
    print(f"    with clone terms : {len(resolved_with_hits)}")
    print(f"  Still unresolved   : {len(still_failed)}")
    if elapsed_min:
        print(f"  Total runtime      : {int(elapsed_min)}m {elapsed_sec:.1f}s")
    else:
        print(f"  Total runtime      : {elapsed_sec:.1f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
