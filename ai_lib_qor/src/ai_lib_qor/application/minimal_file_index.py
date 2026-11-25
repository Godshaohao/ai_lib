"""Rebuildable ordered path histories over the three minimal source contracts."""
import hashlib
import json
import os
import re
import time
from datetime import date
from pathlib import Path, PurePosixPath

from ai_lib_qor.sources.layout import library_folder,archive_files
from ai_lib_qor.sources.minimal_delivery import order_deliveries
from ai_lib_qor.sources.timestamps import instant,utc_text
from ai_lib_qor.versions.store import locked,write_atomic,validate
from .minimal_effective import _deliveries,_history


def _relative(value):
    if not isinstance(value,str) or not value or '\\' in value or PurePosixPath(value).is_absolute() or any(x in ('','.','..') for x in value.split('/')):
        raise ValueError('文件相对路径无效')
    return value


def _root(value):
    if not isinstance(value,str) or not os.path.isabs(value) or os.path.normpath(value)!=value:raise ValueError('来源根路径无效')
    return value


def _configured_times(work,vendor,library):
    from .path_config import registration_times
    return registration_times(work,vendor,library)


def _ordered(records,times):
    return order_deliveries(records,times)


def build_index(work,vendor,library):
    folder=library_folder(work,vendor,library);deliveries=_deliveries(folder,vendor,library)
    ordered=_ordered(list(deliveries.values()),_configured_times(work,vendor,library))
    if not ordered:raise ValueError('没有来源交付')
    index={'vendor':vendor,'library':library,'deliveries':[],'nl_snapshots':[],'revisions':[],'views':{}}
    def node(view,path):return index['views'].setdefault(view,{}).setdefault(path,{'raw':[],'nl':[],'effective':[]})
    known={}
    for d in ordered:
        root=_root(d['root']);index['deliveries'].append({'version':d['version'],'version_date':d['version_date'],'root':root})
        for view,paths in d['views'].items():
            if not isinstance(view,str) or not isinstance(paths,list):raise ValueError('交付 View 无效')
            for rel in paths:
                _relative(rel);key=(view,d['version'],rel)
                if key in known:raise ValueError('同一来源文件重复')
                absolute=os.path.join(root,rel);known[key]=absolute
                node(view,rel)['raw'].append({'version':d['version'],'path':absolute})
    snapshots=[]
    for p in archive_files(folder,'formal','formal_*.json'):
        if p.is_symlink():raise ValueError('正式快照不能为软链接')
        f=json.loads(p.read_text(encoding='utf-8'))
        validate(f,'formal_path')
        if set(f)!={'version','vendor','library','root','observed_at','views'} or (f['vendor'],f['library'])!=(vendor,library):raise ValueError('正式快照范围或格式不正确')
        snapshots.append((instant(f['observed_at']),p.name,f))
    snapshots.sort(key=lambda x:(x[0],x[1]))
    if len({name for _,name,_ in snapshots}) != len(snapshots):
        raise ValueError('正式快照文件名重复，无法唯一确定快照')
    for _,snapshot_id,f in snapshots:
        root=_root(f['root']);index['nl_snapshots'].append({'snapshot_id':snapshot_id,'nl_version':f['version'],'observed_at':f['observed_at'],'root':root})
        for view,versions in f['views'].items():
            for version,links in versions.items():
                d=deliveries.get(version)
                if d is None:raise ValueError('正式来源版本不存在')
                raw_root=_root(d['root'])
                for link in links:
                    link_rel=_relative(link['path']);resolved=_root(link['resolved'])
                    raw_path = _root(link.get('raw_path', resolved))
                    if not Path(raw_path).is_relative_to(raw_root):raise ValueError('正式来源不在记录的版本目录')
                    rel=_relative(Path(raw_path).relative_to(raw_root).as_posix())
                    if known.get((view,version,rel))!=raw_path:raise ValueError('正式来源不在交付清单中')
                    if not isinstance(link['target'],str):raise ValueError('正式链接目标无效')
                    link_path=os.path.join(root,link_rel)
                    textual=os.path.normpath(link['target'] if os.path.isabs(link['target']) else os.path.join(os.path.dirname(link_path),link['target']))
                    row = {'snapshot_id':snapshot_id,'version':f['version'],'observed_at':f['observed_at'],
                           'link_path':link_path,'link_target':link['target'],'resolved_path':resolved,
                           'source_match':'MATCHED_RAW' if textual==resolved or 'raw_path' in link else 'UNVERIFIED'}
                    if 'raw_path' in link:
                        row['raw_path'] = raw_path
                    node(view,rel)['nl'].append(row)
    for _,_,effective in _history(folder,library):
        if (effective.get('vendor'),effective.get('library'))!=(vendor,library):raise ValueError('有效版本范围不一致')
        revision=effective['revision'];index['revisions'].append(revision);seen=set()
        for view,versions in effective['views'].items():
            for version,paths in versions.items():
                for rel in paths:
                    _relative(rel);key=(view,rel)
                    if key in seen:raise ValueError('有效文件成员重复')
                    seen.add(key);source=known.get((view,version,rel))
                    if source is None:raise ValueError('有效版本来源不在交付清单中')
                    node(view,rel)['effective'].append({'revision':revision,'version':version,'path':source})
    index['views']={v:dict(sorted(files.items())) for v,files in sorted(index['views'].items())}
    validate(index,'file_index_path')
    return index


