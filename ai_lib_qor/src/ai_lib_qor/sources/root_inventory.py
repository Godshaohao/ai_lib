"""Pure L1 inventory for RAW and Formal roots (with backward-compatible build_from_roots facade)."""
from collections import defaultdict
import csv
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from ai_lib_qor.versions.runtime import check_cancel, emit_progress
from ai_lib_qor.versions.store import locked, write_atomic
from .config_reader import read_registration_times
from .layout import SAFE, archive_files, library_folder, log_file, next_filename, storage_dir
from .minimal_delivery import directory_birthtime, order_deliveries, version_date
from .source_discovery import _DEFAULT_VERSION, natural_version_key
from .timestamps import instant, utc_text

_VIEW_TOKEN_RE = re.compile(r'^[A-Z][A-Z0-9_]{1,31}\Z')
VIEW_EXTENSIONS_VERSION = '1.0'

VIEW_EXTENSIONS = {
    '.lef': 'LEF',
    '.lib': 'LIBERTY',
    '.gds': 'GDS',
    '.sp': 'SPICE',
    '.spice': 'SPICE',
    '.cdl': 'CDL',
    '.v': 'VERILOG',
    '.sv': 'VERILOG',
    '.sdc': 'SDC',
    '.db': 'DB',
    '.spef': 'SPEF',
    '.upf': 'UPF',
    '.cpf': 'CPF',
    '.pdf': 'DOC',
    '.txt': 'DOC',
    '.md': 'DOC',
    '.xlsx': 'DOC',
    '.xls': 'DOC',
}


def register_view_extension(ext: str, view: str, *, registry=VIEW_EXTENSIONS):
    """Register or override a lowercase file extension -> uppercase View mapping."""
    if not isinstance(ext, str) or not ext.startswith('.') or len(ext) < 2 or '/' in ext or '\\' in ext:
        raise ValueError(f'文件扩展名无效: {ext}')
    norm_view = str(view or '').strip().upper()
    if not _VIEW_TOKEN_RE.fullmatch(norm_view):
        raise ValueError(f'View 名称无效: {view}')
    registry[ext.lower()] = norm_view


def _view(path, *, extra_extensions=None):
    name = path.lower().removesuffix('.gz')
    ext = Path(name).suffix
    if extra_extensions and ext in extra_extensions:
        return extra_extensions[ext]
    return VIEW_EXTENSIONS.get(ext, 'OTHER')


def infer_nl_version(root):
    match = re.search(r'(?i)NL[\d._-]+', Path(root).name)
    if not match:
        raise ValueError('无法从 NL 目录名识别版本，请使用 --nl-version')
    return re.sub(r'[_-]', '.', match.group()).upper()


def _version_directory(name):
    if re.match(r'^\d{8}(?:$|[_-])', name):
        return version_date(name) is not None
    return bool(_DEFAULT_VERSION.fullmatch(name))


def _matches_ignore(name: str, rel: str, patterns) -> bool:
    if not patterns:
        return False
    for pat in patterns:
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel, pat):
            return True
    return False


def _load_work_inventory_options(out: Path):
    """Read ignore_patterns & view_extensions from path_sources.json without upward application imports."""
    ignore_patterns = None
    extra_extensions = {}
    cfg_path = out / 'path_sources.json'
    if cfg_path.is_file() and not cfg_path.is_symlink():
        try:
            cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
            if isinstance(cfg, dict):
                if isinstance(cfg.get('ignore_patterns'), list):
                    ignore_patterns = [str(x) for x in cfg['ignore_patterns'] if isinstance(x, str) and x.strip()]
                if isinstance(cfg.get('view_extensions'), dict):
                    for k, v in cfg['view_extensions'].items():
                        if isinstance(k, str) and k.startswith('.') and isinstance(v, str) and _VIEW_TOKEN_RE.fullmatch(v.strip().upper()):
                            extra_extensions[k.lower()] = v.strip().upper()
        except (OSError, ValueError, TypeError):
            pass
    return ignore_patterns, extra_extensions


