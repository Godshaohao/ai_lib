"""Manifest-level bidirectional pairing check between effective LIBERTY (.lib) and DB (.db) files.

Strictly zero disk reading of `.db` binary files or `.lib` contents — operates purely on
`ctx['target']` member paths of the target effective revision.
"""
import fnmatch
from pathlib import Path


def _matches_any(rel_path: str, patterns: list[str]) -> bool:
    if not patterns:
        return False
    name = Path(rel_path).name
    for pat in patterns:
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel_path, pat):
            return True
    return False


def _canonical_stem(
    rel_path: str,
    *,
    view: str,
    match_scope: str = 'basename',
    strip_suffixes: list[str] | None = None,
    extra_trim: list[str] | None = None,
    case_sensitive: bool = False,
) -> str:
    raw = Path(rel_path).name if match_scope == 'basename' else rel_path.replace('\\', '/')
    s = raw
    for suf in (strip_suffixes or ['.gz']):
        if suf and s.lower().endswith(suf.lower()):
            s = s[:-len(suf)]
    ext = '.lib' if view == 'LIBERTY' else '.db'
    if s.lower().endswith(ext):
        s = s[:-len(ext)]
    for trim in (extra_trim or []):
        if trim and s.lower().endswith(trim.lower()):
            s = s[:-len(trim)]
    return s if case_sensitive else s.casefold()


def run_lib_db_pairing(ctx: dict) -> dict:
    """Verify 1:1 naming/presence correspondence between LIBERTY (.lib) and DB (.db) in effective target."""
    target = ctx.get('target') or {}
    params = (ctx.get('plugin_params') or {}).get('LIB_DB_PAIRING') or {}
    explicit = bool(ctx.get('explicit_plugins'))

    ignore_patterns = [str(p) for p in (params.get('ignore_patterns') or []) if str(p).strip()]
    match_scope = str(params.get('match_scope') or 'basename').strip().lower()
    if match_scope not in ('basename', 'relative_path'):
        match_scope = 'basename'
    strip_suffixes = list(params.get('strip_suffixes') or ['.gz'])
    lib_trim = list(params.get('lib_suffix_trim') or [])
    db_trim = list(params.get('db_suffix_trim') or [])
    case_sensitive = bool(params.get('case_sensitive', False))
    strict_orphan_db = bool(params.get('strict_orphan_db', True))
    require_db = params.get('require_db')

    lib_paths = sorted(
        path for (view, path) in target
        if view == 'LIBERTY' and not _matches_any(path, ignore_patterns)
    )
    db_paths = sorted(
        path for (view, path) in target
        if view == 'DB' and not _matches_any(path, ignore_patterns)
    )

    if not lib_paths and not db_paths:
        return {'checks': []}

    # Auto-applicability: if a library has .lib but zero .db, only enforce when require_db=True or explicitly requested.
    if lib_paths and not db_paths and not require_db and not explicit:
        return {'checks': []}

    lib_by_stem: dict[str, list[str]] = {}
    for p in lib_paths:
        stem = _canonical_stem(
            p,
            view='LIBERTY',
            match_scope=match_scope,
            strip_suffixes=strip_suffixes,
            extra_trim=lib_trim,
            case_sensitive=case_sensitive,
        )
        lib_by_stem.setdefault(stem, []).append(p)

    db_by_stem: dict[str, list[str]] = {}
    for p in db_paths:
        stem = _canonical_stem(
            p,
            view='DB',
            match_scope=match_scope,
            strip_suffixes=strip_suffixes,
            extra_trim=db_trim,
            case_sensitive=case_sensitive,
        )
        db_by_stem.setdefault(stem, []).append(p)

    lib_stems = set(lib_by_stem)
    db_stems = set(db_by_stem)
    matched_stems = sorted(lib_stems & db_stems)
    missing_db_stems = sorted(lib_stems - db_stems)
    orphan_db_stems = sorted(db_stems - lib_stems)
    dup_lib = {k: v for k, v in lib_by_stem.items() if len(v) > 1}
    dup_db = {k: v for k, v in db_by_stem.items() if len(v) > 1}

    findings = []
    for st in missing_db_stems:
        for lp in lib_by_stem[st]:
            findings.append({
                'view': 'DB',
                'path': lp,
                'object_type': 'LIB_DB_PAIR',
                'object_name': Path(lp).name,
                'diff_type': 'MISSING_DB',
                'detail': f'存在 .lib 但缺少对应 .db（stem={st}）',
            })
    for st in orphan_db_stems:
        for dp in db_by_stem[st]:
            findings.append({
                'view': 'LIBERTY',
                'path': dp,
                'object_type': 'LIB_DB_PAIR',
                'object_name': Path(dp).name,
                'diff_type': 'ORPHAN_DB',
                'detail': f'存在 .db 但缺少对应 .lib（stem={st}）',
            })
    for st, paths in sorted(dup_lib.items()):
        findings.append({
            'view': 'LIBERTY',
            'path': paths[0],
            'object_type': 'LIB_DB_PAIR',
            'object_name': st,
            'diff_type': 'DUPLICATE_LIB_STEM',
            'detail': f'多个 .lib 映射到同一配对名 {st}: {", ".join(paths)}',
        })
    for st, paths in sorted(dup_db.items()):
        findings.append({
            'view': 'DB',
            'path': paths[0],
            'object_type': 'LIB_DB_PAIR',
            'object_name': st,
            'diff_type': 'DUPLICATE_DB_STEM',
            'detail': f'多个 .db 映射到同一配对名 {st}: {", ".join(paths)}',
        })

    scope_keys = sorted(set(lib_paths) | set(db_paths))
    summary_parts = [f'已配对 {len(matched_stems)} 组（.lib={len(lib_paths)}，.db={len(db_paths)}）']

    if missing_db_stems:
        sample = ', '.join(Path(lib_by_stem[s][0]).name for s in missing_db_stems[:6])
        more = f' 等共 {len(missing_db_stems)} 项' if len(missing_db_stems) > 6 else ''
        summary_parts.append(f'缺 .db {len(missing_db_stems)} 项：{sample}{more}')
    if orphan_db_stems:
        sample = ', '.join(Path(db_by_stem[s][0]).name for s in orphan_db_stems[:6])
        more = f' 等共 {len(orphan_db_stems)} 项' if len(orphan_db_stems) > 6 else ''
        summary_parts.append(f'多余 .db（无对应 .lib）{len(orphan_db_stems)} 项：{sample}{more}')
    if dup_lib or dup_db:
        summary_parts.append(f'重名冲突（.lib 重复 {len(dup_lib)}，.db 重复 {len(dup_db)}）')

    caveat = '（仅核验有效版本文件清单的命名与存在性对应，未读取 .db 内容；模型一致性需由 PT 验证）'
    if missing_db_stems or dup_lib or dup_db or (orphan_db_stems and strict_orphan_db):
        result = 'FAIL'
        severity = 'ERROR'
    elif orphan_db_stems:
        result = 'INCONCLUSIVE'
        severity = 'WARNING'
    else:
        result = 'PASS'
        severity = 'INFO'

    return {
        'checks': [{
            'check_id': 'LIB_DB_PAIRING',
            'scope_file_keys': scope_keys,
            'result': result,
            'severity': severity,
            'coverage': 'MANIFEST',
            'facts_refs': [],
            'detail': '；'.join(summary_parts) + caveat,
            'findings': findings,
        }],
    }
