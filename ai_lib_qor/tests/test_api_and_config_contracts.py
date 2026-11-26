"""Tests for P0 (strict DAG, lowered queries, stateless /api/v1/*) and P1 (config schemas, externalized rules, per-library config)."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_lib_qor.application.ip_partition import load_partition, partition_library_ips
from ai_lib_qor.application.minimal_checks import run_library, run_revision
from ai_lib_qor.application.path_batch import check_pending
from ai_lib_qor.application.path_config import (
    effective_check_plugins,
    get_library_config_view,
    get_workspace_config_view,
    load_path_config,
    save_path_config,
    update_library_config,
    update_workspace_config,
    workbench_runtime_settings,
)
from ai_lib_qor.application.path_query import query_file_index, query_json_inventory
from ai_lib_qor.application.path_refresh import refresh_all
from ai_lib_qor.sources.root_inventory import build_from_roots
from ai_lib_qor.versions.store import validate
from ai_lib_qor.workbench.path_app import create_path_app

_LEF_V1 = 'MACRO M1\n SIZE 2 BY 3 ;\n PIN A\n  DIRECTION INPUT ;\n END A\nEND M1\n'
_LEF_V2 = 'MACRO M1\n SIZE 2 BY 4 ;\n PIN A\n  DIRECTION INPUT ;\n END A\nEND M1\n'
_LIB_OK = 'library(demo) {\n cell(M1) {\n  pin(A) { direction : input; }\n }\n}\n'


class ApiAndConfigContractsTests(unittest.TestCase):
    def _setup_workspace(self, td: str):
        root = Path(td)
        raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
        nl.mkdir()
        work.mkdir()
        v1 = raw / 'V1' / 'STD' / '20261001_v1'
        v2 = raw / 'V1' / 'STD' / '20261002_v2'
        (v1 / 'LEF').mkdir(parents=True)
        (v1 / 'LIB').mkdir(parents=True)
        (v2 / 'LEF').mkdir(parents=True)
        (v2 / 'LIB').mkdir(parents=True)
        (v1 / 'LEF' / 'a.lef').write_text(_LEF_V1, encoding='utf-8')
        (v1 / 'LIB' / 'a.lib').write_text(_LIB_OK, encoding='utf-8')
        (v2 / 'LEF' / 'a.lef').write_text(_LEF_V2, encoding='utf-8')
        (v2 / 'LIB' / 'a.lib').write_text(_LIB_OK, encoding='utf-8')
        (v2 / 'LEF' / 'extra.lef').write_text(_LEF_V2, encoding='utf-8')
        (nl / 'a.lef').symlink_to(v1 / 'LEF' / 'a.lef')
        (nl / 'a.lib').symlink_to(v1 / 'LIB' / 'a.lib')
        save_path_config(work, {
            'raw_roots': [str(raw)],
            'nl_root': str(nl),
            'nl_version': 'NL1',
            'libraries': {'V1': {'STD': {'ip_type': 'STDCELL'}}},
        })
        refresh_all(work)
        return raw, nl, work

    def _client_and_csrf(self, work: Path):
        app = create_path_app(work)
        self.addCleanup(app.extensions['jobs'].shutdown)
        client = app.test_client()
        client.get('/')
        with client.session_transaction() as sess:
            csrf = sess['csrf']
        return app, client, csrf

    def test_no_utf8_bom_in_source_tree_and_build_from_roots_hook_di(self):
        src_root = Path(__file__).resolve().parents[1] / 'src' / 'ai_lib_qor'
        bom_files = [p for p in src_root.rglob('*.py') if p.read_bytes().startswith(b'\xef\xbb\xbf')]
        self.assertEqual(bom_files, [])

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, work = root / 'raw', root / 'work'
            (raw / 'V1' / 'L1' / '20261001_v1').mkdir(parents=True)
            (raw / 'V1' / 'L1' / '20261001_v1' / 'a.lef').write_text(_LEF_V1, encoding='utf-8')
            captured = []

            def custom_hook(out, result, **kwargs):
                captured.append((out, kwargs['touched_libraries']))

            build_from_roots(raw, None, work, update_formal=False, post_inventory_hook=custom_hook)
            self.assertEqual(len(captured), 1)
            self.assertIn(('V1', 'L1'), captured[0][1])

    def test_config_schemas_validate_on_save_and_load(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td) / 'work'
            work.mkdir()
            # Valid path_sources passes
            save_path_config(work, {
                'raw_roots': [],
                'workbench': {'max_workers': 4, 'index_page_size': 50, 'json_inventory_page_size': 40},
                'check_plugins': {'disabled': ['VERILOG_PARTIAL_DIFF']},
                'check_plugins_by_ip_type': {'SRAM': {'enabled': ['LEF_LIBERTY_PIN_MATCH', 'LEF_MACRO_DIFF']}},
            })
            cfg = load_path_config(work, strict=True)
            self.assertEqual(cfg['workbench']['max_workers'], 4)

            # Unknown key rejected by path_sources.schema.json
            with self.assertRaisesRegex(ValueError, 'path_sources Schema'):
                save_path_config(work, {'unknown_typo_key': True})

            # Out-of-range workbench.max_workers rejected
            with self.assertRaisesRegex(ValueError, 'max_workers'):
                save_path_config(work, {'workbench': {'max_workers': 99}})

            # Invalid ip_partition rejected on load
            (work / 'ip_partition_BAD.json').write_text(json.dumps({
                'schema_version': 'ip_partition.v1',
                'vendor': 'V1',
                'library': 'BAD',
                'tracks': {'IP1': 'not-a-list'},
            }), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'ip_partition Schema'):
                load_partition(work, 'V1', 'BAD')

            # Valid ip_partition passes
            validate({
                'schema_version': 'ip_partition.v1',
                'vendor': 'V1',
                'library': 'OK',
                'ip_type': 'SRAM',
                'ip_list': ['IP1'],
                'tracks': {'IP1': ['20261001_v1']},
                'needs_review': {'conflicts': [], 'unassigned': []},
                'auto_trace': {},
                'updated_at': '2026-11-24T00:00:00Z',
            }, 'ip_partition')

    def test_runtime_settings_env_overrides_config_overrides_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, work = self._setup_workspace(td)
            rt0 = workbench_runtime_settings(work)
            self.assertEqual((rt0['max_workers'], rt0['index_page_size'], rt0['json_inventory_page_size']), (2, 80, 100))

            update_workspace_config(work, {'workbench': {'max_workers': 5, 'index_page_size': 25, 'json_inventory_page_size': 30}})
            rt1 = workbench_runtime_settings(work)
            self.assertEqual((rt1['max_workers'], rt1['index_page_size'], rt1['json_inventory_page_size']), (5, 25, 30))
            self.assertEqual(rt1['sources']['max_workers'], 'config')

            with patch.dict(os.environ, {
                'AI_LIB_QOR_MAX_WORKERS': '7',
                'AI_LIB_QOR_INDEX_PAGE_SIZE': '15',
                'AI_LIB_QOR_INVENTORY_PAGE_SIZE': '20',
            }):
                rt2 = workbench_runtime_settings(work)
                self.assertEqual((rt2['max_workers'], rt2['index_page_size'], rt2['json_inventory_page_size']), (7, 15, 20))
                self.assertEqual(rt2['sources']['max_workers'], 'env')
                app = create_path_app(work)
                self.addCleanup(app.extensions['jobs'].shutdown)
                self.assertEqual(app.config['QOR_MAX_WORKERS'], 7)
                self.assertEqual(app.config['QOR_INDEX_PAGE_SIZE'], 15)
                self.assertEqual(app.config['QOR_JSON_INVENTORY_PAGE_SIZE'], 20)

    def test_check_plugins_policy_hierarchy_and_execution(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, work = self._setup_workspace(td)
            # Default: None (all registered)
            self.assertIsNone(effective_check_plugins(work, 'V1', 'STD'))

            # Configure by ip_type = STDCELL
            update_workspace_config(work, {
                'check_plugins_by_ip_type': {
                    'STDCELL': {'enabled': ['LEF_LIBERTY_PIN_MATCH', 'LEF_MACRO_DIFF']},
                },
            })
            self.assertEqual(effective_check_plugins(work, 'V1', 'STD'), ['LEF_LIBERTY_PIN_MATCH', 'LEF_MACRO_DIFF'])

            # Per-library override narrows to single plugin
            update_library_config(work, 'V1', 'STD', {
                'check_plugins': {'enabled': ['LEF_LIBERTY_PIN_MATCH'], 'disabled': []},
            })
            self.assertEqual(effective_check_plugins(work, 'V1', 'STD'), ['LEF_LIBERTY_PIN_MATCH'])

            # Execute revision check -> respects per-library plugin config
            res = run_revision(work, 'V1', 'STD', 'rev_0002', render=False)
            report = json.loads(Path(res['check']).read_text(encoding='utf-8'))
            self.assertEqual(report['tooling']['plugins'], ['LEF_LIBERTY_PIN_MATCH'])

            # check_pending recognizes already-checked revision with same configured plugin set
            pending = check_pending(work, vendor='V1', library='STD')
            self.assertEqual(pending['checked_count'], 0)
            self.assertEqual(pending['skipped_already_checked_count'], 1)

            # Inherit reset returns to ip_type policy
            update_library_config(work, 'V1', 'STD', {'inherit_check_plugins': True})
            self.assertEqual(effective_check_plugins(work, 'V1', 'STD'), ['LEF_LIBERTY_PIN_MATCH', 'LEF_MACRO_DIFF'])

    def test_stateless_api_v1_full_read_and_write_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, work = self._setup_workspace(td)
            run_revision(work, 'V1', 'STD', 'rev_0001', render=False)
            run_revision(work, 'V1', 'STD', 'rev_0002', render=False)
            run_library(work, 'V1', 'STD', render_single_excel=False)

            _, client, csrf = self._client_and_csrf(work)
            headers = {'X-CSRF-Token': csrf}

            # 1. GET /api/v1/inventory (workspace + single library)
            r_inv = client.get('/api/v1/inventory?json_layer=L2&page_size=20')
            self.assertEqual(r_inv.status_code, 200)
            self.assertGreaterEqual(r_inv.json['matched'], 2)
            self.assertEqual(r_inv.json['page_size'], 20)

            r_inv_lib = client.get('/api/v1/inventory?vendor=V1&library=STD')
            self.assertEqual(r_inv_lib.status_code, 200)
            self.assertTrue(all(row['library'] == 'STD' for row in r_inv_lib.json['rows']))

            # 2. GET /api/v1/index (lowered query_file_index)
            r_idx = client.get('/api/v1/index?vendor=V1&library=STD&view=LEF&q=LEF/a.lef&page=1&page_size=10')
            self.assertEqual(r_idx.status_code, 200)
            self.assertEqual(r_idx.json['total'], 1)
            self.assertEqual(r_idx.json['rows'][0]['path'], 'LEF/a.lef')

            # 3. GET /api/v1/overall (auto-latest)
            r_ov = client.get('/api/v1/overall?vendor=V1&library=STD')
            self.assertEqual(r_ov.status_code, 200)
            self.assertEqual(len(r_ov.json['versions']), 2)

            # 4. GET & POST /api/v1/config (workspace & per-library)
            r_ws_cfg = client.get('/api/v1/config')
            self.assertEqual(r_ws_cfg.status_code, 200)
            self.assertTrue(r_ws_cfg.json['schema_valid'])
            self.assertGreaterEqual(len(r_ws_cfg.json['available_plugins']), 2)

            r_lib_cfg = client.get('/api/v1/config?vendor=V1&library=STD')
            self.assertEqual(r_lib_cfg.status_code, 200)
            self.assertEqual(r_lib_cfg.json['ip_type'], 'STDCELL')

            r_upd = client.post('/api/v1/config', headers=headers, json={
                'vendor': 'V1',
                'library': 'STD',
                'updates': {
                    'ip_type': 'STDCELL_V2',
                    'skip_parse_views': ['CDL'],
                    'initial_delivery_tail': 5,
                    'check_plugins': {'enabled': ['LEF_LIBERTY_PIN_MATCH'], 'disabled': []},
                },
            })
            self.assertEqual(r_upd.status_code, 200)
            self.assertEqual(r_upd.json['ip_type'], 'STDCELL_V2')
            self.assertEqual(r_upd.json['effective']['skip_parse_views'], ['CDL'])
            self.assertEqual(r_upd.json['effective']['initial_delivery_tail'], 5)
            self.assertEqual(r_upd.json['effective']['check_plugins'], ['LEF_LIBERTY_PIN_MATCH'])

            # Reject invalid plugin name via API
            r_bad = client.post('/api/v1/config', headers=headers, json={
                'vendor': 'V1',
                'library': 'STD',
                'updates': {'check_plugins': {'enabled': ['NO_SUCH_PLUGIN'], 'disabled': []}},
            })
            self.assertEqual(r_bad.status_code, 400)

            # 5. GET & POST /api/v1/acceptance (stateless accept & rollback)
            r_acc_get = client.get('/api/v1/acceptance?vendor=V1&library=STD')
            self.assertEqual(r_acc_get.status_code, 200)
            self.assertIsNone(r_acc_get.json['accepted_revision'])

            r_acc1 = client.post('/api/v1/acceptance', headers=headers, json={
                'vendor': 'V1', 'library': 'STD', 'revision': 'rev_0001', 'action': 'accept', 'reason': 'API 采纳',
            })
            self.assertEqual(r_acc1.status_code, 200)
            self.assertEqual(r_acc1.json['revision'], 'rev_0001')

            r_acc2 = client.post('/api/v1/acceptance', headers=headers, json={
                'vendor': 'V1', 'library': 'STD', 'revision': 'rev_0002', 'action': 'accept', 'reason': '升级采纳',
            })
            self.assertEqual(r_acc2.status_code, 200)
            r_rb = client.post('/api/v1/acceptance', headers=headers, json={
                'vendor': 'V1', 'library': 'STD', 'revision': 'rev_0001', 'action': 'rollback', 'reason': '回退',
            })
            self.assertEqual(r_rb.status_code, 200)
            self.assertEqual(r_rb.json['revision'], 'rev_0001')

            # 6. POST /api/v1/effective/preview & /api/v1/effective/apply (stateless)
            r_prev = client.post('/api/v1/effective/preview', headers=headers, json={
                'vendor': 'V1',
                'library': 'STD',
                'action': 'set',
                'view': 'LEF',
                'path': 'LEF/a.lef',
                'version': '20261001_v1',
            })
            self.assertEqual(r_prev.status_code, 200)
            self.assertEqual(r_prev.json['parent'], 'rev_0002')
            self.assertEqual(len(r_prev.json['changes']), 1)

            r_app = client.post('/api/v1/effective/apply', headers=headers, json={
                'vendor': 'V1',
                'library': 'STD',
                'action': 'update',
                'operations': r_prev.json['operations'],
                'expected_parent': r_prev.json['parent'],
            })
            self.assertEqual(r_app.status_code, 200)
            self.assertEqual(r_app.json['revision'], 'rev_0003')

            # 7. POST /api/v1/unadopted/ignore & Library UI drawer presence
            r_ign = client.post('/api/v1/unadopted/ignore', headers=headers, json={
                'vendor': 'V1', 'library': 'STD', 'view': 'LEF', 'path': 'LEF/extra.lef', 'ignored': True,
            })
            self.assertEqual(r_ign.status_code, 200)
            self.assertTrue(r_ign.json['ignored'])

            r_page = client.get('/path/library?vendor=V1&library=STD')
            self.assertEqual(r_page.status_code, 200)
            html = r_page.get_data(as_text=True)
            self.assertIn('id="lib-config-open-btn"', html)
            self.assertIn('id="lib-config-drawer"', html)

            # Direct Python query functions remain Flask-free
            direct_inv = query_json_inventory(work, vendor='V1', library='STD')
            direct_idx = query_file_index(work, 'V1', 'STD', view='LEF')
            self.assertGreaterEqual(direct_inv['matched'], 1)
            self.assertGreaterEqual(direct_idx['total'], 1)


if __name__ == '__main__':
    unittest.main()
