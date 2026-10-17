"""Explicit aliases and unique exact names only; no fuzzy identity guesses."""

from collections import Counter
from copy import deepcopy
from fnmatch import fnmatchcase
from .model import entity_id, port_id
from .normalize import normalize_port
from .profile import select_review_facts


def build_effective_model(index, profile, *, mapping=None, allow_unused_mapping=False):
    index = apply_file_contexts(index, mapping, allow_unused=allow_unused_mapping)
    facts, scope = select_review_facts(index, profile, mapping=mapping, allow_unused_mapping=allow_unused_mapping)
    bindings = bind_macros(facts, mapping=mapping, required_views=profile['config']['required_views'], allow_unused_mapping=True)
    missing = {(item['macro'], item['variant']) for item in scope['missing_contexts']}
    for binding in bindings:
        if (binding['name'], binding['variant']) in missing and binding['status'] in {'CONFIRMED', 'UNIQUE_EXACT'}:
            binding.update(status='UNRESOLVED', reason_code='MISSING_SELECTED_CONTEXT')
    return {'schema_version': 'semantic_effective_model.v1', 'effective_digest': index['effective_digest'],
            'profile_digest': profile['digest'], 'facts': facts, 'bindings': bindings, 'scope': scope}


def apply_file_contexts(index, mapping, *, allow_unused=False):
    if mapping is None:
        return index
    if not isinstance(mapping, dict):
        raise ValueError('映射必须为 JSON 对象')
    if mapping.get('confirmed') is not True:
        raise ValueError('映射必须经过人工确认（confirmed: true）')
    if mapping.get('library_id') and mapping['library_id'] != index['library_id']:
        raise ValueError('映射 library_id 与当前库不一致')
    contexts = mapping.get('file_contexts', [])
    if not isinstance(contexts, list):
        raise ValueError('file_contexts 必须为列表')
    if not contexts:
        return index
    if (not isinstance(contexts, list) or mapping.get('library_id') != index['library_id']
            or not isinstance(mapping.get('basis'), str) or not mapping['basis'].strip()):
        raise ValueError('file_contexts 需要明确的 library_id、basis 和配置列表')
    for row in contexts:
        if (not isinstance(row, dict) or set(row) - {'view', 'files', 'corner', 'mode', 'variant'}
                or row.get('view') not in {'lef', 'liberty', 'verilog'}
                or not isinstance(row.get('files'), list) or not row['files']
                or any(not isinstance(pattern, str) or not pattern.strip() for pattern in row['files'])
                or not set(row) & {'corner', 'mode', 'variant'}
                or any(not isinstance(value, str) or not value.strip()
                       for key, value in row.items() if key in {'corner', 'mode', 'variant'})):
            raise ValueError('file_contexts 每项需要 view、files 列表及明确的 corner/mode/variant')
    facts, matched = [], set()
    for source in index['facts']:
        hits = [i for i, row in enumerate(contexts) if row['view'] == source['view']
                and any(fnmatchcase(source['file_identity']['effective_relpath'], pattern) for pattern in row['files'])]
        if len(hits) > 1:
            raise ValueError('同一文件匹配多份 file_contexts，请缩小文件范围')
        if not hits:
            facts.append(source)
            continue
        matched.update(hits)
        context = {key: value for key, value in contexts[hits[0]].items() if key in {'corner', 'mode', 'variant'}}
        evidence = source['file_identity']
        if any(evidence.get(key) is not None and evidence[key] != value for key, value in context.items()):
            raise ValueError('人工上下文与已确认扫描上下文冲突，请核对来源')
        fact = deepcopy(source)
        fact['file_identity'].update(context, semantic_context={**context, 'confirmed': True,
            'basis': mapping['basis'], 'source': 'manual_mapping'})
        for key in ('corner', 'variant'):
            if key in context:
                fact[key] = context[key]
        if 'corner' in context:
            fact['corner_status'] = 'CONFIRMED'
        facts.append(fact)
    if len(matched) != len(contexts) and not allow_unused:
        raise ValueError('file_contexts 中有配置未匹配可用扫描事实，请核对文件路径与扫描')
    return {**index, 'facts': facts}


