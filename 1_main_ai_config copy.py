"""
Analyze all AI_CONFIG CSV files (commands, context_files, mcp, skills, subagents)
to identify files that mention code-clone / code-duplication related terms.

Workflow:
  1. For each configured CSV source, load the file and filter rows.
  2. Build the local file path: repos_data/repos/{owner§repo}/{file_col_value}
  3. Read the file from disk.
  4. Apply a case-insensitive regex for every CLONE_TERM.
  5. Collect per-file statistics (matched terms, counts, snippets).
  6. Write detailed results to clone_terms_report.json.
  7. Write a summary analysis to clone_terms_analysis.json.
"""

import csv
import json
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AI_CONFIG_DIR  = Path("ai_config")
REPOS_CSV      = Path("ai_config/repos.csv")
REPOS_DATA_DIR = Path("ai_config/repos_data/repos")

# Maps each CSV filename to the column that holds the file path.
CSV_SOURCES: dict[str, str] = {
    "commands.csv":      "command",
    "context_files.csv": "context_file",
    "hooks.csv":         "hook",
    "mcp.csv":           "mcp",
    "rules.csv":         "rule",
    "settings.csv":      "settings",
    "skills.csv":        "skills.md",
    "subagents.csv":     "subagent",
}

RESULTS_DIR   = Path("ai_config_results")
REPORT_PATH   = RESULTS_DIR / "clone_terms_report.json"
ANALYSIS_PATH = RESULTS_DIR / "clone_terms_analysis.json"
FAILED_PATH   = RESULTS_DIR / "clone_terms_failed.json"

CLONE_TERMS: list[str] = [
    "duplicate code",
    "duplicated code",
    "code duplication",
    "logic duplication",
    "duplicated logic",
    "copy-paste",
    "copy-pasted",
    "repeated code",
    "DRY principle",
    "avoid duplication",
    "reused code",
    "code reuse",
    "code sharing",
]

# Adicionar resue and code reused

CLEAN_TERMS: list[str] = CLONE_TERMS

SNIPPET_CONTEXT = 80   # characters of context around each match


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class FileRecord(NamedTuple):
    repo_name: str
    file_path: str
    github_link: str
    name: str
    language: str
    commit_sha: str
    timestamp: str
    branch: str
    created_at: str
    num_commits: str
    is_empty: str
    first_commit_sha: str


class TermHit(NamedTuple):
    term: str
    count: int
    snippets: list[str]


class MatchResult(NamedTuple):
    record: FileRecord
    hits: list[TermHit]
    total_matches: int
    local_path: str


class FailedRecord(NamedTuple):
    csv: str
    repo_name: str
    file_path: str
    local_path: str
    reason: str  # "no_local_path" | "file_not_found" | "read_error"


# ---------------------------------------------------------------------------
# Step 0 – Load engineered repos
# ---------------------------------------------------------------------------

def load_engineered_repos(repos_path: Path) -> set[str]:
    """Return the set of repo_names where engineered_project is True."""
    engineered: set[str] = set()
    rows = load_csv(repos_path)
    for row in rows:
        if row.get("engineered_project", "").strip().lower() == "true":
            engineered.add(row.get("repo_name", "").strip())
    return engineered


# ---------------------------------------------------------------------------
# Step 1 – Load a CSV file
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
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

def filter_records(
    rows: list[dict],
    file_col: str,
    engineered_repos: set[str],
) -> list[FileRecord]:
    """Keep rows whose file-path column is non-empty and whose repo is an engineered project."""
    records: list[FileRecord] = []
    for row in rows:
        file_path: str = row.get(file_col, "").strip()
        repo_name: str = row.get("repo_name", "").strip()
        if file_path and repo_name in engineered_repos:
            records.append(
                FileRecord(
                    repo_name=row.get("repo_name", "").strip(),
                    file_path=file_path,
                    github_link=row.get("github_link", "").strip(),
                    name=row.get("name", "").strip(),
                    language=row.get("language", "").strip(),
                    commit_sha=row.get("last_commit_sha", "").strip(),
                    timestamp=row.get("timestamp", "").strip(),
                    branch=row.get("branch", "").strip(),
                    created_at=row.get("created_at", "").strip(),
                    num_commits=row.get("#commits", "").strip(),
                    is_empty=row.get("is_empty", "").strip(),
                    first_commit_sha=row.get("first_commit_sha", "").strip(),
                )
            )
    return records


# ---------------------------------------------------------------------------
# Step 3 – Build local file path
# ---------------------------------------------------------------------------

def repo_to_local_path(repo_name: str, file_path: str) -> Path | None:
    """
    Build the absolute local path for a config file.

    repo_name : "owner/repo"  →  folder name "owner§repo"
    file_path : value from the CSV file column (e.g. ".claude/skills.md")
    """
    if not repo_name or not file_path:
        return None
    folder = repo_name.replace("/", "§")
    return REPOS_DATA_DIR / folder / file_path


# ---------------------------------------------------------------------------
# Step 4 – Read local file
# ---------------------------------------------------------------------------

