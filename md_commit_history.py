"""
Fetch the full commit history of every MD file found in clone_terms_report.json
and report whether those files have been modified over time.

For each file, the script calls:
  GET /repos/{owner}/{repo}/commits?path={file_path}

Outputs:
  ai_config_results/md_commit_history.json  – full commit history per file
  ai_config_results/md_commit_history.csv   – flat table, one row per commit

Run:
  python md_commit_history.py
"""

import csv
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPORT_PATH = Path("ai_config_results/clone_terms_report.json")
OUT_JSON = Path("ai_config_results/md_commit_history.json")
OUT_CSV = Path("ai_config_results/md_commit_history.csv")

# How many days without a new commit before a file is considered "stale"
STALE_THRESHOLD_DAYS = 90

MAX_WORKERS = 10               # concurrent threads fetching commit history
PER_PAGE = 100                 # max allowed by GitHub
_print_lock = threading.Lock() # thread-safe printing

NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        print(
            "[WARNING] GITHUB_TOKEN not set. "
            "Unauthenticated requests are limited to 60/hour.\n"
        )
    return headers


def handle_rate_limit(response: requests.Response) -> None:
    reset_ts = int(response.headers.get("X-RateLimit-Reset", time.time() + 60))
    wait = max(reset_ts - time.time(), 0) + 5
    with _print_lock:
        print(f"  [RATE LIMIT] Waiting {wait:.0f} s before retrying...")
    time.sleep(wait)


def get_with_retry(url: str, headers: dict, params: dict | None = None) -> requests.Response | None:
    while True:
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
        except requests.RequestException as exc:
            print(f"  [ERROR] Network error: {exc}")
            return None
        if resp.status_code in (429, 403) and "rate limit" in resp.text.lower():
            handle_rate_limit(resp)
            continue
        return resp


def fetch_commit_history(repo: str, file_path: str, headers: dict) -> list[dict]:
    """
    Return all commits that touched `file_path` in `repo`.
    Each item: {sha, author, date, message}
    """
    url = f"https://api.github.com/repos/{repo}/commits"
    commits: list[dict] = []
    page = 1

    while True:
        params = {"path": file_path, "per_page": PER_PAGE, "page": page}
        resp = get_with_retry(url, headers, params)

        if resp is None:
            break
        if resp.status_code == 404:
            print(f"  [404] Repo or path not found: {repo}/{file_path}")
            break
        if resp.status_code != 200:
            print(f"  [ERROR] HTTP {resp.status_code} for {repo}/{file_path}: {resp.text[:120]}")
            break

        data = resp.json()
        if not data:
            break

        for item in data:
            commit_info = item.get("commit", {})
            author_info = commit_info.get("author") or commit_info.get("committer") or {}
            commits.append({
                "sha": item.get("sha", "")[:12],
                "full_sha": item.get("sha", ""),
                "author": author_info.get("name", "unknown"),
                "date": author_info.get("date", ""),
                "message": commit_info.get("message", "").split("\n")[0][:120],
            })

        # If fewer than PER_PAGE results, we've reached the last page
        if len(data) < PER_PAGE:
            break

        page += 1

    return commits


def days_since(iso_date: str) -> int | None:
    """Return the number of days between iso_date and today."""
    if not iso_date:
        return None
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        return (NOW - dt).days
    except ValueError:
        return None


