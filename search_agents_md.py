"""
Search GitHub for AGENTS.md files that mention code clone-related terms.

Workflow:
  1. For each term in CLONE_TERMS, query the GitHub Code Search API for
     files named AGENTS.md that contain that term.
  2. Deduplicate: first by html_url (same file found via multiple terms),
     then by canonical path (owner/path) to drop forks pointing to identical
     content at the same relative location.
  3. Fetch the star count for each unique repository and discard files from
     repos with fewer than MIN_STARS stars.
  4. Fetch the raw content of each surviving file and verify it against a
     case-insensitive regex built from all CLONE_TERMS (guards against API
     false-positives and ensures the term really appears in the file).
  5. Write the filtered results to a JSON file and a Markdown report.

Requires a GitHub personal access token set in the GITHUB_TOKEN environment
variable to avoid hitting the unauthenticated rate limit (10 req/min).
"""

import base64
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CLONE_TERMS = [
    '"duplicate code"',
    '"duplicated code"',
    '"code duplication"',
    '"code redundancy"',
    '"duplicated logic"',
    '"copy-paste code"',
    '"copy-pasted code"',
    '"repeated code"',
    '"extract method"',
    '"extract function"',
    '"DRY principle"',
    '"avoid duplication"',
]

# Case-insensitive regex built from all terms (quotes stripped – used to
# verify raw file content after the API search step).
TERM_REGEX: re.Pattern = re.compile(
    "|".join(re.escape(t.strip('"')) for t in CLONE_TERMS),
    re.IGNORECASE,
)

MIN_STARS = 100  # Repositories with fewer stars are excluded

GITHUB_API_URL = "https://api.github.com/search/code"
GITHUB_REPO_URL = "https://api.github.com/repos/{full_name}"
PER_PAGE = 100       # max allowed by GitHub Search API
MAX_RESULTS = 1000   # GitHub Search API hard cap per query
DELAY_BETWEEN_TERMS = 6  # seconds – keeps authenticated rate limit safe
DELAY_BETWEEN_PAGES = 2  # seconds
DELAY_BETWEEN_REPO_CALLS = 1  # seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN")  # loaded from .env via load_dotenv()
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        print(
            "[WARNING] GITHUB_TOKEN not set. "
            "Unauthenticated requests are limited to 10/min.\n"
        )
    return headers


def handle_rate_limit(response: requests.Response) -> None:
    """Block until the rate-limit window resets."""
    reset_ts = int(response.headers.get("X-RateLimit-Reset", time.time() + 60))
    wait = max(reset_ts - time.time(), 0) + 5
    print(f"  [RATE LIMIT] Waiting {wait:.0f} seconds before retrying...")
    time.sleep(wait)


def request_with_retry(url: str, headers: dict, params: dict | None = None) -> requests.Response | None:
    """GET a URL, automatically retrying on rate-limit responses."""
    while True:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 429 or (
            response.status_code == 403
            and "rate limit" in response.text.lower()
        ):
            handle_rate_limit(response)
            continue
        return response


def search_by_term(term: str, headers: dict) -> list[dict]:
    """
    Return all AGENTS.md file items from the GitHub code-search API
    that match the given term.
    """
    results: list[dict] = []
    page = 1

    while True:
        params = {
            "q": f"filename:AGENTS.md {term}",
            "per_page": PER_PAGE,
            "page": page,
        }

        response = request_with_retry(GITHUB_API_URL, headers, params)

        if response is None or response.status_code == 422:
            print(f"  [SKIP] Query rejected for term: {term}")
            break

        if response.status_code != 200:
            print(f"  [ERROR] HTTP {response.status_code}: {response.text[:200]}")
            break

        data = response.json()
        items: list[dict] = data.get("items", [])

        if not items:
            break

        results.extend(items)

        total_count: int = data.get("total_count", 0)
        fetched_so_far = page * PER_PAGE
        print(
            f"  Page {page}: fetched {len(items)} items "
            f"(total reported by API: {total_count})"
        )

        # GitHub caps results at 1 000 regardless of total_count
        if fetched_so_far >= min(total_count, MAX_RESULTS):
            break

        page += 1
        time.sleep(DELAY_BETWEEN_PAGES)

    return results


def fetch_file_content(repo: str, path: str, headers: dict) -> str | None:
    """Download the raw text content of a file via the GitHub Contents API."""
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    response = request_with_retry(url, headers)
    if response is None or response.status_code != 200:
        return None
    data = response.json()
    encoding = data.get("encoding", "")
    raw = data.get("content", "")
    if encoding == "base64":
        return base64.b64decode(raw).decode("utf-8", errors="replace")
    return raw  # plain text fallback


