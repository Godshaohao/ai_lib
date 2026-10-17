"""Small controlled evidence fixtures; never production completeness claims."""

import json
from pathlib import Path
from lib_guard.effective.manifest import build_effective_manifest
from lib_guard.test.test_semantic_adapter import parser_result


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


class SemanticFixture:
    def __init__(self, root):
        self.root = Path(root)
        self.catalog = {'libraries': [{'library_id': 'ip/demo', 'library_name': 'demo', 'versions': []}]}

    def version(self, name, views=('lef', 'liberty', 'verilog'), *, legacy=False, width=1000, complete=True):
        raw = self.root / 'raw' / name
        scan = self.root / 'scan' / name
        inventory, results, tasks = [], {}, []
        for view in views:
            rel = view + '/M.' + {'liberty': 'lib', 'verilog': 'v'}.get(view, view)
            path = raw / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name + '-' + view)
            stamp = path.stat()
            inventory.append({'path': rel, 'abs_path': str(path), 'file_type': view,
                              'size_bytes': stamp.st_size, 'mtime': stamp.st_mtime})
            result = parser_result(view, complete=complete)
            result.update(file=rel, abs_path=str(path))
            if view == 'lef':
                result['data']['macros']['M']['size']['x'] = width
                result['data']['macros']['M']['pins']['VDD'] = {'use': 'POWER'}
            key = 'parser_results/' + view + '/result.json'
            results[key] = result
            tasks.append({'file': rel, 'file_type': view, 'parser_tasks': [{'result_path': key,
                'parser_name': result['parser_name'], 'parser_version': result['parser_version'], 'result_status': result['status']}]})
            if not legacy:
                write_json(scan / key, result)
        snapshot = {'digest': 'sha256:' + name, 'strength': 'full'}
        write_json(scan / 'scan_meta.json', {'release_version': name, 'root_path': str(raw),
            'library_name': 'demo', 'snapshot_identity': snapshot, 'status': 'PASS', 'scan_id': name})
        write_json(scan / 'file_inventory.json', {'files': inventory, 'scan_id': name, 'root_path': str(raw)})
        write_json(scan / 'parser_manifest.json', {'scan_id': name, 'files': tasks})
        if legacy:
            write_json(scan / 'parser_results.json', results)
        version = {'version_id': name, 'raw_path': str(raw), 'scan': {'scan_dir': str(scan), 'snapshot_identity': snapshot}}
        self.catalog['libraries'][0]['versions'].append(version)
        return version

    def manifest(self, includes=(), *, delete_files=None):
        return build_effective_manifest(self.catalog, 'demo', 'full', list(includes), delete_files=delete_files)
