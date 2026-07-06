from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import html
import json


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _rows(items: list[Mapping[str, Any]]) -> str:
    if not items:
        return "<tr><td colspan='5' class='empty'>暂无文件</td></tr>"
    out = []
    for item in items:
        out.append(
            "<tr>"
            f"<td><code>{_esc(item.get('target_relpath'))}</code></td>"
            f"<td>{_esc(item.get('view'))}</td>"
            f"<td>{_esc(item.get('source_kind'))}</td>"
            f"<td>{_esc(item.get('source_package'))}</td>"
            f"<td><code>{_esc(item.get('source_path'))}</code></td>"
            "</tr>"
        )
    return "".join(out)


def render_snapshot_html(snapshot: Mapping[str, Any] | str | Path, out_dir: str | Path) -> dict[str, Any]:
    data = json.loads(Path(snapshot).read_text(encoding="utf-8")) if isinstance(snapshot, (str, Path)) else dict(snapshot)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    view_rows = "".join(
        f"<tr><td>{_esc(view)}</td><td>{_esc(source)}</td></tr>"
        for view, source in sorted((data.get("resolved_views") or {}).items())
    ) or "<tr><td colspan='2' class='empty'>暂无视图</td></tr>"
    issue_rows = "".join(
        f"<tr><td>{_esc(i.get('severity'))}</td><td>{_esc(i.get('category'))}</td><td>{_esc(i.get('target_relpath'))}</td></tr>"
        for i in data.get("issues", []) or []
    ) or "<tr><td colspan='3' class='empty'>暂无异常</td></tr>"
    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>{_esc(data.get('snapshot_id'))}</title>
<style>
body {{ margin: 0; background: #f6f8fb; color: #172033; font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif; }}
header {{ padding: 28px 34px; background: #fff; border-bottom: 1px solid #e2e8f0; }}
main {{ padding: 24px 34px 44px; }}
h1 {{ margin: 0 0 8px; font-size: 28px; letter-spacing: 0; }}
.sub {{ color: #64748b; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 18px 0; }}
.metric, section {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; box-shadow: 0 10px 28px rgba(15,23,42,.07); }}
.metric {{ padding: 16px; }}
.metric b {{ display: block; margin-top: 8px; font-size: 24px; }}
section {{ margin: 16px 0; overflow: hidden; }}
h2 {{ margin: 0; padding: 14px 16px; background: #fbfcff; border-bottom: 1px solid #e2e8f0; font-size: 16px; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 10px 12px; border-bottom: 1px solid #e2e8f0; text-align: left; vertical-align: top; }}
th {{ color: #475569; background: #f8fafc; font-size: 12px; }}
code {{ color: #1e3a8a; word-break: break-all; }}
.empty {{ color: #64748b; text-align: center; }}
</style>
</head>
<body>
<header>
  <h1>组合快照</h1>
  <div class="sub">{_esc(data.get('snapshot_id'))} · 基线={_esc(data.get('base_package'))} · 更新={_esc(', '.join(data.get('updates') or []))}</div>
</header>
<main>
  <div class="grid">
    <div class="metric">状态<b>{_esc(data.get('status'))}</b></div>
    <div class="metric">已解析视图<b>{len(data.get('resolved_views') or {})}</b></div>
    <div class="metric">已解析文件<b>{len(data.get('resolved_files') or [])}</b></div>
    <div class="metric">问题<b>{len(data.get('issues') or [])}</b></div>
  </div>
  <section><h2>视图解析映射</h2><table><thead><tr><th>视图</th><th>来源包</th></tr></thead><tbody>{view_rows}</tbody></table></section>
  <section><h2>来源追溯</h2><table><thead><tr><th>目标</th><th>视图</th><th>类型</th><th>包</th><th>来源</th></tr></thead><tbody>{_rows(list(data.get('resolved_files') or []))}</tbody></table></section>
  <section><h2>问题</h2><table><thead><tr><th>级别</th><th>类别</th><th>目标</th></tr></thead><tbody>{issue_rows}</tbody></table></section>
</main>
</body>
</html>
"""
    index = out / "index.html"
    index.write_text(html_text, encoding="utf-8")
    return {"status": "PASS", "html_dir": str(out), "index_html": str(index)}
