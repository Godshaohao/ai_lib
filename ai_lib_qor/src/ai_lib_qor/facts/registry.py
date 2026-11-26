"""Pluggable View -> Parser registry for FileFacts extraction."""
from contextlib import contextmanager
import gzip
import hashlib
import io
from pathlib import Path

from ._compat.cdl import CDL_PARSER_VERSION, parse_cdl_data_file
from ._compat.lef import LEF_PARSER_VERSION, parse_lef_data_file
from ._compat.liberty import LIBERTY_PARSER_VERSION, parse_liberty_interface_data_file
from ._compat.verilog import VERILOG_PARSER_VERSION, parse_verilog_data_file

ADAPTER_VERSION = '1.0'


class _HashingBinaryReader(io.BufferedIOBase):
    """Transparent buffered binary proxy computing raw-file SHA-256 in a single streaming read pass."""

    def __init__(self, raw):
        self._raw = raw
        self._hash = hashlib.sha256()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def read(self, size: int = -1) -> bytes:
        chunk = self._raw.read(size)
        if chunk:
            self._hash.update(chunk)
        return chunk

    def read1(self, size: int = -1) -> bytes:
        fn = getattr(self._raw, 'read1', self._raw.read)
        chunk = fn(size)
        if chunk:
            self._hash.update(chunk)
        return chunk

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

    def writable(self) -> bool:
        return False

    def flush(self) -> None:
        pass

    def close(self) -> None:
        # Underlying `raw` is closed by the outer `with path.open('rb')` context after hexdigest() drains it.
        self._closed = True

    def hexdigest(self) -> str:
        # Drain any trailing unread bytes (e.g. gzip trailer) so SHA-256 always covers the entire file.
        while True:
            tail = self._raw.read(1024 * 1024)
            if not tail:
                break
            self._hash.update(tail)
        return self._hash.hexdigest()


@contextmanager
def _open_strict_text_single_pass(path: Path, *, digest_out: dict | None = None, newline=None):
    """Open plain or .gz file once with strict UTF-8 decoding, optionally hashing raw bytes in the same pass."""
    is_gz = path.name.lower().endswith('.gz')
    if digest_out is None:
        opener = gzip.open if is_gz else open
        kwargs = {'encoding': 'utf-8', 'errors': 'strict'}
        if newline is not None:
            kwargs['newline'] = newline
        with opener(path, 'rt', **kwargs) as stream:
            yield stream
        return

    with path.open('rb') as raw:
        hashing = _HashingBinaryReader(raw)
        if is_gz:
            with gzip.GzipFile(fileobj=hashing, mode='rb') as gz_bin:
                with io.TextIOWrapper(gz_bin, encoding='utf-8', errors='strict', newline=newline) as txt:
                    yield txt
        else:
            with io.TextIOWrapper(hashing, encoding='utf-8', errors='strict', newline=newline) as txt:
                yield txt
        digest_out['sha256'] = hashing.hexdigest()


def _unique(items, label):
    names = [x['name'] for x in items]
    if len(names) != len(set(names)):
        raise ValueError(f'{label} 名称重复')
    return items


def _strict_encoding(path):
    opener = gzip.open if path.name.lower().endswith('.gz') else open
    with opener(path, 'rt', encoding='utf-8', errors='strict') as f:
        while f.read(1024 * 1024):
            pass


def parse_lef(path, *, allow_pg=False, digest_out=None):
    path = Path(path)
    with _open_strict_text_single_pass(path, digest_out=digest_out) as stream:
        parsed = parse_lef_data_file(path, errors='strict', stream_override=stream)
    coverage = parsed['semantic_coverage']
    if coverage['macro_set'] != 'PRESENT' or coverage['port_set'] != 'PRESENT':
        raise ValueError('LEF 结构不完整或解析覆盖不足')
    result = []
    for name, m in parsed['macros'].items():
        size = m.get('size')
        pins = []
        if isinstance(size, dict) and set(size) >= {'x', 'y'}:
            size = [size['x'], size['y']]
        if not isinstance(size, (list, tuple)) or len(size) != 2:
            raise ValueError(f'{name} 缺少可确认 SIZE')
        for pin, p in m['pins'].items():
            use = str(p.get('use') or '').upper()
            if use in {'POWER', 'GROUND'} and not allow_pg:
                raise ValueError(f'{name}/{pin} 是电源引脚，v3 事实无法保留 Pin 类型')
            if not p.get('direction'):
                raise ValueError(f'{name}/{pin} 缺少方向')
            row = {'name': pin, 'direction': p['direction']}
            if allow_pg and use:
                row['use'] = use
            pins.append(row)
        result.append({'name': name, 'size_um': list(size), 'pins': _unique(pins, 'Pin')})
    if not result:
        raise ValueError('LEF 不含可确认 Macro')
    sections = ['MACRO_NAME', 'MACRO_SIZE', 'PIN_NAME', 'PIN_DIRECTION'] + (['PIN_USE'] if allow_pg else [])
    return {
        'view': 'LEF',
        'parser': {'name': 'src_qor_lef', 'version': f'{LEF_PARSER_VERSION}+adapter-{ADAPTER_VERSION}'},
        'parse_status': 'COMPLETE',
        'covered_sections': sections,
        'units': {'distance': 'um'},
        'objects': {'macros': _unique(result, 'Macro')},
    }


