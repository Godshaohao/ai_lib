#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from html import escape
from pathlib import Path


def read_first_csv(data_dir: Path):
    files = sorted(data_dir.glob("*.csv"))
    if not files:
        return None, [], []
    path = files[0]
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return path.name, reader.fieldnames or [], rows


def render_html(title: str, csv_name: str, fields, rows) -> str:
    header = "".join(f"<th>{escape(f)}</th>" for f in fields)
    body = ""
    for row in rows[:100]:
        body += "<tr>" + "".join(f"<td>{escape(str(row.get(f, '')))}</td>" for f in fields) + "</tr>\n"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 24px;
      background: #f6f7f9;
      color: #1f2937;
    }}
    .card {{
      background: white;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      padding: 18px;
      margin-bottom: 16px;
      box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: white;
    }}
    th, td {{
      border-bottom: 1px solid #e5e7eb;
      padding: 8px 10px;
      text-align: left;
      font-size: 13px;
    }}
    th {{
      background: #f9fafb;
      font-weight: 600;
    }}
    .muted {{
      color: #6b7280;
      font-size: 13px;
    }}
  </style>
</head>
<body>
  <div class="card">
    <h1>{escape(title)}</h1>
    <p class="muted">Workflow helper renderer. Generated HTML is preview output, not source of truth.</p>
  </div>

  <div class="card">
    <h2>Data Preview</h2>
    <p class="muted">Source CSV: {escape(csv_name or "none")}</p>
    <table>
      <thead><tr>{header}</tr></thead>
      <tbody>{body}</tbody>
    </table>
  </div>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a simple workflow dashboard from CSV data.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--out", default="reports/index.html")
    parser.add_argument("--title", default="lib_guard Workflow Dashboard")
    args = parser.parse_args()

    csv_name, fields, rows = read_first_csv(Path(args.data_dir))
    html = render_html(args.title, csv_name or "", fields, rows)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
