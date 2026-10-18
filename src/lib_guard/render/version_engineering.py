"""Desktop engineering tables for the shared version reader model."""

from pathlib import Path

from lib_guard.render import product_theme as ui
from lib_guard.view_types import view_label


STATUS = {'CHANGED': '确认变化', 'FAIL': '检查未通过', 'NOT_CHECKED': '尚未确认',
          'REVIEW_REQUIRED': '对应关系待确认', 'UNKNOWN': '证据不足',
          'INCOMPLETE': '未完成', 'AMBIGUOUS': '对应不唯一', 'SAME': '内容未变化'}


def _value(value):
    if value is None:
        return '未提取'
    if isinstance(value, bool):
        return '是' if value else '否'
    if isinstance(value, dict):
        return '；'.join(f'{key}：{_value(item)}' for key, item in list(value.items())[:6]) or '空'
    if isinstance(value, (list, tuple)):
        text = '；'.join(_value(item) for item in value[:6]) or '空'
        return text + (f'；另 {len(value) - 6} 项，见证据' if len(value) > 6 else '')
    return str(value)


def _path(path, label='原始文件'):
    if not path:
        return ''
    return (f"<details class='engineering-path'><summary>{ui.esc(label)}</summary>"
            f"<code>{ui.esc(path)}</code><button type='button' class='btn secondary' "
            f"aria-label='复制{ui.esc(label)}路径' data-path='{ui.esc(path)}' "
            "onclick='copyText(this.dataset.path,this)'>复制路径</button></details>")


def _port_dialog(obj, dialog_id):
    ports = obj.get('ports') or []
    rows = ['<tr>' + ''.join(f'<td>{ui.esc(_value(value))}</td>' for value in (
        item['name'], item.get('direction'), item.get('width'), item.get('use') or item.get('pg_type'), item.get('layers')))
            + '</tr>' for item in ports]
    return (f"<dialog id='{dialog_id}' class='engineering-port-dialog'><h3>{ui.esc(obj['name'])} · Pin / 端口</h3>"
            "<div class='engineering-pin-scroll'>" + ui.table(['名称', '方向', '位宽', '用途', '层'], rows)
            + "</div><form method='dialog'><button class='btn secondary'>关闭</button></form></dialog>")


