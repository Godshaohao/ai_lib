from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SMOKE_CONFIG = ROOT / "work" / "single_library_smoke_20260805" / "lib_guard.yml"
LIBRARY = "vendor_A.openroad_platform.openroad_asap7"


class WebAppTest(unittest.TestCase):
    def test_effective_recommendation_uses_full_catalog_not_version_page(self):
        from lib_guard.web.app import create_app
        with tempfile.TemporaryDirectory() as td, patch.dict('os.environ', {}, clear=True):
            root = Path(td)
            workspace = root / 'workspace'
            (root / 'raw').mkdir()
            client = create_app(cwd=root, test_config={'TESTING': True}).test_client()
            self.assertEqual(client.post('/api/workspace/init', json={
                'workspace': str(workspace), 'raw_root': str(root / 'raw'),
            }).status_code, 200)
            catalog = workspace / 'catalog/catalog.json'
            catalog.parent.mkdir(parents=True, exist_ok=True)
            versions = [{'version_id': '20240101_full', 'package_type': 'FULL_PACKAGE'}]
            versions.extend({'version_id': f'2025{i + 101:04d}_fix', 'package_type': 'PARTIAL_UPDATE'} for i in range(105))
            catalog.write_text(json.dumps({'libraries': [{'library_id': 'demo', 'library_name': 'demo', 'versions': versions}]}))
            page = client.get('/api/libraries/demo/versions?limit=100').get_json()
            self.assertEqual(len(page['versions']), 100)
            self.assertNotIn('20240101_full', [row['version_id'] for row in page['versions']])
            response = client.get('/api/libraries/demo/effective-recommendation')
            self.assertEqual(response.status_code, 200, response.get_json())
            choice = response.get_json()['recommendation']
            self.assertEqual(choice['base_full'], '20240101_full')
            self.assertEqual(len(choice['includes']), 105)
            self.assertEqual(choice['source'], 'catalog_recommendation')

    def test_effective_recommendation_explains_omitted_versions(self):
        from lib_guard.web.app import create_app
        with tempfile.TemporaryDirectory() as td, patch.dict('os.environ', {}, clear=True):
            root = Path(td)
            (root / 'raw').mkdir()
            workspace = root / 'workspace'
            client = create_app(cwd=root, test_config={'TESTING': True}).test_client()
            self.assertEqual(client.post('/api/workspace/init', json={
                'workspace': str(workspace), 'raw_root': str(root / 'raw'),
            }).status_code, 200)
            catalog = workspace / 'catalog/catalog.json'
            catalog.parent.mkdir(parents=True, exist_ok=True)
            catalog.write_text(json.dumps({'libraries': [{'library_id': 'demo', 'library_name': 'demo', 'versions': [
                {'version_id': '20240101_full', 'package_type': 'FULL_PACKAGE'},
                {'version_id': '20240201_fix', 'package_type': 'PARTIAL_UPDATE'},
                {'version_id': '20250101_full', 'package_type': 'FULL_PACKAGE'},
                {'version_id': '20250201_unknown', 'package_type': 'UNKNOWN_PACKAGE'},
                {'version_id': '20250301_fix', 'package_type': 'PARTIAL_UPDATE'},
            ]}]}))
            response = client.get('/api/libraries/demo/effective-recommendation')
            self.assertEqual(response.status_code, 200, response.get_json())
            data = response.get_json()
            self.assertEqual(data['recommendation']['base_full'], '20250101_full')
            self.assertEqual(data['recommendation']['includes'], ['20250301_fix'])
            self.assertEqual({row['version'] for row in data['excluded']},
                             {'20240101_full', '20240201_fix', '20250201_unknown'})
            self.assertTrue(all(row['reason'] for row in data['excluded']))

    def test_web_refresh_partial_report_preserves_package_gap_without_unusable_verdict(self):
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td, patch.dict('os.environ', {}, clear=True):
            root = Path(td)
            workspace = root / 'workspace'
            raw = root / 'raw/fix_lef'
            raw.mkdir(parents=True)
            scan = workspace / 'scan_out/demo/fix_lef/scan_1'
            (scan / 'summary').mkdir(parents=True)
            (scan / 'scan_meta.json').write_text(json.dumps({'scan_id': 'scan-web-p0', 'status': 'PASS'}))
            (scan / 'file_inventory.json').write_text(json.dumps({
                'files': [{'path': 'LEF/M.lef', 'file_type': 'lef', 'size_bytes': 12}],
                'file_type_counts': {'lef': 1},
            }))
            readiness = {'bundle_status': 'BLOCK', 'components': [{
                'required_views': ['lef', 'liberty', 'verilog'],
                'required_view_results': {
                    view: {'found': view == 'lef', 'status': 'PASS' if view == 'lef' else 'BLOCK'}
                    for view in ('lef', 'liberty', 'verilog')
                },
            }]}
            readiness_path = scan / 'summary/release_readiness.json'
            readiness_path.write_text(json.dumps(readiness))
            client = create_app(cwd=root, test_config={'TESTING': True}).test_client()
            self.assertEqual(client.post('/api/workspace/init', json={
                'workspace': str(workspace), 'raw_root': str(root / 'raw'),
            }).status_code, 200)
            catalog = workspace / 'catalog/catalog.json'
            catalog.parent.mkdir(parents=True, exist_ok=True)
            catalog.write_text(json.dumps({'libraries': [{'library_id': 'ip/demo', 'library_name': 'demo',
                'versions': [{'version_id': 'fix_lef', 'package_type': 'PARTIAL_UPDATE',
                              'raw_path': str(raw), 'scan': {'status': 'PASS', 'scan_dir': str(scan)}}]}]}))
            catalog_before = catalog.read_bytes()
            readiness_before = readiness_path.read_bytes()
            with patch('lib_guard.web.app.subprocess.Popen') as process:
                response = client.post('/api/libraries/demo/versions/fix_lef/refresh-reader-report')
                self.assertEqual(response.status_code, 200, response.get_json())
                versions = client.get('/api/libraries/demo/versions').get_json()['versions']
                self.assertTrue(versions[0]['version_detail_exists'], (response.get_json(), versions))
                self.assertEqual(versions[0]['change_summary'], '基准待确认')
                self.assertEqual(versions[0]['workflow_status']['label'], '组合基准待确认')
                page_response = client.get(versions[0]['version_detail_url'])
                self.assertEqual(page_response.status_code, 200)
                html = page_response.get_data(as_text=True)
                self.assertIn('本包未交付', html)
                self.assertNotIn('补齐前不可接入', html)
                page_response.close()
                process.assert_not_called()
            self.assertEqual(catalog.read_bytes(), catalog_before)
            self.assertEqual(readiness_path.read_bytes(), readiness_before)

    def test_reader_report_can_be_rebuilt_without_running_a_scan_or_check(self):
        from lib_guard.web.app import create_app
        with tempfile.TemporaryDirectory() as td, patch.dict('os.environ', {}, clear=True):
            root = Path(td)
            raw = root / 'raw/full'
            raw.mkdir(parents=True)
            workspace = root / 'workspace'
            client = create_app(cwd=root, test_config={'TESTING': True}).test_client()
            self.assertEqual(client.post('/api/workspace/init', json={
                'workspace': str(workspace), 'raw_root': str(root / 'raw'),
            }).status_code, 200)
            catalog = workspace / 'catalog/catalog.json'
            catalog.parent.mkdir(parents=True, exist_ok=True)
            catalog.write_text(json.dumps({'libraries': [{'library_id': 'demo', 'library_name': 'demo',
                'versions': [{'version_id': 'full', 'raw_path': str(raw)}]}]}))
            with patch('lib_guard.web.app.subprocess.Popen') as process:
                response = client.post('/api/libraries/demo/versions/full/refresh-reader-report')
                self.assertEqual(response.status_code, 200, response.get_json())
                page = Path(response.get_json()['render']['version_detail_html'])
                self.assertTrue(page.is_file())
                page.unlink()
                rebuilt = client.post('/api/libraries/demo/versions/full/refresh-reader-report')
                self.assertEqual(rebuilt.status_code, 200, rebuilt.get_json())
                self.assertTrue(page.is_file())
                process.assert_not_called()

    def test_candidate_plan_feedback_names_composition_without_claiming_accept_ready(self):
        from lib_guard.web.app import _job_result_summary
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root/'result.json').write_text(json.dumps({'cli_result': {'status': 'PASS', 'candidate_effective': {'effective_id': 'candidate_fix', 'base_full': 'full1', 'overlays': ['fix2', 'fix1']}, 'scan_versions': ['fix1']}}))
            summary = _job_result_summary(root)
            self.assertIn('full1', summary)
            self.assertIn('fix2 → fix1', summary)
            self.assertIn('需补扫 1', summary)
            self.assertNotIn('可确认', summary)

    def test_manual_effective_selection_reaches_existing_next_and_intake(self):
        from lib_guard.web.app import create_app
        with tempfile.TemporaryDirectory() as td:
            client = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={'TESTING': True, 'job_root': td}).test_client()
            for action in ['next', 'intake']:
                response = client.post(f'/api/libraries/{LIBRARY}/{action}', json={
                    'plan_only': True, 'base_full': '20260624_asap7', 'includes': ['20260627_asap7'],
                })
                self.assertEqual(response.status_code, 202)
                request = json.loads(Path(response.get_json()['request']).read_text())
                args = request['args']
                self.assertIn('--base-full', args)
                self.assertEqual(args[args.index('--base-full')+1], '20260624_asap7')
                self.assertEqual(args[args.index('--include')+1], '20260627_asap7')
            response = client.post(f'/api/libraries/{LIBRARY}/next', json={'base_full': '20260624_asap7', 'includes': 'not-a-list'})
            self.assertEqual(response.status_code, 400)

    def test_job_feedback_never_calls_failed_or_unverified_evidence_success(self):
        from lib_guard.web.app import _job_result_summary
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for result, expected in (
                ({'status': 'FAILED', 'scan_dir': '/scan', 'version': 'v2', 'scan_error': 'Permission denied'}, '扫描失败'),
                ({'status': 'FAILED', 'old_version': 'v1', 'new_version': 'v2'}, '版本对比失败'),
                ({'status': 'UNSUPPORTED', 'summary': {'file_type': 'db', 'changed': False}, 'pairwise_result': '/pair'}, '未完成'),
                ({'status': 'DONE', 'summary': {'file_type': 'db'}, 'pairwise_result': '/pair'}, '源文件内容未验证'),
                ({'status': 'SAME', 'summary': {'file_type': 'lef', 'status': 'SAME', 'changed': False}, 'pairwise_result': '/pair'}, '已提取字段无差异，源文件内容未验证'),
            ):
                (root / 'result.json').write_text(json.dumps({'cli_result': result}))
                summary = _job_result_summary(root)
                self.assertIn(expected, summary)
                if result['status'] == 'FAILED':
                    self.assertNotIn('完成', summary)

    def test_workspace_reopens_after_web_initialization_without_rescanning(self):
        from lib_guard.catalog.runtime import write_catalog_runtime
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td, patch.dict('os.environ', {}, clear=True):
            root = Path(td)
            raw = root / 'raw'
            raw.mkdir()
            workspace = root / 'data'
            client = create_app(cwd=root, test_config={'TESTING': True}).test_client()
            response = client.post('/api/workspace/init', json={'workspace': str(workspace), 'raw_root': str(raw)})
            self.assertEqual(response.status_code, 200)
            catalog = workspace / 'catalog/catalog.json'
            catalog.parent.mkdir(parents=True)
            catalog.write_text(json.dumps({'libraries': [{'library_name': 'A', 'library_id': 'ip/A', 'versions': [{'version_id': 'full'}]}]}))
            scan_dir = workspace / 'scan_out/A/full/scan_1'
            scan_dir.mkdir(parents=True)
            (scan_dir / 'scan_meta.json').write_text(json.dumps({'status': 'PASS'}))
            (scan_dir / 'file_inventory.json').write_text(json.dumps({'files': []}))
            runtime_path = write_catalog_runtime(catalog, {'ip/A/full': {'scan': {'status': 'PASS', 'scan_dir': str(scan_dir)}}})
            runtime_before = runtime_path.read_bytes()
            before = catalog.read_bytes()
            reopened = create_app(cwd=root, test_config={'TESTING': True}).test_client()
            with patch('lib_guard.web.app.subprocess.Popen') as process:
                payload = reopened.get('/api/workspace').get_json()
                self.assertFalse(payload['setup_required'])
                self.assertEqual(payload['paths']['workspace'], str(workspace))
                libraries = reopened.get('/api/libraries').get_json()
                self.assertEqual(libraries['libraries'][0]['library_name'], 'A')
                versions = reopened.get('/api/libraries/A/versions').get_json()
                self.assertEqual(versions['versions'][0]['scan_status'], 'PASS')
                self.assertEqual(versions['versions'][0]['scan_dir'], str(scan_dir))
                process.assert_not_called()
            self.assertEqual(catalog.read_bytes(), before)
            self.assertEqual(runtime_path.read_bytes(), runtime_before)

    def test_connecting_existing_workspace_does_not_reset_configuration(self):
        from lib_guard.short_cli_config import write_default_config
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td, patch.dict('os.environ', {}, clear=True):
            root = Path(td)
            raw = root / 'raw'
            raw.mkdir()
            workspace = root / 'data'
            config = write_default_config(workspace, raw_root=raw)
            config.write_text(config.read_text().replace('hash_policy: smart', 'hash_policy: full'))
            before = config.read_bytes()
            client = create_app(cwd=root, test_config={'TESTING': True}).test_client()
            response = client.post('/api/workspace/init', json={'workspace': str(workspace), 'raw_root': str(raw)})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(config.read_bytes(), before)

    def test_explicit_config_wins_over_previous_workspace(self):
        from lib_guard.short_cli_config import write_default_config
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td, patch.dict('os.environ', {}, clear=True):
            root = Path(td)
            saved = write_default_config(root / 'saved', raw_root=root)
            explicit = write_default_config(root / 'explicit', raw_root=root)
            (root / 'work').mkdir()
            (root / 'work/web_workspace.json').write_text(json.dumps({'config': str(saved)}))
            client = create_app(config_path=explicit, cwd=root, test_config={'TESTING': True}).test_client()
            self.assertEqual(client.get('/api/workspace').get_json()['paths']['workspace'], str(root / 'explicit'))
            missing = create_app(config_path=root / 'missing.yml', cwd=root, test_config={'TESTING': True}).test_client()
            self.assertTrue(missing.get('/api/workspace').get_json()['setup_required'])

    def test_missing_saved_workspace_is_not_recreated(self):
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td, patch.dict('os.environ', {}, clear=True):
            root = Path(td)
            missing = root / 'removed/lib_guard.yml'
            (root / 'work').mkdir()
            pointer = root / 'work/web_workspace.json'
            pointer.write_text(json.dumps({'config': str(missing)}))
            before = pointer.read_bytes()
            client = create_app(cwd=root, test_config={'TESTING': True}).test_client()
            payload = client.get('/api/workspace').get_json()
            self.assertTrue(payload['setup_required'])
            self.assertIn(str(missing), payload['error'])
            self.assertFalse(missing.parent.exists())
            self.assertEqual(pointer.read_bytes(), before)

    def test_multi_release_jobs_validate_stage_and_require_apply_confirmation(self):
        from lib_guard.web.app import create_app
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = root / 'lib_guard.yml'
            config.write_text(f'workspace: {root}\nraw_root: {root}/raw\nrelease_root: {root}/release\n')
            catalog = root / 'catalog/catalog.json'
            catalog.parent.mkdir()
            catalog.write_text(json.dumps({'libraries': [{'library_id': 'ip/A', 'library_name': 'A', 'versions': []}]}))
            app = create_app(config_path=config, cwd=ROOT, test_config={'TESTING': True})
            client = app.test_client()
            payload = {'libraries': ['A'], 'publish_name': 'lib_NL2.1.0', 'latest_name': 'latest'}
            self.assertEqual(client.post('/api/release-set/apply', json=payload).status_code, 400)
            self.assertEqual(client.post('/api/release-set/plan', json={**payload, 'publish_name':'../escape'}).status_code, 400)
            response = client.post('/api/release-set/plan', json=payload)
            self.assertEqual(response.status_code, 202, response.get_json())
            request = json.loads(Path(response.get_json()['request']).read_text())
            self.assertIn('lib_guard.release.set_publish', request['args'])
            task = json.loads(Path(request['args'][-1]).read_text())
            self.assertEqual(task['libraries'], ['ip/A'])
            self.assertFalse(task['apply'])
            response = client.post('/api/release-set/apply', json={**payload, 'acknowledged': True})
            self.assertEqual(response.status_code, 202)
            self.assertFalse((root / 'release').exists())

    def test_catalog_report_entry_is_available_only_when_html_exists(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / 'raw'
            raw.mkdir()
            html = root / 'catalog' / 'html'
            config = root / 'lib_guard.yml'
            config.write_text(f'workspace: {root}\nraw_root: {raw}\ncatalog_html: {html}\n', encoding='utf-8')
            client = create_app(config_path=config, cwd=ROOT, test_config={'TESTING': True}).test_client()
            report = client.get('/api/workspace').get_json()['catalog_report']
            self.assertFalse(report['available'])
            self.assertIsNone(report['url'])
            html.mkdir(parents=True)
            (html / 'index.html').write_text('<h1>Catalog smoke</h1>', encoding='utf-8')
            report = client.get('/api/workspace').get_json()['catalog_report']
            self.assertTrue(report['available'])
            self.assertEqual(report['path'], str(html / 'index.html'))
            with client.get(report['url']) as response:
                self.assertEqual(response.status_code, 200)

    def test_formal_release_refresh_accepts_an_initialized_empty_root(self) -> None:
        """An empty initialized release root is valid; it means no formal release yet."""
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "work"
            raw_root = root / "raw"
            release_root = workspace / "release_area"
            raw_root.mkdir(parents=True)
            release_root.mkdir(parents=True)
            config_path = workspace / "lib_guard.yml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                "\n".join(
                    [
                        f"workspace: {workspace}",
                        f"raw_root: {raw_root}",
                        f"catalog: {workspace / 'catalog' / 'catalog.json'}",
                        f"release_root: {release_root}",
                        f"release_library_index: {workspace / 'config' / 'release_libraries' / 'latest.json'}",
                    ]
                ) + "\n",
                encoding="utf-8",
            )
            app = create_app(config_path=config_path, cwd=ROOT, test_config={"TESTING": True})

            response = app.test_client().post("/api/release-libraries/refresh", json={})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["summary"]["library_count"], 0)

    def test_formal_release_library_routes_refresh_and_keep_raw_catalog_separate(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "work"
            release_root = root / "formal_release"
            release_dir = release_root / "ucie" / "releases" / "R1"
            release_dir.mkdir(parents=True)
            (release_dir / "release_manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": "release_manifest.v1",
                        "release_id": "R1",
                        "alias": "current",
                        "release_root": str(release_root / "ucie"),
                        "libraries": [{"library_type": "ip", "library_name": "ucie", "version_id": "v1"}],
                    }
                ),
                encoding="utf-8",
            )
            config_path = workspace / "lib_guard.yml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                "\n".join(
                    [
                        f"workspace: {workspace}",
                        f"raw_root: {root / 'raw'}",
                        f"catalog: {workspace / 'catalog' / 'catalog.json'}",
                        f"release_root: {release_root}",
                        f"release_library_index: {workspace / 'config' / 'release_libraries' / 'latest.json'}",
                    ]
                ) + "\n",
                encoding="utf-8",
            )
            app = create_app(config_path=config_path, cwd=ROOT, test_config={"TESTING": True})
            client = app.test_client()

            refresh = client.post("/api/release-libraries/refresh", json={"root": str(release_root)})
            listed = client.get("/api/release-libraries")

        self.assertEqual(refresh.status_code, 200)
        self.assertEqual(refresh.get_json()["summary"]["library_count"], 1)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.get_json()["libraries"][0]["library_id"], "ip/ucie")
        self.assertEqual(listed.get_json()["libraries"][0]["raw_catalog_match"], "")

    def _write_current_effective(
        self,
        catalog_html: Path,
        *,
        library: str,
        effective_id: str,
        digest_suffix: str,
    ) -> None:
        from lib_guard.effective.manifest import build_effective_manifest
        from lib_guard.effective.pointer import safe_name, write_current_pointer

        manifest_dir = catalog_html / "libraries" / safe_name(library) / "effective" / effective_id
        manifest_dir.mkdir(parents=True)
        catalog = {
            "libraries": [
                {
                    "library_id": library,
                    "library_name": library.split("/")[-1],
                    "versions": [
                        {
                            "version_id": "full",
                            "scan": {"snapshot_identity": {"digest": f"sha256:{digest_suffix}", "strength": "full"}},
                        }
                    ],
                }
            ]
        }
        manifest = build_effective_manifest(catalog, library, "full", [], effective_id=effective_id)
        manifest_path = manifest_dir / "effective_manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        write_current_pointer(manifest_path, accepted_by="owner", note="web test")

    def test_many_libraries_and_versions_stay_browseable_with_pagination(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "work"
            catalog_path = workspace / "catalog" / "catalog.json"
            catalog_path.parent.mkdir(parents=True)
            libraries = []
            for lib_index in range(4):
                versions = []
                for version_index in range(50):
                    version_id = f"202607{version_index + 1:02d}_lib{lib_index}_v{version_index + 1:02d}"
                    previous = f"202607{version_index:02d}_lib{lib_index}_v{version_index:02d}" if version_index else ""
                    versions.append(
                        {
                            "version_id": version_id,
                            "raw_path": str(root / "raw" / f"lib{lib_index}" / version_id),
                            "stage": "candidate" if version_index >= 45 else "stable",
                            "package_type": "PARTIAL_UPDATE" if version_index % 5 == 0 else "FULL_PACKAGE",
                            "current_effective": version_index == 44,
                            "scan": {"status": "NOT_SCANNED" if version_index >= 48 else "SCANNED"},
                            "diff": {
                                "adjacent_old_version": previous,
                                "adjacent_status": "PENDING" if version_index >= 45 else "DIFF_DONE",
                            },
                            "release": {"check_status": "RELEASE_BLOCKED" if version_index == 49 else "UNKNOWN"},
                        }
                    )
                libraries.append(
                    {
                        "library_name": f"Vendor_{lib_index}.demo_ip",
                        "library_id": f"ip/Vendor_{lib_index}.demo_ip",
                        "display_name": f"demo_ip_{lib_index}",
                        "vendor": f"Vendor_{lib_index}",
                        "report_slug": f"ip_Vendor_{lib_index}.demo_ip",
                        "summary": {"version_count": 50, "latest_version": versions[-1]["version_id"]},
                        "versions": versions,
                    }
                )
            catalog_path.write_text(json.dumps({"libraries": libraries}), encoding="utf-8")
            config_path = workspace / "lib_guard.yml"
            config_path.write_text(
                "\n".join(
                    [
                        f"workspace: {workspace}",
                        f"raw_root: {root / 'raw'}",
                        f"catalog: {catalog_path}",
                        f"catalog_html: {workspace / 'catalog' / 'html'}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            app = create_app(config_path=config_path, cwd=ROOT, test_config={"TESTING": True, "job_root": str(workspace / "jobs")})
            client = app.test_client()

            libraries_payload = client.get("/api/libraries").get_json()
            first_page = client.get("/api/libraries/Vendor_2.demo_ip/versions", query_string={"offset": 0, "limit": 25}).get_json()
            second_page = client.get("/api/libraries/Vendor_2.demo_ip/versions", query_string={"offset": 25, "limit": 25}).get_json()

        self.assertEqual(libraries_payload["status"], "PASS")
        self.assertEqual(len(libraries_payload["libraries"]), 4)
        self.assertEqual({row["version_count"] for row in libraries_payload["libraries"]}, {50})
        self.assertTrue(all(row["workflow_pending_count"] > 0 for row in libraries_payload["libraries"]))
        self.assertEqual(first_page["pagination"]["total"], 50)
        self.assertEqual(len(first_page["versions"]), 25)
        self.assertEqual(first_page["pagination"]["next_offset"], 25)
        self.assertEqual(len(second_page["versions"]), 25)
        self.assertIsNone(second_page["pagination"]["next_offset"])
        self.assertEqual(first_page["versions"][0]["version_id"], "20260750_lib2_v50")
        self.assertEqual(first_page["versions"][0]["release_status"], "RELEASE_BLOCKED")

    def test_file_change_rows_expose_old_and_new_paths_without_reading_raw(self) -> None:
        from lib_guard.web.read_model import list_file_diff_rows

        with tempfile.TemporaryDirectory() as td:
            diff_dir = Path(td) / "diff"
            diff_dir.mkdir()
            (diff_dir / "file_diff.json").write_text(
                json.dumps(
                    {
                        "added": ["new/gds/chip.gds"],
                        "removed": ["old/rtl/legacy.v"],
                        "changed": ["upstream/LEF/macro.lef"],
                        "renamed_or_moved": [{"old": "package/LEF/macro.lef", "new": "upstream/LEF/macro.lef"}],
                        "unverified": [{"old": "package/LIB/a.lib", "new": "upstream/LIB/a.lib"}],
                    }
                ),
                encoding="utf-8",
            )
            state = {
                "catalog": {
                    "libraries": [
                        {
                            "library_name": "demo",
                            "versions": [
                                {
                                    "version_id": "v2",
                                    "raw_path": str(Path(td) / "raw"),
                                    "diff": {"adjacent_diff_dir": str(diff_dir)},
                                }
                            ],
                        }
                    ]
                }
            }

            rows = list_file_diff_rows(state, "demo", "v2")

            self.assertEqual([row["change"] for row in rows], ["ADDED", "REMOVED", "CHANGED", "PATH_CHANGED", "PATH_CHANGED"])
            moved = next(row for row in rows if row["change"] == "PATH_CHANGED")
            self.assertEqual(moved["old_path"], "package/LEF/macro.lef")
            self.assertEqual(moved["new_path"], "upstream/LEF/macro.lef")
            self.assertTrue(moved["deep_diff_available"])
            self.assertFalse(next(row for row in rows if row["change"] == "ADDED")["deep_diff_available"])

    def test_file_change_page_filters_and_counts_existing_diff_evidence(self) -> None:
        """Large change sets must be filtered before they reach the browser."""

        from lib_guard.web.read_model import list_file_diff_page

        with tempfile.TemporaryDirectory() as td:
            diff_dir = Path(td) / "diff"
            diff_dir.mkdir()
            (diff_dir / "file_diff.json").write_text(
                json.dumps(
                    {
                        "added": ["new/lef/a.lef", "new/lef/b.lef", "new/gds/top.gds"],
                        "removed": ["old/rtl/legacy.v"],
                        "changed": ["new/rtl/top.v", "new/rtl/helper.v"],
                    }
                ),
                encoding="utf-8",
            )
            state = {
                "catalog": {
                    "libraries": [{"library_name": "demo", "versions": [{"version_id": "v2", "diff": {"adjacent_diff_dir": str(diff_dir)}}]}]
                }
            }

            page = list_file_diff_page(
                state,
                "demo",
                "v2",
                change="ADDED",
                file_type="lef",
                query="b.lef",
                offset=0,
                limit=1,
            )

        self.assertEqual(page["total"], 1)
        self.assertEqual(page["rows"][0]["new_path"], "new/lef/b.lef")
        self.assertEqual(page["next_offset"], None)
        self.assertEqual(page["counts"]["by_change"], {"ADDED": 3, "REMOVED": 1, "CHANGED": 2})
        self.assertEqual(page["counts"]["by_file_type"]["lef"], 2)

    def test_health_and_library_routes_are_read_only(self) -> None:
        from lib_guard.web.app import create_app

        app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True})
        client = app.test_client()

        self.assertEqual(client.get("/api/health").get_json()["status"], "PASS")
        response = client.get("/api/libraries")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["libraries"][0]["library_name"], LIBRARY)

    def test_loading_workbench_and_selecting_existing_read_routes_creates_no_job(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            job_root = Path(td) / "jobs"
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": str(job_root)})
            client = app.test_client()
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/api/libraries").status_code, 200)
            self.assertEqual(client.get(f"/api/libraries/{LIBRARY}/versions").status_code, 200)
            self.assertFalse(job_root.exists(), "Navigation and read-only library selection must not enqueue jobs")

    def test_unknown_library_is_rejected_before_job_creation(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post("/api/libraries/missing.library/versions/v1/scan")

            self.assertEqual(response.status_code, 404)
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_scan_creates_a_validated_job_request(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/scan",
                json={"parse_jobs": 1},
            )

            self.assertEqual(response.status_code, 202)
            payload = response.get_json()
            request_path = Path(payload["request"])
            request = json.loads(request_path.read_text(encoding="utf-8"))
            self.assertEqual(request["action"], "scan")
            self.assertEqual(request["library"], LIBRARY)
            self.assertEqual(request["version"], "20260627_asap7")
            self.assertNotIn("shell", request)
            self.assertIn("observability", request)
            self.assertIn("progress_roots", request["observability"])

    def test_workspace_route_exposes_read_only_paths_and_scan_defaults(self) -> None:
        from lib_guard.web.app import create_app

        app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True})
        payload = app.test_client().get("/api/workspace").get_json()

        self.assertEqual(payload["status"], "PASS")
        self.assertIn("catalog", payload["paths"])
        self.assertIn("hash_policy", payload["scan_strategy"])
        self.assertIn("web_actions", payload)
        self.assertEqual(payload["web_actions"]["scan"]["label"], "扫描")
        self.assertEqual(payload["web_actions"]["file-diff"]["cli_action"], "fd")
        self.assertTrue(payload["web_actions"]["library-add"]["requires_confirmation"])

    def test_workspace_route_guides_bootstrap_when_config_is_missing(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            missing_config = Path(td) / "workspace" / "lib_guard.yml"
            app = create_app(config_path=missing_config, cwd=ROOT, test_config={"TESTING": True})
            response = app.test_client().get("/api/workspace")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["status"], "NEEDS_INIT")
            self.assertTrue(payload["setup_required"])
            self.assertEqual(payload["catalog_state"], "CONFIG_MISSING")
            self.assertIn("初始化", payload["message"])
            self.assertIn("web_actions", payload)
            self.assertEqual(payload["web_actions"]["cmp"]["label"], "对比")

    def test_workspace_init_creates_config_and_activates_session(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            raw_root = Path(td) / "raw"
            raw_root.mkdir()
            workspace = Path(td) / "workspace"
            app = create_app(cwd=td, test_config={"TESTING": True, "job_root": str(workspace / "jobs")})
            client = app.test_client()

            init_response = client.post(
                "/api/workspace/init",
                json={"workspace": str(workspace), "raw_root": str(raw_root), "library_type": "ip"},
            )
            workspace_response = client.get("/api/workspace")

            self.assertEqual(init_response.status_code, 200)
            init_payload = init_response.get_json()
            self.assertEqual(init_payload["status"], "PASS")
            self.assertTrue((workspace / "lib_guard.yml").exists())
            self.assertEqual(Path(init_payload["paths"]["raw_root"]).resolve(), raw_root.resolve())
            self.assertEqual(workspace_response.status_code, 200)
            self.assertEqual(workspace_response.get_json()["catalog_state"], "NOT_INITIALIZED")

    def test_release_set_api_builds_manifest_from_selected_current_effectives(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "work"
            catalog_html = workspace / "catalog" / "html"
            catalog = workspace / "catalog" / "catalog.json"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(
                json.dumps(
                    {
                        "libraries": [
                            {"library_id": "ip/libA", "library_name": "libA", "versions": []},
                            {"library_id": "ip/libB", "library_name": "libB", "versions": []},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            config_path = workspace / "lib_guard.yml"
            config_path.write_text(
                f"workspace: {workspace}\nraw_root: {root / 'raw'}\ncatalog: {catalog}\ncatalog_html: {catalog_html}\n",
                encoding="utf-8",
            )
            self._write_current_effective(catalog_html, library="ip/libA", effective_id="E1", digest_suffix="a")
            self._write_current_effective(catalog_html, library="ip/libB", effective_id="E2", digest_suffix="b")
            app = create_app(config_path=config_path, cwd=ROOT, test_config={"TESTING": True})

            response = app.test_client().post("/api/release-set/build", json={"libraries": ["ip/libA", "ip/libB"], "set_id": "set_current"})
            payload = response.get_json()
            manifest_exists = Path(payload["manifest_path"]).is_file()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["manifest"]["summary"]["library_count"], 2)
        self.assertTrue(manifest_exists)
        self.assertEqual(payload["manifest"]["libraries"][0]["source"], "current_effective_pointer")

    def test_release_set_api_resolves_display_library_names_to_catalog_library_ids(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "work"
            catalog_html = workspace / "catalog" / "html"
            catalog = workspace / "catalog" / "catalog.json"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(
                json.dumps({"libraries": [{"library_id": "ip/libA", "library_name": "libA", "display_name": "Lib A", "versions": []}]}),
                encoding="utf-8",
            )
            config_path = workspace / "lib_guard.yml"
            config_path.write_text(
                f"workspace: {workspace}\nraw_root: {root / 'raw'}\ncatalog: {catalog}\ncatalog_html: {catalog_html}\n",
                encoding="utf-8",
            )
            self._write_current_effective(catalog_html, library="ip/libA", effective_id="E1", digest_suffix="a")
            app = create_app(config_path=config_path, cwd=ROOT, test_config={"TESTING": True})

            response = app.test_client().post("/api/release-set/build", json={"libraries": ["libA"], "set_id": "set_current"})
            payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["manifest"]["libraries"][0]["library_id"], "ip/libA")
        self.assertEqual(payload["manifest"]["summary"]["missing_current_effective"], 0)

    def test_release_set_api_compares_manifests_at_library_digest_level(self) -> None:
        from lib_guard.effective.release_set import build_release_set_manifest, write_release_set_manifest
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "work"
            catalog_html_old = workspace / "old_html"
            catalog_html_new = workspace / "catalog" / "html"
            catalog = workspace / "catalog" / "catalog.json"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(json.dumps({"libraries": [{"library_id": "ip/libA", "library_name": "libA", "versions": []}]}), encoding="utf-8")
            config_path = workspace / "lib_guard.yml"
            config_path.write_text(
                f"workspace: {workspace}\nraw_root: {root / 'raw'}\ncatalog: {catalog}\ncatalog_html: {catalog_html_new}\n",
                encoding="utf-8",
            )
            self._write_current_effective(catalog_html_old, library="ip/libA", effective_id="E1", digest_suffix="old")
            self._write_current_effective(catalog_html_new, library="ip/libA", effective_id="E2", digest_suffix="new")
            old_path = workspace / "release_sets" / "old" / "release_set_manifest.json"
            new_path = workspace / "release_sets" / "new" / "release_set_manifest.json"
            write_release_set_manifest(old_path, build_release_set_manifest(catalog_html_old, ["ip/libA"], set_id="old"))
            write_release_set_manifest(new_path, build_release_set_manifest(catalog_html_new, ["ip/libA"], set_id="new"))
            app = create_app(config_path=config_path, cwd=ROOT, test_config={"TESTING": True})

            response = app.test_client().post("/api/release-set/compare", json={"old_manifest": str(old_path), "new_manifest": str(new_path)})
            payload = response.get_json()
            compare_exists = Path(payload["compare_path"]).is_file()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["compare"]["summary"]["actions"], {"CHANGE_EFFECTIVE": 1})
        self.assertTrue(compare_exists)
        self.assertNotIn("changed_files", json.dumps(payload["compare"]))

    def test_path_children_defaults_to_configured_raw_root(self) -> None:
        from lib_guard.web.app import create_app

        app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True})
        response = app.test_client().get("/api/path-children")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        raw_root = Path(payload["roots"][0]).resolve()
        current = Path(payload["current_path"]).resolve()
        self.assertEqual(current, raw_root)
        self.assertTrue(payload["children"])
        self.assertTrue(all(item["path"].startswith(str(raw_root) + "/") for item in payload["children"]))

    def test_new_workspace_allows_path_browse_and_library_add_before_catalog_exists(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "workspace"
            raw_root = Path(td) / "raw"
            library_root = raw_root / "Vendor_A" / "demo"
            library_root.mkdir(parents=True)
            config_path = workspace / "lib_guard.yml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                "\n".join(
                    [
                        f"workspace: {workspace}",
                        f"raw_root: {raw_root}",
                        f"catalog: {workspace / 'catalog' / 'catalog.json'}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            app = create_app(
                config_path=config_path,
                cwd=ROOT,
                test_config={"TESTING": True, "job_root": str(workspace / "jobs")},
            )
            client = app.test_client()

            workspace_response = client.get("/api/workspace")
            browse_response = client.get("/api/path-children")
            add_response = client.post(
                "/api/library/add",
                json={"library_id": "Vendor_A.demo", "root": str(library_root), "apply": True, "refresh_catalog": True},
            )

            self.assertEqual(workspace_response.status_code, 200)
            self.assertEqual(workspace_response.get_json()["catalog_state"], "NOT_INITIALIZED")
            self.assertEqual(browse_response.status_code, 200)
            self.assertEqual(add_response.status_code, 202)

    def test_library_discover_accepts_explicit_discover_root(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "workspace"
            raw_root = Path(td) / "raw"
            discover_root = raw_root / "Vendor_A"
            discover_root.mkdir(parents=True)
            config_path = workspace / "lib_guard.yml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                "\n".join(
                    [
                        f"workspace: {workspace}",
                        f"raw_root: {raw_root}",
                        f"catalog: {workspace / 'catalog' / 'catalog.json'}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            app = create_app(
                config_path=config_path,
                cwd=ROOT,
                test_config={"TESTING": True, "job_root": str(workspace / "jobs")},
            )

            response = app.test_client().post(
                "/api/library/discover",
                json={"root": str(discover_root), "max_depth": 3, "min_versions": 1, "max_dirs": 99, "max_candidates": 7},
            )

            self.assertEqual(response.status_code, 202)
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))
            self.assertIn("library", request["args"])
            self.assertIn("discover", request["args"])
            self.assertIn("--root", request["args"])
            self.assertEqual(request["args"][request["args"].index("--root") + 1], str(discover_root.resolve()))
            self.assertIn("--min-versions", request["args"])
            self.assertEqual(request["args"][request["args"].index("--min-versions") + 1], "1")

    def test_library_discover_defaults_to_single_version_candidates_from_config(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "workspace"
            raw_root = Path(td) / "raw"
            raw_root.mkdir(parents=True)
            config_path = workspace / "lib_guard.yml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                "\n".join(
                    [
                        f"workspace: {workspace}",
                        f"raw_root: {raw_root}",
                        f"catalog: {workspace / 'catalog' / 'catalog.json'}",
                        "discover_min_versions: 1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            app = create_app(config_path=config_path, cwd=ROOT, test_config={"TESTING": True, "job_root": str(workspace / "jobs")})

            response = app.test_client().post("/api/library/discover", json={})

            self.assertEqual(response.status_code, 202)
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))
            self.assertEqual(request["args"][request["args"].index("--min-versions") + 1], "1")

    def test_workspace_config_update_saves_safe_defaults_and_keeps_backup(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "workspace"
            raw_root = Path(td) / "raw"
            release_root = Path(td) / "release"
            raw_root.mkdir(parents=True)
            release_root.mkdir()
            config_path = workspace / "lib_guard.yml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                "\n".join(
                    [
                        f"workspace: {workspace}",
                        f"raw_root: {raw_root}",
                        f"catalog: {workspace / 'catalog' / 'catalog.json'}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            app = create_app(config_path=config_path, cwd=ROOT, test_config={"TESTING": True, "job_root": str(workspace / "jobs")})

            response = app.test_client().post(
                "/api/workspace/config",
                json={
                    "raw_root": str(raw_root),
                    "release_root": str(release_root),
                    "hash_policy": "smart",
                    "parse_jobs": 4,
                    "force_hash_file_types": ["lef"],
                    "skip_hash_file_types": ["gds"],
                    "render_detail": True,
                    "discover_min_versions": 1,
                    "discover_max_depth": 3,
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["scan_strategy"]["parse_jobs"], "4")
            self.assertEqual(payload["scan_strategy"]["force_hash_file_types"], "lef")
            self.assertEqual(payload["discovery_strategy"]["min_versions"], "1")
            self.assertEqual(payload["discovery_strategy"]["max_depth"], "3")
            self.assertTrue(Path(payload["backup"]).is_file())
            text = config_path.read_text(encoding="utf-8")
            self.assertIn("discover_min_versions: 1", text)
            self.assertIn("parse_jobs: 4", text)
            self.assertIn(f"release_root: {release_root}", text)

    def test_workspace_config_update_rejects_unknown_fields(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "workspace"
            raw_root = Path(td) / "raw"
            raw_root.mkdir(parents=True)
            config_path = workspace / "lib_guard.yml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                "\n".join([f"workspace: {workspace}", f"raw_root: {raw_root}"]) + "\n",
                encoding="utf-8",
            )
            app = create_app(config_path=config_path, cwd=ROOT, test_config={"TESTING": True})

            response = app.test_client().post("/api/workspace/config", json={"shell": "rm -rf /", "raw_root": str(raw_root)})

            self.assertEqual(response.status_code, 400)
            self.assertIn("不支持", response.get_json()["error"])
            self.assertNotIn("shell", config_path.read_text(encoding="utf-8"))

    def test_library_accept_only_registers_checked_candidate_rows(self) -> None:
        from lib_guard.library_registry import write_library_rows
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "workspace"
            raw_root = root / "raw"
            candidate_a = raw_root / "Vendor_A" / "alpha"
            candidate_b = raw_root / "Vendor_B" / "beta"
            candidate_a.mkdir(parents=True)
            candidate_b.mkdir(parents=True)
            candidates_path = workspace / "config" / "library_candidates" / "latest.tsv"
            registry_path = workspace / "config" / "library_registry.tsv"
            write_library_rows(candidates_path, [
                {"status": "REVIEW", "library_id": "Vendor_A.alpha", "root_abs": str(candidate_a), "display_name": "alpha", "vendor": "Vendor_A", "middle_path": ""},
                {"status": "REVIEW", "library_id": "Vendor_B.beta", "root_abs": str(candidate_b), "display_name": "beta", "vendor": "Vendor_B", "middle_path": ""},
            ])
            config_path = workspace / "lib_guard.yml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                "\n".join([
                    f"workspace: {workspace}",
                    f"raw_root: {raw_root}",
                    f"catalog: {workspace / 'catalog' / 'catalog.json'}",
                    f"library_candidates: {candidates_path}",
                    f"library_registry: {registry_path}",
                ]) + "\n",
                encoding="utf-8",
            )
            jobs = workspace / "jobs"
            app = create_app(config_path=config_path, cwd=ROOT, test_config={"TESTING": True, "job_root": str(jobs)})
            client = app.test_client()

            snapshot = client.get("/api/library-candidates")
            self.assertEqual(snapshot.status_code, 200)
            selected_id = snapshot.get_json()["candidates"][0]["candidate_id"]
            response = client.post("/api/library/accept", json={"candidate_ids": [selected_id]})

            self.assertEqual(response.status_code, 202)
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))
            self.assertIn("--input", request["args"])
            selected_input = Path(request["args"][request["args"].index("--input") + 1])
            selected_text = selected_input.read_text(encoding="utf-8")
            self.assertIn("Vendor_A.alpha", selected_text)
            self.assertNotIn("Vendor_B.beta", selected_text)
            self.assertEqual(request["candidate_selection"]["count"], 1)

    def test_path_children_rejects_path_outside_allowed_roots(self) -> None:
        from lib_guard.web.app import create_app

        app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True})
        response = app.test_client().get("/api/path-children", query_string={"path": "/etc"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("允许范围", response.get_json()["error"])

    def test_path_children_does_not_follow_symlink_outside_allowed_roots(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            raw_root = Path(td) / "raw"
            workspace = Path(td) / "workspace"
            raw_root.mkdir()
            workspace.mkdir()
            outside = Path(td) / "outside"
            outside.mkdir()
            (raw_root / "escape").symlink_to(outside, target_is_directory=True)
            catalog_path = workspace / "catalog" / "catalog.json"
            catalog_path.parent.mkdir(parents=True)
            catalog_path.write_text(json.dumps({"libraries": []}), encoding="utf-8")
            config_path = workspace / "lib_guard.yml"
            config_path.write_text(
                "\n".join(
                    [
                        f"workspace: {workspace}",
                        f"raw_root: {raw_root}",
                        f"catalog: {catalog_path}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            app = create_app(config_path=config_path, cwd=ROOT, test_config={"TESTING": True})

            response = app.test_client().get("/api/path-children")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["children"], [])

    def test_scan_request_accepts_explicit_strategy_settings(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/scan",
                json={
                    "hash_policy": "smart",
                    "force_hash_file_types": ["lef", "liberty"],
                    "skip_hash_file_types": ["gds"],
                    "parse_jobs": 4,
                    "parse_file_types": "lef,cdl",
                    "parse_exclude_file_types": "verilog,liberty",
                    "no_render": True,
                },
            )
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))

            self.assertIn("--hash-policy", request["args"])
            self.assertIn("--parse-file-types", request["args"])
            self.assertIn("--force-hash-file-types", request["args"])
            self.assertIn("lef,liberty", request["args"])
            self.assertIn("--skip-hash-file-types", request["args"])
            self.assertIn("--no-render", request["args"])

    def test_boolean_strategy_values_must_be_json_booleans(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/scan",
                json={"no_render": "false"},
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("布尔", response.get_json()["error"])
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_non_object_json_is_rejected_without_creating_a_job(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/scan",
                json=["not", "an", "object"],
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("JSON 对象", response.get_json()["error"])
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_malformed_json_is_rejected_without_creating_a_job(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/scan",
                data="{",
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("格式无效", response.get_json()["error"])
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_non_json_body_is_rejected_without_creating_a_job(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/scan",
                data="scan",
                content_type="text/plain",
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("JSON 对象", response.get_json()["error"])
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_compare_request_accepts_base_and_scan_policy(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/compare",
                json={"base": "20260624_asap7", "mode": "adjacent", "scan_if_missing": True, "rescan": False},
            )
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))

            self.assertIn("--base", request["args"])
            self.assertIn("--scan-if-missing", request["args"])

    def test_non_scan_job_does_not_reuse_scan_progress(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/release-check",
                json={},
            )

            self.assertEqual(response.status_code, 202)
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))
            self.assertEqual(request["observability"]["progress_roots"], [])

    def test_release_plan_uses_cli_dry_run_without_apply_or_force(self) -> None:
        """Preview remains non-mutating even when actual publication is available."""

        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/release-plan",
                json={"alias": "stage", "link_mode": "copy", "overwrite": True},
            )

            self.assertEqual(response.status_code, 202)
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))
            self.assertEqual(request["action"], "release-plan")
            self.assertIn("rel", request["args"])
            self.assertIn("--alias", request["args"])
            self.assertIn("stage", request["args"])
            self.assertIn("--link-mode", request["args"])
            self.assertIn("copy", request["args"])
            self.assertIn("--overwrite", request["args"])
            self.assertNotIn("--apply", request["args"])
            self.assertNotIn("--force", request["args"])
            self.assertNotIn("--force-reason", request["args"])
            self.assertNotIn("--no-verify", request["args"])

    def test_release_apply_requires_confirmation_and_keeps_verification(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            client = app.test_client()
            url = f"/api/libraries/{LIBRARY}/versions/20260627_asap7/release-apply"
            self.assertEqual(client.post(url, json={}).status_code, 400)
            self.assertEqual(client.post(url, json={"acknowledged": True, "force": True}).status_code, 400)
            response = client.post(url, json={"acknowledged": True, "alias": "stage"})
            self.assertEqual(response.status_code, 202)
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))
            self.assertEqual(request["action"], "release-apply")
            self.assertIn("--apply", request["args"])
            self.assertIn("stage", request["args"])
            self.assertNotIn("--force", request["args"])
            self.assertNotIn("--no-verify", request["args"])

    def test_actual_release_projection_preserves_cli_verification_and_links(self) -> None:
        from lib_guard.web.app import _release_plan_projection

        projection = _release_plan_projection(
            {"dry_run": False, "verify_status": "PASS", "link_result": {
                "status": "APPLIED", "release_dir": "/release/releases/R1",
                "target_alias": "/release/current", "summary": {"planned_files": 1, "failed_files": 0},
                "created_links": [{"relative_path": "LEF/top.lef", "status": "LINKED"}],
            }},
            {"action": "release-apply", "library": LIBRARY, "version": "20260627_asap7"},
        )
        self.assertFalse(projection["dry_run"])
        self.assertEqual(projection["status"], "APPLIED")
        self.assertEqual(projection["verify_status"], "PASS")
        self.assertEqual(projection["planned_files"], 1)
        self.assertEqual(projection["link_rows"][0]["status"], "LINKED")

    def test_named_release_defaults_can_be_saved_and_read_back(self) -> None:
        from lib_guard.web.app import create_app
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "lib_guard.yml"
            config.write_text(SMOKE_CONFIG.read_text())
            app = create_app(config_path=config, cwd=ROOT, test_config={"TESTING": True, "job_root": str(Path(td) / "jobs")})
            client = app.test_client()
            response = client.post("/api/workspace/config", json={"release_publish_name": "lib_NL7", "release_latest_name": "latest_NL7"})
            self.assertEqual(response.status_code, 200)
            expected = {"publish_name": "lib_NL7", "latest_name": "latest_NL7"}
            self.assertEqual(response.get_json()["release_settings"], expected)
            self.assertEqual(client.get("/api/workspace").get_json()["release_settings"], expected)
            self.assertEqual(client.post("/api/workspace/config", json={"release_publish_name": "../escape"}).status_code, 400)

    def test_release_pyramid_keeps_missing_counts_and_source_evidence(self) -> None:
        from lib_guard.web.app import _release_plan_projection
        projected = _release_plan_projection({
            "dry_run": False, "verify_status": "FAILED", "link_result": {
                "status": "FAILED", "created_links": [{"status": "LINKED", "link_action": "REPLACE", "library_name": "A", "version_id": "v2", "previous_target": "/old/a"}],
                "verify": {"issues": [{"message": "target mismatch", "file": "LEF/a.lef"}]},
            }, "verify_issues": [{"message": "target mismatch", "file": "LEF/a.lef"}],
        }, {"action": "release-apply"})
        self.assertIsNone(projected["planned_files"])
        self.assertEqual(projected["status"], "FAILED")
        self.assertEqual(len(projected["issues"]), 1)
        self.assertEqual(projected["link_rows"][0]["library_name"], "A")
        self.assertEqual(projected["link_rows"][0]["link_action"], "REPLACE")

    def test_job_summary_distinguishes_release_check_from_publication(self) -> None:
        from lib_guard.web.app import _job_result_summary
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = {"release_check_status": "PASS", "link_result": {"status": "FAILED"}}
            (root / "result.json").write_text(json.dumps({"cli_result": result}))
            self.assertIn("发布未完成", _job_result_summary(root))
            result.update({"verify_status": "PASS", "link_result": {"status": "APPLIED", "summary": {"planned_files": 205}}})
            (root / "result.json").write_text(json.dumps({"cli_result": result}))
            self.assertIn("已执行发布", _job_result_summary(root))
            self.assertIn("205", _job_result_summary(root))

    def test_formal_release_overwrite_preview_is_dry_run_only(self) -> None:
        """A formal release target may only create a validated overwrite preview."""

        from lib_guard.web.app import create_app

        formal_row = {
            "library_id": "ip/formal_ucie",
            "current_release": "R20260921",
            "current_version": "20260627_asap7",
            "source": "release_manifest",
            "raw_catalog_match": f"ip/{LIBRARY}",
            "raw_catalog_name": LIBRARY,
            "history": [],
        }
        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            client = app.test_client()
            with patch("lib_guard.web.app.list_release_library_rows", return_value={"status": "READY", "libraries": [formal_row]}):
                blocked_responses = [
                    client.post(
                        "/api/release-libraries/ip/formal_ucie/versions/20260627_asap7/preview-overwrite",
                        json={key: value},
                    )
                    for key, value in (("apply", True), ("force", True), ("force_reason", "manual"), ("no_verify", True))
                ]
                response = client.post(
                    "/api/release-libraries/ip/formal_ucie/versions/20260627_asap7/preview-overwrite",
                    json={"alias": "stage", "link_mode": "copy"},
                )

            for blocked in blocked_responses:
                self.assertEqual(blocked.status_code, 400)
                self.assertIn("不允许", blocked.get_json()["error"])
            self.assertEqual(response.status_code, 202)
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))

        self.assertEqual(request["action"], "release-overwrite-preview")
        self.assertEqual(request["library"], f"ip/{LIBRARY}")
        self.assertEqual(request["formal_release_target"]["library_id"], "ip/formal_ucie")
        self.assertIn("rel", request["args"])
        self.assertIn("--overwrite", request["args"])
        self.assertNotIn("--apply", request["args"])
        self.assertNotIn("--force", request["args"])
        self.assertNotIn("--force-reason", request["args"])
        self.assertNotIn("--no-verify", request["args"])

    def test_formal_release_force_requires_audited_confirmation(self) -> None:
        """The Web force path is explicit, audited, and cannot skip verification."""

        from lib_guard.web.app import create_app

        formal_row = {
            "library_id": "ip/formal_ucie",
            "current_release": "R20260921",
            "current_version": "20260627_asap7",
            "source": "release_manifest",
            "raw_catalog_match": f"ip/{LIBRARY}",
            "raw_catalog_name": LIBRARY,
            "history": [],
        }
        endpoint = "/api/release-libraries/ip/formal_ucie/versions/20260627_asap7/force-overwrite"
        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            client = app.test_client()
            with patch("lib_guard.web.app.list_release_library_rows", return_value={"status": "READY", "libraries": [formal_row]}):
                for payload in (
                    {"force_by": "owner", "acknowledged": True},
                    {"force_reason": "紧急修复已人工确认", "acknowledged": True},
                    {"force_reason": "紧急修复已人工确认", "force_by": "owner"},
                    {"force_reason": "紧急修复已人工确认", "force_by": "owner", "acknowledged": True, "no_verify": True},
                ):
                    response = client.post(endpoint, json=payload)
                    self.assertEqual(response.status_code, 400)

                response = client.post(
                    endpoint,
                    json={
                        "alias": "current",
                        "link_mode": "symlink",
                        "force_reason": "紧急修复已人工确认",
                        "force_by": "release_owner",
                        "acknowledged": True,
                    },
                )
                request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))

        self.assertEqual(response.status_code, 202)
        self.assertEqual(request["action"], "release-force")
        self.assertEqual(request["formal_release_target"]["library_id"], "ip/formal_ucie")
        self.assertIn("--apply", request["args"])
        self.assertIn("--force", request["args"])
        self.assertIn("--overwrite", request["args"])
        self.assertIn("--force-reason", request["args"])
        self.assertIn("紧急修复已人工确认", request["args"])
        self.assertIn("--force-by", request["args"])
        self.assertIn("release_owner", request["args"])
        self.assertIn("--no-render", request["args"])
        self.assertNotIn("--no-verify", request["args"])

    def test_completed_release_plan_exposes_compact_configuration_and_manifest(self) -> None:
        from lib_guard.web.app import _job_status

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = root / "release_manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            (root / "status.json").write_text(
                json.dumps({"status": "COMPLETED", "return_code": 0}),
                encoding="utf-8",
            )
            (root / "request.json").write_text(
                json.dumps(
                    {
                        "library": LIBRARY,
                        "version": "20260627_asap7",
                        "args": ["python", "-m", "lib_guard.short_cli", "rel", LIBRARY, "20260627_asap7", "--overwrite", "--no-render"],
                        "formal_release_target": {"library_id": "ip/formal_ucie", "release_id": "R20260921"},
                    }
                ),
                encoding="utf-8",
            )
            (root / "result.json").write_text(
                json.dumps(
                    {
                        "schema_version": "web_job_result.v1",
                        "result": "ok",
                        "exit_code": 0,
                        "cli_result": {
                            "status": "PASS",
                            "dry_run": True,
                            "link_status": "DRY_RUN",
                            "release_root": "/release_area",
                            "alias": "stage",
                            "overwrite": False,
                            "manifest": str(manifest),
                            "link_result": {
                                "mode": "symlink", "summary": {"planned_files": 12},
                                "created_links": [{"relative_path": "LEF/top.lef", "status": "WOULD_REPLACE",
                                                   "previous_target": "/raw/old/top.lef", "target_path": "/raw/new/top.lef"}],
                                "failed_links": [{"relative_path": "GDS/missing.gds", "status": "FAILED", "error": "source missing"}],
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            status = _job_status(root, None)

            self.assertEqual(status["release_plan"]["status"], "DRY_RUN")
            self.assertEqual(status["release_plan"]["alias"], "stage")
            self.assertEqual(status["release_plan"]["link_mode"], "symlink")
            self.assertEqual(status["release_plan"]["planned_files"], 12)
            self.assertEqual(status["release_plan"]["link_rows"][0]["previous_target"], "/raw/old/top.lef")
            self.assertEqual(status["release_plan"]["link_rows"][1]["error"], "source missing")
            self.assertEqual(status["release_plan"]["formal_release_target"]["library_id"], "ip/formal_ucie")
            self.assertTrue(any(item["id"] == "release_manifest" for item in status["artifacts"]))

    def test_compare_without_rescan_does_not_reuse_scan_progress(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/compare",
                json={"base": "20260624_asap7", "mode": "adjacent", "scan_if_missing": False, "rescan": False},
            )

            self.assertEqual(response.status_code, 202)
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))
            self.assertEqual(request["observability"]["progress_roots"], [])

    def test_compare_rescan_observes_the_new_scan_progress_roots(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/compare",
                json={"base": "20260624_asap7", "rescan": True},
            )

            self.assertEqual(response.status_code, 202)
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))
            self.assertTrue(request["observability"]["progress_roots"])

    def test_compare_rejects_base_from_another_library_before_job_creation(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/compare",
                json={"base": "not_in_this_catalog"},
            )

            self.assertEqual(response.status_code, 409)
            self.assertIn("不属于当前库", response.get_json()["error"])
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_compare_without_catalog_base_is_rejected_before_job_creation(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260624_asap7/compare",
                json={},
            )

            self.assertEqual(response.status_code, 409)
            self.assertIn("对比基准", response.get_json()["error"])
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_accept_window_without_candidate_is_rejected_before_job_creation(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/accept-window",
                json={"accepted_by": "owner"},
            )

            self.assertEqual(response.status_code, 409)
            self.assertIn("可确认的新版本", response.get_json()["error"])
            self.assertIn("处理建议", response.get_json()["error"])
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_window_actions_are_allowlisted_and_do_not_accept_arbitrary_commands(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            client = app.test_client()
            next_response = client.post(f"/api/libraries/{LIBRARY}/next", json={"plan_only": True})
            intake_response = client.post(f"/api/libraries/{LIBRARY}/intake", json={"plan_only": True})

            next_request = json.loads(Path(next_response.get_json()["request"]).read_text(encoding="utf-8"))
            intake_request = json.loads(Path(intake_response.get_json()["request"]).read_text(encoding="utf-8"))
            self.assertEqual(next_request["args"][-2:], [LIBRARY, "--plan-only"])
            self.assertIn("intake", intake_request["args"])
            self.assertNotIn("shell", next_request)

    def test_mark_and_override_requests_validate_allowed_values(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            client = app.test_client()
            marked = client.post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/mark",
                json={"type": "FULL", "note": "manual confirmed"},
            )
            overridden = client.post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/override",
                json={"package_type": "FULL_PACKAGE", "compare_default": "previous_effective", "note": "confirmed"},
            )

            mark_request = json.loads(Path(marked.get_json()["request"]).read_text(encoding="utf-8"))
            override_request = json.loads(Path(overridden.get_json()["request"]).read_text(encoding="utf-8"))
            self.assertIn("--type", mark_request["args"])
            self.assertIn("library", override_request["args"])

            rejected = client.post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/mark",
                json={"type": "rm -rf /"},
            )
            self.assertEqual(rejected.status_code, 400)
            self.assertEqual(len(list(Path(td).iterdir())), 2)

    def test_unmanaged_job_is_not_reported_as_still_running_after_restart(self) -> None:
        from lib_guard.web.app import _job_status

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "status.json").write_text(json.dumps({"status": "RUNNING"}), encoding="utf-8")

            status = _job_status(root, None)

            self.assertEqual(status["status"], "FAILED")
            self.assertIn("未记录最终返回码", status["message"])

    def test_unmanaged_job_with_missing_or_invalid_status_is_terminal_failed(self) -> None:
        from lib_guard.web.app import _job_status

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            status = _job_status(root, None)
            self.assertEqual(status["status"], "FAILED")
            self.assertIn("状态文件", status["message"])

    def test_run_status_exposes_terminal_tail_and_scan_progress(self) -> None:
        from lib_guard.web.app import _job_status

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "job"
            progress = Path(td) / "scan" / "logs" / "scan_progress_latest.json"
            root.mkdir()
            progress.parent.mkdir(parents=True)
            (root / "status.json").write_text(
                json.dumps({"status": "COMPLETED", "started_epoch": 100.0, "finished_epoch": 112.5}),
                encoding="utf-8",
            )
            (root / "request.json").write_text(
                json.dumps({"observability": {"progress_paths": [str(progress)]}}),
                encoding="utf-8",
            )
            (root / "stdout.log").write_text("1/7 walk 4/4 100%\nscan finished\n", encoding="utf-8")
            progress.write_text(
                json.dumps({
                    "event": "step",
                    "stage": "4/7 parse",
                    "message": "parser task finished",
                    "done": 8,
                    "total": 10,
                    "percent": 80.0,
                    "performance": {"total_seconds": 12.5},
                }),
                encoding="utf-8",
            )

            status = _job_status(root, None)

            self.assertIn("scan finished", status["log_tail"])
            self.assertEqual(status["elapsed_seconds"], 12.5)
            self.assertEqual(status["progress"]["stage"], "4/7 parse")
            self.assertEqual(status["progress"]["percent"], 80.0)

            (root / "status.json").write_text(json.dumps({"status": "BOGUS"}), encoding="utf-8")
            status = _job_status(root, None)
            self.assertEqual(status["status"], "FAILED")
            self.assertIn("未知", status["message"])

            (root / "status.json").write_text("{", encoding="utf-8")
            status = _job_status(root, None)
            self.assertEqual(status["status"], "FAILED")
            self.assertIn("状态文件", status["message"])

    def test_queued_job_does_not_report_progress_left_by_an_earlier_scan(self) -> None:
        from lib_guard.web.app import _job_status

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "job"
            progress = Path(td) / "scan" / "logs" / "scan_progress_latest.json"
            root.mkdir()
            progress.parent.mkdir(parents=True)
            progress.write_text(
                json.dumps({"stage": "finish", "message": "previous scan finished", "percent": 100}),
                encoding="utf-8",
            )
            (root / "status.json").write_text(
                json.dumps({"status": "QUEUED", "created_epoch": 1_700_000_000.0}),
                encoding="utf-8",
            )
            (root / "request.json").write_text(
                json.dumps({"observability": {"progress_roots": [str(progress)]}}),
                encoding="utf-8",
            )

            status = _job_status(root, None, managed=True)

            self.assertEqual(status["progress"]["event"], "waiting")
            self.assertNotIn("previous scan finished", status["progress"].get("message", ""))

    def test_running_job_ignores_progress_file_older_than_its_start_time(self) -> None:
        from lib_guard.web.app import _job_status

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "job"
            progress = Path(td) / "scan" / "logs" / "scan_progress_latest.json"
            root.mkdir()
            progress.parent.mkdir(parents=True)
            progress.write_text(
                json.dumps({"stage": "finish", "message": "stale progress", "percent": 100}),
                encoding="utf-8",
            )
            (root / "status.json").write_text(
                json.dumps({"status": "RUNNING", "started_epoch": 4_000_000_000.0}),
                encoding="utf-8",
            )
            (root / "request.json").write_text(
                json.dumps({"observability": {"progress_roots": [str(progress)]}}),
                encoding="utf-8",
            )

            status = _job_status(root, None, managed=True)

            self.assertEqual(status["progress"]["event"], "waiting")
            self.assertNotIn("stale progress", status["progress"].get("message", ""))

    def test_failed_release_job_exposes_a_short_failure_summary(self) -> None:
        from lib_guard.web.app import _job_status

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "status.json").write_text(
                json.dumps({"status": "FAILED", "return_code": 2, "started_epoch": 100.0, "finished_epoch": 101.0}),
                encoding="utf-8",
            )
            (root / "stdout.log").write_text(
                json.dumps(
                    {
                        "release_check_status": "BLOCK",
                        "block_reasons": ["审查门禁未关闭", "当前有效版对比未完成"],
                        "issues": [{"severity": "blocker", "title": "审查门禁未关闭"}],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            status = _job_status(root, None)

            self.assertIn("发布检查被阻塞", status["error"])
            self.assertIn("审查门禁未关闭", status["error"])
            self.assertLessEqual(len(status["error"]), 240)

    def test_completed_job_exposes_a_bounded_operator_summary(self) -> None:
        from lib_guard.web.app import _job_result_summary, _job_status

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "status.json").write_text(
                json.dumps({"status": "COMPLETED", "return_code": 0}),
                encoding="utf-8",
            )
            (root / "result.json").write_text(
                json.dumps(
                    {
                        "schema_version": "web_job_result.v1",
                        "result": "ok",
                        "exit_code": 0,
                        "cli_result": {
                            "release_check_status": "PASS_WITH_WARNING",
                            "version": "v2",
                            "block_reasons": [],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            status = _job_status(root, None)

            self.assertEqual(status["result_summary"], "发布检查通过（有提醒） · v2")
            self.assertLessEqual(len(status["result_summary"]), 240)

            (root / "result.json").write_text(
                json.dumps(
                    {
                        "cli_result": {
                            "status": "DIFF",
                            "summary": {"file_type": "lef", "changed": True},
                            "pairwise_result": str(root / "pairwise_result.json"),
                        }
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(_job_result_summary(root), "深度核对完成 · LEF · 旧报告有变化，源文件内容未验证")

    def test_arbitrary_action_route_does_not_exist(self) -> None:
        from lib_guard.web.app import create_app

        app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True})

        response = app.test_client().post("/api/run-shell", json={"command": "rm -rf /"})

        self.assertEqual(response.status_code, 404)

    def test_catalog_refresh_and_worklist_routes_expand_to_short_commands(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            client = app.test_client()

            catalog = client.post(
                f"/api/libraries/{LIBRARY}/catalog",
                json={"refresh": True, "with_evidence": False, "full": True},
            )
            worklist = client.post("/api/worklist", json={})

            self.assertEqual(catalog.status_code, 202)
            self.assertEqual(worklist.status_code, 202)
            catalog_request = json.loads(Path(catalog.get_json()["request"]).read_text(encoding="utf-8"))
            worklist_request = json.loads(Path(worklist.get_json()["request"]).read_text(encoding="utf-8"))
            self.assertEqual(catalog_request["args"][catalog_request["args"].index("cat") : catalog_request["args"].index("cat") + 2], ["cat", LIBRARY])
            self.assertIn("--refresh-catalog", catalog_request["args"])
            self.assertIn("--full", catalog_request["args"])
            self.assertIn("worklist", worklist_request["args"])

    def test_file_diff_route_uses_catalog_relative_inputs_and_rejects_traversal(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            client = app.test_client()
            response = client.post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/file-diff",
                json={"base": "20260624_asap7", "relpath": "lef/asap7.lef", "type": "lef"},
            )
            rejected = client.post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/file-diff",
                json={"base": "20260624_asap7", "relpath": "../outside.lef", "type": "lef"},
            )

            self.assertEqual(response.status_code, 202)
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))
            start = request["args"].index("fd")
            self.assertEqual(request["args"][start : start + 4], ["fd", LIBRARY, "20260627_asap7", "lef/asap7.lef"])
            self.assertIn("--base", request["args"])
            self.assertNotIn("--force-large", request["args"])
            self.assertEqual(rejected.status_code, 400)
            self.assertIn("相对路径", rejected.get_json()["error"])

    def test_file_diff_route_accepts_linked_old_and_new_paths(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/file-diff",
                json={
                    "base": "20260624_asap7",
                    "old_relpath": "asap7_source_package/lef/asap7_tech_1x_201209.lef",
                    "relpath": "upstream_ae9a8ed9/lef/asap7_tech_1x_201209.lef",
                    "type": "lef",
                },
            )

            self.assertEqual(response.status_code, 202)
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))
            start = request["args"].index("fd")
            self.assertEqual(request["args"][start : start + 2], ["fd", "--old"])
            old_path = ROOT / "tests" / "fixtures" / "raw" / "vendor_A" / "openroad_asap7" / "20260624_asap7" / "asap7_source_package" / "lef" / "asap7_tech_1x_201209.lef"
            new_path = ROOT / "tests" / "fixtures" / "raw" / "vendor_A" / "openroad_asap7" / "20260627_asap7" / "upstream_ae9a8ed9" / "lef" / "asap7_tech_1x_201209.lef"
            self.assertIn(str(old_path), request["args"])
            self.assertIn(str(new_path), request["args"])

    def test_file_diff_route_rejects_large_linked_type_without_explicit_opt_in(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/file-diff",
                json={
                    "base": "20260624_asap7",
                    "old_relpath": "asap7_source_package/lib/CCS/asap7sc7p5t_SEQ_RVT_FF_ccs_220123.lib",
                    "relpath": "upstream_ae9a8ed9/lib/CCS/asap7sc7p5t_SEQ_RVT_FF_ccs_220123.lib",
                    "type": "liberty",
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("force-large", response.get_json()["error"])
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_file_diff_route_allows_large_linked_type_only_with_opt_in(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/file-diff",
                json={
                    "base": "20260624_asap7",
                    "old_relpath": "asap7_source_package/lib/CCS/asap7sc7p5t_SEQ_RVT_FF_ccs_220123.lib",
                    "relpath": "upstream_ae9a8ed9/lib/CCS/asap7sc7p5t_SEQ_RVT_FF_ccs_220123.lib",
                    "type": "liberty",
                    "force_large": True,
                },
            )

            self.assertEqual(response.status_code, 202)
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))
            self.assertIn("--old", request["args"])
            self.assertIn("--new", request["args"])
            self.assertIn("--force-large", request["args"])

    def test_file_diff_route_accepts_explicit_files_inside_allowed_roots(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "workspace"
            raw_root = Path(td) / "raw"
            old = raw_root / "manual" / "old.lef"
            new = raw_root / "manual" / "new.lef"
            old.parent.mkdir(parents=True)
            old.write_text("VERSION 5.8 ;\nMACRO A\nEND A\n", encoding="utf-8")
            new.write_text("VERSION 5.8 ;\nMACRO B\nEND B\n", encoding="utf-8")
            config_path = workspace / "lib_guard.yml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                "\n".join(
                    [
                        f"workspace: {workspace}",
                        f"raw_root: {raw_root}",
                        f"catalog: {SMOKE_CONFIG.parent / 'catalog' / 'catalog.json'}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            app = create_app(config_path=config_path, cwd=ROOT, test_config={"TESTING": True, "job_root": str(workspace / "jobs")})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/file-diff",
                json={"old_file": str(old), "new_file": str(new), "type": "lef"},
            )

            self.assertEqual(response.status_code, 202)
            request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))
            start = request["args"].index("fd")
            self.assertEqual(request["args"][start : start + 2], ["fd", "--old"])
            self.assertEqual(request["args"][request["args"].index("--old") + 1], str(old.resolve()))
            self.assertEqual(request["args"][request["args"].index("--new") + 1], str(new.resolve()))
            self.assertEqual(request["args"][request["args"].index("--type") + 1], "lef")

    def test_completed_file_diff_run_exposes_html_artifact_link(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "workspace"
            raw_root = root / "raw"
            job_root = workspace / "jobs"
            artifact_dir = workspace / "file_diff" / "manual" / "lef_old_to_new"
            artifact_dir.mkdir(parents=True)
            raw_root.mkdir(parents=True)
            html = artifact_dir / "index.html"
            markdown = artifact_dir / "pairwise_summary.md"
            pairwise = artifact_dir / "pairwise_result.json"
            raw_text_diff = artifact_dir / "raw_text_diff.html"
            export_zip = artifact_dir / "file_diff_export.zip"
            html.write_text("<html><body>单文件深度对比报告</body></html>", encoding="utf-8")
            markdown.write_text("# 单文件深度对比摘要\n", encoding="utf-8")
            pairwise.write_text("{}", encoding="utf-8")
            raw_text_diff.write_text("<html><body>双栏文本对比</body></html>", encoding="utf-8")
            export_zip.write_bytes(b"PK\x05\x06" + b"\x00" * 18)
            config_path = workspace / "lib_guard.yml"
            config_path.write_text(
                "\n".join(
                    [
                        f"workspace: {workspace}",
                        f"raw_root: {raw_root}",
                        f"catalog: {SMOKE_CONFIG.parent / 'catalog' / 'catalog.json'}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            run = job_root / "file-diff_demo"
            run.mkdir(parents=True)
            (run / "status.json").write_text(json.dumps({"job_id": run.name, "status": "COMPLETED", "return_code": 0}), encoding="utf-8")
            (run / "stdout.log").write_text(
                json.dumps(
                    {
                        "status": "DIFF",
                        "out_dir": str(artifact_dir),
                        "html": str(html),
                        "markdown": str(markdown),
                        "export": str(export_zip),
                        "pairwise_result": str(pairwise),
                        "summary": {"file_type": "lef", "changed": True},
                    }
                ),
                encoding="utf-8",
            )
            (run / "result.json").write_text(
                json.dumps(
                    {
                        "schema_version": "web_job_result.v1",
                        "result": "ok",
                        "exit_code": 0,
                        "cli_result": {
                            "status": "DIFF",
                            "out_dir": str(artifact_dir),
                            "html": str(html),
                            "markdown": str(markdown),
                            "export": str(export_zip),
                            "pairwise_result": str(pairwise),
                            "summary": {"file_type": "lef", "changed": True},
                        },
                    }
                ),
                encoding="utf-8",
            )

            app = create_app(config_path=config_path, cwd=ROOT, test_config={"TESTING": True, "job_root": str(job_root)})
            client = app.test_client()
            status = client.get(f"/api/runs/{run.name}")

            self.assertEqual(status.status_code, 200)
            payload = status.get_json()
            artifacts = {item["id"]: item for item in payload["artifacts"]}
            self.assertEqual(payload["artifacts"][0]["id"], "raw_text_diff")
            self.assertEqual(artifacts["raw_text_diff"]["label"], "双栏文本对比")
            self.assertEqual(artifacts["html"]["url"], f"/api/runs/{run.name}/artifact/html")
            self.assertEqual(artifacts["markdown"]["url"], f"/api/runs/{run.name}/artifact/markdown")
            self.assertEqual(artifacts["export"]["url"], f"/api/runs/{run.name}/artifact/export")
            report = client.get(artifacts["html"]["url"])
            self.assertEqual(report.status_code, 200)
            self.assertIn("单文件深度对比报告", report.get_data(as_text=True))
            report.close()
            inline_export = client.get(f"/api/runs/{run.name}/artifact/file_diff_export.zip")
            self.assertEqual(inline_export.status_code, 200)
            self.assertEqual(inline_export.get_data()[:2], b"PK")
            inline_export.close()

    def test_completed_scan_run_exposes_scan_html_artifact(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "workspace"
            raw_root = root / "raw"
            report = workspace / "reports" / "demo" / "v1" / "scan_html" / "index.html"
            report.parent.mkdir(parents=True)
            raw_root.mkdir()
            report.write_text("<html><body>扫描报告</body></html>", encoding="utf-8")
            config_path = workspace / "lib_guard.yml"
            config_path.write_text(
                "\n".join(
                    [
                        f"workspace: {workspace}",
                        f"raw_root: {raw_root}",
                        f"catalog: {SMOKE_CONFIG.parent / 'catalog' / 'catalog.json'}",
                    ]
                ) + "\n",
                encoding="utf-8",
            )
            run = workspace / "jobs" / "scan_demo"
            run.mkdir(parents=True)
            result = {
                "schema_version": "web_job_result.v1",
                "result": "ok",
                "exit_code": 0,
                "cli_result": {"status": "PASS", "scan_html": {"index_html": str(report)}},
            }
            (run / "result.json").write_text(json.dumps(result), encoding="utf-8")
            (run / "status.json").write_text(
                json.dumps({"job_id": run.name, "status": "COMPLETED", "return_code": 0}),
                encoding="utf-8",
            )
            (run / "stdout.log").write_text("", encoding="utf-8")

            client = create_app(
                config_path=config_path,
                cwd=ROOT,
                test_config={"TESTING": True, "job_root": str(workspace / "jobs")},
            ).test_client()
            status = client.get(f"/api/runs/{run.name}")
            self.assertEqual(status.status_code, 200)
            artifact = next(item for item in status.get_json()["artifacts"] if item["id"] == "scan_html")
            self.assertEqual(artifact["kind"], "html")
            response = client.get(artifact["url"])
            self.assertEqual(response.status_code, 200)
            self.assertIn("扫描报告", response.get_data(as_text=True))
            response.close()

    def test_file_diff_route_rejects_explicit_files_outside_allowed_roots(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "workspace"
            raw_root = Path(td) / "raw"
            raw_root.mkdir(parents=True)
            outside = Path(td) / "outside.lef"
            inside = raw_root / "new.lef"
            outside.write_text("VERSION 5.8 ;\nMACRO A\nEND A\n", encoding="utf-8")
            inside.write_text("VERSION 5.8 ;\nMACRO B\nEND B\n", encoding="utf-8")
            config_path = workspace / "lib_guard.yml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                "\n".join(
                    [
                        f"workspace: {workspace}",
                        f"raw_root: {raw_root}",
                        f"catalog: {SMOKE_CONFIG.parent / 'catalog' / 'catalog.json'}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            app = create_app(config_path=config_path, cwd=ROOT, test_config={"TESTING": True, "job_root": str(workspace / "jobs")})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/file-diff",
                json={"old_file": str(outside), "new_file": str(inside), "type": "lef"},
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("不在当前允许范围内", response.get_json()["error"])
            self.assertFalse((workspace / "jobs").exists())

    def test_linked_file_diff_request_does_not_overwrite_scan_or_version_diff(self) -> None:
        from lib_guard.web.app import create_app
        from lib_guard.web.read_model import load_web_state

        with tempfile.TemporaryDirectory() as td:
            state = load_web_state(config_path=SMOKE_CONFIG, cwd=ROOT)
            library = next(item for item in state["catalog"]["libraries"] if item.get("library_name") == LIBRARY)
            version = next(item for item in library["versions"] if item.get("version_id") == "20260627_asap7")
            scan_dir = Path(str((version.get("scan") or {}).get("scan_dir") or ""))
            diff_data = version.get("diff") or {}
            diff_dir = Path(str(diff_data.get("adjacent_diff_dir") or diff_data.get("base_diff_dir") or ""))
            before = {
                "catalog": Path(state["catalog_path"]).read_bytes(),
                "scan": (scan_dir / "file_inventory.json").read_bytes(),
                "diff": (diff_dir / "file_diff.json").read_bytes(),
            }
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/file-diff",
                json={
                    "base": "20260624_asap7",
                    "old_relpath": "asap7_source_package/lef/asap7_tech_1x_201209.lef",
                    "relpath": "upstream_ae9a8ed9/lef/asap7_tech_1x_201209.lef",
                    "type": "lef",
                },
            )

            self.assertEqual(response.status_code, 202)
            self.assertEqual(before["catalog"], Path(state["catalog_path"]).read_bytes())
            self.assertEqual(before["scan"], (scan_dir / "file_inventory.json").read_bytes())
            self.assertEqual(before["diff"], (diff_dir / "file_diff.json").read_bytes())

    def test_file_changes_endpoint_exposes_existing_diff_rows(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().get(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/file-changes"
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["source"], "existing_file_diff_evidence")
            self.assertEqual(payload["base_version"], "20260624_asap7")
            self.assertGreater(payload["count"], 0)
            self.assertIn("file_type", payload["rows"][0])
            self.assertIn("pagination", payload)
            self.assertIn("counts", payload)
            self.assertIn("comparison_semantics", payload)
            self.assertIn("omitted_from_overlay", payload)

    def test_file_changes_endpoint_filters_and_pages_on_the_server(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().get(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/file-changes?change=ADDED&limit=1"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertLessEqual(len(payload["rows"]), 1)
        self.assertTrue(all(row["change"] == "ADDED" for row in payload["rows"]))
        self.assertGreaterEqual(payload["counts"]["total"], payload["count"])
        self.assertIn("next_offset", payload["pagination"])

    def test_file_tree_endpoint_exposes_scan_inventory_as_relative_paths(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().get(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/file-tree"
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["source"], "scan_file_inventory")
            self.assertGreater(payload["file_count"], 0)
            self.assertTrue(payload["files"])
            self.assertTrue(all("abs_path" not in row for row in payload["files"]))
            self.assertTrue(all(not row["path"].startswith("/") for row in payload["files"]))

    def test_review_gate_and_packet_routes_expand_to_fixed_short_commands(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            client = app.test_client()
            gate = client.post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/review-gate",
                json={"operation": "check", "gate": "current"},
            )
            packet = client.post(
                f"/api/libraries/{LIBRARY}/versions/20260627_asap7/review-packet",
                json={"operation": "submit", "review_id": "review_01", "decision": "PASS", "note": "checked", "reviewer": "reviewer"},
            )

            self.assertEqual(gate.status_code, 202)
            self.assertEqual(packet.status_code, 202)
            gate_request = json.loads(Path(gate.get_json()["request"]).read_text(encoding="utf-8"))
            packet_request = json.loads(Path(packet.get_json()["request"]).read_text(encoding="utf-8"))
            gate_start = gate_request["args"].index("rv")
            packet_start = packet_request["args"].index("review")
            self.assertEqual(gate_request["args"][gate_start : gate_start + 2], ["rv", "check"])
            self.assertEqual(packet_request["args"][packet_start : packet_start + 2], ["review", "submit"])
            self.assertIn("--reviewer", packet_request["args"])
            self.assertNotIn("shell", gate_request)
            self.assertNotIn("shell", packet_request)

    def test_library_admin_action_file_and_rollback_routes_are_allowlisted(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            client = app.test_client()
            requests = [
                ("/api/library/discover", {}, "library"),
                ("/api/library/accept", {}, "library"),
                ("/api/library/apply", {}, "library"),
                ("/api/library/add", {"library_id": "Vendor_Z.demo", "root": str(ROOT / "tests" / "fixtures" / "raw" / "vendor_A")}, "library"),
                (f"/api/libraries/{LIBRARY}/action", {}, "action"),
                (
                    f"/api/libraries/{LIBRARY}/effective-rollback",
                    {"to": "E_old", "by": "owner", "reason": "candidate was incorrect"},
                    "effective",
                ),
            ]

            for endpoint, payload, expected in requests:
                response = client.post(endpoint, json=payload)
                self.assertEqual(response.status_code, 202, endpoint)
                request = json.loads(Path(response.get_json()["request"]).read_text(encoding="utf-8"))
                self.assertIn(expected, request["args"])
                if endpoint == "/api/library/apply":
                    self.assertIn("--refresh-catalog", request["args"])
                if endpoint == "/api/library/accept":
                    self.assertIn("--apply", request["args"])
                    self.assertIn("--refresh-catalog", request["args"])
                self.assertNotIn("shell", request)

    def test_library_add_rejects_root_outside_configured_browse_scope(self) -> None:
        from lib_guard.web.app import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(config_path=SMOKE_CONFIG, cwd=ROOT, test_config={"TESTING": True, "job_root": td})
            response = app.test_client().post(
                "/api/library/add",
                json={"library_id": "outside.demo", "root": "/etc"},
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("浏览目录", response.get_json()["error"])
            self.assertIn(str(ROOT / "tests" / "fixtures" / "raw"), response.get_json()["error"])
            self.assertEqual(list(Path(td).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
