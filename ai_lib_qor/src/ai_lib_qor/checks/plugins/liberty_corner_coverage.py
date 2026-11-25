"""Manifest-level Liberty (.lib) corner acceptance check driven by a Business IP -> Group -> Corner table.

Ultra-simple 2-symbol corner syntax (case-insensitive substring match against `.lib` path):
- Plain token: `"ss_125c"`       -> path contains `ss_125c`
- `+` (AND)  : `"ss+125c"`       -> path contains BOTH `ss` and `125c`
- `|` (OR)   : `"tt|typ+25c"`    -> path contains (`tt` or `typ`) AND `25c`

`ip_groups` maps Business IP (or single-track library name, supporting `*` wildcard) -> group name or list of groups.
"""
import fnmatch
import json
from pathlib import Path

from ai_lib_qor.versions.store import validate


def _load_corner_table(ctx: dict, params: dict) -> tuple[dict | None, str | None]:
    if isinstance(params.get('groups'), dict) and (
        isinstance(params.get('ip_groups'), dict) or isinstance(params.get('ip_rules'), list)
    ):
        table = {'groups': params['groups']}
        if isinstance(params.get('ip_groups'), dict):
            table['ip_groups'] = params['ip_groups']
        if isinstance(params.get('ip_rules'), list):
            table['ip_rules'] = params['ip_rules']
        if params.get('default_groups'):
            table['default_groups'] = list(params['default_groups'])
        if params.get('schema_version'):
            table['schema_version'] = params['schema_version']
        validate(table, 'corner_acceptance')
        return table, 'inline:path_sources.json'

    work = ctx.get('work')
    if not work:
        return None, None
    work_root = Path(work).resolve()
    raw_file = params.get('table_file')
    if raw_file:
        cand = Path(raw_file)
        if not cand.is_absolute():
            cand = (work_root / cand).resolve()
        else:
            cand = cand.resolve()
        if not cand.is_relative_to(work_root):
            raise ValueError(f'Corner 验收表路径不能越界工作目录: {raw_file}')
        if cand.is_symlink() or not cand.is_file():
            raise ValueError(f'Corner 验收表不存在或为软链接: {raw_file}')
        source_label = str(cand.relative_to(work_root))
    else:
        cand = work_root / 'corner_acceptance.json'
        if cand.is_symlink():
            raise ValueError('corner_acceptance.json 不能为软链接')
        if not cand.is_file():
            return None, None
        source_label = 'corner_acceptance.json'

    table = json.loads(cand.read_text(encoding='utf-8'))
    validate(table, 'corner_acceptance')
    return table, source_label


def _pattern_match(value: str | None, pattern: str | None) -> bool:
    if pattern is None or not str(pattern).strip():
        return True
    if not value:
        return False
    return fnmatch.fnmatch(str(value).casefold(), str(pattern).strip().casefold())


def _parse_corner_spec(raw) -> dict:
    """Normalize either a simple `+`/`|` corner string or a structured corner object."""
    if isinstance(raw, dict):
        return {
            'id': raw['id'],
            'label': raw.get('label') or raw['id'],
            'clauses': (
                [[k.casefold() for k in raw['keywords'] if k]]
                if raw.get('match_mode') == 'any' and raw.get('keywords')
                else [[k.casefold()] for k in (raw.get('keywords') or []) if k]
            ) + (
                [[k.casefold() for k in raw['any_keywords'] if k]]
                if raw.get('any_keywords')
                else []
            ),
            'exclude': [k.casefold() for k in (raw.get('exclude_keywords') or []) if k],
            'min_count': int(raw.get('min_count') or 1),
            'optional': bool(raw.get('optional', False)),
            'hint': '+'.join(raw.get('keywords') or raw.get('any_keywords') or [raw['id']]),
        }

    expr = str(raw).strip()
    clauses: list[list[str]] = []
    for part in expr.split('+'):
        tok = part.strip()
        if not tok:
            continue
        alts = [a.strip().casefold() for a in tok.split('|') if a.strip()]
        if alts:
            clauses.append(alts)
    if not clauses:
        clauses.append([expr.casefold()])
    return {
        'id': expr,
        'label': expr,
        'clauses': clauses,
        'exclude': [],
        'min_count': 1,
        'optional': False,
        'hint': expr,
    }


