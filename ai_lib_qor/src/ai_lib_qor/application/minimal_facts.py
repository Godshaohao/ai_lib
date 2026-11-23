"""Build path-based FileFacts from the validated minimal file index (single-hash stability verification)."""
import csv
import json
from pathlib import Path
import time

from ai_lib_qor.facts import parsers
from ai_lib_qor.sources.layout import library_folder, log_file, next_filename, storage_dir
from ai_lib_qor.sources.timestamps import instant, utc_text
from ai_lib_qor.versions.store import locked, validate, write_atomic
from .minimal_file_index import _RACY_WINDOW_NS, _relative, query_path


def _stat_key(path):
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _lookup_in_index(index, view, relative_path, *, revision=None, version=None):
    row = index['views'].get(view, {}).get(_relative(relative_path))
    if row is None:
        raise ValueError('文件不在索引中')
    if revision is not None:
        if revision not in index['revisions']:
            raise ValueError('有效版本不存在')
        matches = [r for r in row['effective'] if r['revision'] == revision]
        if len(matches) > 1:
            raise ValueError('有效版本来源不唯一')
        return {'effective': matches[0] if matches else None}
    order = [item['version'] for item in index['deliveries']]
    if version not in order:
        raise ValueError('交付版本不存在')
    rank = {v: i for i, v in enumerate(order)}
    at = rank[version]
    candidates = [item for item in row['raw'] if rank[item['version']] <= at]
    return {'as_of': candidates[-1] if candidates else None}


def build_facts(
    work,
    vendor,
    library,
    view,
    relative_path,
    *,
    version=None,
    revision=None,
    _capture=False,
    _in_memory=False,
    _index=None,
    _raw_obs=None,
    _precomputed_stamp=None,
):
    if (version is None) == (revision is None):
        raise ValueError('必须且只能指定一个交付版本或有效版本')
    if view not in parsers.supported_views():
        raise ValueError('此 View 暂不支持 FileFacts 解析')
    folder = library_folder(work, vendor, library)
    index_path = folder / 'file_index.json'
    if _index is not None:
        data = _index
        row = _lookup_in_index(data, view, relative_path, revision=revision, version=version)
    else:
        row = query_path(work, vendor, library, view, relative_path, revision=revision, version=version)
        if index_path.is_symlink() or not index_path.is_file():
            raise ValueError('索引不存在或无效')
        data = json.loads(index_path.read_text(encoding='utf-8'))

    chosen = row['effective'] if revision else row['as_of']
    if not chosen or (version and chosen['version'] != version):
        raise ValueError('指定版本没有该文件')
    source_version = chosen['version']
    absolute = Path(chosen['path'])
    deliveries = [d for d in data['deliveries'] if d['version'] == source_version]
    if len(deliveries) != 1:
        raise ValueError('来源版本不唯一')
    root = Path(deliveries[0]['root']).resolve(strict=True)
    real = absolute.resolve(strict=True)
    if not real.is_relative_to(root) or not real.is_file() or real != absolute:
        raise ValueError('RAW 文件不存在、越界或包含符号链接')

    if _raw_obs is not None:
        rec = _raw_obs.get((source_version, relative_path))
        if rec is not None:
            stat = real.stat()
            if (stat.st_size, stat.st_mtime_ns) != rec:
                raise ValueError('RAW 文件相对首次观察已变化，不能当作历史文件解析')
    else:
        observation = log_file(folder, 'raw_observations.tsv')
        if observation.is_symlink():
            raise ValueError('RAW 观察记录不能为软链接')
        if observation.is_file():
            with observation.open(encoding='utf-8', newline='') as stream:
                for recorded in csv.reader(stream, delimiter='\t'):
                    if len(recorded) != 5:
                        raise ValueError('RAW 观察记录格式无效')
                    if recorded[:2] == [source_version, relative_path]:
                        stat = real.stat()
                        if (stat.st_size, stat.st_mtime_ns) != (int(recorded[2]), int(recorded[3])):
                            raise ValueError('RAW 文件相对首次观察已变化，不能当作历史文件解析')
                        break

    if _precomputed_stamp is not None:
        before, digest = _precomputed_stamp
        if _stat_key(real) != before:
            raise ValueError('读取 RAW 文件时发生变化')
    else:
        before = _stat_key(real)
        digest = parsers._file_digest(real)
        if _stat_key(real) != before:
            raise ValueError('读取 RAW 文件时发生变化')

    payload = parsers.parse_file_payload(real, view, allow_pg=True)
    if _stat_key(real) != before:
        raise ValueError('解析期间 RAW 文件发生变化')
    # Only re-hash after parsing if the file was created within the 50ms racy clock window;
    # mature files are already guarded by (dev, ino, size, mtime_ns, ctime_ns).
    if abs(time.time_ns() - before[4]) < _RACY_WINDOW_NS:
        if parsers._file_digest(real) != digest or _stat_key(real) != before:
            raise ValueError('解析期间 RAW 文件发生变化')

    at = utc_text()
    facts = {
        'schema_version': 'file_facts.path.v1',
        'source': {
            'vendor': vendor,
            'library': library,
            'version': source_version,
            'relative_path': relative_path,
            'absolute_path': str(absolute),
            'historical_content': 'UNVERIFIED',
        },
        'selection': {'kind': 'EFFECTIVE' if revision else 'DELIVERY', 'value': revision or version},
        'parsed_at': at,
        **payload,
    }
    validate(facts, 'file_facts_path')

    output = None
    if _in_memory and _index is not None:
        # Caller (check orchestrator) already verified the library archive at check start and will
        # re-verify under locked(folder) before publishing any pool blobs or CheckResult.
        # Keep per-file RAW identity stability check without repeating full-library archive enumeration.
        if _stat_key(real) != before:
            raise ValueError('保存前 RAW 文件发生变化')
    else:
        with locked(folder):
            from .path_query import PathDataQuery
            saved = PathDataQuery(work)._index_locked(vendor, library)
            latest = saved['views'].get(view, {}).get(relative_path, {})
            entries = latest.get('effective' if revision else 'raw', [])
            if sum(x.get('version') == source_version and x.get('path') == str(absolute) and (not revision or x.get('revision') == revision) for x in entries) != 1:
                raise ValueError('解析期间文件来源发生变化')
            if _stat_key(real) != before:
                raise ValueError('保存前 RAW 文件发生变化')
            stamp = instant(at).strftime('%Y%m%dT%H%M%SZ')
            if not _in_memory:
                outdir = storage_dir(folder, 'log')
                output = outdir / next_filename(outdir, f'facts_{view}_{stamp}')
                write_atomic(output, facts, immutable=True)
    result = {'state': 'CREATED', 'path': str(output) if output is not None else None, 'view': view, 'version': source_version}
    if _in_memory:
        result['_facts'] = facts
    if _capture:
        result['_source_stamp'] = (before, digest)
    return result
