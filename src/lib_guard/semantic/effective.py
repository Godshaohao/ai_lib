"""Resolve final Effective selections to exact, fresh per-file scan evidence."""

import json
import math
from pathlib import Path

from lib_guard.effective.manifest import validate_effective_manifest, canonical_relpath
from lib_guard.scan.report import load_parser_results
from lib_guard.view_types import canonical_file_type
from .adapters import adapt_result


class ScanGenerationMismatch(ValueError):
    pass


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _result_source(result, root):
    file = result.get('file')
    absolute = result.get('abs_path')
    if not file:
        return None
    path = Path(file) if Path(file).is_absolute() else root / file
    if absolute and Path(absolute).resolve() != path.resolve():
        return None
    return path.resolve()


def _index_scan(scan):
    meta = _read(scan / 'scan_meta.json')
    inventory = _read(scan / 'file_inventory.json')
    tasks = _read(scan / 'parser_manifest.json')
    root = Path(meta['root_path'])
    if (not meta.get('scan_id') or not isinstance(inventory, dict)
            or inventory.get('scan_id') != meta['scan_id'] or tasks.get('scan_id') != meta['scan_id']
            or (inventory.get('root_path') and Path(inventory['root_path']).resolve() != root.resolve())
            or (inventory.get('snapshot_identity') and inventory['snapshot_identity'] != meta.get('snapshot_identity'))
            or (inventory.get('input_fingerprint') and inventory['input_fingerprint'] != meta.get('input_fingerprint'))):
        raise ScanGenerationMismatch('Inventory / parser manifest do not belong to selected scan generation')
    records = inventory.get('files', []) if isinstance(inventory, dict) else inventory
    inventory_index, parser_index = {}, {}
    task_index = {}
    for item in tasks.get('files', []):
        key = (item.get('file'), canonical_file_type(item.get('file_type')))
        task_index.setdefault(key, []).extend(item.get('parser_tasks', []))
    for record in records:
        absolute = (root / record['path']).resolve()
        if not record.get('abs_path') or Path(record['abs_path']).resolve() == absolute:
            inventory_index.setdefault(absolute, []).append(record)
    for ref, payload in load_parser_results(scan).items():
        if not isinstance(payload, dict):
            continue
        current_tasks = task_index.get((payload.get('file'), canonical_file_type(payload.get('file_type'))), [])
        if not any(task.get('result_path') == ref and task.get('parser_name') == payload.get('parser_name')
                   and task.get('parser_version') and task['parser_version'] == payload.get('parser_version')
                   and (not task.get('status') or str(task['status']).upper() == str(payload.get('status') or '').upper())
                   and str(task.get('result_status') or task.get('status') or '').upper() == str(payload.get('status') or '').upper()
                   for task in current_tasks):
            continue
        absolute = _result_source(payload, root)
        if absolute is not None:
            key = (absolute, canonical_file_type(payload.get('file_type')))
            parser_index.setdefault(key, []).append((ref, payload))
    return meta, inventory_index, parser_index


