"""Runtime plugin loader (path_sources.json `plugin_modules` + env `AI_LIB_QOR_PLUGIN_MODULES`) and test isolation helper."""
import contextlib
import copy
import importlib
import os
import re

from ai_lib_qor.checks.path_plugins import PATH_CHECK_PLUGIN_META, PATH_CHECK_PLUGINS, register_path_plugin
from ai_lib_qor.facts.registry import PARSER_REGISTRY, register_parser
from ai_lib_qor.sources.root_inventory import VIEW_EXTENSIONS, register_view_extension
from .path_config import configured_plugin_modules

_MODULE_NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z')
_LOADED_MODULES: set[str] = set()


def _plugin_api():
    return {
        'register_view_extension': register_view_extension,
        'register_parser': register_parser,
        'register_path_plugin': register_path_plugin,
    }


def load_plugin_module(module_name: str, *, force: bool = False) -> bool:
    """Import a dotted Python plugin module and invoke its optional `register(api)` hook."""
    if not isinstance(module_name, str) or not _MODULE_NAME_RE.fullmatch(module_name):
        raise ValueError(f'插件模块名称不合法: {module_name}')
    if not force and module_name in _LOADED_MODULES:
        return False
    mod = importlib.import_module(module_name)
    hook = getattr(mod, 'register', None)
    if callable(hook):
        hook(_plugin_api())
    _LOADED_MODULES.add(module_name)
    return True


def load_configured_plugins(work=None, *, force: bool = False) -> list[str]:
    """Load plugin modules configured in work/path_sources.json (`plugin_modules`) and AI_LIB_QOR_PLUGIN_MODULES."""
    names = []
    if work is not None:
        names.extend(configured_plugin_modules(work))
    env_raw = os.environ.get('AI_LIB_QOR_PLUGIN_MODULES', '').strip()
    if env_raw:
        for part in env_raw.split(':'):
            part = part.strip()
            if part:
                names.append(part)
    loaded = []
    for name in dict.fromkeys(names):
        if load_plugin_module(name, force=force):
            loaded.append(name)
    return loaded


@contextlib.contextmanager
def isolated_registries():
    """Context manager snapshotting and restoring global View/Parser/Plugin registries (for tests)."""
    orig_ext = dict(VIEW_EXTENSIONS)
    orig_parsers = dict(PARSER_REGISTRY)
    orig_plugins = dict(PATH_CHECK_PLUGINS)
    orig_meta = copy.deepcopy(PATH_CHECK_PLUGIN_META)
    orig_loaded = set(_LOADED_MODULES)
    try:
        yield _plugin_api()
    finally:
        VIEW_EXTENSIONS.clear()
        VIEW_EXTENSIONS.update(orig_ext)
        PARSER_REGISTRY.clear()
        PARSER_REGISTRY.update(orig_parsers)
        PATH_CHECK_PLUGINS.clear()
        PATH_CHECK_PLUGINS.update(orig_plugins)
        PATH_CHECK_PLUGIN_META.clear()
        PATH_CHECK_PLUGIN_META.update(orig_meta)
        _LOADED_MODULES.clear()
        _LOADED_MODULES.update(orig_loaded)
