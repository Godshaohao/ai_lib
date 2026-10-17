"""Context-aware bit identity, separate from declared orientation."""

import re


def normalize_port(port, *, aliases=None):
    name = (aliases or {}).get(port['name'], port['name'])
    bits, orientation = [name], None
    declared = port.get('declared_range')
    if declared:
        match = re.fullmatch(r'\[\s*(-?\d+)\s*:\s*(-?\d+)\s*\]', declared)
        if match:
            left, right = map(int, match.groups())
            orientation = [left, right]
            bits = [f'{name}[{bit}]' for bit in range(min(left, right), max(left, right) + 1)] if abs(left - right) < 4096 else None
            if port.get('width') is not None and port['width'] != abs(left - right) + 1:
                bits = None
        else:
            bits = None
    elif port.get('width') not in (None, 1) or (port.get('range_required') and port.get('width') != 1):
        bits = None
    elif not name.startswith('\\') and port.get('bus_chars') and len(port['bus_chars']) == 2:
        left, right = port['bus_chars']
        match = re.fullmatch(r'(.+)' + re.escape(left) + r'(-?\d+)' + re.escape(right), name)
        if match:
            bits = [f'{match[1]}[{int(match[2])}]']
    direction = str(port.get('direction') or '').upper()
    if direction not in {'INPUT', 'OUTPUT', 'INOUT'}:
        direction = 'UNKNOWN'
    return {**port, 'bits': bits, 'orientation': orientation, 'direction': direction}
