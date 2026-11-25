"""High-signal v3 8-sheet workbook model for path-mode CheckResult reports."""
from collections import Counter, defaultdict
from pathlib import Path

from ai_lib_qor.application.formal_comparison import compare_formal_member, formal_link_relation, latest_formal_snapshot

from .workbook_diff import (
    MAX_PARTIAL_DIFF_ROWS_PER_FILE,
    MAX_PIN_DIFF_ROWS_PER_CHECK,
    _fmt_signed,
    _nat_key,
    _norm_obj_name,
    _text,
    analyze_pin_match_check as _analyze_pin_match_check,
    build_deduped_pin_diff_rows as _build_deduped_pin_diff_rows,
    evidence_label,
    evidence_list_label,
    extract_corner_hint,
    format_lef_change,
    unpack_partial_diff as _unpack_partial_diff,
    unpack_plugin_findings,
)

_RUN_STATE_ZH = {
    'SUCCEEDED': '执行完成',
    'PARTIAL': '部分完成',
    'FAILED': '执行失败',
    'RUNNING': '运行中',
    'NOT_CHECKED': '未检查',
}


def _quality_verdict(report):
    from ai_lib_qor.checks.path_plugins import evaluate_check_verdict
    verdict = evaluate_check_verdict(report)
    return verdict['text'], verdict['code']


def _format_paths_cell(paths, max_show=3):
    uniq = sorted(set(paths))
    if not uniq:
        return ''
    if len(uniq) <= max_show:
        return '\n'.join(uniq)
    return '\n'.join(uniq[:max_show]) + f'\n… 共 {len(uniq)} 个文件'


