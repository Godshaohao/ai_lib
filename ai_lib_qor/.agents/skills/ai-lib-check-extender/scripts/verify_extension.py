#!/usr/bin/env python3
"""One-command validator for ai_lib_qor check plugins, corner tables, and EDA script templates.

Verifies:
1. Strict 7-layer unidirectional DAG (zero upward cross-layer imports across src/ai_lib_qor).
2. Zero UTF-8 BOM Python files in src/ai_lib_qor.
3. Every registered check plugin has complete metadata in PATH_CHECK_PLUGIN_META.
4. Built-in (and optional --work) EDA Jinja2 script templates compile cleanly under StrictUndefined.
5. Optional --work configs (path_sources.json, ip_partition_*.json, corner_acceptance.json) pass JSON Schema.
"""
import argparse
import ast
import json
from pathlib import Path
import sys

from jinja2 import Environment, FileSystemLoader, StrictUndefined

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC_ROOT = REPO_ROOT / 'src' / 'ai_lib_qor'
LAYER_RANK = {
    'versions': 0,
    'sources': 1,
    'facts': 2,
    'checks': 3,
    'application': 4,
    'reporting': 5,
    'workbench': 6,
}


def check_dag_and_bom() -> list[str]:
    errors = []
    for layer in LAYER_RANK:
        layer_dir = SRC_ROOT / layer
        if not layer_dir.is_dir():
            continue
        for py in sorted(layer_dir.rglob('*.py')):
            raw = py.read_bytes()
            rel = py.relative_to(REPO_ROOT).as_posix()
            if raw.startswith(b'\xef\xbb\xbf'):
                errors.append(f'UTF-8 BOM detected: {rel}')
            tree = ast.parse(raw.decode('utf-8-sig'), filename=rel)
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module]
                for m in mods:
                    if not m.startswith('ai_lib_qor.'):
                        continue
                    parts = m.split('.')
                    if len(parts) >= 2 and parts[1] in LAYER_RANK:
                        tgt = parts[1]
                        if LAYER_RANK[tgt] > LAYER_RANK[layer]:
                            errors.append(f'DAG violation: {rel}:{node.lineno} ({layer}) -> {m} ({tgt})')
    return errors


def check_plugins(work: Path | None) -> tuple[list[str], int]:
    if work is not None:
        from ai_lib_qor.application.plugin_loader import load_configured_plugins
        load_configured_plugins(work)
    from ai_lib_qor.checks.path_plugins import PATH_CHECK_PLUGIN_META, PATH_CHECK_PLUGINS

    errors = []
    for name, fn in PATH_CHECK_PLUGINS.items():
        if not callable(fn):
            errors.append(f'Plugin {name} is not callable')
        meta = PATH_CHECK_PLUGIN_META.get(name)
        if not isinstance(meta, dict):
            errors.append(f'Plugin {name} missing PATH_CHECK_PLUGIN_META entry')
            continue
        for key in ('version', 'description', 'required_views', 'requires_baseline', 'needs_facts', 'category'):
            if key not in meta:
                errors.append(f'Plugin {name} metadata missing key: {key}')
    return errors, len(PATH_CHECK_PLUGINS)


