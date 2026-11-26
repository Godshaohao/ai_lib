"""Configuration for the path-based work directory (Schema-validated global & per-library overrides)."""
from copy import deepcopy
import os
from pathlib import Path

from ai_lib_qor.sources.config_reader import load_work_config, read_registration_times
from ai_lib_qor.versions.store import locked, validate, write_atomic

DEFAULT_WORKBENCH_MAX_WORKERS = 2
DEFAULT_INDEX_PAGE_SIZE = 80
DEFAULT_JSON_INVENTORY_PAGE_SIZE = 100


def load_path_config(work, *, strict: bool = False):
    return load_work_config(work, strict=strict)


def validate_path_config(config: dict) -> None:
    """Strictly validate a path_sources config dict against schemas/path_sources.schema.json."""
    if not isinstance(config, dict):
        raise ValueError('来源配置必须是 JSON 对象')
    validate(config, 'path_sources')


def save_path_config(work, config: dict, *, already_locked: bool = False) -> Path:
    """Validate `config` against path_sources JSON Schema and persist atomically."""
    if not isinstance(config, dict):
        raise ValueError('来源配置必须是 JSON 对象')
    validate(config, 'path_sources')
    root = Path(work)
    cp = root / 'path_sources.json'
    if cp.is_symlink():
        raise ValueError('来源配置不能为软链接')
    if already_locked:
        write_atomic(cp, config)
    else:
        with locked(root):
            if cp.is_symlink():
                raise ValueError('来源配置不能为软链接')
            write_atomic(cp, config)
    return cp


def _parse_int_range(raw, *, name: str, min_val: int, max_val: int) -> int:
    if isinstance(raw, bool):
        raise ValueError(f'{name} 必须是 {min_val}~{max_val} 之间的整数')
    try:
        val = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{name} 必须是 {min_val}~{max_val} 之间的整数') from exc
    if not (min_val <= val <= max_val):
        raise ValueError(f'{name} 必须在 {min_val}~{max_val} 之间')
    return val


def workbench_runtime_settings(work) -> dict:
    """Resolve workbench runtime parameters: env vars > path_sources.json workbench > defaults."""
    cfg = load_path_config(work)
    wb = cfg.get('workbench') or {}
    if not isinstance(wb, dict):
        raise ValueError('workbench 必须为对象')

    def _resolve(cfg_key: str, env_key: str, default: int, min_v: int, max_v: int) -> tuple[int, str]:
        env_raw = os.environ.get(env_key, '').strip()
        if env_raw:
            return _parse_int_range(env_raw, name=env_key, min_val=min_v, max_val=max_v), 'env'
        if cfg_key in wb and wb[cfg_key] is not None:
            return _parse_int_range(wb[cfg_key], name=f'workbench.{cfg_key}', min_val=min_v, max_val=max_v), 'config'
        return default, 'default'

    max_workers, mw_src = _resolve('max_workers', 'AI_LIB_QOR_MAX_WORKERS', DEFAULT_WORKBENCH_MAX_WORKERS, 1, 32)
    index_ps, idx_src = _resolve('index_page_size', 'AI_LIB_QOR_INDEX_PAGE_SIZE', DEFAULT_INDEX_PAGE_SIZE, 10, 500)
    inv_ps, inv_src = _resolve('json_inventory_page_size', 'AI_LIB_QOR_INVENTORY_PAGE_SIZE', DEFAULT_JSON_INVENTORY_PAGE_SIZE, 10, 500)
    return {
        'max_workers': max_workers,
        'index_page_size': index_ps,
        'json_inventory_page_size': inv_ps,
        'sources': {
            'max_workers': mw_src,
            'index_page_size': idx_src,
            'json_inventory_page_size': inv_src,
        },
    }


def _normalize_plugin_policy(raw, *, source_label: str) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f'{source_label} 必须是 JSON 对象')
    unknown = sorted(set(raw) - {'enabled', 'disabled'})
    if unknown:
        raise ValueError(f'{source_label} 包含未知字段: {", ".join(unknown)}')
    out = {'enabled': None, 'disabled': []}
    if 'enabled' in raw and raw['enabled'] is not None:
        if not isinstance(raw['enabled'], list) or any(not isinstance(x, str) or not x.strip() for x in raw['enabled']):
            raise ValueError(f'{source_label}.enabled 必须是插件名数组')
        out['enabled'] = list(dict.fromkeys(x.strip() for x in raw['enabled']))
    if 'disabled' in raw and raw['disabled'] is not None:
        if not isinstance(raw['disabled'], list) or any(not isinstance(x, str) or not x.strip() for x in raw['disabled']):
            raise ValueError(f'{source_label}.disabled 必须是插件名数组')
        out['disabled'] = list(dict.fromkeys(x.strip() for x in raw['disabled']))
    return out


