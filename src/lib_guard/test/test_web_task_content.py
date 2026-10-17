"""Behavioral boundaries for task scope and persistent settings."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from lib_guard.test.test_web_semantic_review import make_workspace

ROOT = Path(__file__).resolve().parents[3]


class WebTaskContentTest(unittest.TestCase):
    def test_directory_update_keeps_scan_defaults(self):
        from lib_guard.web.app import create_app
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config, _ = make_workspace(root)
            config.write_text(config.read_text() + 'hash_policy: smart\nparse_jobs: 4\n')
            raw = root / 'other_raw'
            raw.mkdir()
            client = create_app(config_path=config, cwd=ROOT, test_config={'TESTING': True}).test_client()
            response = client.post('/api/workspace/config', json={'raw_root': str(raw)})
            self.assertEqual(response.status_code, 200, response.get_json())
            saved = config.read_text()
            self.assertIn('hash_policy: smart', saved)
            self.assertIn('parse_jobs: 4', saved)
            self.assertIn(str(raw), saved)

    def test_release_input_precedes_preview_and_apply_and_version_list_is_not_sticky(self):
        template = (ROOT / 'src/lib_guard/web/templates/index.html').read_text()
        styles = (ROOT / 'src/lib_guard/web/static/styles.css').read_text()
        action = template[template.index('class="release-workspace-actions"'):template.index('id="formal-release-library-panel"')]
        for left, right in [('id="release-publish-name"', 'id="release-plan-action-button"'),
                            ('id="release-plan-action-button"', 'id="release-plan-result"'),
                            ('id="release-plan-result"', 'id="release-apply-action-button"')]:
            self.assertLess(action.index(left), action.index(right))
        workspace = template[template.index('id="version-workspace"'):template.index('id="action-workspace"')]
        self.assertLess(workspace.index('id="version-list-disclosure"'), workspace.index('class="pinned-workbench"'))
        self.assertIn('id="version-list-disclosure" class="pinned-version-board" aria-label="版本状态列表" open', workspace)
        self.assertRegex(styles, r'\.pinned-workbench\s*\{[^}]*position:\s*static')

    def test_combination_labels_use_ordered_manifest_versions_and_rule_requirements(self):
        with tempfile.TemporaryDirectory() as td:
            config, _ = make_workspace(td)
            from lib_guard.web.app import create_app
            client = create_app(config_path=config, cwd=ROOT, test_config={'TESTING': True}).test_client()
            options = client.get('/api/libraries/demo/semantic-review').get_json()
            target = next(row for row in options['targets'] if row['id'] == 'E2')
            self.assertEqual(target['versions'], ['full', 'fix'])
            self.assertIn('full + fix', target['label'])
            checks = {check['id']: check for profile in options['profiles'] for check in profile['checks']}
            self.assertTrue(checks['LEF_MACRO_DELTA']['requires_base'])

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_release_apply_requires_matching_successful_preview(self):
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        helper = script[script.index('  function actionPayload('):script.index('  function webActionSpec(')]
        harness = """
const assert = require('node:assert/strict');
const nodes = new Map();
const $ = id => { if (!nodes.has(id)) nodes.set(id, {
  value:'',checked:false,disabled:false,classList:{hidden:false,toggle(name, on){this[name]=on;}}
}); return nodes.get(id); };
const state = {selectedLibrary:'demo',selectedVersion:{version_id:'v2'},formalReleaseTarget:null,
  releasePlan:null,releasePreviewKey:'',activeAction:null};