def _corner_matches_path(rel_path: str, parsed: dict) -> bool:
    hay = rel_path.casefold()
    if any(ex in hay for ex in parsed['exclude']):
        return False
    return all(any(alt in hay for alt in clause) for clause in parsed['clauses'])


def _extract_group_corners(group_val) -> list[dict]:
    items = group_val if isinstance(group_val, list) else (group_val.get('corners') or [])
    return [_parse_corner_spec(item) for item in items]


def resolve_ip_corner_groups(
    table: dict,
    *,
    vendor: str | None,
    library: str | None,
    business_ip: str | None,
) -> tuple[list[str], list[str]]:
    """Return `(matched_group_names, matched_rule_notes)` for the given Business IP (or single-track library).

    Priority for `ip_groups`:
      1. Exact Business IP / library name match (no wildcard)
      2. Wildcard Business IP / library pattern match (e.g. `sram22_256x16*`)
      3. `*` catch-all fallback (only if explicitly written in `ip_groups`)
    """
    groups_out: list[str] = []
    notes: list[str] = []
    target_ip = business_ip or library
    vendor_lib = f'{vendor}/{library}' if vendor and library else ''

    ip_groups = table.get('ip_groups')
    if isinstance(ip_groups, dict):
        exact_hits: list[str] = []
        pattern_hits: list[str] = []
        catchall_hits: list[str] = []

        def _add(bucket: list[str], val):
            names = [val] if isinstance(val, str) else list(val)
            for g in names:
                if g not in bucket:
                    bucket.append(g)

        for key, val in ip_groups.items():
            k = str(key).strip()
            if not k:
                continue
            if k == '*':
                _add(catchall_hits, val)
                continue
            is_wild = ('*' in k or '?' in k or '[' in k)
            if '/' in k:
                hit = _pattern_match(vendor_lib, k)
            else:
                hit = _pattern_match(target_ip, k)
            if hit:
                _add(pattern_hits if is_wild else exact_hits, val)

        chosen = exact_hits or pattern_hits or catchall_hits
        for g in chosen:
            if g not in groups_out:
                groups_out.append(g)

    for rule in table.get('ip_rules') or []:
        has_constraint = any(
            rule.get(k) is not None and str(rule.get(k)).strip()
            for k in ('match_vendor', 'match_library', 'match_ip')
        )
        if not has_constraint:
            continue
        if not _pattern_match(vendor, rule.get('match_vendor')):
            continue
        if not _pattern_match(library, rule.get('match_library')):
            continue
        if rule.get('match_ip') is not None and str(rule.get('match_ip')).strip():
            if not _pattern_match(target_ip, rule.get('match_ip')):
                continue
        for g in rule.get('groups') or []:
            if g not in groups_out:
                groups_out.append(g)
        if rule.get('note'):
            notes.append(str(rule['note']))

    if not groups_out:
        for g in table.get('default_groups') or []:
            if g not in groups_out:
                groups_out.append(g)
    return groups_out, notes


