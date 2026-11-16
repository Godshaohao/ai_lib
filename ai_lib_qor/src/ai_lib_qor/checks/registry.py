"""Explicit trusted local check registrations; no imports from user-provided paths."""
from .plugins.lef_macro_diff import compare as macro_diff
from .plugins.lef_liberty_pin_match import compare as pin_match


def lef_diff(context):
    changes = []
    for comp in context['comparisons']:
        delta = macro_diff(comp['old'], comp['new'])
        old_ref, new_ref = comp['old_ref'], comp['new_ref']
        changes.append({'file_key':comp['file_key'], 'old_source_ref':old_ref, 'new_source_ref':new_ref,
                        'source_changed':old_ref != new_ref, 'content_status':'CHANGED' if delta else 'UNKNOWN',
                        'object_changes':delta or []})
    return {'file_changes':changes}


def lef_liberty(context):
    return {'quality_checks':[pin_match(p['lef'],p['liberty'],p['lef_key'],p['liberty_key']) for p in context['pin_pairs']]}


REGISTRY = {'LEF_MACRO_DIFF':lef_diff, 'LEF_LIBERTY_PIN_MATCH':lef_liberty}


def resolve_plugins(names, registry=REGISTRY):
    if not isinstance(names, list) or not names: raise ValueError('必须明确启用至少一个检查插件')
    if len(names) != len(set(names)): raise ValueError('检查插件重复')
    unknown = [name for name in names if name not in registry]
    if unknown: raise ValueError('未注册的检查插件: ' + ', '.join(unknown))
    return [registry[name] for name in names]