def effective_check_plugins(
    work,
    vendor: str | None = None,
    library: str | None = None,
    *,
    ip_type: str | None = None,
    explicit_plugins=None,
) -> list[str] | None:
    """Resolve effective check plugin names from workspace -> ip_type -> per-library policies.

    Returns `None` when no policy restricts plugins (preserve default all-registered behavior).
    If `explicit_plugins` is provided (e.g. CLI --plugins), returns it directly.
    """
    if explicit_plugins is not None:
        return list(explicit_plugins)
    from ai_lib_qor.checks.path_plugins import PATH_CHECK_PLUGINS

    cfg = load_path_config(work)
    registered = list(PATH_CHECK_PLUGINS.keys())
    reg_set = set(registered)

    global_pol = _normalize_plugin_policy(cfg.get('check_plugins'), source_label='check_plugins')

    eff_ip_type = ip_type
    if eff_ip_type is None and vendor and library:
        eff_ip_type = library_ip_config(work, vendor, library).get('ip_type')

    ip_type_pol = None
    by_type = cfg.get('check_plugins_by_ip_type')
    if isinstance(by_type, dict) and eff_ip_type:
        wanted = eff_ip_type.strip().casefold()
        for k, v in by_type.items():
            if isinstance(k, str) and k.strip().casefold() == wanted:
                ip_type_pol = _normalize_plugin_policy(v, source_label=f'check_plugins_by_ip_type.{k}')
                break

    lib_pol = None
    if vendor and library:
        lib_cfg = cfg.get('libraries', {}).get(vendor, {}).get(library, {})
        if isinstance(lib_cfg, dict) and 'check_plugins' in lib_cfg:
            lib_pol = _normalize_plugin_policy(
                lib_cfg.get('check_plugins'),
                source_label=f'libraries.{vendor}.{library}.check_plugins',
            )

    if global_pol is None and ip_type_pol is None and lib_pol is None:
        return None

    selected = list(registered)
    for pol, label in (
        (global_pol, 'check_plugins'),
        (ip_type_pol, f'check_plugins_by_ip_type.{eff_ip_type}'),
        (lib_pol, f'libraries.{vendor}.{library}.check_plugins'),
    ):
        if pol is None:
            continue
        if pol['enabled'] is not None:
            bad = [p for p in pol['enabled'] if p not in reg_set]
            if bad:
                raise ValueError(f'{label}.enabled 包含未注册的检查插件: {", ".join(bad)}')
            selected = [p for p in registered if p in set(pol['enabled'])]
        if pol['disabled']:
            bad = [p for p in pol['disabled'] if p not in reg_set]
            if bad:
                raise ValueError(f'{label}.disabled 包含未注册的检查插件: {", ".join(bad)}')
            dis = set(pol['disabled'])
            selected = [p for p in selected if p not in dis]
    if not selected:
        raise ValueError('检查插件配置生效后为空，请至少保留一个启用的检查插件')
    return selected


def _merge_plugin_params_layer(target: dict, layer, *, source_label: str) -> None:
    if layer is None:
        return
    if not isinstance(layer, dict):
        raise ValueError(f'{source_label} 必须是 JSON 对象')
    for pname, params in layer.items():
        if not isinstance(pname, str) or not pname.strip():
            raise ValueError(f'{source_label} 存在无效插件名')
        key = pname.strip()
        if params is None:
            target.pop(key, None)
            continue
        if not isinstance(params, dict):
            raise ValueError(f'{source_label}.{key} 必须是 JSON 对象')
        merged = deepcopy(target.get(key) or {})
        merged.update(deepcopy(params))
        target[key] = merged


def effective_plugin_params(
    work,
    vendor: str | None = None,
    library: str | None = None,
    *,
    ip_type: str | None = None,
) -> dict:
    """Resolve 3-tier merged check plugin parameters: workspace -> ip_type -> per-library."""
    cfg = load_path_config(work)
    eff_ip_type = ip_type
    if eff_ip_type is None and vendor and library:
        eff_ip_type = library_ip_config(work, vendor, library).get('ip_type')

    merged: dict = {}
    _merge_plugin_params_layer(merged, cfg.get('check_plugin_params'), source_label='check_plugin_params')

    by_type = cfg.get('check_plugin_params_by_ip_type')
    if isinstance(by_type, dict) and eff_ip_type:
        wanted = eff_ip_type.strip().casefold()
        for k, v in by_type.items():
            if isinstance(k, str) and k.strip().casefold() == wanted:
                _merge_plugin_params_layer(merged, v, source_label=f'check_plugin_params_by_ip_type.{k}')
                break

    if vendor and library:
        lib_cfg = cfg.get('libraries', {}).get(vendor, {}).get(library, {})
        if isinstance(lib_cfg, dict) and 'check_plugin_params' in lib_cfg:
            _merge_plugin_params_layer(
                merged,
                lib_cfg.get('check_plugin_params'),
                source_label=f'libraries.{vendor}.{library}.check_plugin_params',
            )
    return merged


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


