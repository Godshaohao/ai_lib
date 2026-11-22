import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_lib_qor.application.minimal_checks import render_excel_from_check, run_revision
from ai_lib_qor.application.path_refresh import refresh_all
from ai_lib_qor.checks.path_plugins import PATH_CHECK_PLUGINS, register_path_plugin
from ai_lib_qor.facts.registry import PARSER_REGISTRY, register_parser
from ai_lib_qor.reporting.qor_views import FACTS_VIEW_REGISTRY, build_facts_view, register_facts_view


class PluggableQoRViewsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.root = root
        self.work = root / 'work'
        self.raw = root / 'raw'
        self.nl = root / 'NL1'
        self.nl.mkdir()
        (root / 'plans').mkdir()

        # V1: LEF (2x3, pin IN=INPUT) + LIBERTY (IN=INPUT)
        lef1 = self.raw / 'v/lib/20261001_v1/LEF/a.lef'
        lef1.parent.mkdir(parents=True)
        lef1.write_text('MACRO A\n SIZE 2 BY 3 ;\n PIN IN\n  DIRECTION INPUT ;\n END IN\nEND A\n')
        lib1 = self.raw / 'v/lib/20261001_v1/LIB/a.lib'
        lib1.parent.mkdir(parents=True)
        lib1.write_text('library(L) {\n cell(A) {\n  pin(IN) { direction : input; }\n }\n}\n')
        (self.nl / 'a.lef').symlink_to(lef1)
        (self.nl / 'a.lib').symlink_to(lib1)

        self.work.mkdir()
        (self.work / 'path_sources.json').write_text(json.dumps({
            'raw_root': str(self.raw),
            'nl_root': str(self.nl),
            'nl_version': 'NL1',
        }))
        refresh_all(self.work)

        # V2: LEF updated (SIZE 2x4, pin IN=OUTPUT, pin OUT=OUTPUT)
        lef2 = self.raw / 'v/lib/20261002_v2/LEF/a.lef'
        lef2.parent.mkdir(parents=True)
        lef2.write_text(
            'MACRO A\n SIZE 2 BY 4 ;\n'
            ' PIN IN\n  DIRECTION OUTPUT ;\n END IN\n'
            ' PIN OUT\n  DIRECTION OUTPUT ;\n END OUT\n'
            'END A\n'
        )
        refresh_all(self.work, formal=False)

    def test_parser_and_facts_view_registries_are_pluggable(self):
        custom_parsers = dict(PARSER_REGISTRY)
        register_parser(
            'GDS',
            lambda p, allow_pg=False: {
                'view': 'GDS',
                'parser': {'name': 'demo_gds', 'version': '0.1'},
                'parse_status': 'PARTIAL',
                'covered_sections': ['TOP_CELL'],
                'units': {},
                'objects': {'top_cells': ['A']},
            },
            registry=custom_parsers,
        )
        from ai_lib_qor.facts.parsers import parse_file_payload
        dummy = self.root / 'a.gds'
        dummy.write_text('dummy')
        payload = parse_file_payload(dummy, 'GDS', registry=custom_parsers)
        self.assertEqual(payload['view'], 'GDS')
        self.assertEqual(payload['objects']['top_cells'], ['A'])

        custom_views = dict(FACTS_VIEW_REGISTRY)
        register_facts_view(
            'GDS',
            lambda f: {
                'summary_metrics': [{'label': 'Top Cells', 'value': len(f['objects']['top_cells'])}],
                'entities_title': 'GDS Cells',
                'entities_columns': ['Cell'],
                'entities': [[c] for c in f['objects']['top_cells']],
                'pins_title': '',
                'pins': [],
                'pin_directions': [],
                'pin_uses': [],
                'coverage_note': 'custom gds view',
            },
            registry=custom_views,
        )
        view = build_facts_view(payload, registry=custom_views)
        self.assertEqual(view['entities_title'], 'GDS Cells')
        self.assertEqual(view['summary_metrics'][0]['value'], 1)

    def test_custom_check_plugin_and_decoupled_excel_rendering(self):
        # Register a custom plugin temporarily without touching minimal_checks.py
        def custom_rule(ctx):
            return {
                'checks': [{
                    'check_id': 'CUSTOM_DEMO_RULE',
                    'scope_file_keys': ['LEF/a.lef'],
                    'result': 'PASS',
                    'coverage': 'COMPLETE',
                    'facts_refs': [],
                    'detail': 'custom plugin executed',
                }]
            }
        register_path_plugin('CUSTOM_DEMO_RULE', custom_rule)
        self.addCleanup(lambda: PATH_CHECK_PLUGINS.pop('CUSTOM_DEMO_RULE', None))

        # Run without rendering Excel (pure data build)
        res = run_revision(self.work, 'v', 'lib', 'rev_0002', plugins=['LEF_MACRO_DIFF', 'CUSTOM_DEMO_RULE'], render=False)
        self.assertIsNone(res['excel'])
        check_path = Path(res['check'])
        self.assertTrue(check_path.is_file())
        data = json.loads(check_path.read_text(encoding='utf-8'))
        self.assertEqual([c['check_id'] for c in data['checks']], ['CUSTOM_DEMO_RULE'])
        self.assertEqual(data['comparisons'][0]['content_status'], 'CURRENT_CONTENT_DIFF')

        # Render Excel later strictly from saved disk JSON (no re-parsing RAW)
        with patch('ai_lib_qor.facts.parsers.parse_file_payload', side_effect=AssertionError('不得重解析 RAW')):
            excel_out = render_excel_from_check(self.work, 'v', 'lib', check_path.name)
        self.assertTrue(Path(excel_out).is_file())

    def test_web_check_facts_and_compare_views_are_readonly_and_accurate(self):
        res = run_revision(self.work, 'v', 'lib', 'rev_0002')
        check_name = Path(res['check']).name
        check_data = json.loads(Path(res['check']).read_text(encoding='utf-8'))
        comp = check_data['comparisons'][0]
        old_ref, new_ref = comp['facts_refs']

        from ai_lib_qor.workbench.app import create_app
        app = create_app(self.root / 'plans', self.root / 'runs', self.work)
        client = app.test_client()

        # All 3 online analysis routes must be strictly read-only (no os.walk, no parsing)
        with patch('os.walk', side_effect=AssertionError('不扫描 RAW')), \
             patch('ai_lib_qor.facts.parsers.parse_file_payload', side_effect=AssertionError('不重解析')):
            r_check = client.get('/path/check/view', query_string={'vendor': 'v', 'library': 'lib', 'name': check_name})
            self.assertEqual(r_check.status_code, 200)
            html_check = r_check.get_data(as_text=True)
            self.assertIn('rev_0002', html_check)
            self.assertIn('rev_0001', html_check)
            self.assertIn('内容有变', html_check)
            self.assertIn('LEF_LIBERTY_PIN_MATCH', html_check)

            r_facts = client.get('/path/facts/view', query_string={'vendor': 'v', 'library': 'lib', 'check': check_name, 'ref': new_ref})
            self.assertEqual(r_facts.status_code, 200)
            html_facts = r_facts.get_data(as_text=True)
            self.assertIn('MACRO_SIZE', html_facts)
            self.assertIn('OUT', html_facts)

            r_cmp = client.get('/path/facts/compare', query_string={'vendor': 'v', 'library': 'lib', 'check': check_name, 'old': old_ref, 'new': new_ref})
            self.assertEqual(r_cmp.status_code, 200)
            html_cmp = r_cmp.get_data(as_text=True)
            self.assertIn('DIRECTION_CHANGED', html_cmp)
            self.assertIn('ADDED', html_cmp)
            self.assertIn('CHANGED', html_cmp)

            r_dl = client.get('/path/facts/download', query_string={'vendor': 'v', 'library': 'lib', 'check': check_name, 'ref': new_ref})
            self.assertEqual(r_dl.status_code, 200)
            downloaded = json.loads(r_dl.get_data(as_text=True))
            self.assertEqual(downloaded['view'], 'LEF')
            r_dl.close()

            # Path traversal rejected
            self.assertEqual(client.get('/path/check/view', query_string={'vendor': 'v', 'library': 'lib', 'name': '../secret.json'}).status_code, 404)
            self.assertEqual(client.get('/path/facts/view', query_string={'vendor': 'v', 'library': 'lib', 'name': '../secret.json'}).status_code, 404)
