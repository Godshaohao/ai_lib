"""Read installed mixed delivery files without rebuilding or modifying them."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Mapping

from lib_guard.view_types import canonical_file_type, release_view_dir


_FORMAL_PACKAGE_PREFIX = 'lib_NL'
_FORMAL_POINTER_NAMES = ('current', 'latest')
_FORMAL_CONTROL_NAMES = frozenset({
    'history', '.staging', 'release_runs', 'reports', 'scan_out', 'diff', 'html',
    'release_manifest.json', 'release_result.json', 'release_set_manifest.json',
})


def _is_formal_auxiliary(path: Path) -> bool:
    return path.name in {'release_manifest.json', 'release_result.json', 'release_set_manifest.json'} or path.name.endswith('.lock')


def _formal_package_roots(root: Path) -> list[Path]:
    if root.name.startswith(_FORMAL_PACKAGE_PREFIX):
        return [root]
    return sorted(
        (entry for entry in root.iterdir() if entry.is_dir() and not entry.is_symlink()
         and entry.name.startswith(_FORMAL_PACKAGE_PREFIX)),
        key=lambda entry: entry.name,
    )


def _formal_pointer(root: Path, package_roots: list[Path]) -> dict[str, str]:
    """Return the named delivery entry without treating it as a version diff."""

    if root.name.startswith(_FORMAL_PACKAGE_PREFIX):
        for name in _FORMAL_POINTER_NAMES:
            entry = root / name
            if not (entry.exists() or entry.is_symlink()):
                continue
            try:
                target = entry.resolve()
            except (OSError, RuntimeError):
                return {'name': name, 'target': '', 'status': '断链'}
            status = '正常' if target.is_dir() else '断链'
            return {'name': name, 'target': target.name if target.exists() else '', 'status': status}
        return {'name': '', 'target': root.name, 'status': '当前目录'}
    package_names = {entry.name for entry in package_roots}
    for name in _FORMAL_POINTER_NAMES:
        entry = root / name
        if not (entry.exists() or entry.is_symlink()):
            continue
        try:
            target = entry.resolve()
        except (OSError, RuntimeError):
            return {'name': name, 'target': '', 'status': '断链'}
        status = '正常' if target.is_dir() and target.name in package_names else '目标不是正式包'
        return {'name': name, 'target': target.name if target.exists() else '', 'status': status}
    return {'name': '', 'target': '', 'status': '未配置'}


def audit_formal_directory(
    root: str | Path,
    catalog: Mapping[str, Any] | None = None,
    *,
    max_files: int = 100_000,
) -> dict[str, Any]:
    """Audit one installed formal delivery tree without requiring a manifest.

    This is deliberately a current-tree audit.  It does not compare packages,
    infer FULL/FIX/effective state, or read file contents.  A manifest can add
    provenance elsewhere, but its absence is not a delivery failure.
    """

    directory = Path(root).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f'正式目录不存在或不是目录：{directory}')
    package_roots = _formal_package_roots(directory)
    pointer = _formal_pointer(directory, package_roots)
    if package_roots and not directory.name.startswith(_FORMAL_PACKAGE_PREFIX):
        # A formal root may retain history and operational folders beside the
        # current lib_NL* packages.  Audit only the current package payloads;
        # history is evidence, not part of the current delivery.
        inventory = {
            'files': [], 'file_count': 0, 'unknown_count': 0, 'broken_count': 0,
            'type_counts': defaultdict(int), 'ignored_directory_links': [],
        }
        for package in package_roots:
            child = inventory_directory(package, catalog or {}, max_files=max_files)
            for item in child['files']:
                item = dict(item)
                item['relative_path'] = str(Path(package.name) / item['relative_path'])
                inventory['files'].append(item)
            inventory['file_count'] += child['file_count']
            inventory['unknown_count'] += child['unknown_count']
            inventory['broken_count'] += child['broken_count']
            inventory['ignored_directory_links'].extend(child['ignored_directory_links'])
            for key, count in child['type_counts'].items():
                inventory['type_counts'][key] += count
        if inventory['file_count'] > max_files:
            raise ValueError(f'正式目录超过 {max_files} 个文件，请选择具体交付目录；原快照未替换。')
    else:
        inventory = inventory_directory(directory, catalog or {}, max_files=max_files)
    inventory['files'] = [item for item in inventory['files'] if not _is_formal_auxiliary(Path(str(item['path'])))]
    inventory['file_count'] = len(inventory['files'])
    inventory['unknown_count'] = sum(1 for item in inventory['files'] if not item.get('library'))
    inventory['broken_count'] = sum(1 for item in inventory['files'] if item.get('link_status') == '链接失效')
    inventory['type_counts'] = defaultdict(int)
    for item in inventory['files']:
        inventory['type_counts'][str(item.get('file_type') or 'unknown')] += 1
    package_names = {entry.name for entry in package_roots}
    view_counts: dict[str, int] = defaultdict(int)
    package_rows: dict[str, dict[str, Any]] = {
        entry.name: {'name': entry.name, 'path': str(entry), 'file_count': 0, 'views': {}}
        for entry in package_roots
    }
    extra_paths: list[str] = []
    unknown_views: set[str] = set()

    for item in inventory['files']:
        relative = Path(str(item['relative_path']))
        if directory.name.startswith(_FORMAL_PACKAGE_PREFIX) and relative.parts and relative.parts[0] in _FORMAL_POINTER_NAMES:
            continue
        package_name = directory.name if directory.name.startswith(_FORMAL_PACKAGE_PREFIX) else (
            relative.parts[0] if relative.parts and relative.parts[0] in package_names else ''
        )
        view_name = ''
        if package_name:
            package_relative = relative if directory.name.startswith(_FORMAL_PACKAGE_PREFIX) else Path(*relative.parts[1:])
            if package_relative.parts:
                view_dir = package_relative.parts[0]
                if len(package_relative.parts) == 1 and Path(str(item['path'])).parent == (directory / package_name):
                    continue
                view_name = release_view_dir(view_dir)
                if package_relative.parts[0].upper() not in {view_name, 'LEF', 'LIB', 'GDS', 'OAS', 'DB', 'CDL', 'SPICE', 'VERILOG', 'RTL', 'NDM', 'NDM_WO_LIB', 'DFT', 'PGV', 'QRC', 'RAM', 'LPE_SPICE', 'CCSP', 'CONFIG', 'TECHNOLOGY'}:
                    unknown_views.add(package_relative.parts[0])
        else:
            view_name = release_view_dir(item.get('file_type'))
        view_counts[view_name] += 1
        if package_name in package_rows:
            row = package_rows[package_name]
            row['file_count'] += 1
            row['views'][view_name] = row['views'].get(view_name, 0) + 1

    for package in package_roots:
        for entry in package.iterdir():
            if entry.name in _FORMAL_CONTROL_NAMES:
                continue
            if entry.is_file() or entry.is_symlink():
                if not _is_formal_auxiliary(entry):
                    extra_paths.append(entry.name if directory.name.startswith(_FORMAL_PACKAGE_PREFIX) else str(entry.relative_to(directory)))
            elif entry.is_dir() and entry.name.lower() in {'readme', 'docs', 'doc', 'backup', 'bak', 'log', 'logs'}:
                extra_paths.append(entry.name if directory.name.startswith(_FORMAL_PACKAGE_PREFIX) else str(entry.relative_to(directory)))
    if not directory.name.startswith(_FORMAL_PACKAGE_PREFIX):
        for entry in directory.iterdir():
            if entry.name in package_names or entry.name in _FORMAL_POINTER_NAMES or entry.name in _FORMAL_CONTROL_NAMES:
                continue
            if (entry.is_file() and not _is_formal_auxiliary(entry)) or (entry.is_dir() and entry.name.lower() in {'readme', 'docs', 'doc', 'backup', 'bak', 'log', 'logs'}):
                extra_paths.append(str(entry.relative_to(directory)))

    warnings: list[str] = []
    if extra_paths:
        warnings.append(f'发现 {len(extra_paths)} 个非交付内容：{", ".join(sorted(extra_paths)[:8])}' + (' 等' if len(extra_paths) > 8 else ''))
    if unknown_views:
        warnings.append(f'发现未配置的视图目录：{", ".join(sorted(unknown_views))}')
    if pointer['status'] == '断链':
        warnings.append(f'{pointer["name"]} 指向不存在的目录')
    elif pointer['status'] == '目标不是正式包':
        warnings.append(f'{pointer["name"]} 未指向 lib_NL* 正式包')
    if pointer['status'] == '未配置' and not directory.name.startswith(_FORMAL_PACKAGE_PREFIX):
        warnings.append('未发现 current/latest 正式入口')

    manifest_present = any((package / 'release_manifest.json').is_file() for package in package_roots)
    status = '不可用' if inventory['broken_count'] or pointer['status'] in {'断链', '目标不是正式包'} else '部分可用' if warnings else '可用'
    for row in package_rows.values():
        row['views'] = dict(sorted(row['views'].items()))
    return {
        'status': 'READY',
        'audit_status': status,
        'root': str(directory),
        'refreshed_at': datetime.now(timezone.utc).isoformat(),
        'manifest_present': manifest_present,
        'package_count': len(package_roots),
        'packages': list(package_rows.values()),
        'current_pointer': pointer,
        'file_count': inventory['file_count'],
        'broken_count': inventory['broken_count'],
        'unknown_count': inventory['unknown_count'],
        'view_counts': dict(sorted(view_counts.items())),
        'type_counts': inventory['type_counts'],
        'ignored_directory_links': inventory['ignored_directory_links'],
        'files': inventory['files'],
        'extra_paths': sorted(extra_paths),
        'unknown_views': sorted(unknown_views),
        'warnings': warnings,
        'version_comparisons': 0,
        'comparison_policy': '正式目录只核查当前交付结构，不做历史版本对比',
    }


def inventory_directory(root: str | Path, catalog: Mapping[str, Any], *, max_files: int = 100_000) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f'正式目录不存在或不是目录：{root}')
    owners: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for library in catalog.get('libraries', []):
        for version in library.get('versions', []):
            if version.get('raw_path'):
                owners[str(Path(version['raw_path']).expanduser().resolve())].append((library['library_name'], version['version_id']))
    files=[]
    ignored=[]
    errors=[]
    def onerror(error: OSError) -> None:
        errors.append(str(error))
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=onerror):
        parent=Path(directory)
        for name in list(dirs):
            if (parent/name).is_symlink():
                ignored.append(str(parent/name))
                dirs.remove(name)
        for name in sorted(names):
            path=parent/name
            if not (path.is_symlink() or path.is_file()):
                continue
            if len(files) >= max_files:
                raise ValueError(f'正式目录超过 {max_files} 个文件，请选择具体交付目录；原快照未替换。')
            is_link=path.is_symlink()
            source=''
            matches=[]
            status='普通文件'
            if is_link:
                try:
                    target=path.resolve()
                    source=str(target)
                    status='链接正常' if target.is_file() else '链接失效'
                    for ancestor in target.parents:
                        if str(ancestor) in owners:
                            matches=owners[str(ancestor)]
                            break
                except (OSError, RuntimeError):
                    status='链接失效'
            match=matches[0] if len(matches)==1 else ('','')
            suffix=Path(path.stem).suffix if path.suffix.lower()=='.gz' else path.suffix
            files.append({'path':str(path),'relative_path':str(path.relative_to(root)), 'source_path':source,
                          'library':match[0], 'version':match[1], 'file_type':canonical_file_type(suffix.lstrip('.')),
                          'link_status':status,'source_status':'链接目标匹配' if len(matches)==1 else '归属冲突' if matches else '来源待确认',
                          'corner':'未记录'})
    if errors:
        raise ValueError('正式目录读取不完整，原快照未替换：'+'；'.join(errors))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in files:
        grouped[item['library']].append(item)
    libraries=[]
    type_counts: dict[str,int]=defaultdict(int)
    for item in files:
        type_counts[item['file_type']]+=1
    for name, items in sorted(grouped.items()):
        if not name:
            continue
        counts: dict[str,int]=defaultdict(int)
        for item in items:
            counts[item['file_type']]+=1
        libraries.append({'library':name,'versions':sorted({item['version'] for item in items}),
                          'file_count':len(items), 'types':dict(counts),
                          'broken_count':sum(item['link_status']=='链接失效' for item in items)})
    return {'status':'READY','root':str(root),'refreshed_at':datetime.now(timezone.utc).isoformat(),
            'libraries':libraries,'files':files,'file_count':len(files),'unknown_count':len(grouped.get('',[])),
            'broken_count':sum(item['link_status']=='链接失效' for item in files),
            'ignored_directory_links':ignored,'type_counts':dict(type_counts)}
