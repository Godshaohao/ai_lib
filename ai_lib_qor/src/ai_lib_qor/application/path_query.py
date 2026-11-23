"""Shared read-only queries, unified check lookup, tooling freshness checks, and unadopted-file summaries."""
import json
from pathlib import Path

from ai_lib_qor.checks.path_plugins import PATH_CHECK_PLUGINS, evaluate_check_verdict, plugin_versions
from ai_lib_qor.facts.registry import current_parser_info
from ai_lib_qor.sources.layout import library_folder
from ai_lib_qor.versions.store import locked
from .minimal_effective import _deliveries, _flat, _history
from .minimal_file_index import _archive_stat_summary, _configured_times, _ordered, build_index, index_manifest_matches, read_manifest, without_formal_snapshot_ids
from .path_config import ignored_unadopted_files

_UNSET = object()
_RUNS_TAIL_BYTES = 65536


def check_tooling_status(report, *, expected_plugins=None):
    """Compare a saved CheckResult's parser signatures & plugin versions against active tooling (read-only)."""
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


def _summarize_check_record(folder: Path, path: Path, data: dict, *, expected_plugins=None) -> dict:
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
    return {
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
        'tooling_status': check_tooling_status(data, expected_plugins=expected_plugins),
    }


def _iter_saved_checks(folder: Path):
    if not folder.is_dir():
        return []
    candidates = [*folder.glob('check_run_*.json')]
    log_dir = folder / 'log'
    if log_dir.is_dir() and not log_dir.is_symlink():
        candidates.extend(log_dir.glob('check_rev_*_run_*.json'))
    return sorted(candidates, key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)


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
):
    """O(1) tail-seek check lookup using log/runs.jsonl when no out-of-band check file is newer than runs.jsonl."""
    log_dir = folder / 'log'
    runs_path = log_dir / 'runs.jsonl'
    if log_dir.is_symlink() or runs_path.is_symlink() or not runs_path.is_file():
        return None, False
    try:
        runs_mtime = runs_path.stat().st_mtime_ns
        if folder.stat().st_mtime_ns > runs_mtime or log_dir.stat().st_mtime_ns > runs_mtime:
            return None, False
        tail_lines, read_all = _read_tail_lines(runs_path)
    except OSError:
        return None, False

    match_baseline = baseline is not _UNSET
    wanted_plugins = sorted(set(plugins)) if plugins is not None else None
    folder_res = folder.resolve()

    def scan(lines):
        for raw in reversed(lines):
            try:
                ev = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if ev.get('type') != 'CHECK' or ev.get('revision') != revision:
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
                data = json.loads(target.read_text(encoding='utf-8'))
                if (
                    data.get('schema_version') == 'check_result.path.v1'
                    and (data.get('vendor'), data.get('library')) == (vendor, library)
                    and data.get('revision') == revision
                    and (not match_baseline or data.get('baseline') == baseline)
                    and _plugins_match(data, plugins)
                ):
                    return _summarize_check_record(folder, target, data, expected_plugins=plugins)
            except (OSError, ValueError, TypeError, KeyError):
                continue
        return None

    hit = scan(tail_lines)
    if hit is not None:
        return hit, True
    if not read_all:
        try:
            full_lines = [ln for ln in runs_path.read_text(encoding='utf-8').splitlines() if ln.strip()]
            hit = scan(full_lines)
            if hit is not None:
                return hit, True
        except OSError:
            return None, False
    return None, False


def find_latest_check(work, vendor, library, *, revision, baseline=_UNSET, plugins=None):
    """Unified single entry point for looking up the newest saved CheckResult matching (revision, baseline, plugins)."""
    if not revision:
        return None
    folder = library_folder(work, vendor, library)
    hit, resolved = _fast_lookup_via_runs_jsonl(folder, vendor, library, revision, baseline=baseline, plugins=plugins)
    if resolved:
        return hit
    match_baseline = baseline is not _UNSET
    for path in _iter_saved_checks(folder):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if (
                data.get('schema_version') == 'check_result.path.v1'
                and (data.get('vendor'), data.get('library')) == (vendor, library)
                and data.get('revision') == revision
                and (not match_baseline or data.get('baseline') == baseline)
                and _plugins_match(data, plugins)
            ):
                return _summarize_check_record(folder, path, data, expected_plugins=plugins)
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return None


def latest_check_for_scope(work, vendor, library, revision, baseline, *, plugins=None):
    """Find the most recent saved CheckResult matching (revision, baseline[, plugins]) without triggering parsing."""
    return find_latest_check(work, vendor, library, revision=revision, baseline=baseline, plugins=plugins)