def get_repo_stars(full_name: str, headers: dict, cache: dict) -> int:
    """Return the star count for a repository, using a local cache."""
    if full_name in cache:
        return cache[full_name]

    url = GITHUB_REPO_URL.format(full_name=full_name)
    response = request_with_retry(url, headers)

    stars = 0
    if response is not None and response.status_code == 200:
        stars = response.json().get("stargazers_count", 0)
    elif response is not None:
        print(f"  [WARN] Could not fetch repo info for {full_name}: HTTP {response.status_code}")

    cache[full_name] = stars
    time.sleep(DELAY_BETWEEN_REPO_CALLS)
    return stars


def deduplicate_by_canonical_path(file_index: dict) -> list[dict]:
    """
    Primary dedup: file_index is already keyed by html_url, so the same file
    found via multiple terms is already merged.

    Secondary dedup: drop forks — if two repos have an AGENTS.md at the
    identical relative path AND one is a fork of the other, GitHub's fork
    network means the content is effectively the same file. We keep only the
    entry with the most matched terms; ties are broken by repo name
    alphabetically so the result is deterministic.
    """
    # Group by the file's path (relative to repo root)
    by_path: dict[str, list[dict]] = defaultdict(list)
    for entry in file_index.values():
        if entry["html_url"]:
            by_path[entry["path"]].append(entry)

    deduplicated: list[dict] = []
    for path, entries in by_path.items():
        if len(entries) == 1:
            deduplicated.append(entries[0])
        else:
            # Keep the entry with the most matched terms; deterministic tie-break
            best = max(
                entries,
                key=lambda e: (len(e["matched_terms"]), -ord(e["repo"][0].lower())),
            )
            deduplicated.append(best)

    return deduplicated


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def save_json(results: list[dict], output_dir: str) -> str:
    path = os.path.join(output_dir, "agents_md_results.json")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "min_stars_filter": MIN_STARS,
        "total_files": len(results),
        "files": results,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return path