def library_ip_config(work, vendor, library) -> dict:
    """Read optional per-library multi-track IP config (`ip_type`, `ip_list`); empty `ip_list` means single-track."""
    from ai_lib_qor.sources.layout import SAFE

    libraries = load_path_config(work).get('libraries', {})
    vendor_cfg = libraries.get(vendor, {})
    if not isinstance(vendor_cfg, dict):
        raise ValueError('供应商配置格式无效')
    settings = vendor_cfg.get(library, {})
    if not isinstance(settings, dict):
        raise ValueError('库配置格式无效')

    raw_type = settings.get('ip_type')
    if raw_type is not None:
        if not isinstance(raw_type, str) or not raw_type.strip():
            raise ValueError('ip_type 必须为非空字符串')
        ip_type = raw_type.strip()
    else:
        ip_type = None

    raw_list = settings.get('ip_list')
    if raw_list is None:
        ip_list = []
    else:
        if not isinstance(raw_list, list):
            raise ValueError('ip_list 必须是字符串数组')
        ip_list = []
        seen_folded = set()
        for item in raw_list:
            if not isinstance(item, str) or not item.strip():
                raise ValueError('ip_list 中存在无效的业务 IP 名称')
            token = item.strip()
            if not SAFE.fullmatch(token) or token in ('.', '..') or '__' in token:
                raise ValueError(f'业务 IP 名称不安全（不能包含双下划线或非法路径字符）: {token}')
            folded = token.casefold()
            if folded in seen_folded:
                raise ValueError(f'ip_list 存在重复（忽略大小写）的业务 IP: {token}')
            seen_folded.add(folded)
            ip_list.append(token)

    return {
        'ip_type': ip_type,
        'ip_list': ip_list,
        'is_multi_track': bool(ip_list),
    }


def list_libraries_by_ip_type(work, ip_type: str | None = None) -> list[dict]:
    """Return configured/discovered libraries filtered by optional `ip_type` (case-insensitive)."""
    root = Path(work)
    cfg_libs = load_path_config(work).get('libraries', {})
    keys = set()
    libs_root = root / 'libraries'
    if libs_root.is_dir():
        for folder in sorted(libs_root.glob('*/*')):
            if folder.is_dir() and not folder.is_symlink() and not folder.parent.is_symlink():
                keys.add((folder.parent.name, folder.name))
    if isinstance(cfg_libs, dict):
        for v, v_map in cfg_libs.items():
            if isinstance(v_map, dict):
                for lib in v_map:
                    keys.add((v, lib))
    out = []
    wanted = ip_type.strip().casefold() if isinstance(ip_type, str) and ip_type.strip() else None
    for v, lib in sorted(keys):
        try:
            info = library_ip_config(work, v, lib)
        except ValueError:
            continue
        if wanted is not None:
            cur = (info['ip_type'] or '').casefold()
            if cur != wanted:
                continue
        out.append({'vendor': v, 'library': lib, **info})
    return out


def configured_plugin_modules(work) -> list[str]:
    cfg = load_path_config(work)
    raw = cfg.get('plugin_modules', [])
    if not isinstance(raw, list) or any(not isinstance(x, str) or not x.strip() for x in raw):
        raise ValueError('plugin_modules 配置必须是字符串数组')
    return [x.strip() for x in raw]


DEFAULT_SKIP_PARSE_VIEWS = ('CDL', 'SPICE', 'VERILOG')
DEFAULT_INITIAL_DELIVERY_TAIL = 3
DEFAULT_LIBERTY_PARSE_FILTER = {
    'enabled': True,
    'threshold': 12,
    'keywords': ('tt', 'ss', 'ff'),
    'exclude_keywords': (),
    'max_selected': 6,
    'fallback': 'first_n',
}


def _validate_tail_value(raw, field_name: str) -> int | None:
    if raw is None or raw == 0:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ValueError(f'{field_name} 必须是非负整数（0 或 null 表示不折叠、全历史逐版演进）')
    return raw


def initial_delivery_tail(work, vendor=None, library=None) -> int | None:
    """Resolve A+ initial history tail window for non-Formal delivery initialization.

    - Positive int `k` (default 3): fold earliest `max(1, N - k)` deliveries chronologically into `rev_0001`,
      then let the latest `k` deliveries evolve individually into `rev_0002 .. rev_{k+1}`.
    - `0` or `None`: disable folding (full history evolution starting from the earliest delivery).
    """
    cfg = load_path_config(work)
    if 'initial_delivery_tail' in cfg:
        effective = _validate_tail_value(cfg.get('initial_delivery_tail'), 'initial_delivery_tail')
    else:
        effective = DEFAULT_INITIAL_DELIVERY_TAIL

    if vendor and library:
        lib_cfg = cfg.get('libraries', {}).get(vendor, {}).get(library, {})
        if isinstance(lib_cfg, dict) and 'initial_delivery_tail' in lib_cfg:
            effective = _validate_tail_value(
                lib_cfg.get('initial_delivery_tail'),
                f'libraries.{vendor}.{library}.initial_delivery_tail',
            )
    return effective


def _normalize_view_list(raw, field_name: str) -> list[str]:
    if not isinstance(raw, list):
        raise ValueError(f'{field_name} 必须是 View 字符串数组（例如 ["CDL", "SPICE", "VERILOG"] 或 []）')
    out = []
    seen = set()
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f'{field_name} 中存在无效的 View 名称')
        tok = item.strip().upper()
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return sorted(out)


