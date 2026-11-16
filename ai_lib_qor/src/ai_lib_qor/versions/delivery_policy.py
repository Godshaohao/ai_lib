"""Apply explicit deliveries without inferring deletion from missing files."""
from .slot_resolver import delivery_members


def apply_delivery(parent, delivery, selected_keys=None):
    new = dict(parent)
    supplied = delivery_members(delivery)
    removed = delivery['explicit_removed_file_keys']
    if selected_keys is not None:
        selected_keys = set(selected_keys)
        unknown = selected_keys - (set(supplied) | set(removed))
        if unknown: raise ValueError(f'所选 file_key 不在交付记录: {sorted(unknown)}')
        supplied = {key: value for key, value in supplied.items() if key in selected_keys}
        removed = [key for key in removed if key in selected_keys]
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
