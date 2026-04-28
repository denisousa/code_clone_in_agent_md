# Code Clone in Agent Configuration Files

This repository contains scripts and data to investigate whether AI coding agent
configuration files (`.md`, `.json`) mention code-clone / code-duplication related
terms, and to study the relationship between those configurations and clone density
evolution in open-source projects.

---

## Related Dataset

**AI-Config Dataset** — [https://se-uhd.de/ai-config-dataset/#dashboard](https://se-uhd.de/ai-config-dataset/#dashboard)

The dataset provides structured CSV exports of agent configuration files collected
from public GitHub repositories, covering commands, context files, MCP configs,
skills, and subagents.

---

## Related Papers

| Title | Notes |
|---|---|
| **Configuring Agentic AI Coding Tools: An Exploratory Study** | Full paper by Sebastian et al. Direct source of the AI-Config dataset used here. Zenodo: [10.5281/zenodo.19696190](https://zenodo.org/records/19696190) · arXiv: [2510.21413](https://arxiv.org/abs/2510.21413) |
| **Context Engineering for AI Agents in Open-Source Software** | Earlier work by the same author. Related but independent from the AI-Config dataset. |

---

## Research Questions

**RQ1 — How are developers configuring agents to manage code clones?**

For each configuration file that mentions clone-related terms, the analysis covers:
- Repository domain
- Whether the file is an agent or subagent configuration
- Whether the file is dedicated solely to avoiding duplication
- Whether it is used in a code review context

**RQ2 — After adopting agent configurations, did developers become more attentive to the emergence of code clones?**

...

**RQ3 — After adopting agent configurations, did the clone density in the project decrease?**

...

---

## Methodology

1. Collect all repositories that have an agent configuration file mentioning code-duplication terms.
2. Compute the full clone genealogy of the collected projects.
3. Identify whether a merged pull request (merged commit) was authored by a human or an agent.
4. Calculate clone density for each merged commit.

---

## Script: `main.py`

Scans the AI-Config CSV files and searches for code-clone related terms in every
configuration file by fetching its raw content from GitHub.

**CSV sources processed:**

| CSV file | File-path column |
|---|---|
| `commands.csv` | `command` |
| `context_files.csv` | `context_file` |
| `mcp.csv` | `mcp` |
| `skills.csv` | `skills.md` |
| `subagents.csv` | `subagent` |

**Search terms:**
`duplicate code`, `duplicated code`, `code duplication`, `code redundancy`,
`duplicated logic`, `copy-paste`, `copy-pasted`, `repeated code`,
`DRY principle`, `avoid duplication`

**Output files** (written to `ai_config_results/`):

| File | Content |
|---|---|
| `clone_terms_report.json` | Per-file matches with term counts and snippets |
| `clone_terms_analysis.json` | Aggregated summary and global term ranking |
| `clone_terms_failed.json` | URLs that could not be fetched (with reason) |

### Setup

```bash
pip install requests python-dotenv
```

Create a `.env` file with your GitHub token to avoid rate-limiting:

```
GITHUB_TOKEN=ghp_...
```

### Run

```bash
python main.py
```

The script prints a pre-run summary with entry counts per CSV and an estimated
runtime before starting any network requests.

**Dataset scale (as of 2026-04-27):**

```
commands.csv          1,098 entries
context_files.csv     9,491 entries
mcp.csv                 138 entries
skills.csv            2,430 entries
subagents.csv           884 entries
─────────────────────────────────
TOTAL                14,041 entries   (~234 min estimated)
```
