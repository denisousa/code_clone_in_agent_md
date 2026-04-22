# Code Clone in AGENTS.md

Search GitHub for `AGENTS.md` files that mention code clone-related terms. Designed for research purposes — collecting real-world AI agent configuration files that address code duplication.

## How it works

1. For each term in `CLONE_TERMS`, queries the GitHub Code Search API for files named `AGENTS.md` containing that term.
2. Deduplicates results by URL (same file found via multiple terms) and by canonical path (removes forks with identical content).
3. Fetches the star count for each repository and discards those below `MIN_STARS` (default: 100).
4. Downloads the raw file content and verifies the term appears (guards against API false-positives).
5. Saves results to `results/agents_md_results.json` and `results/agents_md_report.md`.

## Searched terms

| Term |
|------|
| `duplicate code` |
| `duplicated code` |
| `code duplication` |
| `code redundancy` |
| `duplicated logic` |
| `copy-paste code` |
| `copy-pasted code` |
| `repeated code` |
| `extract method` |
| `extract function` |
| `DRY principle` |
| `avoid duplication` |

## Requirements

- Python 3.10+
- A GitHub Personal Access Token (PAT) with `public_repo` read scope

Install dependencies:

```bash
pip install requests python-dotenv
```

## Configuration

Create a `.env` file in the project root:

```
GITHUB_TOKEN=your_token_here
```

> Without a token, the GitHub API is limited to 10 requests/min (unauthenticated).

## Usage

```bash
python search_agents_md.py
```

Results will be saved to the `results/` folder (created automatically).

## Output

| File | Description |
|------|-------------|
| `results/agents_md_results.json` | Full structured results with metadata |
| `results/agents_md_report.md` | Human-readable Markdown report with summary and per-file details |

## Project structure

```
.
├── search_agents_md.py   # Main script
├── .env                  # GitHub token (not committed)
├── results/              # Output directory (auto-created)
│   ├── agents_md_results.json
│   └── agents_md_report.md
└── README.md
```