def skip_parse_views(work, vendor=None, library=None) -> list[str]:
    """Resolve effective list of views skipped during check parsing (default: CDL, SPICE, VERILOG).

    Workspace `skip_parse_views` overrides the default; per-library `libraries.<v>.<lib>.skip_parse_views`
    overrides workspace default. Set `[]` to enable parsing all supported views.
    """
    cfg = load_path_config(work)
    if 'skip_parse_views' in cfg and cfg['skip_parse_views'] is not None:
        effective = _normalize_view_list(cfg['skip_parse_views'], 'skip_parse_views')
    else:
        effective = sorted(DEFAULT_SKIP_PARSE_VIEWS)

    if vendor and library:
        lib_cfg = cfg.get('libraries', {}).get(vendor, {}).get(library, {})
        if isinstance(lib_cfg, dict) and 'skip_parse_views' in lib_cfg:
            raw_lib = lib_cfg.get('skip_parse_views')
            if raw_lib is None:
                effective = []
            else:
                effective = _normalize_view_list(
                    raw_lib,
                    f'libraries.{vendor}.{library}.skip_parse_views',
                )
    return effective


def _normalize_keyword_list(raw, field_name: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f'{field_name} 必须是字符串数组')
    out = []
    seen = set()
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f'{field_name} 中存在无效关键词')
        tok = item.strip()
        folded = tok.casefold()
        if folded not in seen:
            seen.add(folded)
            out.append(tok)
    return out


def _validate_liberty_filter_dict(raw, *, source_label: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f'{source_label} 必须是 JSON 对象')
    allowed = {'enabled', 'threshold', 'keywords', 'exclude_keywords', 'max_selected', 'fallback'}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f'{source_label} 包含未知字段: {", ".join(unknown)}')
    out = {}
    if 'enabled' in raw:
        if not isinstance(raw['enabled'], bool):
            raise ValueError(f'{source_label}.enabled 必须是布尔值')
        out['enabled'] = raw['enabled']
    if 'threshold' in raw:
        val = raw['threshold']
        if val is None or val == 0:
            out['threshold'] = None
        elif isinstance(val, bool) or not isinstance(val, int) or val < 1:
            raise ValueError(f'{source_label}.threshold 必须是大于等于 1 的整数（或 0/null 关闭）')
        else:
            out['threshold'] = val
    if 'keywords' in raw:
        out['keywords'] = _normalize_keyword_list(raw['keywords'], f'{source_label}.keywords')
    if 'exclude_keywords' in raw:
        out['exclude_keywords'] = _normalize_keyword_list(raw['exclude_keywords'], f'{source_label}.exclude_keywords')
    if 'max_selected' in raw:
        val = raw['max_selected']
        if val is None or val == 0:
            out['max_selected'] = None
        elif isinstance(val, bool) or not isinstance(val, int) or val < 1:
            raise ValueError(f'{source_label}.max_selected 必须是大于等于 1 的整数（或 null 不限）')
        else:
            out['max_selected'] = val
    if 'fallback' in raw:
        val = raw['fallback']
        if val not in ('first_n', 'skip'):
            raise ValueError(f'{source_label}.fallback 必须是 "first_n" 或 "skip"')
        out['fallback'] = val
    return out


def liberty_parse_filter(work, vendor=None, library=None) -> dict:
    """Resolve effective Liberty parse filter policy (built-in default -> workspace -> per-library override)."""
    cfg = load_path_config(work)
    if 'liberty_parse_filter' in cfg:
        merged = {
            'enabled': None,
            'threshold': None,
            'keywords': [],
            'exclude_keywords': [],
            'max_selected': None,
            'fallback': 'first_n',
        }
        raw_global = cfg.get('liberty_parse_filter')
        if raw_global is None:
            merged['enabled'] = False
        else:
            merged.update(_validate_liberty_filter_dict(raw_global, source_label='liberty_parse_filter'))
    else:
        merged = {
            'enabled': DEFAULT_LIBERTY_PARSE_FILTER['enabled'],
            'threshold': DEFAULT_LIBERTY_PARSE_FILTER['threshold'],
            'keywords': list(DEFAULT_LIBERTY_PARSE_FILTER['keywords']),
            'exclude_keywords': list(DEFAULT_LIBERTY_PARSE_FILTER['exclude_keywords']),
            'max_selected': DEFAULT_LIBERTY_PARSE_FILTER['max_selected'],
            'fallback': DEFAULT_LIBERTY_PARSE_FILTER['fallback'],
        }

    if vendor and library:
        lib_cfg = cfg.get('libraries', {}).get(vendor, {}).get(library, {})
        if isinstance(lib_cfg, dict) and 'liberty_parse_filter' in lib_cfg:
            raw_lib = lib_cfg.get('liberty_parse_filter')
            if raw_lib is None:
                merged['enabled'] = False
            else:
                merged.update(
                    _validate_liberty_filter_dict(
                        raw_lib,
                        source_label=f'libraries.{vendor}.{library}.liberty_parse_filter',
                    )
                )

    threshold = merged['threshold']
    if merged['enabled'] is None:
        enabled = threshold is not None
    else:
        enabled = bool(merged['enabled']) and (threshold is not None)

    return {
        'enabled': enabled,
        'threshold': threshold,
        'keywords': list(merged['keywords']),
        'exclude_keywords': list(merged['exclude_keywords']),
        'max_selected': merged['max_selected'],
        'fallback': merged['fallback'],
    }


