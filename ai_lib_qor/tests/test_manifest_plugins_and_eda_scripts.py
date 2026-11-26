"""Tests for LIB_DB_PAIRING, LIBERTY_CORNER_COVERAGE (IP->Group->Corner table), plugin_params, and EDA .csh script generator."""
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from ai_lib_qor.application.minimal_checks import run_revision
from ai_lib_qor.application.path_config import (
    effective_plugin_params,
    save_path_config,
    update_library_config,
    update_workspace_config,
)
from ai_lib_qor.application.path_refresh import refresh_all
from ai_lib_qor.cli import parser as cli_parser, run as cli_run
from ai_lib_qor.reporting.eda_scripts import export_eda_script, list_script_templates, render_eda_script
from ai_lib_qor.versions.store import validate
from ai_lib_qor.workbench.path_app import create_path_app

_LEF = 'MACRO M1\n SIZE 2 BY 3 ;\n PIN A\n  DIRECTION INPUT ;\n END A\nEND M1\n'
_LIB = 'library(demo) {\n cell(M1) {\n  pin(A) { direction : input; }\n }\n}\n'


class ManifestPluginsAndEdaScriptsTests(unittest.TestCase):
    def _create_lib_with_files(self, td: str, files: dict[str, bytes | str], *, lib_cfg: dict | None = None, ws_extra: dict | None = None):
        root = Path(td)
        raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
        nl.mkdir(exist_ok=True)
        work.mkdir(exist_ok=True)
        v1 = raw / 'V1' / 'SRAM_LIB' / '20261001_v1'
        for rel, content in files.items():
            fp = v1 / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                fp.write_bytes(content)
            else:
                fp.write_text(content, encoding='utf-8')
            link = nl / Path(rel).name
            if not link.exists():
                link.symlink_to(fp)
        cfg = {
            'raw_roots': [str(raw)],
            'nl_root': str(nl),
            'nl_version': 'NL1',
            'libraries': {'V1': {'SRAM_LIB': lib_cfg or {'ip_type': 'SRAM'}}},
            **(ws_extra or {}),
        }
        save_path_config(work, cfg)
        refresh_all(work)
        return raw, nl, work

    def test_example_corner_acceptance_table_passes_schema(self):
        repo_root = Path(__file__).resolve().parents[1]
        example = repo_root / 'examples' / 'corner_acceptance.example.json'
        self.assertTrue(example.is_file())
        data = json.loads(example.read_text(encoding='utf-8'))
        validate(data, 'corner_acceptance')
        self.assertIn('_note', data)
        self.assertIn('STDCELL_G1', data['groups'])
        self.assertIn('SRAM_G1', data['groups'])
        self.assertIn('ip_groups', data)

    def test_compact_corner_table_two_symbol_syntax_and_business_ip_only(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, work = self._create_lib_with_files(td, {
                'LEF/sram.lef': _LEF,
                'LIB/sram_typ_25c.lib': _LIB,
                'LIB/sram_slow_125c.lib': _LIB,
            })
            compact = {
                '_note': ['测试备注'],
                'groups': {
                    'SRAM_G1': ['tt|typ+25c', 'ss|slow+125c'],
                    'SRAM_G2': ['tt|typ+25c', 'ff|fast+-40c'],
                },
                'ip_groups': {
                    'SRAM_*': 'SRAM_G1',
                },
            }
            (work / 'corner_acceptance.json').write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding='utf-8')
            res1 = run_revision(work, 'V1', 'SRAM_LIB', 'rev_0001', render=False)
            rep1 = json.loads(Path(res1['check']).read_text(encoding='utf-8'))
            cc1 = [c for c in rep1['checks'] if c['check_id'] == 'LIBERTY_CORNER_COVERAGE']
            self.assertEqual(len(cc1), 1)
            self.assertEqual(cc1[0]['result'], 'PASS')

            # Exact business IP / library name overrides wildcard pattern
            compact['ip_groups']['SRAM_LIB'] = 'SRAM_G2'
            (work / 'corner_acceptance.json').write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding='utf-8')
            res2 = run_revision(work, 'V1', 'SRAM_LIB', 'rev_0001', render=False)
            rep2 = json.loads(Path(res2['check']).read_text(encoding='utf-8'))
            cc2 = [c for c in rep2['checks'] if c['check_id'] == 'LIBERTY_CORNER_COVERAGE']
            self.assertEqual(len(cc2), 1)
            self.assertEqual(cc2[0]['result'], 'FAIL')
            self.assertEqual(cc2[0]['findings'][0]['object_name'], 'ff|fast+-40c')

            # Unmapped business IP returns INCONCLUSIVE (never fake PASS)
            compact['ip_groups'] = {'OTHER_IP': 'SRAM_G1'}
            (work / 'corner_acceptance.json').write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding='utf-8')
            res3 = run_revision(work, 'V1', 'SRAM_LIB', 'rev_0001', render=False)
            rep3 = json.loads(Path(res3['check']).read_text(encoding='utf-8'))
            cc3 = [c for c in rep3['checks'] if c['check_id'] == 'LIBERTY_CORNER_COVERAGE']
            self.assertEqual(len(cc3), 1)
            self.assertEqual(cc3[0]['result'], 'INCONCLUSIVE')

    def test_lib_db_pairing_pass_fail_and_zero_db_read(self):
        with tempfile.TemporaryDirectory() as td:
            # 1. Complete 1:1 .lib <-> .db pairing (binary non-UTF8 bytes in .db MUST NEVER be read!)
            _, _, work = self._create_lib_with_files(td, {
                'LEF/sram.lef': _LEF,
                'LIB/sram_tt_25c.lib': _LIB,
                'LIB/sram_ss_125c.lib': _LIB,
                'DB/sram_tt_25c.db': b'\x89\x00\xffSYNOPSYS_BINARY_DB_1',
                'DB/sram_ss_125c.db': b'\x89\x00\xffSYNOPSYS_BINARY_DB_2',
            })
            res = run_revision(work, 'V1', 'SRAM_LIB', 'rev_0001', render=False)
            report = json.loads(Path(res['check']).read_text(encoding='utf-8'))
            pairing = [c for c in report['checks'] if c['check_id'] == 'LIB_DB_PAIRING']
            self.assertEqual(len(pairing), 1)
            self.assertEqual(pairing[0]['result'], 'PASS')
            self.assertEqual(pairing[0]['coverage'], 'MANIFEST')
            self.assertIn('已配对 2 组', pairing[0]['detail'])

        with tempfile.TemporaryDirectory() as td:
            # 2. Missing .db + orphan .db -> FAIL with structured findings
            _, _, work = self._create_lib_with_files(td, {
                'LEF/sram.lef': _LEF,
                'LIB/sram_tt_25c.lib': _LIB,
                'LIB/sram_ss_125c.lib': _LIB,
                'DB/sram_tt_25c.db': b'\x00\x01',
                'DB/sram_orphan_ff.db': b'\x00\x02',
            })
            res = run_revision(work, 'V1', 'SRAM_LIB', 'rev_0001', render=False)
            report = json.loads(Path(res['check']).read_text(encoding='utf-8'))
            pairing = [c for c in report['checks'] if c['check_id'] == 'LIB_DB_PAIRING']
            self.assertEqual(len(pairing), 1)
            self.assertEqual(pairing[0]['result'], 'FAIL')
            diff_types = {f['diff_type'] for f in pairing[0]['findings']}
            self.assertEqual(diff_types, {'MISSING_DB', 'ORPHAN_DB'})

        with tempfile.TemporaryDirectory() as td:
            # 3. Zero .db with require_db=True + skip_parse_views=['LIBERTY'] still runs (needs_facts=False!)
            _, _, work = self._create_lib_with_files(
                td,
                {'LEF/sram.lef': _LEF, 'LIB/sram_tt_25c.lib': _LIB},
                ws_extra={
                    'skip_parse_views': ['LIBERTY', 'CDL', 'SPICE', 'VERILOG'],
                    'check_plugin_params': {'LIB_DB_PAIRING': {'require_db': True}},
                },
            )
            res = run_revision(work, 'V1', 'SRAM_LIB', 'rev_0001', render=False)
            report = json.loads(Path(res['check']).read_text(encoding='utf-8'))
            pairing = [c for c in report['checks'] if c['check_id'] == 'LIB_DB_PAIRING']
            self.assertEqual(len(pairing), 1)
            self.assertEqual(pairing[0]['result'], 'FAIL')
            self.assertEqual(report['tooling']['plugin_coverage']['LIB_DB_PAIRING'], 'EXECUTED')

    def test_liberty_corner_coverage_ip_group_table_and_three_tier_params(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, work = self._create_lib_with_files(td, {
                'LEF/sram.lef': _LEF,
                'LIB/sram_tt_0p75v_25c.lib': _LIB,
                'LIB/sram_ss_0p675v_125c.lib': _LIB,
            })
            # Write work/corner_acceptance.json
            table = {
                'schema_version': 'corner_acceptance.v1',
                'groups': {
                    'SRAM_BASE': {
                        'corners': [
                            {'id': 'TT_25C', 'any_keywords': ['tt', 'typ'], 'keywords': ['25c']},
                            {'id': 'SS_125C', 'any_keywords': ['ss', 'slow'], 'keywords': ['125c']},
                            {'id': 'FF_M40C', 'any_keywords': ['ff', 'fast'], 'keywords': ['m40c'], 'optional': True},
                        ],
                    },
                    'SRAM_STRICT': {
                        'corners': [
                            {'id': 'TT_25C', 'keywords': ['tt', '25c']},
                            {'id': 'FF_M40C', 'keywords': ['ff', 'm40c']},
                        ],
                    },
                },
                'ip_rules': [
                    {'match_ip': 'SRAM_LIB', 'groups': ['SRAM_BASE']},
                ],
            }
            (work / 'corner_acceptance.json').write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding='utf-8')

            # PASS on SRAM_BASE (optional FF_M40C absent does not fail)
            res1 = run_revision(work, 'V1', 'SRAM_LIB', 'rev_0001', render=False)
            rep1 = json.loads(Path(res1['check']).read_text(encoding='utf-8'))
            cc1 = [c for c in rep1['checks'] if c['check_id'] == 'LIBERTY_CORNER_COVERAGE']
            self.assertEqual(len(cc1), 1)
            self.assertEqual(cc1[0]['result'], 'PASS')
            self.assertIn('SRAM_BASE', cc1[0]['detail'])

            # Override via 3-tier check_plugin_params (per-library inline rules requiring SRAM_STRICT -> FAIL missing FF_M40C)
            update_workspace_config(work, {
                'check_plugin_params_by_ip_type': {
                    'SRAM': {'LIBERTY_CORNER_COVERAGE': {'fail_on_unmapped_ip': False}},
                },
            })
            update_library_config(work, 'V1', 'SRAM_LIB', {
                'check_plugin_params': {
                    'LIBERTY_CORNER_COVERAGE': {
                        'groups': table['groups'],
                        'ip_rules': [{'match_library': 'SRAM_LIB', 'groups': ['SRAM_STRICT']}],
                    },
                },
            })
            eff_p = effective_plugin_params(work, 'V1', 'SRAM_LIB')
            self.assertIn('LIBERTY_CORNER_COVERAGE', eff_p)
            self.assertFalse(eff_p['LIBERTY_CORNER_COVERAGE']['fail_on_unmapped_ip'])

            res2 = run_revision(work, 'V1', 'SRAM_LIB', 'rev_0001', render=False)
            rep2 = json.loads(Path(res2['check']).read_text(encoding='utf-8'))
            cc2 = [c for c in rep2['checks'] if c['check_id'] == 'LIBERTY_CORNER_COVERAGE']
            self.assertEqual(len(cc2), 1)
            self.assertEqual(cc2[0]['result'], 'FAIL')
            self.assertEqual(cc2[0]['findings'][0]['object_name'], 'FF_M40C')

    def test_eda_script_generator_cli_api_web_and_workspace_override(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, work = self._create_lib_with_files(td, {
                'LEF/sram.lef': _LEF,
                'LIB/sram_tt_25c.lib': _LIB,
                'DB/sram_tt_25c.db': b'\x00\x01DB',
            })

            # 1. Built-in templates discovery & render
            tpls = list_script_templates(work)
            names = {t['name'] for t in tpls}
            self.assertTrue({'pt_check', 'innovus_check'} <= names)

            pt_res = render_eda_script(work, 'V1', 'SRAM_LIB', 'rev_0001', template='pt_check')
            self.assertEqual(pt_res['counts']['DB'], 1)
            self.assertIn('#!/bin/csh -f', pt_res['content'])
            self.assertIn('sram_tt_25c.db', pt_res['content'])
            self.assertIn('check_library', pt_res['content'])

            inv_res = render_eda_script(work, 'V1', 'SRAM_LIB', 'rev_0001', template='innovus_check')
            self.assertEqual(inv_res['counts']['LEF'], 1)
            self.assertIn('sram.lef', inv_res['content'])
            self.assertIn('read_physical -lefs', inv_res['content'])

            # 2. Export to disk with 0o755 executable bit via CLI
            out_csh = Path(td) / 'out' / 'run_pt.csh'
            cli_out = cli_run(cli_parser().parse_args([
                'export-script',
                '--work', str(work),
                '--vendor', 'V1',
                '--library', 'SRAM_LIB',
                '--revision', 'rev_0001',
                '--template', 'pt_check',
                '--out', str(out_csh),
            ]))
            self.assertTrue(out_csh.is_file())
            self.assertTrue(bool(out_csh.stat().st_mode & stat.S_IXUSR))
            self.assertEqual(cli_out['template'], 'pt_check')

            # 3. Workspace template override in work/script_templates/pt_check.csh.j2
            ws_tpl_dir = work / 'script_templates'
            ws_tpl_dir.mkdir()
            (ws_tpl_dir / 'pt_check.csh.j2').write_text('#!/bin/csh -f\n# CUSTOM_COMPANY_PT {{ library }} {{ db_files|length }}\n', encoding='utf-8')
            pt_ovr = render_eda_script(work, 'V1', 'SRAM_LIB', 'rev_0001', template='pt_check')
            self.assertIn('CUSTOM_COMPANY_PT SRAM_LIB 1', pt_ovr['content'])
            self.assertTrue(pt_ovr['template_source'].startswith('workspace:'))

            # 4. API & Web UI links
            app = create_path_app(work)
            self.addCleanup(app.extensions['jobs'].shutdown)
            client = app.test_client()
            r_tpl = client.get('/api/v1/scripts/templates')
            self.assertEqual(r_tpl.status_code, 200)
            self.assertTrue(any(t['name'] == 'pt_check' and t['source'] == 'workspace_override' for t in r_tpl.json['templates']))

            r_json = client.get('/api/v1/scripts/export?vendor=V1&library=SRAM_LIB&revision=rev_0001&template=innovus_check')
            self.assertEqual(r_json.status_code, 200)
            self.assertIn('sram.lef', r_json.json['content'])

            r_dl = client.get('/api/v1/scripts/export?vendor=V1&library=SRAM_LIB&revision=rev_0001&template=pt_check&download=1')
            self.assertEqual(r_dl.status_code, 200)
            self.assertIn('attachment;', r_dl.headers.get('Content-Disposition', ''))
            self.assertIn('CUSTOM_COMPANY_PT', r_dl.get_data(as_text=True))

            r_lib = client.get('/path/library?vendor=V1&library=SRAM_LIB')
            self.assertEqual(r_lib.status_code, 200)
            html = r_lib.get_data(as_text=True)
            self.assertIn('导出 PT (.csh)', html)
            self.assertIn('导出 Innovus (.csh)', html)


if __name__ == '__main__':
    unittest.main()
