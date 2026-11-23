"""Content-addressed FileFacts pool storage & read-only check bundle hydration."""
import csv
import gzip
import json
import os
from pathlib import Path
import uuid
import zlib

from ai_lib_qor.sources.layout import library_folder, log_file
from ai_lib_qor.versions.store import validate


def write_pool_atomic(path, payload):
    """Write an immutable content-addressed gzipped JSON fact object atomically."""
    if path.is_symlink():
        raise ValueError('事实共享池文件不能为软链接')
    if path.is_file():
        return
    blob = gzip.compress(
        json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8'),
        compresslevel=6,
    )
    tmp = path.parent / f'.{path.name}.{uuid.uuid4().hex}.tmp'
    try:
        with tmp.open('wb') as stream:
            stream.write(blob)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read_pool(folder, pool_rel):
    if not isinstance(pool_rel, str) or not pool_rel or pool_rel.startswith('/') or '..' in Path(pool_rel).parts:
        raise ValueError('事实共享池路径无效')
    facts_dir = folder / 'facts'
    if facts_dir.is_symlink():
        raise ValueError('事实共享池目录不能为软链接')
    target = folder / pool_rel
    if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(folder.resolve()):
        raise ValueError('事实共享池文件不存在或越界')
    try:
        return json.loads(gzip.decompress(target.read_bytes()))
    except (EOFError, gzip.BadGzipFile, zlib.error) as exc:
        raise ValueError(f'Facts 共享池文件损坏: {pool_rel}') from exc


def hydrate_fact(folder, fact_obj, pool_cache):
    """Hydrate a lightweight content-addressed pool pointer into a full file_facts.path.v1 dict."""
    if not isinstance(fact_obj, dict):
        return None
    if fact_obj.get('storage') != 'CONTENT_ADDRESSED_POOL':
        return fact_obj
    pool_rel = fact_obj.get('pool_file')
    if pool_rel not in pool_cache:
        pool_cache[pool_rel] = read_pool(folder, pool_rel)
    pool_data = pool_cache[pool_rel]
    return {
        'schema_version': fact_obj.get('schema_version', 'file_facts.path.v1'),
        'source': fact_obj['source'],
        'selection': fact_obj['selection'],
        'parsed_at': fact_obj['parsed_at'],
        'view': pool_data['view'],
        'parser': pool_data['parser'],
        'parse_status': pool_data['parse_status'],
        'covered_sections': pool_data['covered_sections'],
        'units': pool_data['units'],
        'objects': pool_data['objects'],
    }


def load_raw_observations(folder):
    observation = log_file(folder, 'raw_observations.tsv')
    if observation.is_symlink():
        raise ValueError('RAW 观察记录不能为软链接')
    records = {}
    if observation.is_file():
        with observation.open(encoding='utf-8', newline='') as stream:
            for row in csv.reader(stream, delimiter='\t'):
                if len(row) != 5:
                    raise ValueError('RAW 观察记录格式无效')
                records.setdefault((row[0], row[1]), (int(row[2]), int(row[3])))
    return records


def resolve_check_file(folder, check_filename):
    if not isinstance(check_filename, str) or '/' in check_filename or '\\' in check_filename or check_filename in ('', '.', '..'):
        raise ValueError('检查文件名不安全')
    log_path = folder / 'log' / check_filename
    root_path = folder / check_filename
    if (folder / 'log').is_symlink():
        raise ValueError('日志目录不能为软链接')
    target = log_path if log_path.is_file() else root_path
    if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(folder.resolve()):
        raise ValueError('检查结果文件不存在')
    return target


