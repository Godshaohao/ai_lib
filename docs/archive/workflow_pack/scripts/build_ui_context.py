#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path


MAX_SAMPLE_ROWS = 8


def read_csv_sample(path: Path, max_rows: int = MAX_SAMPLE_ROWS):
    for encoding in ("utf-8-sig", "gbk"):
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                reader = csv.DictReader(f)
                rows = []
                for i, row in enumerate(reader):
                    if i >= max_rows:
                        break
                    rows.append(row)
                return reader.fieldnames or [], rows, None
        except UnicodeDecodeError:
            continue
        except Exception as exc:  # pragma: no cover - utility script
            return [], [], str(exc)
    return [], [], f"unable to decode {path}"


def count_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return max(sum(1 for _ in f) - 1, 0)
    except Exception:
        return None


def csv_table(rows, fields) -> str:
    if not rows or not fields:
        return "_No sample rows._"
    lines = [",".join(fields)]
    for row in rows:
        values = []
        for field in fields:
            value = str(row.get(field, "")).replace("\n", " ").replace("\r", " ")
            if "," in value or '"' in value:
                value = '"' + value.replace('"', '""') + '"'
            values.append(value)
        lines.append(",".join(values))
    return "\n".join(lines)


def build_context(data_dir: Path, out: Path, project_name: str = "lib_guard") -> None:
    csv_files = sorted(data_dir.glob("*.csv"))

    lines = [
        f"# UI Context for {project_name}",
        "",
        f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 1. UI Goal",
        "",
        "- Summarize UI-relevant data for dashboard/report iteration.",
        "- Keep rendering changes separate from parser, validator, readiness, diff, and release logic.",
        "- Treat generated HTML as preview output, not source of truth.",
        "",
        "## 2. Source Of Truth",
        "",
        "- Production renderers: `src/lib_guard/render/`",
        "- Workflow helper renderer: `scripts/render_dashboard.py`",
        "- Raw source data: `data/*.csv` or lib_guard JSON outputs",
        "- Generated preview: `reports/index.html`",
        "",
        "## 3. Data Files",
        "",
    ]
    if not csv_files:
        lines.append("_No CSV files found._")
    else:
        for path in csv_files:
            fields, sample_rows, err = read_csv_sample(path)
            row_count = count_rows(path)
            lines.extend([
                f"### {path.name}",
                "",
                f"- Path: `{path}`",
                f"- Row count: `{row_count if row_count is not None else 'unknown'}`",
            ])
            if err:
                lines.extend([f"- Read error: `{err}`", ""])
                continue
            lines.extend([
                f"- Columns: `{', '.join(fields) if fields else 'unknown'}`",
                "",
                "Sample:",
                "",
                "```csv",
                csv_table(sample_rows, fields),
                "```",
                "",
                "Recommended UI:",
                "",
                "- TODO: describe card / chart / matrix / table usage.",
                "",
            ])
    lines.extend([
        "## 4. Current UI Problems",
        "",
        "- TODO",
        "",
        "## 5. Requested UI Changes",
        "",
        "- TODO",
        "",
        "## 6. Expected Output",
        "",
        "Modify only UI source files unless the user explicitly requests data logic changes.",
        "",
    ])

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a UI context markdown from CSV files.")
    parser.add_argument("--data-dir", default="data", help="Directory containing CSV files.")
    parser.add_argument("--out", default="reports/ui_context.md", help="Output markdown file.")
    parser.add_argument("--project-name", default="lib_guard", help="Project/dashboard name.")
    args = parser.parse_args()

    build_context(Path(args.data_dir), Path(args.out), args.project_name)


if __name__ == "__main__":
    main()