def select_liberty_files(paths: list[str], policy: dict) -> dict:
    """Deterministically select a subset of LIBERTY relative paths when count exceeds policy['threshold']."""
    ordered = sorted(paths)
    total = len(ordered)
    threshold = policy.get('threshold')
    keywords = list(policy.get('keywords') or [])
    exclude_keywords = list(policy.get('exclude_keywords') or [])
    max_selected = policy.get('max_selected')
    fallback = policy.get('fallback') or 'first_n'

    if not policy.get('enabled') or threshold is None or total <= threshold:
        return {
            'applied': False,
            'selected': ordered,
            'skipped': [],
            'total_liberty_files': total,
            'selected_count': total,
            'skipped_count': 0,
            'threshold': threshold,
            'keywords': keywords,
            'exclude_keywords': exclude_keywords,
            'max_selected': max_selected,
            'fallback': fallback,
            'fallback_used': False,
        }

    pool = ordered
    if exclude_keywords:
        excl_folded = [k.casefold() for k in exclude_keywords]
        filtered_pool = [p for p in ordered if not any(ek in p.casefold() for ek in excl_folded)]
        if filtered_pool:
            pool = filtered_pool

    fallback_used = False
    selected_list: list[str] = []
    if keywords:
        # Round-robin across keyword buckets so multi-corner keyword sets (e.g. tt/ss/ff) stay balanced under max_selected
        buckets = [[p for p in pool if kw.casefold() in p.casefold()] for kw in keywords]
        seen = set()
        cap = max_selected if max_selected is not None else len(pool)
        progress = True
        while progress and len(selected_list) < cap:
            progress = False
            for bucket in buckets:
                while bucket and bucket[0] in seen:
                    bucket.pop(0)
                if bucket and len(selected_list) < cap:
                    pick = bucket.pop(0)
                    seen.add(pick)
                    selected_list.append(pick)
                    progress = True
        if not selected_list:
            if fallback == 'first_n':
                cap = max_selected if max_selected is not None else threshold
                selected_list = pool[:cap]
                fallback_used = True
            else:
                selected_list = []
    else:
        cap = max_selected if max_selected is not None else threshold
        selected_list = pool[:cap]

    selected_set = set(selected_list)
    selected_ordered = [p for p in ordered if p in selected_set]
    skipped_ordered = [p for p in ordered if p not in selected_set]
    return {
        'applied': True,
        'selected': selected_ordered,
        'skipped': skipped_ordered,
        'total_liberty_files': total,
        'selected_count': len(selected_ordered),
        'skipped_count': len(skipped_ordered),
        'threshold': threshold,
        'keywords': keywords,
        'exclude_keywords': exclude_keywords,
        'max_selected': max_selected,
        'fallback': fallback,
        'fallback_used': fallback_used,
    }


def liberty_filter_evidence(selection):
    """Return the applied sampling policy and counts persisted in CheckResult."""
    if not selection['applied']:
        return None
    return {key: selection[key] for key in (
        'applied', 'total_liberty_files', 'selected_count', 'skipped_count',
        'threshold', 'keywords', 'exclude_keywords', 'max_selected', 'fallback', 'fallback_used',
    )}


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
            save_path_config(work, config, already_locked=True)
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
            save_path_config(work, config, already_locked=True)
    return {'vendor': vendor, 'library': library, 'view': view.strip().upper(), 'path': rel_path.strip(), 'ignored': ignored}


def _clean_ip_list_input(raw_list) -> list[str]:
    from ai_lib_qor.sources.layout import SAFE
    if raw_list is None:
        return []
    if not isinstance(raw_list, list):
        raise ValueError('ip_list 必须是字符串数组')
    out = []
    seen = set()
    for item in raw_list:
        if not isinstance(item, str) or not item.strip():
            raise ValueError('ip_list 中存在无效的业务 IP 名称')
        token = item.strip()
        if not SAFE.fullmatch(token) or token in ('.', '..') or '__' in token:
            raise ValueError(f'业务 IP 名称不安全（不能包含双下划线或非法路径字符）: {token}')
        folded = token.casefold()
        if folded in seen:
            raise ValueError(f'ip_list 存在重复（忽略大小写）的业务 IP: {token}')
        seen.add(folded)
        out.append(token)
    return out


