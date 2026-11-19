"""Create a new isolated RAW/Formal fixture and verify real link observations."""
import argparse
import json
import os
from pathlib import Path

from ai_lib_qor.application.data_query import LibraryDataQuery
from ai_lib_qor.application.effective_json import create_revision
from ai_lib_qor.application.simple_sources import simple_raw
from ai_lib_qor.sources.delivery_builder import build_delivery
from ai_lib_qor.sources.formal_sync import sync_formal
from ai_lib_qor.versions.store import write_atomic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, help='不存在的新目录，仅用于模拟验收')
    args = parser.parse_args()
    root = Path(args.out).absolute()
    root.mkdir(parents=True, exist_ok=False)
    work = root / 'work'; work.mkdir()
    folder = work / 'libraries' / 'sample_vendor' / 'sample_library'
    folder.mkdir(parents=True)
    nl = root / 'formal' / 'NL_TEST'; nl.mkdir(parents=True)
    paths = ['LEF/core.lef', 'LIB/NLDM/core_ff.lib', 'LIB/NLDM/core_ss.lib', 'LIB/NLDM/core_tt.lib']
    records = []
    for number, version in ((1, 'V05'), (2, 'V06')):
        raw = root / 'raw' / version; raw.mkdir(parents=True)
        selected = paths if number == 1 else paths[:2]
        mapping = {}
        for rel in selected:
            file = raw / rel; file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('MACRO CORE\n SIZE 10 BY 20 ;\n PIN A\n DIRECTION INPUT ;\n END A\nEND CORE\n' if rel.endswith('.lef')
                            else 'library(sample) { cell(CORE) { pin(A) { direction : input; } } }', encoding='utf-8')
            mapping[rel] = {'file_key': 'sample:' + rel.replace('/', ':')}
        metadata = {'delivery_id': 'delivery_%03d' % number, 'vendor_id': 'sample_vendor',
                    'source_library_id': 'sample_library', 'supplier_version': version,
                    'delivery_order': number, 'received_at': '2026-11-19T00:00:00Z', 'package_mode': 'UNKNOWN'}
        record = build_delivery(raw, metadata, mapping)
        write_atomic(folder / ('delivery_%03d.json' % number), record, immutable=True)
        records.append(record)
    for rel in paths:
        link = nl / rel; link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(os.path.relpath(root / 'raw' / 'V05' / rel, link.parent))
    observation = sync_formal(root / 'runs', {'formal_nl_id': 'NL_TEST', 'root': str(nl)}, records, work)
    if observation['status'] != 'COMPLETE' or observation['snapshot_action'] != 'CREATED':
        raise ValueError('正式快照未成功生成: ' + json.dumps(observation, ensure_ascii=False))
    snap = json.loads((folder / 'formal_NL_TEST_001.json').read_text(encoding='utf-8'))
    for entry in snap['linked_files']:
        link = nl / entry['link_path']; target = link.resolve(strict=True)
        expected = (root / 'raw' / 'V05' / entry['link_path']).resolve(strict=True)
        if (os.readlink(link) != entry['link_target'] or target != expected or
            entry['resolved_path'] != str(expected) or entry['source_match'] != 'MATCHED_RAW' or
            entry['source_ref']['delivery_id'] != records[0]['delivery_id']):
            raise ValueError('正式链接与 RAW 记录不一致: ' + entry['link_path'])
    query = LibraryDataQuery(work, root / 'runs')
    owner = {'type': 'SOURCE_LIBRARY', 'id': 'sample_library'}
    old = create_revision(simple_raw(query, 'sample_vendor', 'sample_library', 'V05'), owner=owner,
                          revision='rev_0001', created_at='2026-11-19T00:00:00Z', include_views=['LEF', 'LIBERTY'])
    new = create_revision(simple_raw(query, 'sample_vendor', 'sample_library', 'V06'), owner=owner,
                          revision='rev_0002', created_at='2026-11-19T00:00:00Z', include_views=['LEF', 'LIBERTY'], parent=old)
    for number, record in ((1, old), (2, new)):
        write_atomic(folder / ('effective_sample_library_%03d.json' % number), record, immutable=True)
    query = LibraryDataQuery(work, root / 'runs')
    comparisons = {rev: query.compare_formal_vs_effective('sample_vendor', 'sample_library', 'NL_TEST',
                   observation['snapshot_id'], 'sample_library', rev) for rev in ('rev_0001', 'rev_0002')}
    result = {'description': '隔离模拟数据；Formal 同步时实际读取链接并核验目标。查询结果只表示归档记录关系。',
              'links_verified_at_sync': len(snap['linked_files']), 'formal_snapshot_id': observation['snapshot_id'],
              'comparisons': comparisons}
    write_atomic(root / 'verification.json', result, immutable=True)
    print(json.dumps({'output': str(root), 'links_verified_at_sync': len(snap['linked_files']),
                      'formal_snapshot_id': observation['snapshot_id']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
