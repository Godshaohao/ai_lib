"""Small fact panels for selected deep checks and existing file correspondence."""

import json
from pathlib import Path
import shutil
from datetime import datetime

from lib_guard.render import product_theme as ui


def _compact(value):
    if value is None:
        return '—'
    text = str(value) if isinstance(value, (str, int, float, bool)) else json.dumps(value, ensure_ascii=False)
    return text[:160] + ('…' if len(text) > 160 else '')


def _source_pair(row):
    old, new = str(row['old_file']), str(row['new_file'])
    return (
        f'<div class="check-source-name" title="{ui.esc(old)}"><span>旧</span><code>{ui.esc(Path(old).name)}</code></div>'
        f'<div class="check-source-name" title="{ui.esc(new)}"><span>新</span><code>{ui.esc(Path(new).name)}</code></div>'
        '<details class="check-paths"><summary>原始路径</summary>'
        + ''.join(f'<div><b>{label}</b><code>{ui.esc(path)}</code><button class="btn secondary" type="button" data-path="{ui.esc(path)}" onclick="copyText(this.dataset.path,this)">复制{label}文件路径</button></div>' for label, path in [('旧', old), ('新', new)])
        + '</details>'
    )


def render_file_checks(rows, pairing, page):
    if not rows and not pairing.get('rows'):
        return ''
    content = ''
    if rows:
        rendered = []
        history_rows = []
        for row in rows:
            source = Path(row['evidence_dir'])
            relative = Path('representative') / row['file_type'] / row['evidence_id']
            destination = Path(page).parent / relative
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True)
                links = f"<a href='{ui.esc((relative / 'index.html').as_posix())}'>详细对比</a><a href='{ui.esc((relative / 'pairwise_summary.md').as_posix())}'>文字摘要</a>"
            else:
                links = '详细证据不存在，需重新核查'
            changes = ''.join(f"<tr><td>{ui.esc(item.get('path'))}</td><td>{ui.esc(_compact(item.get('old')))}</td><td>{ui.esc(_compact(item.get('new')))}</td></tr>" for item in row.get('changes', []))
            detail = f"<details><summary>字段定位（最多 6 条）</summary><table><thead><tr><th>字段</th><th>旧值</th><th>新值</th></tr></thead><tbody>{changes}</tbody></table></details>" if changes else ''
            if row.get('parsed_fields') or row.get('unparsed_features'):
                detail += '<details><summary>实际解析范围</summary><p>已提取：' + ui.esc('、'.join(row.get('parsed_fields', [])) or '未记录') + '</p><p>不覆盖：' + ui.esc('、'.join(row.get('unparsed_features', [])) or '未记录') + '</p></details>'
            cap = row.get('comparison_capability') or {}
            raw = row.get('source_content_status') or 'UNVERIFIED'
            result = {
                'SAME': '源文件字节相同',
                'DIFF': '源文件字节不同',
            }.get(raw, '源文件内容未验证')
            parsed = row.get('parsed_fields_status') or ('无差异' if row['result'] == 'SAME' else '见旧报告')
            parsed_label = {
                'SAME': '已提取字段无差异', 'DIFF': '已提取字段有差异',
                'NOT_CHECKED': '解析字段未核对', 'NOT_APPLICABLE': '不适用结构化字段比较',
            }.get(parsed, '旧报告字段结论：' + parsed)
            label = {'liberty': 'Liberty', 'verilog': 'Verilog'}.get(row['file_type'], row['file_type'].upper())
            saved_at = datetime.fromisoformat(row['saved_at']).astimezone().strftime('%Y-%m-%d %H:%M')
            rendered.append(f"<tr><td><b>{ui.esc(label)}</b></td><td>{_source_pair(row)}</td><td><strong>{ui.esc(result)}</strong><small>{ui.esc(parsed_label)}</small><small>{ui.esc(cap.get('evidence_mode_label') or '证据能力未记录')}</small><small>{ui.esc(row['freshness'])}</small></td><td><b>{row['change_count']}</b> 项字段变化{detail}</td><td>{ui.esc(row['note'] or '未填写备注')}<small>{ui.esc(row['updated_by'])} · {ui.esc(saved_at)}</small></td><td class='check-report-links'>{links}</td></tr>")
            for item in row.get('history', []):
                summary = Path(item['evidence_dir']) / 'pairwise_summary.md'
                history_link = '历史摘要未保留'
                if summary.is_file():
                    history_relative = Path('representative') / row['file_type'] / item['evidence_id'] / 'pairwise_summary.md'
                    history_destination = Path(page).parent / history_relative
                    history_destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(summary, history_destination)
                    history_link = f"<a href='{ui.esc(history_relative.as_posix())}'>文字摘要</a>"
                history_rows.append('<tr>' + ''.join(f'<td>{value}</td>' for value in (
                    ui.esc(label), ui.esc(item.get('generated_at') or item.get('saved_at')),
                    ui.esc(item.get('base_version') or '未记录'),
                    ui.esc(Path(str(item.get('old_file') or '')).name) + ' → ' + ui.esc(Path(str(item.get('new_file') or '')).name),
                    history_link)) + '</tr>')
        content += "<div class='file-check-heading'><h3>代表文件深度核查</h3><span>已加入 " + str(len(rows)) + " 对文件</span></div><p>仅代表所选文件对；文件状态使用大小和修改时间核查，不表示已重新计算内容 Hash，也不代表整个视图通过。</p><div class='file-check-scroll'><table class='representative-check-table'><colgroup><col style='width:7%'><col style='width:27%'><col style='width:21%'><col style='width:15%'><col style='width:22%'><col style='width:8%'></colgroup><thead><tr><th>类型</th><th>所选文件</th><th>结果 / 证据范围</th><th>主要变化</th><th>人工备注</th><th>报告</th></tr></thead><tbody>" + ''.join(rendered) + '</tbody></table></div>'
        if history_rows:
            content += '<details><summary>历史核查摘要（' + str(len(history_rows)) + '）</summary><p>历史结果仅供追溯，不计入当前结论。</p>' + ui.table(
                ['类型', '生成时间', '基准版本', '文件对', '历史证据'], history_rows) + '</details>'
    if pairing.get('rows'):
        table_rows = [f"<tr><td>{ui.esc(item['name'])}</td><td>{ui.esc(item['relation'])}</td><td>{'<br>'.join(ui.esc(p) for p in item['liberty_files']) or '—'}</td><td>{'<br>'.join(ui.esc(p) for p in item['db_files']) or '—'}</td></tr>" for item in pairing['rows']]
        table = ui.faceted_table('lib-db-detail', ['名称', '对应情况', 'Liberty 原始路径', 'DB 原始路径'], table_rows, facets=[(1, '对应情况')], placeholder='搜索名称或原始路径', wrap_class='file-check-scroll')
        content += f"<details><summary>Liberty / DB 配套清单 · Liberty {pairing['liberty_count']} / DB {pairing['db_count']}</summary><p>{ui.esc(pairing['basis'])}</p>{table}</details>"
    return "<section id='file-checks' class='file-checks'><style>.file-checks{margin:16px 0;border-top:1px solid var(--line,#d0d5dd);padding-top:12px}.file-check-heading{display:flex;align-items:center;justify-content:space-between}.file-check-heading h3{margin:0}.file-check-heading span,.file-checks td small{color:var(--muted,#667085);font-size:12px}.file-checks td small{display:block;margin-top:5px}.file-check-scroll{max-height:360px;overflow:auto}.file-checks table{width:100%;border-collapse:collapse;font-size:13px}.representative-check-table{table-layout:fixed}.file-checks th,.file-checks td{padding:10px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line,#e4e7ec)}.file-checks th{position:sticky;top:0;background:var(--panel,#f8fafc)}.file-checks td{overflow-wrap:anywhere}.file-checks code{white-space:normal}.file-checks summary{cursor:pointer;padding:8px 0}.check-source-name{display:flex;gap:8px;align-items:baseline;margin:3px 0}.check-source-name span{color:var(--muted,#667085);flex-shrink:0}.check-source-name code{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}.check-paths>div{padding:6px 0}.check-paths code{display:block;overflow-wrap:anywhere}.check-paths button{margin-top:5px;font-size:12px}.check-report-links a{display:block;margin-bottom:6px}</style>" + content + '</section>'
