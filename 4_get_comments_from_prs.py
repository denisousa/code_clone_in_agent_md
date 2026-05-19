import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
DEFAULT_REPORT_PATH = Path("ai_config_results/clone_terms_report_filtered.json")
DEFAULT_OUTPUT_DIR = Path("results/prs")

HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "pr-comments-collector",
}

if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

# Number of CLONE_TERMS grouped into each GitHub Search query.
# Larger batches = fewer API calls, but risk hitting the query-length limit.
SEARCH_BATCH_SIZE = 5

CLONE_TERMS: list[str] = [
    "duplicate code",
    "duplicated code",
    "code duplication",
    "code redundancy",
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
    "code clone",
    "code cloning",
    "library reuse",
    "API reuse",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch pull requests for repositories listed in the filtered report, "
            "keep only PRs that mention code duplication or code cloning, and save "
            "their content to disk."
        )
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Path to clone_terms_report_filtered.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where PR folders will be created.",
    )
    parser.add_argument(
        "--repo-name",
        help="Optional owner/repo filter. When omitted, all repositories are processed.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional limit for the number of PRs to download.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers for fetching PR bundles (default: 4).",
    )
    return parser.parse_args()


def parse_github_datetime(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


def github_request(url: str) -> requests.Response:
    response = requests.get(url, headers=HEADERS, timeout=30)

    if response.status_code >= 400:
        raise RuntimeError(
            f"Error {response.status_code} while accessing {url}:\n{response.text}"
        )

    return response


def iterate_paginated_list(url: str):
    next_url = url

    while next_url:
        response = github_request(next_url)
        data = response.json()

        if not isinstance(data, list):
            raise RuntimeError(f"Expected a list response from {next_url}.")

        for item in data:
            yield item

        next_url = response.links.get("next", {}).get("url")


def github_get_json(url: str):
    return github_request(url).json()


def iterate_search_results(url: str):
    """Paginate through GitHub Search API results (returns {total_count, items})."""
    next_url = url

    while next_url:
        response = github_request(next_url)
        data = response.json()
        for item in data.get("items", []):
            yield item
        next_url = response.links.get("next", {}).get("url")


def search_merged_prs_with_terms(
    owner: str,
    repo: str,
    created_since: datetime,
    limit: int | None = None,
) -> list[int]:
    """
    Use the GitHub Search API to find merged PR numbers that mention any of
    the CLONE_TERMS. Groups terms into batches to keep queries short.
    Returns a deduplicated, sorted list of PR numbers.
    """
    since_date = created_since.strftime("%Y-%m-%d")
    pr_numbers: set[int] = set()

    for i in range(0, len(CLONE_TERMS), SEARCH_BATCH_SIZE):
        batch = CLONE_TERMS[i : i + SEARCH_BATCH_SIZE]
        terms_query = " OR ".join(f'"{term}"' for term in batch)
        query = (
            f"repo:{owner}/{repo} is:pr is:merged "
            f"created:>={since_date} {terms_query}"
        )
        url = (
            "https://api.github.com/search/issues"
            f"?q={requests.utils.quote(query)}&per_page=100"
        )
        for item in iterate_search_results(url):
            pr_numbers.add(item["number"])
            if limit is not None and len(pr_numbers) >= limit:
                return sorted(pr_numbers)

    return sorted(pr_numbers)


def load_projects(report_path: Path) -> dict[str, dict]:
    with report_path.open("r", encoding="utf-8") as file:
        report = json.load(file)

    projects: dict[str, dict] = {}

    for source in report.get("sources", []):
        for match in source.get("matches", []):
            repo_name = (match.get("repo_name") or "").strip()
            created_at = (match.get("created_at") or "").strip()

            if not repo_name or not created_at:
                continue

            existing = projects.get(repo_name)
            if existing is None or created_at < existing["created_at"]:
                projects[repo_name] = {
                    "repo_name": repo_name,
                    "created_at": created_at,
                    "source_csv": source.get("csv"),
                    "sample_file_path": match.get("file_path"),
                    "sample_file_created_at": match.get("file_created_at"),
                }

    if not projects:
        raise RuntimeError(f"No projects with repo_name/created_at found in {report_path}.")

    return projects


def select_projects(projects: dict[str, dict], repo_name: str | None) -> list[dict]:
    if repo_name:
        project = projects.get(repo_name)
        if project is None:
            raise RuntimeError(f"Repository {repo_name} was not found in the filtered report.")
        return [project]

    return [projects[name] for name in sorted(projects)]



def fetch_pr_bundle(owner: str, repo: str, pr_number: int) -> dict:
    base_url = f"https://api.github.com/repos/{owner}/{repo}"
    pr = github_get_json(f"{base_url}/pulls/{pr_number}")
    issue_comments = list(
        iterate_paginated_list(f"{base_url}/issues/{pr_number}/comments?per_page=100")
    )
    review_comments = list(
        iterate_paginated_list(f"{base_url}/pulls/{pr_number}/comments?per_page=100")
    )
    reviews = list(
        iterate_paginated_list(f"{base_url}/pulls/{pr_number}/reviews?per_page=100")
    )
    commits = list(
        iterate_paginated_list(f"{base_url}/pulls/{pr_number}/commits?per_page=100")
    )

    return {
        "pr": pr,
        "issue_comments": issue_comments,
        "review_comments": review_comments,
        "reviews": reviews,
        "commits": commits,
    }


def collect_searchable_text(bundle: dict) -> list[str]:
    pr = bundle["pr"]
    texts = [
        pr.get("title") or "",
        pr.get("body") or "",
    ]

    for comment in bundle["issue_comments"]:
        texts.append(comment.get("body") or "")

    for review in bundle["reviews"]:
        texts.append(review.get("body") or "")

    for comment in bundle["review_comments"]:
        texts.append(comment.get("body") or "")
        texts.append(comment.get("diff_hunk") or "")

    for commit in bundle["commits"]:
        texts.append(commit.get("commit", {}).get("message") or "")

    return [text for text in texts if text.strip()]


def find_duplication_mentions(bundle: dict) -> list[dict]:
    seen_excerpts: set[str] = set()
    matches: list[dict] = []

    for text in collect_searchable_text(bundle):
        normalized_text = " ".join(text.split())
        lower_text = normalized_text.lower()
        for term in CLONE_TERMS:
            if term.lower() in lower_text:
                excerpt = normalized_text[:400]
                if excerpt not in seen_excerpts:
                    seen_excerpts.add(excerpt)
                    matches.append({"term": term, "excerpt": excerpt})
                break

    return matches


def build_pr_text(bundle: dict) -> str:
    pr = bundle["pr"]
    issue_comments = bundle["issue_comments"]
    review_comments = bundle["review_comments"]
    reviews = bundle["reviews"]
    commits = bundle["commits"]

    text_parts = []

    text_parts.append("# Pull Request")
    text_parts.append(f"URL: {pr.get('html_url')}")
    text_parts.append(f"Number: {pr.get('number')}")
    text_parts.append(f"Title: {pr.get('title')}")
    text_parts.append(f"State: {pr.get('state')}")
    text_parts.append(f"Author: {pr.get('user', {}).get('login')}")
    text_parts.append(f"Created at: {pr.get('created_at')}")
    text_parts.append(f"Updated at: {pr.get('updated_at')}")
    text_parts.append(f"Merged at: {pr.get('merged_at')}")
    text_parts.append(f"Source branch: {pr.get('head', {}).get('ref')}")
    text_parts.append(f"Target branch: {pr.get('base', {}).get('ref')}")

    text_parts.append("\n## PR Description")
    text_parts.append(pr.get("body") or "")

    text_parts.append("\n## General Conversation Comments")
    if issue_comments:
        for comment in issue_comments:
            text_parts.append("---")
            text_parts.append(f"Author: {comment.get('user', {}).get('login')}")
            text_parts.append(f"Created at: {comment.get('created_at')}")
            text_parts.append(f"Updated at: {comment.get('updated_at')}")
            text_parts.append(comment.get("body") or "")
    else:
        text_parts.append("No general conversation comments found.")

    text_parts.append("\n## Reviews")
    if reviews:
        for review in reviews:
            text_parts.append("---")
            text_parts.append(f"Author: {review.get('user', {}).get('login')}")
            text_parts.append(f"State: {review.get('state')}")
            text_parts.append(f"Submitted at: {review.get('submitted_at')}")
            text_parts.append(review.get("body") or "")
    else:
        text_parts.append("No reviews found.")

    text_parts.append("\n## Code Review Comments")
    if review_comments:
        for comment in review_comments:
            text_parts.append("---")
            text_parts.append(f"Author: {comment.get('user', {}).get('login')}")
            text_parts.append(f"File: {comment.get('path')}")
            text_parts.append(
                f"Line: {comment.get('line') or comment.get('original_line')}"
            )
            text_parts.append(f"Created at: {comment.get('created_at')}")
            text_parts.append("Diff snippet:")
            text_parts.append(comment.get("diff_hunk") or "")
            text_parts.append("Comment:")
            text_parts.append(comment.get("body") or "")
    else:
        text_parts.append("No code review comments found.")

    text_parts.append("\n## Commits")
    if commits:
        for commit in commits:
            text_parts.append("---")
            text_parts.append(f"SHA: {commit.get('sha')}")
            text_parts.append(
                f"Author: {commit.get('commit', {}).get('author', {}).get('name')}"
            )
            text_parts.append(f"Message: {commit.get('commit', {}).get('message')}")
    else:
        text_parts.append("No commits found.")

    return "\n".join(text_parts)


def write_json(path: Path, data) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def write_text(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8") as file:
        file.write(content)


def save_pr_bundle(
    output_dir: Path,
    project: dict,
    bundle: dict,
    duplication_mentions: list[str],
) -> Path:
    repo_name = project["repo_name"]
    owner, repo = repo_name.split("/", maxsplit=1)
    repo_dir = output_dir / f"{owner}_{repo}"
    pr_number = bundle["pr"]["number"]
    pr_dir = repo_dir / str(pr_number)
    pr_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "repo_name": repo_name,
        "repo_created_at": project["created_at"],
        "source_csv": project.get("source_csv"),
        "sample_file_path": project.get("sample_file_path"),
        "sample_file_created_at": project.get("sample_file_created_at"),
        "pr_number": pr_number,
        "pr_url": bundle["pr"].get("html_url"),
        "duplication_mentions": duplication_mentions,
    }

    write_json(pr_dir / "metadata.json", metadata)
    write_json(pr_dir / "pr.json", bundle["pr"])
    write_json(pr_dir / "issue_comments.json", bundle["issue_comments"])
    write_json(pr_dir / "review_comments.json", bundle["review_comments"])
    write_json(pr_dir / "reviews.json", bundle["reviews"])
    write_json(pr_dir / "commits.json", bundle["commits"])
    write_text(pr_dir / "complete_pr_text.md", build_pr_text(bundle))

    return pr_dir


def main() -> None:
    args = parse_args()
    projects = load_projects(args.report_path)
    selected_projects = select_projects(projects, args.repo_name)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    total_prs_seen = 0
    total_prs_saved = 0

    for project_index, project in enumerate(selected_projects, start=1):
        owner, repo = project["repo_name"].split("/", maxsplit=1)
        created_since = parse_github_datetime(project["created_at"])

        print(
            f"[{project_index}/{len(selected_projects)}] Repository: {project['repo_name']}"
        )
        print(f"Repository creation date: {project['created_at']}")
        print("Searching for merged PRs with duplication/cloning terms...")

        pr_numbers = search_merged_prs_with_terms(
            owner=owner,
            repo=repo,
            created_since=created_since,
            limit=args.limit,
        )
        total_prs_seen += len(pr_numbers)
        print(f"PRs matched by search: {len(pr_numbers)}")

        def fetch_and_save(pr_number: int):
            bundle = fetch_pr_bundle(owner, repo, pr_number)
            duplication_mentions = find_duplication_mentions(bundle)
            if not duplication_mentions:
                return pr_number, None
            saved_dir = save_pr_bundle(args.output_dir, project, bundle, duplication_mentions)
            return pr_number, saved_dir

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(fetch_and_save, n): n for n in pr_numbers}
            for future in as_completed(futures):
                pr_number, saved_dir = future.result()
                if saved_dir:
                    total_prs_saved += 1
                    print(f"  Saved PR #{pr_number} -> {saved_dir}")
                else:
                    print(f"  Skipping PR #{pr_number}: terms not found in full text")

    print(f"Processed repositories: {len(selected_projects)}")
    print(f"PRs matched by search API: {total_prs_seen}")
    print(f"Saved PRs with duplication/cloning mentions: {total_prs_saved}")


if __name__ == "__main__":
    main()