def parse_liberty(path, *, allow_pg=False, digest_out=None):
    path = Path(path)
    with _open_strict_text_single_pass(path, digest_out=digest_out, newline='') as stream:
        parsed = parse_liberty_interface_data_file(path, errors='strict', stream_override=stream)
    if parsed['semantic_coverage']['port_set'] != 'PRESENT':
        raise ValueError('Liberty 结构不完整或接口覆盖不足')
    cells = []
    for lib in parsed['libraries'].values():
        for name, cell in lib['cells'].items():
            pins = []
            for pin, p in cell['pins'].items():
                if not p.get('direction'):
                    raise ValueError(f'{name}/{pin} 缺少方向')
                pins.append({'name': pin, 'direction': p['direction']})
            cells.append({'name': name, 'pins': _unique(pins, 'Pin')})
    if not cells:
        raise ValueError('Liberty 不含可确认 Cell')
    return {
        'view': 'LIBERTY',
        'parser': {'name': 'src_qor_liberty_interface', 'version': f'{LIBERTY_PARSER_VERSION}+adapter-{ADAPTER_VERSION}'},
        'parse_status': 'COMPLETE',
        'covered_sections': ['CELL_NAME', 'PIN_NAME', 'PIN_DIRECTION'],
        'units': {},
        'objects': {'cells': _unique(cells, 'Cell')},
    }


def parse_verilog(path, *, allow_pg=False):
    path = Path(path)
    _strict_encoding(path)
    parsed = parse_verilog_data_file(path)
    return {
        'view': 'VERILOG',
        'parser': {'name': 'src_qor_verilog', 'version': VERILOG_PARSER_VERSION},
        'parse_status': 'PARTIAL',
        'covered_sections': ['MODULE_NAME', 'PORT_OBSERVATIONS'],
        'units': {},
        'objects': {'modules': list(parsed['modules'].values())},
    }


parse_lef._parser_name = 'src_qor_lef'
parse_lef._parser_version = f'{LEF_PARSER_VERSION}+adapter-{ADAPTER_VERSION}'
parse_lef._parser_sig = f'{parse_lef._parser_name}:{parse_lef._parser_version}'

parse_liberty._parser_name = 'src_qor_liberty_interface'
parse_liberty._parser_version = f'{LIBERTY_PARSER_VERSION}+adapter-{ADAPTER_VERSION}'
parse_liberty._parser_sig = f'{parse_liberty._parser_name}:{parse_liberty._parser_version}'

parse_verilog._parser_name = 'src_qor_verilog'
parse_verilog._parser_version = VERILOG_PARSER_VERSION
parse_verilog._parser_sig = f'{parse_verilog._parser_name}:{parse_verilog._parser_version}'


def _make_netlist_parser(view_name):
    def _parse(path, *, allow_pg=False):
        path = Path(path)
        _strict_encoding(path)
        parsed = parse_cdl_data_file(path)
        return {
            'view': view_name,
            'parser': {'name': 'src_qor_cdl', 'version': CDL_PARSER_VERSION},
            'parse_status': 'PARTIAL',
            'covered_sections': ['SUBCIRCUIT_OBSERVATIONS', 'INSTANCE_OBSERVATIONS'],
            'units': {},
            'objects': {'subcircuits': list(parsed['subckts'].values()), 'includes': parsed['includes']},
        }
    _parse._parser_name = 'src_qor_cdl'
    _parse._parser_version = CDL_PARSER_VERSION
    _parse._parser_sig = f'src_qor_cdl:{CDL_PARSER_VERSION}:{view_name}'
    return _parse


PARSER_REGISTRY = {
    'LEF': parse_lef,
    'LIBERTY': parse_liberty,
    'VERILOG': parse_verilog,
    'CDL': _make_netlist_parser('CDL'),
    'SPICE': _make_netlist_parser('SPICE'),
}


def register_parser(view, handler, *, registry=PARSER_REGISTRY):
    if not isinstance(view, str) or not view.strip():
        raise ValueError('View 名称无效')
    if not callable(handler):
        raise ValueError('Parser 必须可调用')
    registry[view.upper()] = handler


def supported_views(*, registry=PARSER_REGISTRY):
    return tuple(registry.keys())


def get_parser(view, *, registry=PARSER_REGISTRY):
    handler = registry.get(view)
    if handler is None:
        raise ValueError(f'不支持解析的 View: {view}')
    return handler


def parser_signature(view, *, allow_pg=False, registry=PARSER_REGISTRY):
    """Deterministic parser identity used as part of content-addressed FileFacts pool keys."""
    handler = get_parser(view, registry=registry)
    sig = getattr(handler, '_parser_sig', None) or getattr(handler, 'parser_version', None)
    if not sig:
        sig = f'custom:{getattr(handler, "__module__", "")}.{getattr(handler, "__qualname__", repr(handler))}'
    return f'{view}|{sig}|pg={int(bool(allow_pg))}'


def current_parser_info(view, *, allow_pg=True, registry=PARSER_REGISTRY):
    """Return active parser metadata (name, version, signature) for tooling freshness comparison."""
    handler = registry.get(view)
    if handler is None:
        return None
    name = getattr(handler, '_parser_name', None)
    version = getattr(handler, '_parser_version', None) or getattr(handler, 'parser_version', None)
    return {
        'view': view,
        'name': name,
        'version': version,
        'signature': parser_signature(view, allow_pg=allow_pg, registry=registry),
    }
