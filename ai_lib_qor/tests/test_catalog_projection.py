"""Tests for the rebuildable SQLite query projection catalog (ADR-0002)."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from ai_lib_qor.application.catalog_projection import (
    catalog_db_path,
    ensure_projection_fresh,
    invalidate_projection_freshness_cache,
    query_catalog_check_items,
    query_catalog_checks,
    query_catalog_corners,
    query_catalog_json_inventory,
    query_catalog_object_changes,
    query_catalog_objects,
    query_catalog_summary,
    rebuild_catalog,
    sync_libraries_projection,
)
from ai_lib_qor.application.minimal_checks import run_revision
from ai_lib_qor.application.path_acceptance import accept_revision
from ai_lib_qor.application.path_query import workspace_activity_and_readiness
from ai_lib_qor.application.path_refresh import refresh_l1, refresh_l2, refresh_l3, refresh_status
from ai_lib_qor.application.path_storage import clean_cache, storage_stats
from ai_lib_qor.cli import parser as cli_parser, run as cli_run
from ai_lib_qor.sources.layout import library_folder
from ai_lib_qor.workbench.path_app import create_path_app


def _write_delivery(raw_root: Path, vendor: str, lib: str, version: str, cell_suffix: str):
    vd = raw_root / vendor / lib / version
    (vd / 'lef').mkdir(parents=True, exist_ok=True)
    (vd / 'lib').mkdir(parents=True, exist_ok=True)
    (vd / 'lef' / 'std.lef').write_text(
        f'VERSION 5.8 ;\nMACRO INV_{cell_suffix}\n  CLASS CORE ;\n  SIZE 1.0 BY 2.0 ;\n'
        f'  PIN A\n    DIRECTION INPUT ;\n  END A\n  PIN Y\n    DIRECTION OUTPUT ;\n  END Y\n'
        f'END INV_{cell_suffix}\nEND LIBRARY\n',
        encoding='utf-8',
    )
    (vd / 'lib' / 'tt_0p80v_25c.lib').write_text(
        f'library(demo_{cell_suffix}) {{\n'
        f'  nom_process : 1.0;\n  nom_voltage : 0.80;\n  nom_temperature : 25.0;\n'
        f'  cell(INV_{cell_suffix}) {{\n'
        f'    area : 2.0;\n'
        f'    pin(A) {{ direction : input; }}\n'
        f'    pin(Y) {{ direction : output; }}\n'
        f'  }}\n'
        f'}}\n',
        encoding='utf-8',
    )


class TestCatalogProjection(unittest.TestCase):
    def test_rebuild_write_through_and_delete_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, work = root / 'raw', root / 'work'
            _write_delivery(raw, 'v1', 'libA', '20260101_v1', 'A1')
            refresh_l1(work, raw_root=raw, raw=True, formal=False)
            refresh_l2(work)
            refresh_l3(work)
            run_revision(work, 'v1', 'libA', 'rev_0001', render=False)
            accept_revision(work, 'v1', 'libA', 'rev_0001', actor='tester', reason='ok')

            rebuilt = rebuild_catalog(work)
            self.assertEqual(rebuilt['libraries'], 1)
            self.assertEqual(rebuilt['deliveries'], 1)
            self.assertEqual(rebuilt['revisions'], 1)
            self.assertEqual(rebuilt['checks'], 1)
            self.assertTrue(catalog_db_path(work).is_file())

            # Write-through on new delivery + L2/L3 + check updates projection automatically
            _write_delivery(raw, 'v1', 'libA', '20260102_v2', 'A2')
            refresh_l1(work, raw_root=raw, raw=True, formal=False)
            refresh_l2(work)
            refresh_l3(work)
            run_revision(work, 'v1', 'libA', 'rev_0002', baseline='rev_0001', render=False)

            summ = query_catalog_summary(work, ensure_fresh=False)
            self.assertEqual(summ['backend'], 'sqlite')
            self.assertEqual(summ['totals']['libraries'], 1)
            self.assertEqual(summ['totals']['deliveries'], 2)
            self.assertEqual(summ['totals']['revisions'], 2)
            self.assertEqual(summ['totals']['accepted'], 1)

            # Deleting projection.sqlite never loses data:
            # - pure read-only refresh_status falls back to JSON without mutating work/
            # - explicit catalog query transparently rebuilds projection.sqlite
            catalog_db_path(work).unlink()
            self.assertFalse(catalog_db_path(work).is_file())
            st = refresh_status(work)
            self.assertFalse(catalog_db_path(work).is_file())
            self.assertEqual(st['totals']['deliveries'], 2)
            self.assertEqual(st['totals']['revisions'], 2)
            self.assertEqual(st['libraries'][0]['accepted_revision'], 'rev_0001')

            rebuilt_on_demand = query_catalog_summary(work)
            self.assertTrue(catalog_db_path(work).is_file())
            self.assertEqual(rebuilt_on_demand['totals']['deliveries'], 2)
            st_sql = refresh_status(work)
            self.assertEqual(st_sql['totals']['deliveries'], 2)
            self.assertEqual(st_sql['libraries'][0]['accepted_revision'], 'rev_0001')

    def test_corrupt_check_explicitly_marked_corrupt_in_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, work = root / 'raw', root / 'work'
            _write_delivery(raw, 'v1', 'libC', '20260101_v1', 'C1')
            refresh_l1(work, raw_root=raw, raw=True, formal=False)
            refresh_l2(work)
            refresh_l3(work)
            r1 = run_revision(work, 'v1', 'libC', 'rev_0001', render=False)

            # Inject a schema-invalid check JSON missing required `note`
            folder = library_folder(work, 'v1', 'libC')
            valid_doc = json.loads(Path(r1['check']).read_text(encoding='utf-8'))
            bad_doc = dict(valid_doc)
            bad_doc.pop('note', None)
            bad_path = folder / 'log' / 'check_libC_rev_0001_20991231_bad.json'
            bad_path.write_text(json.dumps(bad_doc), encoding='utf-8')

            rebuilt = rebuild_catalog(work)
            self.assertEqual(rebuilt['checks'], 2)
            self.assertEqual(rebuilt['corrupt_checks'], 1)

            corrupt_only = query_catalog_checks(work, quality='CORRUPT')
            self.assertEqual(corrupt_only['total'], 1)
            self.assertTrue(corrupt_only['items'][0]['is_corrupt'])
            self.assertEqual(corrupt_only['items'][0]['check_name'], bad_path.name)

            valid_only = query_catalog_checks(work, include_corrupt=False)
            self.assertEqual(valid_only['total'], 1)
            self.assertFalse(valid_only['items'][0]['is_corrupt'])

    def test_out_of_band_change_self_heals_without_full_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, work = root / 'raw', root / 'work'
            _write_delivery(raw, 'v1', 'lib1', '20260201_v1', 'L1')
            _write_delivery(raw, 'v1', 'lib2', '20260201_v1', 'L2')
            refresh_l1(work, raw_root=raw, raw=True, formal=False)
            refresh_l2(work)
            refresh_l3(work)
            rebuild_catalog(work)

            # Simulate out-of-band CLI acceptance while SQLite write-through is disabled
            with mock.patch.dict(os.environ, {'AI_LIB_QOR_CATALOG_SQLITE': '0'}):
                accept_revision(work, 'v1', 'lib2', 'rev_0001', actor='cli-oob', reason='oob')

            # Re-enable SQLite: ensure_projection_fresh MUST detect ONLY lib2 changed and heal it
            from ai_lib_qor.application import catalog_projection as cp
            with mock.patch.object(cp, '_collect_library_rows', wraps=cp._collect_library_rows) as m_col:
                ensure_projection_fresh(work)
                scanned_libs = [(c.args[1], c.args[2]) for c in m_col.call_args_list]
            self.assertEqual(scanned_libs, [('v1', 'lib2')])

            st = refresh_status(work)
            by_lib = {r['library']: r for r in st['libraries']}
            self.assertIsNone(by_lib['lib1']['accepted_revision'])
            self.assertEqual(by_lib['lib2']['accepted_revision'], 'rev_0001')

    def test_env_redirect_for_nfs_and_disable_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, work = root / 'raw', root / 'work'
            external_db = root / 'local_ssd' / 'custom_projection.sqlite'
            _write_delivery(raw, 'v1', 'libNfs', '20260301_v1', 'N1')
            refresh_l1(work, raw_root=raw, raw=True, formal=False)
            refresh_l2(work)
            refresh_l3(work)

            with mock.patch.dict(os.environ, {'AI_LIB_QOR_CATALOG_DB': str(external_db)}):
                res = rebuild_catalog(work)
                self.assertEqual(Path(res['db_path']), external_db.resolve())
                self.assertTrue(external_db.is_file())
                self.assertFalse((work / '.catalog').exists())
                inv = query_catalog_json_inventory(work)
                self.assertEqual(inv['backend'], 'sqlite')
                self.assertGreaterEqual(inv['counts']['total'], 4)

            # Disable SQLite completely: fallback to pure JSON works identically
            with mock.patch.dict(os.environ, {'AI_LIB_QOR_CATALOG_SQLITE': '0'}):
                st = refresh_status(work)
                self.assertEqual(st['totals']['libraries'], 1)
                act = workspace_activity_and_readiness(work, days=7)
                self.assertEqual(act['counts']['raw_deliveries'], 1)

            # Verify workbench.catalog_sqlite & catalog_db_path pass path_sources.schema.json validation
            from ai_lib_qor.versions.store import validate
            validate({
                'raw_roots': [str(raw)],
                'workbench': {
                    'host': '127.0.0.1',
                    'port': 5055,
                    'catalog_sqlite': True,
                    'catalog_db_path': str(external_db),
                },
            }, 'path_sources')

    def test_storage_stats_clean_cache_api_and_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, work = root / 'raw', root / 'work'
            _write_delivery(raw, 'v1', 'libApi', '20260401_v1', 'P1')
            refresh_l1(work, raw_root=raw, raw=True, formal=False)
            refresh_l2(work)
            refresh_l3(work)
            run_revision(work, 'v1', 'libApi', 'rev_0001', render=False)
            rebuild_catalog(work)

            # Storage stats classifies .catalog/ under rebuildable_cache_bytes
            st = storage_stats(work)
            self.assertGreater(st['catalog_cache_bytes'], 0)
            self.assertGreaterEqual(st['rebuildable_cache_bytes'], st['catalog_cache_bytes'])

            # CLI catalog-rebuild & catalog-query
            p = cli_parser()
            r_rb = cli_run(p.parse_args(['catalog-rebuild', '--work', str(work)]))
            self.assertEqual(r_rb['libraries'], 1)
            r_sum = cli_run(p.parse_args(['catalog-query', '--work', str(work), '--summary']))
            self.assertEqual(r_sum['totals']['libraries'], 1)
            r_chk = cli_run(p.parse_args(['catalog-query', '--work', str(work), '--vendor', 'v1']))
            self.assertEqual(r_chk['total'], 1)

            # Web API /api/v1/catalog/*
            app = create_path_app(work)
            self.addCleanup(app.extensions['jobs'].shutdown, wait=True)
            client = app.test_client()
            client.get('/')
            with client.session_transaction() as sess:
                csrf = sess['csrf']

            self.assertEqual(client.get('/api/v1/catalog/summary').get_json()['totals']['libraries'], 1)
            self.assertEqual(client.get('/api/v1/catalog/checks?vendor=v1').get_json()['total'], 1)
            r_post = client.post('/api/v1/catalog/rebuild', data={'csrf': csrf})
            self.assertEqual(r_post.status_code, 200)
            self.assertEqual(r_post.get_json()['libraries'], 1)

            # cache-clean --clean-catalog removes projection safely without harming authoritative files
            dry = clean_cache(work, clean_excel=False, clean_orphan_facts=False, clean_catalog=True, dry_run=True)
            self.assertGreaterEqual(dry['removed_count'], 1)
            self.assertTrue(catalog_db_path(work).is_file())
            applied = clean_cache(work, clean_excel=False, clean_orphan_facts=False, clean_catalog=True, dry_run=False)
            self.assertGreaterEqual(applied['removed_count'], 1)
            self.assertFalse(catalog_db_path(work).is_file())

    def test_layer2_check_items_changes_corners_and_dedup_objects(self):
        """Verify Layer-2 summary tables (check_items, object_change_events, effective_views, effective_objects)
        across multiple corners & revisions, with deduplicated Cells (no per-pin bloat) and zero RAW parsing."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, work = root / 'raw', root / 'work'

            # Delivery v1: 1 LEF macro + 2 Liberty corners (ss_125c + tt_25c) sharing the same Cell
            vd1 = raw / 'v1' / 'sram_ip' / '20260501_v1'
            (vd1 / 'lef').mkdir(parents=True, exist_ok=True)
            (vd1 / 'lib').mkdir(parents=True, exist_ok=True)
            (vd1 / 'lef' / 'sram.lef').write_text(
                'VERSION 5.8 ;\nMACRO SRAM_SP_64X32\n  CLASS BLOCK ;\n  SIZE 10.0 BY 20.0 ;\n'
                '  PIN CLK\n    DIRECTION INPUT ;\n  END CLK\n'
                '  PIN Q\n    DIRECTION OUTPUT ;\n  END Q\n'
                'END SRAM_SP_64X32\nEND LIBRARY\n',
                encoding='utf-8',
            )
            for cname, volt, temp in (('ss_0p72v_125c', '0.72', '125.0'), ('tt_0p80v_25c', '0.80', '25.0')):
                (vd1 / 'lib' / f'sram_{cname}.lib').write_text(
                    f'library(sram_{cname}) {{\n'
                    f'  nom_process : 1.0;\n  nom_voltage : {volt};\n  nom_temperature : {temp};\n'
                    f'  cell(SRAM_SP_64X32) {{\n'
                    f'    area : 200.0;\n'
                    f'    pin(CLK) {{ direction : input; }}\n'
                    f'    pin(Q) {{ direction : output; }}\n'
                    f'  }}\n'
                    f'}}\n',
                    encoding='utf-8',
                )

            refresh_l1(work, raw_root=raw, raw=True, formal=False)
            refresh_l2(work)
            refresh_l3(work)
            run_revision(work, 'v1', 'sram_ip', 'rev_0001', render=False)
            accept_revision(work, 'v1', 'sram_ip', 'rev_0001', actor='qa', reason='baseline ok')

            # Delivery v2: LEF SIZE changed (10x20 -> 12.5x20) and extra pin D added in LEF (mismatching Liberty!)
            vd2 = raw / 'v1' / 'sram_ip' / '20260502_v2'
            (vd2 / 'lef').mkdir(parents=True, exist_ok=True)
            (vd2 / 'lib').mkdir(parents=True, exist_ok=True)
            (vd2 / 'lef' / 'sram.lef').write_text(
                'VERSION 5.8 ;\nMACRO SRAM_SP_64X32\n  CLASS BLOCK ;\n  SIZE 12.5 BY 20.0 ;\n'
                '  PIN CLK\n    DIRECTION INPUT ;\n  END CLK\n'
                '  PIN D\n    DIRECTION INPUT ;\n  END D\n'
                '  PIN Q\n    DIRECTION OUTPUT ;\n  END Q\n'
                'END SRAM_SP_64X32\nEND LIBRARY\n',
                encoding='utf-8',
            )
            for cname, volt, temp in (('ss_0p72v_125c', '0.72', '125.0'), ('tt_0p80v_25c', '0.80', '25.0')):
                (vd2 / 'lib' / f'sram_{cname}.lib').write_text(
                    f'library(sram_{cname}) {{\n'
                    f'  nom_process : 1.0;\n  nom_voltage : {volt};\n  nom_temperature : {temp};\n'
                    f'  cell(SRAM_SP_64X32) {{\n'
                    f'    area : 250.0;\n'
                    f'    pin(CLK) {{ direction : input; }}\n'
                    f'    pin(Q) {{ direction : output; }}\n'
                    f'  }}\n'
                    f'}}\n',
                    encoding='utf-8',
                )

            refresh_l1(work, raw_root=raw, raw=True, formal=False)
            refresh_l2(work)
            refresh_l3(work)
            run_revision(work, 'v1', 'sram_ip', 'rev_0002', baseline='rev_0001', render=False)

            # Rebuild catalog while asserting ZERO RAW parsing is invoked
            with mock.patch('ai_lib_qor.facts.registry.parse_lef', side_effect=AssertionError('must not parse RAW')), \
                 mock.patch('ai_lib_qor.facts.registry.parse_liberty', side_effect=AssertionError('must not parse RAW')):
                rb = rebuild_catalog(work)
            self.assertGreaterEqual(rb['check_items'], 2)
            self.assertGreaterEqual(rb['object_change_events'], 1)
            self.assertGreaterEqual(rb['effective_views'], 3)
            self.assertGreaterEqual(rb['effective_objects'], 2)

            # 1. check_items scoreboard: rev_0002 has LEF_LIBERTY_PIN_MATCH FAIL
            ci = query_catalog_check_items(work, check_id='LEF_LIBERTY_PIN_MATCH', result='FAIL', latest_only=True)
            self.assertGreaterEqual(ci['total'], 1)
            self.assertEqual(ci['by_check_id'][0]['check_id'], 'LEF_LIBERTY_PIN_MATCH')
            self.assertGreaterEqual(ci['by_check_id'][0]['fail_libraries'], 1)

            # Summary also includes by_check_id & Layer-2 totals
            summ = query_catalog_summary(work)
            self.assertTrue(any(x['check_id'] == 'LEF_LIBERTY_PIN_MATCH' for x in summ['by_check_id']))
            self.assertGreaterEqual(summ['totals']['object_change_events'], 1)

            # 2. object_change_events: tracks SIZE change between rev_0001 and rev_0002
            chg = query_catalog_object_changes(work, object_name='SRAM_SP_64X32')
            self.assertGreaterEqual(chg['total'], 1)
            self.assertTrue(any('12.5' in str(x['new_value']) for x in chg['items']))

            # 3. effective_views / corners: supports `+` AND token search (ss+125c)
            crn = query_catalog_corners(work, q='ss+125c', view='LIBERTY', latest_only=True)
            self.assertEqual(crn['total'], 1)
            self.assertEqual(crn['items'][0]['revision'], 'rev_0002')
            self.assertIn('ss_0p72v_125c', crn['items'][0]['corner_hint'])

            # 4. effective_objects: 2 Liberty corners sharing SRAM_SP_64X32 deduplicate to 1 row (corner_file_count=2)
            objs_lib = query_catalog_objects(work, q='SRAM_SP_64X32', object_type='CELL', view='LIBERTY', latest_only=True)
            self.assertEqual(objs_lib['total'], 1)
            self.assertEqual(objs_lib['items'][0]['corner_file_count'], 2)
            self.assertEqual(objs_lib['items'][0]['pin_count'], 2)

            objs_lef = query_catalog_objects(work, q='SRAM_SP_64X32', object_type='MACRO', view='LEF', latest_only=True)
            self.assertEqual(objs_lef['total'], 1)
            self.assertAlmostEqual(objs_lef['items'][0]['width_um'], 12.5)
            self.assertAlmostEqual(objs_lef['items'][0]['area_um2'], 250.0)
            self.assertEqual(objs_lef['items'][0]['pin_count'], 3)

            # 5. CLI & Web API Layer-2 endpoints
            p = cli_parser()
            self.assertGreaterEqual(
                cli_run(p.parse_args(['catalog-query', '--work', str(work), '--check-items', '--result', 'FAIL']))['total'],
                1,
            )
            self.assertGreaterEqual(
                cli_run(p.parse_args(['catalog-query', '--work', str(work), '--changes', '--object-name', 'SRAM']))['total'],
                1,
            )
            self.assertEqual(
                cli_run(p.parse_args(['catalog-query', '--work', str(work), '--objects', '--object-type', 'CELL', '--q', 'SRAM']))['total'],
                1,
            )
            self.assertEqual(
                cli_run(p.parse_args(['catalog-query', '--work', str(work), '--corners', '--q', 'ss+125c']))['total'],
                1,
            )

            app = create_path_app(work)
            self.addCleanup(app.extensions['jobs'].shutdown, wait=True)
            client = app.test_client()
            cat_page = client.get('/?view=catalog')
            self.assertEqual(cat_page.status_code, 200)
            html = cat_page.get_data(as_text=True)
            self.assertIn('id="catalog-section"', html)
            self.assertIn('data-api-check-items="/api/v1/catalog/check-items"', html)
            self.assertIn('data-api-corners="/api/v1/catalog/corners"', html)
            self.assertEqual(client.get('/api/v1/catalog/check-items?result=FAIL').status_code, 200)
            self.assertGreaterEqual(client.get('/api/v1/catalog/changes?object_name=SRAM').get_json()['total'], 1)
            self.assertEqual(client.get('/api/v1/catalog/objects?object_type=CELL&q=SRAM').get_json()['total'], 1)
            self.assertEqual(client.get('/api/v1/catalog/corners?q=ss%2B125c').get_json()['total'], 1)

    def test_ttl_freshness_cache_per_lib_config_sig_and_batch_sync(self):
        """Verify 3 scale optimizations:
        1) Short-TTL freshness cache eliminates repeated folder_sig stat loops during interactive queries;
        2) Editing unrelated path_sources.json fields rescans 0 libraries, and editing 1 library's ip_type rescans ONLY that library;
        3) Batch sync_libraries_projection commits multiple libraries in ONE SQLite connection/transaction.
        """
        from ai_lib_qor.application import catalog_projection as cp
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, work = root / 'raw', root / 'work'
            _write_delivery(raw, 'v1', 'lib1', '20260601_v1', 'L1')
            _write_delivery(raw, 'v1', 'lib2', '20260601_v1', 'L2')
            refresh_l1(work, raw_root=raw, raw=True, formal=False)
            refresh_l2(work)
            refresh_l3(work)
            rebuild_catalog(work)

            # 1) Short-TTL freshness cache: 1st call stats 2 libs, 2nd call within TTL stats 0 libs
            invalidate_projection_freshness_cache(work)
            with mock.patch.object(cp, '_library_folder_sig', wraps=cp._library_folder_sig) as m_sig:
                query_catalog_summary(work, fresh_ttl_s=5.0)
                first_calls = m_sig.call_count
                query_catalog_corners(work, fresh_ttl_s=5.0)
                query_catalog_objects(work, fresh_ttl_s=5.0)
                second_calls = m_sig.call_count
            self.assertEqual(first_calls, 2)
            self.assertEqual(second_calls, 2)

            # 2a) Editing unrelated workspace setting in path_sources.json rescans 0 libraries!
            cfg_path = work / 'path_sources.json'
            cfg = json.loads(cfg_path.read_text(encoding='utf-8')) if cfg_path.is_file() else {}
            cfg.setdefault('workbench', {})['index_page_size'] = 120
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
            with mock.patch.object(cp, '_collect_library_rows', wraps=cp._collect_library_rows) as m_col:
                ensure_projection_fresh(work, fresh_ttl_s=0.0)
                self.assertEqual(m_col.call_count, 0)

            # 2b) Editing ONLY lib2's ip_type in path_sources.json rescans ONLY lib2 (NOT lib1)!
            cfg.setdefault('libraries', {}).setdefault('v1', {})['lib2'] = {'ip_type': 'SRAM'}
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
            with mock.patch.object(cp, '_collect_library_rows', wraps=cp._collect_library_rows) as m_col:
                ensure_projection_fresh(work, fresh_ttl_s=0.0)
                scanned = [(c.args[1], c.args[2]) for c in m_col.call_args_list]
            self.assertEqual(scanned, [('v1', 'lib2')])

            # 3) Batch sync_libraries_projection opens ONLY 1 SQLite connection for 2 libraries
            with mock.patch.object(cp, '_connect', wraps=cp._connect) as m_conn:
                res = sync_libraries_projection(work, [('v1', 'lib1'), ('v1', 'lib2'), ('v1', 'lib1')])
                self.assertEqual(m_conn.call_count, 1)
            self.assertIsNotNone(res)
            self.assertEqual(res['count'], 2)


if __name__ == '__main__':
    unittest.main()
