"""Select and compare an exact Formal snapshot against an Effective member."""


def latest_formal_snapshot(index, nl_version=None):
    return next((snapshot for snapshot in reversed(index['nl_snapshots'])
                 if nl_version is None or snapshot['nl_version'] == nl_version), None)


def formal_link_relation(link, effective):
    if link['source_match'] != 'MATCHED_RAW':
        return '无法确认'
    if effective is None:
        return '无法对照'
    return '来源相同' if link['resolved_path'] == effective['path'] else '来源不同'


def compare_formal_member(snapshot, history, effective):
    if snapshot is None:
        return None, '尚无 Formal 快照'
    link = next((link for link in reversed(history)
                 if link['snapshot_id'] == snapshot['snapshot_id']), None)
    if link is None:
        return None, '最新快照未观察到'
    return link, formal_link_relation(link, effective)
