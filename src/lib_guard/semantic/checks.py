"""Advisory rules: changes are facts, not release failures."""

import math
from .model import check_result
from .normalize import normalize_port


def _ports(obs, kind, aliases=None):
    ports = [normalize_port(port, aliases=aliases) for port in obs['object']['ports'] if port['kind'] in kind]
    if any(port['bits'] is None for port in ports):
        return None
    result = {}
    for port in ports:
        for bit in port['bits']:
            if bit in result:
                return None
            result[bit] = port['direction'] if kind == {'SIGNAL'} else port['kind']
    return dict(sorted(result.items()))


def check_bindings(bindings, *, flag_policy=None, mapping=None, enabled_checks=None):
    rows = []
    for binding in bindings:
        macro = binding['macro_id']
        observations = binding['observations']
        refs = [obs['source_ref'] for obs in observations]
        reliable = binding['status'] in {'CONFIRMED', 'UNIQUE_EXACT'}
        if enabled_checks is None or 'MACRO_BINDING' in enabled_checks:
            rows.append(check_result('MACRO_BINDING', macro, 'PASS' if reliable else 'REVIEW_REQUIRED', binding['reason_code'], refs))
        for rule, selected, coverage, kinds in (
            ('SIGNAL_PORT_SET', observations, 'port_set', {'SIGNAL'}),
            ('SIGNAL_PORT_DIRECTION', observations, 'port_set', {'SIGNAL'}),
            ('PG_PORT_LEF_LIB', [obs for obs in observations if obs['view'] in {'lef', 'liberty'}], 'pg_port_set', {'POWER', 'GROUND'}),
        ):
            if enabled_checks is not None and rule not in enabled_checks:
                continue
            actual = []
            ready = reliable and len({obs['view'] for obs in selected}) >= 2
            for obs in selected:
                aliases = ((mapping or {}).get('port_aliases') or {}).get(obs['view'], {})
                ports = _ports(obs, kinds, aliases)
                ready &= (obs['object']['coverage'].get(coverage) in {'PRESENT', 'ABSENT_VERIFIED'}
                          and ports is not None and not any(port['kind'] == 'UNKNOWN' for port in obs['object']['ports']))
                actual.append({'view': obs['view'], 'corner': obs['corner'], 'source_ref': obs['source_ref'], 'ports': ports})
            if not ready:
                status, reason = 'NOT_CHECKED', 'INCOMPLETE_PORT_COVERAGE' if reliable else 'UNCONFIRMED_BINDING'
            elif rule == 'SIGNAL_PORT_SET':
                sets = [set(item['ports']) for item in actual]
                status, reason = ('PASS', 'MATCH') if all(value == sets[0] for value in sets) else ('FAIL', 'PORT_SET_MISMATCH')
            else:
                maps = [item['ports'] for item in actual]
                if rule == 'SIGNAL_PORT_DIRECTION' and any(set(value) != set(maps[0]) for value in maps):
                    status, reason = 'NOT_CHECKED', 'UNALIGNED_PORT_SET'
                elif rule == 'SIGNAL_PORT_DIRECTION' and any('UNKNOWN' in value.values() for value in maps):
                    status, reason = 'NOT_CHECKED', 'UNKNOWN_DIRECTION'
                else:
                    status, reason = ('PASS', 'MATCH') if all(value == maps[0] for value in maps) else ('FAIL', 'PORT_DIRECTION_MISMATCH' if rule == 'SIGNAL_PORT_DIRECTION' else 'PG_ROLE_MISMATCH')
            rows.append(check_result(rule, macro, status, reason, [obs['source_ref'] for obs in selected], actual=actual))
        if enabled_checks is not None and 'LIB_MACRO_FLAGS' not in enabled_checks:
            continue
        libs = [obs for obs in observations if obs['view'] == 'liberty']
        ready = reliable and bool(libs) and all(obs['object']['attributes'].get(key, {}).get('coverage') == 'PRESENT' for obs in libs for key in (flag_policy or {}))
        actual = [{key: obs['object']['attributes'].get(key, {}).get('value') for key in (flag_policy or {})} for obs in libs]
        status = 'NOT_APPLICABLE' if not flag_policy else 'NOT_CHECKED' if not ready else 'PASS' if all(item == flag_policy for item in actual) else 'FAIL'
        rows.append(check_result('LIB_MACRO_FLAGS', macro, status, 'NO_FLAG_POLICY' if not flag_policy else 'CONFIGURED_FLAG_POLICY', refs, actual=actual))
    return sorted(rows, key=lambda row: (row['macro_id'], row['check_id']))


