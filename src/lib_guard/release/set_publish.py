"""Publish explicitly selected current effective combinations as one delivery."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from lib_guard.effective.pointer import load_current_pointer
from lib_guard.release.bundle import create_manifest_from_effective_manifest, validate_release_name, write_json, utc_now
from lib_guard.release.linker import link_release_from_manifest


def publish_release_set(catalog_html: str | Path, libraries: Sequence[str], release_root: str | Path,
                        *, publish_name: str, latest_name: str = 'latest',
                        out_dir: str | Path, apply: bool = False) -> dict:
    publish_name = validate_release_name(publish_name)
    latest_name = validate_release_name(latest_name)
    if publish_name == latest_name:
        raise ValueError('阶段目录与最新指针名不能相同')
    selected = list(dict.fromkeys(libraries))
    if not selected:
        raise ValueError('请勾选至少一个库')
    output = Path(out_dir)
    components, files = [], []
    for index, library in enumerate(selected):
        pointer = load_current_pointer(catalog_html, library)
        if not pointer.get('current_effective_id') or pointer.get('effective_integrity_status') != 'MATCH':
            raise ValueError(f'库 {library} 没有可核对的当前有效组合，请先确认有效版本')
        effective_path = Path(pointer['manifest'])
        component = create_manifest_from_effective_manifest(
            effective_path, output / f'component_{index}.json', release_root=release_root)
        files.extend(component['files'])
        components.append({
            'library_id': library, 'library_name': component['library_name'],
            'library_type': component['library_type'], 'version_id': pointer['current_effective_id'],
            'base_full_version': pointer.get('base_full_version'),
            'accepted_updates': pointer.get('accepted_updates', []),
            'effective_manifest': str(effective_path), 'source': 'current_effective_pointer',
        })
    manifest_path = output / 'release_manifest.json'
    write_json(manifest_path, {
        'schema_version': 'release_manifest.v1', 'release_id': output.name,
        'release_root': str(Path(release_root).resolve()), 'publish_name': publish_name,
        'latest_name': latest_name, 'alias': 'current', 'created_at': utc_now(),
        'source_kind': 'current_effective_set', 'release_components': components,
        'libraries': [], 'files': files,
    })
    print(f'发布准备：{len(components)} 个库，{len(files)} 个文件；阶段 {publish_name}', flush=True)
    link = link_release_from_manifest(manifest_path, apply=apply, mode='symlink', overwrite=True, out_dir=output)
    verify = link.get('verify') or {}
    return {
        'status': link['status'], 'dry_run': not apply, 'link_status': link['status'],
        'verify_status': verify.get('status', '未执行'), 'link_result': link,
        'manifest': str(manifest_path), 'release_root': str(release_root),
        'library_count': len(components), 'out_dir': str(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='执行已确认有效组合的多库链接交付')
    parser.add_argument('--request', required=True)
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_text())
    try:
        result = publish_release_set(**request)
    except (OSError, ValueError, KeyError) as exc:
        result = {'status': 'FAILED', 'error': str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if result['status'] in {'DRY_RUN', 'APPLIED', 'PARTIAL_DRY_RUN', 'PARTIAL_APPLIED'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