def bind_macros(facts, *, mapping=None, required_views=('lef', 'liberty', 'verilog'), allow_unused_mapping=False):
    if mapping and mapping.get('confirmed') is not True:
        raise ValueError('Semantic mapping must be explicitly confirmed')
    aliases = (mapping or {}).get('macro_aliases', [])
    groups = {}
    used = set()
    for fact in facts:
        for obj in fact['objects']:
            candidates = [i for i, row in enumerate(aliases)
                          if row['view'] == fact['view'] and row['object'] == obj['name']
                          and (not row.get('source_relpath') or row['source_relpath'] == fact['file_identity']['source_relpath'])]
            if len(candidates) > 1:
                raise ValueError('Conflicting explicit macro mappings')
            name = aliases[candidates[0]]['macro'] if candidates else obj['name']
            used.update(candidates)
            library = fact['file_identity']['library_id']
            key = (library, name, fact.get('variant'))
            group = groups.setdefault(key, {'schema_version': 'semantic_binding.v1',
                'macro_id': entity_id(*key), 'library_id': library, 'name': name,
                'variant': fact.get('variant'), 'observations': [], 'explicit': False})
            group['explicit'] |= bool(candidates)
            group['observations'].append({'view': fact['view'], 'corner': fact.get('corner'),
                'corner_status': fact.get('corner_status'), 'object': deepcopy(obj),
                'source_ref': fact['file_identity']['parser_result_ref'], 'evidence': deepcopy(fact['file_identity'])})
    if len(used) != len(aliases) and not allow_unused_mapping:
        raise ValueError('Explicit macro mapping has no selected evidence')
    rows = []
    for group in groups.values():
        observations = group['observations']
        counts = Counter((obs['view'], obs['corner'] if obs['corner_status'] == 'CONFIRMED' else None) for obs in observations)
        mixed_unknown_corner = any(sum(obs['view'] == view for obs in observations) > 1
            and any(obs['view'] == view and obs['corner_status'] != 'CONFIRMED' for obs in observations)
            for view in {obs['view'] for obs in observations})
        if max(counts.values()) > 1 or mixed_unknown_corner:
            status, reason = 'AMBIGUOUS', 'DUPLICATE_VIEW_CONTEXT'
        elif not set(required_views) <= {obs['view'] for obs in observations}:
            status, reason = 'UNRESOLVED', 'MISSING_VIEW_BINDING'
        else:
            status, reason = ('CONFIRMED', 'EXPLICIT_MAPPING') if group['explicit'] else ('UNIQUE_EXACT', 'UNIQUE_EXACT_NAME')
        group.update(status=status, reason_code=reason)
        group['observations'] = sorted(observations, key=lambda obs: (obs['view'], obs['corner'] or '', obs['source_ref']))
        ports = {}
        for obs in group['observations']:
            aliases_for_view = ((mapping or {}).get('port_aliases') or {}).get(obs['view'], {})
            for port in obs['object']['ports']:
                normalized = normalize_port(port, aliases=aliases_for_view)
                for bit in normalized['bits'] or []:
                    row = ports.setdefault(bit, {'port_id': port_id(group['macro_id'], bit), 'logical_bit': bit, 'observations': []})
                    row['observations'].append({'view': obs['view'], 'corner': obs['corner'],
                        'kind': port['kind'], 'direction': normalized['direction'], 'declared_orientation': normalized['orientation'],
                        'source_ref': obs['source_ref'], 'local_name': port['name']})
        group['ports'] = [ports[bit] for bit in sorted(ports)]
        rows.append(group)
    return sorted(rows, key=lambda row: row['macro_id'])