def render_engineering_report(report, page):
    sources = report.get('sources') or []
    objects, source_rows, hrefs, dialogs = [], [], {}, []
    for source in sources:
        href = source.get('href') or ''
        hrefs[source['evidence']] = href
        scope = source['scope'] + ('' if source['current'] else ' · 历史提取')
        context = source.get('description') or '; '.join(_value(item) for item in source.get('contexts', []))
        if source['file_type'] == 'liberty':
            context += '；工作条件：' + '; '.join(_value(item) for item in source.get('contexts', []))
            context += '；时序单位：' + (_value(source.get('units')) if any((source.get('units') or {}).values()) else '未提取')
        link = f"<a href='{ui.esc(href)}'>详细对比</a>" if href else _path(source['evidence'], '提取证据路径')
        source_rows.append('<tr>' + ''.join(f'<td>{value}</td>' for value in (
            f"<b>{ui.esc(source['label'])}</b>",
            ui.esc(Path(source['source']).name) + _path(source['source']),
            f"{source['object_count']} 个对象 / {source['pin_count']} 个声明 Pin",
            ui.esc(scope), ui.esc(context or '见对象规格'),
            '<br>'.join(ui.esc(item) for item in source['limitations']) or '未记录额外限制', link)) + '</tr>')
        for obj in source['objects']:
            dialog_id = f'engineering-ports-{len(dialogs)}'
            dialogs.append(_port_dialog(obj, dialog_id))
            size = obj.get('size')
            dimensions = (f"{size.get('x', '未提取')} × {size.get('y', '未提取')} {obj['unit']}" if size
                          else f"面积字段 {_value(obj['area'])}" if obj.get('area') is not None else '未提取')
            objects.append('<tr>' + ''.join(f'<td>{value}</td>' for value in (
                ui.esc(source['label']), ui.esc(obj.get('library') or obj.get('class') or '未提取'),
                '<code>' + ui.esc(obj['name']) + '</code>', ui.esc(dimensions), ui.esc(obj.get('site') or '未提取'),
                f"<button type='button' class='btn secondary' onclick=\"document.getElementById('{dialog_id}').showModal()\">查看 {len(obj['ports'])} Pin</button>",
                ui.esc(Path(source['source']).name) + _path(source['source']),
                ui.esc('所选文件' if source['paired'] else '扫描提取') + ('' if source['current'] else ' · 历史'))) + '</tr>')

    source_table = ui.table(['视图', '文件', '已提取内容', '证据范围', '规格 / 工作条件', '检查限制', '证据'], source_rows,
                            '尚无可展示的技术提取结果；完成扫描后可查看已解析规格。')
    object_table = ui.faceted_table('engineering-objects', ['视图', '库名 / 类别', '对象', '尺寸 / 面积', 'Site', '接口', '来源文件', '范围'],
                                    objects, facets=[(0, '视图'), (1, '类别'), (7, '范围')],
                                    placeholder='搜索单元、模块、Site 或文件', wrap_class='engineering-scroll')
    finding_rows = []
    for item in report.get('findings', []):
        evidence = hrefs.get(item.get('evidence')) or item.get('href') or ''
        link = f"<a href='{ui.esc(evidence)}'>详细证据</a>" if evidence else _path(item.get('evidence'), '检查证据路径')
        finding_rows.append('<tr>' + ''.join(f'<td>{value}</td>' for value in (
            '<code>' + ui.esc(item['object']) + '</code>', ui.esc(item['label']),
            ui.esc(_value(item.get('old'))), ui.esc(_value(item.get('new'))),
            ui.badge('WARNING' if item['status'] in {'CHANGED', 'FAIL'} else 'INFO', STATUS.get(item['status'], '需核对')),
            ui.esc(item['scope']), ui.esc(item['advice']), link + _path(item.get('source')))) + '</tr>')
    findings = (ui.faceted_table('engineering-findings', ['对象', '检查项', '旧值', '新值', '结论', '证据范围', '接入关注点', '来源'],
                                 finding_rows, facets=[(1, '检查项'), (4, '结论')],
                                 placeholder='搜索对象、Pin、检查项或文件', wrap_class='engineering-scroll')
                if finding_rows else '<p class="engineering-empty">当前已展示的检查结果中，没有已确认的工程变化；未检查范围见下方。</p>')
    limitations = '<ul>' + ''.join('<li>' + ui.esc(item) + '</li>' for item in report.get('limitations', [])) + '</ul>'
    delivery = report.get('delivery') or {}
    missing = '、'.join(str(value) for value in delivery.get('missing', []))
    contract = ("<div class='engineering-delivery'><b>现有配置要求</b><span>" + ui.esc('、'.join(delivery.get('required_views') or []) or '未配置必需视图') + '</span>'
                + (f"<span>缺失：{ui.esc(missing)}</span>" if missing else '') + '</div>')
    coverage_rows = []
    for evidence in delivery.get('required_view_evidence', []):
        status = str(evidence.get('status') or '')
        if evidence.get('validation_level') == 'metadata_required':
            file_evidence = '文件已发现；未要求深度解析' if status in {'PASS', 'FOUND'} else '元数据核查未通过'
        else:
            file_evidence = f"{evidence.get('satisfied', 0)} / {evidence.get('total', 0)} 文件满足检查口径"
        coverage_rows.append('<tr>' + ''.join(f'<td>{ui.esc(_value(value))}</td>' for value in (
            view_label(evidence.get('view')), '必需视图', {'PASS': '已满足', 'FOUND': '已发现', 'BLOCK': '未满足'}.get(status, status),
            file_evidence,
            evidence.get('incomplete_files') or evidence.get('message') or '无已记录缺口')) + '</tr>')
    for key, label in (('modes', 'Mode / 模式'), ('corners', 'Corner / 工艺角')):
        context = (delivery.get('delivery_requirements') or {}).get(key) or {}
        coverage_rows.append('<tr>' + ''.join(f'<td>{ui.esc(_value(value))}</td>' for value in (
            label, context.get('required') or '未配置', context.get('observed') or '无已确认记录',
            context.get('candidate_hints') or '无线索', context.get('missing') or '无已记录缺口')) + '</tr>')
    coverage = '<details class="engineering-limits"><summary>交付要求与覆盖明细</summary>' + ui.table(
        ['视图 / 上下文', '要求', '已确认 / 状态', '文件证据 / 候选线索', '缺口或说明'], coverage_rows) + '</details>'
    combination = report.get('combination') or {}
    combination_strip = ''
    if combination:
        order = combination.get('components') or []
        composition = 'FULL ' + str(order[0]) + (' + 增量 ' + ' → '.join(str(value) for value in order[1:]) if len(order) > 1 else '') if order else '组成未记录'
        combination_strip = '<p class="engineering-combination">' + ui.esc(
            f"检查对象：完整组合 {combination.get('effective_id') or '未记录'}；{composition}；"
            f"基准组合：{combination.get('base_effective_id') or '未选择'}；方案：{combination.get('profile') or '未记录'}；"
            f"记录时间：{combination.get('published_at') or '未记录'}"
        ) + ('' if combination.get('status') == 'CURRENT' else '；历史结果未计入当前结论') + '</p>'
    return (
        "<style>"
        ".engineering-section{margin:0 0 18px;background:#fff;border-top:2px solid #288477;padding:14px 16px}"
        ".engineering-section h2{margin:0 0 12px;font-size:17px}.engineering-section h3{font-size:14px;margin:16px 0 8px}"
        ".engineering-section h2{padding-bottom:9px;border-bottom:1px solid #dce5e1}"
        ".engineering-source-list,.engineering-object-list{border-top:1px solid #e2e9e6;padding:9px 0}"
        ".engineering-source-list summary,.engineering-object-list summary{cursor:pointer;color:#235b51;font-size:13px;font-weight:700}"
        ".engineering-object-list[open] summary,.engineering-source-list[open] summary{margin-bottom:10px}"
        ".engineering-source-overview{display:flex;gap:14px;flex-wrap:wrap;margin:8px 0 10px;font-size:12px;color:#526574}"
        ".engineering-source-overview strong{color:#172d33;font-size:13px}.engineering-empty{margin:0 0 8px;color:#526574;font-size:13px}"
        ".engineering-section table{width:100%;table-layout:fixed}.engineering-section td{vertical-align:top;font-size:12px;overflow-wrap:anywhere}"
        ".engineering-section th{font-size:12px}.engineering-section code{font-size:11px;overflow-wrap:anywhere}"
        "#engineering-objects th:nth-child(3){width:24%}#engineering-objects th:nth-child(7){width:18%}"
        "#engineering-objects th:nth-child(4){width:13%}.engineering-combination{font-size:12px;padding:8px 0;color:#526574}"
        ".engineering-scroll{max-height:420px;overflow:auto;border:1px solid #dce3e8;scrollbar-gutter:stable}"
        ".engineering-scroll thead{position:sticky;top:0;background:#edf3f5;z-index:2}"
        ".engineering-section .table-tools{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:8px 0}"
        ".engineering-section .table-tools .search{display:flex;align-items:center;gap:8px;min-width:280px;flex:1}"
        ".engineering-section .table-tools .search span{flex:0 0 auto;white-space:nowrap}"
        ".engineering-section .table-tools .search input{min-width:0;flex:1}.engineering-section .table-count{white-space:nowrap}"
        ".engineering-section .facet-selects{display:flex;gap:6px}.engineering-section .facet-selects select{max-width:190px}"
        ".engineering-path{margin-top:5px}.engineering-path summary,.engineering-ports summary{color:#126c65;cursor:pointer;font-size:12px}"
        ".engineering-path code{display:block;margin:6px 0;user-select:all}.engineering-path button{min-height:25px;padding:3px 7px}"
        ".engineering-port-dialog{width:760px;max-width:85vw;border:1px solid #b9c9ce;border-radius:6px;padding:18px;color:#243746}"
        ".engineering-port-dialog::backdrop{background:#102e3a77}.engineering-port-dialog h3{margin:0 0 12px}.engineering-port-dialog form{text-align:right;margin-top:10px}"
        ".engineering-pin-scroll{max-height:55vh;overflow:auto;background:#fff}.engineering-pin-scroll thead{position:sticky;top:0;background:#edf3f5}"
        ".reader-file-sources>summary{padding:12px 16px;background:#eaf0f2;border-top:1px solid #bccdd3;font-size:15px;font-weight:700;cursor:pointer}"
        ".reader-file-sources[open]>summary{margin-bottom:12px}"
        ".engineering-delivery{display:flex;gap:12px;flex-wrap:wrap;padding:9px 0;margin-bottom:6px;border-bottom:1px solid #e3e8ec;font-size:13px}"
        ".engineering-limits{font-size:12px;color:#526574;margin-top:10px}.engineering-limits ul{margin:7px 0;padding-left:20px}"
        "</style>"
        '<section id="engineering-content" data-section="engineering-overview" class="engineering-section"><h2>库内容概览</h2>'
        + contract + coverage
        + '<div class="engineering-source-overview"><strong>'
        + ui.esc('；'.join(f"{source['label']}：{source['object_count']} 个对象 / {source['pin_count']} 个声明 Pin"
                          for source in sources[:3]) or '暂无已解析对象')
        + '</strong><span>仅覆盖下列已提取文件；不代表整库</span></div>'
        + '<details class="engineering-source-list"><summary>查看提取文件与检查限制</summary>' + source_table + '</details>'
        + '<details class="engineering-object-list"><summary>查看对象与接口规格（'
        + str(len(objects)) + ' 项）</summary>' + object_table + '</details>' + ''.join(dialogs) + '</section>'
        '<section id="engineering-results" data-section="engineering-findings" class="engineering-section"><h2>工程变化与检查结果</h2>'
        + combination_strip + findings + '<details class="engineering-limits"><summary>尚未确认的范围</summary>' + limitations + '</details></section>'
    )


