"""L1 metadata-only source and version discovery. Never infer BusinessIP ownership."""
from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath


_DEFAULT_VERSION = re.compile(
    r"(?i)(?:v|rev|r|release|ver)[._-]?\d[a-z0-9._-]*|20\d{2}[._-]?\d{1,2}(?:[._-]?\d{1,2})?(?:_[a-f0-9]{7,40})?"
)


def _safe_relative(value):
    if not isinstance(value, str) or not value or value.startswith('/') or '\\' in value:
        return False
    return all(p not in ('', '.', '..') for p in value.split('/'))


def load_scan_sources(work):
    """Backwards-compatible explicit sources; optionally add libraries from legacy Library Map.

    One-time configuration in work/scan_sources.json:
      {"sources": [], "raw_root": "/raw", "library_map": "/cfg/library_map.yml"}
    Existing explicit entries override derived ones by (vendor_id, source_library_id).
    """
    if not work:
        return []
    file = Path(work) / 'scan_sources.json'
    if not file.is_file() or file.is_symlink():
        return []
    config = json.loads(file.read_text(encoding='utf-8'))
    explicit = config.get('sources', [])
    if not isinstance(explicit, list):
        raise ValueError('scan_sources.json: sources 必须是数组')
    found = {}
    if config.get('library_map') and config.get('raw_root'):
        from lib_guard.discovery import load_library_map
        policy = {'discovery': {'library_map': str(config['library_map'])}}
        for lib in load_library_map(config['raw_root'], policy, file):
            if not lib.vendor:
                continue  # vendor not proven; do not invent it
            key = (str(lib.vendor), str(lib.library_id))
            found[key] = {
                'vendor_id': key[0], 'source_library_id': key[1],
                'root': str(lib.root),
                'version_path_rules': config.get('version_path_rules', [{'pattern': '{version}'}]),
                'origin': 'library_map',
            }
    seen = set()
    for item in explicit:
        if not isinstance(item, dict):
            raise ValueError('scan_sources.json: 来源配置必须是对象')
        key = (item['vendor_id'], item['source_library_id'])
        if key in seen:
            raise ValueError(f'来源配置重复: {key}')
        seen.add(key)
        if not item.get('root'):
            raise ValueError(f'来源未配置根目录: {key}')
        found[key] = dict(item)
    return [found[k] for k in sorted(found)]


def discover_version_paths(scan, source):
    """Discover version prefixes from relative path *only*. Never read file contents.

    Existing explicit version_paths are authoritative. Optional version_path_rules
    use {vendor}, {library}, {version}; defaults to direct version-looking child dirs.
    Ambiguous paths/IDs are excluded instead of guessing a delivery order.
    """
    explicit = source.get('version_paths')
    if explicit:
        if not isinstance(explicit, dict):
            raise ValueError('version_paths 必须是对象')
        for version, prefix in explicit.items():
            if not isinstance(version, str) or not version or not _safe_relative(prefix):
                raise ValueError(f'版本目录配置非法: {version}: {prefix}')
        return dict(explicit), []

    rules = source.get('version_path_rules') or [{'pattern': '{version}'}]
    if not isinstance(rules, list):
        raise ValueError('version_path_rules 必须是数组')
    compiled = []
    for item in rules:
        pattern = item.get('pattern') if isinstance(item, dict) else item
        if not isinstance(pattern, str) or pattern.count('{version}') != 1:
            raise ValueError(f'版本规则必须恰好包含一个 {{version}}: {pattern}')
        pattern = pattern.replace('{vendor}', str(source.get('vendor_id', '')))
        pattern = pattern.replace('{library}', str(source.get('source_library_id', '')))
        if '{' in pattern.replace('{version}', '') or '}' in pattern.replace('{version}', ''):
            raise ValueError('版本规则含未知占位符')
        if not _safe_relative(pattern.replace('{version}', 'VERSION')):
            raise ValueError('版本规则不是安全相对路径')
        regex = '^' + re.escape(pattern).replace(re.escape('{version}'), r'(?P<version>[^/]+)') + r'/'
        compiled.append((re.compile(regex), pattern == '{version}'))

    candidates = {}
    warnings = []
    for entry in scan.get('files', []):
        path = entry['path']
        matches = []
        for regex, default in compiled:
            m = regex.match(path)
            if not m:
                continue
            version = m.group('version')
            if default and not _DEFAULT_VERSION.fullmatch(version):
                continue
            prefix = path[:m.end() - 1]
            if _safe_relative(prefix):
                matches.append((version, prefix))
        if len(set(matches)) == 1:
            version, prefix = matches[0]
            candidates.setdefault(version, set()).add(prefix)
        elif len(set(matches)) > 1:
            warnings.append(f'{path}: 命中多个版本范围')
    versions = {}
    for version, paths in sorted(candidates.items()):
        if len(paths) == 1:
            versions[version] = next(iter(paths))
        else:
            warnings.append(f'{version}: 版本名称在多个目录中出现，未纳管')
    return versions, sorted(set(warnings))


def natural_version_key(version):
    """Deterministic version display order; not proof of supplier chronology."""
    return tuple((0, int(x)) if x.isdigit() else (1, x.lower())
                 for x in re.split(r'(\d+)', version))
