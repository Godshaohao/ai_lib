"""Apply explicit deliveries without inferring removal from absent members."""
from .slot_resolver import delivery_members


def apply_delivery(parent, delivery, selected_keys=None, *, verify_files=False):
    new = dict(parent)
    removed = delivery['explicit_removed_file_keys']
    if selected_keys is not None:
        selected_keys = set(selected_keys)
        known = {f['file_key'] for f in delivery['files'] if f['classification'] == 'RESOLVED' and f['file_key']}
        unknown = selected_keys - known - set(removed)
        if unknown:
            raise ValueError(f'所选 file_key 未确认或不在交付记录: {sorted(unknown)}')
        # Only selected known slots are passed to the strict resolver.
        supplied = delivery_members(delivery, selected_keys=selected_keys & known, verify_files=verify_files)
        removed = [key for key in removed if key in selected_keys]
    else:
        supplied = delivery_members(delivery, verify_files=verify_files)
    if len(removed) != len(set(removed)):
        raise ValueError('显式移除文件重复')
    if set(removed) & set(supplied):
        raise ValueError('同一文件既交付又声明移除')
    if set(removed) - set(parent):
        raise ValueError('显式移除的文件不在父版本')
    for key in removed:
        del new[key]
    new.update(supplied)
    return new