def engineering_markdown(report):
    def cell(value):
        return _value(value).replace('|', '\\|').replace('\n', ' ')
    lines = ['## 工程阅读摘要', '', report.get('delivery_summary') or '交付要求待确认', '']
    lines += ['- ' + item for item in report.get('key_facts', [])]
    lines += ['', '## 库内容概览', '', '| 视图 | 来源文件 | 对象 | 声明 Pin | 范围 |', '| --- | --- | --- | --- | --- |']
    for source in report.get('sources', []):
        lines.append('| ' + ' | '.join(cell(value) for value in (source['label'], source['source'], source['object_count'], source['pin_count'], source['scope'])) + ' |')
    lines += ['', '## 工程变化与检查结果', '', '| 对象 | 检查项 | 旧值 | 新值 | 结论 | 接入关注点 |', '| --- | --- | --- | --- | --- | --- |']
    for item in report.get('findings', [])[:120]:
        lines.append('| ' + ' | '.join(cell(value) for value in (item['object'], item['label'], item.get('old'), item.get('new'), STATUS.get(item['status'], '待核对'), item['advice'])) + ' |')
    if not report.get('findings'):
        lines.append('尚无已确认的工程变化，检查范围见上方；这不代表整库已完成检查。')
    if len(report.get('findings', [])) > 120:
        lines.append('此处列出前 120 行，完整表格见同目录 index.html 的工程检查区。')
    lines += ['', '## 未确认范围', ''] + ['- ' + item for item in report.get('limitations', [])]
    lines += ['', '处理联系：' + str(report.get('contact') or '未登记'), '', '---', '', '## 文件与来源', '']
    return '\n'.join(lines)
