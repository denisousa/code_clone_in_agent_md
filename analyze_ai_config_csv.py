"""
Analyze all AI_CONFIG CSV files (commands, context_files, mcp, skills, subagents)
to identify .md files that mention code-clone / code-duplication related terms.

Workflow:
  1. For each configured CSV source, load the file and filter rows whose file
     path ends with .md.
  2. Convert each github_link to a raw-content URL and fetch the file text.
  3. Apply a case-insensitive regex for every CLONE_TERM.
  4. Collect per-file statistics (matched terms, counts, snippets).
  5. Write detailed results to clone_terms_report.json.
  6. Write a summary analysis to clone_terms_analysis.json.

Requires GITHUB_TOKEN in environment (or .env file) to avoid rate-limiting.
"""

import csv
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AI_CONFIG_DIR = Path("ai_config")

# Maps each CSV filename to the column that holds the file path.
# CSVs without a file-path column (commits.csv, repos.csv) are omitted.
CSV_SOURCES: dict[str, str] = {
    "commands.csv":      "command",
    "context_files.csv": "context_file",
    "mcp.csv":           "mcp",
    "skills.csv":        "skills.md",
    "subagents.csv":     "subagent",
}

RESULTS_DIR   = Path("ai_config_results")
REPORT_PATH   = RESULTS_DIR / "clone_terms_report.json"
ANALYSIS_PATH = RESULTS_DIR / "clone_terms_analysis.json"

CLONE_TERMS: list[str] = [
    '"duplicate code"',
    '"duplicated code"',
    '"code duplication"',
    '"code redundancy"',
    '"duplicated logic"',
    '"copy-paste"',
    '"copy-pasted"',
    '"repeated code"',
    '"DRY principle"',
    '"avoid duplication"',
]

# Strip surrounding quotes for regex matching and display
CLEAN_TERMS: list[str] = [t.strip('"') for t in CLONE_TERMS]

SNIPPET_CONTEXT = 80        # characters of context around each match
DELAY_BETWEEN_REQUESTS = 1  # seconds between GitHub API calls


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class FileRecord(NamedTuple):
    repo_name: str
    file_path: str
    github_link: str
    name: str
    language: str


class TermHit(NamedTuple):
    term: str
    count: int
    snippets: list[str]


class MatchResult(NamedTuple):
    record: FileRecord
    hits: list[TermHit]
    total_matches: int


# ---------------------------------------------------------------------------
# Step 1 – Load a CSV file
# ---------------------------------------------------------------------------

def load_csv(csv_path: Path) -> list[dict]:
    """Read all rows from a CSV file and return them as a list of dicts."""
    csv.field_size_limit(10 * 1024 * 1024)  # 10 MB — handles large commit messages
    rows: list[dict] = []
    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Step 2 – Filter .md records
# ---------------------------------------------------------------------------

def filter_md_records(rows: list[dict], file_col: str) -> list[FileRecord]:
    """Keep only rows whose file path (given column) ends with .md."""
    md_records: list[FileRecord] = []
    for row in rows:
        file_path: str = row.get(file_col, "").strip()
        if file_path.lower().endswith(".md"):
            md_records.append(
                FileRecord(
                    repo_name=row.get("repo_name", "").strip(),
                    file_path=file_path,
                    github_link=row.get("github_link", "").strip(),
                    name=row.get("name", "").strip(),
                    language=row.get("language", "").strip(),
                )
            )
    return md_records


# ---------------------------------------------------------------------------
# Step 3 – Convert github_link to raw content URL
# ---------------------------------------------------------------------------

def github_link_to_raw_url(github_link: str) -> str | None:
    """
    Convert a GitHub tree URL to a raw.githubusercontent.com URL.

    Example:
      https://github.com/owner/repo/tree/branch/path/to/file.md
      → https://raw.githubusercontent.com/owner/repo/branch/path/to/file.md
    """
    if not github_link:
        return None
    raw = github_link.replace("https://github.com/", "https://raw.githubusercontent.com/")
    raw = re.sub(r"/tree/", "/", raw, count=1)
    return raw