def build_path_workbook_spec(report):
    """Build structured v3 8-sheet specification for a single path-mode CheckResult."""
    context = report['_path_context']
    index = context['index']
    facts = context['facts']
    acceptance = context.get('acceptance')
    facts_evidence = report.get('facts_evidence') or {}

    vendor = report.get('vendor') or index.get('vendor') or ''
    owner = report['library']
    revision = report['revision']
    baseline = report.get('baseline')
    is_prev_file_mode = (baseline == '__prev_file__')
    baseline_display = '按文件上一时间版本' if is_prev_file_mode else (baseline or '无基线')
    files = report.get('files') or []
    checks = report.get('checks') or []
    changes = report.get('changes') or []
    comparisons = report.get('comparisons') or []
    partial_comparisons = report.get('partial_comparisons') or []
    summary = report.get('summary') or {}

    parsed_by_key = {(f['view'], f['path']): f for f in files}
    comp_by_key = {(c['view'], c['path']): c for c in comparisons}
    partial_by_key = {(c['view'], c['path']): c for c in partial_comparisons}
    latest_nl_snap = latest_formal_snapshot(index)

    # --- Sheet 02: Unified File Version Matrix ---
    matrix_rows = []
    current_views = defaultdict(list)
    current_member_paths = {}
    src_counts = Counter()
    parse_counts = Counter()
    nl_match_count = 0
    nl_drift_count = 0
    total_raw_occ = 0

    for view, group in index.get('views', {}).items():
        for path, row in group.items():
            raw = row.get('raw') or []
            total_raw_occ += len(raw)
            current = next((x for x in row.get('effective', []) if x['revision'] == revision), None)
            if is_prev_file_mode:
                comp_hit = comp_by_key.get((view, path)) or partial_by_key.get((view, path))
                if comp_hit and comp_hit.get('baseline_version'):
                    before = {'version': comp_hit['baseline_version']}
                elif current is not None:
                    pos = next((i for i, r in enumerate(raw) if r.get('version') == current['version']), -1)
                    before = {'version': raw[pos - 1]['version']} if pos > 0 else None
                else:
                    before = None
            else:
                before = next((x for x in row.get('effective', []) if x['revision'] == baseline), None) if baseline else None
            item = parsed_by_key.get((view, path))

            in_curr = current is not None
            in_base = before is not None
            if in_curr:
                current_views[view].append(path)
                current_member_paths[(view, path)] = current['path']

            membership = '当前有效' if in_curr else ('仅基线移除' if in_base else '未纳入当前有效集')
            if in_curr and in_base:
                src_rel = '来源相同' if before['version'] == current['version'] else '来源变化'
            elif in_curr and not in_base:
                src_rel = '首版纳入' if (baseline is None or is_prev_file_mode) else '新增'
            elif not in_curr and in_base:
                src_rel = '移除'
            else:
                src_rel = '仅RAW存在'
            if in_curr or in_base:
                src_counts[src_rel] += 1

            if not in_curr:
                parse_lbl = '已移除' if in_base else '未纳入有效集'
            elif not item or item.get('status') == 'NOT_CHECKED':
                parse_lbl = (
                    '按配置跳过(NOT_CHECKED)'
                    if (item and ('liberty_parse_filter' in str(item.get('note', '')) or 'skip_parse_views' in str(item.get('note', ''))))
                    else '暂不支持(NOT_CHECKED)'
                )
                parse_counts['NOT_CHECKED'] += 1
            elif item.get('status') == 'FAILED':
                parse_lbl = '解析失败'
                parse_counts['FAILED'] += 1
            elif item.get('status') == 'PARSED':
                fobj = facts.get(item.get('facts')) or facts.get(Path(item['facts']).name) if item.get('facts') else None
                if item.get('facts') and not fobj:
                    parse_lbl = '证据不可用'
                    parse_counts['EVIDENCE_UNAVAILABLE'] += 1
                elif fobj and fobj.get('parse_status') == 'PARTIAL':
                    parse_lbl = '部分解析'
                    parse_counts['PARTIAL'] += 1
                else:
                    parse_lbl = '已解析'
                    parse_counts['PARSED'] += 1
            else:
                parse_lbl = str(item.get('status'))

            comp = comp_by_key.get((view, path))
            pcomp = partial_by_key.get((view, path))
            if comp:
                content_lbl = '内容变化' if comp.get('content_status') == 'CURRENT_CONTENT_DIFF' else '内容一致'
            elif pcomp:
                content_lbl = '部分差异' if pcomp.get('differences') else '部分一致'
            elif not in_curr:
                content_lbl = '未对比'
            elif baseline is None:
                content_lbl = '无基线未对比'
            else:
                content_lbl = '未对比'

            _, nl_lbl = compare_formal_member(latest_nl_snap, row['nl'], current)
            if nl_lbl == '来源相同':
                nl_match_count += 1
            elif nl_lbl == '来源不同':
                nl_drift_count += 1

            sort_key = (0 if in_curr else (1 if in_base else 2), view, path)
            matrix_rows.append((sort_key, [
                membership,
                view,
                path,
                src_rel,
                before['version'] if before else '无',
                current['version'] if current else '无',
                parse_lbl,
                content_lbl,
                nl_lbl,
                len(raw),
                raw[-1]['version'] if raw else '无',
                current['path'] if current else (raw[-1]['path'] if raw else ''),
            ]))
    matrix_rows.sort(key=lambda pair: pair[0])
    matrix_table = [r for _, r in matrix_rows]

    # --- Sheet 03: Structured & Multi-Corner-Deduplicated Object & Interface Differences ---
    diff_rows = []
    for ch in changes:
        fmt = format_lef_change(ch, facts_evidence)
        diff_rows.append([
            '跨版本LEF对比', ch.get('view', 'LEF'), ch.get('path', ''),
            fmt['object_type'], fmt['object_name'], fmt['diff_type'],
            fmt['old_text'], fmt['new_text'], fmt['note'], fmt['evidence'],
        ])

    partial_diff_files = 0
    for pitem in partial_comparisons:
        unpacked = _unpack_partial_diff(pitem, facts_evidence)
        if unpacked:
            partial_diff_files += 1
            diff_rows.extend(unpacked)

    fail_pin_checks = [q for q in checks if q.get('check_id') == 'LEF_LIBERTY_PIN_MATCH' and q.get('result') == 'FAIL']
    pin_diff_rows, pin_meta = _build_deduped_pin_diff_rows(fail_pin_checks, facts, facts_evidence)
    diff_rows.extend(pin_diff_rows)
    per_check_stats = dict(pin_meta['per_check_stats'])

    plugin_finding_rows, plugin_badges = unpack_plugin_findings(checks, facts_evidence)
    diff_rows.extend(plugin_finding_rows)
    for k, v in plugin_badges.items():
        per_check_stats.setdefault(k, v)

    # --- Sheet 01: Risks & Engineering Checks (severity-sorted, drill-down link + concise summary) ---
    severity_rank = {'FAIL': 0, 'FAILED': 0, 'INCONCLUSIVE': 1, 'PASS': 2}
    risk_items = []
    for row in files:
        if row.get('status') == 'FAILED':
            risk_items.append((
                0, '文件解析', f"PARSE_FAILED ({row['view']})", 'FAILED', 'FAILED',
                '—', row['path'], row.get('note') or '文件解析失败', '',
            ))
    for q in checks:
        res = q.get('result', 'INCONCLUSIVE')
        drill = '—'
        detail_txt = q.get('detail', '')
        if id(q) in per_check_stats:
            _, badge, clean_detail = per_check_stats[id(q)]
            drill = ('link', '03-对象与接口差异', badge)
            detail_txt = clean_detail
        elif res == 'FAIL' and diff_rows:
            drill = ('link', '03-对象与接口差异', '查看差异 →')
        risk_items.append((
            severity_rank.get(res, 1),
            '工程检查',
            q.get('check_id', ''),
            res,
            q.get('coverage', 'UNKNOWN'),
            drill,
            '\n'.join(q.get('scope_file_keys') or []),
            detail_txt,
            evidence_list_label(q.get('facts_refs') or [], facts_evidence),
        ))
    risk_items.sort(key=lambda x: (x[0], x[2], x[6]))
    risk_rows = [[idx, *item[1:]] for idx, item in enumerate(risk_items, 1)]

    # --- Sheets 04 / 05 / 06: MacroView Alignment + LEF Detail + Liberty Detail ---
    macro_entries = defaultdict(lambda: defaultdict(list))
    cdl_entries = defaultdict(list)
    cdl_instantiated = set()
    lef_sig_pin_counts = {}  # macro_name -> signal pin count (for Liberty cross-check column)
    lef_raw_records = []
    lib_raw_records = []
    view_status_map = defaultdict(set)

    for row in files:
        view_status_map[row['view']].add(row.get('status', 'NOT_CHECKED'))
        if row.get('status') != 'PARSED' or not row.get('facts'):
            continue
        fact = facts.get(row['facts']) or facts.get(Path(row['facts']).name)
        if not fact:
            continue
        view = row['view']
        obj = fact.get('objects') or {}
        ev_lbl = evidence_label(row['facts'], facts_evidence)

        if view == 'LEF':
            for m in obj.get('macros', []):
                name = m['name']
                macro_entries[name]['LEF'].append(row['path'])
                size = m.get('size_um') or [0.0, 0.0]
                w, h = float(size[0]), float(size[1])
                pins = m.get('pins') or []
                sig_pins = [p for p in pins if str(p.get('use') or '').upper() not in ('POWER', 'GROUND')]
                pg_pins = [p for p in pins if str(p.get('use') or '').upper() in ('POWER', 'GROUND')]
                lef_sig_pin_counts[name] = len(sig_pins)
                pg_names = sorted((p['name'] for p in pg_pins), key=_nat_key)
                if not pg_names:
                    pg_text = '无'
                elif len(pg_names) <= 8:
                    pg_text = ', '.join(pg_names)
                else:
                    pg_text = ', '.join(pg_names[:8]) + f' … 共{len(pg_names)}个'
                sig_dirs = Counter((p.get('direction') or 'UNKNOWN').upper() for p in sig_pins)
                dir_txt = ', '.join(f'{k} {v}' for k, v in sorted(sig_dirs.items())) or '无'
                lef_raw_records.append((
                    row['path'], row['version'], name,
                    round(w, 4), round(h, 4), round(w * h, 4),
                    round(w / h, 3) if h > 0 else 0.0,
                    len(pins), len(sig_pins), len(pg_pins),
                    pg_text, dir_txt, ', '.join(fact.get('covered_sections') or []), ev_lbl,
                ))
        elif view == 'LIBERTY':
            corner_hint = extract_corner_hint(row['path'])
            for c in obj.get('cells', []):
                name = c['name']
                macro_entries[name]['LIBERTY'].append(row['path'])
                pins = c.get('pins') or []
                dirs = Counter((p.get('direction') or 'UNKNOWN').upper() for p in pins)
                lib_raw_records.append((
                    row['path'], corner_hint, row['version'], name,
                    len(pins),
                    dirs.get('INPUT', 0), dirs.get('OUTPUT', 0), dirs.get('INOUT', 0),
                    sum(v for k, v in dirs.items() if k not in ('INPUT', 'OUTPUT', 'INOUT')),
                    '仅信号接口（未解析 PVT/PG/时序）', ev_lbl,
                ))
        elif view == 'VERILOG':
            for mod in obj.get('modules', []):
                name = mod.get('name')
                if name:
                    macro_entries[name]['VERILOG'].append(row['path'])
        elif view in ('CDL', 'SPICE'):
            for sub in obj.get('subcircuits', []):
                name = sub.get('name')
                if name:
                    cdl_entries[name].append(row['path'])
                    for inst in sub.get('instances') or []:
                        tgt = inst.get('target')
                        if tgt:
                            cdl_instantiated.add(tgt)

    # Finalize LEF rows with live Excel aspect-ratio formula (data starts at Excel Row 6!)
    lef_rows = []
    lef_sum_area = 0.0
    lef_sum_pins = lef_sum_sig = lef_sum_pg = 0
    for idx, rec in enumerate(lef_raw_records):
        erow = 6 + idx
        w, h, area, ratio = rec[3], rec[4], rec[5], rec[6]
        lef_sum_area += area
        lef_sum_pins += rec[7]
        lef_sum_sig += rec[8]
        lef_sum_pg += rec[9]
        lef_rows.append([
            rec[0], rec[1], rec[2], w, h,
            ('formula', f'=ROUND(D{erow}*E{erow},4)', area),
            ('formula', f'=IF(E{erow}>0,ROUND(D{erow}/E{erow},3),0)', ratio),
            rec[7], rec[8], rec[9], rec[10], rec[11], rec[12], rec[13],
        ])

    # Finalize Liberty rows with cross-check vs LEF signal pin count
    lib_rows = []
    lib_sum_sig = lib_sum_in = lib_sum_out = lib_sum_io = lib_sum_other = 0
    for rec in lib_raw_records:
        path, hint, ver, cname, sig_n, in_c, out_c, io_c, oth_c, cov, ev_lbl = rec
        lib_sum_sig += sig_n
        lib_sum_in += in_c
        lib_sum_out += out_c
        lib_sum_io += io_c
        lib_sum_other += oth_c
        lef_n = lef_sig_pin_counts.get(cname)
        if lef_n is None:
            vs_lef = '无匹配LEF'
        elif lef_n == sig_n:
            vs_lef = f'一致 ({sig_n}={lef_n})'
        else:
            vs_lef = f'差异 (Lib {sig_n} vs LEF {lef_n})'
        lib_rows.append([path, hint, ver, cname, sig_n, vs_lef, in_c, out_c, io_c, oth_c, cov, ev_lbl])

    # Filter CDL/SPICE internal transistor-level subcircuits cleanly
    primary_names = set(macro_entries.keys())
    filtered_internal_subckts = 0
    if primary_names:
        for name, paths in cdl_entries.items():
            if name in primary_names:
                macro_entries[name]['NETLIST'].extend(paths)
            else:
                filtered_internal_subckts += 1
    else:
        top_subckts = [n for n in cdl_entries if n not in cdl_instantiated] or list(cdl_entries.keys())
        filtered_internal_subckts = len(cdl_entries) - len(top_subckts)
        for name in top_subckts:
            macro_entries[name]['NETLIST'].extend(cdl_entries[name])

    def _view_cell_status(hit_paths, view_keys):
        if hit_paths:
            return _format_paths_cell(hit_paths, max_show=3)
        present = any(v in current_views for v in view_keys)
        if not present:
            return '无此View'
        statuses = set().union(*(view_status_map.get(v, set()) for v in view_keys))
        if 'FAILED' in statuses and 'PARSED' not in statuses:
            return '解析失败'
        if 'PARSED' in statuses:
            return '未命中同名对象'
        return '存在（未解析）'

    gds_status = f"存在（未解析，{len(current_views['GDS'])} 个文件）" if current_views.get('GDS') else '无此View'
    db_status = f"存在（未解析，{len(current_views['DB'])} 个文件）" if current_views.get('DB') else '无此View'
    parseable_present_groups = [
        grp for grp in (('LEF',), ('LIBERTY',), ('VERILOG',), ('CDL', 'SPICE'))
        if any(v in current_views for v in grp)
    ]
    denom = max(1, len(parseable_present_groups))

    macro_rows = []
    for name in sorted(macro_entries, key=_nat_key):
        vmap = macro_entries[name]
        hits = sum(1 for k in ('LEF', 'LIBERTY', 'VERILOG', 'NETLIST') if vmap.get(k))
        missing_views = []
        for lbl, key, vkeys in (('LEF', 'LEF', ('LEF',)), ('Liberty', 'LIBERTY', ('LIBERTY',)), ('Verilog', 'VERILOG', ('VERILOG',)), ('CDL/SPICE', 'NETLIST', ('CDL', 'SPICE'))):
            if any(v in current_views for v in vkeys) and not vmap.get(key):
                missing_views.append(lbl)
        align_note = '可解析视图同名齐全' if not missing_views else ('缺少同名对象: ' + ', '.join(missing_views))
        macro_rows.append([
            name,
            f'{hits}/{denom}',
            _view_cell_status(vmap.get('LEF'), ('LEF',)),
            _view_cell_status(vmap.get('LIBERTY'), ('LIBERTY',)),
            _view_cell_status(vmap.get('VERILOG'), ('VERILOG',)),
            _view_cell_status(vmap.get('NETLIST'), ('CDL', 'SPICE')),
            gds_status,
            db_status,
            align_note,
        ])

    # --- Sheet 07: Formal NL Links + FileFacts Pool Provenance ---
    formal_rows = []
    for view, group in index.get('views', {}).items():
        for path, row in group.items():
            curr_abs = current_member_paths.get((view, path))
            for link in row.get('nl') or []:
                rel_curr = formal_link_relation(link, {'path': curr_abs} if curr_abs else None)
                formal_rows.append([
                    link.get('version', ''),
                    link.get('observed_at', ''),
                    view,
                    path,
                    rel_curr,
                    link.get('source_match', ''),
                    link.get('link_path', ''),
                    link.get('link_target', ''),
                    link.get('resolved_path', ''),
                ])

    unavailable_refs = set(context.get('unavailable_facts') or [])
    provenance_rows = []
    seen_refs = set()
    for ref_id, ev in sorted(facts_evidence.items()):
        if not isinstance(ev, dict):
            continue
        seen_refs.add(ref_id)
        src = ev.get('source') or {}
        parser_info = ev.get('parser') or {}
        sha = ev.get('source_sha256') or ''
        provenance_rows.append([
            ref_id,
            ev.get('view', ''),
            src.get('relative_path', ''),
            src.get('version', ''),
            '证据不可用' if ref_id in unavailable_refs else ev.get('parse_status', ''),
            ev.get('pool_file') or '(内嵌/旧格式)',
            sha[:16] if sha else '未记录',
            f"{parser_info.get('name', '')} {parser_info.get('version', '')}".strip(),
            ', '.join(ev.get('covered_sections') or []),
        ])
    for row in files:
        ref_id = row.get('facts')
        if ref_id and ref_id not in seen_refs:
            fobj = facts.get(ref_id) or facts.get(Path(ref_id).name)
            if fobj:
                parser_info = fobj.get('parser') or {}
                provenance_rows.append([
                    ref_id, row['view'], row['path'], row['version'],
                    fobj.get('parse_status', ''), Path(ref_id).name, '未记录',
                    f"{parser_info.get('name', '')} {parser_info.get('version', '')}".strip(),
                    ', '.join(fobj.get('covered_sections') or []),
                ])

    # --- Sheet 00: Decision Overview (with Action Callout + Live Cross-Sheet Formulas) ---
    verdict_zh, verdict_code = _quality_verdict(report)
    run_state_zh = _RUN_STATE_ZH.get(report.get('state', ''), report.get('state', ''))
    latest_rev = index['revisions'][-1] if index.get('revisions') else '无'
    business_ip = report.get('business_ip')
    ip_type = report.get('ip_type')
    acc_pointer_name = f'accepted_effective__{business_ip}.json' if business_ip else 'accepted_effective.json'
    if isinstance(acceptance, dict):
        acc_rev = acceptance.get('accepted_revision')
        if acc_rev is None:
            acc_status = '尚未人工采纳'
        elif acc_rev == revision:
            acc_status = '当前版本已采纳'
        else:
            acc_status = f'已采纳 {acc_rev}（非本次检查版本）'
    else:
        acc_rev = None
        acc_status = f'未读取（请核对 {acc_pointer_name}）'

    pass_checks = sum(1 for q in checks if q.get('result') == 'PASS')
    fail_checks = summary.get('failed_checks', 0)
    inc_checks = summary.get('inconclusive_checks', 0)
    fail_files = summary.get('failed_files', 0)
    curr_total = sum(len(v) for v in current_views.values())
    track_scope = (
        f"  |  业务 IP: {business_ip}" + (f" ({ip_type})" if ip_type else "")
        if business_ip else ""
    )
    scope_line = f"供应商: {vendor or '未指定'}  |  库: {owner}{track_scope}  |  目标版本: {revision}  |  基线: {baseline_display}  |  执行时间: {report.get('run_at', '')}"

    # Action recommendation banner tailored to exact decision state
    if verdict_code == 'FAIL':
        dedup_hint = (
            f"（多 Corner 同构合并后 {pin_meta['dedup_total']} 条，原始 {pin_meta['raw_total']} 条）"
            if pin_meta['raw_total'] > pin_meta['dedup_total']
            else f"（共 {len(diff_rows)} 条差异）"
        )
        action_callout = (
            'fail',
            f"【阻塞 · 建议暂缓采纳】本次存在 {fail_checks} 项质检失败、{fail_files} 个文件解析失败{dedup_hint}。"
            f"请优先查看「01-风险与检查」与「03-对象与接口差异」，确认修复并重检后再行人工采纳。",
        )
    elif verdict_code == 'SCOPE_PASS' and acc_rev == revision:
        action_callout = (
            'ok',
            f"【已采纳放行】{revision} 已通过全部已覆盖范围检查，且与当前人工采纳指针 ({acc_pointer_name}) 一致。"
            f"若需检查未覆盖视图（GDS/DB/PVT/时序），请结合专项工具核验。",
        )
    elif verdict_code == 'SCOPE_PASS':
        accept_cmd = f"accept-revision --revision {revision}" + (f" --ip {business_ip}" if business_ip else "")
        action_callout = (
            'info',
            f"【可推进人工复核】已覆盖范围检查全部通过（通过 {pass_checks} / 失败 0）；"
            f"请确认「02-文件版本矩阵」中的覆盖范围与 Formal NL 状态无异议后，执行 {accept_cmd} 完成人工采纳。",
        )
    else:
        action_callout = (
            'warn',
            f"【部分覆盖 · 需人工核对边界】存在部分解析视图（{parse_counts['PARTIAL']} 个）、未解析视图（{parse_counts['NOT_CHECKED']} 个）或不确定检查（{inc_checks} 项）。"
            f"请核对「01-风险与检查」与「02-文件版本矩阵」覆盖缺口后再决策是否采纳。",
        )

    unavailable = context.get('unavailable_facts') or []
    if unavailable:
        action_callout = (
            'warn',
            f'证据不可用（{len(unavailable)} 份）。检查结论保留为原运行记录，'
            '请先核对缺失证据再决定是否采纳。',
        )

    risk_tab = '#DC2626' if (fail_checks > 0 or fail_files > 0) else ('#D97706' if inc_checks > 0 else '#16A34A')
    diff_tab = '#D97706' if diff_rows else '#64748B'

    diff_empty = (
        '无对比基线（未执行跨版本对象对比），且本版本 LEF/Liberty 信号 Pin 检查无异常差异。'
        if baseline is None else
        '本次基线对比及跨视图接口检查均未发现对象或引脚差异。'
    )
    diff_sub_extra = (
        f"  |  多 Corner Pin 差异已自动同构合并：原始 {pin_meta['raw_total']} 条 → {pin_meta['dedup_total']} 条"
        f"（角点特异性异常 {pin_meta['corner_specific']} 条）。"
        if pin_meta['raw_total'] > pin_meta['dedup_total']
        else '  |  包含跨版本 LEF 变更、网表部分接口差异及本版 LEF-Liberty 逐 Pin 不一致拆行。'
    )
    macro_sub = scope_line + (
        f'\n注：仅展示顶层对象对齐；CDL/SPICE 中另有 {filtered_internal_subckts} 个非顶层内部子电路已过滤，避免淹没顶层视图。'
        if filtered_internal_subckts else
        '\n注：仅基于本次已解析 FileFacts 的同名对象对齐；Verilog/CDL/SPICE 为部分解析，GDS/DB 仅反映有效集存在性。'
    )

    def _count_formula(sheet_name, col_let, start_excel_row, count):
        if count <= 0:
            return 0
        end_row = start_excel_row + count - 1
        return ('formula', f"=COUNTA('{sheet_name}'!{col_let}{start_excel_row}:{col_let}{end_row})", count)

    pin_dir_summary = (
        f"LEF/Lib Pin 异常 {pin_meta['dedup_total']}（原始 {pin_meta['raw_total']} 去重合并）"
        if pin_meta['raw_total'] > pin_meta['dedup_total']
        else f"LEF/Lib Pin 异常 {pin_meta['dedup_total']}"
    )
    directory_rows = [
        [('01-风险与检查', '01-风险与检查'), _count_formula('01-风险与检查', 'A', 5, len(risk_rows)),
         f"失败 {fail_checks} · 不确定 {inc_checks} · 文件失败 {fail_files} · 通过 {pass_checks}",
         '工程检查结论、文件解析故障与差异一键钻取（按严重度置顶）'],
        [('02-文件版本矩阵', '02-文件版本矩阵'), _count_formula('02-文件版本矩阵', 'C', 6, len(matrix_table)),
         f"当前有效 {curr_total} / 历史总文件 {len(matrix_table)} · 来源变更 {src_counts['来源变化']} · 新增 {src_counts['新增']} · 移除 {src_counts['移除']}",
         '单一权威文件清单：有效集归属、来源演进、内容结论、Formal NL 与 RAW 历史次数'],
        [('03-对象与接口差异', '03-对象与接口差异'), _count_formula('03-对象与接口差异', 'E', 5, len(diff_rows)),
         f"LEF对象变更 {len(changes)} · 网表部分差异文件 {partial_diff_files} · {pin_dir_summary}",
         '跨版本 Macro/Pin/网表变化与多 Corner 去重合并后的 LEF-Liberty 逐 Pin 差异'],
        [('04-MacroView对齐', '04-MacroView对齐'), _count_formula('04-MacroView对齐', 'A', 5, len(macro_rows)),
         f"顶层对象 {len(macro_rows)} 个" + (f"（已过滤 {filtered_internal_subckts} 个 CDL 内部子电路）" if filtered_internal_subckts else ''),
         '顶层 Macro/Cell 跨视图齐套矩阵与 GDS/DB 实际存在状态'],
        [('05-LEF宏明细', '05-LEF宏明细'), _count_formula('05-LEF宏明细', 'C', 6, len(lef_rows)),
         f"已解析 LEF Macro {len(lef_rows)} 个 · 面积合计 {lef_sum_area:,.2f} um² · 信号/PG Pin {lef_sum_sig}/{lef_sum_pg}",
         'LEF 物理尺寸、面积、宽高比公式、信号/PG Pin 拆分与 PG 引脚名'],
        [('06-Liberty单元明细', '06-Liberty单元明细'), _count_formula('06-Liberty单元明细', 'D', 6, len(lib_rows)),
         f"已解析 Liberty Cell {len(lib_rows)} 条 · 含文件名 Corner 提示与相对 LEF 信号 Pin 核对",
         'Liberty 信号接口明细、IN/OUT/INOUT 分布与相对 LEF 引脚数即时比对'],
        [('07-正式库与证据溯源', '07-正式库与证据溯源'), len(formal_rows) + len(provenance_rows),
         f"Formal 链接 {len(formal_rows)} 条（一致 {nl_match_count} / 漂移 {nl_drift_count}）· 共享池证据 {len(provenance_rows)} 份",
         'Formal NL 正式库软链对照与内容寻址 FileFacts 磁盘溯源清单'],
    ]

    title_owner = f'{owner} / {business_ip}' if business_ip else owner
    identity_cards = [
        ('供应商 (Vendor)', vendor or '未指定', '来源库 (Library)', owner),
    ]
    if business_ip:
        identity_cards.append(('业务 IP 轨道', business_ip, 'IP 类型 (ip_type)', ip_type or '未分类'))
    identity_cards.extend([
        ('目标有效版本', revision, '对比基线版本', baseline_display),
        ('质检结论', verdict_zh, '运行状态', run_state_zh),
        ('人工采纳状态', acc_status, '最新计算版本', latest_rev),
        ('Run ID', report['run_id'], '执行时间 (UTC)', report.get('run_at', '')),
    ])
    overview_spec = {
        'name': '00-决策概览',
        'kind': 'overview',
        'tab_color': '#1B365D',
        'title': f'IP 库质量检查决策报告 · {vendor + " / " if vendor else ""}{title_owner} ({revision})',
        'subtitle': f"Run ID: {report['run_id']}  |  执行时间: {report.get('run_at', '')}  |  本报告仅反映已保存 CheckResult 与归档记录，未检查项不视为通过。",
        'action_callout': action_callout,
        'identity_cards': identity_cards,
        'kpi_cards': [
            ('有效集成员总数', curr_total, '已解析 / 部分解析', f"{parse_counts['PARSED']} / {parse_counts['PARTIAL']}"),
            ('暂不支持 (NOT_CHECKED)', parse_counts['NOT_CHECKED'], '解析失败文件', fail_files),
            ('来源变化 / 新增 / 移除', f"{src_counts['来源变化']} / {src_counts['新增']} / {src_counts['移除']}" if baseline else '无基线', '确认内容变化文件', summary.get('files_with_confirmed_content_change', 0) if baseline else '无基线'),
            ('检查通过 / 失败 / 不确定', f'{pass_checks} / {fail_checks} / {inc_checks}', '对象与Pin差异（合并后）', len(diff_rows)),
            ('顶层 Macro/Cell 数', len(macro_rows), 'Formal NL 一致 / 漂移', f'{nl_match_count} / {nl_drift_count}'),
        ],
        'directory_headers': ['工作表（点击跳转）', '记录数', '关键指标摘要', '表内核心内容'],
        'directory_rows': directory_rows,
        'directory_col_specs': [
            {'kind': 'link', 'min_w': 22, 'max_w': 28},
            {'kind': 'int', 'min_w': 10, 'max_w': 12},
            {'kind': 'text', 'min_w': 36, 'max_w': 56},
            {'kind': 'text', 'min_w': 38, 'max_w': 58},
        ],
        'boundaries': [
            ('检查覆盖边界', report.get('note') or '仅覆盖已列出规则与已解析视图。'),
            ('整库质量与采纳红线', '运行 SUCCEEDED 或已覆盖检查 PASS 均不等于完整库全量通过（GDS/DB/PVT/时序等未检查），亦绝不自动等同于人工采纳（accepted_effective.json 独立维护）。'),
            ('来源与历史字节红线', '版本来源变化不等于内容变化；文件名 Corner 提示不等于业务身份确权；当前内容对比不证明历史交付期间字节未被原地改写。'),
        ],
        'verdict_code': verdict_code,
    }

    # Build dynamic SUBTOTAL bars for Sheets 02, 05, 06
    m_end = 5 + len(matrix_table)
    matrix_subtotal = (
        {
            'label': '动态筛选汇总（筛选下方任意列，可见文件数与累计交付数自动重算）：',
            'formulas': {
                2: (f'=SUBTOTAL(103,C6:C{m_end})', len(matrix_table), 'int'),
                9: (f'=SUBTOTAL(109,J6:J{m_end})', total_raw_occ, 'int'),
            },
        }
        if matrix_table else None
    )

    lef_end = 5 + len(lef_rows)
    lef_subtotal = (
        {
            'label': '动态筛选汇总（筛选后自动重算 Macro 数、面积、总/信号/PG Pin 合计）：',
            'formulas': {
                2: (f'=SUBTOTAL(103,C6:C{lef_end})', len(lef_rows), 'int'),
                5: (f'=SUBTOTAL(109,F6:F{lef_end})', round(lef_sum_area, 4), 'float'),
                7: (f'=SUBTOTAL(109,H6:H{lef_end})', lef_sum_pins, 'int'),
                8: (f'=SUBTOTAL(109,I6:I{lef_end})', lef_sum_sig, 'int'),
                9: (f'=SUBTOTAL(109,J6:J{lef_end})', lef_sum_pg, 'int'),
            },
        }
        if lef_rows else None
    )

    lib_end = 5 + len(lib_rows)
    lib_subtotal = (
        {
            'label': '动态筛选汇总（可按文件名 Corner 提示筛选，自动重算 Cell 与各方向信号 Pin 合计）：',
            'formulas': {
                3: (f'=SUBTOTAL(103,D6:D{lib_end})', len(lib_rows), 'int'),
                4: (f'=SUBTOTAL(109,E6:E{lib_end})', lib_sum_sig, 'int'),
                6: (f'=SUBTOTAL(109,G6:G{lib_end})', lib_sum_in, 'int'),
                7: (f'=SUBTOTAL(109,H6:H{lib_end})', lib_sum_out, 'int'),
                8: (f'=SUBTOTAL(109,I6:I{lib_end})', lib_sum_io, 'int'),
                9: (f'=SUBTOTAL(109,J6:J{lib_end})', lib_sum_other, 'int'),
            },
        }
        if lib_rows else None
    )

    table_sheets = [
        {
            'name': '01-风险与检查',
            'kind': 'table',
            'tab_color': risk_tab,
            'back_sheet': '00-决策概览',
            'title': f'01 · 工程检查与风险清单 — {owner} ({revision})',
            'subtitle': scope_line + '  |  按严重度置顶（FAIL / FAILED → INCONCLUSIVE → PASS）；点击「差异钻取」直达逐 Pin 明细。',
            'headers': ['序号', '类别', '检查项 / 问题ID', '结论', '覆盖度', '差异钻取', '涉及文件', '异常摘要 / 结论说明', '事实证据文件'],
            'rows': risk_rows,
            'col_specs': [
                {'kind': 'int', 'min_w': 8, 'max_w': 10},
                {'kind': 'center', 'min_w': 11, 'max_w': 14},
                {'kind': 'text', 'min_w': 24, 'max_w': 30},
                {'kind': 'status', 'min_w': 13, 'max_w': 16},
                {'kind': 'center', 'min_w': 12, 'max_w': 15},
                {'kind': 'link_center', 'min_w': 18, 'max_w': 26},
                {'kind': 'text', 'min_w': 32, 'max_w': 48},
                {'kind': 'text', 'min_w': 36, 'max_w': 56},
                {'kind': 'text', 'min_w': 28, 'max_w': 46},
            ],
            'empty_message': '本次检查未配置检查项且无文件解析失败。',
        },
        {
            'name': '02-文件版本矩阵',
            'kind': 'table',
            'tab_color': '#334155',
            'back_sheet': '00-决策概览',
            'subtotal': matrix_subtotal,
            'title': f'02 · 文件版本与状态矩阵 — {owner} ({revision} vs {baseline_display})',
            'subtitle': scope_line + '  |  当前有效集成员置顶；明确区分「未纳入当前有效集」与「暂不支持(NOT_CHECKED)」。',
            'headers': ['有效集归属', 'View', '相对路径', '来源关系', '基线来源版本', '目标来源版本', '解析状态', '内容对比结论', 'Formal NL 现状', 'RAW 版本数', 'RAW 最新版本', '目标 RAW 绝对路径'],
            'rows': matrix_table,
            'col_specs': [
                {'kind': 'status', 'min_w': 16, 'max_w': 20},
                {'kind': 'center', 'min_w': 11, 'max_w': 14},
                {'kind': 'text', 'min_w': 34, 'max_w': 50},
                {'kind': 'status', 'min_w': 12, 'max_w': 16},
                {'kind': 'center', 'min_w': 18, 'max_w': 24},
                {'kind': 'center', 'min_w': 18, 'max_w': 24},
                {'kind': 'status', 'min_w': 18, 'max_w': 22},
                {'kind': 'status', 'min_w': 14, 'max_w': 18},
                {'kind': 'status', 'min_w': 18, 'max_w': 24},
                {'kind': 'int', 'min_w': 11, 'max_w': 13},
                {'kind': 'center', 'min_w': 18, 'max_w': 24},
                {'kind': 'text', 'min_w': 32, 'max_w': 54},
            ],
            'empty_message': '当前库索引中暂无文件记录。',
        },
        {
            'name': '03-对象与接口差异',
            'kind': 'table',
            'tab_color': diff_tab,
            'back_sheet': '00-决策概览',
            'title': f'03 · 对象变化与接口差异明细 — {owner} ({revision} vs {baseline_display})',
            'subtitle': scope_line + diff_sub_extra,
            'headers': ['差异来源', 'View', '相对路径', '对象类型', '对象名称', '差异类型', '旧值 / LEF参考', '新值 / Liberty实测', '说明与变化量', '证据文件'],
            'rows': diff_rows,
            'col_specs': [
                {'kind': 'center', 'min_w': 15, 'max_w': 18},
                {'kind': 'center', 'min_w': 12, 'max_w': 18},
                {'kind': 'text', 'min_w': 30, 'max_w': 48},
                {'kind': 'center', 'min_w': 10, 'max_w': 14},
                {'kind': 'text', 'min_w': 24, 'max_w': 40},
                {'kind': 'status', 'min_w': 14, 'max_w': 18},
                {'kind': 'text', 'min_w': 16, 'max_w': 32},
                {'kind': 'text', 'min_w': 16, 'max_w': 32},
                {'kind': 'text', 'min_w': 34, 'max_w': 54},
                {'kind': 'text', 'min_w': 28, 'max_w': 48},
            ],
            'empty_message': diff_empty,
        },
        {
            'name': '04-MacroView对齐',
            'kind': 'table',
            'tab_color': '#0D9488',
            'back_sheet': '00-决策概览',
            'title': f'04 · 顶层对象 MacroView 对齐矩阵 — {owner} ({revision})',
            'subtitle': macro_sub,
            'headers': ['顶层对象 (Macro / Cell)', '视图齐套', 'LEF', 'Liberty', 'Verilog (部分)', 'CDL / SPICE (部分)', 'GDS (有效集状态)', 'DB (有效集状态)', '对齐说明'],
            'rows': macro_rows,
            'col_specs': [
                {'kind': 'text', 'min_w': 24, 'max_w': 38},
                {'kind': 'center', 'min_w': 11, 'max_w': 13},
                {'kind': 'text', 'min_w': 26, 'max_w': 44},
                {'kind': 'text', 'min_w': 28, 'max_w': 48},
                {'kind': 'text', 'min_w': 24, 'max_w': 40},
                {'kind': 'text', 'min_w': 24, 'max_w': 40},
                {'kind': 'status', 'min_w': 18, 'max_w': 24},
                {'kind': 'status', 'min_w': 14, 'max_w': 22},
                {'kind': 'status', 'min_w': 24, 'max_w': 40},
            ],
            'empty_message': '本次检查未解析到顶层 Macro / Cell / Module 对象。',
        },
        {
            'name': '05-LEF宏明细',
            'kind': 'table',
            'tab_color': '#475569',
            'back_sheet': '00-决策概览',
            'subtotal': lef_subtotal,
            'title': f'05 · LEF Macro 物理与引脚明细 — {owner} ({revision})',
            'subtitle': scope_line + '  |  面积与宽高比使用动态公式；PG 引脚名取自 LEF USE POWER/GROUND（LEF-Liberty 检查仅比对信号 Pin）。',
            'headers': ['相对路径', '来源版本', 'Macro 名称', '宽度 (um)', '高度 (um)', '面积 (um²)', '宽高比 (W/H)', '总 Pin 数', '信号 Pin 数', 'PG Pin 数', 'PG 引脚名', '信号方向分布', '解析覆盖范围', '共享池证据'],
            'rows': lef_rows,
            'col_specs': [
                {'kind': 'text', 'min_w': 26, 'max_w': 42},
                {'kind': 'center', 'min_w': 18, 'max_w': 22},
                {'kind': 'text', 'min_w': 22, 'max_w': 34},
                {'kind': 'float', 'min_w': 12, 'max_w': 15},
                {'kind': 'float', 'min_w': 12, 'max_w': 15},
                {'kind': 'float', 'min_w': 14, 'max_w': 18},
                {'kind': 'float', 'min_w': 13, 'max_w': 15},
                {'kind': 'int', 'min_w': 11, 'max_w': 13},
                {'kind': 'int', 'min_w': 12, 'max_w': 14},
                {'kind': 'int', 'min_w': 11, 'max_w': 13},
                {'kind': 'text', 'min_w': 14, 'max_w': 28},
                {'kind': 'text', 'min_w': 22, 'max_w': 34},
                {'kind': 'text', 'min_w': 26, 'max_w': 42},
                {'kind': 'text', 'min_w': 26, 'max_w': 40},
            ],
            'empty_message': '本次检查未解析到 LEF Macro 记录。',
        },
        {
            'name': '06-Liberty单元明细',
            'kind': 'table',
            'tab_color': '#475569',
            'back_sheet': '00-决策概览',
            'subtotal': lib_subtotal,
            'title': f'06 · Liberty Cell 信号接口明细 — {owner} ({revision})',
            'subtitle': scope_line + '\n注：「文件名 Corner 提示」仅从路径名提取供筛选参考，不等同于 Liberty operating_conditions 解析确权；当前未解析 PVT/PG/时序弧。',
            'headers': ['相对路径', '文件名 Corner 提示', '来源版本', 'Cell 名称', '信号 Pin 数', '相对 LEF 信号Pin', 'INPUT', 'OUTPUT', 'INOUT', '其他方向', '覆盖说明', '共享池证据'],
            'rows': lib_rows,
            'col_specs': [
                {'kind': 'text', 'min_w': 32, 'max_w': 48},
                {'kind': 'center', 'min_w': 18, 'max_w': 24},
                {'kind': 'center', 'min_w': 18, 'max_w': 22},
                {'kind': 'text', 'min_w': 22, 'max_w': 34},
                {'kind': 'int', 'min_w': 12, 'max_w': 14},
                {'kind': 'status', 'min_w': 18, 'max_w': 24},
                {'kind': 'int', 'min_w': 9, 'max_w': 11},
                {'kind': 'int', 'min_w': 10, 'max_w': 12},
                {'kind': 'int', 'min_w': 9, 'max_w': 11},
                {'kind': 'int', 'min_w': 10, 'max_w': 12},
                {'kind': 'text', 'min_w': 24, 'max_w': 32},
                {'kind': 'text', 'min_w': 26, 'max_w': 40},
            ],
            'empty_message': '本次检查未解析到 Liberty Cell 记录。',
        },
        {
            'name': '07-正式库与证据溯源',
            'kind': 'provenance',
            'tab_color': '#64748B',
            'back_sheet': '00-决策概览',
            'title': f'07 · Formal NL 正式链接与证据溯源 — {owner} ({revision})',
            'subtitle': scope_line + '  |  上表核对 Formal NL 软链相对当前有效版本的一致/漂移状态；下表映射本次解析所使用的内容寻址共享池文件。',
            'formal_headers': ['正式阶段', '观测时间', 'View', 'RAW 相对路径', '与当前有效集关系', '链接状态', '链接路径', '链接目标', '解析目标路径'],
            'formal_rows': formal_rows,
            'formal_col_specs': [
                {'kind': 'center', 'min_w': 12, 'max_w': 18},
                {'kind': 'center', 'min_w': 20, 'max_w': 24},
                {'kind': 'center', 'min_w': 11, 'max_w': 14},
                {'kind': 'text', 'min_w': 30, 'max_w': 44},
                {'kind': 'status', 'min_w': 18, 'max_w': 22},
                {'kind': 'status', 'min_w': 15, 'max_w': 18},
                {'kind': 'text', 'min_w': 28, 'max_w': 46},
                {'kind': 'text', 'min_w': 26, 'max_w': 44},
                {'kind': 'text', 'min_w': 28, 'max_w': 46},
            ],
            'formal_empty': '尚未在已扫描的 Formal NL 正式目录中发现该库的软链引用。',
            'prov_headers': ['逻辑引用', 'View', '相对路径', '来源版本', '解析状态', '共享池磁盘文件', '源文件 SHA-256 (前16位)', '解析器', '解析覆盖范围'],
            'prov_rows': provenance_rows,
            'prov_col_specs': [
                {'kind': 'text', 'min_w': 24, 'max_w': 36},
                {'kind': 'center', 'min_w': 11, 'max_w': 14},
                {'kind': 'text', 'min_w': 30, 'max_w': 44},
                {'kind': 'center', 'min_w': 18, 'max_w': 22},
                {'kind': 'status', 'min_w': 12, 'max_w': 16},
                {'kind': 'text', 'min_w': 28, 'max_w': 40},
                {'kind': 'center', 'min_w': 20, 'max_w': 22},
                {'kind': 'text', 'min_w': 24, 'max_w': 36},
                {'kind': 'text', 'min_w': 28, 'max_w': 46},
            ],
            'prov_empty': '本次检查未产生已解析的 FileFacts 证据。',
        },
    ]

    return {
        'properties': {
            'title': f'IP 库检查报告 · {owner} ({revision})',
            'subject': '路径式有效版本检查结论、文件矩阵与 FileFacts 证据',
        },
        'sheets': [overview_spec, *table_sheets],
    }


def build_path_sheets(report):
    """Flat (name, headers, rows) projection for inspection or tabular consumers."""
    spec = build_path_workbook_spec(report)
    out = []
    for sh in spec['sheets']:
        if sh['kind'] == 'overview':
            rows = [[k1, v1, k2, v2] for k1, v1, k2, v2 in sh['identity_cards']]
            rows.extend([[k1, v1, k2, v2] for k1, v1, k2, v2 in sh['kpi_cards']])
            out.append((sh['name'], ['字段', '值', '字段2', '值2'], rows))
        elif sh['kind'] == 'provenance':
            out.append((sh['name'], sh['formal_headers'], sh['formal_rows']))
        else:
            out.append((sh['name'], sh['headers'], sh['rows']))
    return out