def get_workspace_config_view(work) -> dict:
    """Read-only structured view of workspace configuration, runtime settings, and plugin catalog."""
    from ai_lib_qor.checks.path_plugins import PATH_CHECK_PLUGIN_META, PATH_CHECK_PLUGINS
    from ai_lib_qor.facts.parsers import supported_views
    from ai_lib_qor.sources.config_reader import raw_root_values

    cfg = load_path_config(work)
    raw_paths = raw_root_values(cfg)
    raw_roots = [raw_paths] if isinstance(raw_paths, str) and raw_paths else (list(raw_paths) if isinstance(raw_paths, list) else [])
    plugins_catalog = [
        {
            'name': name,
            'version': (PATH_CHECK_PLUGIN_META.get(name) or {}).get('version', '1.0'),
            'description': (PATH_CHECK_PLUGIN_META.get(name) or {}).get('description', ''),
            'required_views': list((PATH_CHECK_PLUGIN_META.get(name) or {}).get('required_views') or []),
            'requires_baseline': bool((PATH_CHECK_PLUGIN_META.get(name) or {}).get('requires_baseline', False)),
        }
        for name in PATH_CHECK_PLUGINS
    ]
    eff_plugins = effective_check_plugins(work)
    schema_error = None
    try:
        validate_path_config(cfg)
    except ValueError as exc:
        schema_error = str(exc)
    return {
        'work': str(Path(work).resolve()),
        'schema_valid': schema_error is None,
        'schema_error': schema_error,
        'raw_roots': raw_roots,
        'nl_root': cfg.get('nl_root') or '',
        'nl_version': cfg.get('nl_version') or '',
        'update_options': update_options(cfg),
        'skip_parse_views': skip_parse_views(work),
        'initial_delivery_tail': initial_delivery_tail(work),
        'liberty_parse_filter': liberty_parse_filter(work),
        'plugin_modules': configured_plugin_modules(work),
        'check_plugins': cfg.get('check_plugins'),
        'check_plugins_by_ip_type': cfg.get('check_plugins_by_ip_type') or {},
        'check_plugin_params': cfg.get('check_plugin_params') or {},
        'check_plugin_params_by_ip_type': cfg.get('check_plugin_params_by_ip_type') or {},
        'effective_check_plugins': eff_plugins if eff_plugins is not None else list(PATH_CHECK_PLUGINS.keys()),
        'effective_plugin_params': effective_plugin_params(work),
        'workbench': workbench_runtime_settings(work),
        'available_plugins': plugins_catalog,
        'supported_views': sorted(supported_views()),
        'config': cfg,
    }


def get_library_config_view(work, vendor: str, library: str) -> dict:
    """Read-only structured view of per-library overrides + effective inherited values."""
    from ai_lib_qor.checks.path_plugins import PATH_CHECK_PLUGIN_META, PATH_CHECK_PLUGINS
    from ai_lib_qor.facts.parsers import supported_views

    cfg = load_path_config(work)
    lib_raw = deepcopy(cfg.get('libraries', {}).get(vendor, {}).get(library, {}) or {})
    ip_cfg = library_ip_config(work, vendor, library)
    eff_skip = skip_parse_views(work, vendor, library)
    ws_skip = skip_parse_views(work)
    eff_tail = initial_delivery_tail(work, vendor, library)
    ws_tail = initial_delivery_tail(work)
    eff_lf = liberty_parse_filter(work, vendor, library)
    ws_lf = liberty_parse_filter(work)
    eff_plugins = effective_check_plugins(work, vendor, library, ip_type=ip_cfg['ip_type'])
    ws_plugins = effective_check_plugins(work, ip_type=ip_cfg['ip_type'])
    all_plugins = list(PATH_CHECK_PLUGINS.keys())
    plugins_catalog = [
        {
            'name': name,
            'version': (PATH_CHECK_PLUGIN_META.get(name) or {}).get('version', '1.0'),
            'description': (PATH_CHECK_PLUGIN_META.get(name) or {}).get('description', ''),
            'required_views': list((PATH_CHECK_PLUGIN_META.get(name) or {}).get('required_views') or []),
            'requires_baseline': bool((PATH_CHECK_PLUGIN_META.get(name) or {}).get('requires_baseline', False)),
        }
        for name in all_plugins
    ]
    return {
        'vendor': vendor,
        'library': library,
        'ip_type': ip_cfg['ip_type'],
        'ip_list': ip_cfg['ip_list'],
        'is_multi_track': ip_cfg['is_multi_track'],
        'overrides': {
            'has_skip_parse_views': 'skip_parse_views' in lib_raw,
            'skip_parse_views': lib_raw.get('skip_parse_views'),
            'has_initial_delivery_tail': 'initial_delivery_tail' in lib_raw,
            'initial_delivery_tail': lib_raw.get('initial_delivery_tail'),
            'has_liberty_parse_filter': 'liberty_parse_filter' in lib_raw,
            'liberty_parse_filter': lib_raw.get('liberty_parse_filter'),
            'has_check_plugins': 'check_plugins' in lib_raw,
            'check_plugins': lib_raw.get('check_plugins'),
            'has_check_plugin_params': 'check_plugin_params' in lib_raw,
            'check_plugin_params': lib_raw.get('check_plugin_params'),
            'excluded_versions': list(lib_raw.get('excluded_versions') or []),
            'ignored_unadopted_files': list(lib_raw.get('ignored_unadopted_files') or []),
        },
        'effective': {
            'skip_parse_views': eff_skip,
            'initial_delivery_tail': eff_tail,
            'liberty_parse_filter': eff_lf,
            'check_plugins': eff_plugins if eff_plugins is not None else all_plugins,
            'plugin_params': effective_plugin_params(work, vendor, library, ip_type=ip_cfg['ip_type']),
        },
        'workspace_defaults': {
            'skip_parse_views': ws_skip,
            'initial_delivery_tail': ws_tail,
            'liberty_parse_filter': ws_lf,
            'check_plugins': ws_plugins if ws_plugins is not None else all_plugins,
        },
        'available_plugins': plugins_catalog,
        'supported_views': sorted(supported_views()),
    }


