"""Shared read-only queries, unified check lookup, tooling freshness checks, and unadopted-file summaries."""
from collections import OrderedDict
import json
import os
from pathlib import Path
import threading

from ai_lib_qor.checks.path_plugins import PATH_CHECK_PLUGINS, evaluate_check_verdict, plugin_versions
from ai_lib_qor.facts.registry import current_parser_info
from ai_lib_qor.sources.layout import library_folder
from ai_lib_qor.versions.store import locked, read_json_readonly
from .minimal_effective import _deliveries, _flat, _history, _latest_effective_pointer, _norm_business_ip, list_track_effective_ips
from .minimal_file_index import _archive_stat_summary, _configured_times, _ordered, build_index, index_manifest_matches, read_manifest, without_formal_snapshot_ids
from .path_config import (
    ignored_unadopted_files, library_ip_config, liberty_filter_evidence, liberty_parse_filter,
    list_libraries_by_ip_type, select_liberty_files, skip_parse_views,
)

_UNSET = object()
_RUNS_TAIL_BYTES = 65536
_RUNS_CACHE_LOCK = threading.Lock()
_RUNS_CACHE: OrderedDict = OrderedDict()
_RUNS_CACHE_MAX = 512


def _read_runs_jsonl_cached(runs_path: Path, *, tail_only: bool) -> tuple[list[dict], bool]:
    """Stat-verified parsed runs.jsonl cache (avoids repeated disk reads across batch/timeline lookups)."""
    st = runs_path.stat()
    key = (str(runs_path.resolve()), st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino, tail_only)
    with _RUNS_CACHE_LOCK:
        hit = _RUNS_CACHE.get(key)
        if hit is not None:
            _RUNS_CACHE.move_to_end(key)
            return hit
    if tail_only and st.st_size > _RUNS_TAIL_BYTES:
        with runs_path.open('rb') as stream:
            stream.seek(st.st_size - _RUNS_TAIL_BYTES)
            raw = stream.read().decode('utf-8', errors='replace')
        raw_lines = [ln for ln in raw.splitlines()[1:] if ln.strip()]
        read_all = False
    else:
        raw_lines = [ln for ln in runs_path.read_text(encoding='utf-8').splitlines() if ln.strip()]
        read_all = True
    events = []
    for ln in raw_lines:
        try:
            ev = json.loads(ln)
            if isinstance(ev, dict):
                events.append(ev)
        except (ValueError, TypeError):
            continue
    val = (events, read_all)
    with _RUNS_CACHE_LOCK:
        _RUNS_CACHE[key] = val
        _RUNS_CACHE.move_to_end(key)
        while len(_RUNS_CACHE) > _RUNS_CACHE_MAX:
            _RUNS_CACHE.popitem(last=False)
    return val


def _has_newer_check_json(folder: Path, log_dir: Path, runs_mtime: int) -> bool:
    """Return True only if an actual check_*.json file is newer than runs.jsonl (ignores .xlsx/overall writes)."""
    for base, prefix in ((folder, 'check_run_'), (log_dir, 'check_')):
        try:
            if base.is_symlink() or not base.is_dir():
                continue
            with os.scandir(base) as it:
                for entry in it:
                    name = entry.name
                    if not name.startswith(prefix) or not name.endswith('.json'):
                        continue
                    if entry.is_symlink():
                        continue
                    if entry.stat(follow_symlinks=False).st_mtime_ns > runs_mtime:
                        return True
        except OSError:
            return True
    return False


def check_tooling_status(report, *, expected_plugins=None, work=None):
    """Compare a saved CheckResult against active parsers, plugins and file selection."""
    reasons = []
    if not isinstance(report, dict):
        return {'status': 'CURRENT', 'is_stale': False, 'reasons': []}

    tooling = report.get('tooling')
    checked_views = set()
    if isinstance(tooling, dict) and isinstance(tooling.get('parser_signatures'), dict):
        for view, saved_sig in sorted(tooling['parser_signatures'].items()):
            cur = current_parser_info(view, allow_pg=True)
            checked_views.add(view)
            if cur is None:
                reasons.append(f'{view} 解析器已移除或未注册')
            elif saved_sig != cur['signature']:
                reasons.append(f'{view} 解析器签名变更: {saved_sig} → {cur["signature"]}')
        saved_pvers = tooling.get('plugin_versions')
        if isinstance(saved_pvers, dict):
            active_pvers = plugin_versions(list(saved_pvers.keys()))
            for pname, sver in sorted(saved_pvers.items()):
                cver = active_pvers.get(pname)
                if cver is None:
                    reasons.append(f'检查插件 {pname} 已移除或未注册')
                elif str(sver) != str(cver):
                    reasons.append(f'检查插件 {pname} 已升级: {sver} → {cver}')
        if expected_plugins is not None:
            saved_plugins = tooling.get('plugins') or []
            if sorted(saved_plugins) != sorted(expected_plugins):
                reasons.append(f'检查插件集合变更: {saved_plugins} → {list(expected_plugins)}')

    # Fallback for historical saved checks created before `tooling` metadata existed:
    seen_evidence = {}
    for ev in (report.get('facts_evidence') or {}).values():
        if not isinstance(ev, dict):
            continue
        view = ev.get('view')
        parser = ev.get('parser')
        if not view or view in checked_views or not isinstance(parser, dict):
            continue
        seen_evidence.setdefault(view, set()).add((parser.get('name'), parser.get('version')))

    for view, pairs in sorted(seen_evidence.items()):
        cur = current_parser_info(view, allow_pg=True)
        if cur is None or not cur.get('name') or not cur.get('version'):
            continue
        for p_name, p_ver in sorted(pairs):
            if (p_name, p_ver) != (cur['name'], cur['version']):
                reasons.append(f'{view} 解析器已升级: {p_name} {p_ver} → {cur["name"]} {cur["version"]}')

    if work is not None:
        tooling = tooling if isinstance(tooling, dict) else {}
        files = report.get('files') or []
        views = {file['view'] for file in files}
        vendor, library = report['vendor'], report['library']
        try:
            skipped = set(skip_parse_views(work, vendor, library)) & views
            liberty_paths = [file['path'] for file in files if file['view'] == 'LIBERTY'] if 'LIBERTY' not in skipped else []
            current_filter = liberty_filter_evidence(select_liberty_files(liberty_paths, liberty_parse_filter(work, vendor, library)))
            if skipped != (set(tooling.get('skipped_views') or []) & views):
                reasons.append('文件解析范围配置变更')
            if current_filter != tooling.get('liberty_filter'):
                reasons.append('Liberty 抽样配置变更')
        except (OSError, ValueError, TypeError) as exc:
            reasons.append(f'当前检查配置无效: {exc}')

    return {
        'status': 'STALE_TOOLING' if reasons else 'CURRENT',
        'is_stale': bool(reasons),
        'reasons': reasons,
    }


def _plugins_match(data: dict, expected_plugins, *, allow_legacy_default: bool = True) -> bool:
    """Check whether a saved CheckResult satisfies the requested plugin set."""
    if expected_plugins is None:
        return True
    wanted = sorted(set(expected_plugins))
    tooling = data.get('tooling')
    if isinstance(tooling, dict) and isinstance(tooling.get('plugins'), list):
        return sorted(set(tooling['plugins'])) == wanted
    # Legacy saved checks predating `tooling.plugins` implicitly ran the built-in default plugin set.
    if allow_legacy_default and wanted == sorted(PATH_CHECK_PLUGINS.keys()):
        return True
    return False


def _summarize_check_record(folder: Path, path: Path, data: dict, *, expected_plugins=None, work=None) -> dict:
    comp_map = {(c['view'], c['path']): c for c in data.get('comparisons', [])}
    pcomp_map = {(c['view'], c['path']): c for c in data.get('partial_comparisons', [])}
    file_map = {}
    for f in data.get('files', []):
        key = (f['view'], f['path'])
        comp = comp_map.get(key)
        pcomp = pcomp_map.get(key)
        if comp:
            c_status = comp['content_status']
            refs = comp.get('facts_refs') or []
        elif pcomp:
            c_status = 'PARTIAL_DIFF' if pcomp.get('differences') else 'PARTIAL_MATCH'
            refs = pcomp.get('facts_refs') or []
        else:
            c_status = 'NOT_COMPARED'
            refs = []
        file_map[key] = {
            'parse_status': f.get('status'),
            'fact_ref': Path(f['facts']).name if f.get('facts') else None,
            'content_status': c_status,
            'compare_old': Path(refs[0]).name if len(refs) == 2 else None,
            'compare_new': Path(refs[1]).name if len(refs) == 2 else None,
        }
    verdict = evaluate_check_verdict(data)
    q_code, q_cls, q_text = verdict['code'], verdict['cls'], verdict['text']
    fc, ic, ff = verdict['failed_checks'], verdict['inconclusive_checks'], verdict['failed_files']
    run_state = data.get('state', 'UNKNOWN')
    xlsx = path.with_suffix('.xlsx') if path.parent.name == 'log' else folder / ('report_' + data['run_id'] + '.xlsx')
    out = {
        'check_name': path.name,
        'check_path': str(path),
        'excel_path': str(xlsx) if (not xlsx.is_symlink() and xlsx.is_file()) else None,
        'report_name': xlsx.name if (not xlsx.is_symlink() and xlsx.is_file()) else path.name,
        'run_id': data.get('run_id'),
        'revision': data.get('revision'),
        'baseline': data.get('baseline'),
        'run_at': data.get('run_at', ''),
        'state': run_state,
        'quality_code': q_code,
        'quality_cls': q_cls,
        'quality_text': q_text,
        'verdict': q_text,
        'failed_checks': fc,
        'inconclusive_checks': ic,
        'failed_files': ff,
        'files': file_map,
        'tooling_status': check_tooling_status(data, expected_plugins=expected_plugins, work=work),
    }
    if data.get('business_ip') is not None:
        out['business_ip'] = data.get('business_ip')
        out['ip_type'] = data.get('ip_type')
        out['track_id'] = data.get('track_id')
    return out


def _iter_saved_checks(folder: Path):
    if not folder.is_dir():
        return []
    candidates = [*folder.glob('check_run_*.json')]
    log_dir = folder / 'log'
    if log_dir.is_dir() and not log_dir.is_symlink():
        candidates.extend(p for p in log_dir.glob('check_*.json') if not p.is_symlink())
    return sorted(set(candidates), key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)


