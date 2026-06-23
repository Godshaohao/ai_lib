"""
lib_guard.scan.parsers

Parser package for lib_guard scan.

Design:
- No text.py. Generic file helpers live in base.py.
- Each format module exposes standalone parse_*_file / parse_*_text helpers.
- Each format module also exposes a XxxParser class for ScanRunner.
"""
from __future__ import annotations

from .base import BaseParser, ParserIssue, make_parser_envelope, read_text_file
from .lef import LefParser, parse_lef_file, parse_lef_text, diff_lef_files, diff_lef_summary
from .liberty import LibertyParser, parse_liberty_file, parse_liberty_text, diff_liberty_files, diff_liberty_summary
from .db import DbParser, parse_db_file, probe_db_file
from .verilog import VerilogParser, parse_verilog_file, parse_verilog_text, diff_verilog_files, diff_verilog_summary
from .cdl import CdlParser, parse_cdl_file, parse_cdl_text, diff_cdl_files, diff_cdl_summary
from .sdc import SdcParser, parse_sdc_file, parse_sdc_text
from .upf import UpfParser, parse_upf_file, parse_upf_text
from .cpf import CpfParser, parse_cpf_file, parse_cpf_text
from .spef import SpefParser, parse_spef_file, parse_spef_text
from .ibis import IbisParser, parse_ibis_file, parse_ibis_text
from .pwl import PwlParser, parse_pwl_file, parse_pwl_text
from .snp import SnpParser, parse_snp_file, parse_snp_text
from .cpm import CpmParser, parse_cpm_file, parse_cpm_text
from .filelist import FilelistParser, parse_filelist_file, parse_filelist_text
from .package import PackageParser, parse_package_file, parse_package_text, parse_touchstone_file
from .waiver import WaiverParser, parse_waiver_file, parse_waiver_text

__all__ = [
    'BaseParser', 'ParserIssue', 'make_parser_envelope', 'read_text_file',
    'LefParser', 'parse_lef_file', 'parse_lef_text', 'diff_lef_files', 'diff_lef_summary',
    'LibertyParser', 'parse_liberty_file', 'parse_liberty_text', 'diff_liberty_files', 'diff_liberty_summary',
    'DbParser', 'parse_db_file', 'probe_db_file',
    'VerilogParser', 'parse_verilog_file', 'parse_verilog_text', 'diff_verilog_files', 'diff_verilog_summary',
    'CdlParser', 'parse_cdl_file', 'parse_cdl_text', 'diff_cdl_files', 'diff_cdl_summary',
    'SdcParser', 'parse_sdc_file', 'parse_sdc_text',
    'UpfParser', 'parse_upf_file', 'parse_upf_text',
    'CpfParser', 'parse_cpf_file', 'parse_cpf_text',
    'SpefParser', 'parse_spef_file', 'parse_spef_text',
    'IbisParser', 'parse_ibis_file', 'parse_ibis_text',
    'PwlParser', 'parse_pwl_file', 'parse_pwl_text',
    'SnpParser', 'parse_snp_file', 'parse_snp_text',
    'CpmParser', 'parse_cpm_file', 'parse_cpm_text',
    'FilelistParser', 'parse_filelist_file', 'parse_filelist_text',
    'PackageParser', 'parse_package_file', 'parse_package_text', 'parse_touchstone_file',
    'WaiverParser', 'parse_waiver_file', 'parse_waiver_text',
]

