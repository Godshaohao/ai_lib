from __future__ import annotations

import unittest
import shutil
import subprocess
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class WebUiContractTest(unittest.TestCase):
    def test_analysis_actions_are_scoped_to_analysis_and_run_console_is_collapsible(self):
        template = (ROOT / 'src/lib_guard/web/templates/index.html').read_text()
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        styles = (ROOT / 'src/lib_guard/web/static/styles.css').read_text()
        analysis = template.split('id="action-workspace"', 1)[1].split('id="release-workspace"', 1)[0]
        commandbar = analysis[analysis.index('class="workbench-commandbar"'):analysis.index('class="action-deck-heading"')]
        for action in ('scan', 'compare', 'file-diff', 'checks', 'review'):
            self.assertIn(f'data-workbench-command="{action}"', commandbar)
        self.assertNotIn('data-workbench-command="release"', template)
        self.assertEqual(template.count('data-stage-target="release-workspace"'), 1)
        self.assertIn('function activateWorkbenchCommand(', script)
        self.assertIn("activateWorkbenchCommand(tab.dataset.workbenchCommand || tab.dataset.analysisAction)", script)
        self.assertIn('<details id="run-workspace" class="runtime-dock runtime-strip"', template)
        self.assertIn('id="runtime-dock-summary"', template)
        self.assertLess(template.index('class="runtime-dock runtime-strip"'), template.index('</main>'))
        pinned = template[template.index('class="pinned-workbench"'):template.index('</section>', template.index('class="pinned-workbench"'))]
        self.assertNotIn('id="run-workspace"', pinned)
        self.assertRegex(styles, r'\.console-shell\s*\{[^}]*grid-template-columns:\s*272px minmax\(0, 1fr\)')
        self.assertRegex(styles, r'\.runtime-dock\s*\{[^}]*position:\s*fixed')

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_global_workbench_commands_select_the_expected_workspace(self):
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        start = script.index('  function activateWorkbenchCommand(')
        end = script.index('\n  function ', start + 10)
        helper = script[start:end]
        harness = """
const assert = require('node:assert/strict');
const calls = [];
const selectAnalysisAction = value => calls.push(['action', value]);
const setActiveStageTab = value => calls.push(['stage', value]);
""" + helper + """
for (const [command, expected] of Object.entries({scan:'scan', compare:'compare', 'file-diff':'file-diff', review:'review'})) {
  calls.length = 0;
  activateWorkbenchCommand(command);
  assert.deepEqual(calls, [['action', expected], ['stage', 'action-workspace']]);
}
calls.length = 0;
activateWorkbenchCommand('release');
assert.deepEqual(calls, [['stage', 'release-workspace']]);
"""
        result = subprocess.run(['node', '-e', harness], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_lib_db_checklist_is_in_file_structure_and_uses_existing_evidence(self):
        template=(ROOT/'src/lib_guard/web/templates/index.html').read_text()
        script=(ROOT/'src/lib_guard/web/static/app.js').read_text()
        for element in ['lib-db-correspondence-panel','lib-db-relation','lib-db-query','lib-db-prev','lib-db-next']:
            self.assertIn(f'id="{element}"',template)
        self.assertIn('payload.lib_db_correspondence',script)
        self.assertIn('不自动判断缺件',template)

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_formal_quick_filters_clear_old_scope_before_loading(self):
        script=(ROOT/'src/lib_guard/web/static/app.js').read_text()
        self.assertIn('  function resetFormalInventoryFilters(',script)
        helper=script[script.index('  function resetFormalInventoryFilters('):script.index('  async function loadFormalInventory(')]
        harness="""
const assert=require('node:assert/strict');
const state={formalOffset:100};
const nodes=new Map(); const $=id=>{if(!nodes.has(id))nodes.set(id,{value:'old'});return nodes.get(id);};
let calls=0; const loadFormalInventory=()=>{calls++;};
"""+helper+"""
resetFormalInventoryFilters('broken');
assert.equal(state.formalOffset,0); assert.equal($('formal-directory-library').value,'');
assert.equal($('formal-directory-version').value,''); assert.equal($('formal-directory-query').value,'');
assert.equal($('formal-directory-status').value,'broken'); assert.equal(calls,1);
resetFormalInventoryFilters(); assert.equal($('formal-directory-status').value,'');
"""
        result=subprocess.run(['node','-e',harness],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_formal_directory_inventory_is_separate_from_temporary_release(self):
        template=(ROOT/'src/lib_guard/web/templates/index.html').read_text()
        script=(ROOT/'src/lib_guard/web/static/app.js').read_text()
        for element in ['formal-directory-root','formal-directory-current-root','formal-directory-libraries','formal-directory-packages','formal-directory-files','formal-audit-status','formal-current-pointer','temporary-directory-panel']:
            self.assertIn(f'id="{element}"',template)
        self.assertIn('/api/formal-directory/refresh',script)
        self.assertIn('formalInventoryRequestId',script)
        self.assertIn('原快照保留',script)
        self.assertIn('不比较历史版本',script)
        self.assertIn('没有 release_manifest.json 不影响正式目录核查',script)

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_effective_table_saves_edits_before_preview_and_stops_on_failure(self):
        script = (ROOT/'src/lib_guard/web/static/app.js').read_text()
        self.assertIn('  function effectiveVersionEdits(', script)
        helpers = script[script.index('  function effectiveSelectionKey('):script.index('  function renderEffectiveSelection(')]
        harness = """
const assert=require('node:assert/strict');
const state={selectedLibrary:'demo',effectiveDrafts:new Map(),versions:[{version_id:'full',package_type:'FULL_PACKAGE'},{version_id:'fix',package_type:'PARTIAL_UPDATE'}]};
const selectedLibraryRow=()=>({}); const $=()=>({textContent:''});
let calls=[],failure=false;
const setActionBusy=()=>{},getJson=async(url,opts)=>{calls.push({url,payload:JSON.parse(opts.body)});return {};};
const startJob=async()=>({return_code:failure?2:0});
""" + helpers + """
(async()=>{
const draft=effectiveSelectionDraft(); draft.preview={key:effectiveSelectionKey(draft),endpoint:'next'};
editEffectiveVersion('fix',{package_type:'HOTFIX'});
assert.equal(draft.preview,null); assert.equal(effectiveSelectionMatchesCandidate(draft,{base_full_version:'full',accepted_updates:[]}),false);
assert.equal(effectiveVersionRows()[1].package_type,'HOTFIX');
failure=true; await assert.rejects(saveEffectiveVersionEdits('demo'),/fix/);
assert.equal(effectiveVersionEdits().size,1);
failure=false; await saveEffectiveVersionEdits('demo');
assert.equal(effectiveVersionEdits().size,0); assert.equal(calls[1].payload.package_type,'HOTFIX');
assert.ok(calls[1].url.endsWith('/fix/override'));
})();
"""
        result=subprocess.run(['node','-e',harness],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_accepted_combination_is_not_still_presented_as_unapplied_candidate(self):
        script = (ROOT/'src/lib_guard/web/static/app.js').read_text()
        template = (ROOT/'src/lib_guard/web/templates/index.html').read_text()
        self.assertIn('id="candidate-effective-status"', template)
        self.assertIn("pendingWindow.state === 'ACCEPTED'", script)
        self.assertIn('查看已确认组合的核对记录', script)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for manual selection tests')
    def test_manual_selection_preserves_drafts_and_requires_exact_preview(self):
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        self.assertIn('  function effectiveSelectionKey(', script)
        helper = script[script.index('  function effectiveSelectionKey('):script.index('  function renderEffectiveSelection(')]
        harness = """
const assert = require('node:assert/strict');
const state = {effectiveDrafts:new Map(), selectedLibrary:'A', versions:[]};
const rows = [{version_id:'full1',package_type:'FULL_PACKAGE'},
 {version_id:'old',package_type:'HOTFIX'}, {version_id:'full2',package_type:'FULL_PACKAGE'},
 {version_id:'fix',package_type:'PARTIAL_UPDATE'}, {version_id:'doc',package_type:'DOC_UPDATE'},
 {version_id:'unknown',package_type:'UNKNOWN_PACKAGE'}];
// API rows arrive newest first; eligibility follows catalog order, not display sorting.
state.versions = rows.slice().reverse();
let library = {pending_window:{candidate_effective_stack:{base_full_version:'full1',accepted_updates:['doc','fix']}},
 current_effective_stack:{base_full_version:'full2',accepted_updates:[]}};
const selectedLibraryRow = () => library;
""" + helper + """
let draft = effectiveSelectionDraft();
assert.equal(draft.base_full,'full1'); assert.deepEqual(draft.includes,['doc','fix']);
assert.deepEqual(eligibleEffectiveOverlays(state.versions,'full2').map(r=>r.version_id),['doc','fix']);
state.versions.push({version_id:'older_fix',package_type:'PARTIAL_UPDATE'});
assert.ok(eligibleEffectiveOverlays(state.versions,'full2',true).some(r=>r.version_id==='older_fix'));
assert.equal(effectiveSelectionMatchesCandidate(draft,library.pending_window.candidate_effective_stack),true);
draft.preview = {key:effectiveSelectionKey(draft),endpoint:'next',payload:{base_full:'full1',includes:['doc','fix']}};
assert.equal(effectiveSelectionPreviewReady(draft,'next'),true);
changeEffectiveSelection({base_full:'full1',includes:['fix','doc']});
assert.equal(draft.preview,null); assert.equal(draft.dirty,true);
assert.equal(effectiveSelectionMatchesCandidate(draft,library.pending_window.candidate_effective_stack),false);
library = {current_effective_stack:{base_full_version:'full2'}};
assert.strictEqual(effectiveSelectionDraft(),draft);
state.selectedLibrary='B';
assert.equal(effectiveSelectionDraft().base_full,'full2');
state.selectedLibrary='C'; library={pending_window:{candidate_effective_stack:null}};
assert.equal(effectiveSelectionDraft().base_full,'full2');
assert.equal(effectiveSelectionDraft().source,'最新完整包预填');
assert.deepEqual(effectiveSelectionDraft().includes,['fix','doc']);
state.selectedLibrary='A'; assert.strictEqual(effectiveSelectionDraft(),draft);
"""
        result = subprocess.run(['node', '-e', harness], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_manual_selection_editor_is_in_existing_workbench(self):
        template = (ROOT / 'src/lib_guard/web/templates/index.html').read_text()
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        for element_id in ['effective-selection-body', 'effective-selection-order', 'effective-selection-status', 'effective-selection-load-all']:
            self.assertIn(f'id="{element_id}"', template)
        self.assertIn('name="effective-base"', script)
        self.assertIn('data-effective-overlay', script)
        self.assertIn('effectiveSelectionPreviewReady', script)
        self.assertIn('effectiveSelectionMatchesCandidate', script)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for workflow selection tests')
    def test_manual_selection_workflow_reuses_successful_preview_and_blocks_stale_accept(self):
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        helpers = script[script.index('  function effectiveSelectionKey('):script.index('  function renderEffectiveSelection(')]
        workflow = script[script.index('  function workflowRequest('):script.index('  function workflowSuccessMessage(')]
        harness = """
const assert = require('node:assert/strict');
const state = {selectedLibrary:'demo',activeAction:null,effectiveDrafts:new Map(),versions:[]};
const library = {pending_window:{candidate_effective_stack:{base_full_version:'full',accepted_updates:['doc','fix']}}};
const selectedLibraryRow = () => library;
const nodes = new Map();
const $ = id => {if(!nodes.has(id)) nodes.set(id,{value:'owner',checked:false,textContent:''}); return nodes.get(id);};
let strategy='first', outcome=0, requests=[], confirmations=0;
const strategyPayload = () => ({hash_policy:strategy});
const window = {confirm:()=>{confirmations++;return true;}};
const writeConfirmation=()=>'',setWorkflowStatus=()=>{},statusClass=()=>'',renderVersionFacts=()=>{};
const setActionBusy=action=>{state.activeAction=action;};
const clearActionBusy=()=>{state.activeAction=null;};
const getJson=async(url,options)=>{requests.push({url,payload:JSON.parse(options.body)});return {status:'QUEUED'};};
const startJob=async()=>{state.activeAction=null;return {return_code:outcome,result_summary:'returned summary'};};
""" + helpers + workflow + """
(async()=>{
 const draft=effectiveSelectionDraft();
 await runWorkflow('next-apply'); assert.equal(requests.length,0); assert.equal(confirmations,0);
 outcome=1; await runWorkflow('next-preview'); assert.equal(draft.preview,null);
 await runWorkflow('next-apply'); assert.equal(requests.length,1);
 outcome=0; await runWorkflow('next-preview');
 assert.equal(effectiveSelectionPreviewReady(draft,'next'),true);
 assert.equal($('workflow-summary').textContent,'returned summary');
 assert.deepEqual(requests[1].payload.includes,['doc','fix']);
 strategy='changed'; await runWorkflow('next-apply');
 assert.equal(requests[2].payload.hash_policy,'first');
 assert.equal(requests[2].payload.base_full,'full');
 assert.deepEqual(requests[2].payload.includes,['doc','fix']);
 assert.equal(requests[2].payload.apply,true);
 assert.equal(requests[2].payload.plan_only,false);
 changeEffectiveSelection({base_full:'full',includes:['fix','doc']});
 await runWorkflow('accept-window'); await runWorkflow('next-apply');
 assert.equal(requests.length,3);
 await runWorkflow('intake-preview'); await runWorkflow('intake-apply');
 assert.deepEqual(requests[4].payload.includes,['fix','doc']);
 assert.equal(requests[4].payload.plan_only,false);
 assert.equal(effectiveSelectionPreviewReady(draft,'next'),false);
 library.pending_window.candidate_effective_stack.accepted_updates=['fix','doc'];
 await runWorkflow('accept-window'); assert.ok(requests[5].url.endsWith('/accept-window'));
 assert.deepEqual(requests[5].payload,{accepted_by:'owner',note:'owner',expected_effective_id:''});
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result = subprocess.run(['node', '-e', harness], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for selection pagination tests')
    def test_manual_selection_loads_all_pages_only_on_demand(self):
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        helper = script[script.index('  async function loadAllEffectiveVersions('):script.index('  function shortDigest(')]
        harness = """
const assert=require('node:assert/strict');
const state={selectedLibrary:'demo',libraryRequestId:1,versions:[],versionHasMore:true};
const $=()=>({});let reads=0;
const refreshVersionsForSelectedLibrary=async(id,append)=>{
 assert.equal(id,1);assert.equal(append,true);reads++;
 state.versions.push(...Array.from({length:25},(_,i)=>({version_id:`v${reads}-${i}`})));
 state.versionHasMore=reads<3;
};
""" + helper + """
(async()=>{
 assert.equal(reads,0);await loadAllEffectiveVersions();
 assert.equal(reads,3);assert.equal(state.versions.length,75);
 state.versionHasMore=true;state.versionsLoadingMore=true;
 await loadAllEffectiveVersions();assert.equal(reads,3);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result = subprocess.run(['node', '-e', harness], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for composition tests')
    def test_effective_table_contains_composition_not_unrelated_history(self):
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        self.assertIn('  function effectiveCompositionRows(', script)
        helper = script[script.index('  function effectiveCompositionRows('):script.index('  function renderEffectiveCompositionTable(')]
        subprocess.run(['node', '-e', "const assert = require('node:assert/strict');" + helper + """
const updates = Array.from({length:50}, (_,i) => `fix${i}`);
const versions = [{version_id:'unrelated_history',scan_evidence_ready:true},{version_id:'base',scan_evidence_ready:true}];
const rows = effectiveCompositionRows({available:true,base_full_version:'base',accepted_updates:updates},
  {candidate_effective_id:'E_new',base_full_version:'newbase',accepted_updates:['patch']}, versions);
assert.equal(rows.length, 53);
assert.equal(rows[0].role, '完整包基线');
assert.equal(rows[50].order, 51);
assert.equal(rows[0].evidence, '已就绪');
assert.equal(rows[51].evidence, '未读取');
assert.ok(!rows.some(row => row.version === 'unrelated_history'));
assert.equal(filterEffectiveCompositionRows(rows,'candidate','patch').length,1);
assert.equal(filterEffectiveCompositionRows(rows,'current','base').length,1);
assert.deepEqual(effectiveCompositionRows({}, {}, versions), []);
"""], check=True, capture_output=True, text=True)

    def test_effective_workspace_has_real_table_and_bounded_controls(self):
        template = (ROOT / 'src/lib_guard/web/templates/index.html').read_text()
        styles = (ROOT / 'src/lib_guard/web/static/styles.css').read_text()
        for element_id in ['effective-composition-body', 'effective-composition-query', 'effective-composition-scope', 'effective-composition-reset']:
            self.assertIn(f'id="{element_id}"', template)
        self.assertIn('aria-label="有效组合组成"', template)
        self.assertIn('.effective-comparison-grid', styles)
        self.assertIn('.effective-composition-scroll', styles)
        self.assertNotIn('.workflow-step > span {', styles)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for effective navigation tests')
    def test_effective_results_and_rollback_follow_current_library_state(self):
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        helper = script[script.index('  function shortDigest('):script.index('  function releaseSetLibraryAvailable(')]
        subprocess.run(['node', '-e', """
const assert = require('node:assert/strict');
const elements = new Map();
const $ = id => {if (!elements.has(id)) elements.set(id, {value: '', querySelectorAll(){return [];}, removeAttribute(k){delete this[k];}}); return elements.get(id);};
const escapeHtml = text => String(text);
const library = {library_name: 'demo', current_effective_stack: {available:true,current_effective_id:'E_old'},
  pending_window: {compare_url:'/artifacts/compare/index.html', candidate_effective_stack:{candidate_effective_id:'E_new'},
    saved_combinations:[{effective_id:'E_old'},{effective_id:'E_new'},{effective_id:'E_history'}]}};
const state = {selectedLibrary:'demo',libraries:[library],versions:[],activeAction:null};
""" + helper + """
renderEffectiveStack();
assert.equal($('compare-current-candidate').href, '/artifacts/compare/index.html');
assert.equal($('compare-current-candidate').hidden, false);
assert.equal($('workflow-compare-placeholder').hidden, true);
assert.ok($('rollback-to').innerHTML.includes('E_history'));
assert.ok(!$('rollback-to').innerHTML.includes('E_new'));
assert.ok(!$('rollback-to').innerHTML.includes('E_old'));
$('rollback-to').value = 'E_history';
renderEffectiveStack();
assert.equal($('rollback-to').value, 'E_history');
library.pending_window = {};
renderEffectiveStack();
assert.equal($('compare-current-candidate').hidden, true);
assert.equal($('compare-current-candidate').href, undefined);
assert.equal($('workflow-compare-placeholder').hidden, false);
assert.equal($('rollback-to').disabled, true);
"""], check=True, capture_output=True, text=True)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for confirmation tests')
    def test_effective_confirmation_discloses_old_and_new_composition(self):
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        helper = script[script.index('  function writeConfirmation('):script.index('  function renderJobObservation(')]
        subprocess.run(['node', '-e', """
const assert = require('node:assert/strict');
const state = {selectedLibrary: 'demo', libraries: [{library_name: 'demo',
  current_effective_stack: {current_effective_id: 'E_old', base_full_version: 'full1', accepted_updates: ['fix1']},
  pending_window: {candidate_effective_id: 'E_new', candidate_effective_stack: {base_full_version: 'full2', accepted_updates: ['fix2']}}}]};
const $ = () => ({value: 'owner'});
""" + helper + """
const text = writeConfirmation('accept-window');
for (const value of ['E_old', 'E_new', 'full1', 'full2', 'fix1', 'fix2', 'owner']) assert.ok(text.includes(value), value);
assert.ok(text.includes('不创建发布链接'));
"""], check=True, capture_output=True, text=True)

    def test_effective_comparison_is_a_result_link_not_plan_action(self):
        template = (ROOT / 'src/lib_guard/web/templates/index.html').read_text()
        self.assertRegex(template, r'<a id="compare-current-candidate"[^>]*>')
        self.assertNotRegex(template, r'id="compare-current-candidate"[^>]*data-workflow-action')
        self.assertIn('<select id="rollback-to">', template)
        self.assertRegex(template, r'id="current-effective-stack"[^>]* open')

    @unittest.skipUnless(shutil.which('node'), 'Node is required for evidence label tests')
    def test_file_change_feedback_distinguishes_missing_files_from_unsupported_type(self):
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        helper = script[script.index('  function fileChangeOperationLabel('):script.index('  function renderFileChangeWorkbench(')]
        subprocess.run(['node', '-e', "const assert = require('node:assert/strict');" + helper + """
assert.equal(fileChangeOperationLabel({deep_diff_available:true}), '选择核对');
assert.equal(fileChangeOperationLabel({old_path:'old',new_path:'new'}), '类型不支持');
assert.equal(fileChangeOperationLabel({new_path:'new'}), '缺旧文件');
assert.equal(fileChangeOperationLabel({old_path:'old'}), '缺新文件');
assert.equal(fileEvidenceLabel('metadata-only'), '元数据级');
assert.equal(fileEvidenceLabel('summary-only'), '摘要级');
assert.equal(fileEvidenceLabel('file-level'), '文件级');
assert.equal(fileEvidenceLabel('future-mode'), 'future-mode');
"""], check=True, capture_output=True, text=True)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for next-step tests')
    def test_next_step_uses_existing_evidence_and_never_runs_mutating_actions(self):
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        helper = script[script.index('  function analysisNextStep('):script.index('  function renderActionDeckNavigation(')]
        subprocess.run(['node', '-e', "const assert = require('node:assert/strict');" + helper + """
assert.equal(analysisNextStep(null), null);
assert.equal(analysisNextStep({scan_evidence_ready:false}).target, 'scan');
assert.equal(analysisNextStep({scan_evidence_ready:true}).target, 'tree');
assert.equal(analysisNextStep({scan_evidence_ready:true,base_version:'v1'}).target, 'compare');
assert.equal(analysisNextStep({scan_evidence_ready:true,base_version:'v1',diff_evidence_ready:true}).target, 'changes');
assert.equal(analysisNextStep({scan_evidence_ready:true,base_version:'v1',diff_html:'/diff/index.html'}).target, 'changes');
assert.equal(analysisNextStep({scan_evidence_ready:true,base_version:'v1',diff_status:'DIFF_DONE',diff_html:null}).target, 'changes');
"""], check=True, capture_output=True, text=True)
        template = (ROOT / 'src/lib_guard/web/templates/index.html').read_text()
        for control in ('analysis-next-step', 'reset-file-tree-filters', 'reset-file-change-filters'):
            self.assertIn(f'id="{control}"', template)
        self.assertNotIn("$('job-summary').textContent += ` 运行清单：", script)

    def test_desktop_component_system_has_consistent_density_and_readable_context(self):
        styles = (ROOT / 'src/lib_guard/web/static/styles.css').read_text()
        self.assertIn('--control-height: 32px', styles)
        self.assertIn('--table-row-height: 40px', styles)
        self.assertIn('.version-focus-strip strong { white-space: normal;', styles)
        self.assertIn('.action-deck-grid > .action-card { border: 0;', styles)
        self.assertIn('grid-template-columns: repeat(3, max-content) minmax(72px, 1fr)', styles)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for action selection tests')
    def test_analysis_action_switch_preserves_forms_and_exposes_one_panel(self):
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        select = script[script.index('  function selectAnalysisAction('):script.index('  function openFileDiffWorkbench(')]
        harness = """
const assert = require('node:assert/strict');
const names = ['scan', 'compare', 'file-diff', 'checks', 'review'];
const panels = Object.fromEntries(names.map(n => [n, {hidden: n !== 'scan', value: 'retained'}]));
const tabs = names.map(n => ({dataset: {analysisAction: n}, selected: n === 'scan', classList: {toggle(){}},
  setAttribute(k,v) {this.selected = v === 'true';}, getAttribute() {return this.dataset.analysisAction;}}));
const document = {querySelectorAll: () => tabs};
const $ = id => panels[id];
""" + select + """
for (const name of names) {
  selectAnalysisAction(name);
  assert.deepEqual(names.filter(n => !panels[n].hidden), [name]);
  assert.deepEqual(tabs.filter(t => t.selected).map(t => t.dataset.analysisAction), [name]);
  assert.equal(panels.compare.value, 'retained');
}
selectAnalysisAction('invalid');
assert.equal(panels.review.hidden, false);
"""
        subprocess.run(['node', '-e', harness], check=True, capture_output=True, text=True)

    def test_information_hierarchy_prioritizes_versions_and_separates_library_intake(self):
        template = (ROOT / 'src/lib_guard/web/templates/index.html').read_text()
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        version_workspace = template.split('id="version-workspace"', 1)[1].split('id="action-workspace"', 1)[0]
        self.assertRegex(version_workspace, r'<details id="version-list-disclosure" class="pinned-version-board"[^>]* open>')
        self.assertLess(version_workspace.index('id="version-list-disclosure"'), version_workspace.index('id="library-intake-disclosure"'))
        intake = version_workspace.split('id="library-intake-disclosure"', 1)[1]
        self.assertIn('id="registered-library-table-body"', intake)
        self.assertIn('class="library-intake-zone"', intake)
        self.assertRegex(version_workspace, r'<details id="library-intake-disclosure"[^>]*>')
        self.assertIn('aria-label="常用操作"', template)
        self.assertLess(template.index('id="action-workspace"'), template.index('class="workbench-commandbar"'))
        self.assertNotIn('class="workbench-commandbar"', template.split('id="action-workspace"', 1)[0])
        for name in ('scan', 'compare', 'file-diff', 'checks', 'review'):
            self.assertIn(f'data-analysis-action="{name}"', template)
            self.assertIn(f'id="analysis-panel-{name}"', template)
        self.assertIn('function selectAnalysisAction(', script)
        self.assertIn("selectAnalysisAction('review')", script)
        self.assertNotIn('扫描、对比和交付事实的唯一侧栏摘要', template)

    def test_version_list_has_readable_desktop_height_and_filename_width(self):
        styles = (ROOT / 'src/lib_guard/web/static/styles.css').read_text()
        rules = re.findall(r'\.version-table-shell\.pinned-version-table-shell\s*\{([^}]+)\}', styles)
        self.assertEqual(len(rules), 1)
        self.assertIn('max-height: min(55vh, 620px)', rules[0])
        self.assertNotRegex(rules[0], r'min-height\s*:')
        self.assertRegex(styles, r'\.version-work-table th:nth-child\(1\), \.version-work-table td:nth-child\(1\) \{ width: 35%; \}')

    def test_version_filter_has_one_entry_and_selected_version_actions_are_centralized(self):
        template = (ROOT / 'src/lib_guard/web/templates/index.html').read_text()
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        version_workspace = template.split('id="version-workspace"', 1)[1].split('id="action-workspace"', 1)[0]
        self.assertNotIn('id="version-status-filter"', template)
        self.assertIn('data-version-focus-action="open"', version_workspace)
        self.assertIn('data-version-focus-action="scan"', version_workspace)
        self.assertIn('data-version-focus-action="compare"', version_workspace)
        self.assertNotIn('versionRowActions(item)', script[script.index('function renderVersions()'):script.index('function setActionDeckState(')])
        self.assertIn("data-version-focus-action", script)
        self.assertEqual(script.count("document.querySelectorAll('[data-version-focus-action]').forEach((button) => button.addEventListener('click'"), 1)

    def test_candidate_confirmation_uses_readable_evidence_and_visible_path(self):
        template = (ROOT / 'src/lib_guard/web/templates/index.html').read_text()
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        section = script[script.index('  function renderLibraryCandidates()'):script.index('  async function loadLibraryCandidates()')]
        self.assertNotIn('置信度', section)
        self.assertIn('candidate.view_types', section)
        self.assertIn('修改库名 / 库根', section)
        self.assertIn('搜索未完成', section)
        self.assertIn('version_names', section)
        self.assertIn('发现路径', template)
        self.assertIn('高级搜索限制', template)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for delivery filter tests')
    def test_delivery_drilldown_clears_conflicting_filters(self):
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        start = script.index('  async function selectPublishedFiles(')
        end = script.index('  async function loadPublishedDetail(', start)
        harness = r'''
const assert=require('node:assert/strict');
const state={publishedLibrary:'ip/old',publishedFileQuery:'old',publishedOffset:100};
const nodes=new Map();
const $=id=>{if(!nodes.has(id))nodes.set(id,{value:'old',scrollIntoView(){},focus(){}});return nodes.get(id);};
let loads=0;
const renderPublishedDirectory=()=>{},updateRouteState=()=>{},loadPublishedDetail=async()=>{loads++;};
'''
        checks = r'''
(async()=>{
await selectPublishedFiles('ip/A');
assert.equal(state.publishedLibrary,'ip/A');assert.equal(state.publishedOffset,0);
assert.equal(state.publishedFileQuery,'');assert.equal($('published-view').value,'');
assert.equal($('published-link-status').value,'');assert.equal(loads,1);
await selectPublishedFiles('', 'LEF');
assert.equal(state.publishedLibrary,'');assert.equal($('published-view').value,'LEF');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', harness + script[start:end] + checks], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_delivery_labels_separate_composition_and_file_source(self):
        template = (ROOT / 'src/lib_guard/web/templates/index.html').read_text()
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        self.assertIn('准备更新发布', template)
        self.assertIn('全部发布来源', template)
        self.assertIn("item.source_version || '未记录'", script)
        self.assertIn('data-copy-delivery-path', script)
        self.assertIn('待补登记', script)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for settings navigation tests')
    def test_published_root_settings_opens_disclosure_before_focus(self):
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        start = script.index("  $('published-root-settings').addEventListener")
        end = script.index("  $('published-search').addEventListener", start)
        harness = r'''
const assert = require('node:assert/strict');
let callback, focused=false;
const nodes={'published-root-settings':{addEventListener:(event,fn)=>{callback=fn;}},
 'settings-disclosure':{open:false},'config-release-root':{focus:()=>{focused=nodes['settings-disclosure'].open;},scrollIntoView(){}}};
const $=id=>nodes[id];
const setDirectoryMode=()=>{},setActiveStageTab=()=>{};
'''
        result = subprocess.run(['node', '-e', harness + script[start:end] + '\ncallback();assert.equal(focused,true);'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for release refresh tests')
    def test_published_directory_selects_delivery_and_never_leaves_blank_tables(self):
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        start = script.index('  async function loadPublishedDetail(')
        end = script.index('  function loadReleaseStageConfiguration(', start)
        harness = r'''
const assert = require('node:assert/strict');
const state = {publishedRequestId:0, selectedPublishedStage:'', directoryMode:'published',
 publishedFileQuery:'', publishedLibrary:'', publishedOffset:0, libraries:[],
 formalReleaseSnapshot:{stages:[{publish_name:'old'},{publish_name:'latest',is_latest:true}]}};
const nodes = new Map();
const $ = id => {if(!nodes.has(id)) nodes.set(id,{innerHTML:'',textContent:'',querySelectorAll:()=>[]}); return nodes.get(id);};
const escapeHtml = x => String(x ?? '');
const renderPublishedDirectory = () => {};
const updateRouteState = () => {};
let fail = false, reads = [];
const getJson = async url => {reads.push(url); if(fail) throw new Error('无法读取'); return {
 stage:{publish_name:'latest',library_count:0,file_count:0,libraries:[]},files:[],total:0,offset:0};};
'''
        checks = r'''
(async () => {
 await loadPublishedDetail();
 assert.equal(state.selectedPublishedStage,'latest');
 assert.equal(reads.length,1);
 assert.ok($('published-components').innerHTML.includes('未记录'));
 $('published-view').value='LEF'; $('published-link-status').value='abnormal'; state.publishedLibrary='ip/B';
 await loadPublishedDetail();
 assert.ok(reads[1].includes('view=LEF'));
 assert.ok(reads[1].includes('link_status=abnormal'));
 assert.ok(reads[1].includes('library=ip%2FB'));
 fail = true;
 await loadPublishedDetail();
 assert.ok($('published-components').innerHTML.includes('读取失败'));
 assert.ok($('published-files').innerHTML.includes('读取失败'));
 state.formalReleaseSnapshot.stages = [];
 await loadPublishedDetail();
 assert.ok($('published-components').innerHTML.includes('暂无'));
})().catch(error => {console.error(error); process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', harness + script[start:end] + checks], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for release refresh tests')
    def test_successful_publication_refreshes_directory_but_preview_does_not(self):
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        start = script.index('  async function pollJob(')
        end = script.index("  document.querySelector('.skip-link')", start)
        harness = r'''
const assert = require('node:assert/strict');
const state={}; const $=()=>({classList:{remove(){}},textContent:''});
const JOB_TIMEOUT_MS=1800000;
const statusLabel = x => x, statusClass = x => x;
const renderJobObservation=()=>{},renderJobQualitySummary=()=>{},renderJobArtifacts=()=>{},renderReleasePlanResult=()=>{};
const invalidateReleasePreview=()=>{};
const clearActionBusy=()=>{},loadLibraries=async()=>{},showError=()=>{};
let refreshes=0, returnCode=0;
const getJson=async()=>({status:returnCode ? 'FAILED':'COMPLETED',return_code:returnCode});
const refreshFormalReleaseLibraries=async()=>{refreshes++;};
'''
        checks = r'''
(async()=>{
 for(const action of ['release-apply','release-force','release-set-apply','release-plan','release-set-plan']) {
  state.activeJob={commandAction:action}; state.pollTimer=setInterval(()=>{},10000);
  await pollJob('test');
 }
 assert.equal(refreshes,3);
 returnCode=2; state.activeJob={commandAction:'release-apply'}; state.pollTimer=setInterval(()=>{},10000);
 await pollJob('test'); assert.equal(refreshes,3);
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', harness + script[start:end] + checks], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for directory switching tests')
    def test_directory_switch_keeps_source_selection_and_only_loads_delivery(self):
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        start = script.index('  function setDirectoryMode(')
        end = script.index('  function renderPublishedDirectory(', start)
        harness = r'''
const assert = require('node:assert/strict');
const state = {selectedLibrary:'A', selectedVersion:{version_id:'v2'}, publishedRequestId:0, publishedQuery:'NL', libraryQuery:'A'};
const nodes = new Map();
const $ = id => { if (!nodes.has(id)) nodes.set(id,{classList:{toggle(){}},setAttribute(){},value:'',textContent:''}); return nodes.get(id); };
const document = {body:{classList:{toggle(){}}}};
let reads = 0;
const renderLibraries = () => {};
const updateRouteState = () => {};
const loadPublishedDetail = () => {reads++;};
'''
        checks = r'''
setDirectoryMode('published');
assert.equal($('library-filter').value,'NL');
assert.equal(reads,1);
setDirectoryMode('source');
assert.equal($('library-filter').value,'A');
assert.equal(state.selectedLibrary,'A');
assert.equal(state.selectedVersion.version_id,'v2');
assert.equal(reads,1);
'''
        result = subprocess.run(['node', '-e', harness + script[start:end] + checks], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for result rendering tests')
    def test_release_set_compare_lists_actual_library_changes(self) -> None:
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        start = script.index('  function releaseSetCompareText(')
        end = script.index('  async function compareReleaseSet(', start)
        harness = r'''
const assert = require('node:assert/strict');
const escapeHtml = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
'''
        checks = r'''
const html = releaseSetCompareHtml({summary:{changed_libraries:3},libraries:[
 {library_id:'A',action:'CHANGE_EFFECTIVE',old_effective_id:'old',new_effective_id:'new'},
 {library_id:'B',action:'ADD_LIBRARY',new_effective_id:'b1'},
 {library_id:'C',action:'REMOVE_LIBRARY',old_effective_id:'c1'},
 {library_id:'D',action:'KEEP_LIBRARY',old_effective_id:'d1',new_effective_id:'d1'},
 {library_id:'<script>',action:'UNRECOGNIZED'}]},'/tmp/<result>.json');
for (const text of ['组合变化','新增库','移出清单','保持','待核查','old','new','&lt;script&gt;','&lt;result&gt;']) assert.ok(html.includes(text),text);
assert.ok(html.includes('<table'));
assert.ok(html.includes('release-set-compare-wrap'));
assert.ok(!html.includes('<script>'));
assert.ok(releaseSetCompareHtml({libraries:[]},'').includes('没有库级对比明细'));
'''
        result = subprocess.run(['node', '-e', harness + script[start:end] + checks], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_workspaces_have_one_owner_for_analysis_delivery_and_settings(self) -> None:
        template = (ROOT / 'src/lib_guard/web/templates/index.html').read_text()
        self.assertIn('<strong>库与版本</strong>', template)
        self.assertIn('<strong>版本分析</strong>', template)
        self.assertIn('<strong>发布交付</strong>', template)
        self.assertNotIn('data-stage-target="evidence-workspace"', template)
        self.assertNotIn('data-stage-target="management-workspace"', template)
        delivery = template.split('id="release-workspace"', 1)[1].split('id="management-workspace"', 1)[0]
        for element in ('release-action-button', 'release-plan-result', 'formal-release-library-panel', 'release-set-panel'):
            self.assertIn(f'id="{element}"', delivery)
        settings = template.split('id="management-workspace"', 1)[1]
        self.assertNotIn('id="formal-release-library-panel"', settings)
        self.assertIn('id="rollback-to"', settings)
        self.assertIn('id="workspace-settings-button"', template)
        self.assertIn('id="scan-settings-heading"', template.split('id="action-workspace"', 1)[1].split('id="release-workspace"', 1)[0])
        ids = re.findall(r'\bid="([^"]+)"', template)
        self.assertEqual(len(ids), len(set(ids)), 'Controls must not be duplicated when moved')

    def test_workspace_content_matches_user_judgement_boundaries(self) -> None:
        template = (ROOT / 'src/lib_guard/web/templates/index.html').read_text()
        library_workspace = template.split('id="version-workspace"', 1)[1].split('id="action-workspace"', 1)[0]
        analysis_workspace = template.split('id="action-workspace"', 1)[1].split('id="release-workspace"', 1)[0]
        delivery_workspace = template.split('id="release-workspace"', 1)[1]

        self.assertNotIn('id="current-effective-stack"', library_workspace)
        self.assertNotIn('id="effective-selection-body"', library_workspace)
        self.assertNotIn('id="semantic-review-heading"', library_workspace)
        self.assertNotIn('class="object-maintenance"', library_workspace)
        self.assertIn('id="semantic-review-heading"', analysis_workspace)
        self.assertIn('id="current-effective-stack"', delivery_workspace)
        self.assertIn('id="effective-selection-body"', delivery_workspace)
        self.assertIn('id="accept-window-button"', delivery_workspace)
        settings_workspace = template.split('id="management-workspace"', 1)[1]
        self.assertIn('class="object-maintenance"', settings_workspace)
        self.assertIn('总目录报告', template)
        self.assertIn('当前有效版本未设置', template)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for workspace navigation tests')
    def test_workspace_switch_preserves_selection_and_groups_analysis_panels(self) -> None:
        script = (ROOT / 'src/lib_guard/web/static/app.js').read_text()
        start = script.index('  function setActiveStageTab(')
        end = script.index('  function scrollToStage(', start)
        harness = r'''
const assert = require('node:assert/strict');
const state = {selectedLibrary:'A', selectedVersion:{version_id:'v2'}, workspaceTab:'changes'};
const STAGE_IDS = ['version-workspace','action-workspace','release-workspace','management-workspace'];
const nodes = new Map();
const $ = id => {
 if (!nodes.has(id)) nodes.set(id, {attrs:{}, hidden:false, classList:{toggle(name, flag){nodes.get(id).hidden=flag;},remove(){}},setAttribute(name,value){this.attrs[name]=value;}});
 return nodes.get(id);
};
const tabs=STAGE_IDS.slice(0,3).map(id=>({dataset:{stageTarget:id},attrs:{},classList:{toggle(){},remove(){}},setAttribute(name,value){this.attrs[name]=value;},getAttribute(name){return this.attrs[name] || 'false';}}));
const document={querySelectorAll:()=>tabs};
const updateRouteState=()=>{};
const selectAnalysisAction=()=>{};
'''
        checks = r'''
setActiveStageTab('evidence-workspace');
assert.equal(state.activeStage,'action-workspace');
assert.equal($('evidence-workspace').hidden,false);
assert.equal($('release-workspace').hidden,true);
setActiveStageTab('release-workspace');
assert.equal($('evidence-workspace').hidden,true);
assert.equal($('action-workspace').hidden,true);
assert.equal($('release-workspace').hidden,false);
setActiveStageTab('management-workspace');
assert.equal($('workspace-settings-button').attrs['aria-expanded'],'true');
assert.equal(state.selectedVersion.version_id,'v2');
assert.equal(state.workspaceTab,'changes');
assert.equal(state.selectedLibrary,'A');
'''
        result = subprocess.run(['node', '-e', harness + script[start:end] + checks], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
    @unittest.skipUnless(shutil.which("node"), "Node is required for release summary behavior tests")
    def test_release_pyramid_summary_and_filters_do_not_invent_success(self) -> None:
        script = (ROOT / "src/lib_guard/web/static/app.js").read_text()
        start = script.index("  function releaseLinkAction(")
        end = script.index("  function renderReleasePlanResult(", start)
        checks = r'''
const assert = require('node:assert/strict');
const rows = [
 {status:'WOULD_KEEP',file_type:'lef',relative_path:'LEF/a.lef'},
 {status:'WOULD_REPLACE',file_type:'lef',relative_path:'LEF/b.lef',previous_target:'/old/b'},
 {status:'FAILED',file_type:'gds',relative_path:'GDS/c.gds',error:'missing source'}];
assert.deepEqual(filterReleaseLinks(rows, '', '', 'focus').map(x=>x.relative_path), ['LEF/b.lef','GDS/c.gds']);
assert.equal(filterReleaseLinks(rows, 'gds', 'gds', 'all').length, 1);
assert.equal(filterReleaseLinks(rows, '', '', 'same').length, 1);
assert.equal(releaseLinkAction({status:'LINKED',link_action:'REPLACE'}), 'replace');
assert.equal(releaseLinkAction({status:'LINKED'}), 'unknown');
assert.match(releaseResultHeadline({dry_run:true,status:'DRY_RUN',planned_files:3}), /未发布/);
assert.match(releaseResultHeadline({dry_run:false,status:'APPLIED',verify_status:'PASS',planned_files:3}), /已发布/);
assert.match(releaseResultHeadline({dry_run:false,status:'FAILED',verify_status:'FAILED',planned_files:3}), /未完成/);
assert.doesNotMatch(releaseResultHeadline({dry_run:false,status:'APPLIED',verify_status:'未执行'}), /校验通过/);
assert.doesNotMatch(releaseResultHeadline({dry_run:true,status:'DRY_RUN'}), /0 个/);
assert.match(releaseCsvCell('=CMD()'), /^"\t/);
assert.equal(releaseCsvCell('a"b'), '"a""b"');
'''
        result = subprocess.run(["node", "-e", script[start:end] + checks], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
    @unittest.skipUnless(shutil.which("node"), "Node is required for selection behavior tests")
    def test_release_set_empty_selection_and_filter_are_preserved(self) -> None:
        script = (ROOT / "src/lib_guard/web/static/app.js").read_text(encoding="utf-8")
        start = script.index("  function releaseSetLibraryAvailable(")
        end = script.index("\n  function ", script.index("  function renderReleaseSetWorkbench()") + 5)
        harness = r'''
const elements = new Map();
function $(id) {
  if (!elements.has(id)) elements.set(id, {value: id === 'release-set-availability' ? 'all' : '', querySelectorAll: () => [], innerHTML: '', textContent: ''});
  return elements.get(id);
}
const state = {libraries: [
 {library_name:'A', current_effective:'v1'},
 {library_name:'B', current_effective_stack:{available:true, current_effective_id:'v2'}},
 {library_name:'C'}], selectedReleaseSetLibraries:new Set(), activeAction:null};
const currentEffectiveStack = item => item.current_effective_stack || {};
const escapeHtml = text => String(text);
const libraryMetaLine = () => '';
'''
        assertions = r'''
const assert = require('node:assert/strict');
renderReleaseSetWorkbench();
assert.equal(state.selectedReleaseSetLibraries.size, 0);
assert.equal($('release-set-build').disabled, true);
state.selectedReleaseSetLibraries.add('B');
$('release-set-filter').value = 'A';
renderReleaseSetWorkbench();
assert.match($('release-set-selection-summary').textContent, /筛选外 1/);
assert.deepEqual(visibleReleaseSetLibraries().map(x => x.library_name), ['A']);
$('release-set-filter').value = '';
$('release-set-availability').value = 'missing';
renderReleaseSetWorkbench();
assert.deepEqual(visibleReleaseSetLibraries().map(x => x.library_name), ['C']);
assert.equal($('select-visible-release-set').disabled, true);
state.selectedReleaseSetLibraries.clear();
renderReleaseSetWorkbench();
assert.equal(state.selectedReleaseSetLibraries.size, 0);
assert.equal($('release-set-build').disabled, true);
state.libraries[1].current_effective_stack.available = false;
state.libraries[1].current_effective = 'stale-id';
state.selectedReleaseSetLibraries.add('B');
renderReleaseSetWorkbench();
assert.match($('release-set-selection-summary').textContent, /已选 0（筛选外 0）/);
assert.equal(state.selectedReleaseSetLibraries.has('B'), false);
assert.equal($('release-set-build').disabled, true);
assert.ok($('release-set-library-body').innerHTML.includes('data-release-set-setup="B"'));
assert.equal(releaseSetLibraryAvailable({current_effective_stack:{available:false},current_effective:'stale'}),false);
assert.equal(releaseSetLibraryAvailable({current_effective:'legacy'}),true);
$('release-set-availability').value='all';
state.activeAction='release-set-compare';
renderReleaseSetWorkbench();
assert.match($('release-set-library-body').innerHTML, /data-release-set-library="A" type="checkbox"\s+disabled/);
assert.equal($('release-set-compare').disabled,true);
'''
        result = subprocess.run(["node", "-e", harness + script[start:end] + assertions], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_table_selection_controls_are_explicit_and_do_not_reselect_empty_sets(self) -> None:
        template = (ROOT / "src/lib_guard/web/templates/index.html").read_text(encoding="utf-8")
        script = (ROOT / "src/lib_guard/web/static/app.js").read_text(encoding="utf-8")
        for control in ("registered-library-filter", "release-set-filter", "release-set-availability",
                        "select-visible-release-set", "clear-release-set", "release-set-selection-summary",
                        "candidate-select-all", "reset-candidate-filters"):
            self.assertIn(f'id="{control}"', template)
        self.assertNotIn("if (!state.selectedReleaseSetLibraries.size && state.libraries.length)", script)
        self.assertIn("indeterminate", script)

    def test_formal_release_library_panel_is_query_only_and_keeps_history_visible(self) -> None:
        template = (ROOT / "src" / "lib_guard" / "web" / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "src" / "lib_guard" / "web" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="formal-release-library-panel"', template)
        self.assertIn('id="formal-release-root"', template)
        self.assertIn('id="refresh-formal-release-libraries"', template)
        self.assertIn('id="formal-release-library-table-body"', template)
        self.assertIn('/api/release-libraries', script)
        self.assertIn('/api/release-libraries/refresh', script)
        self.assertIn('/preview-overwrite', script)
        self.assertIn('release-overwrite-preview', script)
        self.assertIn('data-action="release-apply"', template)
        self.assertIn('id="release-apply-action-button"', template)
        self.assertIn("if (!window.confirm(message))", script)

    def test_home_action_deck_exposes_parallel_version_actions_with_scoped_forms(self) -> None:
        template = (ROOT / "src" / "lib_guard" / "web" / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "src" / "lib_guard" / "web" / "static" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "src" / "lib_guard" / "web" / "static" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="action-workspace"', template)
        self.assertIn('aria-label="版本分析"', template)
        self.assertLess(template.index('id="action-workspace"'), template.index('id="evidence-workspace"'))
        self.assertIn(">打开版本详情页<", template)
        self.assertIn("版本更新备注", template)
        self.assertIn('aria-label="版本备注摘要"', template)
        self.assertIn('id="update-note-summary"', template)
        self.assertIn('id="save-update-note-draft"', template)
        self.assertIn('id="publish-update-note"', template)
        self.assertNotIn('id="select-version-button"', template)
        for action_id, label in (
            ("scan-action-button", "扫描"),
            ("compare-action-button", "对比"),
            ("open-file-diff", "深度文件对比"),
            ("open-review-actions", "审查记录"),
            ("release-action-button", "检查正式发布条件"),
            ("release-plan-action-button", "生成发布预演"),
        ):
            self.assertIn(f'id="{action_id}"', template)
            self.assertIn(label, template)
        self.assertIn('id="file-diff-relpath"', template)
        self.assertIn('id="file-diff-old-file"', template)
        self.assertIn('id="file-diff-new-file"', template)
        self.assertIn('id="run-explicit-file-diff"', template)
        self.assertIn('id="review-gate-operation"', template)
        self.assertIn('id="review-packet-operation"', template)
        self.assertIn('id="release-alias"', template)
        self.assertIn('id="release-link-mode"', template)
        self.assertIn('id="release-overwrite"', template)
        self.assertIn('id="release-force-action-button"', template)
        self.assertIn('id="release-force-reason"', template)
        self.assertIn('id="release-force-by"', template)
        self.assertIn('id="release-force-acknowledged"', template)
        self.assertIn("受控强制发布", template)
        self.assertIn("release-plan", script)
        self.assertIn("release_plan", script)
        self.assertIn("release-force", script)
        self.assertIn("/force-overwrite", script)
        for element_id in (
            "scan-action-button",
            "compare-action-button",
            "release-action-button",
            "review-gate-operation",
            "review-packet-operation",
            "review-owner",
            "reviewer",
            "review-id",
            "review-decision",
            "review-note",
        ):
            self.assertEqual(template.count(f'id="{element_id}"'), 1, element_id)
        self.assertNotIn('<h4>手动文件核对</h4>', template)
        self.assertNotIn('<h4>审查记录与有效组合</h4>', template)
        self.assertIn("openFileDiffWorkbench", script)
        self.assertIn("runExplicitFileDiff", script)
        self.assertIn("old_file", script)
        self.assertIn("new_file", script)
        self.assertIn("openReviewActions", script)
        self.assertNotIn("const COMMAND_LABELS =", script)
        self.assertIn("function commandLabel(action)", script)
        self.assertIn("workspace?.web_actions", script)
        self.assertIn("loadUpdateNoteForSelectedVersion", script)
        self.assertIn("await loadUpdateNoteForSelectedVersion()", script)
        self.assertIn("saveUpdateNote", script)
        self.assertIn("update-note", script)
        self.assertIn("count <= 8", script)
        self.assertNotIn("depth < 1 ? 'open'", script)
        self.assertIn("action-deck-grid", styles)
        self.assertIn("action-card", styles)
        self.assertIn("version-note-workbench", styles)
        self.assertIn('class="semantic-review-card"', template)
        self.assertIn('id="semantic-review-heading"', template)
        self.assertNotIn("接入与有效版", template)
        self.assertIn("新版本接入", template)
        self.assertIn("读取已保存建议", template)
        self.assertIn("预览处理计划", template)
        self.assertIn("生成待确认候选", template)
        self.assertIn("确认并设为当前有效", template)
        self.assertNotIn("接入窗口", template)
        self.assertNotIn("下一步预演", template)
        self.assertNotIn("接受候选有效版", template)
        self.assertIn(".action-deck-grid { display: grid; grid-template-columns: minmax(0, 1fr); align-items: start; gap: 10px;", styles)
        self.assertIn('.action-deck-grid > [hidden] { display: none; }', styles)

    def test_new_library_intake_has_a_short_safe_path(self) -> None:
        template = (ROOT / "src" / "lib_guard" / "web" / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "src" / "lib_guard" / "web" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="workspace-setup-panel"', template)
        self.assertIn('id="setup-workspace"', template)
        self.assertIn('id="setup-raw-root"', template)
        self.assertIn('id="setup-create-config"', template)
        self.assertIn("/api/workspace/init", script)
        self.assertIn("renderWorkspaceSetup", script)
        self.assertIn('id="library-add-apply" type="checkbox" checked', template)
        self.assertIn('id="library-add-refresh" type="checkbox" checked', template)
        self.assertIn("登记并加入目录", template)
        self.assertIn("同名已登记库会替换旧库根", template)
        self.assertIn("重新发现候选库", template)
        self.assertIn("读取上次结果", template)
        self.assertIn("修改库名 / 库根", script)
        self.assertIn("prefillLibraryAddFromCandidate", script)
        self.assertIn("loadLibraries(preferredLibrary = '')", script)
        self.assertIn("completedJob?.registeredLibrary", script)
        self.assertIn("registeredLibrary: action === 'library-add' ? payload.library_id : ''", script)
        self.assertIn('id="library-add-feedback"', template)
        self.assertIn("showLibraryAddFeedback", script)

    def test_desktop_console_defers_inactive_evidence_and_supports_skip_navigation(self) -> None:
        template = (ROOT / "src" / "lib_guard" / "web" / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "src" / "lib_guard" / "web" / "static" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "src" / "lib_guard" / "web" / "static" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('<a class="skip-link" href="#workspace-main">跳到主内容</a>', template)
        self.assertIn('<main id="workspace-main" class="workspace" tabindex="-1">', template)
        self.assertIn(".skip-link", styles)
        self.assertIn(".button-small { min-height: 32px;", styles)
        self.assertIn(".workflow-context-item span { color: var(--muted); font-size: 11px;", styles)
        self.assertIn(".version-link { min-height: 32px;", styles)
        self.assertIn(".zone-kicker { display: block; color: var(--teal); font-size: 11px;", styles)
        self.assertIn("font-size: 11px; font-weight: 850; white-space: nowrap;", styles)
        self.assertIn("font-size: 11px; font-weight: 800;", styles)
        self.assertIn('title="${escapeHtml(item.library_name)}"', script)
        self.assertIn("fileChangesLoadedKey", script)
        self.assertIn("fileTreeLoadedKey", script)
        self.assertIn("refreshActiveEvidenceForSelectedVersion", script)
        self.assertIn("切换到“变化清单”后读取对比证据", script)
        self.assertIn("切换到“文件结构”后读取扫描清单", script)
        self.assertIn("暂无文件变化证据", script)
        self.assertIn("main?.focus()", script)
        self.assertIn("data-retry-file-tree", script)
        self.assertIn("data-retry-file-changes", script)
        self.assertNotIn("await Promise.all([\n      refreshFileChangesForSelectedVersion(requestId),\n      refreshFileTreeForSelectedVersion(requestId),\n    ]);", script)

    def test_desktop_shell_has_bounded_chinese_workbench_sections(self) -> None:
        template = (ROOT / "src" / "lib_guard" / "web" / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "src" / "lib_guard" / "web" / "static" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "src" / "lib_guard" / "web" / "static" / "styles.css").read_text(encoding="utf-8")

        for label in (
            "库目录",
            "版本列表",
            "库接入与候选库",
            "事实状态",
            "当前有效版本",
            "生成处理建议",
            "生成处理计划",
            "运行与默认配置",
            "工作区默认值",
            "工作区默认值",
            "默认原始库根",
            "最少版本数",
            "保存目录",
            "保存扫描默认值",
            "保存发现默认值",
            "扫描证据",
            "证据读取",
            "版本对比",
            "页面输出",
            "扫描或对比后刷新版本详情页",
            "完整内容证据会读取文件内容，可能明显变慢",
            "仅生成扫描和对比事实，不刷新页面",
            "版本配置与组合",
            "确认并设为当前有效",
            "版本概览",
            "当前版本上下文",
            "当前版本处理范围",
            "运行反馈",
            "版本分析",
            "文件核对",
            "变化清单",
            "库与版本",
            "发布交付",
            "配置与维护",
            "策略与例外",
            "新版本接入",
            "新库接入",
            "已登记库与候选库",
            "查看全部工作清单",
            "发现候选库",
            "候选库",
            "登记已选库",
            "勾选筛选结果",
            "高级搜索限制",
            "应用并刷新目录",
            "深度文件对比",
            "文件结构",
            "复制源路径",
            "复制所选路径",
            "选择筛选结果",
            "清空选择",
            "变化类型",
            "视图类型",
            "运行文件级对比",
            "审查门禁",
            "审查记录包",
            "回退当前有效版本",
            "执行预定义动作",
            "浏览目录",
            "使用当前目录",
        ):
            self.assertIn(label, script if label in ("新版本待扫", "基准待扫", "当前版补证据") else template)
        self.assertIn('class="settings-disclosure panel"', template)
        self.assertIn('class="settings-section"', template)
        self.assertIn('class="workspace-heading-main"', template)
        self.assertIn("job-log-details", template)
        self.assertNotIn('class="job-log-details" open', template)
        self.assertIn('id="catalog-full"', template)
        self.assertIn('id="reviewer"', template)
        self.assertIn("action-card-workflow", template)
        self.assertIn("新版本接入", template)
        self.assertIn("action-deck", template)
        self.assertIn('class="control-zone stage-anchor hidden"', template)
        self.assertIn('class="primary-stage-tabs" role="tablist"', template)
        self.assertLess(template.index('class="primary-stage-tabs"'), template.index('class="workspace-heading"'))
        self.assertIn('class="workflow-context sr-only"', template)
        self.assertIn('id="action-workspace" class="panel action-deck stage-anchor hidden"', template)
        self.assertIn('id="evidence-workspace" class="content-grid stage-anchor hidden"', template)
        self.assertIn('class="pinned-workbench"', template)
        self.assertIn('id="run-workspace" class="runtime-dock runtime-strip"', template)
        self.assertNotIn('id="run-workspace" class="panel run-panel stage-anchor hidden"', template)
        self.assertIn('data-stage-target="version-workspace"', template)
        self.assertIn('data-stage-target="action-workspace"', template)
        self.assertIn('data-stage-target="release-workspace"', template)
        self.assertNotIn('data-stage-target="run-workspace"', template)
        self.assertIn('id="workspace-settings-button"', template)
        self.assertIn('aria-label="版本分析"', template)
        self.assertIn('class="object-maintenance"', template)
        self.assertIn('id="flow-object-value"', template)
        self.assertIn('id="flow-facts-value"', template)
        self.assertIn('id="metric-effective"', template)
        self.assertIn('id="flow-release-value"', template)
        self.assertIn('class="inline-action-details"', template)
        self.assertIn('aria-label="有效组合与版本接入"', template)
        self.assertIn('colspan="7"', template)
        self.assertIn('id="registered-library-table-body"', template)
        self.assertIn('class="file-tree-filter-group"', template)
        self.assertIn('class="file-tree-action-group"', template)
        self.assertIn("版本列表", template)
        for label in ("当前关注", "全部历史", "新版本待扫", "基准待扫", "当前版补证据", "待对比", "可审查", "当前有效", "发布待确认", "异常", "待扫描"):
            self.assertIn(label, script)
        for label in (
            "待处理优先",
            "最新版本优先",
            "最旧版本优先",
            "当前有效优先",
            "包类型",
            "对比基准",
            '<th scope="col">扫描</th>',
            '<th scope="col">对比</th>',
            '<th scope="col">发布检查</th>',
            "所选版本操作",
        ):
            self.assertIn(label, template)
        self.assertIn('id="version-sort"', template)
        self.assertIn('id="version-status-facets"', template)
        self.assertIn("version-table-shell", template)
        self.assertIn("pinned-version-board", template)
        self.assertIn("pinned-version-table-shell", template)
        self.assertIn("versionFacetCounts", script)
        self.assertIn("renderVersionFacets", script)
        self.assertIn("sortVersionsForDisplay", script)
        self.assertIn("data-version-facet", script)
        self.assertIn("library-item-signals", script)
        self.assertIn("基准待扫", script)
        self.assertIn("最新", script)
        self.assertIn(".version-status-facets", styles)
        self.assertIn(".library-item-signals", styles)
        self.assertIn('class="version-focus-strip"', template)
        self.assertIn('id="version-focus-target"', template)
        self.assertIn('id="version-focus-base"', template)
        self.assertIn('id="version-focus-effective"', template)
        self.assertIn('id="version-focus-facts"', template)
        self.assertIn("versionEvidenceChips", script)
        self.assertIn("version-base-label", script)
        self.assertIn("versionRoleLabel", script)
        self.assertIn('data-version-focus-action="open"', template)
        self.assertIn('data-version-focus-action="scan"', template)
        self.assertIn('data-version-focus-action="compare"', template)
        self.assertIn("发布待确认", script)
        self.assertIn("待扫描", script)
        self.assertIn("待对比", script)
        self.assertIn("可审查", script)
        self.assertIn("version-evidence-stack", styles)
        self.assertIn("版本分析", template)
        self.assertIn('id="analysis-next-step"', template)
        self.assertIn("id=\"action-workspace\"", template)
        self.assertIn("id=\"registered-library-table-body\"", template)
        self.assertIn("已登记库", template)
        self.assertIn("候选库", template)
        self.assertIn("data-force-hash-type", template)
        self.assertIn("data-skip-hash-type", template)
        self.assertIn("deriveVersionTask", script)
        self.assertIn("renderRegisteredLibraries", script)
        self.assertIn("force_hash_file_types", script)
        self.assertIn("skip_hash_file_types", script)
        self.assertIn("renderActionDeckReadiness", script)
        self.assertIn("openVersionDetail", script)
        self.assertIn("待确认候选", script)
        self.assertNotIn("候选有效组合';", script)

    def test_effective_stack_and_release_set_have_visible_web_entrypoints(self) -> None:
        template = (ROOT / "src" / "lib_guard" / "web" / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "src" / "lib_guard" / "web" / "static" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "src" / "lib_guard" / "web" / "static" / "styles.css").read_text(encoding="utf-8")

        for label in (
            "当前有效组合",
            "完整包基线",
            "叠加更新",
            "来源",
            "待确认候选",
            "比较当前与候选",
            "多库发布组合",
            "生成多库组合清单",
            "比较两个组合清单",
            "生成和比较清单不创建发布链接",
            "预演 / 实际创建链接",
        ):
            self.assertIn(label, template)
        for element_id in (
            "current-effective-stack",
            "current-effective-source",
            "current-effective-base",
            "current-effective-overlays",
            "candidate-effective-stack",
            "compare-current-candidate",
            "release-set-panel",
            "release-set-library-body",
            "release-set-id",
            "release-set-plan",
            "release-set-apply",
            "release-set-publish-name",
            "release-stage-body",
            "release-set-note",
            "release-set-build",
            "release-set-old-manifest",
            "release-set-new-manifest",
            "release-set-compare",
            "release-set-result",
        ):
            self.assertIn(f'id="{element_id}"', template)
        for symbol in (
            "renderEffectiveStack",
            "renderReleaseSetWorkbench",
            "buildReleaseSet",
            "compareReleaseSet",
            "/api/release-set/build",
            "/api/release-set/compare",
            "current_effective_stack",
            "candidate_effective_stack",
        ):
            self.assertIn(symbol, script)
        for selector in (
            ".effective-stack-panel",
            ".effective-comparison-grid",
            ".release-set-panel",
            ".release-set-table",
            ".release-set-result",
        ):
            self.assertIn(selector, styles)
        self.assertIn("scanFactLabel", script)
        self.assertIn("compareFactLabel", script)
        self.assertIn("扫描记录缺证据", script)
        self.assertIn("对比记录待验证", script)
        self.assertIn("需补扫", script)
        self.assertIn("const hasSuggestion", script)
        self.assertIn("workflowAction === 'window'", script)
        self.assertIn("当前还没有接入建议，请先生成处理建议。", script)
        self.assertIn("计划预览已完成", script)
        self.assertIn("执行并生成候选", script)
        self.assertNotIn("runReviewSequence", script)
        self.assertIn("loadLibraryCandidates", script)
        self.assertIn("selectedCandidateIds", script)
        self.assertIn("candidate_ids", script)
        self.assertIn("候选库表中勾选至少一个确认的库根", script)
        self.assertIn("candidate-table-wrap", styles)
        self.assertIn("max-height: 300px", styles)
        self.assertNotIn('data-command-action="library-accept"', template)
        self.assertIn("result.result_summary", script)

    def test_library_rail_has_asset_filters_and_dense_metadata(self) -> None:
        template = (ROOT / "src" / "lib_guard" / "web" / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "src" / "lib_guard" / "web" / "static" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "src" / "lib_guard" / "web" / "static" / "styles.css").read_text(encoding="utf-8")

        for element_id in (
            "library-scope-filter",
            "library-kind-filter",
            "library-vendor-filter",
            "library-platform-filter",
            "library-facet-summary",
        ):
            self.assertIn(f'id="{element_id}"', template)
        for label in (
            "全部库",
            "需处理库",
            "发布待确认",
            "无当前有效",
            "候选待登记",
            "库类型",
            "厂商",
            "平台",
        ):
            self.assertIn(label, template)
        for symbol in (
            "libraryScopeCounts",
            "populateLibraryFilters",
            "libraryMatchesFilters",
            "renderLibraryFacetSummary",
            "libraryKindLabel",
            "libraryPlatformLabel",
            "library-meta-line",
        ):
            self.assertIn(symbol, script)
        for selector in (
            ".library-filter-grid",
            ".library-facet-summary",
            ".library-meta-line",
        ):
            self.assertIn(selector, styles)

    def test_library_management_is_presented_as_path_to_intake_flow(self) -> None:
        template = (ROOT / "src" / "lib_guard" / "web" / "templates" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "src" / "lib_guard" / "web" / "static" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "src" / "lib_guard" / "web" / "static" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("库管理", template)
        self.assertIn("新库接入", template)
        self.assertIn("从库路径到版本处理", template)
        self.assertIn('class="library-intake-playbook"', template)
        self.assertIn('data-ui-action="open-library-add"', template)
        self.assertLess(template.index("version-focus-strip"), template.index("新库接入"))
        self.assertLess(template.index('id="registered-library-heading"'), template.index('id="candidate-discover-root"'))
        self.assertLess(template.index('id="candidate-discover-root"'), template.index('id="library-add-disclosure"'))
        for label in (
            "已登记库",
            "重新发现候选库",
            "应用并刷新目录",
            "手动添加库（补充）",
            "库属性（可登记）",
            "登记后自动应用并刷新目录",
            "发现路径",
            "建议已登记库名",
            "核对库根和版本",
        ):
            self.assertIn(label, template)
        self.assertIn("openLibraryAddForm", script)
        self.assertIn("focusVersionActions", script)
        self.assertIn("candidate-discover-root", script)
        self.assertIn("suggested_library_id", script)
        self.assertIn("data-ui-action", script)
        self.assertIn("scrollToStage('version-workspace')", script)
        self.assertIn(".library-intake-playbook", styles)
        self.assertIn(".command-action-strip", styles)
        self.assertIn("PASS_WITH_WARNING: '正式发布通过（有提醒）'", script)
        self.assertIn("选择版本后可以独立执行扫描、对比、深度文件核对、审查记录和发布检查。", script)
        self.assertIn("检查正式发布条件", template)
        self.assertIn("无可比基准", script)
        self.assertNotIn("建议动作</th>", template)
        self.assertNotIn("按当前基准依次执行扫描、对比、发布检查", template)
        self.assertIn("运行与默认配置", template)
        self.assertIn("scan-action-note", template)
        for action in (
            "worklist",
            "catalog-refresh",
            "library-discover",
            "library-apply",
            "library-add",
            "file-diff",
            "review-gate",
            "review-packet",
            "effective-rollback",
            "action-file",
        ):
            self.assertIn(f'data-command-action="{action}"', template)
        self.assertIn("runCommand('library-accept')", script)
        self.assertIn("data-command-action", script)
        self.assertIn("正式发布待处理", script)
        self.assertIn("releaseChip", script)
        self.assertIn("不代表 IP 使用失败", script)
        for element_id in ("job-observation", "job-stage", "job-percent", "job-elapsed", "job-progress-bar", "job-log-tail"):
            self.assertIn(f'id="{element_id}"', template)
        self.assertIn('id="open-file-diff"', template)
        self.assertIn('id="open-review-actions"', template)
        self.assertIn('id="job-artifacts"', template)
        self.assertIn('class="action-deck-grid"', template)
        self.assertIn('id="base-version-options"', template)
        self.assertIn("renderJobObservation", script)
        self.assertIn("renderJobArtifacts", script)
        self.assertIn("has-live-job", script)
        self.assertIn("runtime-summary", template)
        self.assertIn(".pinned-workbench", styles)
        self.assertIn(".runtime-strip", styles)
        self.assertIn("updateSettingsSummary", script)
        self.assertIn("flow-facts-value", script)
        self.assertNotIn("flow-decision-value", template + script)
        self.assertIn("扫描 ${scanFactLabel", script)
        self.assertNotIn("versionStageStrip", script)
        self.assertNotIn("version-stage-strip", styles)
        self.assertIn("终端输出", template)
        self.assertIn("发布待确认", template)
        self.assertNotIn('data-sequence-step="release-check"', template)
        self.assertNotIn("第 3 步 / 3：发布检查", script)
        self.assertIn("读取中", script)
        self.assertIn("失败原因：", script)
        self.assertIn("当前显示", script)
        self.assertIn("VERSION_RENDER_BATCH", script)
        self.assertIn("versionRenderLimit", script)
        self.assertIn("再显示 ${VERSION_RENDER_BATCH} 个", script)
        self.assertIn("继续读取版本", script)
        self.assertIn("filteredVersions", script)
        self.assertIn("if (selectedChanged) resetSelectedVersionEvidence();", script)
        self.assertNotIn("if (!append || selectedChanged) resetSelectedVersionEvidence();", script)
        self.assertIn("if (name === state.selectedLibrary && state.versions.length) {", script)
        self.assertIn("已保存计划无法读取", script)
        self.assertIn("先预览处理计划，再执行生成候选", script)
        self.assertIn("超过 30 分钟", script)
        self.assertIn('value="candidate"', template)
        self.assertIn("本次扫描设置", template)
        self.assertIn("已连接", script)
        self.assertIn("/api/libraries", script)
        self.assertIn("overflow", styles)
        self.assertIn('class="main-column"', template)
        self.assertIn(".main-column { min-width: 0; display: grid;", styles)
        self.assertIn(".side-stack { position: sticky;", styles)
        self.assertIn("max-height: calc(100vh - 92px);", styles)
        for element_id in ("file-change-body", "file-change-kind-filter", "file-change-type-filter", "linked-old-relpath", "linked-new-relpath", "linked-file-diff-button"):
            self.assertIn(f'id="{element_id}"', template)
        self.assertIn('id="file-change-page-summary"', template)
        self.assertIn('id="load-more-file-changes"', template)
        for element_id in ("library-path-picker", "path-browser-list", "path-browser-current"):
            self.assertIn(f'id="{element_id}"', template)
        self.assertIn("file-changes", script)
        self.assertIn("/api/path-children", script)
        self.assertIn("/file-tree", script)
        self.assertIn("selectedFileTreePaths", script)
        self.assertIn("buildFileTree", script)
        self.assertIn("scheduleFileTreeRender", script)
        self.assertIn("display_path", script)
        self.assertIn("file-tree-scroll", styles)
        self.assertIn(".workspace-tabs { display: flex;", styles)
        self.assertIn(".workspace-tab.is-active", styles)
        self.assertIn(".action-panel { min-width: 0; display: block;", styles)
        self.assertIn(".control-zone { margin-top: 24px;", styles)
        self.assertNotIn('class="metric-strip"', template)
        self.assertIn("activateWorkspaceTab", script)
        self.assertIn("fileChangeLimit: 100", script)
        self.assertIn("URLSearchParams", script)
        self.assertIn("history.replaceState", script)
        self.assertIn("fileChangeTotal", script)
        self.assertIn("fileChangeFacetCounts", script)
        self.assertIn("data-file-change-facet", script)
        self.assertIn('id="file-change-facets"', template)
        self.assertIn("文件变化总览", template)
        self.assertIn("show-settings-button", template)
        self.assertLess(template.index('class="primary-stage-tabs"'), template.index('id="version-workspace"'))
        self.assertLess(template.index('id="version-workspace"'), template.index('id="version-list-disclosure"'))
        self.assertLess(template.index('id="version-list-disclosure"'), template.index('class="pinned-workbench"'))
        self.assertLess(template.index('id="version-workspace"'), template.index('id="run-workspace"'))
        self.assertLess(template.index('id="version-workspace"'), template.index('id="action-workspace"'))
        self.assertLess(template.index('id="action-workspace"'), template.index('id="evidence-workspace"'))
        self.assertLess(template.index('id="version-workspace"'), template.index('class="panel evidence-workspace"'))
        self.assertLess(template.index('class="panel evidence-workspace"'), template.index('id="management-workspace"'))
        self.assertIn("old_relpath", script)
        self.assertIn("deep_diff_available", script)
        self.assertNotIn("!rows.some((item) => item.version_id === state.selectedVersion.version_id)", script)
        self.assertNotIn('<h3>当前版本</h3>', template)
        self.assertNotIn('<main class="workspace" aria-live="polite">', template)
        self.assertNotIn("run-shell", template + script)


if __name__ == "__main__":
    unittest.main()