def _read_tail_lines(path: Path, max_bytes: int = _RUNS_TAIL_BYTES) -> tuple[list[str], bool]:
    """Read only the last `max_bytes` of runs.jsonl for O(1) constant-time recent check lookup."""
    size = path.stat().st_size
    if size <= max_bytes:
        return [ln for ln in path.read_text(encoding='utf-8').splitlines() if ln.strip()], True
    with path.open('rb') as stream:
        stream.seek(size - max_bytes)
        raw = stream.read().decode('utf-8', errors='replace')
    lines = raw.splitlines()
    return [ln for ln in lines[1:] if ln.strip()], False


def _fast_lookup_via_runs_jsonl(
    folder: Path,
    vendor: str,
    library: str,
    revision: str,
    *,
    baseline=_UNSET,
    plugins=None,
    business_ip=None,
    work=None,
):
    """O(1) tail-seek check lookup using cached log/runs.jsonl + Schema-validated check_result_path reads."""
    ip = _norm_business_ip(business_ip)
    log_dir = folder / 'log'
    runs_path = log_dir / 'runs.jsonl'
    if log_dir.is_symlink() or runs_path.is_symlink() or not runs_path.is_file():
        return None, False
    try:
        runs_mtime = runs_path.stat().st_mtime_ns
        if (folder.stat().st_mtime_ns > runs_mtime or log_dir.stat().st_mtime_ns > runs_mtime) and _has_newer_check_json(folder, log_dir, runs_mtime):
            return None, False
        tail_events, read_all = _read_runs_jsonl_cached(runs_path, tail_only=True)
    except OSError:
        return None, False

    match_baseline = baseline is not _UNSET
    wanted_plugins = sorted(set(plugins)) if plugins is not None else None
    folder_res = folder.resolve()

    def scan(events):
        for ev in reversed(events):
            if ev.get('type') != 'CHECK' or ev.get('revision') != revision:
                continue
            if ev.get('business_ip') != ip:
                continue
            if match_baseline and 'baseline' in ev and ev.get('baseline') != baseline:
                continue
            if wanted_plugins is not None and isinstance(ev.get('plugins'), list):
                if sorted(set(ev['plugins'])) != wanted_plugins:
                    continue
            rel = ev.get('json')
            if not isinstance(rel, str) or not rel:
                continue
            target = folder / rel
            if target.is_symlink() or not target.is_file():
                continue
            try:
                if not target.resolve().is_relative_to(folder_res):
                    continue
                data = read_json_readonly(target, 'check_result_path')
                if (
                    data.get('schema_version') == 'check_result.path.v1'
                    and (data.get('vendor'), data.get('library')) == (vendor, library)
                    and data.get('business_ip') == ip
                    and data.get('revision') == revision
                    and (not match_baseline or data.get('baseline') == baseline)
                    and _plugins_match(data, plugins)
                ):
                    return _summarize_check_record(folder, target, data, expected_plugins=plugins, work=work)
            except (OSError, ValueError, TypeError, KeyError):
                continue
        return None

    hit = scan(tail_events)
    if hit is not None:
        return hit, True
    if not read_all:
        try:
            full_events, _ = _read_runs_jsonl_cached(runs_path, tail_only=False)
            hit = scan(full_events)
            if hit is not None:
                return hit, True
        except OSError:
            return None, False
    return None, False


def find_latest_check(work, vendor, library, *, revision, baseline=_UNSET, plugins=None, business_ip=None):
    """Unified single entry point for looking up the newest Schema-valid CheckResult matching (revision, baseline, plugins, business_ip)."""
    if not revision:
        return None
    ip = _norm_business_ip(business_ip)
    folder = library_folder(work, vendor, library)
    hit, resolved = _fast_lookup_via_runs_jsonl(folder, vendor, library, revision, baseline=baseline, plugins=plugins, business_ip=ip, work=work)
    if resolved:
        return hit
    match_baseline = baseline is not _UNSET
    for path in _iter_saved_checks(folder):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            data = read_json_readonly(path, 'check_result_path')
            if (
                data.get('schema_version') == 'check_result.path.v1'
                and (data.get('vendor'), data.get('library')) == (vendor, library)
                and data.get('business_ip') == ip
                and data.get('revision') == revision
                and (not match_baseline or data.get('baseline') == baseline)
                and _plugins_match(data, plugins)
            ):
                return _summarize_check_record(folder, path, data, expected_plugins=plugins, work=work)
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return None


def latest_check_for_scope(work, vendor, library, revision, baseline, *, plugins=None, business_ip=None):
    """Find the most recent saved CheckResult matching (revision, baseline[, plugins, business_ip]) without triggering parsing."""
    return find_latest_check(work, vendor, library, revision=revision, baseline=baseline, plugins=plugins, business_ip=business_ip)


def latest_check_for_revision(work, vendor, library, target_revision, *, plugins=None, business_ip=None):
    """Find the most recent saved CheckResult for target_revision regardless of baseline (read-only)."""
    return find_latest_check(work, vendor, library, revision=target_revision, baseline=_UNSET, plugins=plugins, business_ip=business_ip)


def unadopted_new_files(work, vendor, library, *, sample_limit=20, business_ip=None):
    """Read-only diff of files present in latest archived delivery (or track's latest delivery) but not yet in latest effective revision."""
    ip = _norm_business_ip(business_ip)
    folder = library_folder(work, vendor, library)
    if not folder.is_dir():
        return None
    try:
        latest_eff_ptr = folder / _latest_effective_pointer(ip)
        eff_dir = folder / 'effective'
        if not latest_eff_ptr.is_symlink() and not eff_dir.is_dir() and not any(folder.glob(f'effective_{library}_*.json')):
            return None
        eff_data = None
        if latest_eff_ptr.is_symlink():
            tgt = latest_eff_ptr.resolve(strict=True)
            if tgt.is_relative_to(folder.resolve()) and tgt.is_file():
                eff_data = json.loads(tgt.read_text(encoding='utf-8'))
        if eff_data is None:
            hist = _history(folder, library, business_ip=ip)
            eff_data = hist[-1][2] if hist else None
        if not eff_data:
            return None

        deliv_data = None
        if ip is not None:
            from .ip_partition import load_partition
            part = load_partition(work, vendor, library)
            track_vers = (part or {}).get('tracks', {}).get(ip) or []
            if not track_vers:
                return None
            deliveries = _deliveries(folder, vendor, library)
            latest_track_ver = track_vers[-1]
            deliv_data = deliveries.get(latest_track_ver)
        else:
            latest_deliv_ptr = folder / 'latest_delivery.json'
            if latest_deliv_ptr.is_symlink():
                tgt = latest_deliv_ptr.resolve(strict=True)
                if tgt.is_relative_to(folder.resolve()) and tgt.is_file():
                    deliv_data = json.loads(tgt.read_text(encoding='utf-8'))
            if deliv_data is None:
                deliveries = _deliveries(folder, vendor, library)
                if not deliveries:
                    return None
                ordered = _ordered(list(deliveries.values()), _configured_times(work, vendor, library))
                deliv_data = ordered[-1] if ordered else None
        if not deliv_data:
            return None

        eff_members = set(_flat(eff_data.get('views') or {}).keys())
        ignored = ignored_unadopted_files(work, vendor, library)
        active = []
        ignored_count = 0
        for view, paths in sorted((deliv_data.get('views') or {}).items()):
            for rel in sorted(paths):
                if (view, rel) in eff_members:
                    continue
                if (view, rel) in ignored:
                    ignored_count += 1
                    continue
                active.append({'view': view, 'path': rel})
        res = {
            'latest_delivery': deliv_data.get('version'),
            'latest_revision': eff_data.get('revision'),
            'count': len(active),
            'ignored_count': ignored_count,
            'sample': active[:sample_limit],
        }
        if ip is not None:
            res['business_ip'] = ip
        return res
    except (OSError, ValueError, TypeError, KeyError):
        return None


def track_effective_stat(folder: Path, library: str, business_ip) -> list:
    """Stat summary of a business IP track's immutable Effective JSON files for drift detection."""
    ip = _norm_business_ip(business_ip)
    if ip is None:
        return []
    entries = []
    for _, path, _ in _history(folder, library, business_ip=ip):
        st = path.stat()
        entries.append([path.relative_to(folder).as_posix(), st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino])
    return entries


def build_track_index_view(folder: Path, vendor: str, library: str, index: dict, business_ip: str) -> tuple[dict, str | None, list]:
    """Project a verified physical file_index onto a single business IP track without touching file_index.json."""
    ip = _norm_business_ip(business_ip)
    if ip is None:
        return index, None, []
    history = _history(folder, library, business_ip=ip)
    known = {}
    views_proj = {}
    for view, group in (index.get('views') or {}).items():
        g_proj = {}
        for rel, row in group.items():
            for raw_entry in row.get('raw') or []:
                known[(view, raw_entry['version'], rel)] = raw_entry['path']
            g_proj[rel] = {'raw': row.get('raw') or [], 'nl': row.get('nl') or [], 'effective': []}
        views_proj[view] = g_proj

    revisions = []
    ip_type = None
    track_stat = []
    for _, path, eff in history:
        if (eff.get('vendor'), eff.get('library')) != (vendor, library) or eff.get('business_ip') != ip:
            raise ValueError('多轨有效版本范围不一致')
        if ip_type is None and eff.get('ip_type') is not None:
            ip_type = eff.get('ip_type')
        rev = eff['revision']
        revisions.append(rev)
        st = path.stat()
        track_stat.append([path.relative_to(folder).as_posix(), st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino])
        seen = set()
        for view, versions in (eff.get('views') or {}).items():
            for version, paths in versions.items():
                for rel in paths:
                    key = (view, rel)
                    if key in seen:
                        raise ValueError('轨道有效版本成员重复')
                    seen.add(key)
                    src = known.get((view, version, rel))
                    if src is None:
                        raise ValueError(f'轨道 {ip} 有效版本来源不在交付清单中: {view} {version} {rel}')
                    views_proj.setdefault(view, {}).setdefault(rel, {'raw': [], 'nl': [], 'effective': []})['effective'].append({
                        'revision': rev,
                        'version': version,
                        'path': src,
                    })

    projected = {
        'vendor': index['vendor'],
        'library': index['library'],
        'deliveries': index['deliveries'],
        'nl_snapshots': index['nl_snapshots'],
        'revisions': revisions,
        'views': views_proj,
    }
    return projected, ip_type, track_stat


