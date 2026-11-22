"""Run trusted check functions and retain only explicitly supported contributions."""
from .registry import REGISTRY, resolve_plugins


def run_contributions(names, context, registry=REGISTRY):
    result = {'file_changes': [], 'quality_checks': []}
    for plugin in resolve_plugins(names, registry):
        contribution = plugin(context)
        if not isinstance(contribution, dict) or not set(contribution) <= set(result):
            raise ValueError('插件贡献包含不支持的字段')
        for key, rows in contribution.items():
            if not isinstance(rows, list): raise ValueError('插件贡献必须是列表')
            result[key].extend(rows)
    return result