def save_markdown_report(results: list[dict], output_dir: str, stats: dict) -> str:
    path = os.path.join(output_dir, "agents_md_report.md")

    # Count how many files matched each term
    term_counts: dict[str, int] = {t: 0 for t in CLONE_TERMS}
    for entry in results:
        for term in entry["matched_terms"]:
            if term in term_counts:
                term_counts[term] += 1

    lines: list[str] = [
        "# AGENTS.md Search Report",
        "",
        f"**Generated at:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total AGENTS.md files found (before star filter) | {stats['total_before_star_filter']} |",
        f"| Files discarded (repo stars < {MIN_STARS}) | {stats['discarded_low_stars']} |",
        f"| Files discarded (fork deduplication) | {stats['discarded_forks']} |",
        f"| Files discarded (regex content check) | {stats.get('discarded_regex', 0)} |",
        f"| **Files in final results** | **{len(results)}** |",
        f"| Minimum stars required | {MIN_STARS} |",
        "",
        "## Matched Terms Breakdown",
        "",
        "| Term | Files |",
        "|------|-------|",
    ]

    for term, count in term_counts.items():
        lines.append(f"| `{term}` | {count} |")

    lines += [
        "",
        "## Results",
        "",
    ]

    for i, entry in enumerate(results, start=1):
        terms_str = ", ".join(f"`{t}`" for t in sorted(entry["matched_terms"]))
        lines += [
            f"### {i}. [{entry['repo']}]({entry['repo_url']})",
            "",
            f"- **File path:** `{entry['path']}`",
            f"- **File URL:** {entry['html_url']}",
            f"- **Stars:** {entry['stars']:,}",
            f"- **Matched terms:** {terms_str}",
            "",
        ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    headers = build_headers()

    # ------------------------------------------------------------------
    # Step 1: Search – collect all matching files keyed by html_url
    # ------------------------------------------------------------------
    file_index: dict[str, dict] = defaultdict(
        lambda: {"repo": "", "path": "", "html_url": "", "matched_terms": set()}
    )

    for term in CLONE_TERMS:
        print(f"\n[SEARCH] Searching for AGENTS.md files containing: {term}")
        items = search_by_term(term, headers)
        print(f"  -> {len(items)} result(s) found for this term.")

        for item in items:
            html_url: str = item.get("html_url", "")
            if not html_url:
                continue

            entry = file_index[html_url]
            entry["repo"] = item.get("repository", {}).get("full_name", "unknown")
            entry["path"] = item.get("path", "")
            entry["html_url"] = html_url
            entry["matched_terms"].add(term)

        time.sleep(DELAY_BETWEEN_TERMS)

    total_after_url_dedup = len([v for v in file_index.values() if v["html_url"]])
    print(f"\n[DEDUP] {total_after_url_dedup} unique file(s) after URL deduplication.")

    # ------------------------------------------------------------------
    # Step 2: Fork deduplication (same relative path across repos)
    # ------------------------------------------------------------------
    deduped_files = deduplicate_by_canonical_path(file_index)
    discarded_forks = total_after_url_dedup - len(deduped_files)
    print(f"[DEDUP] {discarded_forks} file(s) removed by fork/path deduplication.")
    print(f"[DEDUP] {len(deduped_files)} file(s) remaining.")

    # ------------------------------------------------------------------
    # Step 3: Fetch star counts and filter
    # ------------------------------------------------------------------
    print(f"\n[STARS] Fetching star counts (min required: {MIN_STARS})...")
    stars_cache: dict[str, int] = {}
    filtered_files: list[dict] = []

    for entry in deduped_files:
        stars = get_repo_stars(entry["repo"], headers, stars_cache)
        entry["stars"] = stars
        entry["repo_url"] = f"https://github.com/{entry['repo']}"

        if stars >= MIN_STARS:
            filtered_files.append(entry)
        else:
            print(f"  [SKIP] {entry['repo']} ({stars} stars < {MIN_STARS})")

    discarded_low_stars = len(deduped_files) - len(filtered_files)
    print(f"[STARS] {discarded_low_stars} file(s) removed (repo stars < {MIN_STARS}).")
    print(f"[STARS] {len(filtered_files)} file(s) remaining.")

    # ------------------------------------------------------------------
    # Step 4: Regex verification – fetch raw content and confirm matches
    # ------------------------------------------------------------------
    print(f"\n[REGEX] Verifying file contents with case-insensitive regex...")
    print(f"[REGEX] Pattern: {TERM_REGEX.pattern[:120]}{'...' if len(TERM_REGEX.pattern) > 120 else ''}")

    verified_files: list[dict] = []
    for entry in filtered_files:
        content = fetch_file_content(entry["repo"], entry["path"], headers)
        if content is None:
            print(f"  [WARN] Could not fetch content for {entry['repo']}/{entry['path']} – keeping anyway.")
            verified_files.append(entry)
            continue

        # Find all terms that actually appear in the file (case-insensitive)
        confirmed_terms = {
            t.strip('"')
            for t in CLONE_TERMS
            if re.search(re.escape(t.strip('"')), content, re.IGNORECASE)
        }

        if confirmed_terms:
            entry["matched_terms"] = sorted(confirmed_terms)
            verified_files.append(entry)
        else:
            print(f"  [SKIP] {entry['repo']}/{entry['path']} – no term found in raw content.")

        time.sleep(DELAY_BETWEEN_REPO_CALLS)

    discarded_regex = len(filtered_files) - len(verified_files)
    print(f"[REGEX] {discarded_regex} file(s) removed (no term in raw content).")
    print(f"[REGEX] {len(verified_files)} file(s) remaining.")

    # Serialise matched_terms (set -> sorted list) for JSON output
    # (already sorted above; ensure any remaining sets are also converted)
    for entry in verified_files:
        if isinstance(entry["matched_terms"], set):
            entry["matched_terms"] = sorted(entry["matched_terms"])

    # ------------------------------------------------------------------
    # Step 5: Console summary
    # ------------------------------------------------------------------
    print(f"\n{'='*70}")
    print(f"FINAL RESULTS: {len(verified_files)} unique AGENTS.md file(s) matched.\n")
    for entry in verified_files:
        print(f"Repo  : {entry['repo']} ({entry['stars']:,} stars)")
        print(f"Path  : {entry['path']}")
        print(f"URL   : {entry['html_url']}")
        print(f"Terms : {', '.join(entry['matched_terms'])}")
        print()

    # ------------------------------------------------------------------
    # Step 6: Save outputs
    # ------------------------------------------------------------------
    output_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(output_dir, exist_ok=True)

    stats = {
        "total_before_star_filter": len(deduped_files),
        "discarded_low_stars": discarded_low_stars,
        "discarded_forks": discarded_forks,
        "discarded_regex": discarded_regex,
    }

    json_path = save_json(verified_files, output_dir)
    md_path = save_markdown_report(verified_files, output_dir, stats)

    print(f"JSON report saved to : {json_path}")
    print(f"Markdown report saved: {md_path}")


if __name__ == "__main__":
    main()
