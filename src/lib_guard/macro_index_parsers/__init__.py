"""Private parser copies used by the standalone Macro Index workflow.

These parsers are intentionally isolated from ``lib_guard.scan`` so the
Macro Index can generate its own facts without a scan workspace.
"""

from .cdl import parse_cdl_file
from .lef import parse_lef_file
from .liberty import parse_liberty_file
from .verilog import parse_verilog_file

PARSER_BY_VIEW = {
    "lef": parse_lef_file,
    "liberty": parse_liberty_file,
    "verilog": parse_verilog_file,
    "cdl": parse_cdl_file,
}
