"""Adapt existing envelopes without rereading RAW or upgrading parser coverage."""

from copy import deepcopy

from lib_guard.view_types import canonical_file_type
from .model import FACT_SCHEMA_VERSION, attribute
from .normalize import normalize_port


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _coverage(data, field):
    declared = data.get('semantic_coverage', {})
    if (declared.get('schema_version') == 'semantic_parser_coverage.v1'
            and declared.get('validated') is True and declared.get('basis')
            and declared.get(field) in {'PRESENT', 'ABSENT_VERIFIED'}):
        return declared[field]
    return 'NOT_EXTRACTED'


def _port(name, record, kind, *, bus_chars=None):
    return {'name': name, 'kind': kind, 'direction': record.get('direction'), 'use': record.get('use'),
            'declared_range': record.get('declared_range'), 'width': record.get('width'),
            'bus_chars': bus_chars, 'layers': sorted(record['layers']) if isinstance(record.get('layers'), list) else None,
            'geometry': deepcopy(record.get('rects')), 'line': record.get('line_start')}


def adapt_result(result, evidence):
    view = canonical_file_type(result.get('file_type') or evidence['file_type'])
    if view == 'systemverilog':
        view = 'verilog'
    data = result.get('data') or {}
    status = str(result.get('status') or 'SKIPPED').upper()
    fact = {'schema_version': FACT_SCHEMA_VERSION, 'file_identity': deepcopy(evidence),
            'view': view, 'parse_status': status, 'variant': evidence.get('variant'),
            'corner': evidence.get('corner'), 'corner_status': 'CONFIRMED' if evidence.get('corner') else 'UNRESOLVED',
            'parser': {'name': result.get('parser_name'), 'version': result.get('parser_version'),
                       'status': status, 'result_ref': evidence.get('parser_result_ref')},
            'coverage': {'port_set': 'NOT_EXTRACTED'}, 'objects': [],
            'parse_limitations': deepcopy(data.get('parse_limitations', []))[:100],
            'parse_strategy': data.get('parse_strategy'), 'unparsed_features': data.get('unparsed_features', [])}
    if view not in {'lef', 'liberty', 'verilog'}:
        fact['parse_status'] = 'METADATA_ONLY' if view in {'db', 'gds', 'oas', 'ndm'} else 'UNSUPPORTED'
        return fact
    if status != 'PASS':
        fact['coverage']['port_set'] = 'FAILED' if status == 'FAILED' else 'NOT_EXTRACTED'
        return fact
    objects = []
    if view == 'lef':
        for name, macro in sorted(_mapping(data.get('macros')).items()):
            size, origin = macro.get('size') or {}, macro.get('origin')
            units_known = data.get('coordinate_units') == 'um' or isinstance(data.get('database_microns'), (int, float)) and data['database_microns'] > 0
            attrs = {key: attribute(size.get(axis) if units_known else None,
                                   'PRESENT' if units_known and size.get(axis) is not None else 'NOT_EXTRACTED', unit='um')
                     for key, axis in [('width_um', 'x'), ('height_um', 'y')]}
            attrs['origin_um'] = attribute(origin if units_known else None,
                'PRESENT' if units_known and origin is not None else 'NOT_EXTRACTED', unit='um')
            attrs['class'] = attribute(macro.get('class'), 'PRESENT' if macro.get('class') else 'NOT_EXTRACTED')
            attrs['pin_count'] = attribute(len(macro['pins']) if isinstance(macro.get('pins'), dict) else None,
                                           'PRESENT' if isinstance(macro.get('pins'), dict) else 'NOT_EXTRACTED')
            ports = [_port(pin, rec, {'POWER': 'POWER', 'GROUND': 'GROUND', 'SIGNAL': 'SIGNAL', 'CLOCK': 'SIGNAL'}.get(str(rec.get('use') or '').upper(), 'UNKNOWN'),
                           bus_chars=data.get('busbitchars')) for pin, rec in sorted(_mapping(macro.get('pins')).items())]
            geometry = _coverage(data, 'pin_geometry') if data.get('geometry_detail') == 'full' else 'NOT_EXTRACTED'
            if any(not isinstance(port['geometry'], list) for port in ports):
                geometry = 'NOT_EXTRACTED'
            if geometry != 'PRESENT':
                for port in ports:
                    port['geometry'] = None
            objects.append({'name': name, 'attributes': attrs, 'ports': ports, 'coverage': {
                'port_set': _coverage(data, 'port_set') if isinstance(macro.get('pins'), dict) else 'NOT_EXTRACTED',
                'pg_port_set': _coverage(data, 'pg_port_set') if isinstance(macro.get('pins'), dict) else 'NOT_EXTRACTED',
                'pin_layers': _coverage(data, 'pin_layers') if all(p['layers'] is not None for p in ports) else 'NOT_EXTRACTED',
                'pin_geometry': geometry}, 'line': macro.get('line_start')})
    elif view == 'liberty':
        for library, lib in sorted(_mapping(data.get('libraries')).items()):
            for name, cell in sorted(_mapping(lib.get('cells')).items()):
                attrs = {key: attribute(cell.get(key), 'PRESENT' if cell.get(key) is not None else 'NOT_EXTRACTED')
                         for key in ('area', 'is_macro', 'is_pad')}
                ports = [_port(pin, rec, 'SIGNAL') for pin, rec in sorted(_mapping(cell.get('pins')).items())
                         if str(rec.get('direction') or '').lower() != 'internal']
                ports += [_port(pin, rec, 'GROUND' if 'ground' in str(rec.get('pg_type') or '').lower()
                               else 'POWER' if 'power' in str(rec.get('pg_type') or '').lower() else 'UNKNOWN')
                          for pin, rec in sorted(_mapping(cell.get('pg_pins')).items())]
                objects.append({'name': name, 'library': library, 'attributes': attrs, 'ports': ports,
                    'coverage': {'port_set': _coverage(data, 'port_set') if isinstance(cell.get('pins'), dict) else 'NOT_EXTRACTED',
                                 'pg_port_set': _coverage(data, 'pg_port_set') if isinstance(cell.get('pg_pins'), dict) else 'NOT_EXTRACTED'},
                    'line': cell.get('line_start')})
    else:
        for name, module in sorted(_mapping(data.get('modules')).items()):
            ports = [_port(pin, rec, 'SIGNAL') for pin, rec in sorted(_mapping(module.get('ports')).items())]
            for port in ports:
                port['range_required'] = True
            complete = _coverage(data, 'port_set') if isinstance(module.get('ports'), dict) else 'NOT_EXTRACTED'
            if any(normalize_port(port)['bits'] is None for port in ports):
                complete = 'NOT_EXTRACTED'
            objects.append({'name': name, 'attributes': {}, 'ports': ports,
                            'coverage': {'port_set': complete, 'pg_port_set': 'NOT_APPLICABLE'}})
    for obj in objects:
        obj['local_id'] = f"{view}:{obj.get('library', '')}:{obj['name']}"
        obj['kind'] = 'macro'
    fact['objects'] = objects
    fact['coverage']['port_set'] = 'PRESENT' if objects and all(obj['coverage']['port_set'] in {'PRESENT', 'ABSENT_VERIFIED'} for obj in objects) else 'NOT_EXTRACTED'
    return fact
