import json
import os
import re
import threading
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import List, Dict, Any, Tuple

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

REPORT_PATH      = Path("ai_config_results/clone_terms_report.json")
CHECKPOINT_PATH  = Path("ai_config_results/search_prs_checkpoint.json")
OUTPUT_PATH      = Path("ai_config_results/search_prs_results.json")

# English-only terms for code cloning / duplication discussions
TERMS = [
    r"duplicate code",
    r"duplicated code",
    r"code duplication",
    r"logic duplication",
    r"duplicated logic",
    r"copy[- ]paste",
    r"copy[- ]pasted",
    r"repeated code",
    r"DRY principle",
    r"avoid duplication",
    r"reused code",
    r"code reuse",
    r"code sharing",
]

PATTERN = re.compile("|".join(TERMS), re.IGNORECASE)

BASE_URL = "https://api.github.com"

# Parallelism knobs – kept conservative to avoid GitHub secondary rate limits
MAX_PR_WORKERS   = 5  # PRs analyzed concurrently per repo
MAX_REPO_WORKERS = 2  # repos processed concurrently

# Shared lock so concurrent threads don't interleave their output
PRINT_LOCK = threading.Lock()


def print_repo_summary(repo_full: str, results: List[Dict[str, Any]]) -> None:
    """Print all valid PRs for a repo as soon as it finishes (thread-safe)."""
    with PRINT_LOCK:
        print(f"\n{'#' * 80}")
        if not results:
            print(f"DONE  {repo_full}  – no matches found")
        else:
            print(f"DONE  {repo_full}  – {len(results)} matching PR(s)")
            for result in sorted(results, key=lambda r: r["merged_at"] or ""):
                disc = result["discussion_type"].upper()
                ct   = result.get("commenter_types") or "—"
                terms = ", ".join(result.get("matched_terms", []))
                print(f"  PR #{result['number']} [{disc}] – {result['title']}")
                print(f"     Merged at       : {result['merged_at']}")
                print(f"     URL             : {result['url']}")
                print(f"     Terms matched   : {terms}")
                print(f"     Commenter types : {ct}")
                print(f"     Matches:")
                for m in result["matches"]:
                    author_tag = f" @{m['author']} [{m['author_type']}]" if m["author"] else ""
                    print(f"       [{m['location']}{author_tag}] '{m['term']}' → {m['excerpt']}")
        print(f"{'#' * 80}")


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=50)
    session.mount("https://", adapter)
    headers: Dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    session.headers.update(headers)
    return session


# Single shared session – connection pool is reused across threads
SESSION = _make_session()


def load_checkpoint() -> Dict[str, List[Dict[str, Any]]]:
    """Return previously saved results keyed by repo_full (empty list = processed, no matches)."""
    if CHECKPOINT_PATH.exists():
        with CHECKPOINT_PATH.open(encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_checkpoint(
    data: Dict[str, List[Dict[str, Any]]],
    lock: threading.Lock,
) -> None:
    """Atomically write the checkpoint file (write-then-rename)."""
    with lock:
        tmp = CHECKPOINT_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CHECKPOINT_PATH)


def save_results(
    all_results: Dict[str, List[Dict[str, Any]]],
    lock: threading.Lock,
) -> None:
    """Atomically write the final results file."""
    with lock:
        tmp = OUTPUT_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(OUTPUT_PATH)


def load_repos_from_report() -> List[str]:
    """Return unique repo names (owner/repo) from the clone terms report."""
    with REPORT_PATH.open(encoding="utf-8") as f:
        report = json.load(f)

    seen: set[str] = set()
    for source in report.get("sources", []):
        for match in source.get("matches", []):
            repo_name = match.get("repo_name", "").strip()
            if repo_name:
                seen.add(repo_name)
    return sorted(seen)


_RATE_LIMIT_MSGS = ("rate limit", "secondary rate", "api rate limit", "exceeded a secondary")


