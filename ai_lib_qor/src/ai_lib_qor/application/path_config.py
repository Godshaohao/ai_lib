"""Configuration for the path-based work directory."""
import json
from copy import deepcopy
from pathlib import Path


def load_path_config(work):
    path = Path(work)/'path_sources.json'
    if path.is_symlink():
        raise ValueError('来源配置不能为软链接')
    if not path.exists():
        return {}
    config = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(config, dict) or not isinstance(config.get('libraries', {}), dict):
        raise ValueError('来源配置格式无效')
    return config


def update_options(config, **overrides):
    result={}
    for name in ('update_raw','update_formal','update_index','auto_effective'):
        value=overrides.get(name)
        if value is None:value=config.get(name,True)
        if not isinstance(value,bool):raise ValueError(name+' 必须是布尔值')
        result[name]=value
    return result


def registration_times(work, vendor, library):
    config = load_path_config(work)
    libraries = config.get('libraries', {})
    settings = libraries.get(vendor, {}).get(library, {})
    if not isinstance(settings, dict):
        raise ValueError('库配置格式无效')
    if 'version_registration_times' in settings:
        times = settings['version_registration_times']
        if not isinstance(times, dict):
            raise ValueError('用户登记时间配置无效')
        return times
    # Compatibility: the new configuration wins; old work can still be migrated.
    old = Path(work)/'scan_sources.json'
    if not old.exists():
        return {}
    if old.is_symlink():
        raise ValueError('来源配置不能是软链接')
    data = json.loads(old.read_text(encoding='utf-8'))
    rows = [x for x in data.get('sources', []) if (x.get('vendor_id'), x.get('source_library_id')) == (vendor, library)]
    if len(rows) > 1:
        raise ValueError('来源配置不唯一')
    return rows[0].get('version_registration_times', {}) if rows else {}


def excluded_versions(work, vendor, library):
    data=load_path_config(work).get('libraries', {}).get(vendor, {}).get(library, {}).get('excluded_versions', [])
    if not isinstance(data,list) or any(not isinstance(x,str) for x in data) or len(set(data))!=len(data):
        raise ValueError('排除版本配置无效')
    return set(data)


def set_version_excluded(work, vendor, library, version, excluded):
    from ai_lib_qor.sources.layout import library_folder
    from ai_lib_qor.versions.store import locked,write_atomic
    from .minimal_effective import _deliveries,_history,_flat
    folder=library_folder(work,vendor,library)
    with locked(folder):
        if version not in _deliveries(folder,vendor,library):raise ValueError('来源版本不存在')
        history=_history(folder,library)
        used=bool(history and version in _flat(history[-1][2]['views']).values())
        with locked(work):
            config=deepcopy(load_path_config(work))
            item=config.setdefault('libraries',{}).setdefault(vendor,{}).setdefault(library,{})
            values=excluded_versions(work,vendor,library)
            if excluded:values.add(version)
            else:values.discard(version)
            item['excluded_versions']=sorted(values)
            write_atomic(Path(work)/'path_sources.json',config)
    return {'version':version,'excluded':excluded,'currently_used':used}