# ---------------------------------------------------------------------------
# Step 4 – Fetch file content
# ---------------------------------------------------------------------------

def build_headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    headers: dict = {"Accept": "application/vnd.github+json"}
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
    print(f"  [RATE LIMIT] Waiting {wait:.0f}s before retrying...")
    time.sleep(wait)


def fetch_raw_content(raw_url: str, headers: dict) -> str | None:
    """Fetch plain text from a raw.githubusercontent.com URL with retry on rate-limit."""
    while True:
        try:
            response = requests.get(raw_url, headers=headers, timeout=15)
        except requests.RequestException as exc:
            print(f"  [REQUEST ERROR] {exc}")
            return None

        if response.status_code == 200:
            return response.text

        if response.status_code in (429, 403) and "rate limit" in response.text.lower():
            handle_rate_limit(response)
            continue

        return None  # 404 or other non-retryable error


# ---------------------------------------------------------------------------
# Step 5 – Apply regex and extract statistics
# ---------------------------------------------------------------------------

def extract_snippets(text: str, term: str, context: int = SNIPPET_CONTEXT) -> list[str]:
    """Return a deduplicated list of text snippets around each match of *term*."""
    pattern = re.compile(re.escape(term), re.IGNORECASE)
    snippets: list[str] = []
    seen: set[str] = set()
    for match in pattern.finditer(text):
        start = max(0, match.start() - context)
        end = min(len(text), match.end() + context)
        snippet = "..." + text[start:end].replace("\n", " ").strip() + "..."
        if snippet not in seen:
            seen.add(snippet)
            snippets.append(snippet)
    return snippets


def apply_regex(text: str) -> list[TermHit]:
    """Return TermHit objects for every CLONE_TERM found in *text*."""
    hits: list[TermHit] = []
    for term in CLEAN_TERMS:
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        matches = pattern.findall(text)
        if matches:
            snippets = extract_snippets(text, term)
            hits.append(TermHit(term=term, count=len(matches), snippets=snippets))
    return hits


# ---------------------------------------------------------------------------
# Step 6 – Process a single CSV source
# ---------------------------------------------------------------------------

def process_csv(csv_name: str, file_col: str, headers: dict) -> dict:
    """
    Load, filter, fetch, and search one CSV file.
    Returns a dict with all data needed for both output files.
    """
    csv_path = AI_CONFIG_DIR / csv_name
    print(f"\n{'='*60}")
    print(f"  CSV: {csv_name}  (file column: '{file_col}')")
    print(f"{'='*60}")

    rows = load_csv(csv_path)
    print(f"  Total records: {len(rows)}")

    md_records = filter_md_records(rows, file_col)
    print(f"  .md records:   {len(md_records)}")

    results: list[MatchResult] = []

    for i, record in enumerate(md_records, start=1):
        raw_url = github_link_to_raw_url(record.github_link)
        if not raw_url:
            print(f"  [{i}/{len(md_records)}] SKIP (no github_link): {record.file_path}")
            continue

        print(f"  [{i}/{len(md_records)}] {record.repo_name} / {record.file_path}")

        content = fetch_raw_content(raw_url, headers)
        if content is None:
            print(f"    → Could not fetch content.")
            time.sleep(DELAY_BETWEEN_REQUESTS)
            continue

        hits = apply_regex(content)
        if hits:
            total = sum(h.count for h in hits)
            results.append(MatchResult(record=record, hits=hits, total_matches=total))
            print(f"    → {len(hits)} term(s) matched, {total} total occurrence(s).")

        time.sleep(DELAY_BETWEEN_REQUESTS)

    return {
        "csv": csv_name,
        "total_records": len(rows),
        "total_md_records": len(md_records),
        "results": results,
    }