def _get_with_rate_limit_retry(
    url: str,
    params: Dict[str, Any] | None = None,
    max_attempts: int = 6,
) -> requests.Response:
    """GET *url*, sleeping and retrying automatically on rate-limit 403/429."""
    for attempt in range(max_attempts):
        response = SESSION.get(url, params=params)

        if response.status_code not in (403, 429):
            return response  # success or non-rate-limit error – let caller handle

        # Decide if this is really a rate-limit response
        remaining  = int(response.headers.get("X-RateLimit-Remaining", "1"))
        reset_ts   = int(response.headers.get("X-RateLimit-Reset", "0"))
        try:
            message = response.json().get("message", "").lower()
        except Exception:
            message = ""

        is_rate_limit = (
            response.status_code == 429
            or remaining == 0
            or any(s in message for s in _RATE_LIMIT_MSGS)
        )

        if not is_rate_limit:
            return response  # genuine 403 Forbidden – caller will raise_for_status

        if reset_ts:
            wait = max(reset_ts - int(time.time()) + 5, 10)
        else:
            wait = min(30 * 2 ** attempt, 600)  # exponential: 30s, 60s, 120s … max 10 min

        with PRINT_LOCK:
            print(
                f"\n  [RATE LIMIT] HTTP {response.status_code} – "
                f"waiting {wait}s (attempt {attempt + 1}/{max_attempts}) …"
            )
        time.sleep(wait)

    return response  # return last response after exhausting retries