def build_check_context_from_index(
    vendor,
    library,
    index,
    revision,
    baseline=None,
    *,
    business_ip=None,
    ip_type=None,
    allowed_versions=None,
):
    """Build check context purely in-memory from an already-verified file_index (or track-projected view).

    Supported `baseline` modes:
    - `None`: default immediate previous effective revision (`revisions[n - 1]`, or `None` for first rev)
    - `'__prev_file__'`: Mode A — per-file chronological predecessor in `file_index.raw` (filtered to
      `allowed_versions` to prevent cross-IP contamination and skip excluded deliveries)
    - `'__none__'`: explicit static-only check (no baseline comparison)
    - `'rev_XXXX'`: explicit earlier effective revision milestone baseline
    """
    ip = _norm_business_ip(business_ip)
    revisions = index['revisions']
    if revision not in revisions:
        raise ValueError(f'轨道 {ip} 有效版本不存在: {revision}' if ip else '有效版本不存在')
    n = revisions.index(revision)
    prev_rev = revisions[n - 1] if n > 0 else None
    baseline_mode = 'REVISION'
    if baseline == '__prev_file__':
        baseline_mode = 'PREV_FILE'
    elif baseline is None:
        baseline = prev_rev
        if baseline is None:
            baseline_mode = 'NONE'
    elif baseline == '__none__':
        baseline = None
        baseline_mode = 'NONE'
    elif baseline not in revisions or revisions.index(baseline) >= n:
        raise ValueError(f'轨道 {ip} 基线版本不存在或不是较早版本（禁止跨业务 IP 对比）' if ip else '基线版本不存在或不是较早版本')

    valid_versions = (
        set(allowed_versions)
        if allowed_versions is not None
        else {d['version'] for d in (index.get('deliveries') or [])}
    )

    members = []
    for view, group in index['views'].items():
        for path, history in group.items():
            matches = [row for row in history['effective'] if row['revision'] == revision]
            if not matches:
                continue
            cur = matches[0]
            cur_ver = cur['version']
            inherited = bool(
                prev_rev
                and any(r['revision'] == prev_rev and r['version'] == cur_ver for r in history['effective'])
            )
            if baseline_mode == 'PREV_FILE':
                raw_in_scope = [
                    r for r in (history.get('raw') or [])
                    if r.get('version') in valid_versions or r.get('version') == cur_ver
                ]
                pos = next((i for i, r in enumerate(raw_in_scope) if r.get('version') == cur_ver), -1)
                prev_entry = (
                    {'version': raw_in_scope[pos - 1]['version'], 'path': raw_in_scope[pos - 1]['path']}
                    if pos > 0
                    else None
                )
            elif baseline is not None:
                previous = [row for row in history['effective'] if row['revision'] == baseline]
                prev_entry = previous[0] if previous else None
            else:
                prev_entry = None
            members.append({
                'view': view,
                'path': path,
                'version': cur_ver,
                'absolute_path': cur['path'],
                'baseline': prev_entry,
                'inherited_from_prev_rev': inherited,
            })
    ctx = {
        'vendor': vendor,
        'library': library,
        'revision': revision,
        'baseline': baseline,
        'baseline_mode': baseline_mode,
        'members': members,
        'index': index,
    }
    if ip is not None:
        ctx['business_ip'] = ip
        ctx['ip_type'] = ip_type
        ctx['track_id'] = f'{vendor}/{library}::{ip}'
    return ctx


class PathDataQuery:
    def __init__(self, work):
        self.work = work

    def _index_locked(self, vendor, library, *, verify='manifest', cur_stat=None):
        """Read and verify file_index.json assuming the caller ALREADY holds locked(folder)."""
        folder = library_folder(self.work, vendor, library)
        path = folder / 'file_index.json'
        if path.is_symlink() or not path.is_file():
            raise ValueError('文件索引不存在')
        from ai_lib_qor.versions.store import read_json_readonly
        if verify == 'fast':
            matched, _ = index_manifest_matches(self.work, vendor, library, fast=True, _cur_stat=cur_stat)
            if matched:
                return read_json_readonly(path)
        if verify in ('manifest', 'fast'):
            matched, _ = index_manifest_matches(self.work, vendor, library, fast=False, strict_hash=False, _cur_stat=cur_stat)
            if matched:
                return read_json_readonly(path)
        elif verify == 'strict':
            matched, _ = index_manifest_matches(self.work, vendor, library, fast=False, strict_hash=True)
            if matched:
                return read_json_readonly(path)
        saved = read_json_readonly(path)
        try:
            current = build_index(self.work, vendor, library)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError('文件索引过期或来源无效: ' + str(exc)) from exc
        if saved != current and saved != without_formal_snapshot_ids(current):
            raise ValueError('文件索引过期或格式不兼容')
        return current

    def index(self, vendor, library, *, verify='manifest', _return_stat=False):
        folder = library_folder(self.work, vendor, library)
        path = folder / 'file_index.json'
        if path.is_symlink() or not path.is_file():
            raise ValueError('文件索引不存在')
        with locked(folder):
            cur_stat = None
            if _return_stat:
                try:
                    cur_stat = _archive_stat_summary(self.work, vendor, library, path)
                except (OSError, ValueError, KeyError, TypeError):
                    cur_stat = None
            saved = self._index_locked(vendor, library, verify=verify, cur_stat=cur_stat)
        return (saved, cur_stat) if _return_stat else saved

    def index_status(self, vendor, library):
        folder = library_folder(self.work, vendor, library)
        path = folder / 'file_index.json'
        if path.is_symlink() or not path.is_file():
            return {'status': 'MISSING', 'refreshed_at': None}
        matched, manifest = index_manifest_matches(self.work, vendor, library)
        if matched:
            return {'status': 'FRESH', 'refreshed_at': manifest.get('refreshed_at')}
        return {
            'status': 'UNVERIFIED' if manifest is None else 'STALE',
            'refreshed_at': manifest.get('refreshed_at') if manifest else None,
        }

    def find_latest_check(self, vendor, library, *, revision, baseline=_UNSET, plugins=None, business_ip=None):
        return find_latest_check(self.work, vendor, library, revision=revision, baseline=baseline, plugins=plugins, business_ip=business_ip)

    def latest_check_for_scope(self, vendor, library, revision, baseline, *, plugins=None, business_ip=None):
        return latest_check_for_scope(self.work, vendor, library, revision, baseline, plugins=plugins, business_ip=business_ip)

    def latest_check_for_revision(self, vendor, library, target_revision, *, plugins=None, business_ip=None):
        return latest_check_for_revision(self.work, vendor, library, target_revision, plugins=plugins, business_ip=business_ip)

    def unadopted_new_files(self, vendor, library, *, sample_limit=20, business_ip=None):
        return unadopted_new_files(self.work, vendor, library, sample_limit=sample_limit, business_ip=business_ip)

    def get_check_context(self, vendor, library, revision, baseline=None, *, business_ip=None):
        ip = _norm_business_ip(business_ip)
        index = self.index(vendor, library)
        if ip is not None:
            folder = library_folder(self.work, vendor, library)
            ip_cfg = library_ip_config(self.work, vendor, library)
            projected, eff_ip_type, _ = build_track_index_view(folder, vendor, library, index, ip)
            return build_check_context_from_index(
                vendor,
                library,
                projected,
                revision,
                baseline=baseline,
                business_ip=ip,
                ip_type=eff_ip_type if eff_ip_type is not None else ip_cfg['ip_type'],
            )
        ip_cfg = library_ip_config(self.work, vendor, library)
        if ip_cfg['is_multi_track'] and not index.get('revisions'):
            raise ValueError('该库已启用多业务 IP 分轨，请通过 --ip / business_ip 指定目标业务 IP 轨道')
        return build_check_context_from_index(vendor, library, index, revision, baseline=baseline)

    def list_tracks(self, *, vendor=None, library=None, ip_type=None, business_ip=None, include_checks: bool = True):
        """Read-only track inventory across libraries, filterable by vendor/library, ip_type, and business_ip.

        Uses single-pass directory scanning (`fast_library_track_revisions`) to avoid N+1 JSON/Schema reads
        across multi-track libraries. Pass `include_checks=False` when callers only need track/revision/acceptance info.
        """
        from .ip_partition import active_tracks_for_library
        from .minimal_effective import fast_library_track_revisions

        wanted_ip = _norm_business_ip(business_ip)
        if vendor and library:
            wanted_type = ip_type.strip().casefold() if isinstance(ip_type, str) and ip_type.strip() else None
            info = library_ip_config(self.work, vendor, library)
            if wanted_type is not None and (info['ip_type'] or '').casefold() != wanted_type:
                libs = []
            else:
                libs = [{'vendor': vendor, 'library': library, **info}]
        else:
            libs = list_libraries_by_ip_type(self.work, ip_type=ip_type)

        items = []
        for entry in libs:
            v, lib = entry['vendor'], entry['library']
            if vendor and v != vendor:
                continue
            if library and lib != library:
                continue
            folder = library_folder(self.work, v, lib)
            if not folder.is_dir():
                continue
            track_info = active_tracks_for_library(self.work, v, lib)
            revs_by_ip, acc_by_ip = fast_library_track_revisions(folder, lib)
            if track_info['is_multi_track']:
                ips = list(dict.fromkeys([
                    *track_info['tracks'].keys(),
                    *(k for k in sorted(revs_by_ip) if k is not None),
                ]))
                for ip in ips:
                    if wanted_ip is not None and ip != wanted_ip:
                        continue
                    revs = revs_by_ip.get(ip) or []
                    latest_rev = revs[-1] if revs else None
                    base_rev = revs[-2] if len(revs) >= 2 else None
                    accepted_rev = acc_by_ip.get(ip)
                    chk = (
                        (
                            latest_check_for_scope(self.work, v, lib, latest_rev, '__prev_file__', business_ip=ip)
                            or latest_check_for_scope(self.work, v, lib, latest_rev, base_rev, business_ip=ip)
                        )
                        if (include_checks and latest_rev)
                        else None
                    )
                    items.append({
                        'vendor': v,
                        'library': lib,
                        'ip_type': track_info['ip_type'],
                        'business_ip': ip,
                        'track_id': f'{v}/{lib}::{ip}',
                        'is_multi_track': True,
                        'versions': list(track_info['tracks'].get(ip) or []),
                        'revisions': revs,
                        'latest_revision': latest_rev,
                        'accepted_revision': accepted_rev,
                        'is_latest_accepted': bool(latest_rev and accepted_rev == latest_rev),
                        'latest_check': {
                            'run_id': chk['run_id'],
                            'state': chk['state'],
                            'quality_code': chk['quality_code'],
                            'quality_cls': chk['quality_cls'],
                            'quality_text': chk['quality_text'],
                            'failed_checks': chk['failed_checks'],
                            'inconclusive_checks': chk['inconclusive_checks'],
                            'check_name': chk['check_name'],
                        } if chk else None,
                    })
            else:
                if wanted_ip is not None:
                    continue
                revs = revs_by_ip.get(None) or []
                latest_rev = revs[-1] if revs else None
                base_rev = revs[-2] if len(revs) >= 2 else None
                accepted_rev = acc_by_ip.get(None)
                chk = (
                    (
                        latest_check_for_scope(self.work, v, lib, latest_rev, '__prev_file__')
                        or latest_check_for_scope(self.work, v, lib, latest_rev, base_rev)
                    )
                    if (include_checks and latest_rev)
                    else None
                )
                items.append({
                    'vendor': v,
                    'library': lib,
                    'ip_type': track_info['ip_type'],
                    'business_ip': None,
                    'track_id': f'{v}/{lib}',
                    'is_multi_track': False,
                    'revisions': revs,
                    'latest_revision': latest_rev,
                    'accepted_revision': accepted_rev,
                    'is_latest_accepted': bool(latest_rev and accepted_rev == latest_rev),
                    'latest_check': {
                        'run_id': chk['run_id'],
                        'state': chk['state'],
                        'quality_code': chk['quality_code'],
                        'quality_cls': chk['quality_cls'],
                        'quality_text': chk['quality_text'],
                        'failed_checks': chk['failed_checks'],
                        'inconclusive_checks': chk['inconclusive_checks'],
                        'check_name': chk['check_name'],
                    } if chk else None,
                })
        return {
            'work': str(Path(self.work).resolve()),
            'filters': {'vendor': vendor, 'library': library, 'ip_type': ip_type, 'business_ip': wanted_ip},
            'count': len(items),
            'tracks': items,
        }

    def file(self, vendor, library, view, path, *, revision=None, version=None):
        from .minimal_file_index import _relative
        if revision is not None and version is not None:
            raise ValueError('只能指定 Effective 版本或交付版本')
        index = self.index(vendor, library)
        row = index['views'].get(view, {}).get(_relative(path))
        if row is None:
            raise ValueError('文件不在索引中')
        result = {'vendor': vendor, 'library': library, 'view': view, 'path': path, **row}
        if revision is not None:
            if revision not in index['revisions']:
                raise ValueError('有效版本不存在')
            matches = [r for r in row['effective'] if r['revision'] == revision]
            if len(matches) > 1:
                raise ValueError('有效版本来源不唯一')
            result['effective'] = matches[0] if matches else None
        if version is not None:
            order = [item['version'] for item in index['deliveries']]
            if version not in order:
                raise ValueError('交付版本不存在')
            rank = {v: i for i, v in enumerate(order)}
            at = rank[version]
            candidates = [item for item in row['raw'] if rank[item['version']] <= at]
            result['as_of'] = candidates[-1] if candidates else None
        return result


