"""Structured diff unpacking, multi-corner pin deduplication, and evidence formatting for Excel reports."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import re

MAX_PIN_DIFF_ROWS_PER_CHECK = 500
MAX_PARTIAL_DIFF_ROWS_PER_FILE = 500
MAX_PLUGIN_FINDINGS_PER_CHECK = 500

_NAT_SPLIT_RE = re.compile(r'(\d+)')
_CORNER_HINT_RE = re.compile(
    r'(?:^|[_\-.])((?:ssg|ffg|ttg|ffpg|sspg|fast|slow|typ|tt|ss|ff|sf|fs)'
    r'(?:[_-](?:[mn]?\d+(?:p\d+)?[vVcC]|\d+[vVpP]\d+[vV]?|[mn]?\d+C|\d+c)){0,3})'
    r'(?=$|[_\-.])',
    re.IGNORECASE,
)


def _nat_key(text: str):
    """Natural sort key so bus pins sort as A_DIN[0], A_DIN[1], ..., A_DIN[15]."""
    return [int(part) if part.isdigit() else part.casefold() for part in _NAT_SPLIT_RE.split(str(text))]


def _fmt_signed(delta: float) -> str:
    if abs(delta) < 1e-12:
        return '0'
    return f'{delta:+.4g}'


def _norm_obj_name(name: str) -> str:
    if '/' in name and ' / ' not in name:
        return ' / '.join(part.strip() for part in name.split('/', 1))
    return name


def _text(value):
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def extract_corner_hint(rel_path: str) -> str:
    """Best-effort filename corner hint for filtering only (never authoritative PVT identity)."""
    name = Path(str(rel_path)).name
    if name.lower().endswith('.gz'):
        name = name[:-3]
    stem = Path(name).stem
    m = _CORNER_HINT_RE.search(stem)
    return m.group(1) if m else '未识别'


def evidence_label(ref, facts_evidence):
    """Resolve an internal logical fact ref (fact_<uuid>) to its real disk artifact or readable source label."""
    if not ref:
        return ''
    ev = (facts_evidence or {}).get(ref) or (facts_evidence or {}).get(Path(str(ref)).name)
    if isinstance(ev, dict):
        if ev.get('pool_file'):
            return ev['pool_file']
        src = ev.get('source') or {}
        rel = src.get('relative_path')
        view = ev.get('view')
        if rel and view:
            return f'(内嵌) {view}:{Path(rel).name}'
    return Path(str(ref)).name


def evidence_list_label(refs, facts_evidence):
    seen = []
    for r in refs or []:
        lbl = evidence_label(r, facts_evidence)
        if lbl and lbl not in seen:
            seen.append(lbl)
    if len(seen) > 4:
        return '\n'.join(seen[:4]) + f'\n… 共 {len(seen)} 份证据'
    return '\n'.join(seen)


def format_lef_change(ch, facts_evidence):
    """Format one LEF_MACRO_DIFF change dict into clean human-readable fields."""
    attr = ch.get('attribute', '')
    obj_type = ch.get('object_type', '')
    obj_name = _norm_obj_name(ch.get('object_name', ''))
    old_v = ch.get('old_value')
    new_v = ch.get('new_value')
    ev_lbl = evidence_list_label(ch.get('facts_refs') or [], facts_evidence)
    ver_span = f"{ch.get('baseline_version', '')} → {ch.get('version', '')}" if ch.get('baseline_version') else ''

    if attr == 'SIZE' and isinstance(old_v, list) and isinstance(new_v, list) and len(old_v) == 2 and len(new_v) == 2:
        w1, h1 = float(old_v[0]), float(old_v[1])
        w2, h2 = float(new_v[0]), float(new_v[1])
        a1, a2 = w1 * h1, w2 * h2
        pct = f'{((a2 - a1) / a1 * 100):+.2f}%' if a1 else 'N/A'
        return {
            'object_type': obj_type,
            'object_name': obj_name,
            'diff_type': '尺寸变化',
            'old_text': f'{w1:g} × {h1:g} um',
            'new_text': f'{w2:g} × {h2:g} um',
            'note': f'ΔW {_fmt_signed(w2 - w1)} um, ΔH {_fmt_signed(h2 - h1)} um, 面积 {a1:.3f} → {a2:.3f} um² ({pct})',
            'evidence': ev_lbl,
        }
    if attr == 'PRESENCE':
        label = ('新增 Macro' if new_v else '移除 Macro') if obj_type == 'MACRO' else ('新增 Pin' if new_v else '移除 Pin')
        return {
            'object_type': obj_type,
            'object_name': obj_name,
            'diff_type': label,
            'old_text': '存在' if old_v else '不存在',
            'new_text': '存在' if new_v else '不存在',
            'note': ver_span,
            'evidence': ev_lbl,
        }
    if attr == 'DIRECTION':
        return {
            'object_type': obj_type,
            'object_name': obj_name,
            'diff_type': 'Pin 方向变更',
            'old_text': str(old_v).upper(),
            'new_text': str(new_v).upper(),
            'note': ver_span,
            'evidence': ev_lbl,
        }
    return {
        'object_type': obj_type,
        'object_name': obj_name,
        'diff_type': attr or '变更',
        'old_text': _text(old_v),
        'new_text': _text(new_v),
        'note': ch.get('unit') or ver_span,
        'evidence': ev_lbl,
    }


def analyze_pin_match_check(check, facts):
    """Extract structured per-pin mismatch records and concise summary for one failing LEF_LIBERTY_PIN_MATCH check."""
    refs = check.get('facts_refs') or []
    scope = check.get('scope_file_keys') or []
    if len(refs) != 2:
        return None
    lef_fact = facts.get(refs[0]) or facts.get(Path(refs[0]).name)
    lib_fact = facts.get(refs[1]) or facts.get(Path(refs[1]).name)
    if not lef_fact or not lib_fact or lef_fact.get('view') != 'LEF' or lib_fact.get('view') != 'LIBERTY':
        return None
    lef_path = scope[0] if len(scope) >= 1 else (lef_fact.get('source') or {}).get('relative_path', '')
    lib_path = scope[1] if len(scope) >= 2 else (lib_fact.get('source') or {}).get('relative_path', '')
    macros = {m['name']: m for m in lef_fact.get('objects', {}).get('macros', [])}
    cells = {c['name']: c for c in lib_fact.get('objects', {}).get('cells', [])}
    items = []
    counts = Counter()
    sample_pins = []
    for name in sorted(macros, key=_nat_key):
        if name not in cells:
            counts['Cell缺失'] += 1
            items.append((lef_path, 'CELL', name, 'Cell缺失', 'LEF存在', 'Liberty缺失', 'Liberty 中未找到同名 Cell'))
            continue
        lp = {
            p['name']: (p.get('direction') or '').upper()
            for p in macros[name].get('pins', [])
            if str(p.get('use') or '').upper() not in ('POWER', 'GROUND')
        }
        bp = {
            p['name']: (p.get('direction') or '').upper()
            for p in cells[name].get('pins', [])
        }
        for pin in sorted(set(lp) - set(bp), key=_nat_key):
            counts['Pin缺失'] += 1
            if len(sample_pins) < 8:
                sample_pins.append(f'-{pin}')
            items.append((lef_path, 'PIN', f'{name} / {pin}', 'Pin缺失', lp[pin], '缺失', 'LEF 信号 Pin 在 Liberty 中缺失'))
        for pin in sorted(set(bp) - set(lp), key=_nat_key):
            counts['Pin多余'] += 1
            if len(sample_pins) < 8:
                sample_pins.append(f'+{pin}')
            items.append((lef_path, 'PIN', f'{name} / {pin}', 'Pin多余', '无', bp[pin], 'Liberty 信号 Pin 在 LEF 中不存在'))
        for pin in sorted(set(lp) & set(bp), key=_nat_key):
            if lp[pin] != bp[pin]:
                counts['方向冲突'] += 1
                if len(sample_pins) < 8:
                    sample_pins.append(f'{pin}({lp[pin]}→{bp[pin]})')
                items.append((lef_path, 'PIN', f'{name} / {pin}', '方向冲突', lp[pin], bp[pin], f'方向不一致 ({lp[pin]} → {bp[pin]})'))
    return {
        'lef_path': lef_path,
        'lib_path': lib_path,
        'refs': refs,
        'items': items,
        'counts': counts,
        'sample_pins': sample_pins,
    }


def build_deduped_pin_diff_rows(fail_checks, facts, facts_evidence):
    """Deduplicate identical LEF vs Liberty pin mismatches across multiple Liberty corner files."""
    parsed_analyses = []
    libs_by_lef = defaultdict(list)
    fallback_rows = []
    per_check_stats = {}

    for q in fail_checks:
        ana = analyze_pin_match_check(q, facts)
        if not ana or not ana['items']:
            scope = q.get('scope_file_keys') or []
            ev_lbl = evidence_list_label(q.get('facts_refs') or [], facts_evidence)
            fallback_rows.append([
                '跨视图Pin核验', 'LEF vs LIBERTY', '\n'.join(scope), 'CHECK',
                q.get('check_id', ''), '不一致', '', '', q.get('detail', ''), ev_lbl,
            ])
            per_check_stats[id(q)] = (1, '查看差异 →', q.get('detail', ''))
            continue
        parsed_analyses.append((q, ana))
        if ana['lib_path'] not in libs_by_lef[ana['lef_path']]:
            libs_by_lef[ana['lef_path']].append(ana['lib_path'])
        c = ana['counts']
        parts = []
        if c['Cell缺失']:
            parts.append(f"缺Cell {c['Cell缺失']}")
        if c['Pin缺失']:
            parts.append(f"缺Pin {c['Pin缺失']}")
        if c['Pin多余']:
            parts.append(f"多Pin {c['Pin多余']}")
        if c['方向冲突']:
            parts.append(f"方向冲突 {c['方向冲突']}")
        total_cnt = len(ana['items'])
        badge = f"{' / '.join(parts)} →" if parts else f'{total_cnt} 项差异 →'
        if total_cnt > 12:
            sample = ', '.join(ana['sample_pins'])
            clean_detail = f"共 {total_cnt} 项不匹配（{'，'.join(parts)}）；示例: {sample} … 详见「03-对象与接口差异」"
        else:
            clean_detail = q.get('detail', '')
        per_check_stats[id(q)] = (total_cnt, badge, clean_detail)

    grouped = {}
    raw_total = 0
    order_seq = 0
    for _, ana in parsed_analyses:
        for item in ana['items']:
            raw_total += 1
            if item not in grouped:
                grouped[item] = {'libs': [], 'refs': [], 'order': order_seq}
                order_seq += 1
            entry = grouped[item]
            if ana['lib_path'] not in entry['libs']:
                entry['libs'].append(ana['lib_path'])
            for r in ana['refs']:
                if r not in entry['refs']:
                    entry['refs'].append(r)

    rows = list(fallback_rows)
    overflow = 0
    corner_specific = 0
    sorted_keys = sorted(grouped.keys(), key=lambda it: (it[0], _nat_key(it[2]), it[3]))
    for item in sorted_keys:
        lef_path, obj_type, obj_name, diff_type, old_v, new_v, base_note = item
        info = grouped[item]
        all_libs = libs_by_lef[lef_path]
        hit_libs = info['libs']
        total_libs = len(all_libs)
        hit_n = len(hit_libs)

        if total_libs == 1:
            pair_path = f'{lef_path} ↔ {hit_libs[0]}'
            note = base_note
        elif hit_n == total_libs:
            hints = [h for h in (extract_corner_hint(p) for p in hit_libs) if h != '未识别']
            if hints:
                hint_str = ', '.join(hints[:3]) + (f' 等{len(hints)}角' if len(hints) > 3 else '')
            else:
                hint_str = ''
            pair_path = f'{lef_path} ↔ 全部 {total_libs} 个 Liberty' + (f'\n({hint_str})' if hint_str else '')
            note = f'{base_note}（影响全部 {hit_n}/{total_libs} 个配对 Liberty 文件）'
        else:
            corner_specific += 1
            short_libs = ', '.join(Path(p).name for p in hit_libs[:2]) + (f' 等{hit_n}个' if hit_n > 2 else '')
            pair_path = f'{lef_path} ↔ 仅 {hit_n}/{total_libs} 个 Liberty: {short_libs}'
            note = f'{base_note}（角点特异性异常：仅影响 {hit_n}/{total_libs} 个 Liberty）'

        ev_lbl = evidence_list_label(info['refs'], facts_evidence)
        if len(rows) < MAX_PIN_DIFF_ROWS_PER_CHECK:
            rows.append(['跨视图Pin核验', 'LEF vs LIBERTY', pair_path, obj_type, obj_name, diff_type, old_v, new_v, note, ev_lbl])
        else:
            overflow += 1

    if overflow:
        rows.append([
            '跨视图Pin核验', 'LEF vs LIBERTY', '多文件汇总', 'SUMMARY', '折叠提示', '存在差异',
            '', '', f'… 其余 {overflow} 条去重后 Pin 差异已折叠，完整列表见 CheckResult JSON', '',
        ])

    meta = {
        'raw_total': raw_total + len(fallback_rows),
        'dedup_total': len(rows),
        'corner_specific': corner_specific,
        'per_check_stats': per_check_stats,
    }
    return rows, meta


def unpack_partial_diff(item, facts_evidence):
    """Unpack Verilog / CDL / SPICE / custom partial_comparisons JSON dict into clean readable rows."""
    view = item.get('view', '')
    path = item.get('path', '')
    diffs = item.get('differences') or {}
    ev_label = evidence_list_label(item.get('facts_refs') or [], facts_evidence)
    if not diffs:
        return []
    rows = []
    overflow = 0
    is_verilog = view == 'VERILOG'
    obj_kind = 'MODULE' if is_verilog else ('SUBCKT' if view in ('CDL', 'SPICE') else 'OBJECT')

    def push(row):
        nonlocal overflow
        if len(rows) < MAX_PARTIAL_DIFF_ROWS_PER_FILE:
            rows.append(row)
        else:
            overflow += 1

    for name in sorted(diffs.get('added') or [], key=_nat_key):
        push(['网表部分对比', view, path, obj_kind, name, '新增 Module' if is_verilog else '新增对象', '不存在', '存在', '轻量接口观察（PARTIAL）', ev_label])
    for name in sorted(diffs.get('removed') or [], key=_nat_key):
        push(['网表部分对比', view, path, obj_kind, name, '移除 Module' if is_verilog else '移除对象', '存在', '不存在', '轻量接口观察（PARTIAL）', ev_label])

    changed = diffs.get('changed') or {}
    for name, detail in sorted(changed.items(), key=lambda kv: _nat_key(kv[0])):
        if is_verilog and isinstance(detail, dict) and isinstance(detail.get('ports'), dict):
            ports = detail['ports']
            for p in sorted(ports.get('added') or [], key=_nat_key):
                push(['网表部分对比', view, path, 'PORT', f'{name} / {p}', '新增端口', '不存在', '存在', '轻量接口观察（PARTIAL）', ev_label])
            for p in sorted(ports.get('removed') or [], key=_nat_key):
                push(['网表部分对比', view, path, 'PORT', f'{name} / {p}', '移除端口', '存在', '不存在', '轻量接口观察（PARTIAL）', ev_label])
            for p, attrs in sorted((ports.get('changed') or {}).items(), key=lambda kv: _nat_key(kv[0])):
                for attr, pair in sorted((attrs or {}).items()):
                    old_v = pair.get('old') if isinstance(pair, dict) else ''
                    new_v = pair.get('new') if isinstance(pair, dict) else ''
                    push(['网表部分对比', view, path, 'PORT', f'{name} / {p}', '端口变更', _text(old_v), _text(new_v), f'属性 {attr} 变更（PARTIAL）', ev_label])
        elif isinstance(detail, dict) and isinstance(detail.get('pins'), dict):
            old_pins = detail['pins'].get('old') or []
            new_pins = detail['pins'].get('new') or []
            removed_p = sorted(set(old_pins) - set(new_pins), key=_nat_key)
            added_p = sorted(set(new_pins) - set(old_pins), key=_nat_key)
            if not removed_p and not added_p and old_pins != new_pins:
                note = f'引脚顺序变化（共 {len(new_pins)} 个引脚，PARTIAL）'
            else:
                parts = []
                if added_p:
                    parts.append('新增: ' + ', '.join(added_p[:12]) + (' …' if len(added_p) > 12 else ''))
                if removed_p:
                    parts.append('移除: ' + ', '.join(removed_p[:12]) + (' …' if len(removed_p) > 12 else ''))
                note = '; '.join(parts) + '（PARTIAL）'
            push([
                '网表部分对比', view, path, obj_kind, name, '引脚列表变更',
                ' '.join(str(x) for x in old_pins), ' '.join(str(x) for x in new_pins),
                note, ev_label,
            ])
        else:
            push(['网表部分对比', view, path, obj_kind, name, '存在差异', '', _text(detail), '轻量接口观察（PARTIAL）', ev_label])

    if overflow:
        rows.append([
            '网表部分对比', view, path, 'SUMMARY', '折叠提示', '存在差异',
            '', '', f'… 本文件其余 {overflow} 条部分差异已折叠，完整内容见 CheckResult JSON', ev_label,
        ])
    return rows


def unpack_plugin_findings(checks, facts_evidence):
    """Automatically unpack structured `findings[]` emitted by any custom or built-in check plugin."""
    rows = []
    per_check_badges = {}
    for q in checks:
        findings = q.get('findings')
        if not isinstance(findings, list) or not findings:
            continue
        check_id = q.get('check_id', 'PLUGIN')
        default_path = '\n'.join(q.get('scope_file_keys') or [])
        ev_lbl = evidence_list_label(q.get('facts_refs') or [], facts_evidence)
        count = 0
        overflow = 0
        for item in findings:
            if not isinstance(item, dict):
                continue
            count += 1
            if count <= MAX_PLUGIN_FINDINGS_PER_CHECK:
                rows.append([
                    f'插件:{check_id}',
                    item.get('view') or check_id,
                    item.get('path') or default_path,
                    item.get('object_type') or 'FINDING',
                    _norm_obj_name(item.get('object_name') or check_id),
                    item.get('diff_type') or '异常项',
                    _text(item.get('old_value')),
                    _text(item.get('new_value')),
                    item.get('detail') or q.get('detail', ''),
                    ev_lbl,
                ])
            else:
                overflow += 1
        if overflow:
            rows.append([
                f'插件:{check_id}', check_id, default_path, 'SUMMARY', '折叠提示', '存在差异',
                '', '', f'… 其余 {overflow} 条插件发现项已折叠，完整列表见 CheckResult JSON', ev_lbl,
            ])
        if count:
            per_check_badges[id(q)] = (count, f'{count} 项发现 →', q.get('detail', ''))
    return rows, per_check_badges