def run_liberty_corner_coverage(ctx: dict) -> dict:
    """Verify that the effective revision's LIBERTY (.lib) files satisfy required Corner groups."""
    target = ctx.get('target') or {}
    params = (ctx.get('plugin_params') or {}).get('LIBERTY_CORNER_COVERAGE') or {}
    explicit = bool(ctx.get('explicit_plugins'))
    facts = ctx.get('facts') or {}

    try:
        table, source_label = _load_corner_table(ctx, params)
    except (OSError, ValueError, TypeError) as exc:
        return {
            'checks': [{
                'check_id': 'LIBERTY_CORNER_COVERAGE',
                'scope_file_keys': [],
                'result': 'FAIL',
                'severity': 'ERROR',
                'coverage': 'UNKNOWN',
                'facts_refs': [],
                'detail': f'Corner 验收表加载或 Schema 校验失败: {exc}',
            }],
        }

    if table is None:
        return {'checks': []}

    lib_paths = sorted(path for (view, path) in target if view == 'LIBERTY')
    if not lib_paths and not explicit:
        return {'checks': []}

    vendor = ctx.get('vendor')
    library = ctx.get('library')
    business_ip = ctx.get('business_ip')

    matched_groups, _ = resolve_ip_corner_groups(
        table,
        vendor=vendor,
        library=library,
        business_ip=business_ip,
    )
    if not matched_groups:
        fail_unmapped = bool(params.get('fail_on_unmapped_ip', False))
        scope_tag = business_ip or f'{vendor}/{library}'
        return {
            'checks': [{
                'check_id': 'LIBERTY_CORNER_COVERAGE',
                'scope_file_keys': lib_paths,
                'result': 'FAIL' if fail_unmapped else 'INCONCLUSIVE',
                'severity': 'ERROR' if fail_unmapped else 'WARNING',
                'coverage': 'UNKNOWN',
                'facts_refs': [],
                'detail': f'业务 IP {scope_tag} 未在验收表 {source_label} 的 ip_groups 中配置对应分组，未执行 Corner 验收',
            }],
        }

    groups_def = table.get('groups') or {}
    checks = []
    for gname in matched_groups:
        gval = groups_def.get(gname)
        if not isinstance(gval, (list, dict)):
            checks.append({
                'check_id': 'LIBERTY_CORNER_COVERAGE',
                'scope_file_keys': lib_paths,
                'result': 'FAIL',
                'severity': 'ERROR',
                'coverage': 'UNKNOWN',
                'facts_refs': [],
                'detail': f'[{gname}] 验收表 {source_label} 引用了未定义的 Corner 分组 {gname}',
            })
            continue

        corners = _extract_group_corners(gval)
        req_total = 0
        req_hit = 0
        missing_req = []
        missing_opt = []
        hit_files = set()
        findings = []

        for cspec in corners:
            cid = cspec['id']
            clabel = cspec['label']
            is_opt = cspec['optional']
            min_cnt = cspec['min_count']
            matched = [p for p in lib_paths if _corner_matches_path(p, cspec)]
            hit_files.update(matched)
            if not is_opt:
                req_total += 1
            if len(matched) >= min_cnt:
                if not is_opt:
                    req_hit += 1
            else:
                if is_opt:
                    missing_opt.append(cid)
                else:
                    missing_req.append(cid)
                    findings.append({
                        'view': 'LIBERTY',
                        'path': '',
                        'object_type': 'LIBERTY_CORNER',
                        'object_name': cid,
                        'diff_type': 'MISSING_CORNER',
                        'old_value': f'至少 {min_cnt} 个匹配 ({cspec["hint"]})',
                        'new_value': f'实际命中 {len(matched)} 个',
                        'detail': f'分组 [{gname}] 缺失必选 Corner {clabel}（要求 >= {min_cnt}，实际 {len(matched)}）',
                    })

        facts_refs = sorted({
            facts[('LIBERTY', p)][0].name
            for p in hit_files
            if ('LIBERTY', p) in facts
        })
        if missing_req:
            result = 'FAIL'
            severity = 'ERROR'
            detail = (
                f'[{gname}] 缺失 {len(missing_req)}/{req_total} 个必选 Corner：'
                f'{"、".join(missing_req[:8])}{" 等" if len(missing_req) > 8 else ""}；'
                f'已命中 {req_hit}/{req_total} 项（共 {len(lib_paths)} 个 .lib，基于文件名关键词核验，来源 {source_label}）'
            )
        else:
            result = 'PASS'
            severity = 'INFO'
            opt_note = f'；可选未命中：{"、".join(missing_opt[:4])}' if missing_opt else ''
            detail = (
                f'[{gname}] 必选 Corner 全部命中（{req_hit}/{req_total}，匹配 {len(hit_files)} 个 .lib）'
                f'{opt_note}（基于文件名关键词核验，来源 {source_label}；不替代 .lib 内部 PVT 核对）'
            )

        checks.append({
            'check_id': 'LIBERTY_CORNER_COVERAGE',
            'scope_file_keys': sorted(hit_files) if hit_files else lib_paths,
            'result': result,
            'severity': severity,
            'coverage': 'MANIFEST',
            'facts_refs': facts_refs,
            'detail': detail,
            'findings': findings,
        })

    return {'checks': checks}