# ---------------------------------------------------------------------------
# Step 7 – Aggregate per-CSV statistics
# ---------------------------------------------------------------------------

def aggregate_stats(results: list[MatchResult]) -> dict:
    """Return term-file-count mapping and total matched files for a result set."""
    term_file_counts: dict[str, int] = {t: 0 for t in CLEAN_TERMS}
    for result in results:
        for hit in result.hits:
            term_file_counts[hit.term] += 1
    return {
        "total_md_files_with_match": len(results),
        "term_file_counts": term_file_counts,
        "top_terms": sorted(
            [{"term": t, "files": c} for t, c in term_file_counts.items() if c > 0],
            key=lambda x: x["files"],
            reverse=True,
        ),
    }


# ---------------------------------------------------------------------------
# Step 8 – Save clone_terms_report.json  (detailed)
# ---------------------------------------------------------------------------

def save_report(csv_data: list[dict], report_path: Path) -> None:
    """Write one entry per CSV with all matched file details."""
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": [
            {
                "csv": entry["csv"],
                "total_records": entry["total_records"],
                "total_md_records": entry["total_md_records"],
                "total_md_files_with_match": len(entry["results"]),
                "matches": [
                    {
                        "repo_name": r.record.repo_name,
                        "file_name": Path(r.record.file_path).name,
                        "file_path": r.record.file_path,
                        "github_link": r.record.github_link,
                        "total_occurrences": r.total_matches,
                        "terms": [
                            {
                                "term": hit.term,
                                "count": hit.count,
                                "snippets": hit.snippets[:3],
                            }
                            for hit in r.hits
                        ],
                    }
                    for r in entry["results"]
                ],
            }
            for entry in csv_data
        ],
    }

    report_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[SAVED] Detailed report → {report_path}")


# ---------------------------------------------------------------------------
# Step 9 – Save clone_terms_analysis.json  (summary analysis)
# ---------------------------------------------------------------------------

def save_analysis(csv_data: list[dict], analysis_path: Path) -> None:
    """
    Write a summary analysis JSON with:
    - per-CSV: total rows, .md files count, matched files count, top terms
    - global: totals and overall term ranking
    """
    global_term_counts: dict[str, int] = {t: 0 for t in CLEAN_TERMS}
    global_total_records = 0
    global_total_md = 0
    global_total_matched = 0

    per_csv = []
    for entry in csv_data:
        stats = aggregate_stats(entry["results"])
        global_total_records += entry["total_records"]
        global_total_md      += entry["total_md_records"]
        global_total_matched += stats["total_md_files_with_match"]

        for term, count in stats["term_file_counts"].items():
            global_term_counts[term] += count

        per_csv.append({
            "csv": entry["csv"],
            "total_records_in_csv": entry["total_records"],
            "total_md_files": entry["total_md_records"],
            "md_files_with_match": stats["total_md_files_with_match"],
            "top_terms": stats["top_terms"],
        })

    global_top_terms = sorted(
        [{"term": t, "files": c} for t, c in global_term_counts.items() if c > 0],
        key=lambda x: x["files"],
        reverse=True,
    )

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "global_summary": {
            "total_records_across_all_csvs": global_total_records,
            "total_md_files_across_all_csvs": global_total_md,
            "total_md_files_with_match": global_total_matched,
            "top_terms_globally": global_top_terms,
        },
        "per_csv": per_csv,
    }

    analysis_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SAVED] Analysis summary → {analysis_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    headers = build_headers()

    RESULTS_DIR.mkdir(exist_ok=True)

    csv_data: list[dict] = []
    for csv_name, file_col in CSV_SOURCES.items():
        entry = process_csv(csv_name, file_col, headers)
        csv_data.append(entry)

    print(f"\n{'='*60}")
    print("  Saving output files ...")
    print(f"{'='*60}")
    save_report(csv_data, REPORT_PATH)
    save_analysis(csv_data, ANALYSIS_PATH)


if __name__ == "__main__":
    main()
