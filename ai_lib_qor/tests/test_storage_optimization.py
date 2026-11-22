import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_lib_qor.application.minimal_checks import load_check_bundle, render_excel_from_check, run_library, run_revision
from ai_lib_qor.application.minimal_effective import initialize_from_formal, update_effective
from ai_lib_qor.cli import parser, run as cli_run
from ai_lib_qor.reporting.qor_views import build_check_view, build_facts_view, load_fact_object
from ai_lib_qor.sources.root_inventory import build_from_roots
from ai_lib_qor.workbench.path_app import create_path_app


class StorageOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.root = root
        self.raw = root / 'raw'
        self.nl = root / 'NL1'
        self.nl.mkdir()
        self.work = root / 'work'
        self.v1 = '20261001_r01'
        self.v2 = '20261002_r02'
        self.v3 = '20261003_r03'

        lef_base = (
            'MACRO INV_X1\n'
            ' SIZE 2 BY 3 ;\n'
            ' PIN A\n  DIRECTION INPUT ;\n END A\n'
            ' PIN Y\n  DIRECTION OUTPUT ;\n END Y\n'
            'END INV_X1\n'
        )
        lef_mod = (
            'MACRO INV_X1\n'
            ' SIZE 4 BY 3 ;\n'
            ' PIN A\n  DIRECTION INPUT ;\n END A\n'
            ' PIN Y\n  DIRECTION OUTPUT ;\n END Y\n'
            'END INV_X1\n'
        )
        lib_base = 'library(demo) { cell(INV_X1) { pin(A) { direction : input; } pin(Y) { direction : output; } } }\n'

        # v1: initial LEF + LIB
        # v2: identical bytes for both LEF and LIB (different delivery version, same content)
        # v3: modified LEF + identical LIB
        specs = [
            (self.v1, lef_base, lib_base),
            (self.v2, lef_base, lib_base),
            (self.v3, lef_mod, lib_base),
        ]
        for ver, lef_txt, lib_txt in specs:
            lp = self.raw / 'v/lib' / ver / 'LEF/std.lef'
            lp.parent.mkdir(parents=True, exist_ok=True)
            lp.write_text(lef_txt, encoding='utf-8')
            bp = self.raw / 'v/lib' / ver / 'LIB/std.lib'
            bp.parent.mkdir(parents=True, exist_ok=True)
            bp.write_text(lib_txt, encoding='utf-8')
            if ver == self.v1:
                (self.nl / 'std.lef').symlink_to(lp)
                (self.nl / 'std.lib').symlink_to(bp)

        build_from_roots(self.raw, self.nl, self.work, auto_effective=False)
        self.folder = self.work / 'libraries/v/lib'
        initialize_from_formal(self.work, 'v', 'lib', next((self.folder / 'formal').glob('formal_NL1_*.json')))
        update_effective(self.work, 'v', 'lib', {
            'set': [
                {'view': 'LEF', 'version': self.v2, 'path': 'LEF/std.lef'},
                {'view': 'LIBERTY', 'version': self.v2, 'path': 'LIB/std.lib'},
            ],
            'remove': [],
        })
        update_effective(self.work, 'v', 'lib', {
            'set': [
                {'view': 'LEF', 'version': self.v3, 'path': 'LEF/std.lef'},
                {'view': 'LIBERTY', 'version': self.v3, 'path': 'LIB/std.lib'},
            ],
            'remove': [],
        })

    def test_content_addressed_facts_pool_dedup_and_reuse(self):
        # First check on rev_0001 populates pool for (lef_base, lib_base)
        r1 = run_revision(self.work, 'v', 'lib', 'rev_0001', render=False)
        self.assertIsNone(r1['excel'])
        pool_files_1 = sorted((self.folder / 'facts').glob('fact_ca_*.json.gz'))
        self.assertEqual(len(pool_files_1), 2)
        # Must never create persistent facts_*.json matching legacy glob
        self.assertFalse(list(self.folder.rglob('facts_*.json')))

        # Check JSON stores lightweight CONTENT_ADDRESSED_POOL pointers without objects payload
        c1 = json.loads(Path(r1['check']).read_text(encoding='utf-8'))
        self.assertTrue(c1['facts_evidence'])
        for ptr in c1['facts_evidence'].values():
            self.assertEqual(ptr.get('storage'), 'CONTENT_ADDRESSED_POOL')
            self.assertNotIn('objects', ptr)
            self.assertTrue((self.folder / ptr['pool_file']).is_file())
            blob = json.loads(gzip.decompress((self.folder / ptr['pool_file']).read_bytes()).decode('utf-8'))
            self.assertIn('objects', blob)

        # Second check on rev_0002 (different delivery version, identical file bytes):
        # MUST hit content-addressed pool and skip parse_file_payload completely!
        with patch('ai_lib_qor.facts.parsers.parse_file_payload', side_effect=AssertionError('应命中共享池，不得重复解析')):
            r2 = run_revision(self.work, 'v', 'lib', 'rev_0002', render=False)
        self.assertEqual(r2['state'], 'SUCCEEDED')
        pool_files_2 = sorted((self.folder / 'facts').glob('fact_ca_*.json.gz'))
        self.assertEqual(len(pool_files_2), 2)

        # Third check on rev_0003: LEF changed (new pool entry), LIBERTY unchanged (pool hit!)
        r3 = run_revision(self.work, 'v', 'lib', 'rev_0003', render=False)
        self.assertEqual(r3['state'], 'SUCCEEDED')
        pool_files_3 = sorted((self.folder / 'facts').glob('fact_ca_*.json.gz'))
        self.assertEqual(len(pool_files_3), 3)
        c3 = json.loads(Path(r3['check']).read_text(encoding='utf-8'))
        self.assertTrue(any(ch['attribute'] == 'SIZE' and ch['new_value'] == [4.0, 3.0] for ch in c3['changes']))

        # Transparent hydration in load_check_bundle, load_fact_object, build_check_view & build_facts_view
        bundle = load_check_bundle(self.work, 'v', 'lib', Path(r3['check']).name)
        self.assertTrue(bundle['facts'])
        for ref_id, hydrated in bundle['facts'].items():
            self.assertIn('objects', hydrated)
            self.assertEqual(hydrated['schema_version'], 'file_facts.path.v1')
        cv = build_check_view(self.work, 'v', 'lib', Path(r3['check']).name)
        self.assertTrue(cv['excel_name'].endswith('.xlsx'))
        self.assertFalse(cv['excel_cached'])
        lef_row = next(row for row in cv['file_rows'] if row['view'] == 'LEF')
        fact_obj, _, _ = load_fact_object(self.work, 'v', 'lib', check=Path(r3['check']).name, ref=lef_row['fact_ref'])
        fv = build_facts_view(fact_obj)
        self.assertEqual(fv['summary_metrics'][0]['value'], 1)

    def test_lazy_excel_cli_web_and_overall_reuse(self):
        # CLI --no-excel skips rendering
        args = parser().parse_args([
            'minimal-check-revision', '--work', str(self.work), '--vendor', 'v',
            '--library', 'lib', '--revision', 'rev_0001', '--no-excel',
        ])
        res = cli_run(args)
        check_path = Path(res['check'])
        xlsx_path = check_path.with_suffix('.xlsx')
        self.assertTrue(check_path.is_file())
        self.assertFalse(xlsx_path.exists())

        # Overall run_library(rerun=False) still reuses the saved JSON even without pre-rendered xlsx
        overall = run_library(self.work, 'v', 'lib', revisions=['rev_0001'], rerun=False)
        self.assertEqual(overall['versions'][0]['run_id'], res['run_id'])
        self.assertIsNone(overall['versions'][0]['excel'])
        self.assertTrue(Path(overall['excel']).is_file())

        # Web GET /path/artifact lazily renders, caches, and returns valid Excel
        app = create_path_app(self.work)
        client = app.test_client()
        resp = client.get('/path/artifact', query_string={
            'vendor': 'v', 'library': 'lib', 'name': xlsx_path.name,
        })
        self.assertEqual(resp.status_code, 200)
        resp.close()
        self.assertTrue(xlsx_path.is_file())
        self.assertGreater(xlsx_path.stat().st_size, 1000)

        # CLI minimal-render-excel also works to a custom path
        custom_out = self.root / 'custom.xlsx'
        r_args = parser().parse_args([
            'minimal-render-excel', '--work', str(self.work), '--vendor', 'v',
            '--library', 'lib', '--check', check_path.name, '--out', str(custom_out),
        ])
        r_res = cli_run(r_args)
        self.assertEqual(r_res['state'], 'SUCCEEDED')
        self.assertTrue(custom_out.is_file())

    def test_formal_observations_dedup_and_broken_link_full_log(self):
        log = self.work / 'formal_observations.tsv'
        with log.open(encoding='utf-8', newline='') as f:
            rows_initial = list(csv.reader(f, delimiter='\t'))
        # 1 header + 2 matched links = 3 rows
        self.assertEqual(len(rows_initial), 3)

        # Repeating unchanged formal scan appends only 1 UNCHANGED heartbeat row
        res_same = build_from_roots(self.raw, self.nl, self.work, update_raw=False, update_formal=True, update_index=False)
        self.assertTrue(res_same.get('formal_observation_deduplicated'))
        with log.open(encoding='utf-8', newline='') as f:
            rows_after_same = list(csv.reader(f, delimiter='\t'))
        self.assertEqual(len(rows_after_same), 4)
        self.assertEqual(rows_after_same[-1][3], 'UNCHANGED')
        self.assertEqual(rows_after_same[-1][7], 'SAME_AS_PREVIOUS:2')

        # Adding a broken symlink forces full PARTIAL log with unresolved entry
        broken = self.nl / 'broken.lef'
        broken.symlink_to('missing_target.lef')
        res_broken = build_from_roots(self.raw, self.nl, self.work, update_raw=False, update_formal=True, update_index=False)
        self.assertFalse(res_broken.get('formal_observation_deduplicated'))
        self.assertEqual(res_broken['formal_observation_status'], 'PARTIAL')
        with log.open(encoding='utf-8', newline='') as f:
            rows_after_broken = list(csv.reader(f, delimiter='\t'))
        # 4 + (1 header + 2 matched + 1 broken) = 8 rows
        self.assertEqual(len(rows_after_broken), 8)
        self.assertTrue(any(r[4] == 'broken.lef' and r[7] == 'UNRESOLVED' for r in rows_after_broken))

        # Fixing broken link logs full restored COMPLETE state, then next scan deduplicates again
        broken.unlink()
        res_fixed = build_from_roots(self.raw, self.nl, self.work, update_raw=False, update_formal=True, update_index=False)
        self.assertFalse(res_fixed.get('formal_observation_deduplicated'))
        res_dedup2 = build_from_roots(self.raw, self.nl, self.work, update_raw=False, update_formal=True, update_index=False)
        self.assertTrue(res_dedup2.get('formal_observation_deduplicated'))


if __name__ == '__main__':
    unittest.main()