def check_templates(work: Path | None) -> tuple[list[str], int]:
    from ai_lib_qor.reporting.eda_scripts import list_script_templates

    errors = []
    tpls = list_script_templates(work)
    dummy_vars = {
        'vendor': 'V',
        'library': 'LIB',
        'business_ip': None,
        'ip_type': 'SRAM',
        'revision': 'rev_0001',
        'generated_at': '2026-11-24T00:00:00Z',
        'template': 'demo',
        'template_source': 'check',
        'output_dir': './run_demo',
        'deliveries_used': ['20261001_v1'],
        'members': [],
        'members_by_view': {},
        'lef_files': [{'view': 'LEF', 'path': 'LEF/a.lef', 'version': '20261001_v1', 'absolute_path': '/tmp/a.lef'}],
        'db_files': [{'view': 'DB', 'path': 'DB/a.db', 'version': '20261001_v1', 'absolute_path': '/tmp/a.db'}],
        'lib_files': [{'view': 'LIBERTY', 'path': 'LIB/a.lib', 'version': '20261001_v1', 'absolute_path': '/tmp/a.lib'}],
        'verilog_files': [],
        'gds_files': [],
        'cdl_files': [],
        'counts': {'LEF': 1, 'DB': 1, 'LIBERTY': 1, 'VERILOG': 0, 'GDS': 0, 'CDL': 0, 'TOTAL': 3},
    }
    for info in tpls:
        p = Path(info['path'])
        try:
            env = Environment(loader=FileSystemLoader(str(p.parent)), autoescape=False, undefined=StrictUndefined)
            env.get_template(p.name).render(**dummy_vars)
        except Exception as exc:
            errors.append(f'Template render error ({info["name"]} @ {p}): {exc}')
    return errors, len(tpls)


def check_report_pipelines_smoke() -> list[str]:
    """Smoke-verify offline HTML report & Excel findings unpacker remain decoupled and functional."""
    from ai_lib_qor.checks.path_plugins import evaluate_check_verdict
    from ai_lib_qor.reporting.html_report import render_check_html_report, render_overall_html_report
    from ai_lib_qor.reporting.workbook_diff import unpack_plugin_findings

    errors = []
    sample_check = {
        'check_id': 'SMOKE_RULE',
        'scope_file_keys': ['LIB/demo_tt_25c.lib'],
        'result': 'FAIL',
        'severity': 'ERROR',
        'coverage': 'MANIFEST',
        'facts_refs': [],
        'detail': '冒烟测试缺失项',
        'findings': [{
            'view': 'DB',
            'path': 'LIB/demo_tt_25c.lib',
            'object_type': 'LIB_DB_PAIR',
            'object_name': 'demo_tt_25c.lib',
            'diff_type': 'MISSING_DB',
            'old_value': '1',
            'new_value': '0',
            'detail': '缺少对应 .db',
        }],
    }
    try:
        rows, badges = unpack_plugin_findings([sample_check], {})
        if len(rows) != 1 or not badges:
            errors.append('Excel unpack_plugin_findings did not unpack synthetic finding')
    except Exception as exc:
        errors.append(f'Excel unpack_plugin_findings error: {exc}')

    try:
        rep = {
            'vendor': 'V', 'library': 'L', 'revision': 'rev_0001', 'baseline': None,
            'run_at': '2026-11-25T00:00:00Z', 'state': 'PARTIAL', 'note': 'smoke',
            'files': [], 'checks': [sample_check], 'comparisons': [], 'partial_comparisons': [],
            'changes': [], 'summary': {'failed_checks': 1, 'inconclusive_checks': 0, 'failed_files': 0,
                                       'files_with_new_source': 0, 'files_with_confirmed_content_change': 0},
            'tooling': {'plugins': ['SMOKE_RULE']},
        }
        verdict = evaluate_check_verdict(rep)
        html = render_check_html_report({
            'vendor': 'V', 'library': 'L', 'business_ip': None, 'ip_type': None,
            'check_name': 'check_L_rev_0001_20261125.json', 'report': rep, 'quality': verdict,
            'checks': [sample_check], 'file_rows': [], 'comparisons': [], 'partial_comparisons': [],
            'changes': [], 'view_coverage': [], 'parse_counts': {}, 'source_counts': {}, 'content_counts': {},
            'views_present': [], 'tooling': rep['tooling'],
            'tooling_status': {'status': 'CURRENT', 'is_stale': False, 'reasons': []},
            'acceptance': None, 'excel_name': None, 'excel_cached': False,
        })
        if 'SMOKE_RULE' not in html or '<!doctype html>' not in html.lower():
            errors.append('Offline check HTML report missing expected content')
        ov_html = render_overall_html_report({
            'vendor': 'V', 'library': 'L', 'business_ip': None, 'ip_type': None,
            'overall_name': 'overall_L_20261125.json', 'accepted_revision': None,
            'totals': {
                'revisions': 1, 'pass_count': 0, 'partial_count': 0, 'fail_count': 1,
                'failed_checks_total': 1, 'content_diff_files_total': 0,
            },
            'versions': [{
                'revision': 'rev_0001', 'baseline': None, 'run_at': '2026-11-25T00:00:00Z',
                'is_accepted': False, 'quality': verdict, 'check_name': 'check_L_rev_0001_20261125.json',
                'parsed_files': 0, 'total_files': 0, 'parsed_pct': 0.0, 'failed_files': 0,
                'diff_files': 0, 'failed_checks': 1, 'inconclusive_checks': 0,
                'checks': [sample_check],
            }],
        })
        if 'SMOKE_RULE: FAIL' not in ov_html:
            errors.append('Offline overall HTML report missing expected content')
    except Exception as exc:
        errors.append(f'Offline HTML report smoke error: {exc}')
    return errors


