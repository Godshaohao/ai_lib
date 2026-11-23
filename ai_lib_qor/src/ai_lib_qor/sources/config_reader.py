"""Shared read-only work configuration reader (Layer 1, zero upward dependencies)."""
import json
from pathlib import Path


def load_work_config(work) -> dict:
    path = Path(work) / 'path_sources.json'
    if path.is_symlink():
        raise ValueError('来源配置不能为软链接')
    if not path.exists():
        return {}
    config = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(config, dict) or not isinstance(config.get('libraries', {}), dict):
        raise ValueError('来源配置格式无效')
    return config


def read_registration_times(work, vendor: str, library: str) -> dict:
    """Single source of truth for per-library registration timestamps (path_sources.json with scan_sources.json fallback)."""
    config = load_work_config(work)
    libraries = config.get('libraries', {})
    settings = libraries.get(vendor, {}).get(library, {})
    if not isinstance(settings, dict):
        raise ValueError('库配置格式无效')
    if 'version_registration_times' in settings:
        times = settings['version_registration_times']
        if not isinstance(times, dict):
            raise ValueError('用户登记时间配置无效')
        return times
    # Compatibility fallback for historical scan_sources.json
    old = Path(work) / 'scan_sources.json'
    if not old.exists():
        return {}
    if old.is_symlink():
        raise ValueError('来源配置不能为软链接')
    data = json.loads(old.read_text(encoding='utf-8'))
    rows = [x for x in data.get('sources', []) if (x.get('vendor_id'), x.get('source_library_id')) == (vendor, library)]
    if len(rows) > 1:
        raise ValueError('来源配置不唯一')
    return rows[0].get('version_registration_times', {}) if rows else {}
