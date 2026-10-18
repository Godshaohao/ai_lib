"""Publish completed operator evidence to the single-version reader projection."""

from __future__ import annotations

from datetime import datetime, timezone
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import shutil
import time
from typing import Any

from lib_guard.atomic import atomic_write_json, file_lock
from lib_guard.catalog.runtime import load_catalog_view
from lib_guard.review.representative_files import load_representative_files, save_representative_file
from lib_guard.review.update_notes import review_notes_root, update_note_path


def _library_and_version(catalog: dict[str, Any], library: str, version: str):
    matches = [row for row in catalog.get('libraries', [])
               if library in {row.get('library_id'), row.get('library_name'), row.get('formal_library_id')}]
    if len(matches) != 1:
        raise ValueError(f'目录中无法唯一定位库：{library}')
    versions = [row for row in matches[0].get('versions', []) if row.get('version_id') == version]
    if len(versions) != 1:
        raise ValueError(f'目录中无法唯一定位版本：{library}/{version}')
    return matches[0], versions[0]


def _inside(path: str, root: str) -> bool:
    return Path(path).resolve().is_relative_to(Path(root).resolve())


def _refresh(catalog_path, html_out, library, version):
    from lib_guard.render.version_detail_fast import render_version_detail_only

    return render_version_detail_only(catalog_path=catalog_path, out_dir=html_out,
                                      library=library, version=version, export_markdown=True)


def publish_file_diff(catalog_path, html_out, library, version, out_dir, *, updated_by='operator',
                      started_epoch=None, refresh=True):
    catalog = load_catalog_view(catalog_path)
    lib, target = _library_and_version(catalog, library, version)
    result = json.loads((Path(out_dir) / 'pairwise_result.json').read_text(encoding='utf-8'))
    old, new = str(result.get('old_file') or ''), str(result.get('new_file') or '')
    if not target.get('raw_path') or not _inside(new, target['raw_path']):
        raise ValueError('新侧文件不属于目标版本，不同步到阅读报告')
    base_matches = [row for row in lib.get('versions', []) if row.get('version_id') != version
                    and row.get('raw_path') and _inside(old, str(row['raw_path']))]
    if len(base_matches) != 1:
        raise ValueError('旧侧文件不属于同库基准版本，不同步到阅读报告')
    notes = review_notes_root(catalog_html_out=html_out)
    existing = load_representative_files(notes, library, version)
    if any(row.get('generated_at') == result.get('generated_at') and row.get('old_file') == old
           and row.get('new_file') == new for row in existing):
        selected = next(row for row in existing if row.get('generated_at') == result.get('generated_at')
                        and row.get('old_file') == old and row.get('new_file') == new)
    else:
        selected = save_representative_file(notes, library, version, out_dir, updated_by=updated_by,
                                            expected_generation=result.get('generated_at'),
                                            base_version_override=base_matches[0]['version_id'],
                                            base_root_override=base_matches[0]['raw_path'],
                                            started_epoch=started_epoch)
    if refresh:
        _refresh(catalog_path, html_out, library, version)
    return selected


def load_current_file_checks(root, library, version):
    def order(item):
        generated = item.get('generated_at') or item.get('saved_at', '')
        return (float(item.get('started_epoch') or 0), generated, item.get('evidence_id', ''))

    grouped = {}
    for row in load_representative_files(root, library, version):
        grouped.setdefault(row['file_type'], []).append(row)
    selected = []
    fields = ('evidence_id', 'evidence_dir', 'generated_at', 'saved_at',
              'old_file', 'new_file', 'base_version')
    for kind in sorted(grouped):
        rows = sorted(grouped[kind], key=order, reverse=True)
        current = rows[0]
        if len(rows) > 1:
            current['history'] = [{field: item.get(field) for field in fields} for item in rows[1:]]
        selected.append(current)
    return selected