def analyse_history(file_record: dict, commits: list[dict]) -> dict:
    """
    Build a summary dict for one file entry.
    """
    created_at = file_record.get("created_at", "")
    last_modified = commits[0]["date"] if commits else file_record.get("timestamp", "")
    first_seen = commits[-1]["date"] if commits else created_at
    num_commits = len(commits)

    days_since_last = days_since(last_modified)
    was_ever_modified = num_commits > 1

    if days_since_last is None:
        activity_status = "unknown"
    elif days_since_last <= STALE_THRESHOLD_DAYS:
        activity_status = "active"
    else:
        activity_status = "stale"

    return {
        "repo_name": file_record["repo_name"],
        "file_name": file_record["file_name"],
        "file_path": file_record["file_path"],
        "source_csv": file_record.get("_source_csv", ""),
        "github_link": file_record.get("github_link", ""),
        "branch": file_record.get("branch", ""),
        "created_at": created_at,
        "first_commit_date": first_seen,
        "last_commit_date": last_modified,
        "total_commits": num_commits,
        "was_ever_modified": was_ever_modified,
        "days_since_last_commit": days_since_last,
        "activity_status": activity_status,   # active | stale | unknown
        "stale_threshold_days": STALE_THRESHOLD_DAYS,
        "matched_terms": [t["term"] for t in file_record.get("terms", [])],
        "commits": commits,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def collect_files_from_report(report_path: Path) -> list[dict]:
    """Flatten all matches from all sources in the report into a single list."""
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    files: list[dict] = []
    seen: set[str] = set()   # deduplicate by repo+path

    for source in report.get("sources", []):
        csv_name = source.get("csv", "")
        for match in source.get("matches", []):
            key = f"{match['repo_name']}|{match['file_path']}"
            if key in seen:
                continue
            seen.add(key)
            match["_source_csv"] = csv_name
            files.append(match)

    return files


def save_json(results: list[dict], path: Path) -> None:
    payload = {
        "generated_at": NOW.isoformat(),
        "reference_date": NOW.strftime("%Y-%m-%d"),
        "stale_threshold_days": STALE_THRESHOLD_DAYS,
        "total_files": len(results),
        "files": results,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"\n[OK] JSON saved → {path}")


def save_csv(results: list[dict], path: Path) -> None:
    fieldnames = [
        "repo_name", "file_name", "file_path", "source_csv",
        "branch", "created_at", "first_commit_date", "last_commit_date",
        "total_commits", "was_ever_modified", "days_since_last_commit",
        "activity_status", "matched_terms", "github_link",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in results:
            row_flat = dict(row)
            row_flat["matched_terms"] = "; ".join(row.get("matched_terms", []))
            writer.writerow(row_flat)
    print(f"[OK] CSV  saved → {path}")


def print_summary(results: list[dict]) -> None:
    active = sum(1 for r in results if r["activity_status"] == "active")
    stale = sum(1 for r in results if r["activity_status"] == "stale")
    unknown = sum(1 for r in results if r["activity_status"] == "unknown")
    never_modified = sum(1 for r in results if not r["was_ever_modified"])
    modified = sum(1 for r in results if r["was_ever_modified"])

    print("\n" + "=" * 60)
    print(f"  Summary  (reference date: {NOW.strftime('%Y-%m-%d')})")
    print("=" * 60)
    print(f"  Total files analysed : {len(results)}")
    print(f"  Never modified       : {never_modified}  (only 1 commit)")
    print(f"  Modified at least 1x : {modified}")
    print(f"  Active (≤{STALE_THRESHOLD_DAYS}d ago)    : {active}")
    print(f"  Stale  (>{STALE_THRESHOLD_DAYS}d ago)    : {stale}")
    print(f"  Status unknown       : {unknown}")
    print("=" * 60)

    if modified:
        print("\n  Files with most commits:")
        top = sorted(results, key=lambda r: r["total_commits"], reverse=True)[:10]
        for r in top:
            print(
                f"    {r['total_commits']:3d} commits  "
                f"{r['last_commit_date'][:10]}  "
                f"{r['repo_name']}  {r['file_path']}"
            )


def main() -> None:
    if not REPORT_PATH.exists():
        raise FileNotFoundError(f"Report not found: {REPORT_PATH}")

    headers = build_headers()
    files = collect_files_from_report(REPORT_PATH)

    total = len(files)
    print(f"Files to analyse: {total}  (workers: {MAX_WORKERS})")

    results: list[dict] = [None] * total   # pre-allocated to keep order
    counter = {"done": 0}

    def process(index: int, file_record: dict) -> tuple[int, dict]:
        repo = file_record["repo_name"]
        path = file_record["file_path"]
        commits = fetch_commit_history(repo, path, headers)
        summary = analyse_history(file_record, commits)
        with _print_lock:
            counter["done"] += 1
            print(
                f"[{counter['done']:3d}/{total}] {repo}  →  {path}  "
                f"({len(commits)} commit(s))"
            )
        return index, summary

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process, i, rec): i
            for i, rec in enumerate(files)
        }
        for future in as_completed(futures):
            idx, summary = future.result()
            results[idx] = summary

    save_json(results, OUT_JSON)
    save_csv(results, OUT_CSV)
    print_summary(results)


if __name__ == "__main__":
    main()