def _formal_link_map(formal_doc: dict) -> dict[tuple[str, str], tuple[str, str]]:
    """Flatten formal snapshot views into {(view, link_path): (raw_version, resolved_or_target)}."""
    out: dict[tuple[str, str], tuple[str, str]] = {}
    for view, versions in (formal_doc.get('views') or {}).items():
        if not isinstance(versions, dict):
            continue
        for raw_ver, links in versions.items():
            if not isinstance(links, list):
                continue
            for link in links:
                if not isinstance(link, dict):
                    continue
                lpath = link.get('path')
                if isinstance(lpath, str) and lpath:
                    out[(str(view), lpath)] = (str(raw_ver), str(link.get('resolved') or link.get('target') or ''))
    return out


def workspace_activity_and_readiness(
    work,
    *,
    days: int | None = 7,
    time_basis: str = 'archived',
    now=None,
    refresh_info=None,
    max_raw_rows: int | None = 200,
) -> dict:
    """Read-only workspace source readiness + recent RAW/new-library & Formal NL change tables (zero RAW scanning)."""
    from datetime import datetime, timedelta, timezone
    from ai_lib_qor.sources.config_reader import raw_root_values
    from ai_lib_qor.sources.layout import SAFE, archive_files
    from ai_lib_qor.sources.timestamps import instant, utc_text
    from .ip_partition import active_tracks_for_library
    from .path_config import (
        initial_delivery_tail,
        liberty_parse_filter,
        library_ip_config,
        load_path_config,
        skip_parse_views,
    )

    if time_basis not in ('archived', 'delivery'):
        raise ValueError("时间口径 time_basis 必须是 'delivery' 或 'archived'")
    root = Path(work).resolve()
    now_dt = instant(now) if now is not None else datetime.now(timezone.utc)
    if days is not None:
        if isinstance(days, bool) or not isinstance(days, int) or days < 1:
            raise ValueError('时间窗口 days 必须是正整数或 None')
        cutoff = now_dt - timedelta(days=days)
    else:
        cutoff = None

    cfg = load_path_config(root) if root.is_dir() else {}
    config_file = root / 'path_sources.json'
    config_exists = config_file.is_file() and not config_file.is_symlink()

    # 1. Source Readiness (O(1) directory stat/access checks ONLY — NEVER os.walk!)
    raw_val = raw_root_values(cfg)
    if isinstance(raw_val, str):
        raw_paths = [raw_val.strip()] if raw_val.strip() else []
    elif isinstance(raw_val, (list, tuple)):
        raw_paths = [str(x).strip() for x in raw_val if isinstance(x, str) and x.strip()]
    else:
        raw_paths = []
    raw_root_items = []
    for rp in raw_paths:
        p = Path(rp)
        exists = p.is_dir()
        readable = bool(exists and os.access(p, os.R_OK))
        raw_root_items.append({
            'path': rp,
            'exists': exists,
            'readable': readable,
            'status': 'READY' if readable else 'MISSING',
        })
    if not raw_root_items:
        raw_status = 'UNCONFIGURED'
    elif all(x['status'] == 'READY' for x in raw_root_items):
        raw_status = 'READY'
    elif any(x['status'] == 'READY' for x in raw_root_items):
        raw_status = 'PARTIAL'
    else:
        raw_status = 'MISSING'

    nl_root_str = str(cfg.get('nl_root') or '').strip()
    nl_ver_cfg = str(cfg.get('nl_version') or '').strip() or None
    if nl_root_str:
        np = Path(nl_root_str)
        nl_exists = np.is_dir()
        nl_readable = bool(nl_exists and os.access(np, os.R_OK))
        nl_status = 'READY' if nl_readable else 'MISSING'
    else:
        nl_exists, nl_readable, nl_status = False, False, 'UNCONFIGURED'

    last_l1 = (refresh_info or {}).get('last_by_layer', {}).get('L1') if isinstance(refresh_info, dict) else None
    formal_obs_status = last_l1.get('formal_observation_status') if isinstance(last_l1, dict) else None
    formal_independent_count = int((last_l1 or {}).get('formal_independent_count') or 0) if isinstance(last_l1, dict) else 0
    formal_warning_count = len((last_l1 or {}).get('warnings') or []) if isinstance(last_l1, dict) else 0

    try:
        spv = skip_parse_views(root) if root.is_dir() else ['CDL', 'SPICE', 'VERILOG']
    except ValueError:
        spv = []
    try:
        lf_cfg = liberty_parse_filter(root) if root.is_dir() else {'enabled': False, 'threshold': None}
    except ValueError:
        lf_cfg = {'enabled': False, 'threshold': None}
    try:
        init_tail = initial_delivery_tail(root) if root.is_dir() else 3
    except ValueError:
        init_tail = 3

    # 2. Recent RAW Deliveries / New Libraries & Formal (NL) Snapshot Changes (from archived JSONs ONLY)
    from .catalog_projection import (
        is_projection_fresh_readonly,
        load_delivery_discovery_times,
        query_catalog_activity_deliveries,
        resolve_archived_time,
        resolve_delivery_time,
    )
    sql_raw = None
    if is_projection_fresh_readonly(root):
        sql_raw = query_catalog_activity_deliveries(
            root,
            days=days,
            time_basis=time_basis,
            now=now_dt,
            max_rows=max_raw_rows,
            ensure_fresh=False,
        )

    discovery_map = load_delivery_discovery_times(root) if sql_raw is None else {}
    discovery_by_lib: dict[tuple[str, str], dict[str, float]] = {}
    for (dv, dlib, dver), dts in discovery_map.items():
        discovery_by_lib.setdefault((dv, dlib), {})[dver] = dts

    raw_changes = list(sql_raw['raw_changes']) if sql_raw is not None else []
    raw_candidates = []
    nl_changes = []
    new_libraries_set: set[tuple[str, str]] = set()
    active_raw_libs: set[tuple[str, str]] = set()
    active_nl_libs: set[tuple[str, str]] = set()
    cutoff_ts = cutoff.timestamp() if cutoff is not None else None

    libs_root = root / 'libraries'
    if libs_root.is_dir() and not libs_root.is_symlink():
        for folder in sorted(libs_root.glob('*/*')):
            if folder.is_symlink() or not folder.is_dir() or folder.parent.is_symlink():
                continue
            v, lib = folder.parent.name, folder.name
            if not (SAFE.fullmatch(v) and SAFE.fullmatch(lib)):
                continue

            try:
                ip_cfg = library_ip_config(root, v, lib)
            except ValueError:
                ip_cfg = {'ip_type': None, 'ip_list': [], 'is_multi_track': False}

            # --- RAW deliveries Phase 1: skipped entirely when fresh SQLite projection answered it ---
            if sql_raw is None:
                lib_disc = discovery_by_lib.get((v, lib)) or {}
                lib_min_hist = min(lib_disc.values()) if lib_disc else None
                if time_basis == 'archived':
                    deliv_stats = []
                    for p in archive_files(folder, 'delivery', 'delivery_*.json'):
                        if p.is_symlink() or not p.is_file():
                            continue
                        try:
                            st = p.stat()
                        except OSError:
                            continue
                        file_ts = st.st_mtime
                        eff_ts = file_ts
                        preloaded = None
                        if lib_disc:
                            # Fast zero-read match for canonical delivery_{lib}__{version}.json filenames
                            prefix = f'delivery_{lib}__'
                            matched_ver = p.stem[len(prefix):] if p.stem.startswith(prefix) else None
                            if matched_ver and matched_ver in lib_disc:
                                eff_ts = min(lib_disc[matched_ver], file_ts)
                            elif (
                                (cutoff_ts is None or file_ts >= cutoff_ts)
                                and lib_min_hist is not None
                                and lib_min_hist < file_ts - 60.0
                            ):
                                # Only read legacy numbered filename if file mtime jumped ahead of history (e.g. cp -r)
                                try:
                                    preloaded = read_json_readonly(p)
                                    if isinstance(preloaded, dict) and isinstance(preloaded.get('version'), str):
                                        eff_ts = resolve_archived_time(v, lib, preloaded['version'], file_ts, discovery_map)
                                except (OSError, ValueError, TypeError):
                                    preloaded = None
                        deliv_stats.append((p, eff_ts, preloaded))

                    recent_deliv_files = [
                        (p, ts, pre) for (p, ts, pre) in deliv_stats
                        if cutoff_ts is None or ts >= cutoff_ts
                    ]
                    if deliv_stats:
                        earliest_ts = min(ts for _, ts, _ in deliv_stats)
                        lib_is_new = bool(cutoff_ts is not None and earliest_ts >= cutoff_ts)
                        if lib_is_new:
                            new_libraries_set.add((v, lib))
                        if recent_deliv_files:
                            active_raw_libs.add((v, lib))
                            for p, arch_ts, pre in recent_deliv_files:
                                raw_candidates.append((arch_ts, arch_ts, v, lib, p.name, folder, p, lib_is_new, ip_cfg, pre))
                else:
                    deliv_entries = []
                    for p in archive_files(folder, 'delivery', 'delivery_*.json'):
                        if p.is_symlink() or not p.is_file():
                            continue
                        try:
                            st = p.stat()
                            data = read_json_readonly(p)
                        except (OSError, ValueError, TypeError):
                            continue
                        if not isinstance(data, dict) or not isinstance(data.get('version'), str):
                            continue
                        arch_ts = resolve_archived_time(v, lib, data['version'], st.st_mtime, discovery_map)
                        vdate = data.get('version_date')
                        dmtime = data.get('directory_mtime') or data.get('directory_created_at')
                        deliv_ts, _deliv_at, _deliv_src = resolve_delivery_time(vdate, dmtime, arch_ts)
                        deliv_entries.append((p, arch_ts, deliv_ts, data))

                    if deliv_entries:
                        earliest_ts = min(e[2] for e in deliv_entries)
                        lib_is_new = bool(cutoff_ts is not None and earliest_ts >= cutoff_ts)
                        if lib_is_new:
                            new_libraries_set.add((v, lib))
                        recent_entries = [
                            e for e in deliv_entries
                            if cutoff_ts is None or e[2] >= cutoff_ts
                        ]
                        if recent_entries:
                            active_raw_libs.add((v, lib))
                            for p, arch_ts, deliv_ts, data in recent_entries:
                                raw_candidates.append((deliv_ts, arch_ts, v, lib, p.name, folder, p, lib_is_new, ip_cfg, data))

            # --- Formal (NL) snapshots: use cached JSON reads and skip parsing snapshots entirely outside window ---
            by_nl_stage: dict[str, list[tuple[datetime, str, dict]]] = {}
            for p in archive_files(folder, 'formal', 'formal_*.json'):
                if p.is_symlink() or not p.is_file():
                    continue
                try:
                    data = read_json_readonly(p)
                    obs_dt = instant(data['observed_at'])
                    stage = str(data.get('version') or 'NL')
                except (OSError, ValueError, TypeError, KeyError):
                    continue
                by_nl_stage.setdefault(stage, []).append((obs_dt, p.name, data))

            for stage, snaps in sorted(by_nl_stage.items()):
                snaps.sort(key=lambda x: (x[0], x[1]))
                if cutoff is not None and snaps and snaps[-1][0] < cutoff:
                    continue
                prev_map: dict[tuple[str, str], tuple[str, str]] | None = None
                for idx_s, (obs_dt, fname, fdoc) in enumerate(snaps):
                    if cutoff is not None and obs_dt < cutoff:
                        # Only need the single snapshot immediately preceding the first in-window snapshot
                        if idx_s + 1 < len(snaps) and snaps[idx_s + 1][0] >= cutoff:
                            prev_map = _formal_link_map(fdoc)
                        continue
                    curr_map = _formal_link_map(fdoc)
                    if cutoff is None or obs_dt >= cutoff:
                        active_nl_libs.add((v, lib))
                        if prev_map is None:
                            change_kind = 'INITIAL'
                            added_cnt = len(curr_map)
                            switched_cnt = 0
                            removed_cnt = 0
                            samples = []
                            summary_text = f'首次快照（共 {added_cnt} 条链接）'
                        else:
                            curr_keys = set(curr_map)
                            prev_keys = set(prev_map)
                            added_keys = sorted(curr_keys - prev_keys)
                            removed_keys = sorted(prev_keys - curr_keys)
                            switched_keys = sorted(k for k in (curr_keys & prev_keys) if curr_map[k] != prev_map[k])
                            added_cnt = len(added_keys)
                            switched_cnt = len(switched_keys)
                            removed_cnt = len(removed_keys)
                            change_kind = 'UPDATED' if (added_cnt or switched_cnt or removed_cnt) else 'UNCHANGED'
                            parts = []
                            if added_cnt:
                                parts.append(f'新增 +{added_cnt}')
                            if switched_cnt:
                                parts.append(f'切版 {switched_cnt}')
                            if removed_cnt:
                                parts.append(f'移除 -{removed_cnt}')
                            summary_text = ' · '.join(parts) if parts else f'链接无变化（共 {len(curr_map)} 条）'
                            samples = []
                            for k in switched_keys[:2]:
                                samples.append(f'{k[0]}/{Path(k[1]).name}: {prev_map[k][0]} → {curr_map[k][0]}')
                            for k in added_keys[:max(0, 3 - len(samples))]:
                                samples.append(f'+ {k[0]}/{Path(k[1]).name} ({curr_map[k][0]})')
                            for k in removed_keys[:max(0, 3 - len(samples))]:
                                samples.append(f'- {k[0]}/{Path(k[1]).name}')
                        nl_changes.append({
                            'vendor': v,
                            'library': lib,
                            'ip_type': ip_cfg['ip_type'],
                            'nl_version': stage,
                            'snapshot_file': fname,
                            'observed_at': utc_text(obs_dt),
                            'observed_ts': obs_dt.timestamp(),
                            'change_kind': change_kind,
                            'total_links': len(curr_map),
                            'added': added_cnt,
                            'switched': switched_cnt,
                            'removed': removed_cnt,
                            'summary_text': summary_text,
                            'samples': samples,
                        })
                    prev_map = curr_map

    # --- RAW deliveries Phase 2: hydrate ONLY Top-K most recent deliveries (avoids reading 15,000+ JSONs) ---
    raw_candidates.sort(key=lambda r: (r[0], r[2], r[3], r[4]), reverse=True)
    total_raw_candidates = len(raw_candidates)
    total_new_lib_delivs = sum(1 for r in raw_candidates if r[7])
    raw_truncated = bool(max_raw_rows is not None and total_raw_candidates > max_raw_rows)
    selected_candidates = raw_candidates[:max_raw_rows] if raw_truncated else raw_candidates

    lib_adoption_cache: dict[tuple[str, str], tuple[dict[str, list[str]], bool, dict[str, str], set[str]]] = {}
    for _sort_ts, mtime_ts, v, lib, _fname, folder, p, lib_is_new, ip_cfg, preloaded_data in selected_candidates:
        lkey = (v, lib)
        cached_ad = lib_adoption_cache.get(lkey)
        if cached_ad is None:
            track_info = active_tracks_for_library(root, v, lib) if ip_cfg['is_multi_track'] else None
            ver_to_track: dict[str, str] = {}
            nr_versions: set[str] = set()
            if track_info and track_info.get('is_multi_track'):
                for ip_name, vers in (track_info.get('tracks') or {}).items():
                    for dv in vers:
                        ver_to_track[dv] = ip_name
                nr = track_info.get('needs_review') or {}
                for item in (nr.get('conflicts') or []):
                    if isinstance(item, dict) and item.get('version'):
                        nr_versions.add(item['version'])
                for item in (nr.get('unassigned') or []):
                    if isinstance(item, dict) and item.get('version'):
                        nr_versions.add(item['version'])
                    elif isinstance(item, str):
                        nr_versions.add(item)
            adopted_by_ver: dict[str, list[str]] = {}
            eff_has_any = False
            if ip_cfg['is_multi_track']:
                ips = list(dict.fromkeys([
                    *((track_info or {}).get('tracks') or {}).keys(),
                    *list_track_effective_ips(folder, lib),
                ]))
                for ip_name in ips:
                    lptr = _resolve_pointer_in_folder(folder, f'latest_effective__{ip_name}.json')
                    if lptr is not None:
                        try:
                            latest_row = read_json_readonly(lptr)
                        except (OSError, ValueError, TypeError):
                            latest_row = None
                    else:
                        hist = _history(folder, lib, business_ip=ip_name)
                        latest_row = hist[-1][2] if hist else None
                    if isinstance(latest_row, dict) and latest_row.get('revision'):
                        eff_has_any = True
                        for src_ver in set(_flat(latest_row.get('views') or {}).values()):
                            adopted_by_ver.setdefault(src_ver, []).append(f"{ip_name}:{latest_row['revision']}")
            else:
                lptr = _resolve_pointer_in_folder(folder, 'latest_effective.json')
                if lptr is not None:
                    try:
                        latest_row = read_json_readonly(lptr)
                    except (OSError, ValueError, TypeError):
                        latest_row = None
                else:
                    hist = _history(folder, lib)
                    latest_row = hist[-1][2] if hist else None
                if isinstance(latest_row, dict) and latest_row.get('revision'):
                    eff_has_any = True
                    for src_ver in set(_flat(latest_row.get('views') or {}).values()):
                        adopted_by_ver.setdefault(src_ver, []).append(latest_row['revision'])
            cached_ad = (adopted_by_ver, eff_has_any, ver_to_track, nr_versions)
            lib_adoption_cache[lkey] = cached_ad
        else:
            adopted_by_ver, eff_has_any, ver_to_track, nr_versions = cached_ad

        if preloaded_data is not None:
            data = preloaded_data
        else:
            try:
                data = read_json_readonly(p)
            except (OSError, ValueError, TypeError):
                continue
        if not isinstance(data, dict) or not isinstance(data.get('version'), str):
            continue
        archived_dt = datetime.fromtimestamp(mtime_ts, tz=timezone.utc)
        archived_iso = utc_text(archived_dt)
        vdate = data.get('version_date')
        dmtime = data.get('directory_mtime') or data.get('directory_created_at')
        deliv_ts, deliv_at, deliv_src = resolve_delivery_time(vdate, dmtime, mtime_ts)
        event_at = deliv_at if time_basis == 'delivery' else archived_iso
        event_ts = deliv_ts if time_basis == 'delivery' else mtime_ts
        event_src = deliv_src if time_basis == 'delivery' else 'archived'
        views_obj = data.get('views') if isinstance(data.get('views'), dict) else {}
        view_counts = {vk: len(vlist) for vk, vlist in sorted(views_obj.items()) if isinstance(vlist, list) and vlist}
        ver = data['version']
        adopted_revs = adopted_by_ver.get(ver) or []
        if ver in nr_versions:
            eff_state, eff_label = 'REVIEW', '分轨待复核'
        elif adopted_revs:
            eff_state, eff_label = 'ADOPTED', '已入版 ' + ', '.join(adopted_revs[:2])
        elif eff_has_any:
            eff_state, eff_label = 'ARCHIVED', '已归档（已被新版覆盖或未选入）'
        else:
            eff_state, eff_label = 'PENDING', '待建有效版'
        raw_changes.append({
            'vendor': v,
            'library': lib,
            'ip_type': ip_cfg['ip_type'],
            'track_ip': ver_to_track.get(ver),
            'is_new_library': lib_is_new,
            'change_badge': '新增库' if lib_is_new else '新增交付',
            'version': ver,
            'version_date': vdate,
            'directory_mtime': dmtime,
            'archived_at': archived_iso,
            'archived_ts': mtime_ts,
            'delivery_at': deliv_at,
            'delivery_ts': deliv_ts,
            'delivery_time_source': deliv_src,
            'event_at': event_at,
            'event_ts': event_ts,
            'event_time_source': event_src,
            'file_count': sum(view_counts.values()),
            'view_counts': view_counts,
            'eff_state': eff_state,
            'eff_label': eff_label,
        })

    raw_changes.sort(key=lambda r: (r['event_ts'], r['vendor'], r['library'], r['version']), reverse=True)
    nl_changes.sort(key=lambda r: (r['observed_ts'], r['vendor'], r['library'], r['nl_version']), reverse=True)

    totals = (refresh_info or {}).get('totals') or {}
    libs_total = int(totals.get('libraries', 0))
    libs_eff = int(totals.get('libraries_with_effective', 0))
    idx_fresh = int(totals.get('index_fresh', 0))
    idx_issue = int(totals.get('index_stale_or_unverified', 0)) + int(totals.get('index_missing', 0))

    raw_deliv_total = sql_raw['total_raw_deliveries'] if sql_raw is not None else (total_raw_candidates if raw_truncated else len(raw_changes))
    new_lib_deliv_total = (
        sql_raw['new_library_deliveries']
        if sql_raw is not None
        else (total_new_lib_delivs if raw_truncated else sum(1 for r in raw_changes if r['is_new_library']))
    )

    return {
        'work': str(root),
        'now': utc_text(now_dt),
        'window_days': days,
        'window_label': f'近 {days} 日' if days is not None else '全部历史',
        'time_basis': time_basis,
        'time_basis_label': '按 RAW 交付日期' if time_basis == 'delivery' else '按工作台发现时间',
        'cutoff': utc_text(cutoff) if cutoff is not None else None,
        'readiness': {
            'config_exists': config_exists,
            'raw_status': raw_status,
            'raw_roots': raw_root_items,
            'formal_status': nl_status,
            'formal_root': nl_root_str or None,
            'formal_version': nl_ver_cfg,
            'formal_observation_status': formal_obs_status,
            'formal_independent_count': formal_independent_count,
            'formal_warning_count': formal_warning_count,
            'libraries_total': libs_total,
            'libraries_with_effective': libs_eff,
            'indexes_ready': idx_fresh,
            'indexes_issue': idx_issue,
            'skip_parse_views': spv,
            'initial_delivery_tail': init_tail,
            'liberty_filter_enabled': bool(lf_cfg.get('enabled')),
            'liberty_filter_threshold': lf_cfg.get('threshold'),
        },
        'counts': {
            'new_libraries': sql_raw['new_libraries'] if sql_raw is not None else len(new_libraries_set),
            'raw_deliveries': raw_deliv_total,
            'new_library_deliveries': new_lib_deliv_total,
            'existing_library_deliveries': max(0, raw_deliv_total - new_lib_deliv_total),
            'raw_libraries_touched': sql_raw['raw_libraries_touched'] if sql_raw is not None else len(active_raw_libs),
            'nl_changes': len(nl_changes),
            'nl_libraries_touched': len(active_nl_libs),
        },
        'raw_changes_truncated': sql_raw['raw_changes_truncated'] if sql_raw is not None else raw_truncated,
        'raw_changes_shown': len(raw_changes),
        'raw_changes': raw_changes,
        'nl_changes': nl_changes,
    }


