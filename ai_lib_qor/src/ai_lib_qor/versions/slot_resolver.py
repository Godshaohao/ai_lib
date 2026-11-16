"""Extract fixed, unambiguous v3 source references from intermediate records."""
from pathlib import Path


def delivery_members(delivery, *, verify_files=True):
    root = Path(delivery['source_root']).expanduser().resolve()
    if verify_files and not root.is_dir():
        raise ValueError(f'交付来源目录不可访问: {root}')
    result = {}
    for f in delivery['files']:
        key = f['file_key']
        if f['classification'] != 'RESOLVED' or not key:
            raise ValueError(f"未确认文件身份: {f['relative_path']}")
        if key in result:
            raise ValueError(f'重复 file_key: {key}')
        if verify_files:
            path = (root / f['relative_path']).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError(f"文件不存在或越过来源目录: {f['relative_path']}")
        result[key] = {'kind': 'delivery_file', 'source_library_id': delivery['source_library_id'],
                       'delivery_id': delivery['delivery_id'], 'file_id': f['file_id']}
    ids = [f['file_id'] for f in delivery['files']]
    if len(set(ids)) != len(ids):
        raise ValueError('交付内 file_id 重复')
    return result


def snapshot_members(snapshot):
    result = {}
    for f in snapshot['linked_files']:
        key = f['file_key']
        if not key or key in result:
            raise ValueError('正式快照含有未知或重复 file_key')
        result[key] = {'kind': 'formal_file', 'formal_nl_id': snapshot['formal_nl_id'],
                       'formal_snapshot_id': snapshot['formal_snapshot_id'], 'file_id': f['file_id']}
    ids = [f['file_id'] for f in snapshot['linked_files']]
    if len(ids) != len(set(ids)):
        raise ValueError('正式快照内 file_id 重复')
    if snapshot['coverage'] != 'COMPLETE_IN_SCOPE':
        raise ValueError('正式快照覆盖不足，不能作为完整初始版本')
    return result