def update_workspace_config(work, updates: dict) -> dict:
    """Validate and atomically update workspace-level fields in `path_sources.json`."""
    if not isinstance(updates, dict):
        raise ValueError('配置更新内容必须是 JSON 对象')
    allowed_keys = {
        'raw_root', 'raw_roots', 'nl_root', 'nl_version',
        'update_raw', 'update_formal', 'update_index', 'auto_effective',
        'skip_parse_views', 'initial_delivery_tail', 'liberty_parse_filter',
        'plugin_modules', 'check_plugins', 'check_plugins_by_ip_type',
        'check_plugin_params', 'check_plugin_params_by_ip_type',
        'ignore_patterns', 'view_extensions', 'workbench',
    }
    unknown = sorted(set(updates) - allowed_keys)
    if unknown:
        raise ValueError(f'工作区配置包含未知字段: {", ".join(unknown)}')

    root = Path(work)
    with locked(root):
        cfg = deepcopy(load_path_config(root))
        for k, v in updates.items():
            if k == 'workbench':
                if not isinstance(v, dict):
                    raise ValueError('workbench 必须为对象')
                merged_wb = {**(cfg.get('workbench') or {}), **v}
                for wk in ('max_workers', 'index_page_size', 'json_inventory_page_size'):
                    if wk in merged_wb and merged_wb[wk] is None:
                        merged_wb.pop(wk, None)
                cfg['workbench'] = merged_wb
            elif k == 'skip_parse_views':
                cfg['skip_parse_views'] = [] if v is None else _normalize_view_list(v, 'skip_parse_views')
            elif k == 'initial_delivery_tail':
                cfg['initial_delivery_tail'] = 0 if (v is None or v == 0) else _validate_tail_value(v, 'initial_delivery_tail')
            elif k == 'liberty_parse_filter':
                if v is None:
                    cfg['liberty_parse_filter'] = None
                else:
                    cfg['liberty_parse_filter'] = _validate_liberty_filter_dict(v, source_label='liberty_parse_filter')
            elif k == 'check_plugins':
                if v is None:
                    cfg.pop('check_plugins', None)
                else:
                    cfg['check_plugins'] = _normalize_plugin_policy(v, source_label='check_plugins')
            elif k == 'check_plugins_by_ip_type':
                if v is None:
                    cfg.pop('check_plugins_by_ip_type', None)
                elif not isinstance(v, dict):
                    raise ValueError('check_plugins_by_ip_type 必须是对象')
                else:
                    clean_map = {}
                    for ip_t, pol in v.items():
                        if not isinstance(ip_t, str) or not ip_t.strip():
                            raise ValueError('check_plugins_by_ip_type 存在无效 IP 类型名')
                        if pol is not None:
                            clean_map[ip_t.strip()] = _normalize_plugin_policy(pol, source_label=f'check_plugins_by_ip_type.{ip_t}')
                    cfg['check_plugins_by_ip_type'] = clean_map
            elif k == 'raw_roots':
                if v is None:
                    cfg['raw_roots'] = []
                elif isinstance(v, list) and all(isinstance(x, str) for x in v):
                    cfg['raw_roots'] = [x.strip() for x in v if x.strip()]
                else:
                    raise ValueError('raw_roots 必须是字符串数组')
            else:
                cfg[k] = v
        # Validate check plugin references before persisting
        if 'check_plugins' in updates or 'check_plugins_by_ip_type' in updates:
            from ai_lib_qor.checks.path_plugins import PATH_CHECK_PLUGINS
            reg = set(PATH_CHECK_PLUGINS.keys())
            for pol_label, pol in [
                ('check_plugins', cfg.get('check_plugins')),
                *((f'check_plugins_by_ip_type.{t}', p) for t, p in (cfg.get('check_plugins_by_ip_type') or {}).items()),
            ]:
                if isinstance(pol, dict):
                    for fld in ('enabled', 'disabled'):
                        bad = [p for p in (pol.get(fld) or []) if p not in reg]
                        if bad:
                            raise ValueError(f'{pol_label}.{fld} 包含未注册的检查插件: {", ".join(bad)}')
        save_path_config(root, cfg, already_locked=True)
    return get_workspace_config_view(root)


