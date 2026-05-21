import os
import requests
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # Optional, but recommended

HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "pr-text-extractor",
}

if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"


def parse_pr_url(pr_url: str):
    """
    Example:
    https://github.com/apache/struts/pull/1667
    """
    parsed = urlparse(pr_url)
    parts = parsed.path.strip("/").split("/")

    if len(parts) < 4 or parts[2] != "pull":
        raise ValueError(
            "Invalid PR URL. Use something like: https://github.com/owner/repo/pull/123"
        )

    owner = parts[0]
    repo = parts[1]
    pull_number = int(parts[3])

    return owner, repo, pull_number


def github_get(url: str):
    """
    Runs a GET request with automatic pagination.

    If the response is a list, returns all items from all pages.
    If the response is a single object, returns that object.
    """
    results = []
    current_url = url

    while current_url:
        response = requests.get(current_url, headers=HEADERS, timeout=30)

        if response.status_code >= 400:
            raise RuntimeError(
                f"Error {response.status_code} while accessing {current_url}:\n"
                f"{response.text}"
            )

        data = response.json()

        if isinstance(data, list):
            results.extend(data)
        else:
            return data

        current_url = response.links.get("next", {}).get("url")

    return results


def get_pr_text(pr_url: str):
    owner, repo, pr_number = parse_pr_url(pr_url)

    base_url = f"https://api.github.com/repos/{owner}/{repo}"

    pr = github_get(f"{base_url}/pulls/{pr_number}")
    issue_comments = github_get(f"{base_url}/issues/{pr_number}/comments")
    review_comments = github_get(f"{base_url}/pulls/{pr_number}/comments")
    reviews = github_get(f"{base_url}/pulls/{pr_number}/reviews")
    commits = github_get(f"{base_url}/pulls/{pr_number}/commits")

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
            text_parts.append(
                f"Message: {commit.get('commit', {}).get('message')}"
            )
    else:
        text_parts.append("No commits found.")

    return "\n".join(text_parts)


if __name__ == "__main__":
    pr_url = "https://github.com/apache/struts/pull/1667"

    full_text = get_pr_text(pr_url)

    output_file = "complete_pr_text.md"

    with open(output_file, "w", encoding="utf-8") as file:
        file.write(full_text)

    print(full_text)
    print(f"\nSaved PR text to: {output_file}")