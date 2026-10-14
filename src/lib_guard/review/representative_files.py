"""Human-selected file comparisons, independent of Web jobs and HTML."""

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import uuid

from lib_guard.atomic import atomic_write_json, file_lock
from lib_guard.review.update_notes import update_note_path
from lib_guard.view_types import canonical_file_type


def source_stamp(path):
    stat = Path(path).stat()
    return {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_representative_files(root, library, version):
    path = update_note_path(root, library, version).with_name('representative_files.json')
    if not path.exists():
        return []
    rows = list(_read(path).get('files', {}).values())
    for row in rows:
        expected = row.get('source_stamps') or {}
        row['freshness'] = '未记录文件状态，需人工核查'
        if expected:
            try:
                current = {side: source_stamp(row[side + '_file']) for side in ('old', 'new')}
                row['freshness'] = '文件状态未改变' if current == expected else '源文件已变化，需重新核查'
            except OSError:
                row['freshness'] = '源文件不可读，需重新核查'
    return sorted(rows, key=lambda row: row['file_type'])


def save_representative_file(root, library, version, out_dir, *, note='', updated_by='web', expected_generation=None):
    out = Path(out_dir)
    with file_lock(out.parent / f'.{out.name}.file_diff.lock'):
        return _save_representative_file(root, library, version, out, note=note,
                                         updated_by=updated_by, expected_generation=expected_generation)


def _save_representative_file(root, library, version, out_dir, *, note, updated_by, expected_generation):
    out = Path(out_dir)
    result = _read(out / 'pairwise_result.json')
    if expected_generation is not None and result.get('generated_at') != expected_generation:
        raise ValueError('这次任务的对比产物已被后续任务替换，请重新对比后加入详情页。')
    if result.get('status') != 'DONE' or result.get('result') not in {'SAME', 'DIFF'}:
        raise ValueError('只能加入已完成且可判读的文件对比；失败或不支持的结果不能加入详情页。')
    kind = canonical_file_type(result['file_type'])
    if kind == 'systemverilog':
        kind = 'verilog'
    if not kind.replace('_', '').isalnum():
        raise ValueError('无效的文件类型')
    semantic = _read(out / 'semantic_diff.json')
    index = update_note_path(root, library, version).with_name('representative_files.json')
    evidence_id = uuid.uuid4().hex
    destination = index.parent / 'representative' / kind / evidence_id
    row = {
        'file_type': kind, 'old_file': result['old_file'], 'new_file': result['new_file'],
        'base_version': result.get('base_version'), 'result': result['result'],
        'change_count': int(result.get('change_count') or 0),
        'change_counts': semantic.get('summary', {}).get('by_type', {}),
        'changes': [
            {'path': str(item.get('path') or '')[:300],
             'old': str(item.get('old', item.get('removed_samples', '')))[:160],
             'new': str(item.get('new', item.get('added_samples', '')))[:160]}
            for item in semantic.get('changes', [])[:6]
        ],
        'comparison_capability': result.get('comparison_capability') or {},
        'source_stamps': result.get('source_stamps') or {},
        'note': str(note).strip()[:1000], 'updated_by': str(updated_by).strip()[:80],
        'saved_at': datetime.now(timezone.utc).isoformat(),
        'evidence_id': evidence_id, 'evidence_dir': str(destination),
    }
    parsed_fields, unparsed_features = set(), set()
    for side in ('old', 'new'):
        extract_path = out / (side + '_extract.json')
        if extract_path.is_file():
            data = _read(extract_path).get('data') or {}
            parsed_fields.update(str(value) for value in data.get('parsed_fields', []))
            unparsed_features.update(str(value) for value in data.get('unparsed_features', []))
    row['parsed_fields'] = sorted(parsed_fields)
    row['unparsed_features'] = sorted(unparsed_features)
    # Preserve the existing report and its relative dependencies, not the Web job.
    destination.mkdir(parents=True)
    try:
        for source in out.iterdir():
            if source.is_file() and source.suffix in {'.html', '.md', '.json', '.zip'}:
                shutil.copy2(source, destination / source.name)
        if not (destination / 'index.html').is_file():
            raise ValueError('缺少深度对比 HTML 报告')
        if _read(destination / 'pairwise_result.json') != result:
            raise ValueError('保存过程中对比产物已变化，请重新加入详情页。')
        with file_lock(index.with_name('.representative_files.lock')):
            saved = _read(index) if index.exists() else {'schema_version': 'representative_files.v1', 'files': {}}
            saved['files'][kind] = row
            atomic_write_json(index, saved)
    except Exception:
        shutil.rmtree(destination)
        raise
    return next(item for item in load_representative_files(root, library, version) if item['file_type'] == kind)
