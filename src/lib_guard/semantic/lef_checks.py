"""Small Macro index and task-local RECT check facts from existing LEF evidence."""

from .model import canonical_json, entity_id
from .normalize import normalize_port

LEF_RULES = {
    'LEF_MACRO_DELTA': ['old/new effective', 'complete macro discovery', 'unique macro/variant'],
    'LEF_PHYSICAL_DELTA': ['unique macro', 'complete macro block', 'known physical attribute'],
    'LEF_INTERFACE_DELTA': ['unique macro', 'complete pin set', 'explicit bus and interface attributes'],
    'LEF_GEOMETRY_DELTA': ['unique macro', 'complete RECT pin geometry', 'preserved PORT groups'],
    'LEF_OBS_DELTA': ['unique macro', 'complete RECT obstruction geometry'],
}


def _covered(payload, key):
    coverage = payload.get('data', {}).get('semantic_coverage', {})
    return (payload.get('status') == 'PASS' and coverage.get('validated') is True
            and coverage.get('schema_version') == 'semantic_parser_coverage.v1'
            and bool(coverage.get('basis')) and coverage.get(key) in {'PRESENT', 'ABSENT_VERIFIED'})


def _rect(rect):
    return (rect['layer'], rect['x1'], rect['y1'], rect['x2'], rect['y2'])


class LefCheckFacts:
    def __init__(self, *, enabled_checks=None):
        self.payloads = {}
        self.cache = {}
        self.build_count = 0
        self.enabled_checks = set(LEF_RULES if enabled_checks is None else enabled_checks)

    def add(self, evidence, payload):
        if evidence.get('file_type') == 'lef':
            self.payloads.setdefault(evidence['parser_result_ref'], payload)

    def get(self, ref, name):
        key = (ref, name)
        if key in self.cache:
            return self.cache[key]
        payload = self.payloads[ref]
        data = payload['data']
        macro = data['macros'][name]
        interface, geometry = {}, {}
        interface_ready = _covered(payload, 'port_set')
        geometry_ready = _covered(payload, 'pin_geometry')
        need_interface = 'LEF_INTERFACE_DELTA' in self.enabled_checks
        need_geometry = 'LEF_GEOMETRY_DELTA' in self.enabled_checks
        need_obs = 'LEF_OBS_DELTA' in self.enabled_checks
        interface_ready &= need_interface
        geometry_ready &= need_geometry
        pins = macro.get('pins', {}) if need_interface or need_geometry else {}
        for pin_name, pin in pins.items():
            if need_interface:
                normalized = normalize_port({'name': pin_name, 'direction': pin.get('direction'), 'bus_chars': data.get('busbitchars')})
                interface_ready &= normalized['bits'] is not None and normalized['direction'] != 'UNKNOWN'
                interface_ready &= pin.get('use') in {'SIGNAL', 'CLOCK', 'POWER', 'GROUND', 'ANALOG'}
                for bit in normalized['bits'] or []:
                    interface_ready &= bit not in interface
                    interface[bit] = {'direction': normalized['direction'], 'use': pin.get('use')}
            if not need_geometry:
                continue
            groups = [[] for _ in range(pin.get('port_count', 0))]
            for rect in pin.get('rects', []):
                port = rect.get('port_index')
                if not isinstance(port, int) or not 0 <= port < len(groups) or not rect.get('layer'):
                    geometry_ready = False
                    continue
                groups[port].append(_rect(rect))
            geometry[pin_name] = sorted([sorted(group) for group in groups], key=canonical_json)
        value = {'interface': interface, 'interface_ready': interface_ready,
                 'pin_geometry': geometry, 'geometry_ready': geometry_ready,
                 'obstructions': sorted([_rect(rect) for rect in macro.get('obs', [])], key=canonical_json) if need_obs else None,
                 'obs_ready': need_obs and _covered(payload, 'obs_geometry') and all(rect.get('layer') for rect in macro.get('obs', [])), 'macro': macro,
                 'macro_ready': _covered(payload, 'macro_set'),
                 'limitations': data.get('parse_limitations', [])}
        self.cache[key] = value
        self.build_count += 1
        return value


