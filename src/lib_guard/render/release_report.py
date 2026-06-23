"""HTML renderer for manifest-driven release verification."""

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
            return p.as_uri()
    except Exception:
        pass
    return text.replace("\\", "/")


def _counts_text(counts: Mapping[str, Any]) -> str:
    if not counts:
        return "-"
    return " / ".join(f"{k}:{v}" for k, v in sorted(counts.items())[:10])


def _issue_counts_by_library(issues: list[Mapping[str, Any]]) -> dict[str, Counter[str]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for issue in issues:
        lib = str(issue.get("library_name") or "__release_area__")
        grouped[lib][str(issue.get("category") or "issue")] += 1
    return grouped


def _release_brief_items(postcheck: Mapping[str, Any]) -> list[tuple[str, Any, str, Any]]:
    summary = postcheck.get("summary", {}) or {}
    issue_count = sum(
        int(summary.get(key, 0) or 0)
        for key in ["missing_files", "broken_links", "target_mismatch", "extra_files"]
    )
    return [
        ("Release ID", postcheck.get("release_id") or "-", "release run identifier", postcheck.get("status") or "UNKNOWN"),
        ("Alias", postcheck.get("alias") or "-", "target alias such as current/stage", "PASS"),
        ("Release Root", postcheck.get("release_root") or "-", "release area root", "PASS" if postcheck.get("release_root") else "WARNING"),
        ("Manifest", postcheck.get("manifest_path") or "-", "release_manifest.json", "PASS" if postcheck.get("manifest_path") else "WARNING"),
        ("Postcheck", postcheck.get("postcheck_path") or "-", "release_postcheck.json", "PASS" if postcheck.get("postcheck_path") else "WARNING"),
        ("Libraries", summary.get("expected_libraries", 0), "libraries in manifest", "PASS"),
        ("Expected Files", summary.get("expected_files", 0), "planned file-level release entries", "PASS"),
        ("Linked Files", summary.get("linked_files", 0), "files found in release area", postcheck.get("status") or "UNKNOWN"),
        ("Issues", issue_count, "missing / broken / mismatch / extra", "WARNING" if issue_count else "PASS"),
    ]


def _release_summary_tiles(postcheck: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    summary = postcheck.get("summary", {}) or {}
    specs = [
        ("Expected files", "manifest scope", "expected_files", "PASS", "File-level entries planned by the release manifest."),
        ("Linked files", "release area", "linked_files", postcheck.get("status") or "UNKNOWN", "Files present after link/copy operation."),
        ("Missing files", "needs review", "missing_files", "MISSING", "Manifest files not found in release area."),
        ("Broken links", "needs review", "broken_links", "BROKEN", "Symlinks that do not resolve."),
        ("Mismatches", "needs review", "target_mismatch", "MISMATCH", "Release target does not match manifest source."),
        ("Extra files", "needs review", "extra_files", "EXTRA", "Files in release area not covered by manifest."),
        ("Unknown types", "classifier", "unknown_file_types", "WARNING", "Released files still classified as unknown."),
    ]
    items: list[Mapping[str, Any]] = []
    for title, subtitle, key, status_when_nonzero, hint in specs:
        count = int(summary.get(key, 0) or 0)
        status = "PASS" if key not in {"linked_files"} and count == 0 and status_when_nonzero != "PASS" else status_when_nonzero
        if key in {"expected_files", "linked_files"}:
            status = status_when_nonzero
        items.append(
            {
                "title": title,
                "subtitle": subtitle,
                "status": status,
                "status_label": "review" if status in {"MISSING", "BROKEN", "MISMATCH", "EXTRA", "WARNING"} and count else "ok",
                "count": count,
                "hint": hint,
            }
        )
    return items


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


def _library_verification_rows(postcheck: Mapping[str, Any]) -> list[str]:
    from lib_guard.render.product_theme import badge, esc

    issues_by_lib = _issue_counts_by_library(list(postcheck.get("issues", []) or []))
    rows: list[str] = []
    for item in postcheck.get("libraries", []) or []:
        lib = str(item.get("library_name") or "unknown")
        counts = issues_by_lib.get(lib, Counter())
        evidence = []
        if item.get("scan_html"):
            evidence.append(f"<a class='evidence-link compact' href='{esc(_href(item.get('scan_html')))}'>Scan</a>")
        if item.get("diff_html"):
            evidence.append(f"<a class='evidence-link compact' href='{esc(_href(item.get('diff_html')))}'>Diff</a>")
        evidence_html = "".join(evidence) or '<span class="muted">-</span>'
        rows.append(
            "<tr>"
            f"<td><b>{esc(lib)}</b><div class='sub'>{esc(item.get('version_id') or '-')}</div></td>"
            f"<td>{esc(item.get('expected_files', 0))}</td>"
            f"<td>{esc(item.get('linked_files', 0))}</td>"
            f"<td>{badge('MISSING', counts.get('missing_file', 0))}</td>"
            f"<td>{badge('BROKEN', counts.get('broken_link', 0))}</td>"
            f"<td>{badge('MISMATCH', counts.get('target_mismatch', 0))}</td>"
            f"<td>{badge('EXTRA', counts.get('extra_file', 0))}</td>"
            f"<td>{badge(item.get('link_status') or 'UNKNOWN')}</td>"
            f"<td>{badge('PASS' if item.get('target_match') else 'MISMATCH')}</td>"
            f"<td>{esc(_counts_text(item.get('file_type_counts', {}) or {}))}</td>"
            f"<td>{evidence_html}</td>"
            "</tr>"
        )
    return rows


def _release_trace_links(postcheck: Mapping[str, Any]) -> list[tuple[str, Any, str]]:
    return [
        ("release_manifest.json", _href(postcheck.get("manifest_path")), "planned file-level release entries"),
        ("release_link_result.json", _href(postcheck.get("link_result_path")), "link/copy dry-run or apply result"),
        ("release_postcheck.json", _href(postcheck.get("postcheck_path")), "post-release verification result"),
    ]


def _full_issue_rows(postcheck: Mapping[str, Any]) -> list[str]:
    from lib_guard.render.product_theme import badge, esc

    rows: list[str] = []
    for issue in postcheck.get("issues", []) or []:
        rows.append(
            "<tr>"
            f"<td>{badge(issue.get('severity') or issue.get('category') or 'WARNING')}</td>"
            f"<td><code>{esc(issue.get('category') or '-')}</code></td>"
            f"<td>{esc(issue.get('library_name') or 'release_area')}</td>"
            f"<td>{esc(issue.get('message') or '')}</td>"
            "</tr>"
        )
    return rows


def render_release_html(postcheck: Mapping[str, Any], out_dir: str | Path) -> dict[str, Any]:
    from lib_guard.render.product_theme import (
        attention_items,
        brief_grid,
        collapsible_panel,
        page_shell,
        panel,
        table,
        tile_grid,
        trace_link_list,
    )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    attention = attention_items(_release_attention_items(postcheck))
    summary = tile_grid(_release_summary_tiles(postcheck))
    evidence_drawer = (
        trace_link_list(_release_trace_links(postcheck))
        + collapsible_panel(
            "Raw Issue Table / 原始问题表",
            "Full missing / broken / mismatch / extra issue evidence.",
            table(["Severity", "Category", "Library", "Message"], _full_issue_rows(postcheck), "No release issues"),
            open=bool(postcheck.get("issues")),
        )
    )
    body = (
        "<span class='compat-token'>Release 文件级审阅台</span>"
        + panel(
            "Release Brief / 发布概览",
            "Confirm release_id, alias, release_root and evidence files before reading the verification result.",
            brief_grid(_release_brief_items(postcheck)),
        )
        + panel(
            "Verification Summary / 校验摘要",
            "File-level release verification: expected, linked, missing, broken, mismatch and extra.",
            summary,
        )
        + panel(
            "Release Attention / 发布关注",
            "Only missing, broken, mismatch, extra and manual-review issues are surfaced here.",
            attention,
        )
        + panel(
            "Library Verification Table / 库级校验表",
            "One row per library; full file-level evidence stays folded below.",
            table(
                ["Library", "Expected", "Linked", "Missing", "Broken", "Mismatch", "Extra", "Link", "Target", "File Types", "Evidence"],
                _library_verification_rows(postcheck),
                "No libraries in release postcheck",
            ),
        )
        + collapsible_panel(
            "Evidence Drawer / 证据抽屉",
            "Manifest, link result, postcheck JSON and raw issue rows are trace evidence.",
            evidence_drawer,
            open=False,
        )
    )
    html_text = page_shell(
        "lib_guard 发布校验审阅台",
        "RELEASE REVIEW",
        f"{postcheck.get('release_id') or 'release'} | alias={postcheck.get('alias') or '-'} | status={postcheck.get('status') or 'UNKNOWN'}",
        body,
        nav="<a class='active' href='#'>Brief</a><a href='#'>Verify</a><a href='#'>Attention</a><a href='#'>Evidence</a>",
    )
    index = out / "index.html"
    index.write_text(html_text, encoding="utf-8")
    return {"status": "PASS", "html_dir": str(out), "index_html": str(index)}


def render_release_html_from_json(postcheck_json: str | Path, out_dir: str | Path) -> dict[str, Any]:
    data = json.loads(Path(postcheck_json).read_text(encoding="utf-8"))
    return render_release_html(data, out_dir)