def resolve_effective_facts(manifest, scan_context, *, facts_store=None, check_facts=None):
    validation = validate_effective_manifest(manifest)
    result = {'schema_version': 'semantic_effective_index.v1', 'library_id': manifest.get('library_id'),
        'effective_id': manifest.get('effective_id'), 'effective_digest': validation['digest'],
        'effective_integrity': validation['integrity_status'], 'evidence_trust': validation['evidence_trust'],
        'files': [], 'facts': [], 'advisory': True}
    libraries = [lib for lib in scan_context.get('libraries', []) if manifest.get('library_id') in
                 {lib.get('library_id'), lib.get('library_name')}]
    versions = libraries[0].get('versions', []) if len(libraries) == 1 else []
    components = {item['version_id']: item for item in manifest.get('components', [])}
    cache = {}
    for rel, selected in sorted((manifest.get('effective_files') or {}).items()):
        row = {'effective_relpath': rel, 'source_version': selected.get('source_version'),
               'source_relpath': selected.get('source_path'), 'file_type': canonical_file_type(selected.get('file_type')),
               'fact_status': 'NOT_CHECKED', 'reason_code': 'INVALID_EFFECTIVE_IDENTITY'}
        result['files'].append(row)
        if not validation['valid'] or validation['evidence_status'] != 'TRUSTED' or rel in manifest.get('tombstones', {}):
            continue
        source_version = selected.get('source_version')
        matches = [version for version in versions if version.get('version_id') == source_version]
        if len(matches) != 1 or source_version not in components:
            row['reason_code'] = 'SOURCE_VERSION_UNRESOLVED'
            continue
        version = matches[0]
        scan_dir = (version.get('scan') or {}).get('scan_dir')
        if not scan_dir:
            row['reason_code'] = 'SCAN_MISSING'
            continue
        try:
            if source_version not in cache:
                try:
                    cache[source_version] = _index_scan(Path(scan_dir))
                except (OSError, ValueError, KeyError, TypeError) as error:
                    cache[source_version] = error
            if isinstance(cache[source_version], Exception):
                raise cache[source_version]
            meta, inventory_index, parser_index = cache[source_version]
            root = Path(selected['raw_root']).resolve()
            raw_version = Path(version.get('raw_path') or version.get('version_path') or '').resolve()
            component = components[source_version]
            snapshot = ((meta.get('snapshot_identity') or {}).get('digest') if component.get('identity_source') == 'snapshot_identity'
                        else (meta.get('input_fingerprint') or {}).get('hash'))
            names = {libraries[0].get('library_id'), libraries[0].get('library_name')}
            if (meta.get('release_version') != source_version or meta.get('library_name') not in names
                    or Path(meta.get('root_path') or '').resolve() != root or root != raw_version
                    or snapshot != component.get('snapshot_digest')
                    or meta.get('status') not in {'PASS', 'PASS_WITH_WARNING'}):
                row['reason_code'] = 'SCAN_SOURCE_MISMATCH'
                continue
            source = Path(selected['source_path'])
            if not source.is_absolute() and '..' in source.parts:
                row['reason_code'] = 'SOURCE_PATH_MISMATCH'
                continue
            absolute = source.resolve() if source.is_absolute() else (root / source).resolve()
            if not absolute.is_relative_to(root):
                row['reason_code'] = 'SOURCE_OUTSIDE_VERSION'
                continue
            records = [record for record in inventory_index.get(absolute, [])
                       if canonical_relpath(record['path']) == rel
                       and (source.is_absolute() or Path(record['path']).as_posix() == source.as_posix())]
            if len(records) != 1 or canonical_file_type(records[0].get('file_type')) != row['file_type']:
                row['reason_code'] = 'INVENTORY_SOURCE_MISMATCH'
                continue
            record = records[0]
            stamp = absolute.stat()
            if (record.get('size_bytes') != stamp.st_size or record.get('mtime') is None
                    or not math.isclose(record['mtime'], stamp.st_mtime, rel_tol=0, abs_tol=1e-6)):
                row['reason_code'] = 'STALE_SOURCE_METADATA'
                continue
            matches = [(ref, payload) for ref, payload in parser_index.get((absolute, row['file_type']), [])
                       if payload.get('file') == record['path'] or payload.get('file') == str(root / record['path'])]
            if len(matches) != 1:
                row['reason_code'] = 'PARSER_RESULT_AMBIGUOUS' if matches else 'PARSER_RESULT_MISSING'
                continue
            ref, payload = matches[0]
            reference = str(Path(scan_dir) / ref) if str(ref).startswith('parser_results/') else str(Path(scan_dir) / 'parser_results.json') + '#' + str(ref)
            evidence = {'library_id': manifest['library_id'], 'source_version': source_version,
                'effective_relpath': rel, 'source_relpath': record['path'], 'source_path': str(absolute),
                'file_type': row['file_type'], 'scan_dir': str(scan_dir), 'scan_id': meta.get('scan_id'),
                'snapshot_digest': snapshot, 'parser_result_ref': reference,
                'parser_name': payload.get('parser_name'), 'parser_version': payload.get('parser_version'),
                'source_stamp': {'size_bytes': stamp.st_size, 'mtime_ns': stamp.st_mtime_ns},
                'freshness': 'METADATA_MATCH', 'content_verified': False}
            # Corner/variant must be explicit scan evidence, never filename hints.
            context = (payload.get('semantic_context') or {})
            if context.get('confirmed') is True and context.get('basis'):
                evidence['semantic_context'] = dict(context)
            for key in ('corner', 'variant', 'mode'):
                if context.get('confirmed') is True and context.get('basis'):
                    evidence[key] = context.get(key)
            if check_facts is not None:
                check_facts.add(evidence, payload)
            fact = facts_store.get_or_adapt(payload, evidence) if facts_store is not None else adapt_result(payload, evidence)
            result['facts'].append(fact)
            row.update(fact_status='AVAILABLE', reason_code='EXACT_SOURCE_METADATA_MATCH',
                       parser_result_ref=reference, parse_status=fact['parse_status'], evidence=evidence)
        except (OSError, ValueError, KeyError, TypeError) as error:
            row.update(reason_code='SCAN_GENERATION_MISMATCH' if isinstance(error, ScanGenerationMismatch) else 'EVIDENCE_UNREADABLE', detail=str(error))
    return result