def _equal(old, new, tolerance):
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return math.isclose(old, new, rel_tol=0, abs_tol=tolerance)
    if isinstance(old, dict) and isinstance(new, dict) and old.keys() == new.keys():
        return all(_equal(old[key], new[key], tolerance) for key in old)
    return old == new


def compare_bindings(old_bindings, new_bindings, *, tolerance_um=1e-6, enabled_checks=None, mapping=None):
    old = {row['macro_id']: row for row in old_bindings}
    new = {row['macro_id']: row for row in new_bindings}
    rows = []
    for macro in sorted(set(old) | set(new)):
        before, after = old.get(macro), new.get(macro)
        trusted = all(item and item['status'] in {'UNIQUE_EXACT', 'CONFIRMED'} for item in (before, after))
        observations = [{(obs['view'], obs['corner']): obs for obs in (item or {}).get('observations', [])} for item in (before, after)]
        for context in sorted(set(observations[0]) | set(observations[1]), key=lambda key: (key[0], key[1] or '')):
            left, right = (obs.get(context) for obs in observations)
            view, corner = context
            specs = [('LEF_SIZE_DELTA', key) for key in ('width_um', 'height_um', 'origin_um')] if view == 'lef' else []
            if view == 'lef':
                specs += [('LEF_PIN_DELTA', key) for key in ('pin_set', 'layers', 'geometry')]
            if view == 'verilog':
                specs += [('PORT_DECLARATION_DELTA', 'orientation')]
            if view == 'liberty':
                specs += [('LIB_PORT_DELTA', key) for key in ('signal_ports', 'pg_ports')]
            for rule, key in specs:
                if enabled_checks is not None and rule not in enabled_checks:
                    continue
                values, covered = [], trusted
                for obs in (left, right):
                    obj = obs['object'] if obs else {}
                    if rule == 'LEF_SIZE_DELTA':
                        attr = obj.get('attributes', {}).get(key, {})
                        values.append(attr.get('value'))
                        covered &= attr.get('coverage') == 'PRESENT' and attr.get('unit') == 'um'
                    elif rule == 'LIB_PORT_DELTA':
                        kinds = {'SIGNAL'} if key == 'signal_ports' else {'POWER', 'GROUND'}
                        coverage = 'port_set' if key == 'signal_ports' else 'pg_port_set'
                        aliases = ((mapping or {}).get('port_aliases') or {}).get(view, {})
                        ports = _ports(obs, kinds, aliases) if obs else None
                        covered &= (obj.get('coverage', {}).get(coverage) in {'PRESENT', 'ABSENT_VERIFIED'}
                                    and ports is not None and not any(port['kind'] == 'UNKNOWN' for port in obj.get('ports', [])))
                        if key == 'signal_ports' and ports is not None:
                            covered &= 'UNKNOWN' not in ports.values()
                        values.append(ports)
                    else:
                        ports = [normalize_port(port) for port in obj.get('ports', [])]
                        covered &= obj.get('coverage', {}).get('port_set') in {'PRESENT', 'ABSENT_VERIFIED'} and all(p['bits'] is not None for p in ports)
                        if key == 'geometry':
                            covered &= obj.get('coverage', {}).get('pin_geometry') == 'PRESENT'
                        if key == 'layers':
                            covered &= obj.get('coverage', {}).get('pin_layers') == 'PRESENT' and all(p['layers'] is not None for p in ports)
                        values.append(sorted(bit for port in ports for bit in (port['bits'] or [])) if key == 'pin_set' else
                                      {port['name']: port[key] for port in ports})
                status = 'UNKNOWN' if not covered else 'UNCHANGED' if _equal(*values, tolerance_um) else 'CHANGED'
                rows.append({'schema_version': 'semantic_delta.v1', 'macro_id': macro, 'view': view, 'corner': corner,
                    'check_id': rule, 'attribute': key, 'status': status, 'old': values[0], 'new': values[1],
                    'reason_code': 'ATTRIBUTES_COMPARED' if covered else 'INCOMPLETE_ATTRIBUTE_EVIDENCE',
                    'old_evidence': left['evidence'] if left else None, 'new_evidence': right['evidence'] if right else None})
    return rows