def check_work_schemas(work: Path) -> list[str]:
    from ai_lib_qor.versions.store import validate

    errors = []
    cfg_path = work / 'path_sources.json'
    if cfg_path.is_file() and not cfg_path.is_symlink():
        try:
            validate(json.loads(cfg_path.read_text(encoding='utf-8')), 'path_sources')
        except Exception as exc:
            errors.append(f'path_sources.json invalid: {exc}')

    part_files = [
        *(sorted((work / 'libraries').glob('*/*/ip_partition.json')) if (work / 'libraries').is_dir() else []),
        *sorted(work.glob('ip_partition_*.json')),
    ]
    for p in part_files:
        if p.is_symlink() or not p.is_file():
            continue
        try:
            validate(json.loads(p.read_text(encoding='utf-8')), 'ip_partition')
        except Exception as exc:
            rel_p = p.relative_to(work).as_posix()
            errors.append(f'{rel_p} invalid: {exc}')

    corner_path = work / 'corner_acceptance.json'
    if corner_path.is_file() and not corner_path.is_symlink():
        try:
            validate(json.loads(corner_path.read_text(encoding='utf-8')), 'corner_acceptance')
        except Exception as exc:
            errors.append(f'corner_acceptance.json invalid: {exc}')
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description='Validate ai_lib_qor check plugins, corner tables, and EDA templates.')
    ap.add_argument('--work', help='Optional workspace directory to validate configs, corner table, and custom templates')
    args = ap.parse_args()

    work = Path(args.work).resolve() if args.work else None
    all_errors = []

    dag_errs = check_dag_and_bom()
    all_errors.extend(dag_errs)
    print(f'[1/5] Strict 7-layer DAG & UTF-8 BOM : {"OK" if not dag_errs else f"FAIL ({len(dag_errs)})"}')

    plg_errs, plg_cnt = check_plugins(work)
    all_errors.extend(plg_errs)
    print(f'[2/5] Check plugins metadata ({plg_cnt})     : {"OK" if not plg_errs else f"FAIL ({len(plg_errs)})"}')

    tpl_errs, tpl_cnt = check_templates(work)
    all_errors.extend(tpl_errs)
    print(f'[3/5] EDA script templates ({tpl_cnt})       : {"OK" if not tpl_errs else f"FAIL ({len(tpl_errs)})"}')

    rep_errs = check_report_pipelines_smoke()
    all_errors.extend(rep_errs)
    print(f'[4/5] HTML & Excel report smoke      : {"OK" if not rep_errs else f"FAIL ({len(rep_errs)})"}')

    if work is not None:
        sch_errs = check_work_schemas(work)
        all_errors.extend(sch_errs)
        print(f'[5/5] Workspace config schemas       : {"OK" if not sch_errs else f"FAIL ({len(sch_errs)})"}')
    else:
        print('[5/5] Workspace config schemas       : SKIPPED (no --work passed)')

    if all_errors:
        print('\nErrors:')
        for e in all_errors:
            print('  -', e)
        return 1
    print('\nALL EXTENSION CHECKS PASSED.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
