"""Immutable RAW delivery ingestion from a successful metadata scan.

Auto-ingest means automatic source history, NOT automatic IP adoption. It must
not silently convert a guessed package into a confirmed FULL/INCREMENTAL scope.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from .classifier_adapter import classify_observation
from .source_discovery import natural_version_key
from .delivery_builder import build_delivery
from .update_scan import scan_library
from ai_lib_qor.versions.store import locked, write_atomic
from ai_lib_qor.sources.registration import SAFE


def auto_ingest(work, source, scan, *, classified=None):
    vendor, library = source['vendor_id'], source['source_library_id']
    if not all(SAFE.fullmatch(v) and v not in ('.', '..') for v in (vendor, library)):
        raise ValueError('来源标识不安全')
    raw = Path(source['root']).resolve(strict=True)
    work = Path(work).resolve(strict=True)
    if work.is_relative_to(raw):
        raise ValueError('工作目录不能位于 RAW 内')
    if (scan.get('root'), scan.get('vendor_id'), scan.get('source_library_id')) != (str(raw), vendor, library):
        raise ValueError('扫描与配置不匹配')
    classified = classified if classified is not None else classify_observation(scan, source)
    paths = classified['version_paths']
    result = {'created': 0, 'duplicates': 0, 'modified': 0, 'blocked': 0,
              'files': len(classified['files']), 'versions_discovered': len(paths),
              'unresolved': sum(r['classification'] == 'UNRESOLVED' for r in classified['files']),
              'reasons': list(classified.get('warnings', []))}
    if not paths:
        result['blocked'] += 1
        result['reasons'].append('没有识别出交付版本目录，RAW 文件已保留在扫描历史')
        from ai_lib_qor.application.latest_pointers import refresh_library
        refresh_library(work,vendor,library)
        return result
    from .layout import library_folder, evidence_path, next_filename
    from ai_lib_qor.application.source_repository import SourceRepository
    parent = library_folder(work, vendor, library)
    with locked(parent):
        existing = [(x['record'],x['evidence'] or {}) for x in SourceRepository(work).deliveries()
                    if (x['record']['vendor_id'],x['record']['source_library_id'])==(vendor,library)]
        explicit_order = source.get('delivery_orders', {})
        if not isinstance(explicit_order, dict):
            raise ValueError('delivery_orders 必须是字典')
        if any(type(order) is not int or order < 0 for order in explicit_order.values()):
            raise ValueError('delivery_orders 只能提供非负整数')
        for version in sorted(paths, key=lambda v: (0, explicit_order[v]) if v in explicit_order
                              else (1, natural_version_key(v))):
            relative = paths[version]
            if not SAFE.fullmatch(version) or version in ('.', '..'):
                result['blocked'] += 1
                result['reasons'].append(f'{version}: 版本标识不安全')
                continue
            candidate = raw / relative
            path_parts = Path(relative).parts
            has_link = any(raw.joinpath(*path_parts[:i]).is_symlink() for i in range(1, len(path_parts) + 1))
            if has_link or not candidate.resolve().is_relative_to(raw) or not candidate.is_dir():
                result['blocked'] += 1
                result['reasons'].append(f'{version}: 版本目录不可用')
                continue
            rows = [x for x in classified['files'] if x['supplier_version'] == version]
            if not rows:
                result['blocked'] += 1
                result['reasons'].append(f'{version}: 无可确认文件或版本范围存在歧义')
                continue
            prefix = Path(relative).as_posix().rstrip('/') + '/'
            expected = {x['path'][len(prefix):]: (x['size'], x['mtime_ns']) for x in rows}
            prior = [(a, b) for a, b in existing if a['supplier_version'] == version and a['source_root'] == str(candidate.resolve())]
            if prior:
                if any(
                    ({x['path']: (x['size'], x['mtime_ns']) for x in evidence['files']} == expected)
                    for _, evidence in prior if isinstance(evidence.get('files'), list)
                ):
                    result['duplicates'] += 1
                else:
                    result['modified'] += 1
                    result['reasons'].append(f'{version}: RAW 原地变化；旧内容未保存，历史路径不可保证重现，请作为新交付处理')
                continue

            def observed():
                current = scan_library(candidate, vendor, library, metadata_only=True)
                return current, {f['path']: (f['size'], f['mtime_ns']) for f in current['files']}

            before_scan, before = observed()
            if before_scan['status'] != 'COMPLETE' or expected != before:
                result['blocked'] += 1
                result['reasons'].append(f'{version}: 扫描后文件变化或范围不完整')
                continue
            mapping = {r['relative_in_version']: {
                'file_key': r['file_key'], 'view': r['view'],
                'corner': r['corner'], 'mode': r['mode']
            } for r in rows}
            desired_order = explicit_order.get(version)
            existing_orders = {a['delivery_order'] for a, _ in existing}
            if desired_order is not None and (type(desired_order) is not int or desired_order < 0 or desired_order in existing_orders):
                result['blocked'] += 1
                result['reasons'].append(f'{version}: 配置的交付顺序非法或冲突')
                continue
            delivery_order = desired_order if desired_order is not None else max(existing_orders, default=0) + 1
            delivery_id = 'delivery_' + uuid.uuid4().hex
            metadata = {'delivery_id': delivery_id, 'vendor_id': vendor,
                        'source_library_id': library, 'supplier_version': version,
                        'delivery_order': delivery_order,
                        'received_at': scan['finished_at'], 'package_mode': 'UNKNOWN',
                        'scope_confirmed': False}
            record = build_delivery(candidate, metadata, mapping)
            after_scan, after = observed()
            if after_scan['status'] != 'COMPLETE' or after != before:
                result['blocked'] += 1
                result['reasons'].append(f'{version}: 发布前文件变化')
                continue
            target = parent / next_filename(parent,'delivery',with_evidence=True)
            ep = evidence_path(target)
            evidence_created = False
            try:
                evidence = {
                    'schema_version': 'delivery_source_evidence.v1', 'scan_id': scan['scan_id'],
                    'files': after_scan['files'],
                    'order_basis': 'configured_order' if version in explicit_order else 'natural_name_hint_or_system_receipt',
                    'classification': {r['relative_in_version']: {
                        'basis': r['identity_basis'], 'corner_hint': r['corner_hint']
                    } for r in rows},
                }
                write_atomic(ep, evidence, immutable=True)
                evidence_created = True
                write_atomic(target, record, immutable=True)
            except Exception:
                if evidence_created and not target.exists(): ep.unlink(missing_ok=True)
                raise
            existing.append((record, evidence))
            result['created'] += 1
        from ai_lib_qor.application.latest_pointers import refresh_library_locked
        refresh_library_locked(work,vendor,library)
    return result