def read_local_file(path: Path) -> str | None:
    """Read and return file content, or None if not found / unreadable."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None
    except Exception as exc:
        print(f"  [READ ERROR] {path}: {exc}")
        return None


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

def process_csv(csv_name: str, file_col: str, engineered_repos: set[str]) -> dict:
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

    records = filter_records(rows, file_col, engineered_repos)
    print(f"  Processable records: {len(records)}")

    results: list[MatchResult] = []
    failed: list[FailedRecord] = []
    n_records = len(records)
    completed = 0

    for record in records:
            completed += 1
            local_path_obj = repo_to_local_path(record.repo_name, record.file_path)
            local_path = str(local_path_obj) if local_path_obj else ""
            content = read_local_file(local_path_obj) if local_path_obj else None

            if not local_path:
                print(f"  [{completed}/{n_records}] SKIP (no path): {record.file_path}")
                failed.append(FailedRecord(
                    csv=csv_name,
                    repo_name=record.repo_name,
                    file_path=record.file_path,
                    local_path="",
                    reason="no_local_path",
                ))
                continue

            print(f"  [{completed}/{n_records}] {record.repo_name} / {record.file_path}")

            if content is None:
                print(f"    → File not found locally.")
                failed.append(FailedRecord(
                    csv=csv_name,
                    repo_name=record.repo_name,
                    file_path=record.file_path,
                    local_path=local_path,
                    reason="file_not_found",
                ))
                continue

            hits = apply_regex(content)
            if hits:
                n_hits = sum(h.count for h in hits)
                results.append(MatchResult(record=record, hits=hits, total_matches=n_hits, local_path=local_path))
                print(f"    → {len(hits)} term(s) matched, {n_hits} total occurrence(s).")

    return {
        "csv": csv_name,
        "total_records": len(rows),
        "total_md_records": len(records),
        "results": results,
        "failed": failed,
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
                        "local_path": r.local_path,
                        "timestamp": r.record.timestamp,
                        "branch": r.record.branch,
                        "created_at": r.record.created_at,
                        "#commits": r.record.num_commits,
                        "is_empty": r.record.is_empty,
                        "first_commit_sha": r.record.first_commit_sha,
                        "last_commit_sha": r.record.commit_sha,
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
# Step 8b – Save clone_terms_failed.json
# ---------------------------------------------------------------------------

def save_failed_report(csv_data: list[dict], failed_path: Path) -> None:
    """Write all entries that could not be fetched to a dedicated JSON file."""
    all_failed: list[dict] = []
    for entry in csv_data:
        for f in entry.get("failed", []):
            all_failed.append({
                "csv":        f.csv,
                "repo_name":  f.repo_name,
                "file_path":  f.file_path,
                "local_path": f.local_path,
                "reason":     f.reason,
            })

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_failed": len(all_failed),
        "failed": all_failed,
    }
    failed_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SAVED] Failed URLs report  → {failed_path}  ({len(all_failed)} entries)")


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
# Startup report
# ---------------------------------------------------------------------------

def print_startup_report(engineered_repos: set[str]) -> int:
    """
    Print a pre-run summary: entry count per CSV (engineered repos only) and total,
    plus an estimated runtime at 1 s/entry.
    Returns the total number of entries to be processed.
    """
    col_width = max(len(name) for name in CSV_SOURCES) + 2
    rows_data: list[tuple[str, int]] = []

    for csv_name, file_col in CSV_SOURCES.items():
        csv_path = AI_CONFIG_DIR / csv_name
        rows = load_csv(csv_path)
        count = sum(
            1 for row in rows
            if row.get(file_col, "").strip()
            and row.get("repo_name", "").strip() in engineered_repos
        )
        rows_data.append((csv_name, count))

    total = sum(count for _, count in rows_data)

    print("=" * 60)
    print("  Pre-run summary")
    print("=" * 60)
    print(f"  {'CSV file':<{col_width}}  {'Entries':>14}")
    print(f"  {'-'*col_width}  {'-'*14}")
    for csv_name, count in rows_data:
        print(f"  {csv_name:<{col_width}}  {count:>14,}")
    print(f"  {'-'*col_width}  {'-'*14}")
    print(f"  {'TOTAL':<{col_width}}  {total:>14,}")
    print("=" * 60)
    return total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    start = perf_counter()

    engineered_repos = load_engineered_repos(REPOS_CSV)
    print(f"  Engineered repos loaded: {len(engineered_repos):,} from {REPOS_CSV}")

    print_startup_report(engineered_repos)

    RESULTS_DIR.mkdir(exist_ok=True)

    csv_data: list[dict] = []
    for csv_name, file_col in CSV_SOURCES.items():
        entry = process_csv(csv_name, file_col, engineered_repos)
        csv_data.append(entry)

    print(f"\n{'='*60}")
    print("  Saving output files ...")
    print(f"{'='*60}")
    save_report(csv_data, REPORT_PATH)
    save_failed_report(csv_data, FAILED_PATH)
    save_analysis(csv_data, ANALYSIS_PATH)

    elapsed = perf_counter() - start
    elapsed_min, elapsed_sec = divmod(elapsed, 60)
    print(f"\n{'='*60}")
    if elapsed_min:
        print(f"  Total runtime: {int(elapsed_min)}m {elapsed_sec:.1f}s")
    else:
        print(f"  Total runtime: {elapsed_sec:.1f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
