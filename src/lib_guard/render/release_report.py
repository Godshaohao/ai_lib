"""Chinese Release Review HTML renderer.

Release Review answers whether manifest/link/postcheck evidence is consistent.
It does not replace human signoff.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping
import json


def _href(path: Any) -> str:
    if not path:
        return ""
    text = str(path)
    if text.startswith(("http://", "https://", "file://")):
        return text
    try:
        p = Path(text)
        if p.is_absolute():
            return p.resolve().as_uri()
    except Exception:
        pass
    return text.replace("\\", "/")


def _issue_counts_by_library(issues: list[Mapping[str, Any]]) -> dict[str, Counter[str]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for issue in issues:
        lib = str(issue.get("library_name") or "__release_area__")
        grouped[lib][str(issue.get("category") or "issue")] += 1
    return grouped


def _release_review_model(postcheck: Mapping[str, Any]) -> dict[str, Any]:
    summary = postcheck.get("summary", {}) or {}
    issue_count = sum(int(summary.get(key, 0) or 0) for key in ["missing_files", "broken_links", "target_mismatch", "extra_files"])
    status = str(postcheck.get("status") or "UNKNOWN").upper()
    if status in {"FAILED", "BLOCK", "BLOCKED"}:
        decision = "RELEASE_BLOCKED"
        headline = "Release postcheck 失败，需要先处理发布结果。"
    elif issue_count:
        decision = "PASS_WITH_WARNING"
        headline = f"Release 基本完成，但有 {issue_count} 个发布注意项。"
    elif status == "PASS":
        decision = "PASS"
        headline = "Release postcheck 通过，manifest 和 release area 一致。"
    else:
        decision = "RELEASE_CHECK_REQUIRED"
        headline = "Release 状态未确认，需要查看 manifest / postcheck。"
    next_command = ""
    if issue_count:
        next_label = "检查发布注意项"
        next_reason = "优先检查 missing / broken / mismatch / extra。"
    else:
        next_label = "返回 Catalog / 通知使用者"
        next_reason = "发布检查没有发现优先阻塞项。"
    return {
        "schema_version": "release_review.v1",
        "decision": decision,
        "headline": headline,
        "release_id": postcheck.get("release_id"),
        "alias": postcheck.get("alias"),
        "release_root": postcheck.get("release_root"),
        "release_dir": postcheck.get("release_dir"),
        "summary": {
            "expected_files": int(summary.get("expected_files", 0) or 0),
            "linked_files": int(summary.get("linked_files", 0) or 0),
            "missing_files": int(summary.get("missing_files", 0) or 0),
            "broken_links": int(summary.get("broken_links", 0) or 0),
            "target_mismatch": int(summary.get("target_mismatch", 0) or 0),
            "extra_files": int(summary.get("extra_files", 0) or 0),
            "unknown_file_types": int(summary.get("unknown_file_types", 0) or 0),
            "expected_libraries": int(summary.get("expected_libraries", 0) or 0),
        },
        "next_action": {"label": next_label, "command": next_command, "reason": next_reason},
        "evidence": {
            "manifest": postcheck.get("manifest_path"),
            "link_result": postcheck.get("link_result_path"),
            "postcheck": postcheck.get("postcheck_path"),
        },
    }


def _release_attention_items(postcheck: Mapping[str, Any]) -> list[tuple[Any, str, str, str]]:
    items: list[tuple[Any, str, str, str]] = []
    for issue in postcheck.get("issues", []) or []:
        category = str(issue.get("category") or "issue")
        if category not in {"missing_file", "broken_link", "target_mismatch", "extra_file", "manual_review"}:
            continue
        status = {
            "missing_file": "MISSING",
            "broken_link": "BROKEN",
            "target_mismatch": "MISMATCH",
            "extra_file": "EXTRA",
            "manual_review": "MANUAL_REVIEW",
        }.get(category, issue.get("severity") or "WARNING")
        lib = issue.get("library_name") or "release_area"
        items.append((status, category.replace("_", " "), str(issue.get("message") or ""), str(lib)))
    return items


def _library_rows(postcheck: Mapping[str, Any]) -> list[str]:
    from lib_guard.render import product_theme as ui

    issues_by_lib = _issue_counts_by_library(list(postcheck.get("issues", []) or []))
    rows: list[str] = []
    for item in postcheck.get("libraries", []) or []:
        lib = str(item.get("library_name") or "unknown")
        counts = issues_by_lib.get(lib, Counter())
        evidence = ui.action_strip([
            ui.button("Scan", _href(item.get("scan_html")), disabled=not item.get("scan_html"), target="_blank"),
            ui.button("Diff", _href(item.get("diff_html")), disabled=not item.get("diff_html"), target="_blank"),
        ])
        rows.append(
            "<tr>"
            f"<td><b>{ui.esc(lib)}</b><div class='muted'>{ui.esc(item.get('version_id') or '-')}</div></td>"
            f"<td>{ui.esc(item.get('expected_files', 0))}</td>"
            f"<td>{ui.esc(item.get('linked_files', 0))}</td>"
            f"<td>{ui.quiet_badge('MISSING', counts.get('missing_file', 0))}</td>"
            f"<td>{ui.quiet_badge('BROKEN', counts.get('broken_link', 0))}</td>"
            f"<td>{ui.quiet_badge('MISMATCH', counts.get('target_mismatch', 0))}</td>"
            f"<td>{ui.quiet_badge('EXTRA', counts.get('extra_file', 0))}</td>"
            f"<td>{ui.badge(item.get('link_status') or 'UNKNOWN')}</td>"
            f"<td>{ui.badge('TARGET_MATCH' if item.get('target_match') else 'TARGET_MISMATCH')}</td>"
            f"<td>{evidence}</td>"
            "</tr>"
        )
    return rows


def _issue_rows(postcheck: Mapping[str, Any]) -> list[str]:
    from lib_guard.render import product_theme as ui

    rows = []
    for issue in postcheck.get("issues", []) or []:
        rows.append(
            "<tr>"
            f"<td>{ui.badge(issue.get('severity') or issue.get('category') or 'WARNING')}</td>"
            f"<td><code>{ui.esc(issue.get('category') or '-')}</code></td>"
            f"<td>{ui.esc(issue.get('library_name') or 'release_area')}</td>"
            f"<td>{ui.esc(issue.get('message') or '')}</td>"
            "</tr>"
        )
    return rows


def _review_gate_panel(postcheck: Mapping[str, Any]) -> str:
    from lib_guard.render import product_theme as ui

    gate = postcheck.get("review_gate") if isinstance(postcheck.get("review_gate"), Mapping) else {}
    status = str((gate or {}).get("status") or "NOT_PROVIDED")
    return ui.panel(
        "Review Gate",
        "Release-check consumes this lightweight gate when available. Link/postcheck still records filesystem evidence only.",
        ui.metric_grid([
            ("Status", status, str((gate or {}).get("gate") or "-"), status),
            ("Blocking Open", int((gate or {}).get("blocking_open", 0) or 0), "must be zero for current when policy requires it", "BLOCK" if int((gate or {}).get("blocking_open", 0) or 0) else "PASS"),
            ("Attention", int((gate or {}).get("attention_count", 0) or 0), "recommendations, not current blockers", "WARNING" if int((gate or {}).get("attention_count", 0) or 0) else "PASS"),
        ])
        + ui.trace_link_list([
            ("review_gate.json", _href((gate or {}).get("gate_file")), "Gate status used by release-check"),
            ("review_overrides.json", _href((gate or {}).get("override_file")), "Owner accept/waive decisions"),
        ]),
    )


def render_release_html(postcheck: Mapping[str, Any], out_dir: str | Path) -> dict[str, Any]:
    from lib_guard.render import product_theme as ui

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    review = _release_review_model(postcheck)
    (out / "release_review.json").write_text(json.dumps(review, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    s = review["summary"]
    rail = ui.status_rail([
        ("Catalog", "DISCOVERED", "发布版本来自 catalog"),
        ("Scan", "SCAN_READY", "发布基于已扫描版本"),
        ("Diff", "REVIEW", "发布前应查看对应 Diff / File Diff"),
        ("File Diff", "REVIEW", "必要时查看文件级结果"),
        ("Release", review["decision"], review["headline"]),
    ])
    attention = _release_attention_items(postcheck)
    body = (
        ui.panel(
            "Release 结论",
            "检查 manifest、link/copy 结果和 release area 是否一致。",
            ui.metric_grid([
                ("Expected", s["expected_files"], "manifest 计划文件数", "PASS"),
                ("Linked", s["linked_files"], "release area 已存在文件", review["decision"]),
                ("Missing", s["missing_files"], "manifest 有但 release area 缺失", "MISSING" if s["missing_files"] else "PASS"),
                ("Mismatch", s["target_mismatch"], "目标与 manifest source 不一致", "MISMATCH" if s["target_mismatch"] else "PASS"),
                ("Extra", s["extra_files"], "release area 多余文件", "EXTRA" if s["extra_files"] else "PASS"),
            ])
            + ui.compact_meta([
                ("Release ID", review.get("release_id")), ("Alias", review.get("alias")), ("Release Root", review.get("release_root")), ("Release Dir", review.get("release_dir")),
            ]),
        )
        + ui.next_action_panel(review["next_action"]["label"], review["next_action"]["command"], review["next_action"]["reason"], status=review["decision"])
        + _review_gate_panel(postcheck)
        + ui.panel("发布注意项", "只列出 missing / broken / mismatch / extra / manual_review。", ui.attention_items(attention))
        + ui.panel("Library 校验", "一行一个 library。文件级明细仍以 manifest / postcheck JSON 为准。", ui.filterable_table("release-lib-table", ["Library", "Expected", "Linked", "Missing", "Broken", "Mismatch", "Extra", "Link", "Target", "Evidence"], _library_rows(postcheck), "暂无 library", "筛选 library / version / status"))
        + ui.collapsible_panel(
            "证据区",
            "发布原始证据默认折叠。",
            ui.trace_link_list([
                ("release_review.json", _href(out / "release_review.json"), "本页面使用的发布审阅模型"),
                ("release_manifest.json", _href(postcheck.get("manifest_path")), "计划发布文件"),
                ("release_link_result.json", _href(postcheck.get("link_result_path")), "link/copy 结果"),
                ("release_postcheck.json", _href(postcheck.get("postcheck_path")), "postcheck 结果"),
            ])
            + ui.filterable_table("release-issues", ["Severity", "Category", "Library", "Message"], _issue_rows(postcheck), "暂无 release issue", "筛选 issue"),
            open=False,
        )
    )
    html_text = ui.review_page_shell(
        f"{review.get('release_id') or 'Release'} / {review.get('alias') or '-'}",
        "RELEASE REVIEW",
        review["headline"],
        body,
        decision=review["decision"],
        rail=rail,
        nav="<a href='#'>Scan</a><a href='#'>Diff</a><a href='#'>File Diff</a><a class='active' href='#'>Release</a>",
        meta=ui.compact_meta([("Alias", review.get("alias")), ("Expected", s["expected_files"]), ("Linked", s["linked_files"]), ("Issues", len(attention))]),
    )
    index = out / "index.html"
    index.write_text(html_text, encoding="utf-8")
    return {"status": "PASS", "html_dir": str(out), "index_html": str(index), "release_review": str(out / "release_review.json")}


def render_release_html_from_json(postcheck_json: str | Path, out_dir: str | Path) -> dict[str, Any]:
    data = json.loads(Path(postcheck_json).read_text(encoding="utf-8"))
    return render_release_html(data, out_dir)
