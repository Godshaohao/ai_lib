"""Regression & invariant tests covering P0 workflow fixes, P1 DAG/visibility upgrades, and P2 extensibility."""
import ast
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from ai_lib_qor.application.minimal_checks import run_revision
from ai_lib_qor.application.minimal_effective import apply_update, derive_processed_versions, restore_revision
from ai_lib_qor.application.path_batch import check_pending
from ai_lib_qor.application.path_config import set_unadopted_ignored
from ai_lib_qor.application.path_query import PathDataQuery, check_tooling_status, latest_check_for_revision, latest_check_for_scope, unadopted_new_files
from ai_lib_qor.application.path_refresh import refresh_all, refresh_l1, refresh_l2, refresh_status
from ai_lib_qor.application.plugin_loader import isolated_registries
from ai_lib_qor.checks.path_plugins import PATH_CHECK_PLUGIN_META, PATH_CHECK_PLUGINS, register_path_plugin
from ai_lib_qor.cli import parser as cli_parser, run as cli_run
from ai_lib_qor.facts.registry import PARSER_REGISTRY, register_parser
from ai_lib_qor.reporting.check_renderer import render_excel_from_check
from ai_lib_qor.reporting.path_workbook_model import build_path_workbook_spec
from ai_lib_qor.reporting.work_overview_excel import render_work_overview_excel
from ai_lib_qor.sources.root_inventory import VIEW_EXTENSIONS, register_view_extension
from ai_lib_qor.workbench.path_app import create_path_app

SRC_ROOT = Path(__file__).resolve().parents[1] / 'src' / 'ai_lib_qor'

_LEF_V1 = 'MACRO M1\n SIZE 2 BY 3 ;\n PIN A\n  DIRECTION INPUT ;\n END A\nEND M1\n'
_LEF_V2 = 'MACRO M1\n SIZE 2 BY 4 ;\n PIN A\n  DIRECTION INPUT ;\n END A\nEND M1\n'
_LEF_V3 = 'MACRO M1\n SIZE 3 BY 4 ;\n PIN A\n  DIRECTION INPUT ;\n END A\nEND M1\n'
_LIB_OK = 'library(demo) {\n cell(M1) {\n  pin(A) { direction : input; }\n }\n}\n'


def _imports_in_node(node):
    found = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Import):
            for alias in sub.names:
                found.append(alias.name)
        elif isinstance(sub, ast.ImportFrom):
            if sub.module:
                found.append(sub.module)
    return found


