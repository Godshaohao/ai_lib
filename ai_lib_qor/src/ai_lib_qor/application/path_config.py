"""Configuration for the path-based work directory."""
from copy import deepcopy
from pathlib import Path

from ai_lib_qor.sources.config_reader import load_work_config, read_registration_times


def load_path_config(work):
    return load_work_config(work)


def update_options(config, **overrides):
    result = {}
    for name in ('update_raw', 'update_formal', 'update_index', 'auto_effective'):
        value = overrides.get(name)
        if value is None:
            value = config.get(name, True)
        if not isinstance(value, bool):
            raise ValueError(name + ' 必须是布尔值')
        result[name] = value
    return result


def registration_times(work, vendor, library):
    return read_registration_times(work, vendor, library)


def configured_plugin_modules(work) -> list[str]:
    cfg = load_path_config(work)
    raw = cfg.get('plugin_modules', [])
    if not isinstance(raw, list) or any(not isinstance(x, str) or not x.strip() for x in raw):
        raise ValueError('plugin_modules 配置必须是字符串数组')
    return [x.strip() for x in raw]


def excluded_versions(work, vendor, library):
    data = load_path_config(work).get('libraries', {}).get(vendor, {}).get(library, {}).get('excluded_versions', [])
    if not isinstance(data, list) or any(not isinstance(x, str) for x in data) or len(set(data)) != len(data):
        raise ValueError('排除版本配置无效')
    return set(data)


def set_version_excluded(work, vendor, library, version, excluded):
    from ai_lib_qor.sources.layout import library_folder
    from ai_lib_qor.versions.store import locked, write_atomic
    from .minimal_effective import _deliveries, _flat, _history
    folder = library_folder(work, vendor, library)
    with locked(folder):
        if version not in _deliveries(folder, vendor, library):
            raise ValueError('来源版本不存在')
        history = _history(folder, library)
        used = bool(history and version in _flat(history[-1][2]['views']).values())
        with locked(work):
            config = deepcopy(load_path_config(work))
            item = config.setdefault('libraries', {}).setdefault(vendor, {}).setdefault(library, {})
            values = excluded_versions(work, vendor, library)
            if excluded:
                values.add(version)
            else:
                values.discard(version)
            item['excluded_versions'] = sorted(values)
            write_atomic(Path(work) / 'path_sources.json', config)
    return {'version': version, 'excluded': excluded, 'currently_used': used}


def _unadopted_key(view: str, rel_path: str) -> str:
    if not isinstance(view, str) or not view.strip() or ':' in view:
        raise ValueError('View 名称无效')
    if not isinstance(rel_path, str) or not rel_path.strip() or rel_path.startswith('/') or '\\' in rel_path:
        raise ValueError('相对路径无效')
    return f'{view.strip().upper()}:{rel_path.strip()}'


def ignored_unadopted_files(work, vendor, library) -> set[tuple[str, str]]:
    """Return {(view, relative_path)} explicitly acknowledged/ignored from unadopted-file notices."""
    data = load_path_config(work).get('libraries', {}).get(vendor, {}).get(library, {}).get('ignored_unadopted_files', [])
    if not isinstance(data, list) or any(not isinstance(x, str) or ':' not in x for x in data):
        raise ValueError('ignored_unadopted_files 配置格式无效（应为 VIEW:relative_path 列表）')
    out = set()
    for token in data:
        v, rel = token.split(':', 1)
        out.add((v.strip().upper(), rel.strip()))
    return out


def set_unadopted_ignored(work, vendor, library, view: str, rel_path: str, ignored: bool = True) -> dict:
    """Explicitly ignore or un-ignore a delivery file from unadopted-new-file reminders (never alters Effective)."""
    from ai_lib_qor.sources.layout import library_folder
    from ai_lib_qor.versions.store import locked, write_atomic
    key_str = _unadopted_key(view, rel_path)
    folder = library_folder(work, vendor, library)
    if not folder.is_dir():
        raise ValueError('库目录不存在')
    with locked(folder):
        with locked(work):
            config = deepcopy(load_path_config(work))
            item = config.setdefault('libraries', {}).setdefault(vendor, {}).setdefault(library, {})
            existing = set(item.get('ignored_unadopted_files') or [])
            if ignored:
                existing.add(key_str)
            else:
                existing.discard(key_str)
            item['ignored_unadopted_files'] = sorted(existing)
            write_atomic(Path(work) / 'path_sources.json', config)
    return {'vendor': vendor, 'library': library, 'view': view.strip().upper(), 'path': rel_path.strip(), 'ignored': ignored}