def build_macro_index(index, session):
    groups = {}
    complete = True
    if index is None:
        return {'macros': [], 'complete': False, 'issues': ['NO_BASE_EFFECTIVE']}
    lef_files = [row for row in index['files'] if row['file_type'] == 'lef']
    discovery = {fact['file_identity']['effective_relpath']: fact
                 for fact in index.get('discovery_facts', index['facts']) if fact['view'] == 'lef'}
    complete &= bool(lef_files)
    for row in lef_files:
        fact = discovery.get(row['effective_relpath'])
        payload = session.payloads.get(fact['file_identity']['parser_result_ref']) if fact else None
        complete &= row['fact_status'] == 'AVAILABLE' and payload is not None and _covered(payload, 'macro_set')
    identities = {(obs['source_ref'], obs['object']['name']): binding
                  for binding in index.get('bindings', []) for obs in binding['observations'] if obs['view'] == 'lef'}
    for fact in index['facts']:
        if fact['view'] != 'lef':
            continue
        evidence = fact['file_identity']
        payload = session.payloads.get(evidence['parser_result_ref'])
        if payload is None:
            complete = False
            continue
        complete &= _covered(payload, 'macro_set')
        data = payload.get('data') or {}
        names = data.get('macro_order') or list(data.get('macros') or {})
        selected = {obj['name'] for obj in fact['objects']}
        for name in names:
            if name not in selected:
                continue
            macro = data['macros'][name]
            identity = identities.get((evidence['parser_result_ref'], name))
            canonical_name = identity['name'] if identity else name
            key = (index['library_id'], canonical_name, fact.get('variant'))
            ready = complete and _covered(payload, 'macro_set') and _covered(payload, 'port_set')
            size = macro.get('size') or {}
            groups.setdefault(key, []).append({
                'macro_id': identity['macro_id'] if identity else entity_id(*key),
                'name': canonical_name, 'source_object': name, 'variant': fact.get('variant'),
                'effective_digest': index['effective_digest'],
                'size_um': [size.get('x'), size.get('y')] if data.get('coordinate_units') == 'um' or data.get('database_microns') else None,
                'class': macro.get('class'), 'pin_count': len(macro.get('pins') or {}),
                'source': evidence['source_relpath'], 'source_ref': evidence['parser_result_ref'],
                'status': 'AMBIGUOUS' if identity and identity['status'] == 'AMBIGUOUS' else 'READY' if ready else 'INCOMPLETE'})
    rows = []
    for candidates in groups.values():
        row = dict(candidates[0])
        row['candidates'] = [{'source': item['source'], 'source_ref': item['source_ref'],
                              'source_object': item['source_object']} for item in candidates]
        if len(candidates) != 1:
            row['status'] = 'AMBIGUOUS'
        rows.append(row)
    return {'macros': sorted(rows, key=lambda row: row['macro_id']), 'complete': bool(complete),
            'issues': [] if complete else ['INCOMPLETE_MACRO_DISCOVERY']}