def effective_view_extensions(extra_extensions=None):
    merged = dict(VIEW_EXTENSIONS)
    if extra_extensions:
        for k, v in extra_extensions.items():
            merged[k.lower()] = str(v).strip().upper()
    return dict(sorted(merged.items()))


def _check_view_extension_drift(out: Path, extra_extensions, warnings: list):
    """Detect changes in extension -> View mapping across L1 runs and warn clearly (archived deliveries stay immutable)."""
    state_path = out / '.view_extensions_state.json'
    if state_path.is_symlink():
        raise ValueError('View 映射状态文件不能为软链接')
    current_map = effective_view_extensions(extra_extensions)
    current_digest = hashlib.sha256(
        json.dumps(current_map, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()
    has_deliveries = any((out / 'libraries').glob('*/*/delivery/delivery_*.json')) or any((out / 'libraries').glob('*/*/delivery_*.json'))
    with locked(out):
        prev = None
        if state_path.is_file():
            try:
                loaded = json.loads(state_path.read_text(encoding='utf-8'))
                if isinstance(loaded, dict) and isinstance(loaded.get('mapping'), dict):
                    prev = loaded
            except (OSError, ValueError, TypeError):
                prev = None
        if prev is not None and prev.get('digest') != current_digest:
            old_map = prev['mapping']
            diffs = []
            for ext in sorted(set(old_map) | set(current_map)):
                ov = old_map.get(ext, 'OTHER')
                nv = current_map.get(ext, 'OTHER')
                if ov != nv:
                    diffs.append(f'{ext} ({ov} → {nv})')
            if diffs and has_deliveries:
                warnings.append(
                    'View 映射变更警告：' + '、'.join(diffs)
                    + '；已归档交付不可变，同路径在新旧交付中可能分列不同 View 且 L2 不会自动替换，请人工核对'
                )
        if prev is None or prev.get('digest') != current_digest:
            write_atomic(state_path, {
                'schema': 'view_extensions_state.v1',
                'version': VIEW_EXTENSIONS_VERSION,
                'digest': current_digest,
                'updated_at': utc_text(),
                'mapping': current_map,
            })


def _load_archived_deliveries(out: Path, vendor=None, library=None):
    """Load already-archived immutable deliveries (plus observed version set) to enable fast incremental L1 skips."""
    archived = {}
    libs_root = out / 'libraries'
    if not libs_root.is_dir() or libs_root.is_symlink():
        return archived
    folders = (libs_root / vendor / library,) if vendor else libs_root.glob('*/*')
    for folder in folders:
        if folder.is_symlink() or not folder.is_dir() or folder.parent.is_symlink():
            continue
        obs_path = log_file(folder, 'raw_observations.tsv')
        observed_versions = set()
        if obs_path.is_file() and not obs_path.is_symlink():
            try:
                with obs_path.open(encoding='utf-8', newline='') as stream:
                    for row in csv.reader(stream, delimiter='\t'):
                        if len(row) == 5:
                            observed_versions.add(row[0])
            except OSError:
                continue
        for p in archive_files(folder, 'delivery', 'delivery_*.json'):
            if p.is_symlink():
                continue
            try:
                val = json.loads(p.read_text(encoding='utf-8'))
                if set(val) == {'vendor', 'library', 'version', 'version_date', 'directory_created_at', 'root', 'views'}:
                    key = (val['vendor'], val['library'], val['version'])
                    if val['version'] in observed_versions:
                        archived[key] = val
            except (OSError, ValueError, TypeError):
                continue
    return archived


def _inventory_raw(
    raw,
    warnings,
    observations=None,
    *,
    scope_vendor=None,
    scope_library=None,
    archived=None,
    ignore_patterns=None,
    extra_extensions=None,
    stats=None,
    progress_cb=None,
    cancel_event=None,
):
    records = []
    lookup = {}
    walked = 0
    skipped = 0
    if scope_vendor and scope_library:
        v_dir = raw / scope_vendor
        l_dir = v_dir / scope_library
        targets = (
            [(v_dir, l_dir)]
            if (not v_dir.is_symlink() and v_dir.is_dir() and not l_dir.is_symlink() and l_dir.is_dir())
            else []
        )
    else:
        targets = []
        for vendor in sorted(raw.iterdir()):
            if vendor.is_symlink() or not vendor.is_dir() or not SAFE.fullmatch(vendor.name):
                continue
            for library in sorted(vendor.iterdir()):
                if library.is_symlink() or not library.is_dir() or not SAFE.fullmatch(library.name):
                    continue
                targets.append((vendor, library))
    total_libs = len(targets)
    for idx, (vendor, library) in enumerate(targets, 1):
        check_cancel(cancel_event, 'L1 RAW 盘点已由用户终止')
        emit_progress(progress_cb, 'L1', f'L1 盘点 RAW {vendor.name}/{library.name} ({idx}/{total_libs})', completed=idx - 1, total=total_libs)
        children = [x for x in library.iterdir() if not x.is_symlink() and x.is_dir()]
        versions = [x for x in children if SAFE.fullmatch(x.name) and _version_directory(x.name)]
        if versions:
            for item in children:
                if item not in versions and not _matches_ignore(item.name, item.name, ignore_patterns):
                    warnings.append(f'未识别为版本目录，已跳过: {item}')
        walked_before, skipped_before = walked, skipped
        incomplete = 0
        for version in sorted(versions, key=lambda p: natural_version_key(p.name)):
            check_cancel(cancel_event, 'L1 RAW 盘点已由用户终止')
            key = (vendor.name, library.name, version.name)
            cached = archived.get(key) if archived else None
            if cached and cached.get('root') == str(version):
                records.append(cached)
                for kind, paths in cached['views'].items():
                    for rel in paths:
                        lookup.setdefault(str(version / rel), []).append((vendor.name, library.name, version.name, kind))
                skipped += 1
                continue
            walked += 1
            files = []
            errors = []
            metadata = {}
            for current, dirs, names in os.walk(version, followlinks=False, onerror=lambda e: errors.append(str(e))):
                check_cancel(cancel_event, 'L1 RAW 盘点已由用户终止')
                dirs.sort()
                names.sort()
                for name in list(dirs):
                    dpath = Path(current) / name
                    drel = dpath.relative_to(version).as_posix()
                    if _matches_ignore(name, drel, ignore_patterns):
                        dirs.remove(name)
                        continue
                    if dpath.is_symlink():
                        errors.append('目录链接未扫描: ' + str(dpath))
                        dirs.remove(name)
                for name in names:
                    p = Path(current) / name
                    rel = p.relative_to(version).as_posix()
                    if _matches_ignore(name, rel, ignore_patterns):
                        continue
                    if p.is_symlink() or not p.is_file():
                        errors.append('非普通文件未扫描: ' + str(p))
                        continue
                    try:
                        info = p.stat()
                    except OSError as exc:
                        errors.append(str(exc))
                        continue
                    files.append(rel)
                    metadata[rel] = (info.st_size, info.st_mtime_ns)
            if errors:
                incomplete += 1
                warnings.extend(errors)
                warnings.append(f'{version}: 盘点不完整，不发布')
                continue
            if not files:
                continue
            views = defaultdict(list)
            for path in files:
                views[_view(path, extra_extensions=extra_extensions)].append(path)
            row = {
                'vendor': vendor.name,
                'library': library.name,
                'version': version.name,
                'version_date': version_date(version.name),
                'directory_created_at': directory_birthtime(version),
                'root': str(version),
                'views': dict(sorted(views.items())),
            }
            records.append(row)
            if observations is not None:
                observations[key] = metadata
            for path in files:
                lookup.setdefault(str(version / path), []).append((vendor.name, library.name, version.name, _view(path, extra_extensions=extra_extensions)))
        if stats is not None and versions:
            stats.setdefault('source_verifications', []).append({
                'vendor': vendor.name,
                'library': library.name,
                'source': 'RAW',
                'at': utc_text(),
                'versions_walked': walked - walked_before,
                'versions_reused': skipped - skipped_before,
                'versions_incomplete': incomplete,
            })
    if stats is not None:
        stats['raw_versions_walked'] = walked
        stats['raw_versions_skipped'] = skipped
    return records, lookup


def _inventory_formal(root, lookup, nl_version, warnings, unresolved, *, raw_root=None, scope_vendor=None, scope_library=None):
    groups = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    scoped = bool(scope_vendor and scope_library and raw_root is not None)
    scope_dir = (Path(raw_root) / scope_vendor / scope_library).resolve() if scoped else None

    def onerror(exc):
        warnings.append('NL 目录不可读取: ' + str(exc))
        unresolved.append({'path': str(getattr(exc, 'filename', '') or ''), 'target': None, 'resolved': None, 'reason': 'DIRECTORY_ERROR'})

    for current, dirs, names in os.walk(root, followlinks=False, onerror=onerror):
        dirs.sort()
        names.sort()
        for name in list(dirs):
            p = Path(current) / name
            if p.is_symlink():
                rel = p.relative_to(root).as_posix()
                warnings.append('NL 目录链接未展开: ' + rel)
                unresolved.append({'path': rel, 'target': os.readlink(p), 'resolved': None, 'reason': 'DIRECTORY_SYMLINK'})
                dirs.remove(name)
        for name in names:
            path = Path(current) / name
            rel = path.relative_to(root).as_posix()
            if not path.is_symlink():
                warnings.append('NL 普通文件未归属: ' + rel)
                continue
            try:
                target = os.readlink(path)
            except OSError as exc:
                warnings.append(f'NL 链接不可读取: {rel}: {exc}')
                unresolved.append({'path': rel, 'target': None, 'resolved': None, 'reason': 'READLINK_ERROR'})
                continue
            try:
                resolved = path.resolve(strict=True)
                if not resolved.is_file():
                    raise OSError('目标不是普通文件')
            except (OSError, RuntimeError) as exc:
                warnings.append(f'NL 链接失效: {rel}: {exc}')
                unresolved.append({'path': rel, 'target': target, 'resolved': None, 'reason': 'UNRESOLVED'})
                continue
            if scoped and resolved.is_relative_to(raw_root) and not resolved.is_relative_to(scope_dir):
                # Belongs to a sibling library outside the requested single-library scope; do not misclassify as UNMATCHED.
                continue
            matches = lookup.get(str(resolved), [])
            if len(matches) != 1:
                warnings.append(f'NL 来源无法唯一归属: {rel} → {resolved}')
                unresolved.append({'path': rel, 'target': target, 'resolved': str(resolved), 'reason': 'UNMATCHED' if not matches else 'AMBIGUOUS'})
                continue
            vendor, library, version, view = matches[0]
            groups[(vendor, library)][view][version].append({'path': rel, 'target': target, 'resolved': str(resolved)})
    at = utc_text()
    return [
        {
            'version': nl_version,
            'vendor': vendor,
            'library': library,
            'root': str(root),
            'observed_at': at,
            'views': {v: dict(sorted(versions.items())) for v, versions in sorted(views.items())},
        }
        for (vendor, library), views in sorted(groups.items())
    ]


def update_pointer(folder, name, target):
    pointer = folder / name
    if pointer.exists() and not pointer.is_symlink():
        raise ValueError(f'拒绝覆盖非软链接指针: {pointer}')
    target_path = Path(target)
    if (
        target_path.is_absolute()
        or '..' in target_path.parts
        or len(target_path.parts) > 2
        or (len(target_path.parts) == 2 and target_path.parts[0] not in ('delivery', 'formal', 'effective', 'log'))
    ):
        raise ValueError('指针目标必须在本库目录')
    if len(target_path.parts) == 2 and (folder / target_path.parts[0]).is_symlink():
        raise ValueError('指针目录不能为软链接')
    if not (folder / target).is_file() or (folder / target).is_symlink():
        raise ValueError('指针目标无效')
    if pointer.is_symlink() and os.readlink(pointer) == target:
        return
    tmp = folder / ('.pointer_' + uuid.uuid4().hex)
    try:
        os.symlink(target, tmp)
        os.replace(tmp, pointer)
    finally:
        tmp.unlink(missing_ok=True)


def _latest_delivery(folder, warnings, work, vendor, library, *, registration_times_fn=None):
    items = []
    for path in archive_files(folder, 'delivery', 'delivery_*.json'):
        if path.is_symlink():
            raise ValueError('交付文件不能是链接')
        value = json.loads(path.read_text(encoding='utf-8'))
        items.append((path, value))
    if not items:
        return
    if len(items) == 1:
        chosen = items[0][0]
    else:
        try:
            times = registration_times_fn(work, vendor, library) if registration_times_fn else read_registration_times(work, vendor, library)
            ordered = order_deliveries([value for _, value in items], times)
            chosen = next(path for path, value in items if value['version'] == ordered[-1]['version'])
        except ValueError:
            pointer = folder / 'latest_delivery.json'
            if pointer.is_symlink():
                pointer.unlink()
            warnings.append(f'{folder}: 版本日期缺失或重复，最新交付次序未确认')
            return
    update_pointer(folder, 'latest_delivery.json', str(chosen.relative_to(folder)))


def inventory_sources(
    raw_root,
    nl_root,
    output,
    *,
    nl_version=None,
    update_raw=True,
    update_formal=True,
    vendor=None,
    library=None,
    verify_raw=True,
    ignore_patterns=None,
    extra_extensions=None,
    registration_times_fn=None,
    progress_cb=None,
    cancel_event=None,
):
    """Pure Layer 1 inventory: scan RAW & Formal roots and archive immutable deliveries/snapshots only."""
    if not any((update_raw, update_formal)):
        raise ValueError('L1 盘点至少需要启用 RAW 或 Formal 之一')
    if bool(vendor) != bool(library) or any(x and (not SAFE.fullmatch(x) or x in ('.', '..')) for x in (vendor, library)):
        raise ValueError('供应商和库必须同时指定且名称安全')
    raw = Path(raw_root).resolve(strict=True) if (update_raw or update_formal) and raw_root else None
    nl = Path(nl_root).resolve(strict=True) if update_formal and nl_root else None
    out = Path(output).resolve()
    if (update_raw or update_formal) and (raw is None or not raw.is_dir()):
        raise ValueError('需要 RAW 总目录')
    if update_formal and (nl is None or not nl.is_dir()):
        raise ValueError('需要 NL 总目录')
    if any(out.is_relative_to(p) or p.is_relative_to(out) for p in (raw, nl) if p is not None):
        raise ValueError('输出目录不得与 RAW 或 NL 目录重叠')
    version = (nl_version or infer_nl_version(nl)) if update_formal else None
    if version and (not SAFE.fullmatch(version) or version in ('.', '..')):
        raise ValueError('NL 版本名称不安全')

    cfg_ignore, cfg_ext = _load_work_inventory_options(out)
    if ignore_patterns is None:
        ignore_patterns = cfg_ignore
    merged_ext = {**cfg_ext, **(extra_extensions or {})} if (cfg_ext or extra_extensions) else None

    archived = _load_archived_deliveries(out, vendor, library) if (raw and not verify_raw) else None
    observations = {}
    raw_stats = {}
    warnings = []
    # Single-library scope is honored even when update_formal=True (sibling symlinks are skipped cleanly).
    deliveries, lookup = (
        _inventory_raw(
            raw,
            warnings,
            observations,
            scope_vendor=vendor,
            scope_library=library,
            archived=archived,
            ignore_patterns=ignore_patterns,
            extra_extensions=merged_ext,
            stats=raw_stats,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )
        if raw
        else ([], {})
    )
    check_cancel(cancel_event, 'L1 扫描已由用户终止')
    unresolved = []
    if update_formal:
        emit_progress(progress_cb, 'L1', f'L1 盘点 Formal NL ({version})…')
    formals = (
        _inventory_formal(
            nl,
            lookup,
            version,
            warnings,
            unresolved,
            raw_root=raw,
            scope_vendor=vendor,
            scope_library=library,
        )
        if update_formal
        else []
    )
    out.mkdir(parents=True, exist_ok=True)
    if update_raw:
        _check_view_extension_drift(out, merged_ext, warnings)
    result = {
        'delivery_created': 0,
        'delivery_unchanged': 0,
        'formal_created': 0,
        'formal_unchanged': 0,
        'raw_versions_walked': raw_stats.get('raw_versions_walked', 0),
        'raw_versions_skipped': raw_stats.get('raw_versions_skipped', 0),
        'new_deliveries_by_lib': {},
        'touched_libraries': [],
        'source_verifications': raw_stats.get('source_verifications', []) if update_raw else [],
        'warnings': warnings,
    }
    if update_formal:
        status = 'PARTIAL' if unresolved else 'COMPLETE'
        result.update(formal_observation_status=status, formal_unresolved=unresolved)
        result['source_verifications'].extend({
            'vendor': row['vendor'],
            'library': row['library'],
            'source': 'FORMAL',
            'nl_version': row['version'],
            'status': status,
            'at': row['observed_at'],
        } for row in formals)
        if vendor and not formals:
            result['source_verifications'].append({
                'vendor': vendor,
                'library': library,
                'source': 'FORMAL',
                'nl_version': version,
                'status': 'PARTIAL' if unresolved else 'NO_MATCH',
                'at': utc_text(),
            })
        log = out / 'formal_observations.tsv'
        state_file = out / '.formal_observation_state.json'
        scoped_formal = bool(vendor and library)
        matched_rows = []
        for formal in formals:
            for kind, versions in formal['views'].items():
                for source_version, links in versions.items():
                    for link in links:
                        matched_rows.append((link['path'], link['target'], link['resolved'], f"MATCHED:{formal['vendor']}/{formal['library']}/{source_version}/{kind}"))
        obs_digest = hashlib.sha256(
            json.dumps({'nl_root': str(nl), 'nl_version': version, 'matched': matched_rows}, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        ).hexdigest()
        with locked(out):
            if log.is_symlink():
                raise ValueError('正式来源观察日志不能为软链接')
            if state_file.is_symlink():
                raise ValueError('正式观察状态文件不能为软链接')
            prev_state = {}
            if not scoped_formal and state_file.is_file():
                try:
                    loaded = json.loads(state_file.read_text(encoding='utf-8'))
                    if isinstance(loaded, dict):
                        prev_state = loaded
                except (OSError, ValueError, TypeError):
                    prev_state = {}
            expected_entry = {'nl_root': str(nl), 'digest': obs_digest, 'matched_count': len(matched_rows)}
            deduplicated = (not scoped_formal) and (not unresolved) and log.is_file() and prev_state.get(version) == expected_entry
            with log.open('a', encoding='utf-8', newline='') as stream:
                writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
                stamp = utc_text()
                run = uuid.uuid4().hex
                if deduplicated:
                    writer.writerow([stamp, str(nl), version, 'UNCHANGED', '', '', '', f'SAME_AS_PREVIOUS:{len(matched_rows)}', run])
                else:
                    writer.writerow([stamp, str(nl), version, status, '', '', '', f'SCOPE:{vendor}/{library}' if scoped_formal else '', run])
                    for m_path, m_target, m_resolved, m_tag in matched_rows:
                        writer.writerow([stamp, str(nl), version, status, m_path, m_target, m_resolved, m_tag, run])
                    for item in unresolved:
                        writer.writerow([stamp, str(nl), version, status, item['path'], item['target'] or '', item['resolved'] or '', item['reason'], run])
                stream.flush()
                os.fsync(stream.fileno())
            if not scoped_formal and not deduplicated:
                if not unresolved:
                    prev_state[version] = expected_entry
                    write_atomic(state_file, prev_state)
                elif version in prev_state:
                    prev_state.pop(version, None)
                    write_atomic(state_file, prev_state)
            result['formal_observation_deduplicated'] = deduplicated

    grouped = defaultdict(lambda: {'deliveries': [], 'formals': []})
    for row in deliveries if update_raw else []:
        grouped[(row['vendor'], row['library'])]['deliveries'].append(row)
    for row in formals:
        grouped[(row['vendor'], row['library'])]['formals'].append(row)
    if vendor:
        grouped = {key: row for key, row in grouped.items() if key == (vendor, library)}

    for (v, lib), rows in sorted(grouped.items()):
        result['touched_libraries'].append((v, lib))
        folder = library_folder(out, v, lib)
        with locked(folder):
            observation_path = log_file(folder, 'raw_observations.tsv')
            if observation_path.is_symlink():
                raise ValueError('RAW 观察记录不能为软链接')
            baseline = {}
            if observation_path.exists():
                with observation_path.open(encoding='utf-8', newline='') as stream:
                    for record in csv.reader(stream, delimiter='\t'):
                        if len(record) != 5:
                            raise ValueError('RAW 观察记录格式无效')
                        old_version, old_path, size, mtime, _ = record
                        baseline.setdefault(old_version, {})[old_path] = (int(size), int(mtime))
            new_observations = []
            for delivery in rows['deliveries']:
                version_name = delivery['version']
                current = observations.get((v, lib, version_name))
                if current is None:
                    continue
                if version_name in baseline:
                    changed = [name for name, stat in current.items() if name in baseline[version_name] and baseline[version_name][name] != stat]
                    if changed:
                        warnings.append(f'{v}/{lib}/{version_name}: {len(changed)} 个文件大小或修改时间变化，疑似原地修改；不证明内容相同或历史可还原')
                else:
                    stamp = utc_text()
                    new_observations.extend([version_name, path, size, mtime, stamp] for path, (size, mtime) in sorted(current.items()))
            if new_observations:
                with observation_path.open('a', encoding='utf-8', newline='') as stream:
                    csv.writer(stream, delimiter='\t', lineterminator='\n').writerows(new_observations)
                    stream.flush()
                    os.fsync(stream.fileno())

            for delivery in rows['deliveries']:
                prior = []
                for p in archive_files(folder, 'delivery', 'delivery_*.json'):
                    if p.is_symlink():
                        raise ValueError('交付文件不能是链接')
                    value = json.loads(p.read_text(encoding='utf-8'))
                    if set(value) != {'vendor', 'library', 'version', 'version_date', 'directory_created_at', 'root', 'views'}:
                        raise ValueError('输出目录含非七字段交付，需使用独立目录')
                    if value['version'] == delivery['version']:
                        prior.append(value)
                if len(prior) > 1:
                    raise ValueError('输出含重复版本交付')
                if prior:
                    former = dict(prior[0])
                    current_d = dict(delivery)
                    for value in (former, current_d):
                        if value.get('directory_created_at'):
                            value['directory_created_at'] = utc_text(value['directory_created_at'])
                    if former != current_d:
                        changed = [key for key in former if former.get(key) != current_d.get(key)]
                        names = {'directory_created_at': '目录创建时间', 'views': '文件清单', 'root': '来源目录'}
                        warnings.append(f'{v}/{lib}/{delivery["version"]}: ' + '、'.join(names.get(key, key) for key in changed) + '与已登记交付不同；保留历史，未比较文件内容')
                    else:
                        result['delivery_unchanged'] += 1
                    continue
                stamp = delivery['version_date'].replace('-', '') if delivery['version_date'] else 'undated'
                prefix = f'delivery_{lib}_{stamp}'
                delivery_dir = storage_dir(folder, 'delivery')
                write_atomic(delivery_dir / next_filename(delivery_dir, prefix), delivery, immutable=True)
                result['delivery_created'] += 1
                result['new_deliveries_by_lib'].setdefault((v, lib), []).append(delivery['version'])

            if update_raw:
                _latest_delivery(folder, warnings, out, v, lib, registration_times_fn=registration_times_fn)

            for formal in rows['formals']:
                previous = []
                for p in archive_files(folder, 'formal', 'formal_' + version + '_*.json'):
                    if p.is_symlink():
                        raise ValueError('正式快照文件不能是链接')
                    value = json.loads(p.read_text(encoding='utf-8'))
                    previous.append((instant(value['observed_at']), p, value))
                previous.sort(key=lambda x: (utc_text(x[0]), x[1].name))
                if unresolved:
                    warnings.append(f'{v}/{lib}: 正式来源观察不完整，暂不发布快照')
                    continue
                compare = lambda x: {k: v for k, v in x.items() if k != 'observed_at'}
                if previous and compare(previous[-1][2]) == compare(formal):
                    result['formal_unchanged'] += 1
                    update_pointer(folder, 'latest_formal_' + version + '.json', str(previous[-1][1].relative_to(folder)))
                    continue
                stamp = instant(formal['observed_at']).strftime('%Y%m%dT%H%M%SZ')
                formal_dir = storage_dir(folder, 'formal')
                target = formal_dir / next_filename(formal_dir, 'formal_' + version + '_' + stamp)
                write_atomic(target, formal, immutable=True)
                result['formal_created'] += 1
                update_pointer(folder, 'latest_formal_' + version + '.json', str(target.relative_to(folder)))
    return result


def build_from_roots(
    raw_root,
    nl_root,
    output,
    *,
    nl_version=None,
    update_raw=True,
    update_formal=True,
    update_index=True,
    auto_effective=True,
    vendor=None,
    library=None,
    verify_raw=True,
    ignore_patterns=None,
    progress_cb=None,
    cancel_event=None,
):
    """Backward-compatible facade combining L1 inventory with optional L2/L3 delegation to application.path_refresh."""
    if not any((update_raw, update_formal, update_index)):
        raise ValueError('至少选择一项更新')
    if bool(vendor) != bool(library) or any(x and (not SAFE.fullmatch(x) or x in ('.', '..')) for x in (vendor, library)):
        raise ValueError('供应商和库必须同时指定且名称安全')

    out = Path(output).resolve()
    if update_raw or update_formal:
        inv = inventory_sources(
            raw_root,
            nl_root,
            out,
            nl_version=nl_version,
            update_raw=update_raw,
            update_formal=update_formal,
            vendor=vendor,
            library=library,
            verify_raw=verify_raw,
            ignore_patterns=ignore_patterns,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )
    else:
        out.mkdir(parents=True, exist_ok=True)
        inv = {
            'delivery_created': 0,
            'delivery_unchanged': 0,
            'formal_created': 0,
            'formal_unchanged': 0,
            'raw_versions_walked': 0,
            'raw_versions_skipped': 0,
            'new_deliveries_by_lib': {},
            'touched_libraries': [],
            'warnings': [],
        }

    result = {
        **{k: v for k, v in inv.items() if k not in ('new_deliveries_by_lib', 'touched_libraries')},
        'indexes_updated': 0,
        'indexes_unchanged': 0,
        'indexes_failed': 0,
        'effective_published': 0,
        'effective_pending': 0,
    }
    # Legacy compatibility delegation: L2/L3 state & orchestration live solely in application.path_refresh.
    from ai_lib_qor.application.path_refresh import _complete_legacy_build
    _complete_legacy_build(
        out,
        result,
        new_deliveries_by_lib=inv['new_deliveries_by_lib'],
        touched_libraries=inv['touched_libraries'],
        update_raw=update_raw,
        update_index=update_index,
        auto_effective=auto_effective,
        vendor=vendor,
        library=library,
    )
    return result
