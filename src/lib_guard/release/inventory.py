"""Read installed mixed delivery files without rebuilding or modifying them."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Mapping

from lib_guard.view_types import canonical_file_type


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