def without_formal_snapshot_ids(index):
    """Project the rebuilt index into the old storage shape for read-only verification."""
    def without_id(row):
        return {key: value for key, value in row.items() if key != 'snapshot_id'}
    return {
        **index,
        'nl_snapshots': [without_id(row) for row in index['nl_snapshots']],
        'views': {
            view: {path: {**row, 'nl': [without_id(link) for link in row['nl']]}
                   for path, row in group.items()}
            for view, group in index['views'].items()
        },
    }


def _sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _archive_candidates(folder,library):
    effective_re=re.compile(r'^effective_'+re.escape(library)+r'_(\d+)\.json$')
    if not folder.is_dir():return []
    candidates=[*archive_files(folder,'delivery','delivery_*.json'),
                *archive_files(folder,'formal','formal_*.json'),
                *[p for p in archive_files(folder,'effective','effective_'+library+'_*.json') if effective_re.fullmatch(p.name)]]
    return sorted(set(candidates),key=lambda p:p.relative_to(folder).as_posix())


_RACY_WINDOW_NS = 50_000_000  # 50ms racy-git guard for coarse-grained filesystem clocks


def _archive_stat_summary(work, vendor, library, index_path):
    """Single unified stat summary (size, mtime_ns, ctime_ns, ino) serving both fast overview and tamper-aware reads."""
    folder = library_folder(work, vendor, library)
    entries = []
    for entry in _archive_candidates(folder, library):
        rel = entry.relative_to(folder).as_posix()
        if entry.is_symlink() or not entry.is_file():
            raise ValueError('归档记录不能为软链接: ' + rel)
        st = entry.stat()
        entries.append([rel, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino])
    idx_st = index_path.stat()
    times = _configured_times(work, vendor, library)
    times_hash = hashlib.sha256(json.dumps(times, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
    return {
        'entries': entries,
        'index': [idx_st.st_size, idx_st.st_mtime_ns, idx_st.st_ctime_ns, idx_st.st_ino],
        'registration_times_sha256': times_hash,
    }


# Backward-compatible alias (single unified stat enumeration; no duplicate scan).
_strict_stat_summary = _archive_stat_summary


def _manifest_stat_entries(manifest: dict):
    """Extract unified 5-tuple stat block from manifest (compatible with legacy strict_stat or 3-tuple fast_stat)."""
    if not isinstance(manifest, dict):
        return None
    if isinstance(manifest.get('strict_stat'), dict):
        return manifest['strict_stat']
    if isinstance(manifest.get('fast_stat'), dict):
        return manifest['fast_stat']
    return None


def _fast_stat_matches(saved_stat: dict, cur_stat: dict) -> bool:
    """Compare (rel, size, mtime_ns) + index (size, mtime_ns) + registration_times_sha256 (works for both 3-tuple and 5-tuple manifests)."""
    if saved_stat.get('registration_times_sha256') != cur_stat.get('registration_times_sha256'):
        return False
    s_idx = saved_stat.get('index') or []
    c_idx = cur_stat.get('index') or []
    if len(s_idx) < 2 or len(c_idx) < 2 or s_idx[:2] != c_idx[:2]:
        return False
    s_entries = saved_stat.get('entries') or []
    c_entries = cur_stat.get('entries') or []
    if len(s_entries) != len(c_entries):
        return False
    return all(len(a) >= 3 and len(b) >= 3 and a[:3] == b[:3] for a, b in zip(s_entries, c_entries))


def archive_fingerprint(work, vendor, library, *, prev_manifest=None):
    """Compute per-file SHA-256 fingerprint; when prev_manifest is provided, reuse hashes for mature unchanged immutable files (O(delta))."""
    folder = library_folder(work, vendor, library)
    cached_hashes = {}
    cached_stats = {}
    prev_written = 0
    if isinstance(prev_manifest, dict):
        prev_written = int(prev_manifest.get('written_at_ns') or 0)
        prev_archive = prev_manifest.get('archive') or {}
        prev_stat = _manifest_stat_entries(prev_manifest) or {}
        if isinstance(prev_archive.get('files'), dict) and isinstance(prev_stat.get('entries'), list):
            cached_hashes = prev_archive['files']
            for row in prev_stat['entries']:
                if isinstance(row, list) and len(row) == 5:
                    cached_stats[row[0]] = tuple(row[1:])
    files = {}
    for entry in _archive_candidates(folder, library):
        rel = entry.relative_to(folder).as_posix()
        if entry.is_symlink() or not entry.is_file():
            raise ValueError('归档记录不能为软链接: ' + rel)
        if cached_stats and rel in cached_stats and rel in cached_hashes:
            st = entry.stat()
            sig = (st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino)
            if sig == cached_stats[rel] and prev_written and abs(prev_written - st.st_ctime_ns) >= _RACY_WINDOW_NS:
                files[rel] = cached_hashes[rel]
                continue
        files[rel] = _sha256_file(entry)
    times = _configured_times(work, vendor, library)
    times_hash = hashlib.sha256(json.dumps(times, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
    return {'files': files, 'registration_times_sha256': times_hash}


def _manifest_path(folder):
    return folder / '.file_index_manifest.json'


def _ignored_unadopted_digest(work, vendor, library):
    from .path_config import ignored_unadopted_files
    try:
        items = sorted(f'{v}:{p}' for v, p in ignored_unadopted_files(work, vendor, library))
    except (OSError, ValueError, TypeError):
        items = []
    return items, hashlib.sha256(json.dumps(items, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def _unadopted_count_from_index(index_obj, ignored_set):
    if not index_obj or not index_obj.get('revisions') or not index_obj.get('deliveries'):
        return 0
    latest_rev = index_obj['revisions'][-1]
    latest_deliv = index_obj['deliveries'][-1]['version']
    cnt = 0
    for view, group in (index_obj.get('views') or {}).items():
        for rel, row in group.items():
            in_deliv = any(r.get('version') == latest_deliv for r in row.get('raw') or [])
            if not in_deliv:
                continue
            in_eff = any(e.get('revision') == latest_rev for e in row.get('effective') or [])
            if not in_eff and (view, rel) not in ignored_set:
                cnt += 1
    return cnt


def _write_manifest(work, vendor, library, index_path, *, index_obj=None, prev_manifest=None):
    folder = library_folder(work, vendor, library)
    mpath = _manifest_path(folder)
    if mpath.is_symlink():
        raise ValueError('索引清单不能为软链接')
    ignored_tokens, ignored_sha = _ignored_unadopted_digest(work, vendor, library)
    ignored_set = {tuple(tok.split(':', 1)) for tok in ignored_tokens}
    if index_obj is None:
        index_obj = json.loads(index_path.read_text(encoding='utf-8'))
    unified_stat = _archive_stat_summary(work, vendor, library, index_path)
    manifest = {
        'schema': 'file_index_manifest.v1',
        'vendor': vendor,
        'library': library,
        'refreshed_at': utc_text(),
        'written_at_ns': time.time_ns(),
        'archive': archive_fingerprint(work, vendor, library, prev_manifest=prev_manifest),
        'fast_stat': unified_stat,
        'file_index_sha256': _sha256_file(index_path),
        'formal_snapshot_ids': True,
        'unadopted_new_files_count': _unadopted_count_from_index(index_obj, ignored_set),
        'ignored_unadopted_sha256': ignored_sha,
    }
    write_atomic(mpath, manifest)
    return manifest


def read_manifest(work, vendor, library):
    folder = library_folder(work, vendor, library)
    mpath = _manifest_path(folder)
    if mpath.is_symlink() or not mpath.is_file():
        return None
    try:
        data = json.loads(mpath.read_text(encoding='utf-8'))
        if isinstance(data, dict) and data.get('schema') == 'file_index_manifest.v1' and (data.get('vendor'), data.get('library')) == (vendor, library):
            return data
    except (OSError, ValueError, TypeError):
        return None
    return None


def index_manifest_matches(work, vendor, library, *, fast=False, strict_hash=False, _cur_stat=None):
    folder = library_folder(work, vendor, library)
    path = folder / 'file_index.json'
    if path.is_symlink() or not path.is_file():
        return False, None
    manifest = read_manifest(work, vendor, library)
    if not manifest or not manifest.get('formal_snapshot_ids'):
        return False, manifest
    try:
        saved_stat = _manifest_stat_entries(manifest)
        if fast and saved_stat is not None:
            cur_stat = _cur_stat if _cur_stat is not None else _archive_stat_summary(work, vendor, library, path)
            return _fast_stat_matches(saved_stat, cur_stat), manifest
        if not strict_hash and saved_stat is not None:
            is_five_tuple = len(saved_stat.get('index') or []) == 4 and all(len(e) == 5 for e in (saved_stat.get('entries') or []))
            if is_five_tuple:
                cur_stat = _cur_stat if _cur_stat is not None else _archive_stat_summary(work, vendor, library, path)
                if saved_stat == cur_stat:
                    written_ns = int(manifest.get('written_at_ns') or 0)
                    idx_ctime = cur_stat['index'][2]
                    if not written_ns or abs(written_ns - idx_ctime) < _RACY_WINDOW_NS:
                        if manifest.get('file_index_sha256') != _sha256_file(path):
                            return False, manifest
                    archive_files_map = (manifest.get('archive') or {}).get('files') or {}
                    for rel, _, _, ctime_ns, _ in cur_stat['entries']:
                        if not written_ns or abs(written_ns - ctime_ns) < _RACY_WINDOW_NS:
                            if archive_files_map.get(rel) != _sha256_file(folder / rel):
                                return False, manifest
                    return True, manifest
        if manifest.get('file_index_sha256') != _sha256_file(path):
            return False, manifest
        if manifest.get('archive') != archive_fingerprint(work, vendor, library):
            return False, manifest
    except (OSError, ValueError, TypeError):
        return False, manifest
    return True, manifest


def refresh_index_locked(work, vendor, library, *, force_verify=False):
    folder = library_folder(work, vendor, library)
    path = folder / 'file_index.json'
    if path.is_symlink():
        raise ValueError('索引不能为软链接')
    prev_manifest = None if force_verify else read_manifest(work, vendor, library)
    if not force_verify:
        matched, manifest = index_manifest_matches(work, vendor, library)
        if matched:
            return {'state': 'UNCHANGED', 'path': str(path), 'refreshed_at': manifest.get('refreshed_at'), 'skipped_rebuild': True}
    new = build_index(work, vendor, library)
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(old, dict) or set(old) != {'vendor', 'library', 'deliveries', 'nl_snapshots', 'revisions', 'views'} or (old['vendor'], old['library']) != (vendor, library):
            raise ValueError('已有索引属于其他格式，拒绝覆盖')
        if old == new:
            manifest = _write_manifest(work, vendor, library, path, index_obj=new, prev_manifest=prev_manifest)
            return {'state': 'UNCHANGED', 'path': str(path), 'refreshed_at': manifest['refreshed_at'], 'skipped_rebuild': False}
        def contains(before, after, *, formal=False):
            candidates = iter(after)
            for expected in before:
                for actual in candidates:
                    if formal and 'snapshot_id' not in expected:
                        actual = {key: value for key, value in actual.items() if key != 'snapshot_id'}
                    if expected == actual:
                        break
                else:
                    return False
            return True
        try:
            preserved = all(contains(old[key], new[key], formal=key == 'nl_snapshots')
                            for key in ('deliveries', 'nl_snapshots', 'revisions'))
            for view, files in old['views'].items():
                for relative, row in files.items():
                    target = new['views'].get(view, {}).get(relative)
                    if not target or not all(contains(row[k], target[k], formal=k == 'nl')
                                             for k in ('raw', 'nl', 'effective')):
                        preserved = False
        except (KeyError, TypeError, AttributeError):
            preserved = False
        if not preserved:
            raise ValueError('已发布索引的历史记录或顺序发生变更，拒绝覆盖')
    write_atomic(path, new)
    manifest = _write_manifest(work, vendor, library, path, index_obj=new, prev_manifest=prev_manifest)
    return {'state': 'UPDATED', 'path': str(path), 'refreshed_at': manifest['refreshed_at'], 'skipped_rebuild': False}


def refresh_index(work,vendor,library,*,force_verify=False):
    folder=library_folder(work,vendor,library)
    if not folder.is_dir():raise ValueError('库目录不存在')
    with locked(folder):return refresh_index_locked(work,vendor,library,force_verify=force_verify)


def query_path(work,vendor,library,view,path,*,revision=None,version=None):
    from .path_query import PathDataQuery
    return PathDataQuery(work).file(vendor,library,view,path,revision=revision,version=version)
