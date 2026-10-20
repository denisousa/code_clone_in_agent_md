import csv
import random
import sys
from pathlib import Path

csv.field_size_limit(sys.maxsize)

BASE_DIR = Path(__file__).parent

SOURCES: dict[str, Path] = {
    "repos":   BASE_DIR / "ai_config/repos.csv",
    "skills":  BASE_DIR / "ai_config/skills.csv",
    "commits": BASE_DIR / "ai_config/commits.csv",
}

OUTPUT_DIR = BASE_DIR / "ai_config_results/samples"


def rows_to_markdown(label: str, rows: list[dict]) -> str:
    sections = []
    for i, row in enumerate(rows, start=1):
        lines = [f"# {label} – Row {i}", ""]
        for field, value in row.items():
            lines.append(f"**{field}**")
            lines.append("")
            lines.append(str(value) if value else "_(empty)_")
            lines.append("")
        sections.append("\n".join(lines))
    return "\n---\n\n".join(sections)


def read_random(path: Path, n: int = 5) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return random.sample(rows, min(n, len(rows)))


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for label, path in SOURCES.items():
        rows = read_random(path)
        out = OUTPUT_DIR / f"{label}_sample.md"
        out.write_text(rows_to_markdown(label, rows), encoding="utf-8")
        print(f"Saved to {out}")


if __name__ == "__main__":
    main()