def slice_index_for_report(index: dict, report: dict) -> dict:
    """Select the source records available to the saved run."""
    rc = report.get('report_context')
    pinned_formal = None
    if isinstance(rc, dict) and isinstance(rc.get('deliveries'), list) and isinstance(rc.get('revisions'), list):
        allowed_deliveries = set(rc['deliveries'])
        allowed_revisions = set(rc['revisions'])
        nl_cutoff = rc.get('nl_observed_cutoff')
        if isinstance(rc.get('formal_snapshots'), list):
            pinned_formal = list(rc['formal_snapshots'])
        filter_deliveries = True
    else:
        # Backward-compatible fallback for historical CheckResult JSONs predating `report_context`:
        # bound revisions up to report['revision'] and Formal NL snapshots up to report['run_at'].
        all_revs = index.get('revisions') or []
        target_rev = report.get('revision')
        if target_rev in all_revs:
            allowed_revisions = set(all_revs[: all_revs.index(target_rev) + 1])
        else:
            allowed_revisions = set(all_revs)
        allowed_deliveries = {d['version'] for d in (index.get('deliveries') or [])}
        nl_cutoff = report.get('run_at') or None
        filter_deliveries = False

    def _nl_allowed(obs_at):
        if nl_cutoff is None:
            return False
        return bool(obs_at) and str(obs_at) <= str(nl_cutoff)

    sliced_deliveries = [d for d in (index.get('deliveries') or []) if not filter_deliveries or d['version'] in allowed_deliveries]
    sliced_revisions = [r for r in (index.get('revisions') or []) if r in allowed_revisions]

    if pinned_formal is not None:
        wanted = set(pinned_formal)
        sliced_nl = [n for n in index['nl_snapshots'] if n['snapshot_id'] in wanted]
        if {n['snapshot_id'] for n in sliced_nl} != wanted:
            raise ValueError('检查引用的正式快照归档不完整')
    else:
        sliced_nl = [n for n in index['nl_snapshots'] if _nl_allowed(n['observed_at'])]
    selected_ids = {n['snapshot_id'] for n in sliced_nl}

    sliced_views = {}
    for view, group in (index.get('views') or {}).items():
        new_group = {}
        for rel, row in group.items():
            raw = [e for e in (row.get('raw') or []) if not filter_deliveries or e.get('version') in allowed_deliveries]
            nl = [e for e in row['nl'] if e['snapshot_id'] in selected_ids]
            eff = [e for e in (row.get('effective') or []) if e.get('revision') in allowed_revisions]
            if raw or nl or eff:
                new_group[rel] = {'raw': raw, 'nl': nl, 'effective': eff}
        if new_group:
            sliced_views[view] = new_group

    return {
        'vendor': index.get('vendor'),
        'library': index.get('library'),
        'deliveries': sliced_deliveries,
        'nl_snapshots': sliced_nl,
        'revisions': sliced_revisions,
        'views': sliced_views,
    }


def load_check_bundle(work, vendor, library, check_filename):
    """Read-only loader: reconstruct complete report + facts + point-in-time index bundle solely from saved JSON."""
    from .path_query import PathDataQuery
    folder = library_folder(work, vendor, library)
    live_index = PathDataQuery(work).index(vendor, library)
    check_path = resolve_check_file(folder, check_filename)
    report = json.loads(check_path.read_text(encoding='utf-8'))
    validate(report, 'check_result_path')
    if (report['vendor'], report['library']) != (vendor, library):
        raise ValueError('检查结果与当前库归属不一致')
    index = slice_index_for_report(live_index, report)

    facts_map = {}
    pool_cache = {}
    for ref_id, fact_obj in (report.get('facts_evidence') or {}).items():
        if isinstance(fact_obj, dict):
            try:
                hydrated = hydrate_fact(folder, fact_obj, pool_cache)
            except (OSError, ValueError, TypeError, KeyError):
                hydrated = None
            if hydrated is not None:
                facts_map[ref_id] = hydrated
                facts_map[Path(ref_id).name] = hydrated

    candidate_refs = [f.get('facts') for f in report.get('files', []) if f.get('facts')]
    for c in report.get('checks', []):
        candidate_refs.extend(c.get('facts_refs') or [])
    for key in ('comparisons', 'partial_comparisons', 'changes'):
        for comp in report.get(key, []):
            candidate_refs.extend(comp.get('facts_refs') or [])
    for ref in candidate_refs:
        if not ref or ref in facts_map:
            continue
        name = Path(ref).name
        if name in facts_map:
            facts_map[ref] = facts_map[name]
            continue
        for base in (folder / 'log', folder):
            fp = base / name
            if fp.is_file() and not fp.is_symlink() and fp.resolve().is_relative_to(folder.resolve()):
                try:
                    data = json.loads(fp.read_text(encoding='utf-8'))
                    facts_map[ref] = data
                    facts_map[name] = data
                except (OSError, ValueError, TypeError):
                    pass
                break

    return {
        'folder': folder,
        'check_path': check_path,
        'report': report,
        'index': index,
        'facts': facts_map,
        'unavailable_facts': sorted({ref for ref in [*candidate_refs, *(report.get('facts_evidence') or {})]
                                     if ref and ref not in facts_map and Path(ref).name not in facts_map}),
    }