def github_get(url: str, params: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    results = []
    while url:
        response = _get_with_rate_limit_retry(url, params)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            results.extend(data)
        else:
            results.append(data)
        url = response.links.get("next", {}).get("url")
        params = None
    return results


def find_matches_in_text(
    location: str,
    text: str | None,
    author: str | None = None,
    author_type: str | None = None,
) -> List[Dict[str, Any]]:
    """Return structured match entries for every term hit in *text*."""
    if not text:
        return []
    matches = []
    for m in PATTERN.finditer(text):
        start = max(m.start() - 50, 0)
        end = min(m.end() + 50, len(text))
        excerpt = text[start:end].replace("\n", " ")
        matches.append({
            "location":    location,
            "author":      author,
            "author_type": author_type,
            "term":        m.group(0).lower(),
            "excerpt":     f"...{excerpt}...",
        })
    return matches


def get_author_type(user: Dict[str, Any] | None) -> str:
    """Classify a GitHub user as 'bot' or 'human'."""
    if not user:
        return "unknown"
    if user.get("type") == "Bot":
        return "bot"
    login = user.get("login", "")
    if "[bot]" in login or login.endswith("-bot"):
        return "bot"
    return "human"


def get_merged_pull_requests(owner: str, repo: str) -> List[Dict[str, Any]]:
    url = f"{BASE_URL}/repos/{owner}/{repo}/pulls"
    all_prs = github_get(url, params={
        "state": "closed",
        "per_page": 100,
        "sort": "updated",
        "direction": "desc",
    })
    return [pr for pr in all_prs if pr.get("merged_at") is not None]


def get_issue_comments(owner: str, repo: str, pr_number: int) -> List[Dict[str, Any]]:
    url = f"{BASE_URL}/repos/{owner}/{repo}/issues/{pr_number}/comments"
    return github_get(url, params={"per_page": 100})


def get_review_comments(owner: str, repo: str, pr_number: int) -> List[Dict[str, Any]]:
    url = f"{BASE_URL}/repos/{owner}/{repo}/pulls/{pr_number}/comments"
    return github_get(url, params={"per_page": 100})


def get_reviews(owner: str, repo: str, pr_number: int) -> List[Dict[str, Any]]:
    url = f"{BASE_URL}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
    return github_get(url, params={"per_page": 100})


def analyze_pr(owner: str, repo: str, pr: Dict[str, Any]) -> Dict[str, Any] | None:
    pr_number = pr["number"]
    all_matches: List[Dict[str, Any]] = []

    # ── Primary sources (title + opening body) ──────────────────────────────
    all_matches += find_matches_in_text("PR title", pr.get("title"))
    all_matches += find_matches_in_text("PR body",  pr.get("body"))

    # ── Fetch 3 comment sources in parallel ──────────────────────────────────
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_issue   = ex.submit(get_issue_comments,  owner, repo, pr_number)
        f_review  = ex.submit(get_review_comments, owner, repo, pr_number)
        f_reviews = ex.submit(get_reviews,          owner, repo, pr_number)
        issue_comments  = f_issue.result()
        review_comments = f_review.result()
        reviews         = f_reviews.result()

    for comment in issue_comments:
        user = comment.get("user") or {}
        all_matches += find_matches_in_text(
            "General comment",
            comment.get("body"),
            author=user.get("login"),
            author_type=get_author_type(user),
        )
    for comment in review_comments:
        user = comment.get("user") or {}
        all_matches += find_matches_in_text(
            "Review comment",
            comment.get("body"),
            author=user.get("login"),
            author_type=get_author_type(user),
        )
    for review in reviews:
        user = review.get("user") or {}
        all_matches += find_matches_in_text(
            "Review",
            review.get("body"),
            author=user.get("login"),
            author_type=get_author_type(user),
        )

    if not all_matches:
        return None

    # ── Discussion type: primary / secondary / both ───────────────────────────
    # Primary = match appears in the PR title only.
    # Secondary = match appears anywhere else (body, comments, reviews).
    has_primary   = any(m["location"] == "PR title" for m in all_matches)
    has_secondary = any(m["location"] != "PR title" for m in all_matches)
    if has_primary and has_secondary:
        discussion_type = "both"
    elif has_primary:
        discussion_type = "primary"
    else:
        discussion_type = "secondary"

    # ── Unique matched terms ──────────────────────────────────────────────────
    matched_terms = sorted({m["term"] for m in all_matches})

    # ── Commenter types (secondary sources = everything except PR title) ──────
    comment_author_types = {
        m["author_type"]
        for m in all_matches
        if m["location"] != "PR title" and m["author_type"]
    }
    if "human" in comment_author_types and "bot" in comment_author_types:
        commenter_types: str | None = "both"
    elif "human" in comment_author_types:
        commenter_types = "human"
    elif "bot" in comment_author_types:
        commenter_types = "bot"
    else:
        commenter_types = None

    return {
        "number":           pr_number,
        "title":            pr.get("title"),
        "url":              pr.get("html_url"),
        "merged_at":        pr.get("merged_at"),
        "discussion_type":  discussion_type,
        "matched_terms":    matched_terms,
        "commenter_types":  commenter_types,
        "matches":          all_matches,
    }


def process_repo(repo_full: str) -> Tuple[str, List[Dict[str, Any]]]:
    owner, repo = repo_full.split("/", 1)
    print(f"\n[{repo_full}] Fetching merged PRs ...")
    try:
        prs = get_merged_pull_requests(owner, repo)
    except requests.HTTPError as exc:
        print(f"  [ERROR] {exc}")
        return repo_full, []

    total = len(prs)
    print(f"  {total} merged PRs found – analyzing in parallel ...")

    results: List[Dict[str, Any]] = []
    done = 0

    with ThreadPoolExecutor(max_workers=MAX_PR_WORKERS) as ex:
        futures = {ex.submit(analyze_pr, owner, repo, pr): pr["number"] for pr in prs}
        for fut in as_completed(futures):
            done += 1
            with PRINT_LOCK:
                print(f"  [{done}/{total}] PR #{futures[fut]} analyzed", end="\r")
            try:
                result = fut.result()
                if result:
                    results.append(result)
            except Exception as exc:
                with PRINT_LOCK:
                    print(f"\n  [WARN] PR #{futures[fut]}: {exc}")

    print_repo_summary(repo_full, results)
    return repo_full, results


def main():
    repos = [r for r in load_repos_from_report() if "/" in r]
    print(f"Repositories with code-clone config files: {len(repos)}")

    checkpoint = load_checkpoint()
    pending = [r for r in repos if r not in checkpoint]
    if len(checkpoint) > 0:
        print(f"  Checkpoint loaded – {len(checkpoint)} repo(s) already done, {len(pending)} remaining.")

    # all_results starts populated with previously saved matches
    all_results: Dict[str, List[Dict[str, Any]]] = {
        k: v for k, v in checkpoint.items() if v
    }

    ck_lock = threading.Lock()

    def _process_and_checkpoint(repo_full: str) -> Tuple[str, List[Dict[str, Any]]]:
        repo_full, results = process_repo(repo_full)
        checkpoint[repo_full] = results
        save_checkpoint(checkpoint, ck_lock)
        if results:
            all_results[repo_full] = results
            save_results(all_results, ck_lock)
        return repo_full, results

    with ThreadPoolExecutor(max_workers=MAX_REPO_WORKERS) as ex:
        futures = {ex.submit(_process_and_checkpoint, r): r for r in pending}
        for fut in as_completed(futures):
            fut.result()  # surface exceptions

    if not all_results:
        print("No merged PRs found discussing code cloning or duplication.")
        return

    total = sum(len(v) for v in all_results.values())
    print(f"\nResults saved to {OUTPUT_PATH}")
    print(f"Total: {total} matching PR(s) across {len(all_results)} repo(s).")


if __name__ == "__main__":
    main()