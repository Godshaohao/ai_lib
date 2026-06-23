"""Render diff_output into a product-grade HTML review report."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import json

from lib_guard.render.product_theme import (
    action_bar,
    badge,
    esc,
    evidence_grid,
    metric,
    page_shell,
    panel,
    product_summary,
    status_rail,
    table,
)


def _read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _fmt(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return esc(json.dumps(value, ensure_ascii=False))
    return esc(value)


def _file_href(path: Path) -> str:
    try:
        return path.resolve().as_uri()
    except Exception:
        return str(path)


def _copy_button(command: str) -> str:
    return f"<button class='copy' onclick='copyText({json.dumps(command, ensure_ascii=False)}, this)'>复制</button>"


def _issue_rows(issues: list[Mapping[str, Any]]) -> list[str]:
    rows: list[str] = []
    for issue in issues:
        rows.append(
            "<tr>"
            f"<td>{badge(issue.get('severity', 'info'))}</td>"
            f"<td><code>{esc(issue.get('category'))}</code></td>"
            f"<td>{esc(issue.get('file_type'))}</td>"
            f"<td><b>{esc(issue.get('title'))}</b><div class='sub'>{esc(issue.get('message'))}</div></td>"
            "</tr>"
        )
    return rows


def _kv_rows(items: list[dict[str, Any]]) -> list[str]:
    return [
        "<tr>"
        f"<td><b>{esc(item.get('item'))}</b></td>"
        f"<td>{_fmt(item.get('old'))}</td>"
        f"<td>{_fmt(item.get('new'))}</td>"
        f"<td>{_fmt(item.get('delta'))}</td>"
        "</tr>"
        for item in items
    ]


def _pairwise_task_rows(tasks: list[Mapping[str, Any]]) -> list[str]:
    rows: list[str] = []
    for task in tasks:
        command = str(task.get("command") or "")
        expected = task.get("expected_output")
        expected_link = ""
        status = task.get("status", "PENDING")
        if expected:
            expected_path = Path(str(expected))
            if (expected_path / "file_diff_summary.json").exists():
                status = "DONE"
            expected_link = f"<a class='link' href='{esc(_file_href(expected_path))}'>结果目录</a>"
        rows.append(
            "<tr>"
            f"<td>{badge(task.get('priority', 'P1'))}</td>"
            f"<td><code>{esc(task.get('file_type'))}</code><div class='sub'>{esc(task.get('reason'))}</div></td>"
            f"<td><code>{esc(task.get('old_file'))}</code><div class='sub'>old</div></td>"
            f"<td><code>{esc(task.get('new_file'))}</code><div class='sub'>new</div></td>"
            f"<td><div class='cmd'><code>{esc(command)}</code>{_copy_button(command)}</div><div class='sub link-row'>{expected_link}</div></td>"
            f"<td>{badge(status)}</td>"
            "</tr>"
        )
    return rows


def render_diff_html(diff_dir: str | Path, out_dir: str | Path) -> dict[str, Any]:
    diff = Path(diff_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    meta = _read_json(diff / "diff_meta.json", {}) or {}
    summary = _read_json(diff / "diff_summary.json", {}) or {}
    file_diff = _read_json(diff / "file_diff.json", {}) or {}
    component_diff = _read_json(diff / "component_diff.json", {}) or {}
    readiness = _read_json(diff / "release_readiness_diff.json", {}) or {}
    issues = _read_json(diff / "diff_issues.json", {"issues": []}) or {"issues": []}
    pairwise_tasks = _read_json(diff / "pairwise_diff_tasks.json", {"tasks": [], "summary": {}}) or {"tasks": [], "summary": {}}

    relation = meta.get("version_relation", {}) if isinstance(meta.get("version_relation"), Mapping) else {}
    counts = file_diff.get("counts") or {}
    issue_items = issues.get("issues", []) or []
    status = summary.get("status") or "UNKNOWN"
    risk = summary.get("risk_level") or ("HIGH" if status == "BLOCK" else "LOW")

    summary_cards = product_summary(
        [
            ("差异状态", status, "本次治理 diff 的总体结论", status),
            ("风险等级", risk, "发布前需要关注的风险强度", risk),
            ("变化文件", summary.get("changed_files", counts.get("changed", 0)), "内容 hash 或元数据变化", "warn" if summary.get("changed_files", counts.get("changed", 0)) else "ok"),
            ("专业对比任务", summary.get("pairwise_tasks", 0), "需要用专业脚本两两核查", "warn" if summary.get("pairwise_tasks") else "ok"),
        ]
    )
    stage_rail = status_rail(
        [
            ("版本关系", "PASS" if relation else "UNKNOWN", f"{relation.get('diff_mode') or 'unknown'}"),
            ("文件变化", "WARNING" if counts.get("changed") or counts.get("added") or counts.get("removed") else "PASS", f"changed: {counts.get('changed', 0)}"),
            ("专业对比任务", "WARNING" if pairwise_tasks.get("tasks") else "PASS", f"tasks: {len(pairwise_tasks.get('tasks') or [])}"),
            ("发布准入", status, f"risk: {risk}"),
        ]
    )
    evidence = evidence_grid(
        [
            ("Diff Meta", "PASS" if (diff / "diff_meta.json").exists() else "UNKNOWN", "比较输入、版本关系和扫描目录。", _file_href(diff / "diff_meta.json")),
            ("File Diff", "PASS" if (diff / "file_diff.json").exists() else "UNKNOWN", "新增、删除、变化和元数据变化文件。", _file_href(diff / "file_diff.json")),
            ("Pairwise Tasks", "PASS" if (diff / "pairwise_diff_tasks.json").exists() else "UNKNOWN", "建议手动执行的专业两两对比命令。", _file_href(diff / "pairwise_diff_tasks.json")),
            ("Diff Issues", status, "阻塞项、警告项和人工确认列表。", _file_href(diff / "diff_issues.json")),
        ]
    )
    overview = "".join(
        [
            metric("专业任务", summary.get("pairwise_tasks", 0), "建议执行的两两文件 diff", "warn" if summary.get("pairwise_tasks") else "ok"),
            metric("人工确认", summary.get("manual_review_items", len(issue_items)), "需要审阅的风险项", "warn" if issue_items else "ok"),
        ]
    )
    relation_rows = [
        f"<tr><td>比较模式</td><td>{badge(relation.get('diff_mode'))}</td></tr>",
        f"<tr><td>旧版本</td><td><code>{esc(relation.get('old_version'))}</code></td></tr>",
        f"<tr><td>新版本</td><td><code>{esc(relation.get('new_version'))}</code></td></tr>",
        f"<tr><td>Parent</td><td><code>{esc(relation.get('parent_version'))}</code></td></tr>",
        f"<tr><td>Base</td><td><code>{esc(relation.get('base_version'))}</code></td></tr>",
        f"<tr><td>旧扫描目录</td><td><code>{esc(meta.get('old_scan'))}</code></td></tr>",
        f"<tr><td>新扫描目录</td><td><code>{esc(meta.get('new_scan'))}</code></td></tr>",
    ]
    overview_body = summary_cards + stage_rail + f"<div class='split'><div><div class='metrics'>{overview}</div>{evidence}</div><div>{table(['字段', '值'], relation_rows)}</div></div>"

    file_rows = [
        f"<tr><td>新增</td><td>{esc(counts.get('added', 0))}</td><td>{esc(', '.join((file_diff.get('added') or [])[:6]))}</td></tr>",
        f"<tr><td>删除</td><td>{esc(counts.get('removed', 0))}</td><td>{esc(', '.join((file_diff.get('removed') or [])[:6]))}</td></tr>",
        f"<tr><td>内容变化</td><td>{esc(counts.get('changed', 0))}</td><td>{esc(', '.join((file_diff.get('changed') or [])[:6]))}</td></tr>",
        f"<tr><td>仅元数据变化</td><td>{esc(counts.get('metadata_only_changed', 0))}</td><td></td></tr>",
    ]

    comp_rows = []
    for item in component_diff.get("changed", []) or []:
        comp_rows.append(
            "<tr>"
            f"<td><code>{esc(item.get('component_key'))}</code></td>"
            f"<td>{esc(item.get('old_status'))}</td>"
            f"<td>{esc(item.get('new_status'))}</td>"
            f"<td>{esc(item.get('old_channel'))}</td>"
            f"<td>{esc(item.get('new_channel'))}</td>"
            f"<td>{_fmt(item.get('required_view_changes'))}</td>"
            "</tr>"
        )

    readiness_rows = _kv_rows(
        [
            {"item": "bundle_status", **(readiness.get("bundle_status") or {})},
            {"item": "release_channel", **(readiness.get("release_channel") or {})},
            {"item": "blocking_count", **(readiness.get("blocking_count") or {})},
            {"item": "manual_review_count", **(readiness.get("manual_review_count") or {})},
        ]
    )

    pairwise_rows = _pairwise_task_rows(list(pairwise_tasks.get("tasks") or []))
    pairwise_html = panel(
        "Pairwise Diff Tasks",
        "治理 diff 只判断能否进入下一阶段；下面命令用于手动核查具体 LEF / Liberty / Verilog / SDC 文件差异。",
        table(["优先级", "类型", "Old", "New", "命令", "状态"], pairwise_rows, "暂无需要手动执行的专业文件对比"),
        badge(pairwise_tasks.get("status", "EMPTY")),
    )

    nav = "<a href='#overview'>总览</a><a href='#pairwise'>专业对比</a><a href='#review'>风险项</a>"
    body = (
        "<!-- Diff Overview --><!-- Pairwise Diff Tasks -->"
        + action_bar(
            [
                ("打开 diff_summary", _file_href(diff / "diff_summary.json"), "primary"),
                ("打开 file_diff", _file_href(diff / "file_diff.json"), "secondary"),
                ("打开 pairwise_tasks", _file_href(diff / "pairwise_diff_tasks.json"), "secondary"),
                ("打开 diff_issues", _file_href(diff / "diff_issues.json"), "secondary"),
            ]
        )
        + f"<div id='overview'>{panel('治理差异总览', '先判断版本能不能进入下一阶段；具体文件细节交给专业两两对比脚本。', overview_body, badge(status))}</div>"
        + panel("文件变化", "来自 file_inventory 的文件级变化，帮助定位变化范围。", table(["变化类型", "数量", "样例"], file_rows))
        + panel("组件变化", "组件级状态、channel 与 required view 的变化。", table(["组件", "旧状态", "新状态", "旧通道", "新通道", "Required View"], comp_rows, "暂无组件级变化"))
        + f"<div id='pairwise'>{pairwise_html}</div>"
        + panel("发布准入变化", "比较两个版本在 release readiness 上的风险变化。", table(["项目", "旧值", "新值", "Delta"], readiness_rows))
        + f"<div id='review'>{panel('需要处理的问题', '阻塞项和警告项会进入人工审阅或发布 gate。', table(['级别', '类别', '对象类型', '证据'], _issue_rows(list(issue_items)), '暂无 diff 风险项'))}</div>"
    )
    html_text = page_shell(
        "lib_guard 差异审阅台",
        "DIFF REVIEW DESK",
        f"{relation.get('old_version') or 'old'} -> {relation.get('new_version') or 'new'} | 状态 {status}",
        body,
        nav=nav,
    )
    (out / "index.html").write_text(html_text, encoding="utf-8")
    return {"status": "PASS", "diff_dir": str(diff), "html_dir": str(out), "index_html": str(out / "index.html")}