class ArchitectureP0P2Tests(unittest.TestCase):
    def test_package_dependency_dag_invariants(self):
        # Strict whole-AST DAG guard inspecting BOTH top-level AND function-body imports across every layer.
        layer_rank = {
            'versions': 0,
            'sources': 1,
            'facts': 2,
            'checks': 3,
            'application': 4,
            'reporting': 5,
            'workbench': 6,
        }
        # Zero upward edges across all 7 architectural layers (strict unidirectional DAG).
        compat_allowlist = set()

        def check_scope_imports(rel_path, src_layer, scope_name, node):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    check_scope_imports(rel_path, src_layer, child.name, child)
                elif isinstance(child, ast.ClassDef):
                    check_scope_imports(rel_path, src_layer, child.name, child)
                elif isinstance(child, (ast.Import, ast.ImportFrom)):
                    for mod in _imports_in_node(child):
                        if not mod.startswith('ai_lib_qor.'):
                            continue
                        parts = mod.split('.')
                        if len(parts) < 2 or parts[1] not in layer_rank:
                            continue
                        tgt_layer = parts[1]
                        if layer_rank[tgt_layer] > layer_rank[src_layer]:
                            key = (rel_path, scope_name, tgt_layer)
                            self.assertIn(
                                key,
                                compat_allowlist,
                                f'违反分层 DAG 方向：{rel_path}:{scope_name} ({src_layer}) -> {mod} ({tgt_layer})',
                            )
                else:
                    check_scope_imports(rel_path, src_layer, scope_name, child)

        for layer in layer_rank:
            for py in sorted((SRC_ROOT / layer).rglob('*.py')):
                rel = py.relative_to(SRC_ROOT).as_posix()
                tree = ast.parse(py.read_text(encoding='utf-8-sig'), filename=str(py))
                check_scope_imports(rel, layer, '<module>', tree)

        # Pure L1 inventory_sources has ZERO application/workbench imports
        ri_tree = ast.parse((SRC_ROOT / 'sources' / 'root_inventory.py').read_text(encoding='utf-8-sig'))
        inv_fn = next(n for n in ri_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'inventory_sources')
        self.assertEqual(
            [m for m in _imports_in_node(inv_fn) if any(x in m.split('.') for x in ('application', 'reporting', 'workbench'))],
            [],
        )

        # Verified dead functions remain removed
        import ai_lib_qor.facts.parsers as parsers_mod
        import ai_lib_qor.sources.layout as layout_mod
        import ai_lib_qor.workbench.path_app as path_app_mod
        self.assertFalse(hasattr(parsers_mod, 'parse_delivery_file'))
        self.assertFalse(hasattr(layout_mod, 'delivery_filename'))
        self.assertFalse(hasattr(layout_mod, 'formal_filename'))
        self.assertFalse(hasattr(path_app_mod, 'is_path_work'))

    def test_p0_l2_high_watermark_preserves_manual_restore_and_advances_new_delivery(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            p1 = raw / 'v/lib/20261001_v1/LEF/a.lef'
            p1.parent.mkdir(parents=True)
            p1.write_text(_LEF_V1, encoding='utf-8')
            p2 = raw / 'v/lib/20261002_v2/LEF/a.lef'
            p2.parent.mkdir(parents=True)
            p2.write_text(_LEF_V2, encoding='utf-8')
            (nl / 'a.lef').symlink_to(p1)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))

            r1 = refresh_all(work)
            self.assertEqual(r1['l2']['initialized'], 1)
            self.assertEqual(r1['l2']['effective_published'], 1)

            folder = work / 'libraries/v/lib'
            self.assertFalse((folder / '.auto_effective_state.json').exists(), '状态文件不应散落在库根目录')
            state_file = folder / 'log/.auto_effective_state.json'
            self.assertTrue(state_file.is_file())
            state = json.loads(state_file.read_text(encoding='utf-8'))
            self.assertEqual(state['pending'], [])
            self.assertEqual(set(state['processed']), {'20261001_v1', '20261002_v2'})

            # User rolls back buggy v2 -> rev_0001 (v1), producing rev_0003
            res = restore_revision(work, 'v', 'lib', 'rev_0001', expected_parent='rev_0002', actor='engineer')
            self.assertEqual(res['revision'], 'rev_0003')

            # Subsequent automated refresh_l2 / refresh_all MUST NOT overwrite manual rollback back to v2
            r2 = refresh_all(work, formal=False)
            self.assertEqual(r2['l2']['effective_published'], 0)
            idx = PathDataQuery(work).index('v', 'lib')
            self.assertEqual(idx['revisions'], ['rev_0001', 'rev_0002', 'rev_0003'])
            rev3_ver = PathDataQuery(work).file('v', 'lib', 'LEF', 'LEF/a.lef', revision='rev_0003')['effective']['version']
            self.assertEqual(rev3_ver, '20261001_v1')

            # Brand-new v3 arrives -> L2 advances cleanly to rev_0004 (v3)
            p3 = raw / 'v/lib/20261003_v3/LEF/a.lef'
            p3.parent.mkdir(parents=True)
            p3.write_text(_LEF_V3, encoding='utf-8')
            r3 = refresh_all(work, formal=False)
            self.assertEqual(r3['l2']['effective_published'], 1)
            rev4_ver = PathDataQuery(work).file('v', 'lib', 'LEF', 'LEF/a.lef', revision='rev_0004')['effective']['version']
            self.assertEqual(rev4_ver, '20261003_v3')

    def test_p0_split_brain_auto_effective_state_self_heals_under_log(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            p1 = raw / 'v/lib/20261001_v1/LEF/a.lef'
            p1.parent.mkdir(parents=True)
            p1.write_text(_LEF_V1, encoding='utf-8')
            (nl / 'a.lef').symlink_to(p1)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)

            # Simulate legacy split-brain root + log state files after a new delivery arrives
            p2 = raw / 'v/lib/20261002_v2/LEF/a.lef'
            p2.parent.mkdir(parents=True)
            p2.write_text(_LEF_V2, encoding='utf-8')
            refresh_l1(work, formal=False)
            folder = work / 'libraries/v/lib'
            (folder / '.auto_effective_state.json').write_text(json.dumps({'pending': ['20261002_v2']}), encoding='utf-8')

            l2 = refresh_l2(work)
            self.assertEqual(l2['effective_published'], 1)
            self.assertEqual(l2['effective_pending'], 0)
            self.assertFalse((folder / '.auto_effective_state.json').exists())
            merged = json.loads((folder / 'log/.auto_effective_state.json').read_text(encoding='utf-8'))
            self.assertEqual(merged['pending'], [])
            self.assertIn('20261002_v2', merged['processed'])

    def test_p0_multi_delivery_l2_batch_refreshes_l3_index_once(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            p1 = raw / 'v/lib/20261001_v1/LEF/a.lef'
            p1.parent.mkdir(parents=True)
            p1.write_text(_LEF_V1, encoding='utf-8')
            (nl / 'a.lef').symlink_to(p1)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)

            for ver, content in (('20261002_v2', _LEF_V2), ('20261003_v3', _LEF_V3), ('20261004_v4', _LEF_V1)):
                p = raw / 'v/lib' / ver / 'LEF/a.lef'
                p.parent.mkdir(parents=True)
                p.write_text(content, encoding='utf-8')
            refresh_l1(work, formal=False)

            import ai_lib_qor.application.path_refresh as pr
            calls = []
            orig = pr.refresh_index_locked

            def spy(*args, **kwargs):
                calls.append(args)
                return orig(*args, **kwargs)

            with patch.object(pr, 'refresh_index_locked', side_effect=spy):
                l2 = refresh_l2(work)

            self.assertEqual(l2['effective_published'], 3)
            self.assertEqual(len(calls), 1, f'批量推进 3 个版本应仅刷新 1 次 L3 索引，实际刷新 {len(calls)} 次')

    def test_p0_single_library_l1_with_formal_does_not_walk_sibling_libraries(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            p1 = raw / 'V1/L1/20261001_a/LEF/a.lef'
            p1.parent.mkdir(parents=True)
            p1.write_text(_LEF_V1, encoding='utf-8')
            p2 = raw / 'V2/L2/20261001_b/LEF/b.lef'
            p2.parent.mkdir(parents=True)
            p2.write_text(_LEF_V2, encoding='utf-8')
            (nl / 'a.lef').symlink_to(p1)
            (nl / 'b.lef').symlink_to(p2)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))

            walked_roots = []
            real_walk = os.walk

            def tracking_walk(top, *args, **kwargs):
                walked_roots.append(str(top))
                return real_walk(top, *args, **kwargs)

            with patch('os.walk', side_effect=tracking_walk):
                l1 = refresh_l1(work, vendor='V1', library='L1', raw=True, formal=True, verify_raw=True)

            self.assertEqual(l1['delivery_created'], 1)
            self.assertEqual(l1['formal_created'], 1)
            self.assertEqual(l1['formal_observation_status'], 'COMPLETE')
            self.assertEqual(l1['warnings'], [])
            self.assertFalse(any('V2' in w or 'L2' in w for w in walked_roots), f'单库 L1 不得遍历其他库: {walked_roots}')
            self.assertTrue((work / 'libraries/V1/L1/formal').is_dir())
            self.assertFalse((work / 'libraries/V2/L2').exists())

    def test_p0_concurrent_same_scope_web_job_returns_409(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td) / 'work'
            work.mkdir()
            app = create_path_app(work)
            client = app.test_client()
            client.get('/')
            with client.session_transaction() as sess:
                csrf = sess['csrf']

            gate = threading.Event()
            started = threading.Event()

            def slow_l3(*args, **kwargs):
                started.set()
                gate.wait(timeout=5)
                return {'indexes_updated': 0, 'indexes_unchanged': 0, 'indexes_skipped_rebuild': 0, 'indexes_failed': 0, 'warnings': []}

            try:
                with patch('ai_lib_qor.application.path_refresh.refresh_l3', side_effect=slow_l3):
                    r1 = client.post('/api/v1/jobs/refresh', data={'csrf': csrf, 'layer': 'l3'})
                    self.assertEqual(r1.status_code, 202)
                    started.wait(timeout=3)
                    r2 = client.post('/api/v1/jobs/refresh', data={'csrf': csrf, 'layer': 'l3'})
                    self.assertEqual(r2.status_code, 409)
                    payload = r2.get_json()
                    self.assertEqual(payload['active_job']['job_id'], r1.get_json()['job_id'])
            finally:
                gate.set()
                app.extensions['jobs'].shutdown(wait=True)

    def test_p1_stale_tooling_detection_and_check_pending_include_outdated(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            lef = raw / 'v/lib/20261001_v1/LEF/a.lef'
            lib = raw / 'v/lib/20261001_v1/LIB/a.lib'
            lef.parent.mkdir(parents=True)
            lib.parent.mkdir(parents=True)
            lef.write_text(_LEF_V1, encoding='utf-8')
            lib.write_text(_LIB_OK, encoding='utf-8')
            (nl / 'a.lef').symlink_to(lef)
            (nl / 'a.lib').symlink_to(lib)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)

            res = run_revision(work, 'v', 'lib', 'rev_0001', render=False)
            chk_path = Path(res['check'])
            report = json.loads(chk_path.read_text(encoding='utf-8'))
            self.assertIn('tooling', report)
            self.assertIn('LEF', report['tooling']['parser_signatures'])
            self.assertIn('LIBERTY', report['tooling']['parser_signatures'])
            self.assertFalse(check_tooling_status(report)['is_stale'])

            # Simulate an older historical check (e.g., standalone-interface-2 before upgrade)
            legacy = copy.deepcopy(report)
            legacy.pop('tooling', None)
            for ev in legacy['facts_evidence'].values():
                if ev.get('view') == 'LIBERTY':
                    ev['parser']['version'] = 'standalone-interface-2+adapter-1.0'
            chk_path.write_text(json.dumps(legacy), encoding='utf-8')

            st = check_tooling_status(legacy)
            self.assertTrue(st['is_stale'])
            self.assertEqual(st['status'], 'STALE_TOOLING')
            self.assertTrue(any('LIBERTY' in r for r in st['reasons']))

            # Default check_pending skips conservatively but reports outdated_tooling_count == 1
            p_skip = check_pending(work, include_outdated=False)
            self.assertEqual(p_skip['checked_count'], 0)
            self.assertEqual(p_skip['outdated_tooling_count'], 1)
            self.assertEqual(p_skip['skipped_already_checked'][0]['tooling_status'], 'STALE_TOOLING')

            # Overview Excel exporter surfaces P3 STALE_TOOLING advisory without altering verdict
            ov_xlsx = root / 'overview.xlsx'
            ov_res = render_work_overview_excel(work, ov_xlsx, overwrite=True)
            self.assertTrue(ov_xlsx.is_file())
            self.assertGreaterEqual(ov_res['todo_count'], 1)

            # With include_outdated=True, check_pending reruns cleanly
            p_run = check_pending(work, include_outdated=True)
            self.assertEqual(p_run['checked_count'], 1)
            self.assertEqual(p_run['checked'][0]['rerun_reason'], 'STALE_TOOLING')

    def test_p1_higher_version_new_files_auto_merged_with_safety_boundaries(self):
        from ai_lib_qor.application.minimal_effective import apply_update, preview_delivery
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            # v1 has LEF/a.lef + GDS/keep.gds (both in Formal) + DOC/v1_unlinked.txt (NOT in Formal)
            p1 = raw / 'v/lib/20261001_v1/LEF/a.lef'
            g1 = raw / 'v/lib/20261001_v1/GDS/keep.gds'
            u1 = raw / 'v/lib/20261001_v1/DOC/v1_unlinked.txt'
            for p, txt in ((p1, _LEF_V1), (g1, 'gds-v1'), (u1, 'not-in-formal')):
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(txt, encoding='utf-8')
            (nl / 'a.lef').symlink_to(p1)
            (nl / 'keep.gds').symlink_to(g1)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)

            # Baseline v1 unlinked file is NOT retroactively merged; surfaced via unadopted_new_files
            ctx1 = PathDataQuery(work).get_check_context('v', 'lib', 'rev_0001')
            self.assertEqual([(m['view'], m['path']) for m in ctx1['members']], [('GDS', 'GDS/keep.gds'), ('LEF', 'LEF/a.lef')])
            self.assertEqual(unadopted_new_files(work, 'v', 'lib')['count'], 1)

            # Older historical delivery v0 (< v1) arrives with an unlinked file -> MUST NOT be pulled into Effective!
            p0 = raw / 'v/lib/20260901_v0/DOC/ancient.txt'
            p0.parent.mkdir(parents=True, exist_ok=True)
            p0.write_text('old-junk', encoding='utf-8')
            r_old = refresh_all(work, formal=False)
            self.assertEqual(r_old['l2']['effective_published'], 0)

            # Higher version v2 updates a.lef AND adds brand-new LIB/extra.lib (does NOT resend GDS/keep.gds)
            p2 = raw / 'v/lib/20261002_v2/LEF/a.lef'
            extra = raw / 'v/lib/20261002_v2/LIB/extra.lib'
            p2.parent.mkdir(parents=True)
            extra.parent.mkdir(parents=True)
            p2.write_text(_LEF_V2, encoding='utf-8')
            extra.write_text(_LIB_OK, encoding='utf-8')

            full = refresh_all(work, formal=False)
            self.assertEqual(full['l2']['effective_published'], 1)
            self.assertEqual(full['l2']['unadopted_new_files_total'], 0)

            # rev_0002 upgrades LEF/a.lef -> v2, inherits GDS/keep.gds -> v1, AND auto-merges LIB/extra.lib -> v2!
            ctx2 = PathDataQuery(work).get_check_context('v', 'lib', 'rev_0002')
            members2 = {(m['view'], m['path']): m['version'] for m in ctx2['members']}
            self.assertEqual(members2, {
                ('GDS', 'GDS/keep.gds'): '20261001_v1',
                ('LEF', 'LEF/a.lef'): '20261002_v2',
                ('LIBERTY', 'LIB/extra.lib'): '20261002_v2',
            })
            self.assertEqual(unadopted_new_files(work, 'v', 'lib')['count'], 0)
            self.assertEqual(refresh_status(work)['totals']['unadopted_new_files'], 0)

            # Higher version v3 ONLY adds brand-new DOC/release.txt (and an ignored file DOC/skip.txt)
            set_unadopted_ignored(work, 'v', 'lib', 'DOC', 'DOC/skip.txt', ignored=True)
            for name in ('DOC/release.txt', 'DOC/skip.txt'):
                fp = raw / 'v/lib/20261003_v3' / name
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text('v3', encoding='utf-8')
            full3 = refresh_all(work, formal=False)
            self.assertEqual(full3['l2']['effective_published'], 1)
            ctx3 = PathDataQuery(work).get_check_context('v', 'lib', 'rev_0003')
            members3 = {(m['view'], m['path']): m['version'] for m in ctx3['members']}
            self.assertEqual(members3[('DOC', 'DOC/release.txt')], '20261003_v3')
            self.assertNotIn(('DOC', 'DOC/skip.txt'), members3)

            # Manual removal of DOC/release.txt -> rev_0004; re-running L2 MUST NOT re-add it,
            # while unadopted_new_files + Web notice + API cleanly surface the manually removed latest-delivery file!
            apply_update(work, 'v', 'lib', {'set': [], 'remove': [{'view': 'DOC', 'path': 'DOC/release.txt'}]}, expected_parent='rev_0003')
            self.assertEqual(refresh_l2(work)['effective_published'], 0)
            u = unadopted_new_files(work, 'v', 'lib')
            self.assertEqual(u['count'], 1)
            self.assertEqual(u['sample'][0], {'view': 'DOC', 'path': 'DOC/release.txt'})
            app = create_path_app(work)
            client = app.test_client()
            html = client.get('/path/library', query_string={'vendor': 'v', 'library': 'lib'}).get_data(as_text=True)
            self.assertIn('发现未纳入当前有效集的交付文件', html)
            api_lib = client.get('/api/v1/library', query_string={'vendor': 'v', 'library': 'lib'}).get_json()
            self.assertEqual(api_lib['unadopted_new_files']['count'], 1)

            # preview_delivery(include_new=True) also previews merging new paths (skipping ignored)
            prev = preview_delivery(work, 'v', 'lib', '20261003_v3')
            self.assertEqual([op['path'] for op in prev['operations']['set']], ['DOC/release.txt'])

    def test_p2_custom_view_extension_parser_and_plugin_findings_end_to_end(self):
        orig_ext = dict(VIEW_EXTENSIONS)
        orig_parsers = dict(PARSER_REGISTRY)
        orig_plugins = dict(PATH_CHECK_PLUGINS)
        orig_meta = copy.deepcopy(PATH_CHECK_PLUGIN_META)

        def cleanup_registries():
            VIEW_EXTENSIONS.clear()
            VIEW_EXTENSIONS.update(orig_ext)
            PARSER_REGISTRY.clear()
            PARSER_REGISTRY.update(orig_parsers)
            PATH_CHECK_PLUGINS.clear()
            PATH_CHECK_PLUGINS.update(orig_plugins)
            PATH_CHECK_PLUGIN_META.clear()
            PATH_CHECK_PLUGIN_META.update(orig_meta)

        self.addCleanup(cleanup_registries)

        # Register custom extension & custom SPEF parser & custom check plugin with findings[]
        register_view_extension('.rcx', 'SPEF')

        def parse_spef_demo(path, *, allow_pg=False):
            lines = [ln.strip() for ln in Path(path).read_text(encoding='utf-8').splitlines() if ln.strip()]
            return {
                'view': 'SPEF',
                'parser': {'name': 'demo_spef', 'version': '0.1'},
                'parse_status': 'COMPLETE',
                'covered_sections': ['NET_RC'],
                'units': {'cap': 'pF'},
                'objects': {'nets': [{'name': ln.split()[0], 'cap': float(ln.split()[1])} for ln in lines]},
            }

        parse_spef_demo._parser_name = 'demo_spef'
        parse_spef_demo._parser_version = '0.1'
        parse_spef_demo._parser_sig = 'demo_spef:0.1'
        register_parser('SPEF', parse_spef_demo)

        def run_spef_budget(ctx):
            checks = []
            for (view, path), (fp, fact) in ctx['facts'].items():
                if view != 'SPEF':
                    continue
                findings = []
                for net in fact['objects'].get('nets', []):
                    if net['cap'] > 1.0:
                        findings.append({
                            'view': 'SPEF',
                            'path': path,
                            'object_type': 'NET',
                            'object_name': net['name'],
                            'diff_type': '电容超标',
                            'old_value': '<= 1.0 pF',
                            'new_value': f"{net['cap']} pF",
                            'detail': '超出演示阈值 1.0 pF',
                        })
                checks.append({
                    'check_id': 'SPEF_RC_BUDGET',
                    'scope_file_keys': [path],
                    'result': 'FAIL' if findings else 'PASS',
                    'coverage': 'COMPLETE',
                    'facts_refs': [fp.name],
                    'severity': 'ERROR' if findings else 'INFO',
                    'findings': findings,
                    'detail': f'发现 {len(findings)} 条超标网络' if findings else '全部网络电容在阈值内',
                })
            return {'checks': checks}

        register_path_plugin('SPEF_RC_BUDGET', run_spef_budget, description='SPEF 寄生电容预算检查', required_views=('SPEF',))

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            rcx = raw / 'v/lib/20261001_v1/RC/top.rcx'
            rcx.parent.mkdir(parents=True)
            rcx.write_text('clk_net 2.5\ndata_net 0.4\n', encoding='utf-8')
            (nl / 'top.rcx').symlink_to(rcx)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)

            # Verify CLI --plugins flag runs custom plugin and validates against updated schemas
            out = cli_run(cli_parser().parse_args([
                'minimal-check-revision', '--work', str(work), '--vendor', 'v', '--library', 'lib',
                '--revision', 'rev_0001', '--plugins', 'SPEF_RC_BUDGET', '--no-excel',
            ]))
            report = json.loads(Path(out['check']).read_text(encoding='utf-8'))
            self.assertEqual(report['tooling']['plugins'], ['SPEF_RC_BUDGET'])
            self.assertIn('SPEF', report['tooling']['parser_signatures'])
            self.assertIn('SPEF 寄生电容预算检查', report['note'])
            self.assertEqual(report['checks'][0]['result'], 'FAIL')
            self.assertEqual(len(report['checks'][0]['findings']), 1)

            # Verify Excel workbook automatically renders custom plugin findings on Sheet 03 + drill-down link on Sheet 01
            from ai_lib_qor.application.facts_pool import load_check_bundle
            bundle = load_check_bundle(work, 'v', 'lib', Path(out['check']).name)
            spec = build_path_workbook_spec({**bundle['report'], '_path_context': {'index': bundle['index'], 'facts': bundle['facts'], 'acceptance': None}})
            sh01 = next(s for s in spec['sheets'] if s['name'] == '01-风险与检查')
            sh03 = next(s for s in spec['sheets'] if s['name'] == '03-对象与接口差异')
            self.assertTrue(any(r[0] == '插件:SPEF_RC_BUDGET' and r[4] == 'clk_net' for r in sh03['rows']))
            self.assertTrue(any(isinstance(r[5], tuple) and r[5][1] == '03-对象与接口差异' for r in sh01['rows']))

            # Render physical xlsx to verify zero xlsxwriter errors
            xlsx_path = render_excel_from_check(work, 'v', 'lib', Path(out['check']).name)
            self.assertTrue(Path(xlsx_path).is_file())

    def test_audit_derived_watermark_survives_deleted_state_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            p1 = raw / 'v/lib/20261001_v1/LEF/a.lef'
            p2 = raw / 'v/lib/20261002_v2/LEF/a.lef'
            p1.parent.mkdir(parents=True)
            p2.parent.mkdir(parents=True)
            p1.write_text(_LEF_V1, encoding='utf-8')
            p2.write_text(_LEF_V2, encoding='utf-8')
            (nl / 'a.lef').symlink_to(p1)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))

            # Initialize rev_0001 (v1), evolve rev_0002 (v2), then manually roll back to rev_0001 -> rev_0003
            refresh_all(work)
            restore_revision(work, 'v', 'lib', 'rev_0001', expected_parent='rev_0002', actor='engineer')

            # Completely delete mutable .auto_effective_state.json cache!
            folder = work / 'libraries/v/lib'
            state_file = folder / 'log/.auto_effective_state.json'
            if state_file.exists():
                state_file.unlink()
            self.assertIn('20261002_v2', derive_processed_versions(folder, 'lib'))

            # Subsequent L2 / refresh_all MUST STILL NOT overwrite rev_0003 back to buggy v2!
            r = refresh_all(work, formal=False)
            self.assertEqual(r['l2']['effective_published'], 0)
            self.assertEqual(
                PathDataQuery(work).file('v', 'lib', 'LEF', 'LEF/a.lef', revision='rev_0003')['effective']['version'],
                '20261001_v1',
            )

            # Brand-new v3 still advances cleanly to rev_0004
            p3 = raw / 'v/lib/20261003_v3/LEF/a.lef'
            p3.parent.mkdir(parents=True)
            p3.write_text(_LEF_V3, encoding='utf-8')
            r3 = refresh_all(work, formal=False)
            self.assertEqual(r3['l2']['effective_published'], 1)
            self.assertEqual(
                PathDataQuery(work).file('v', 'lib', 'LEF', 'LEF/a.lef', revision='rev_0004')['effective']['version'],
                '20261003_v3',
            )

    def test_manual_apply_before_l2_watermark_in_audit_survives_state_deletion(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            p1 = raw / 'v/lib/20261001_v1/LEF/a.lef'
            p1b = raw / 'v/lib/20261001_v1/LIB/a.lib'
            p2 = raw / 'v/lib/20261002_v2/LEF/a.lef'
            for p, txt in ((p1, _LEF_V1), (p1b, _LIB_OK), (p2, _LEF_V2)):
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(txt, encoding='utf-8')
            (nl / 'a.lef').symlink_to(p1)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))

            # Archive both v1 & v2, initialize rev_0001 from NL1 (only a.lef -> v1), then manually add a.lib -> v1
            refresh_l1(work)
            from ai_lib_qor.application.minimal_effective import initialize_from_formal
            folder = work / 'libraries/v/lib'
            initialize_from_formal(work, 'v', 'lib', next((folder / 'formal').glob('formal_*.json')))
            apply_update(work, 'v', 'lib', {'set': [{'view': 'LIBERTY', 'version': '20261001_v1', 'path': 'LIB/a.lib'}], 'remove': []}, expected_parent='rev_0001', actor='engineer')

            # Delete mutable cache; audit TSV watermark=['20261001_v1','20261002_v2'] still protects manual pin
            (folder / 'log/.auto_effective_state.json').unlink(missing_ok=True)
            l2 = refresh_l2(work)
            self.assertEqual(l2['effective_published'], 0)
            self.assertEqual(
                PathDataQuery(work).file('v', 'lib', 'LEF', 'LEF/a.lef', revision='rev_0002')['effective']['version'],
                '20261001_v1',
            )

    def test_plugin_modules_runtime_loader_and_plugin_version_stale_detection(self):
        import sys
        with isolated_registries(), tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod_dir = root / 'ext_plugins'
            mod_dir.mkdir()
            mod_name = f'demo_ext_plugin_{os.getpid()}'
            (mod_dir / f'{mod_name}.py').write_text(
                "def _run_rule(ctx):\n"
                "    return {'checks': [{'check_id': 'DEMO_RULE', 'scope_file_keys': [], 'result': 'PASS', 'coverage': 'COMPLETE', 'facts_refs': [], 'detail': 'ok'}]}\n"
                "def register(api):\n"
                "    api['register_path_plugin']('DEMO_RULE', _run_rule, version='1.0', description='外部演示规则')\n",
                encoding='utf-8',
            )
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            p1 = raw / 'v/lib/20261001_v1/LEF/a.lef'
            p1.parent.mkdir(parents=True)
            p1.write_text(_LEF_V1, encoding='utf-8')
            (nl / 'a.lef').symlink_to(p1)
            (work / 'path_sources.json').write_text(json.dumps({
                'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1',
                'plugin_modules': [mod_name],
            }))

            sys.path.insert(0, str(mod_dir))
            try:
                refresh_all(work)
                out = cli_run(cli_parser().parse_args([
                    'minimal-check-revision', '--work', str(work), '--vendor', 'v', '--library', 'lib',
                    '--revision', 'rev_0001', '--plugins', 'DEMO_RULE', '--no-excel',
                ]))
                report = json.loads(Path(out['check']).read_text(encoding='utf-8'))
                self.assertEqual(report['tooling']['plugin_versions'], {'DEMO_RULE': '1.0'})
                self.assertFalse(check_tooling_status(report)['is_stale'])

                # Upgrade plugin version 1.0 -> 2.0 => check_tooling_status flags STALE_TOOLING
                PATH_CHECK_PLUGIN_META['DEMO_RULE']['version'] = '2.0'
                st = check_tooling_status(report)
                self.assertTrue(st['is_stale'])
                self.assertTrue(any('DEMO_RULE' in r and '1.0 → 2.0' in r for r in st['reasons']))
            finally:
                sys.path.remove(str(mod_dir))
                sys.modules.pop(mod_name, None)

    def test_fast_runs_jsonl_lookup_validator_cache_and_manifest_unadopted_cache(self):
        from ai_lib_qor.versions.store import _compiled_validator, validate
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            p1 = raw / 'v/lib/20261001_v1/LEF/a.lef'
            p1.parent.mkdir(parents=True)
            p1.write_text(_LEF_V1, encoding='utf-8')
            (nl / 'a.lef').symlink_to(p1)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)
            run_revision(work, 'v', 'lib', 'rev_0001', render=False)

            # Fast O(1) runs.jsonl lookup avoids directory scan
            with patch('ai_lib_qor.application.path_query._iter_saved_checks', side_effect=AssertionError('应命中 runs.jsonl O(1) 快速路径')):
                hit1 = latest_check_for_scope(work, 'v', 'lib', 'rev_0001', None)
                hit2 = latest_check_for_revision(work, 'v', 'lib', 'rev_0001')
            self.assertIsNotNone(hit1)
            self.assertIsNotNone(hit2)
            self.assertEqual(hit1['check_name'], hit2['check_name'])

            # refresh_status reads manifest-cached unadopted count without calling unadopted_new_files()
            with patch('ai_lib_qor.application.path_refresh.unadopted_new_files', side_effect=AssertionError('FRESH 索引应复用 manifest 缓存')):
                st = refresh_status(work)
            self.assertEqual(st['totals']['unadopted_new_files'], 0)

            # Compiled schema validator cache hits
            before_hits = _compiled_validator.cache_info().hits
            folder = work / 'libraries/v/lib'
            eff = json.loads((folder / 'effective/effective_lib_001.json').read_text(encoding='utf-8'))
            validate(eff, 'effective_path')
            validate(eff, 'effective_path')
            self.assertGreater(_compiled_validator.cache_info().hits, before_hits)

    def test_view_extension_drift_warning_and_unadopted_ignore_list(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            p1 = raw / 'v/lib/20261001_v1/LEF/a.lef'
            r1 = raw / 'v/lib/20261001_v1/RC/a.rcx'
            p1.parent.mkdir(parents=True)
            r1.parent.mkdir(parents=True)
            p1.write_text(_LEF_V1, encoding='utf-8')
            r1.write_text('net1 1.0\n', encoding='utf-8')
            (nl / 'a.lef').symlink_to(p1)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)

            # Initially RC/a.rcx is unadopted (OTHER). Ignore it via CLI -> unadopted count drops 1 -> 0!
            self.assertEqual(unadopted_new_files(work, 'v', 'lib')['count'], 1)
            cli_run(cli_parser().parse_args([
                'path-unadopted-ignore', '--work', str(work), '--vendor', 'v', '--library', 'lib',
                '--view', 'OTHER', '--path', 'RC/a.rcx',
            ]))
            u = unadopted_new_files(work, 'v', 'lib')
            self.assertEqual(u['count'], 0)
            self.assertEqual(u['ignored_count'], 1)
            self.assertEqual(refresh_status(work)['totals']['unadopted_new_files'], 0)

            # Unignore restores reminder
            set_unadopted_ignored(work, 'v', 'lib', 'OTHER', 'RC/a.rcx', ignored=False)
            self.assertEqual(unadopted_new_files(work, 'v', 'lib')['count'], 1)

            # Changing view_extensions mapping (.rcx: OTHER -> SPEF) triggers explicit L1 drift warning
            cfg = json.loads((work / 'path_sources.json').read_text(encoding='utf-8'))
            cfg['view_extensions'] = {'.rcx': 'SPEF'}
            (work / 'path_sources.json').write_text(json.dumps(cfg), encoding='utf-8')
            l1 = refresh_l1(work, formal=False)
            self.assertTrue(any('View 映射变更警告' in w and '.rcx' in w for w in l1['warnings']))

    def test_pyproject_and_ci_packaging_metadata(self):
        import tomllib
        repo = Path(__file__).resolve().parents[1]
        data = tomllib.loads((repo / 'pyproject.toml').read_text(encoding='utf-8'))
        self.assertEqual(data['project']['name'], 'ai-lib-qor')
        self.assertEqual(data['project']['scripts']['ai-lib-qor'], 'ai_lib_qor.cli:main')
        self.assertTrue((repo / '.github/workflows/ci.yml').is_file())
        self.assertTrue((repo / 'docs/schema-compatibility.md').is_file())

    def test_mature_index_read_skips_sha256_and_catches_same_size_utime_tampering(self):
        import ai_lib_qor.application.minimal_file_index as mfi
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            p1 = raw / 'v/lib/20261001_v1/LEF/a.lef'
            p1.parent.mkdir(parents=True)
            p1.write_text(_LEF_V1, encoding='utf-8')
            (nl / 'a.lef').symlink_to(p1)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)

            # Simulate a mature archive (written >1s before manifest)
            folder = work / 'libraries/v/lib'
            mpath = folder / '.file_index_manifest.json'
            manifest = json.loads(mpath.read_text(encoding='utf-8'))
            manifest['written_at_ns'] = manifest['written_at_ns'] + 5_000_000_000
            mpath.write_text(json.dumps(manifest), encoding='utf-8')

            with patch.object(mfi, '_sha256_file', side_effect=AssertionError('成熟归档未变更时不应重复计算 SHA-256')):
                idx = PathDataQuery(work).index('v', 'lib')
            self.assertEqual(idx['revisions'], ['rev_0001'])

            # Same-size + preserved mtime tampering still updates ctime_ns -> immediately caught!
            dfile = next((folder / 'delivery').glob('delivery_*.json'))
            st = dfile.stat()
            orig = dfile.read_text(encoding='utf-8')
            tampered = orig.replace('LEF/a.lef', 'LEF/z.lef')
            self.assertEqual(len(tampered), len(orig))
            dfile.write_text(tampered, encoding='utf-8')
            os.utime(dfile, ns=(st.st_atime_ns, st.st_mtime_ns))
            with self.assertRaisesRegex(ValueError, '索引'):
                PathDataQuery(work).index('v', 'lib')

    def test_run_library_verifies_index_once_across_multiple_revisions(self):
        from ai_lib_qor.application.minimal_checks import run_library
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            for ver, content in (('20261001_v1', _LEF_V1), ('20261002_v2', _LEF_V2), ('20261003_v3', _LEF_V3)):
                p = raw / 'v/lib' / ver / 'LEF/a.lef'
                p.parent.mkdir(parents=True)
                p.write_text(content, encoding='utf-8')
            (nl / 'a.lef').symlink_to(raw / 'v/lib/20261001_v1/LEF/a.lef')
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)

            calls = []
            orig_index = PathDataQuery.index

            def spy_index(self_q, *args, **kwargs):
                calls.append(args)
                return orig_index(self_q, *args, **kwargs)

            with patch.object(PathDataQuery, 'index', spy_index):
                res = run_library(work, 'v', 'lib', rerun=True, render_single_excel=False)
            self.assertEqual(len(res['versions']), 3)
            # Only 1 index load/verify for all 3 revisions (instead of 3*N+1 = 10+)!
            self.assertEqual(len(calls), 1, f'库级检查 3 个版本应仅校验加载 1 次索引，实际 {len(calls)} 次')

    def test_runs_jsonl_tail_seek_o1_on_large_history(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            p1 = raw / 'v/lib/20261001_v1/LEF/a.lef'
            p1.parent.mkdir(parents=True)
            p1.write_text(_LEF_V1, encoding='utf-8')
            (nl / 'a.lef').symlink_to(p1)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)
            out = run_revision(work, 'v', 'lib', 'rev_0001', render=False)

            # Prepend >80KB of older synthetic lines before the real latest entry in runs.jsonl
            runs_path = work / 'libraries/v/lib/log/runs.jsonl'
            tail_line = runs_path.read_text(encoding='utf-8')
            filler = json.dumps({'type': 'CHECK', 'revision': 'rev_0000', 'baseline': None, 'json': 'log/old.json', 'pad': 'x' * 200}) + '\n'
            runs_path.write_text(filler * 450 + tail_line, encoding='utf-8')
            self.assertGreater(runs_path.stat().st_size, 80_000)

            with patch('ai_lib_qor.application.path_query._iter_saved_checks', side_effect=AssertionError('应通过 tail-seek O(1) 命中')):
                hit = latest_check_for_scope(work, 'v', 'lib', 'rev_0001', None)
            self.assertIsNotNone(hit)
            self.assertEqual(hit['check_name'], Path(out['check']).name)

    def test_persistent_job_manager_survives_restart_and_recovers_orphans(self):
        from ai_lib_qor.workbench.jobs import JobManager
        import time as _time
        with tempfile.TemporaryDirectory() as td:
            work = Path(td) / 'work'
            work.mkdir()
            mgr1 = JobManager(max_workers=2, work_root=work)
            job = mgr1.submit('refresh', '重启保留测试', lambda cb, ev: {'ok': True}, scope_key='refresh:v/lib')
            deadline = _time.monotonic() + 5
            while _time.monotonic() < deadline and mgr1.get(job['job_id'])['status'] not in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
                _time.sleep(0.02)
            self.assertEqual(mgr1.get(job['job_id'])['status'], 'SUCCEEDED')
            mgr1.shutdown(wait=True)

            # Seed an orphaned RUNNING job + lease owned by dead PID 99999999
            dead_jid = 'job_dead000000000001'
            import socket
            (work / '.jobs/jobs' / f'{dead_jid}.json').write_text(json.dumps({
                'job_id': dead_jid, 'kind': 'refresh', 'label': '中断任务', 'scope_key': 'refresh:v/orphan',
                'status': 'RUNNING', 'stage': 'L1', 'message': '运行中', 'completed': 0, 'total': 10,
                'percent': 0, 'events': [], 'cancel_requested': False,
                'created_at': '2026-11-22T00:00:00Z', 'started_at': '2026-11-22T00:00:01Z',
                'finished_at': None, 'elapsed_seconds': 1.0, 'result': None, 'error': None,
                'owner_host': socket.gethostname(), 'owner_pid': 99999999,
                'created_ts': _time.time() - 10, 'started_ts': _time.time() - 9,
            }), encoding='utf-8')
            from ai_lib_qor.workbench.jobs import _scope_hash
            (work / '.jobs/leases' / f"{_scope_hash('refresh:v/orphan')}.json").write_text(json.dumps({
                'scope_key': 'refresh:v/orphan', 'job_id': dead_jid,
                'owner_host': socket.gethostname(), 'owner_pid': 99999999,
            }), encoding='utf-8')

            # Fresh JobManager simulating service restart
            mgr2 = JobManager(max_workers=2, work_root=work)
            try:
                persisted = mgr2.get(job['job_id'])
                self.assertIsNotNone(persisted)
                self.assertEqual(persisted['status'], 'SUCCEEDED')
                self.assertEqual(persisted['result'], {'ok': True})

                recovered = mgr2.get(dead_jid)
                self.assertEqual(recovered['status'], 'FAILED')
                self.assertEqual(recovered['stage'], 'INTERRUPTED')

                # Reclaimed stale scope lease allows submitting a new job on the same scope
                fresh_job = mgr2.submit('refresh', '重新发起', lambda cb, ev: {'reclaimed': True}, scope_key='refresh:v/orphan')
                self.assertIn(fresh_job['status'], ('QUEUED', 'RUNNING', 'SUCCEEDED'))
            finally:
                mgr2.shutdown(wait=True)

    def test_cross_worker_scope_conflict_and_cross_worker_cancel(self):
        from ai_lib_qor.versions.runtime import check_cancel
        from ai_lib_qor.workbench.jobs import JobConflictError, JobManager
        import time as _time
        with tempfile.TemporaryDirectory() as td:
            work = Path(td) / 'work'
            work.mkdir()
            mgr_a = JobManager(max_workers=2, work_root=work)
            mgr_b = JobManager(max_workers=2, work_root=work)
            try:
                started = threading.Event()

                def long_worker(cb, ev):
                    started.set()
                    for i in range(200):
                        check_cancel(ev, '跨进程安全终止')
                        cb('STEP', f'step {i}', completed=i, total=200)
                        _time.sleep(0.02)
                    return {'done': True}

                j1 = mgr_a.submit('refresh', 'Worker-A 任务', long_worker, scope_key='refresh:v/lib')
                self.assertTrue(started.wait(timeout=3))

                # Independent Worker-B sees Worker-A's job live and rejects duplicate scope via atomic disk lease
                seen_b = mgr_b.get(j1['job_id'])
                self.assertIsNotNone(seen_b)
                self.assertIn(seen_b['status'], ('QUEUED', 'RUNNING'))
                with self.assertRaises(JobConflictError) as ctx:
                    mgr_b.submit('refresh', 'Worker-B 重复任务', lambda cb, ev: None, scope_key='refresh:v/lib')
                self.assertEqual(ctx.exception.active_job['job_id'], j1['job_id'])

                # Worker-B cancels Worker-A's running job via cross-process cancel flag
                mgr_b.cancel(j1['job_id'])
                deadline = _time.monotonic() + 5
                while _time.monotonic() < deadline and mgr_a.get(j1['job_id'])['status'] not in ('CANCELLED', 'SUCCEEDED', 'FAILED'):
                    _time.sleep(0.02)
                self.assertEqual(mgr_a.get(j1['job_id'])['status'], 'CANCELLED')
            finally:
                mgr_a.shutdown(wait=True)
                mgr_b.shutdown(wait=True)

    def test_runtime_lock_ordering_guard(self):
        from ai_lib_qor.versions.store import locked
        with tempfile.TemporaryDirectory() as td:
            work = Path(td) / 'work'
            lib_a = work / 'libraries/v/lib_a'
            lib_b = work / 'libraries/v/lib_b'
            lib_a.mkdir(parents=True)
            lib_b.mkdir(parents=True)

            # Correct order: library lock FIRST, then workspace root lock -> succeeds
            with locked(lib_a):
                with locked(work):
                    pass

            # Inverted order: workspace root lock FIRST, then library lock -> raises RuntimeError immediately
            with locked(work):
                with self.assertRaisesRegex(RuntimeError, '违反锁序规范'):
                    with locked(lib_a):
                        pass

            # Same-thread re-entrancy -> raises RuntimeError immediately instead of self-deadlocking
            with locked(lib_a):
                with self.assertRaisesRegex(RuntimeError, '不可重入'):
                    with locked(lib_a):
                        pass

            # Reversed sibling library order -> raises RuntimeError
            with locked(lib_b):
                with self.assertRaisesRegex(RuntimeError, '同级多库锁序'):
                    with locked(lib_a):
                        pass

    def test_p1_zero_executed_checks_never_reports_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            p1 = raw / 'v/lib/20261001_v1/LEF/a.lef'
            p1.parent.mkdir(parents=True)
            p1.write_text(_LEF_V1, encoding='utf-8')
            (nl / 'a.lef').symlink_to(p1)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)

            # Diff-only plugin with no baseline -> MUST record INCONCLUSIVE and state=PARTIAL (never SCOPE_PASS)
            res = run_revision(work, 'v', 'lib', 'rev_0001', baseline='__none__', plugins=['LEF_MACRO_DIFF'], render=False)
            self.assertEqual(res['state'], 'PARTIAL')
            report = json.loads(Path(res['check']).read_text(encoding='utf-8'))
            self.assertEqual(report['summary']['inconclusive_checks'], 1)
            self.assertEqual(report['checks'][0]['check_id'], 'LEF_MACRO_DIFF')
            self.assertEqual(report['checks'][0]['result'], 'INCONCLUSIVE')

            found = latest_check_for_scope(work, 'v', 'lib', 'rev_0001', None, plugins=['LEF_MACRO_DIFF'])
            self.assertEqual(found['quality_code'], 'PARTIAL')
            self.assertNotEqual(found['quality_text'], '已覆盖范围通过')

            # Even a legacy report with empty checks & comparisons must never display SCOPE_PASS
            from ai_lib_qor.application.facts_pool import load_check_bundle
            bundle = load_check_bundle(work, 'v', 'lib', Path(res['check']).name)
            empty_rep = {**bundle['report'], 'state': 'SUCCEEDED', 'checks': [], 'comparisons': [], 'partial_comparisons': [],
                         'summary': {**bundle['report']['summary'], 'inconclusive_checks': 0}}
            spec = build_path_workbook_spec({**empty_rep, '_path_context': {'index': bundle['index'], 'facts': bundle['facts'], 'acceptance': None}})
            self.assertEqual(spec['sheets'][0]['verdict_code'], 'PARTIAL')

    def test_p1_check_pending_respects_plugin_set(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            lef = raw / 'v/lib/20261001_v1/LEF/a.lef'
            lib = raw / 'v/lib/20261001_v1/LIB/a.lib'
            lef.parent.mkdir(parents=True)
            lib.parent.mkdir(parents=True)
            lef.write_text(_LEF_V1, encoding='utf-8')
            lib.write_text(_LIB_OK, encoding='utf-8')
            (nl / 'a.lef').symlink_to(lef)
            (nl / 'a.lib').symlink_to(lib)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)

            # 1. Save a check with ONLY LEF_MACRO_DIFF
            run_revision(work, 'v', 'lib', 'rev_0001', plugins=['LEF_MACRO_DIFF'], render=False)
            # 2. Request LEF_LIBERTY_PIN_MATCH -> MUST NOT skip!
            r1 = check_pending(work, plugins=['LEF_LIBERTY_PIN_MATCH'])
            self.assertEqual(r1['checked_count'], 1)
            self.assertEqual(r1['skipped_already_checked_count'], 0)
            # 3. Same plugin set again -> skips cleanly
            r2 = check_pending(work, plugins=['LEF_LIBERTY_PIN_MATCH'])
            self.assertEqual(r2['checked_count'], 0)
            self.assertEqual(r2['skipped_already_checked_count'], 1)
            # 4. Default full plugin set -> MUST NOT skip because neither single-plugin run covered all defaults!
            r3 = check_pending(work)
            self.assertEqual(r3['checked_count'], 1)

    def test_p1_orphan_cache_clean_cannot_delete_in_flight_check_evidence(self):
        from ai_lib_qor.application.facts_pool import load_check_bundle
        from ai_lib_qor.application.path_storage import clean_cache
        import ai_lib_qor.application.minimal_checks as mc
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            lef = raw / 'v/lib/20261001_v1/LEF/a.lef'
            lib = raw / 'v/lib/20261001_v1/LIB/a.lib'
            lef.parent.mkdir(parents=True)
            lib.parent.mkdir(parents=True)
            lef.write_text(_LEF_V1, encoding='utf-8')
            lib.write_text(_LIB_OK, encoding='utf-8')
            (nl / 'a.lef').symlink_to(lef)
            (nl / 'a.lib').symlink_to(lib)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)

            # Trigger clean_cache(--orphan-facts --apply) right after run_path_plugins, BEFORE CheckResult is published
            orig_plugins = mc.run_path_plugins

            def interleaved_clean(*args, **kwargs):
                out = orig_plugins(*args, **kwargs)
                clean_cache(work, clean_excel=False, clean_orphan_facts=True, dry_run=False)
                return out

            with patch.object(mc, 'run_path_plugins', side_effect=interleaved_clean):
                res = run_revision(work, 'v', 'lib', 'rev_0001', render=False)

            folder = work / 'libraries/v/lib'
            report = json.loads(Path(res['check']).read_text(encoding='utf-8'))
            self.assertGreaterEqual(len(report['facts_evidence']), 2)
            for ptr in report['facts_evidence'].values():
                self.assertTrue((folder / ptr['pool_file']).is_file(), f'发布后证据文件缺失: {ptr["pool_file"]}')
            bundle = load_check_bundle(work, 'v', 'lib', Path(res['check']).name)
            self.assertGreaterEqual(len(bundle['facts']), 2)

            # Subsequent orphan clean still preserves all referenced pool files
            cleaned = clean_cache(work, clean_excel=False, clean_orphan_facts=True, dry_run=False)
            self.assertEqual(cleaned['removed_count'], 0)

    def test_p1_rebuilt_excel_from_old_run_excludes_subsequent_deliveries(self):
        from ai_lib_qor.application.facts_pool import load_check_bundle
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            p1 = raw / 'v/lib/20261001_v1/LEF/a.lef'
            p1.parent.mkdir(parents=True)
            p1.write_text(_LEF_V1, encoding='utf-8')
            (nl / 'a.lef').symlink_to(p1)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)

            old_run = run_revision(work, 'v', 'lib', 'rev_0001', render=False)
            old_report = json.loads(Path(old_run['check']).read_text(encoding='utf-8'))
            self.assertEqual(old_report['report_context']['deliveries'], ['20261001_v1'])

            # Add a subsequent delivery AFTER old_run
            p2 = raw / 'v/lib/20261002_v2/LEF/a.lef'
            extra = raw / 'v/lib/20261002_v2/LIB/future_only.lib'
            p2.parent.mkdir(parents=True)
            extra.parent.mkdir(parents=True)
            p2.write_text(_LEF_V2, encoding='utf-8')
            extra.write_text(_LIB_OK, encoding='utf-8')
            refresh_all(work, formal=False)

            # Rebuild workbook model from old_run -> MUST NOT leak 20261002_v2 or future_only.lib!
            bundle = load_check_bundle(work, 'v', 'lib', Path(old_run['check']).name)
            spec = build_path_workbook_spec({**bundle['report'], '_path_context': {'index': bundle['index'], 'facts': bundle['facts'], 'acceptance': None}})
            sh02 = next(s for s in spec['sheets'] if s['name'] == '02-文件版本矩阵')
            flat_text = json.dumps(sh02['rows'], ensure_ascii=False)
            self.assertNotIn('20261002_v2', flat_text)
            self.assertNotIn('future_only.lib', flat_text)
            self.assertEqual([d['version'] for d in bundle['index']['deliveries']], ['20261001_v1'])

    def test_p1_live_quiet_job_never_timeout_reclaimed_by_other_worker(self):
        from ai_lib_qor.workbench.jobs import JobConflictError, JobManager
        import time as _time
        with tempfile.TemporaryDirectory() as td:
            work = Path(td) / 'work'
            work.mkdir()
            mgr_a = JobManager(max_workers=2, work_root=work)
            mgr_b = JobManager(max_workers=2, work_root=work)
            try:
                started = threading.Event()
                release = threading.Event()

                def quiet_job(cb, ev):
                    started.set()
                    release.wait(timeout=3)
                    return {'ok': True}

                j1 = mgr_a.submit('refresh', '静默长任务', quiet_job, scope_key='refresh:v/quiet')
                self.assertTrue(started.wait(timeout=2))
                _time.sleep(0.12)

                # Another worker MUST NOT mark the live local process's job as FAILED or steal its scope lease!
                seen = mgr_b.get(j1['job_id'])
                self.assertEqual(seen['status'], 'RUNNING')
                with self.assertRaises(JobConflictError):
                    mgr_b.submit('refresh', '重复任务', lambda cb, ev: None, scope_key='refresh:v/quiet')

                # Verify dead heartbeat_ts field is no longer persisted in job or lease JSON
                job_disk = json.loads((work / '.jobs/jobs' / f"{j1['job_id']}.json").read_text(encoding='utf-8'))
                self.assertNotIn('heartbeat_ts', job_disk)
                for lease_file in (work / '.jobs/leases').glob('*.json'):
                    self.assertNotIn('heartbeat_ts', json.loads(lease_file.read_text(encoding='utf-8')))

                release.set()
                deadline = _time.monotonic() + 3
                while _time.monotonic() < deadline and mgr_b.get(j1['job_id'])['status'] != 'SUCCEEDED':
                    _time.sleep(0.02)
                self.assertEqual(mgr_b.get(j1['job_id'])['status'], 'SUCCEEDED')
            finally:
                release.set()
                mgr_a.shutdown(wait=True)
                mgr_b.shutdown(wait=True)

    def test_p2_latest_check_json_and_xlsx_pointers_stay_paired(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            p1 = raw / 'v/lib/20261001_v1/LEF/a.lef'
            p2 = raw / 'v/lib/20261002_v2/LEF/a.lef'
            p1.parent.mkdir(parents=True)
            p2.parent.mkdir(parents=True)
            p1.write_text(_LEF_V1, encoding='utf-8')
            p2.write_text(_LEF_V2, encoding='utf-8')
            (nl / 'a.lef').symlink_to(p1)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)

            folder = work / 'libraries/v/lib'
            r2 = run_revision(work, 'v', 'lib', 'rev_0002', render=True)
            self.assertEqual(os.readlink(folder / 'latest_check.json'), f'log/{Path(r2["check"]).name}')
            self.assertEqual(os.readlink(folder / 'latest_check.xlsx'), f'log/{Path(r2["excel"]).name}')

            # Run rev_0001 with --no-excel (render=False) -> latest_check.xlsx MUST NOT keep pointing to rev_0002!
            r1 = run_revision(work, 'v', 'lib', 'rev_0001', render=False)
            self.assertEqual(os.readlink(folder / 'latest_check.json'), f'log/{Path(r1["check"]).name}')
            self.assertFalse((folder / 'latest_check.xlsx').exists() or (folder / 'latest_check.xlsx').is_symlink())

    def test_convergence_cold_check_single_raw_hash_and_single_stat_summary(self):
        import ai_lib_qor.application.minimal_checks as mc
        import ai_lib_qor.facts.parsers as fp
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            lef = raw / 'v/lib/20261001_v1/LEF/a.lef'
            lib = raw / 'v/lib/20261001_v1/LIB/a.lib'
            lef.parent.mkdir(parents=True)
            lib.parent.mkdir(parents=True)
            lef.write_text(_LEF_V1, encoding='utf-8')
            lib.write_text(_LIB_OK, encoding='utf-8')
            (nl / 'a.lef').symlink_to(lef)
            (nl / 'a.lib').symlink_to(lib)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)

            # Verify manifest stores ONE unified stat summary (fast_stat with 5-tuples, no duplicate strict_stat key)
            manifest = json.loads((work / 'libraries/v/lib/.file_index_manifest.json').read_text(encoding='utf-8'))
            self.assertIn('fast_stat', manifest)
            self.assertNotIn('strict_stat', manifest)
            self.assertEqual(len(manifest['fast_stat']['index']), 4)

            # Wait past 50ms racy-git window so files are mature, then count RAW SHA-256 calls during cold check
            import time as _time
            _time.sleep(0.06)
            digest_calls = []
            orig_digest = fp._file_digest

            def spy_digest(path):
                digest_calls.append(str(path))
                return orig_digest(path)

            with patch.object(mc, '_file_digest', side_effect=spy_digest), patch.object(fp, '_file_digest', side_effect=spy_digest):
                run_revision(work, 'v', 'lib', 'rev_0001', render=False)
            # 2 mature parsed files -> EXACTLY 2 SHA-256 calls (1 per file, down from 4-5 per file)!
            self.assertEqual(len(digest_calls), 2, f'2 个成熟 RAW 文件冷检查应仅哈希 2 次，实际 {len(digest_calls)} 次')

    def test_p1_publish_mtime_drift_reuses_held_lock_without_reentry_error(self):
        import ai_lib_qor.application.minimal_checks as mc
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            lef = raw / 'v/lib/20261001_v1/LEF/a.lef'
            lib = raw / 'v/lib/20261001_v1/LIB/a.lib'
            lef.parent.mkdir(parents=True)
            lib.parent.mkdir(parents=True)
            lef.write_text(_LEF_V1, encoding='utf-8')
            lib.write_text(_LIB_OK, encoding='utf-8')
            (nl / 'a.lef').symlink_to(lef)
            (nl / 'a.lib').symlink_to(lib)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)

            idx_path = work / 'libraries/v/lib/file_index.json'
            orig_plugins = mc.run_path_plugins

            def touch_index_mtime(*args, **kwargs):
                out = orig_plugins(*args, **kwargs)
                st = idx_path.stat()
                os.utime(idx_path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
                return out

            with patch.object(mc, 'run_path_plugins', side_effect=touch_index_mtime):
                res = run_revision(work, 'v', 'lib', 'rev_0001', render=False)
            self.assertEqual(res['state'], 'SUCCEEDED')
            self.assertTrue(Path(res['check']).is_file())

    def test_p1_multi_plugin_records_unexecuted_rule_and_prevents_pass(self):
        from ai_lib_qor.application.facts_pool import load_check_bundle
        from ai_lib_qor.reporting.qor_views import build_check_view
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            lef = raw / 'v/lib/20261001_v1/LEF/a.lef'
            lib = raw / 'v/lib/20261001_v1/LIB/a.lib'
            lef.parent.mkdir(parents=True)
            lib.parent.mkdir(parents=True)
            lef.write_text(_LEF_V1, encoding='utf-8')
            lib.write_text(_LIB_OK, encoding='utf-8')
            (nl / 'a.lef').symlink_to(lef)
            (nl / 'a.lib').symlink_to(lib)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)

            # Explicitly request Pin match + LEF diff with NO baseline -> Pin PASSes, LEF diff did NOT execute!
            res = run_revision(
                work, 'v', 'lib', 'rev_0001',
                baseline='__none__',
                plugins=['LEF_LIBERTY_PIN_MATCH', 'LEF_MACRO_DIFF'],
                render=False,
            )
            self.assertEqual(res['state'], 'PARTIAL')
            report = json.loads(Path(res['check']).read_text(encoding='utf-8'))
            self.assertEqual(
                report['tooling']['plugin_coverage'],
                {'LEF_LIBERTY_PIN_MATCH': 'EXECUTED', 'LEF_MACRO_DIFF': 'NOT_EXECUTED'},
            )
            by_id = {c['check_id']: c['result'] for c in report['checks']}
            self.assertEqual(by_id['LEF_LIBERTY_PIN_MATCH'], 'PASS')
            self.assertEqual(by_id['LEF_MACRO_DIFF'], 'INCONCLUSIVE')
            self.assertEqual(report['summary']['inconclusive_checks'], 1)

            # Unified verdict across list, detail view, API, and Excel: ALL PARTIAL, NEVER SCOPE_PASS
            check_name = Path(res['check']).name
            found = latest_check_for_scope(work, 'v', 'lib', 'rev_0001', None, plugins=['LEF_LIBERTY_PIN_MATCH', 'LEF_MACRO_DIFF'])
            self.assertEqual(found['quality_code'], 'PARTIAL')
            detail = build_check_view(work, 'v', 'lib', check_name)
            self.assertEqual(detail['quality']['code'], 'PARTIAL')
            bundle = load_check_bundle(work, 'v', 'lib', check_name)
            spec = build_path_workbook_spec({**bundle['report'], '_path_context': {'index': bundle['index'], 'facts': bundle['facts'], 'acceptance': None}})
            self.assertEqual(spec['sheets'][0]['verdict_code'], 'PARTIAL')

    def test_p1_legacy_zero_result_unified_verdict_in_detail_api_list_and_excel(self):
        from ai_lib_qor.reporting.overall_excel import _verdict_label
        from ai_lib_qor.reporting.qor_views import build_check_view
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            lef = raw / 'v/lib/20261001_v1/LEF/a.lef'
            lef.parent.mkdir(parents=True)
            lef.write_text(_LEF_V1, encoding='utf-8')
            (nl / 'a.lef').symlink_to(lef)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)

            # Write a historical-format SUCCEEDED CheckResult with zero checks & zero comparisons
            folder = work / 'libraries/v/lib'
            legacy_name = 'check_rev_0001_run_00000000000000000000000000000001.json'
            legacy_report = {
                'schema_version': 'check_result.path.v1',
                'run_id': 'run_00000000000000000000000000000001',
                'vendor': 'v',
                'library': 'lib',
                'revision': 'rev_0001',
                'baseline': None,
                'run_at': '2026-11-01T00:00:00Z',
                'state': 'SUCCEEDED',
                'files': [{
                    'view': 'LEF', 'path': 'LEF/a.lef', 'version': '20261001_v1',
                    'absolute_path': str(lef), 'status': 'PARSED', 'facts': None, 'note': 'ok',
                }],
                'checks': [],
                'comparisons': [],
                'partial_comparisons': [],
                'changes': [],
                'summary': {
                    'failed_checks': 0,
                    'inconclusive_checks': 0,
                    'failed_files': 0,
                    'files_with_new_source': 0,
                    'files_with_confirmed_content_change': 0,
                },
                'note': 'legacy empty run',
            }
            (folder / 'log').mkdir(parents=True, exist_ok=True)
            (folder / 'log' / legacy_name).write_text(json.dumps(legacy_report, ensure_ascii=False), encoding='utf-8')

            # 1. Detail view helper
            view = build_check_view(work, 'v', 'lib', legacy_name)
            self.assertEqual(view['quality']['code'], 'PARTIAL')
            self.assertNotEqual(view['quality']['text'], '已覆盖范围通过')

            # 2. Web detail HTML & JSON API & library list page
            app = create_path_app(work)
            self.addCleanup(app.extensions['jobs'].shutdown, wait=True)
            client = app.test_client()
            api_resp = client.get('/api/v1/check', query_string={'vendor': 'v', 'library': 'lib', 'name': legacy_name})
            self.assertEqual(api_resp.status_code, 200)
            self.assertEqual(api_resp.get_json()['quality']['code'], 'PARTIAL')

            html_resp = client.get('/path/check/view', query_string={'vendor': 'v', 'library': 'lib', 'name': legacy_name})
            self.assertEqual(html_resp.status_code, 200)
            self.assertNotIn('已覆盖范围通过', html_resp.get_data(as_text=True))

            lib_resp = client.get('/path/library', query_string={'vendor': 'v', 'library': 'lib', 'revision': 'rev_0001'})
            self.assertEqual(lib_resp.status_code, 200)
            lib_html = lib_resp.get_data(as_text=True)
            self.assertIn('未执行有效检查 / 无结论', lib_html)
            self.assertNotIn('data-quality="SCOPE_PASS"', lib_html)

            # 3. Check lookup & overall verdict helper
            found = latest_check_for_scope(work, 'v', 'lib', 'rev_0001', None)
            self.assertEqual(found['quality_code'], 'PARTIAL')
            self.assertNotEqual(_verdict_label(legacy_report), '已覆盖范围通过')

    def test_p2_same_second_formal_snapshot_never_leaks_into_old_report(self):
        from ai_lib_qor.application.facts_pool import load_check_bundle
        from ai_lib_qor.application.minimal_file_index import refresh_index
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            p1 = raw / 'v/lib/20261001_v1/LEF/a.lef'
            p2 = raw / 'v/lib/20261002_v2/LEF/a.lef'
            p1.parent.mkdir(parents=True)
            p2.parent.mkdir(parents=True)
            p1.write_text(_LEF_V1, encoding='utf-8')
            p2.write_text(_LEF_V2, encoding='utf-8')
            (nl / 'a.lef').symlink_to(p1)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)

            folder = work / 'libraries/v/lib'
            first_snap_file = next((folder / 'formal').glob('formal_*.json'))
            first_snap = json.loads(first_snap_file.read_text(encoding='utf-8'))

            old_run = run_revision(work, 'v', 'lib', 'rev_0001', render=False)
            old_report = json.loads(Path(old_run['check']).read_text(encoding='utf-8'))
            self.assertEqual(old_report['report_context']['formal_snapshots'], [first_snap_file.name])

            # Add a SECOND Formal snapshot in the EXACT SAME SECOND pointing to 20261002_v2
            second_snap = copy.deepcopy(first_snap)
            second_snap['views'] = {
                'LEF': {
                    '20261002_v2': [{
                        'path': 'a.lef',
                        'target': str(p2),
                        'resolved': str(p2.resolve()),
                    }],
                },
            }
            second_name = first_snap_file.stem.rsplit('_', 1)[0] + '_002.json'
            if second_name == first_snap_file.name:
                second_name = first_snap_file.stem + '_002.json'
            (folder / 'formal' / second_name).write_text(json.dumps(second_snap, ensure_ascii=False), encoding='utf-8')
            refresh_index(work, 'v', 'lib')

            live_idx = PathDataQuery(work).index('v', 'lib')
            self.assertEqual(len(live_idx['nl_snapshots']), 2)

            # Rebuilding bundle & workbook for old_run MUST keep strictly 1 Formal snapshot (v1 only)!
            bundle = load_check_bundle(work, 'v', 'lib', Path(old_run['check']).name)
            self.assertEqual(len(bundle['index']['nl_snapshots']), 1)
            nl_entries = bundle['index']['views']['LEF']['LEF/a.lef']['nl']
            self.assertEqual(len(nl_entries), 1)
            self.assertEqual(nl_entries[0]['resolved_path'], str(p1.resolve()))

            spec = build_path_workbook_spec({**bundle['report'], '_path_context': {'index': bundle['index'], 'facts': bundle['facts'], 'acceptance': None}})
            sh07 = next(s for s in spec['sheets'] if s['name'] == '07-正式库与证据溯源')
            self.assertEqual(len(sh07['formal_rows']), 1)
            self.assertNotIn('20261002_v2', json.dumps(sh07['formal_rows'], ensure_ascii=False))

    def test_convergence_cold_check_avoids_per_file_archive_enumeration(self):
        import ai_lib_qor.application.minimal_file_index as mfi
        from ai_lib_qor.application.minimal_facts import build_facts
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()
            # 6 distinct parseable files in one revision
            for idx in range(3):
                lef = raw / f'v/lib/20261001_v1/LEF/m{idx}.lef'
                lib = raw / f'v/lib/20261001_v1/LIB/m{idx}.lib'
                lef.parent.mkdir(parents=True, exist_ok=True)
                lib.parent.mkdir(parents=True, exist_ok=True)
                lef.write_text(f'MACRO M{idx}\n SIZE 2 BY 3 ;\n PIN A\n  DIRECTION INPUT ;\n END A\nEND M{idx}\n', encoding='utf-8')
                lib.write_text(f'library(demo{idx}) {{\n cell(M{idx}) {{\n  pin(A) {{ direction : input; }}\n }}\n}}\n', encoding='utf-8')
                (nl / f'm{idx}.lef').symlink_to(lef)
                (nl / f'm{idx}.lib').symlink_to(lib)
            (work / 'path_sources.json').write_text(json.dumps({'raw_root': str(raw), 'nl_root': str(nl), 'nl_version': 'NL1'}))
            refresh_all(work)

            stat_calls = []
            orig_stat = mfi._archive_stat_summary

            def spy_stat(*args, **kwargs):
                stat_calls.append(args[:3])
                return orig_stat(*args, **kwargs)

            with patch.object(mfi, '_archive_stat_summary', side_effect=spy_stat), \
                 patch('ai_lib_qor.application.path_query._archive_stat_summary', side_effect=spy_stat):
                res = run_revision(work, 'v', 'lib', 'rev_0001', render=False)
            self.assertEqual(res['state'], 'SUCCEEDED')
            # 6 parsed files -> ONLY 2 archive enumerations (1 at check start + 1 at publish; zero per-file scans!)
            self.assertEqual(len(stat_calls), 2, f'6 文件冷检查归档枚举应为 2 次（开始+发布），实际 {len(stat_calls)} 次')

            # Explicit standalone single-file build_facts STILL performs independent archive check and writes log/facts_*.json
            standalone = build_facts(work, 'v', 'lib', 'LEF', 'LEF/m0.lef', version='20261001_v1')
            self.assertTrue(Path(standalone['path']).is_file())


if __name__ == '__main__':
    unittest.main()
