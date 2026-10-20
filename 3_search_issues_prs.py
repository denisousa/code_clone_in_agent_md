"""
For every repository that had a match in clone_terms_report.json,
search GitHub for Issues and Pull Requests that mention code-clone /
code-duplication terms.

Workflow:
  1. Load clone_terms_report.json and extract unique repo_names.
  2. Print the full list of matched repos.
  3. For each repo, query the GitHub Search Issues API with two batches of
     CLONE_TERMS using the `repo:owner/repo` qualifier.
  4. Deduplicate across batches by item id.
  5. Save full results to ai_config_results/issues_prs_report.json.

Requires GITHUB_TOKEN in environment (or .env file).
Search API rate limit: 30 req/min (authenticated) → keep DELAY >= 2 s.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPORT_PATH = Path("ai_config_results/clone_terms_report.json")
OUTPUT_PATH = Path("ai_config_results/issues_prs_report.json")

# Terms split into two batches so each search query stays short.
# 2 API calls per repo.
SEARCH_TERM_BATCHES: list[list[str]] = [
    [
        "duplicate code",
        "duplicated code",
        "code duplication",
        "logic duplication",
        "duplicated logic",
        "copy-paste",
        "copy-pasted",
    ],
    [
        "repeated code",
        "DRY principle",
        "avoid duplication",
        "reused code",
        "code reuse",
        "code sharing",
    ],
]

SEARCH_API = "https://api.github.com/search/issues"
PER_PAGE = 100
DELAY_BETWEEN_REQUESTS = 2.2   # seconds — stays under 30 req/min limit
MAX_PAGES = 10                  # cap at 1 000 results per batch per repo


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

def build_headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        print(
            "[WARNING] GITHUB_TOKEN not set. "
            "Unauthenticated search limit: 10 req/min.\n"
        )
    return headers


def handle_rate_limit(response: requests.Response) -> None:
    reset_ts = int(response.headers.get("X-RateLimit-Reset", time.time() + 60))
    wait = max(reset_ts - time.time(), 0) + 5
    print(f"  [RATE LIMIT] Waiting {wait:.0f}s ...")
    time.sleep(wait)


def search_issues_batch(
    repo: str,
    terms: list[str],
    headers: dict,
) -> list[dict]:
    """
    Search issues + PRs in *repo* that mention any of *terms*.
    Returns raw GitHub search-result items, deduplicated by id.
    """
    quoted = " OR ".join(f'"{t}"' for t in terms)
    q = f"repo:{repo} {quoted}"

    seen_ids: set[int] = set()
    items: list[dict] = []
    page = 1

    while page <= MAX_PAGES:
        params = {"q": q, "per_page": PER_PAGE, "page": page}

        while True:
            time.sleep(DELAY_BETWEEN_REQUESTS)
            try:
                resp = requests.get(
                    SEARCH_API, headers=headers, params=params, timeout=20
                )
            except requests.RequestException as exc:
                print(f"    [REQUEST ERROR] {exc}")
                return items

            if resp.status_code in (429, 403) and "rate limit" in resp.text.lower():
                handle_rate_limit(resp)
                continue

            if resp.status_code != 200:
                print(f"    [HTTP {resp.status_code}] {resp.text[:120]}")
                return items

            data = resp.json()
            page_items = data.get("items", [])

            for item in page_items:
                if item["id"] not in seen_ids:
                    seen_ids.add(item["id"])
                    items.append(item)

            # Stop if this was the last page
            if len(page_items) < PER_PAGE:
                break

            page += 1

    return items


# ---------------------------------------------------------------------------
# Data formatting
# ---------------------------------------------------------------------------

def format_item(item: dict) -> dict:
    """Extract relevant fields from a raw GitHub issue/PR search result."""
    is_pr = "pull_request" in item
    return {
        "type": "pull_request" if is_pr else "issue",
        "number": item.get("number"),
        "title": item.get("title"),
        "state": item.get("state"),
        "html_url": item.get("html_url"),
        "user": item.get("user", {}).get("login"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "closed_at": item.get("closed_at"),
        "comments": item.get("comments", 0),
        "labels": [lb["name"] for lb in item.get("labels", [])],
        "body_excerpt": (item.get("body") or "")[:500],
    }


# ---------------------------------------------------------------------------
# Report loading
# ---------------------------------------------------------------------------

def load_matched_repos(report_path: Path) -> list[str]:
    """Return sorted unique repo_names that had at least one match."""
    with report_path.open(encoding="utf-8") as fh:
        report = json.load(fh)

    repos: set[str] = set()
    for source in report.get("sources", []):
        for match in source.get("matches", []):
            repo = match.get("repo_name", "").strip()
            if repo:
                repos.add(repo)

    return sorted(repos)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    start = perf_counter()
    headers = build_headers()

    repos = load_matched_repos(REPORT_PATH)

    # --- Print matched repo list ---
    print("=" * 60)
    print(f"  Repositories with matches ({len(repos)} total)")
    print("=" * 60)
    for repo in repos:
        print(f"  {repo}")
    print("=" * 60)

    n_batches = len(SEARCH_TERM_BATCHES)
    est_requests = len(repos) * n_batches
    est_sec = est_requests * DELAY_BETWEEN_REQUESTS
    est_min, est_s = divmod(est_sec, 60)
    print(f"\n  API calls (estimate): {est_requests}  (~{int(est_min)}m {int(est_s)}s)")
    print("=" * 60)

    output: list[dict] = []

    for i, repo in enumerate(repos, start=1):
        print(f"\n[{i}/{len(repos)}] {repo}")

        seen_ids: set[int] = set()
        all_raw: list[dict] = []

        for batch_idx, terms in enumerate(SEARCH_TERM_BATCHES, start=1):
            print(f"  Batch {batch_idx}/{n_batches} ...")
            raw_items = search_issues_batch(repo, terms, headers)
            new = 0
            for item in raw_items:
                if item["id"] not in seen_ids:
                    seen_ids.add(item["id"])
                    all_raw.append(item)
                    new += 1
            print(f"  → {len(raw_items)} returned, {new} new (running total: {len(all_raw)})")

        formatted = [format_item(item) for item in all_raw]
        issues = [x for x in formatted if x["type"] == "issue"]
        prs    = [x for x in formatted if x["type"] == "pull_request"]

        print(f"  Issues: {len(issues)}  |  PRs: {len(prs)}")

        output.append({
            "repo_name": repo,
            "total_issues": len(issues),
            "total_prs": len(prs),
            "issues": issues,
            "pull_requests": prs,
        })

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_repos": len(repos),
        "total_issues": sum(r["total_issues"] for r in output),
        "total_prs":    sum(r["total_prs"]    for r in output),
        "repositories": output,
    }

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n{'='*60}")
    print(f"  [SAVED] {OUTPUT_PATH}")
    print(f"  Repos processed : {len(repos)}")
    print(f"  Total issues    : {result['total_issues']}")
    print(f"  Total PRs       : {result['total_prs']}")

    elapsed = perf_counter() - start
    m, s = divmod(elapsed, 60)
    print(f"  Runtime         : {int(m)}m {s:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