def latest_check_for_revision(work, vendor, library, target_revision, *, plugins=None):
    """Find the most recent saved CheckResult for target_revision regardless of baseline (read-only)."""
    return find_latest_check(work, vendor, library, revision=target_revision, baseline=_UNSET, plugins=plugins)


def unadopted_new_files(work, vendor, library, *, sample_limit=20):
    """Read-only diff of files present in latest archived delivery but not yet in latest effective revision (respecting ignored list)."""
    folder = library_folder(work, vendor, library)
    if not folder.is_dir():
        return None
    try:
        latest_eff_ptr = folder / 'latest_effective.json'
        eff_dir = folder / 'effective'
        if not latest_eff_ptr.is_symlink() and not eff_dir.is_dir() and not any(folder.glob(f'effective_{library}_*.json')):
            return None
        eff_data = None
        if latest_eff_ptr.is_symlink():
            tgt = latest_eff_ptr.resolve(strict=True)
            if tgt.is_relative_to(folder.resolve()) and tgt.is_file():
                eff_data = json.loads(tgt.read_text(encoding='utf-8'))
        if eff_data is None:
            hist = _history(folder, library)
            eff_data = hist[-1][2] if hist else None
        if not eff_data:
            return None

        latest_deliv_ptr = folder / 'latest_delivery.json'
        deliv_data = None
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
        return {
            'latest_delivery': deliv_data.get('version'),
            'latest_revision': eff_data.get('revision'),
            'count': len(active),
            'ignored_count': ignored_count,
            'sample': active[:sample_limit],
        }
    except (OSError, ValueError, TypeError, KeyError):
        return None


def build_check_context_from_index(vendor, library, index, revision, baseline=None):
    """Build check context purely in-memory from an already-verified file_index dict (zero redundant disk I/O)."""
    revisions = index['revisions']
    if revision not in revisions:
        raise ValueError('有效版本不存在')
    n = revisions.index(revision)
    if baseline is None:
        baseline = revisions[n - 1] if n else None
    elif baseline == '__none__':
        baseline = None
    elif baseline not in revisions or revisions.index(baseline) >= n:
        raise ValueError('基线版本不存在或不是较早版本')
    members = []
    for view, group in index['views'].items():
        for path, history in group.items():
            matches = [row for row in history['effective'] if row['revision'] == revision]
            previous = [row for row in history['effective'] if row['revision'] == baseline]
            if matches:
                members.append({
                    'view': view,
                    'path': path,
                    'version': matches[0]['version'],
                    'absolute_path': matches[0]['path'],
                    'baseline': previous[0] if previous else None,
                })
    return {
        'vendor': vendor,
        'library': library,
        'revision': revision,
        'baseline': baseline,
        'members': members,
        'index': index,
    }


class PathDataQuery:
    def __init__(self, work):
        self.work = work

    def _index_locked(self, vendor, library, *, verify='manifest', cur_stat=None):
        """Read and verify file_index.json assuming the caller ALREADY holds locked(folder)."""
        folder = library_folder(self.work, vendor, library)
        path = folder / 'file_index.json'
        if path.is_symlink() or not path.is_file():
            raise ValueError('文件索引不存在')
        if verify == 'fast':
            matched, _ = index_manifest_matches(self.work, vendor, library, fast=True, _cur_stat=cur_stat)
            if matched:
                return json.loads(path.read_text(encoding='utf-8'))
        if verify in ('manifest', 'fast'):
            matched, _ = index_manifest_matches(self.work, vendor, library, fast=False, strict_hash=False, _cur_stat=cur_stat)
            if matched:
                return json.loads(path.read_text(encoding='utf-8'))
        elif verify == 'strict':
            matched, _ = index_manifest_matches(self.work, vendor, library, fast=False, strict_hash=True)
            if matched:
                return json.loads(path.read_text(encoding='utf-8'))
        saved = json.loads(path.read_text(encoding='utf-8'))
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

    def find_latest_check(self, vendor, library, *, revision, baseline=_UNSET, plugins=None):
        return find_latest_check(self.work, vendor, library, revision=revision, baseline=baseline, plugins=plugins)

    def latest_check_for_scope(self, vendor, library, revision, baseline, *, plugins=None):
        return latest_check_for_scope(self.work, vendor, library, revision, baseline, plugins=plugins)

    def latest_check_for_revision(self, vendor, library, target_revision, *, plugins=None):
        return latest_check_for_revision(self.work, vendor, library, target_revision, plugins=plugins)

    def unadopted_new_files(self, vendor, library, *, sample_limit=20):
        return unadopted_new_files(self.work, vendor, library, sample_limit=sample_limit)

    def get_check_context(self, vendor, library, revision, baseline=None):
        index = self.index(vendor, library)
        return build_check_context_from_index(vendor, library, index, revision, baseline=baseline)

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
