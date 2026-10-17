"""Reproducible small real-parser rehearsal, never releases or accepts data."""

import hashlib
import json
from pathlib import Path
import time

from lib_guard.catalog.runtime import load_catalog_view
from lib_guard.effective.manifest import build_effective_manifest
from lib_guard.semantic.runner import run_semantic_review
from lib_guard.test.test_release_levels import _scan
from lib_guard.test.semantic_fixture import write_json

LEF = '''VERSION 5.8 ;
BUSBITCHARS "[]" ;
UNITS
DATABASE MICRONS 1000 ;
END UNITS
MACRO M
SIZE 1000 BY 2000 ;
ORIGIN 0 0 ;
PIN CLK
DIRECTION INPUT ;
USE SIGNAL ;
END CLK
PIN RESET
DIRECTION INPUT ;
USE SIGNAL ;
END RESET
END M
'''
LIB = '''library (L) {
cell (M) {
is_macro : true;
area : 12;
pin (CLK) {
direction : input;
}
pin (RESET) {
direction : input;
}
}
}
'''
RTL = '''module M(CLK, RESET);
input CLK;
input RESET;
endmodule
'''


def rehearse(out):
    root = Path(out)
    catalog = {'libraries': [{'library_id': 'ip/demo', 'library_name': 'demo', 'library_type': 'ip', 'versions': []}]}
    for version, files in [('full', {'lef/M.lef': LEF, 'lib/M.lib': LIB, 'rtl/M.v': RTL}),
                           ('fix', {'lef/M.lef': LEF.replace('SIZE 1000', 'SIZE 1100').replace('PIN RESET\nDIRECTION INPUT ;\nUSE SIGNAL ;\nEND RESET\n', '')})]:
        raw, scan = root / 'raw' / version, root / 'scan' / version
        for rel, text in files.items():
            path = raw / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        _scan(raw, scan, mode='scan', version=version, parse_file_types=['lef', 'liberty', 'verilog'])
        meta = json.loads((scan / 'scan_meta.json').read_text())
        catalog['libraries'][0]['versions'].append({'version_id': version, 'raw_path': str(raw.resolve()),
            'scan': {'scan_dir': str(scan.resolve()), 'snapshot_identity': meta['snapshot_identity']}})
    catalog_path, old_path, new_path = root / 'catalog.json', root / 'accepted.json', root / 'candidate.json'
    write_json(catalog_path, catalog)
    write_json(old_path, build_effective_manifest(catalog, 'demo', 'full', [], effective_id='old'))
    write_json(new_path, build_effective_manifest(catalog, 'demo', 'full', [('fix', ['lef'])], effective_id='candidate'))
    for name in ('catalog_runtime.json', 'current_effective.json', 'release_manifest.json'):
        write_json(root / name, {'unchanged': name})
    protected = [catalog_path, old_path, new_path] + [root / name for name in ('catalog_runtime.json', 'current_effective.json', 'release_manifest.json')]
    protected += list((root / 'raw').rglob('*.*'))
    def digests():
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
    before = digests()
    started = time.perf_counter()
    result = run_semantic_review(new_path, catalog_path, root / 'review', base_manifest_path=old_path)
    elapsed = time.perf_counter() - started
    audit = {'mutations': [] if before == digests() else ['UPSTREAM_CHANGED'], 'elapsed_seconds': elapsed,
             'protected_sha256': before, 'summary': result['summary']}
    write_json(root / 'audit.json', audit)
    return result, audit


def existing_asap7(catalog_path, out):
    root = Path(out)
    catalog = load_catalog_view(catalog_path)
    library = catalog['libraries'][0]
    library_id = library['library_id']
    ids = [row['version_id'] for row in library['versions']]
    for name, version in [('old', sorted(ids)[0]), ('new', sorted(ids)[-1])]:
        write_json(root / (name + '.json'), build_effective_manifest(catalog, library_id, version, [], effective_id=name))
    protected = [Path(catalog_path), Path(catalog_path).with_name('catalog_runtime.json')]
    protected += [path for path in Path(catalog_path).parent.rglob('current_effective.json')]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in protected if path.exists()}
    started = time.perf_counter()
    result = run_semantic_review(root / 'new.json', catalog_path, root / 'review', base_manifest_path=root / 'old.json')
    audit = {'elapsed_seconds': time.perf_counter() - started, 'protected_sha256': before,
             'mutations': [path for path, digest in before.items() if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest]}
    write_json(root / 'audit.json', audit)
    return result, audit