$('release-root-display').value='/tmp/release';
$('release-alias').value='current'; $('release-link-mode').value='symlink';
$('release-latest-name').value='latest';
""" + helper + """
assert.equal(invalidateReleasePreview(), false);
assert.equal($('release-apply-action-button').disabled, true);
assert.equal($('release-apply-action-button').classList.hidden, true);
state.releasePlan={dry_run:true,status:'DRY_RUN',library:'demo',version:'v2'};
state.releasePreviewKey=releasePreviewKey();
assert.equal(invalidateReleasePreview(), false);
assert.equal($('release-apply-action-button').disabled, false);
assert.equal($('release-apply-action-button').classList.hidden, false);
$('release-latest-name').value='new-latest';
assert.equal(invalidateReleasePreview(), true);
assert.equal($('release-apply-action-button').disabled, true);
assert.equal($('release-apply-action-button').classList.hidden, true);
$('release-latest-name').value='latest';
state.releasePlan.status='FAILED';
assert.equal(invalidateReleasePreview(), false);
assert.equal($('release-apply-action-button').disabled, true);
state.releasePlan.status='PARTIAL_DRY_RUN';
assert.equal(invalidateReleasePreview(), false);
assert.equal($('release-apply-action-button').disabled, false);
"""
        result = subprocess.run(['node', '-e', harness], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_new_links_are_visible_by_default_in_release_preview(self):
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        helper = script[script.index('  function initialReleaseLinkScope('):script.index('  function filterReleaseLinks(')]
        harness = """
const assert=require('node:assert/strict');
const releaseLinkAction=row=>row.action;
""" + helper + """
assert.equal(initialReleaseLinkScope([{action:'new'},{action:'new'}]),'all');
assert.equal(initialReleaseLinkScope([{action:'new'},{action:'replace'}]),'focus');
assert.equal(initialReleaseLinkScope([{action:'new',error:'missing'}]),'focus');
"""
        result = subprocess.run(['node', '-e', harness], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_saving_directories_does_not_capture_temporary_scan_settings(self):
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        helper = script[script.index('  function workspaceConfigPayload('):script.index('  function showSettingsFeedback(')]
        harness = """
const assert = require('node:assert/strict');
const nodes = new Map();
const $ = id => { if (!nodes.has(id)) nodes.set(id, {value:'',checked:false}); return nodes.get(id); };
const document = {querySelectorAll: () => []};
$('hash-policy').value='full'; $('config-hash-policy').value='smart';
$('config-raw-root').value='/new/raw';
""" + helper + """
const paths=workspaceConfigPayload('directories');
assert.equal(paths.raw_root,'/new/raw');
assert.deepEqual(Object.keys(paths).sort(),['raw_root','release_latest_name','release_publish_name','release_root']);
assert.equal(workspaceConfigPayload('scan').hash_policy,'smart');
assert.equal(Object.keys(workspaceConfigPayload('discovery')).length,4);
"""
        result = subprocess.run(['node', '-e', harness], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_no_baseline_disables_only_delta_rules_and_preserves_selection(self):
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        helper = script[script.index('  function renderSemanticReviewReadiness('):script.index('  function renderSemanticReviewChecks(')]
        harness = """
const assert=require('node:assert/strict');
const inputs=[{checked:true,value:'delta',dataset:{requiresBase:'true'}},{checked:true,value:'single',dataset:{requiresBase:'false'}}];
const nodes=new Map(); const $=id=>{if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',querySelectorAll:()=>inputs});return nodes.get(id);};
const state={selectedLibrary:'demo',semanticOptionsLibrary:'demo',semanticOptions:{targets:[{id:'E2',label:'full + fix'}]}};
$('semantic-review-target').value='E2';
""" + helper + """
renderSemanticReviewReadiness();
assert.equal(inputs[0].disabled,true); assert.equal(inputs[1].disabled,false);
assert.equal($('semantic-review-run').disabled,false);
inputs[1].checked=false; renderSemanticReviewReadiness();
assert.equal($('semantic-review-run').disabled,true);
$('semantic-review-base').value='E1';renderSemanticReviewReadiness();
assert.equal(inputs[0].disabled,false);assert.equal(inputs[0].checked,true);
assert.equal($('semantic-review-run').disabled,false);
assert.ok($('semantic-review-scope').textContent.includes('full + fix'));
"""
        result = subprocess.run(['node', '-e', harness], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