def _source_stamps(manifest):
    stamps = {}
    for item in (manifest.get('effective_files') or {}).values():
        source = Path(str(item.get('source_path') or ''))
        root = Path(str(item.get('raw_root') or ''))
        path = source if source.is_absolute() else root / source
        resolved = path.resolve()
        if not resolved.is_relative_to(root.resolve()):
            raise ValueError('有效组合来源文件越界')
        try:
            stat = resolved.stat()
            stamps[str(resolved)] = {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
        except FileNotFoundError:
            stamps[str(resolved)] = {'missing': True}
    return stamps


def _snapshot_source_stamps(snapshot):
    stamps = {}
    complete = True
    for index in (snapshot['index'], snapshot.get('base_index')):
        if index is None:
            continue
        for item in index['files']:
            evidence = item.get('evidence') or {}
            stamp = evidence.get('source_stamp') or {}
            path = evidence.get('source_path')
            if not path or 'size_bytes' not in stamp or 'mtime_ns' not in stamp:
                complete = False
                continue
            value = {'size': stamp['size_bytes'], 'mtime_ns': stamp['mtime_ns']}
            if path in stamps and stamps[path] != value:
                complete = False
            stamps[path] = value
    return stamps, complete


def publish_semantic_review(catalog_path, html_out, manifest_path, out_dir, *,
                            profile_config_path=None, started_epoch=None, refresh=True):
    from lib_guard.effective.manifest import validate_effective_manifest
    from lib_guard.semantic.results import load_review_snapshot

    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    validation = validate_effective_manifest(manifest)
    if not validation['valid']:
        raise ValueError('有效组合清单完整性校验未通过')
    components = [str(item['version_id']) for item in manifest.get('components', [])]
    if not components:
        raise ValueError('有效组合没有版本组成')
    library, version = str(manifest['library_id']), components[-1]
    _library_and_version(load_catalog_view(catalog_path), library, version)
    snapshot = load_review_snapshot(out_dir)
    summary = snapshot['summary']
    if (summary.get('library_id') != library or summary.get('effective_id') != manifest.get('effective_id')
            or summary.get('effective_digest') != validation['digest']):
        raise ValueError('技术检查快照与目标有效组合不一致')
    generation = str(summary['generation'])
    notes = review_notes_root(catalog_html_out=html_out)
    index = update_note_path(notes, library, version).with_name('semantic_review.json')
    destination = index.parent / 'semantic' / generation
    destination.mkdir(parents=True, exist_ok=True)
    source = Path(out_dir) / summary['artifacts']['markdown']
    markdown = source.read_bytes()
    markdown_digest = sha256(markdown).hexdigest()
    target_markdown = destination / 'summary.md'
    if target_markdown.exists() and sha256(target_markdown.read_bytes()).hexdigest() != markdown_digest:
        raise ValueError('已保存技术检查摘要与当前快照不一致')
    if not target_markdown.exists():
        shutil.copy2(source, target_markdown)
    details_source = Path(out_dir) / summary['artifacts']['check_results']
    details_bytes = details_source.read_bytes()
    details_digest = sha256(details_bytes).hexdigest()
    details_path = destination / 'check_results.json'
    if details_path.exists() and sha256(details_path.read_bytes()).hexdigest() != details_digest:
        raise ValueError('已保存逐项检查结果与当前快照不一致')
    if not details_path.exists():
        shutil.copy2(details_source, details_path)
    manifest_bytes = manifest_path.read_bytes()
    manifest_digest = sha256(manifest_bytes).hexdigest()
    stored_manifest = destination / 'effective_manifest.json'
    if stored_manifest.exists() and sha256(stored_manifest.read_bytes()).hexdigest() != manifest_digest:
        raise ValueError('已保存有效组合清单与当前快照不一致')
    if not stored_manifest.exists():
        shutil.copy2(manifest_path, stored_manifest)
    config_path = Path(profile_config_path).resolve() if profile_config_path else None
    config_digest = sha256(config_path.read_bytes()).hexdigest() if config_path and config_path.is_file() else None
    config_matches_snapshot = True
    if config_path:
        from lib_guard.semantic.profile import load_review_profile

        try:
            current_profile = load_review_profile(config_path, profile_name=summary['review_profile']['name'])
            config_matches_snapshot = current_profile['digest'] == summary['review_profile']['digest']
        except (OSError, ValueError, KeyError, TypeError):
            config_matches_snapshot = False
    source_stamps, stamps_complete = _snapshot_source_stamps(snapshot)
    base_index = snapshot.get('base_index')
    row = {
        'schema_version': 'semantic_reader_projection.v1', 'library': library, 'version': version,
        'effective_id': summary['effective_id'], 'effective_digest': summary['effective_digest'],
        'base_effective_id': base_index['effective_id'] if base_index else None,
        'base_effective_digest': summary.get('base_effective_digest'),
        'components': components, 'profile': summary['review_profile']['name'],
        'profile_digest': summary['review_profile']['digest'], 'generation': generation,
        'counts': summary.get('counts', {}), 'delta_counts': summary.get('delta_counts', {}),
        'delta_context': summary.get('delta_context', ''),
        'object_names': {
            item['macro_id']: item['name'] + (f" [{item['variant']}]" if item.get('variant') else '')
            for item in snapshot['bindings']
        },
        'scope': summary.get('scope', {}), 'advisory': True,
        'manifest_path': str(stored_manifest), 'manifest_sha256': manifest_digest,
        'source_stamps': source_stamps, 'source_stamps_complete': stamps_complete,
        'config_path': str(config_path) if config_path else '', 'config_digest': config_digest,
        'config_matches_snapshot': config_matches_snapshot,
        'markdown_path': str(target_markdown), 'markdown_sha256': markdown_digest,
        'details_path': str(details_path), 'details_sha256': details_digest,
        'attention_examples': [
            {'check_id': item.get('check_id'), 'status': item.get('status'),
             'reason_code': item.get('reason_code'), 'macro_id': item.get('macro_id')}
            for item in snapshot['checks'] if item.get('status') not in {'PASS', 'NOT_APPLICABLE'}
        ][:3],
        'published_at': datetime.now(timezone.utc).isoformat(),
        'started_epoch': float(started_epoch if started_epoch is not None else time.time()),
    }
    with file_lock(index.with_name('.semantic_review.lock')):
        data = json.loads(index.read_text(encoding='utf-8')) if index.exists() else {'schema_version': 'semantic_reader_index.v1', 'results': {}}
        key = f"{summary['effective_digest']}:{summary['review_profile']['name']}:{generation}"
        existing = data['results'].get(key)
        if existing:
            row = existing
        else:
            data['results'][key] = row
        atomic_write_json(index, data)
    if refresh:
        _refresh(catalog_path, html_out, library, version)
    return row


def load_semantic_projection(root, library, version):
    from lib_guard.effective.manifest import validate_effective_manifest

    index = update_note_path(root, library, version).with_name('semantic_review.json')
    if not index.is_file():
        return {}
    rows = json.loads(index.read_text(encoding='utf-8')).get('results', {}).values()
    if not rows:
        return {}
    row = dict(max(rows, key=lambda item: (float(item.get('started_epoch') or 0), item.get('published_at', ''))))
    status = 'CURRENT'
    artifacts = {}
    try:
        generation = str(row['generation'])
        if len(generation) != 64 or any(char not in '0123456789abcdef' for char in generation):
            raise ValueError('技术检查 generation 无效')
        snapshot_root = (index.parent / 'semantic' / generation).resolve()
        for key, filename in (('manifest_path', 'effective_manifest.json'),
                              ('markdown_path', 'summary.md'), ('details_path', 'check_results.json')):
            artifact = Path(row[key]).resolve()
            if artifact != (snapshot_root / filename).resolve() or not artifact.is_relative_to(snapshot_root):
                raise ValueError('技术检查快照产物路径越界')
    except ValueError:
        status = 'INVALID'
    except (OSError, KeyError, TypeError):
        status = 'INVALID'
    if status != 'INVALID':
        for name in ('manifest', 'markdown', 'details'):
            try:
                content = Path(row[f'{name}_path']).read_bytes()
                if sha256(content).hexdigest() != row[f'{name}_sha256']:
                    status = 'INVALID'
                else:
                    artifacts[name] = content
            except (OSError, KeyError, TypeError):
                status = 'INVALID'
    if status != 'INVALID':
        try:
            manifest = json.loads(artifacts['manifest'])
            validation = validate_effective_manifest(manifest)
            if not validation['valid'] or validation['digest'] != row['effective_digest']:
                status = 'STALE'
        except (ValueError, KeyError, TypeError):
            status = 'INVALID'
    if status != 'INVALID':
        if not row.get('source_stamps_complete') or not row.get('config_matches_snapshot', not row.get('config_path')):
            status = 'STALE'
        for path, expected in (row.get('source_stamps') or {}).items():
            try:
                stat = Path(path).stat()
                current_stamp = {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
            except FileNotFoundError:
                current_stamp = {'missing': True}
            except OSError:
                status = 'STALE'
                break
            if current_stamp != expected:
                status = 'STALE'
                break
        if row.get('config_path'):
            config = Path(row['config_path'])
            try:
                config_matches = config.is_file() and sha256(config.read_bytes()).hexdigest() == row.get('config_digest')
            except OSError:
                config_matches = False
            if not config_matches:
                status = 'STALE'
    row['checks'], row['delta'] = [], []
    row['object_names'] = row.get('object_names') or {}
    if status != 'INVALID':
        try:
            evidence = json.loads(artifacts['details'])
            checks, delta = evidence['checks'], evidence['delta']
            if not isinstance(checks, list) or not isinstance(delta, list):
                raise ValueError('逐项检查结果格式无效')
            row['checks'], row['delta'] = checks, delta
            if 'counts' not in row:
                row['counts'] = dict(Counter(item['status'] for item in checks))
            if 'delta_counts' not in row:
                row['delta_counts'] = dict(Counter(item['status'] for item in delta))
        except (ValueError, KeyError, TypeError):
            status = 'INVALID'
            row['checks'], row['delta'] = [], []
    row['status'] = status
    return row


def sync_operator_result(request, result, catalog_path, html_out, job_dir, *, started_epoch=None,
                         profile_config_path=None):
    """Publish a completed Web result; never infer ownership from arbitrary paths."""
    action = request.get('action')
    if action == 'file-diff':
        payload = request.get('payload') or {}
        if payload.get('old_file') or payload.get('new_file'):
            return {'status': 'SKIPPED', 'reason': '任意文件对比不自动归属版本'}
        library, version = request.get('library'), request.get('version')
        if not library or not version or result.get('status') not in {'SAME', 'DIFF'}:
            return {'status': 'SKIPPED', 'reason': '没有可同步的版本对比结果'}
        row = publish_file_diff(catalog_path, html_out, library, version, result['out_dir'],
                                updated_by='web', started_epoch=started_epoch)
        return {'status': 'PASS', 'library': library, 'version': version, 'evidence_id': row['evidence_id']}
    if action == 'semantic-review':
        manifest = Path(job_dir) / 'target_effective.json'
        out = Path(job_dir) / 'semantic_review'
        if not manifest.is_file() or not (out / 'summary.json').is_file():
            return {'status': 'SKIPPED', 'reason': '缺少有效组合检查产物'}
        row = publish_semantic_review(catalog_path, html_out, manifest, out,
                                      profile_config_path=profile_config_path, started_epoch=started_epoch)
        return {'status': 'PASS', 'library': row['library'], 'version': row['version'],
                'generation': row['generation']}
    return {'status': 'SKIPPED', 'reason': '非阅读报告检查动作'}