def compare_lef(old_index, new_index, session, *, enabled_checks=None, tolerance_um=1e-6):
    indices = [build_macro_index(index, session) for index in (old_index, new_index)]
    lookups = [{row['macro_id']: row for row in index['macros']} for index in indices]
    rows = []
    rules = set(LEF_RULES if enabled_checks is None else enabled_checks)
    for macro_id in sorted(set(lookups[0]) | set(lookups[1])):
        old, new = (lookup.get(macro_id) for lookup in lookups)
        reliable = old_index is not None and all(row and row['status'] == 'READY' for row in (old, new))
        presence_covered = old_index is not None and all(index['complete'] for index in indices)
        presence_covered &= all(row is None or row['status'] == 'READY' for row in (old, new))
        facts = [session.get(row['source_ref'], row.get('source_object', row['name'])) if row else None for row in (old, new)]
        specs = [('LEF_MACRO_DELTA', 'presence'), ('LEF_PHYSICAL_DELTA', 'size_um'),
                 ('LEF_PHYSICAL_DELTA', 'class'), ('LEF_PHYSICAL_DELTA', 'origin'),
                 ('LEF_PHYSICAL_DELTA', 'symmetry'), ('LEF_INTERFACE_DELTA', 'interface'),
                 ('LEF_GEOMETRY_DELTA', 'pin_geometry'), ('LEF_OBS_DELTA', 'obstructions')]
        for rule, attribute in specs:
            if rule not in rules:
                continue
            if attribute != 'presence' and presence_covered and (old is None or new is None):
                continue
            covered = reliable
            values = []
            for row, fact in zip((old, new), facts):
                if attribute == 'presence':
                    values.append(row is not None)
                elif fact is None:
                    values.append(None)
                elif attribute == 'size_um':
                    values.append(row['size_um'])
                    covered &= row['size_um'] is not None and all(value is not None for value in row['size_um'])
                elif attribute in {'class', 'origin', 'symmetry'}:
                    value = fact['macro'].get(attribute)
                    values.append(sorted(value) if attribute == 'symmetry' and value is not None else value)
                    covered &= value is not None and fact['macro_ready']
                else:
                    values.append(fact[attribute])
                    covered &= fact[{'interface': 'interface_ready', 'pin_geometry': 'geometry_ready', 'obstructions': 'obs_ready'}[attribute]]
            if attribute == 'presence':
                covered = presence_covered
            same = values[0] == values[1]
            if attribute == 'size_um' and covered:
                same = all(abs(left-right) <= tolerance_um for left, right in zip(*values))
            status = 'INCOMPLETE' if not covered else 'UNCHANGED' if same else 'CHANGED'
            details = {}
            if attribute == 'presence' and status == 'CHANGED':
                details['change'] = 'ADDED' if new else 'REMOVED'
            elif attribute == 'interface':
                details.update(old_count=len(values[0]) if values[0] is not None else None,
                               new_count=len(values[1]) if values[1] is not None else None)
                if covered:
                    details['pins'] = [{'pin': pin, 'old': values[0].get(pin), 'new': values[1].get(pin)}
                        for pin in sorted(set(values[0]) | set(values[1])) if values[0].get(pin) != values[1].get(pin)][:20]
                else:
                    details['missing_attributes'] = {}
                    for side, value in zip(('old', 'new'), values):
                        missing = sorted(pin for pin, attrs in (value or {}).items()
                                         if attrs['direction'] == 'UNKNOWN' or attrs['use'] is None)
                        details['missing_attributes'][side] = {'count': len(missing), 'sample': missing[:20]}
            elif attribute in {'pin_geometry', 'obstructions'}:
                details['old_count'] = len(values[0]) if values[0] is not None else None
                details['new_count'] = len(values[1]) if values[1] is not None else None
                if attribute == 'pin_geometry' and covered:
                    details['changed_pins'] = [pin for pin in sorted(set(values[0]) | set(values[1])) if values[0].get(pin) != values[1].get(pin)][:20]
                details['limitations'] = [reason for fact in facts if fact for reason in fact['limitations']][:10]
            else:
                details.update(old=values[0], new=values[1])
            rows.append({'schema_version': 'semantic_delta.v1', 'macro_id': macro_id,
                'macro': (new or old)['name'], 'view': 'lef', 'corner': None, 'check_id': rule,
                'attribute': attribute, 'status': status, 'reason_code': 'SUPPORTED_LEF_FACTS_COMPARED' if covered else 'INCOMPLETE_LEF_CHECK_INPUT',
                'requirements': LEF_RULES[rule], 'details': details,
                'old_evidence': {'parser_result_ref': old['source_ref']} if old else None,
                'new_evidence': {'parser_result_ref': new['source_ref']} if new else None})
    return rows
