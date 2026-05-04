"""
Filter clone_terms_report.json to keep only repositories whose primary
GitHub language is supported by NiCad.

Supported languages:
  C (.c), C# (.cs), Java (.java), Python (.py), PHP (.php), Ruby (.rb)

Outputs:
  - ai_config_results/clone_terms_report_filtered.json
        Same structure as the original, but only with matches from
        supported-language repos.
  - ai_config_results/clone_terms_skipped_languages.json
        List of removed repos with their detected language.

Requires GITHUB_TOKEN in the environment (or .env file) to avoid
hitting the unauthenticated rate limit.

Usage:
  python filter_by_language.py
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

INPUT_PATH = Path("ai_config_results/clone_terms_report.json")
OUTPUT_PATH = Path("ai_config_results/clone_terms_report_filtered.json")
SKIPPED_PATH = Path("ai_config_results/clone_terms_skipped_languages.json")

# GitHub language name → NiCad language identifier
SUPPORTED_LANGUAGES: dict[str, str] = {
    "C": "c",
    "C#": "cs",
    "Java": "java",
    "Python": "py",
    "PHP": "php",
    "Ruby": "rb",
}

NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# GitHub API helper
# ---------------------------------------------------------------------------

def get_repo_language(repo_name: str, headers: dict) -> str | None:
    """Return the primary language reported by GitHub, or None on failure."""
    url = f"https://api.github.com/repos/{repo_name}"
    try:
        resp = requests.get(url, headers=headers, timeout=30)

        # Handle rate limiting with a wait-and-retry
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            reset = int(resp.headers.get("X-RateLimit-Reset", 0))
            wait = max(reset - int(time.time()), 5)
            print(f"  [RATE-LIMIT] waiting {wait}s …")
            time.sleep(wait)
            resp = requests.get(url, headers=headers, timeout=30)

        if resp.status_code != 200:
            print(f"  [WARN] GitHub API {resp.status_code} for {repo_name}")
            return None

        return resp.json().get("language")
    except Exception as exc:
        print(f"  [WARN] language fetch failed for {repo_name}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not INPUT_PATH.exists():
        print(f"[ERROR] Input not found: {INPUT_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(INPUT_PATH, encoding="utf-8") as f:
        report = json.load(f)

    # Collect every unique repo across all sources
    all_repos: set[str] = set()
    for source in report.get("sources", []):
        for match in source.get("matches", []):
            all_repos.add(match["repo_name"])

    total = len(all_repos)
    print(f"Unique repositories in report: {total}\n")

    # Build auth headers
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        print("[WARN] GITHUB_TOKEN not set – rate limit is 60 req/hour.\n")

    # Fetch language for each repo
    repo_languages: dict[str, str | None] = {}
    for i, repo in enumerate(sorted(all_repos), start=1):
        lang = get_repo_language(repo, headers)
        repo_languages[repo] = lang
        status = "OK" if lang and lang in SUPPORTED_LANGUAGES else "SKIP"
        print(f"  [{i:3d}/{total}] {status}  {repo}  → {lang}")

    # Partition into kept / skipped
    kept_repos = {
        r for r, lang in repo_languages.items()
        if lang and lang in SUPPORTED_LANGUAGES
    }
    skipped_repos = {
        r for r in all_repos if r not in kept_repos
    }

    print(f"\nKept : {len(kept_repos)}")
    print(f"Skipped: {len(skipped_repos)}")

    # ----- Build filtered report (same structure) -----
    # Pass 1: collect all matches per repo to find the earliest created_at
    repo_earliest: dict[str, str] = {}
    for source in report.get("sources", []):
        for m in source.get("matches", []):
            if m["repo_name"] not in kept_repos:
                continue
            ca = m.get("created_at", "")
            if ca:
                if m["repo_name"] not in repo_earliest or ca < repo_earliest[m["repo_name"]]:
                    repo_earliest[m["repo_name"]] = ca

    # Pass 2: build filtered sources, overwriting created_at with the earliest
    # date for that repo and preserving the original in file_created_at
    filtered_sources = []
    for source in report.get("sources", []):
        filtered_matches = []
        for m in source.get("matches", []):
            if m["repo_name"] not in kept_repos:
                continue
            lang = repo_languages[m["repo_name"]]
            enriched = {
                **m,
                "file_created_at": m.get("created_at", ""),
                "created_at": repo_earliest.get(m["repo_name"], m.get("created_at", "")),
                "language": lang,
                "nicad_language": SUPPORTED_LANGUAGES[lang],
            }
            filtered_matches.append(enriched)
        filtered_source = {**source}
        filtered_source["matches"] = filtered_matches
        filtered_source["total_md_files_with_match"] = len(filtered_matches)
        filtered_sources.append(filtered_source)

    filtered_report = {
        **report,
        "generated_at": NOW.isoformat(),
        "filter_applied": {
            "criterion": "primary GitHub language in NiCad-supported set",
            "supported_languages": SUPPORTED_LANGUAGES,
            "original_unique_repos": total,
            "kept": len(kept_repos),
            "skipped": len(skipped_repos),
        },
        "sources": filtered_sources,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(filtered_report, f, indent=2, ensure_ascii=False)
    print(f"\n[OK] Filtered report → {OUTPUT_PATH}")

    # ----- Build skipped repos report -----
    skipped_list = sorted(
        [
            {"repo_name": r, "language": repo_languages[r]}
            for r in skipped_repos
        ],
        key=lambda x: x["repo_name"],
    )

    skipped_report = {
        "generated_at": NOW.isoformat(),
        "description": (
            "Repositories removed from clone_terms_report.json because "
            "their primary GitHub language is not supported by NiCad."
        ),
        "supported_languages": SUPPORTED_LANGUAGES,
        "total_skipped": len(skipped_list),
        "total_kept": len(kept_repos),
        "skipped_repos": skipped_list,
    }

    with open(SKIPPED_PATH, "w", encoding="utf-8") as f:
        json.dump(skipped_report, f, indent=2, ensure_ascii=False)
    print(f"[OK] Skipped repos  → {SKIPPED_PATH}")


if __name__ == "__main__":
    main()
