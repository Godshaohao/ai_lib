"""Extract fixed, unambiguous v3 references from an explicitly selected scope."""
from pathlib import Path


def delivery_members(delivery, *, verify_files=False, selected_keys=None):
    """Strict by default. With selected_keys, inspect selected file slots only.

    Unknown document/other files remain in immutable RAW delivery history; they
    cannot silently become effective members. Requested unknown/ambiguous keys
    still fail. Does not infer deletion from an absent file in a partial package.
    """
    root = Path(delivery['source_root']).expanduser().resolve() if verify_files else None
    if verify_files and not root.is_dir():
        raise ValueError(f'交付来源目录不可访问: {root}')
    selected = set(selected_keys) if selected_keys is not None else None
    if selected is not None:
        known = {f['file_key'] for f in delivery['files'] if f['classification'] == 'RESOLVED' and f['file_key']}
        absent = selected - known
        if absent:
            raise ValueError(f'选择了未确认或不存在的文件位: {sorted(absent)}')
    result = {}
    ids = [f['file_id'] for f in delivery['files']]
    if len(set(ids)) != len(ids):
        raise ValueError('交付内 file_id 重复')
    for f in delivery['files']:
        key = f['file_key']
        if selected is not None and key not in selected:
            continue
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
