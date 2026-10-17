"""Reproducible LEF-first acceptance; optional Cadence Reader is a separate oracle."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import time

from lib_guard.atomic import atomic_write_json
from lib_guard.effective.manifest import build_effective_manifest
from lib_guard.scan.parsers.lef import parse_lef_data_file
from lib_guard.semantic.runner import run_semantic_review
from lib_guard.semantic.results import load_review_snapshot
from lib_guard.test.test_release_levels import _scan
from lib_guard.test.test_lef_check_facts import LEF


def cross_validate(paths):
    from lefdef import C_LefReader
    reports = []
    for path in paths:
        reader = C_LefReader()
        native = reader.read(str(path.resolve()))
        ours = parse_lef_data_file(path)
        expected = {}
        for i in range(native.c_num_macros):
            macro = native.c_macros[i]
            expected[macro.c_name.decode()] = {'size': [macro.c_size_x, macro.c_size_y],
                'class': macro.c_class.decode() if macro.c_class else None, 'pin_count': macro.c_num_pins}
        assert set(expected) == set(ours['macros']), str(path)
        for name, row in expected.items():
            actual = ours['macros'][name]
            assert actual['class'] == row['class'], (path, name, 'class')
            assert len(actual['pins']) == row['pin_count'], (path, name, 'pin_count')
            assert all(abs(actual['size'][axis] - value) <= 1e-6 for axis, value in zip(('x', 'y'), row['size'])), (path, name, 'size')
        geometry_checked = ours['semantic_coverage']['pin_geometry'] == 'PRESENT'
        def rect_value(rect):
            return (rect.c_layer.decode(), rect.c_xl, rect.c_yl, rect.c_xh, rect.c_yh)
        for i in range(native.c_num_macros):
            macro = native.c_macros[i]
            actual = ours['macros'][macro.c_name.decode()]
            for j in range(macro.c_num_pins):
                pin = macro.c_pins[j]
                actual_pin = actual['pins'][pin.c_name.decode()]
                assert actual_pin['direction'] == (pin.c_direction.decode() if pin.c_direction else None)
                assert actual_pin['use'] == (pin.c_use.decode() if pin.c_use else None)
                if geometry_checked:
                    assert actual_pin['port_count'] == pin.c_num_ports
                    for k in range(pin.c_num_ports):
                        port = pin.c_ports[k]
                        rectangles = sorted(rect_value(port.c_rects[n]) for n in range(port.c_num_rects))
                        observed = sorted((r['layer'],r['x1'],r['y1'],r['x2'],r['y2']) for r in actual_pin['rects'] if r['port_index'] == k)
                        assert observed == rectangles, (path, pin.c_name, 'PORT geometry')
            if ours['semantic_coverage']['obs_geometry'] == 'PRESENT':
                expected_obs = sorted(rect_value(macro.c_obs.c_rects[n]) for n in range(macro.c_obs.c_num_rects))
                observed_obs = sorted((r['layer'],r['x1'],r['y1'],r['x2'],r['y2']) for r in actual['obs'])
                assert observed_obs == expected_obs, (path, name, 'OBS')
        reports.append({'source': str(path), 'reader': 'Cadence LEF via lefdef 0.6.0',
            'macro_count': len(expected), 'pin_count': sum(row['pin_count'] for row in expected.values()),
            'name_size_class_pin_count_match': True, 'our_coverage': ours['semantic_coverage'],
            'pin_names_direction_use_match': True,
            'rect_port_groups_and_obs': 'PASS' if geometry_checked else 'NOT_CHECKED_UNSUPPORTED_SYNTAX',
            'samples': list(expected.items())[:3]})
    return reports


def effective_case(root, old_files, new_files):
    catalog = {'libraries': [{'library_id': 'ip/lef_acceptance', 'library_name': 'demo', 'versions': []}]}
    for version, files in [('full', old_files), ('fix', new_files)]:
        raw, scan = root / 'raw' / version, root / 'scan' / version
        for relpath, text in files.items():
            path = raw / relpath
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        _scan(raw, scan, mode='scan', version=version, parse_file_types=['lef'])
        meta = json.loads((scan / 'scan_meta.json').read_text())
        catalog['libraries'][0]['versions'].append({'version_id': version, 'raw_path': str(raw),
            'scan': {'scan_dir': str(scan), 'snapshot_identity': meta['snapshot_identity']}})
    catalog_path, old, new = root / 'catalog.json', root / 'old.json', root / 'new.json'
    atomic_write_json(catalog_path, catalog)
    atomic_write_json(old, build_effective_manifest(catalog, 'demo', 'full', []))
    atomic_write_json(new, build_effective_manifest(catalog, 'demo', 'full', [('fix', ['lef'])]))
    protected = [catalog_path, old, new] + list((root / 'raw').rglob('*.lef'))
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
    started = time.perf_counter()
    result = run_semantic_review(new, catalog_path, root / 'review', base_manifest_path=old, profile_name='lef_basic')
    assert load_review_snapshot(root / 'review') == result
    mutations = [path for path, digest in before.items() if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest]
    assert not mutations, mutations
    return result, {'elapsed_seconds': round(time.perf_counter()-started, 4),
        'macro_states': dict(Counter(row['status'] for row in result['index']['macro_index']['macros'])),
        'delta_counts': result['summary']['delta_counts'], 'upstream_mutations': mutations,
        'snapshot_roundtrip_equal': True,
        'markdown': str(root / 'review' / result['summary']['artifacts']['markdown'])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    out = Path(args.out).resolve()
    fixture_root = Path(__file__).resolve().parents[3] / 'tests/fixtures/raw'
    paths = [next(fixture_root.rglob('fakeram7_128x64.lef')),
             next(fixture_root.rglob('fakeram7_64x256.lef')),
             next(fixture_root.rglob('NangateOpenCellLibrary.macro.lef'))]
    cross = cross_validate(paths)
    cases = []
    old_real = {path.name: path.read_text() for path in paths}
    new_real = dict(old_real)
    source = paths[0].name
    new_real[source] = re.sub(r'(SIZE\s+)([\d.]+)(\s+BY)',
        lambda m: m[1] + str(float(m[2]) + 0.1) + m[3], new_real[source], count=1)
    real_result, audit = effective_case(out / 'real_multi_file', old_real, new_real)
    assert any(row['attribute'] == 'size_um' and row['status'] == 'CHANGED' for row in real_result['delta'])
    cases.append({'name': 'real SRAM + multi Macro LEF', **audit})
    for name, text, attribute, expected in [
        ('direction', LEF.replace('INPUT', 'OUTPUT'), 'interface', 'CHANGED'),
        ('port_groups', LEF.replace('RECT 2 2 3 3 ;', 'END\nPORT\nLAYER M1 ;\nRECT 2 2 3 3 ;'), 'pin_geometry', 'CHANGED'),
        ('same_length_geometry', LEF.replace('RECT 0 0 1 1', 'RECT 0 0 2 1'), 'pin_geometry', 'CHANGED'),
        ('obs', LEF.replace('RECT 1 1 2 2', 'RECT 1 1 3 2'), 'obstructions', 'CHANGED'),
        ('comment_only', '# comment\n' + LEF, 'interface', 'UNCHANGED'),
        ('unsupported_polygon', LEF.replace('RECT 0 0 1 1 ;', 'POLYGON 0 0 1 0 1 1 ;'), 'pin_geometry', 'INCOMPLETE'),
        ('truncated', LEF.split('END A')[0], 'pin_geometry', 'INCOMPLETE'),
    ]:
        result, audit = effective_case(out / name, {'M.lef': LEF}, {'M.lef': text})
        row = next(row for row in result['delta'] if row['attribute'] == attribute)
        assert row['status'] == expected, (name, row)
        cases.append({'name': name, 'expected_attribute': attribute, 'expected_status': expected, **audit})
    report = {'reader_cross_validation': cross, 'cases': cases,
              'ucie_basis': 'controlled UCIE-shaped fixture; proprietary UCIE deliveries unavailable',
              'geometry_scope': 'RECT with PORT grouping; unsupported constructs remain INCOMPLETE'}
    atomic_write_json(out / 'validation.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