def format_bytes(n) -> str:
    val = float(n)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if val < 1024 or unit == 'GB':
            return f'{val:.1f} {unit}' if unit != 'B' else f'{int(val)} B'
        val /= 1024.0
    return f'{n} B'


def _fmt_mtime_utc(path: Path):
    from datetime import datetime, timezone
    try:
        st = path.stat()
    except OSError:
        return '—', 0, '—', 0
    dt = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    return dt, int(st.st_mtime), format_bytes(st.st_size), int(st.st_size)


def _resolve_pointer_in_folder(folder: Path, pointer_name: str):
    ptr = folder / pointer_name
    if not ptr.is_symlink():
        return None
    try:
        target = ptr.resolve(strict=True)
        if target.is_relative_to(folder.resolve()) and target.is_file():
            return target
    except (OSError, ValueError):
        return None
    return None


def source_verification_note(source: str, evidence) -> str:
    if not evidence or not evidence.get('at'):
        return '暂无本库来源核验记录'
    at = evidence['at'].replace('T', ' ').removesuffix('Z')
    verified = evidence.get('verified_at')
    last_full = f" · 上次完整核验 {verified.replace('T', ' ').removesuffix('Z')} UTC" if verified and verified != evidence['at'] else ''
    if source == 'RAW':
        if evidence['versions_incomplete']:
            return f'最近 RAW 盘点 {at} UTC（有版本未完成）{last_full}'
        if evidence['versions_reused']:
            return f"最近 RAW 盘点 {at} UTC（复用 {evidence['versions_reused']} 个已归档版本）{last_full}"
    elif evidence['status'] == 'PARTIAL':
        return f'最近 Formal 盘点 {at} UTC（观察不完整）{last_full}'
    elif evidence['status'] == 'NO_MATCH':
        return f'最近 Formal 盘点 {at} UTC（本库没有匹配链接）{last_full}'
    return f'最近 {source} 核验 {at} UTC'