def update_library_config(work, vendor: str, library: str, updates: dict) -> dict:
    """Validate and atomically update per-library overrides in `path_sources.json`.

    Passing `None` for override fields (`skip_parse_views`, `initial_delivery_tail`,
    `liberty_parse_filter`, `check_plugins`) with `inherit_<field>: True` (or `None` when reset)
    removes the per-library override so it inherits workspace defaults cleanly.
    """
    from ai_lib_qor.sources.layout import SAFE, library_folder

    if not SAFE.fullmatch(vendor or '') or not SAFE.fullmatch(library or ''):
        raise ValueError('供应商或库名无效')
    if not isinstance(updates, dict):
        raise ValueError('单库配置更新内容必须是 JSON 对象')
    allowed_keys = {
        'ip_type', 'ip_list',
        'skip_parse_views', 'inherit_skip_parse_views',
        'initial_delivery_tail', 'inherit_initial_delivery_tail',
        'liberty_parse_filter', 'inherit_liberty_parse_filter',
        'check_plugins', 'inherit_check_plugins',
        'check_plugin_params', 'inherit_check_plugin_params',
    }
    unknown = sorted(set(updates) - allowed_keys)
    if unknown:
        raise ValueError(f'单库配置包含未知字段: {", ".join(unknown)}')

    root = Path(work)
    folder = library_folder(root, vendor, library)
    if not folder.is_dir():
        raise ValueError(f'库目录不存在: {vendor}/{library}')

    with locked(folder):
        with locked(root):
            cfg = deepcopy(load_path_config(root))
            lib_item = cfg.setdefault('libraries', {}).setdefault(vendor, {}).setdefault(library, {})

            if 'ip_type' in updates:
                raw_t = updates['ip_type']
                if raw_t is None or (isinstance(raw_t, str) and not raw_t.strip()):
                    lib_item.pop('ip_type', None)
                elif isinstance(raw_t, str):
                    lib_item['ip_type'] = raw_t.strip()
                else:
                    raise ValueError('ip_type 必须为字符串或 null')

            if 'ip_list' in updates:
                cleaned_ips = _clean_ip_list_input(updates['ip_list'])
                if cleaned_ips:
                    lib_item['ip_list'] = cleaned_ips
                else:
                    lib_item.pop('ip_list', None)

            if updates.get('inherit_skip_parse_views'):
                lib_item.pop('skip_parse_views', None)
            elif 'skip_parse_views' in updates:
                v = updates['skip_parse_views']
                lib_item['skip_parse_views'] = [] if v is None else _normalize_view_list(
                    v, f'libraries.{vendor}.{library}.skip_parse_views'
                )

            if updates.get('inherit_initial_delivery_tail'):
                lib_item.pop('initial_delivery_tail', None)
            elif 'initial_delivery_tail' in updates:
                v = updates['initial_delivery_tail']
                lib_item['initial_delivery_tail'] = 0 if (v is None or v == 0) else _validate_tail_value(
                    v, f'libraries.{vendor}.{library}.initial_delivery_tail'
                )

            if updates.get('inherit_liberty_parse_filter'):
                lib_item.pop('liberty_parse_filter', None)
            elif 'liberty_parse_filter' in updates:
                v = updates['liberty_parse_filter']
                if v is None:
                    lib_item['liberty_parse_filter'] = None
                else:
                    lib_item['liberty_parse_filter'] = _validate_liberty_filter_dict(
                        v, source_label=f'libraries.{vendor}.{library}.liberty_parse_filter'
                    )

            if updates.get('inherit_check_plugins'):
                lib_item.pop('check_plugins', None)
            elif 'check_plugins' in updates:
                v = updates['check_plugins']
                if v is None:
                    lib_item.pop('check_plugins', None)
                else:
                    pol = _normalize_plugin_policy(v, source_label=f'libraries.{vendor}.{library}.check_plugins')
                    from ai_lib_qor.checks.path_plugins import PATH_CHECK_PLUGINS
                    reg = set(PATH_CHECK_PLUGINS.keys())
                    for fld in ('enabled', 'disabled'):
                        bad = [p for p in (pol.get(fld) or []) if p not in reg]
                        if bad:
                            raise ValueError(f'libraries.{vendor}.{library}.check_plugins.{fld} 包含未注册的检查插件: {", ".join(bad)}')
                    # Ensure effective plugin set is non-empty
                    test_enabled = pol['enabled'] if pol['enabled'] is not None else list(PATH_CHECK_PLUGINS.keys())
                    rem = [p for p in test_enabled if p not in set(pol['disabled'] or [])]
                    if not rem:
                        raise ValueError('单库检查插件配置生效后为空，请至少保留一个启用的检查插件')
                    lib_item['check_plugins'] = pol

            if updates.get('inherit_check_plugin_params'):
                lib_item.pop('check_plugin_params', None)
            elif 'check_plugin_params' in updates:
                v = updates['check_plugin_params']
                if v is None:
                    lib_item.pop('check_plugin_params', None)
                elif isinstance(v, dict):
                    lib_item['check_plugin_params'] = deepcopy(v)
                else:
                    raise ValueError('check_plugin_params 必须是 JSON 对象或 null')

            save_path_config(root, cfg, already_locked=True)
    return get_library_config_view(root, vendor, library)