def collect_json_inventory(work, refresh_info, libraries, *, include_workspace=True, filters=None, page_size=None) -> dict:
    """Shared read-only query: filter, sort, and paginate saved JSON archive inventory across workspace or library."""
    import re
    from ai_lib_qor.sources.layout import archive_files
    from .path_config import workbench_runtime_settings

    root = Path(work)
    filters = filters or {}
    if len(libraries or ()) > 50:
        from .catalog_projection import is_projection_fresh_readonly, query_catalog_json_inventory
        if is_projection_fresh_readonly(root):
            sql_inv = query_catalog_json_inventory(
                root,
                include_workspace=include_workspace,
                filters=filters,
                page_size=page_size,
                ensure_fresh=False,
            )
            if sql_inv is not None:
                return sql_inv
    if page_size is None:
        try:
            page_size = workbench_runtime_settings(root)['json_inventory_page_size']
        except (OSError, ValueError, TypeError):
            page_size = 100
    page_size = max(1, min(500, int(page_size)))

    last_by = (refresh_info or {}).get('last_by_layer') or {}
    r1, r2, r3 = (last_by.get(layer) for layer in ('L1', 'L2', 'L3'))

    changed_deliveries = {}
    changed_formals = {}
    if r1:
        for item in r1.get('libraries_changed') or []:
            key = (item.get('vendor'), item.get('library'))
            if item.get('new_deliveries'):
                changed_deliveries[key] = set(item['new_deliveries'])
            if item.get('new_formals'):
                changed_formals[key] = set(item['new_formals'])

    changed_revs = {}
    if r2:
        for item in r2.get('libraries_changed') or []:
            key = (item.get('vendor'), item.get('library'))
            for ev in item.get('events') or []:
                if ev.get('revision'):
                    ev_key = (key[0], key[1], ev.get('business_ip'))
                    changed_revs.setdefault(ev_key, {})[ev['revision']] = ev.get('action') or 'UPDATE'

    rows = []

    if include_workspace:
        cfg_path = root / 'path_sources.json'
        if cfg_path.is_file() and not cfg_path.is_symlink():
            dt, ts, sz_txt, sz = _fmt_mtime_utc(cfg_path)
            rows.append({
                'layer': 'WORKSPACE',
                'layer_label': '工作区',
                'category': '来源目录配置',
                'filename': 'path_sources.json',
                'rel_path': 'path_sources.json',
                'vendor': '',
                'library': '',
                'scope_label': '工作区全局',
                'sync_group': 'unchanged',
                'status_label': '已生效',
                'tag_cls': 'tag-inherited',
                'status_note': '记录 RAW 与 Formal 根目录及默认同步选项',
                'pointer_badge': '',
                'updated_at': dt,
                'updated_ts': ts,
                'size_text': sz_txt,
                'size_bytes': sz,
                'exists': True,
                'action_kind': 'config',
            })
        else:
            rows.append({
                'layer': 'WORKSPACE',
                'layer_label': '工作区',
                'category': '来源目录配置',
                'filename': 'path_sources.json',
                'rel_path': 'path_sources.json',
                'vendor': '',
                'library': '',
                'scope_label': '工作区全局',
                'sync_group': 'issue',
                'status_label': '未配置',
                'tag_cls': 'tag-partial',
                'status_note': '请前往「目录配置」设置来源根目录',
                'pointer_badge': '',
                'updated_at': '—',
                'updated_ts': 0,
                'size_text': '—',
                'size_bytes': 0,
                'exists': False,
                'action_kind': 'config',
            })

        hist_path = root / 'refresh_history.jsonl'
        if hist_path.is_file() and not hist_path.is_symlink():
            dt, ts, sz_txt, sz = _fmt_mtime_utc(hist_path)
            runs_cnt = len((refresh_info or {}).get('recent_runs') or [])
            rows.append({
                'layer': 'WORKSPACE',
                'layer_label': '工作区',
                'category': '同步审计日志',
                'filename': 'refresh_history.jsonl',
                'rel_path': 'refresh_history.jsonl',
                'vendor': '',
                'library': '',
                'scope_label': '工作区全局',
                'sync_group': 'unchanged',
                'status_label': '持续记录',
                'tag_cls': 'tag-inherited',
                'status_note': f'最近 {runs_cnt} 条同步批次已留痕',
                'pointer_badge': '',
                'updated_at': dt,
                'updated_ts': ts,
                'size_text': sz_txt,
                'size_bytes': sz,
                'exists': True,
                'action_kind': 'history',
            })

    for lib_item in libraries or []:
        v = lib_item['vendor']
        lib = lib_item['library']
        try:
            folder = library_folder(root, v, lib)
        except ValueError:
            continue
        if not folder.is_dir():
            continue

        key = (v, lib)
        scope_label = f'{v}/{lib}'
        latest_deliv = _resolve_pointer_in_folder(folder, 'latest_delivery.json')
        latest_eff = _resolve_pointer_in_folder(folder, 'latest_effective.json')
        accepted_eff = _resolve_pointer_in_folder(folder, 'accepted_effective.json')
        latest_formals = set()
        for fptr in folder.glob('latest_formal_*.json'):
            resolved = _resolve_pointer_in_folder(folder, fptr.name)
            if resolved:
                latest_formals.add(resolved)

        sources = lib_item.get('source_verifications', {})
        raw_note = source_verification_note('RAW', sources.get('RAW'))
        formal_evidence = sources.get('FORMAL', {})
        index_attempt = lib_item.get('index_attempt') or {}
        index_failure = index_attempt.get('reason') if index_attempt.get('status') == 'FAILED' else None

        # L1: RAW deliveries
        deliv_changed_versions = changed_deliveries.get(key) or set()
        for p in archive_files(folder, 'delivery', 'delivery_*.json'):
            if p.is_symlink() or not p.is_file():
                continue
            dt, ts, sz_txt, sz = _fmt_mtime_utc(p)
            rel_in_lib = str(p.relative_to(folder))
            is_new = False
            if deliv_changed_versions:
                try:
                    d_ver = json.loads(p.read_text(encoding='utf-8')).get('version')
                    is_new = d_ver in deliv_changed_versions
                except (OSError, ValueError, TypeError):
                    is_new = False
            if is_new:
                sg, sl, tc = 'updated', '本轮新增', 'tag-new'
            else:
                sg, sl, tc = 'unchanged', '已归档', 'tag-inherited'
            rows.append({
                'layer': 'L1',
                'layer_label': 'L1 来源',
                'category': 'RAW 交付归档',
                'filename': p.name,
                'rel_path': f'{scope_label}/{rel_in_lib}',
                'vendor': v,
                'library': lib,
                'scope_label': scope_label,
                'sync_group': sg,
                'status_label': sl,
                'tag_cls': tc,
                'status_note': raw_note,
                'pointer_badge': '最新交付' if (latest_deliv and p.resolve() == latest_deliv) else '',
                'updated_at': dt,
                'updated_ts': ts,
                'size_text': sz_txt,
                'size_bytes': sz,
                'exists': True,
                'action_kind': 'library',
            })

        # L1: Formal snapshots
        formal_changed_names = changed_formals.get(key) or set()
        for p in archive_files(folder, 'formal', 'formal_*.json'):
            if p.is_symlink() or not p.is_file():
                continue
            dt, ts, sz_txt, sz = _fmt_mtime_utc(p)
            rel_in_lib = str(p.relative_to(folder))
            match = re.fullmatch(r'formal_(.+?)_(?:\d{8}T\d{6}Z_)?\d+\.json', p.name)
            note = source_verification_note('Formal', formal_evidence.get(match[1]) if match else None)
            if p.name in formal_changed_names:
                sg, sl, tc = 'updated', '本轮新增', 'tag-new'
            else:
                sg, sl, tc = 'unchanged', '已归档', 'tag-inherited'
            rows.append({
                'layer': 'L1',
                'layer_label': 'L1 来源',
                'category': 'Formal 快照',
                'filename': p.name,
                'rel_path': f'{scope_label}/{rel_in_lib}',
                'vendor': v,
                'library': lib,
                'scope_label': scope_label,
                'sync_group': sg,
                'status_label': sl,
                'tag_cls': tc,
                'status_note': note,
                'pointer_badge': '最新快照' if (p.resolve() in latest_formals) else '',
                'updated_at': dt,
                'updated_ts': ts,
                'size_text': sz_txt,
                'size_bytes': sz,
                'exists': True,
                'action_kind': 'index',
            })

        # L2: Business IP partition config (per-(vendor, library) canonical path with vendor-matched legacy fallback)
        from .ip_partition import resolve_existing_partition_path
        try:
            part_path, part_is_legacy = resolve_existing_partition_path(root, v, lib)
        except ValueError:
            part_path, part_is_legacy = None, False
        if part_path is not None and part_path.is_file() and not part_path.is_symlink():
            dt, ts, sz_txt, sz = _fmt_mtime_utc(part_path)
            nr_cnt = int(lib_item.get('needs_review_count', 0))
            if nr_cnt > 0:
                sg, sl, tc, sn = 'issue', f'待复核 {nr_cnt} 项', 'tag-partial', '存在多命中冲突或未归类版本，请核对后重跑分轨'
            else:
                tr_cnt = len(lib_item.get('tracks') or {})
                legacy_hint = '（旧根路径，下次分轨将无损迁至库内）' if part_is_legacy else '（人工修改受增量保护）'
                sg, sl, tc, sn = 'unchanged', '已分轨', 'tag-inherited', f'已归类 {tr_cnt} 条业务 IP 轨道{legacy_hint}'
            rel_part = part_path.name if part_is_legacy else f'{scope_label}/ip_partition.json'
            rows.append({
                'layer': 'L2',
                'layer_label': 'L2 版本',
                'category': '业务 IP 分轨配置',
                'filename': part_path.name,
                'rel_path': rel_part,
                'vendor': v,
                'library': lib,
                'scope_label': scope_label,
                'sync_group': sg,
                'status_label': sl,
                'tag_cls': tc,
                'status_note': sn,
                'pointer_badge': lib_item.get('ip_type') or '',
                'updated_at': dt,
                'updated_ts': ts,
                'size_text': sz_txt,
                'size_bytes': sz,
                'exists': True,
                'action_kind': 'library',
            })

        # L2: Effective revisions
        eff_files = [p for p in archive_files(folder, 'effective', f'effective_{lib}_*.json') if not p.is_symlink() and p.is_file()]
        track_ptr_cache = {}

        def _track_ptrs(ip_name):
            if ip_name not in track_ptr_cache:
                if ip_name:
                    track_ptr_cache[ip_name] = (
                        _resolve_pointer_in_folder(folder, f'latest_effective__{ip_name}.json'),
                        _resolve_pointer_in_folder(folder, f'accepted_effective__{ip_name}.json'),
                    )
                else:
                    track_ptr_cache[ip_name] = (latest_eff, accepted_eff)
            return track_ptr_cache[ip_name]

        if eff_files:
            track_pat = re.compile(rf'^effective_{re.escape(lib)}__([A-Za-z0-9][A-Za-z0-9_.-]*)_(\d+)\.json$')
            single_pat = re.compile(rf'^effective_{re.escape(lib)}_(\d+)\.json$')
            for p in eff_files:
                dt, ts, sz_txt, sz = _fmt_mtime_utc(p)
                rel_in_lib = str(p.relative_to(folder))
                m_tr = track_pat.fullmatch(p.name)
                m_sg = single_pat.fullmatch(p.name) if not m_tr else None
                eff_ip = m_tr.group(1) if m_tr else None
                rev_num = m_tr.group(2) if m_tr else (m_sg.group(1) if m_sg else None)
                rev_id = f'rev_{int(rev_num):04d}' if rev_num else ''
                rev_changed_map = changed_revs.get((v, lib, eff_ip)) or {}
                act = rev_changed_map.get(rev_id)
                if act == 'INITIALIZE':
                    sg, sl, tc, sn = 'updated', '本轮初始化', 'tag-new', '最近 L2 推进自动初始化'
                elif act:
                    sg, sl, tc, sn = 'updated', '本轮发布', 'tag-new', '最近 L2 推进自动演进'
                else:
                    sg, sl, tc, sn = 'unchanged', '已归档', 'tag-inherited', '只读有效版本归档'
                p_res = p.resolve()
                cur_latest, cur_acc = _track_ptrs(eff_ip)
                badges = []
                if eff_ip:
                    badges.append(eff_ip)
                if cur_latest and p_res == cur_latest:
                    badges.append('最新有效版')
                if cur_acc and p_res == cur_acc:
                    badges.append('已采纳')
                rows.append({
                    'layer': 'L2',
                    'layer_label': 'L2 版本',
                    'category': (f'{eff_ip} · 有效版本 {rev_id}' if eff_ip else (f'有效版本 {rev_id}' if rev_id else '有效版本归档')),
                    'filename': p.name,
                    'rel_path': f'{scope_label}/{rel_in_lib}',
                    'vendor': v,
                    'library': lib,
                    'business_ip': eff_ip,
                    'scope_label': scope_label,
                    'sync_group': sg,
                    'status_label': sl,
                    'tag_cls': tc,
                    'status_note': sn,
                    'pointer_badge': ' · '.join(badges),
                    'updated_at': dt,
                    'updated_ts': ts,
                    'size_text': sz_txt,
                    'size_bytes': sz,
                    'exists': True,
                    'action_kind': 'library',
                    'revision': rev_id,
                })
        else:
            has_formal = (lib_item.get('formal_count') or 0) > 0
            is_mt = bool(lib_item.get('is_multi_track'))
            rows.append({
                'layer': 'L2',
                'layer_label': 'L2 版本',
                'category': '有效版本归档',
                'filename': f'effective_{lib}_001.json',
                'rel_path': f'{scope_label}/effective/effective_{lib}_001.json',
                'vendor': v,
                'library': lib,
                'scope_label': scope_label,
                'sync_group': 'issue',
                'status_label': '未建有效版',
                'tag_cls': 'tag-partial',
                'status_note': '已配置多业务 IP 分轨，请先执行分轨并推进 L2' if is_mt else ('已有 Formal 快照，可推进 L2 初始化' if has_formal else '尚无 Formal 快照，待初始化'),
                'pointer_badge': '',
                'updated_at': '—',
                'updated_ts': 0,
                'size_text': '—',
                'size_bytes': 0,
                'exists': False,
                'action_kind': 'library',
            })

        # L3: File index
        idx_path = folder / 'file_index.json'
        idx_status = lib_item.get('index_status') or ('MISSING' if not idx_path.is_file() else 'UNVERIFIED')
        if idx_status == 'MISSING' or idx_path.is_symlink() or not idx_path.is_file():
            rows.append({
                'layer': 'L3',
                'layer_label': 'L3 索引',
                'category': '跨版本文件索引',
                'filename': 'file_index.json',
                'rel_path': f'{scope_label}/file_index.json',
                'vendor': v,
                'library': lib,
                'scope_label': scope_label,
                'sync_group': 'issue',
                'status_label': '刷新失败' if index_failure else '未生成',
                'tag_cls': 'tag-failed',
                'status_note': index_failure or '索引缺失，需确认顺序后刷新 L3',
                'pointer_badge': '',
                'updated_at': '—',
                'updated_ts': 0,
                'size_text': '—',
                'size_bytes': 0,
                'exists': False,
                'action_kind': 'library',
            })
        else:
            dt, ts, sz_txt, sz = _fmt_mtime_utc(idx_path)
            if index_failure:
                sg, sl, tc, sn = 'issue', '刷新失败', 'tag-failed', index_failure
            elif idx_status in ('STALE', 'UNVERIFIED'):
                sg = 'issue'
                sl = '待刷新'
                tc = 'tag-partial'
                sn = '归档已变动，需刷新 L3' if idx_status == 'STALE' else '未校验指纹，建议刷新 L3'
            elif index_attempt.get('status') == 'UPDATED' and r3 and index_attempt.get('at') == r3.get('at'):
                sg = 'updated'
                sl = '本轮更新'
                tc = 'tag-new'
                sn = '最近 L3 同步已重建索引'
            else:
                sg = 'unchanged'
                sl = '同步一致'
                tc = 'tag-new'
                sn = '与来源归档指纹一致'
            rows.append({
                'layer': 'L3',
                'layer_label': 'L3 索引',
                'category': '跨版本文件索引',
                'filename': 'file_index.json',
                'rel_path': f'{scope_label}/file_index.json',
                'vendor': v,
                'library': lib,
                'scope_label': scope_label,
                'sync_group': sg,
                'status_label': sl,
                'tag_cls': tc,
                'status_note': sn,
                'pointer_badge': '',
                'updated_at': dt,
                'updated_ts': ts,
                'size_text': sz_txt,
                'size_bytes': sz,
                'exists': True,
                'action_kind': 'download_index',
            })

    group_rank = {'updated': 0, 'issue': 1, 'unchanged': 2}
    layer_rank = {'L1': 0, 'L2': 1, 'L3': 2, 'WORKSPACE': 3}
    counts = {'total': len(rows), **dict.fromkeys(group_rank, 0), **dict.fromkeys(layer_rank, 0)}
    for row in rows:
        counts[row['layer']] += 1
        counts[row['sync_group']] += 1

    query_params = {key: str(filters.get(key, '') or '').strip() for key in ('json_layer', 'json_status', 'json_scope', 'json_q', 'json_sort')}
    if query_params['json_layer'] not in layer_rank:
        query_params['json_layer'] = ''
    if query_params['json_status'] not in group_rank:
        query_params['json_status'] = ''
    if query_params['json_sort'] not in ('newest', 'layer'):
        query_params['json_sort'] = 'priority'
    q = query_params['json_q'].casefold()
    search_fields = ('filename', 'rel_path', 'category', 'scope_label', 'status_label', 'status_note')
    rows = [
        row for row in rows
        if (not query_params['json_layer'] or row['layer'] == query_params['json_layer'])
        and (not query_params['json_status'] or row['sync_group'] == query_params['json_status'])
        and (not query_params['json_scope'] or row['scope_label'] == query_params['json_scope'])
        and (not q or q in ' '.join(row[key] for key in search_fields).casefold())
    ]

    def sort_key(row):
        layer = layer_rank[row['layer']]
        scope_lbl, filename = row['scope_label'], row['rel_path']
        newest = -row['updated_ts']
        if query_params['json_sort'] == 'newest':
            return newest, layer, scope_lbl, filename
        if query_params['json_sort'] == 'layer':
            return layer, scope_lbl, newest, filename
        return group_rank[row['sync_group']], newest, layer, scope_lbl, filename

    rows.sort(key=sort_key)
    try:
        page = int(filters.get('json_page', 1))
    except (ValueError, TypeError):
        page = 1
    pages = max(1, (len(rows) + page_size - 1) // page_size)
    page = max(1, min(page, pages))
    return {
        'rows': rows[(page - 1) * page_size : page * page_size],
        'counts': counts,
        'matched': len(rows),
        'page': page,
        'pages': pages,
        'page_size': page_size,
        'query': query_params,
    }


def query_json_inventory(work, *, vendor=None, library=None, filters=None, page_size=None) -> dict:
    """Stateless high-level entry for workspace or single-library JSON archive inventory."""
    from ai_lib_qor.sources.layout import archive_files
    from .ip_partition import active_tracks_for_library
    from .path_refresh import read_refresh_history, refresh_status

    root = Path(work)
    if bool(vendor) != bool(library):
        raise ValueError('vendor 和 library 必须同时指定或同时省略')
    if vendor and library:
        folder = library_folder(root, vendor, library)
        if not folder.is_dir():
            raise ValueError(f'库目录不存在: {vendor}/{library}')
        idx_path = folder / 'file_index.json'
        if idx_path.is_symlink() or not idx_path.is_file():
            lib_idx_status = 'MISSING'
        else:
            matched_m, manifest_m = index_manifest_matches(root, vendor, library, fast=True)
            lib_idx_status = 'FRESH' if matched_m else ('UNVERIFIED' if manifest_m is None else 'STALE')
        _, last_by_layer, verifications, index_attempts = read_refresh_history(root, limit=0)
        track_info = active_tracks_for_library(root, vendor, library)
        nr_info = track_info.get('needs_review') or {}
        key = (vendor, library)
        single_item = {
            'vendor': vendor,
            'library': library,
            'formal_count': len([p for p in archive_files(folder, 'formal', 'formal_*.json') if not p.is_symlink()]),
            'index_status': lib_idx_status,
            'source_verifications': verifications.get(key, {}),
            'index_attempt': index_attempts.get(key),
            'ip_type': track_info.get('ip_type'),
            'is_multi_track': track_info.get('is_multi_track'),
            'tracks': track_info.get('tracks') or {},
            'needs_review_count': len(nr_info.get('conflicts') or []) + len(nr_info.get('unassigned') or []),
        }
        return collect_json_inventory(
            root,
            {'last_by_layer': last_by_layer},
            [single_item],
            include_workspace=False,
            filters=filters,
            page_size=page_size,
        )
    st = refresh_status(root, limit=8)
    return collect_json_inventory(
        root,
        st,
        st.get('libraries') or [],
        include_workspace=True,
        filters=filters,
        page_size=page_size,
    )


_VALID_NL_RELATIONS = frozenset({'', '来源相同', '来源不同', '无法确认', '无法对照', '最新快照未观察到', '尚无 Formal 快照'})


def query_file_index(
    work,
    vendor: str,
    library: str,
    *,
    business_ip: str | None = None,
    q: str = '',
    view: str = '',
    delivery: str = '',
    nl_version: str = '',
    adoption: str = '',
    nl_rel: str = '',
    revision: str = '',
    page: int = 1,
    page_size: int | None = None,
    index: dict | None = None,
) -> dict:
    """Shared read-only query: filter, compare against Formal snapshot, and paginate file_index rows."""
    from .formal_comparison import compare_formal_member, latest_formal_snapshot
    from .path_config import workbench_runtime_settings

    root = Path(work)
    folder = library_folder(root, vendor, library)
    if not folder.is_dir():
        raise ValueError(f'库目录不存在: {vendor}/{library}')
    ip = _norm_business_ip(business_ip)
    if page_size is None:
        try:
            page_size = workbench_runtime_settings(root)['index_page_size']
        except (OSError, ValueError, TypeError):
            page_size = 80
    page_size = max(1, min(500, int(page_size)))
    if not isinstance(page, int) or page < 1:
        raise ValueError('page 必须是大于等于 1 的整数')

    if index is None:
        index = PathDataQuery(root).index(vendor, library)
        if ip is not None:
            index, _, _ = build_track_index_view(folder, vendor, library, index, ip)

    q_clean = str(q or '').strip()
    view = str(view or '').strip()
    delivery = str(delivery or '').strip()
    nl_version = str(nl_version or '').strip()
    adoption = str(adoption or '').strip()
    nl_rel = str(nl_rel or '').strip()
    revision = str(revision or '').strip()

    rows = []
    views = []
    nl_versions = []
    if index:
        views = sorted(index['views'])
        nl_versions = sorted({n['nl_version'] for n in index['nl_snapshots']})
        if nl_version and nl_version not in nl_versions:
            raise ValueError(f'无效的 Formal 版本: {nl_version}')
        if not nl_version and index['nl_snapshots']:
            nl_version = index['nl_snapshots'][-1]['nl_version']
        latest = latest_formal_snapshot(index, nl_version or None)
        if delivery and delivery not in [d['version'] for d in index['deliveries']]:
            raise ValueError(f'无效的交付版本: {delivery}')
        if view and view not in views:
            raise ValueError(f'无效的 View 类别: {view}')
        if revision and revision not in index['revisions']:
            raise ValueError(f'无效的有效版本: {revision}')
        if adoption not in ('', 'adopted', 'unadopted'):
            raise ValueError(f'无效的纳入状态筛选: {adoption}')
        if nl_rel not in _VALID_NL_RELATIONS:
            raise ValueError(f'无效的 Formal 对照筛选: {nl_rel}')
        if not revision and index['revisions']:
            revision = index['revisions'][-1]
        for kind, group in index['views'].items():
            if view and kind != view:
                continue
            for path, history in group.items():
                if delivery and not any(r['version'] == delivery for r in history['raw']):
                    continue
                if q_clean:
                    hay = (kind + ' ' + path + ' ' + ' '.join(r['version'] for r in history['raw'])).casefold()
                    if q_clean.casefold() not in hay:
                        continue
                effective_in_rev = None
                if revision:
                    effective_in_rev = next((e for e in history['effective'] if e['revision'] == revision), None)
                if adoption == 'adopted' and not effective_in_rev:
                    continue
                if adoption == 'unadopted' and effective_in_rev:
                    continue
                nl_latest, nl_relation = compare_formal_member(latest, history['nl'], effective_in_rev)
                if nl_rel and nl_relation != nl_rel:
                    continue
                rows.append({
                    'view': kind,
                    'path': path,
                    'effective_in_rev': effective_in_rev,
                    'nl_latest': nl_latest,
                    'nl_relation': nl_relation,
                    **history,
                })
    total = len(rows)
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    return {
        'vendor': vendor,
        'library': library,
        'business_ip': ip,
        'rows': rows[(page - 1) * page_size : page * page_size],
        'views': views,
        'view': view,
        'q': q_clean,
        'delivery': delivery,
        'deliveries': [d['version'] for d in (index.get('deliveries') or [])] if index else [],
        'revisions': list(index.get('revisions') or []) if index else [],
        'nl_version': nl_version,
        'nl_versions': nl_versions,
        'adoption': adoption,
        'nl_rel': nl_rel,
        'page': page,
        'pages': pages,
        'page_size': page_size,
        'total': total,
        'revision': revision,
    }
