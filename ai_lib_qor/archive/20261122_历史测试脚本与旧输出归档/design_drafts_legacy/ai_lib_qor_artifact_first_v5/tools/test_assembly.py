#!/usr/bin/env python3
import copy, tempfile, unittest
from pathlib import Path
import assemble_checks as engine

FIRST = ["content_compare", "macro_diff", "lef_liberty_alignment", "sta_setup_wns", "qor_gate"]

class CheckAssemblerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.first = engine.assemble("test_run_001", FIRST, [engine.load(x) for x in FIRST])

    def test_multiple_contributions_one_document(self):
        self.assertEqual(set(self.first['checks']), set(FIRST))
        self.assertEqual(self.first['summary']['overall_verdict'], 'INCOMPLETE')
        self.assertIsNone(self.first['checks']['macro_diff']['verdict'])

    def test_overall_not_pass_when_crossview_not_checked(self):
        self.assertEqual(self.first['checks']['lef_liberty_alignment']['verdict'], 'NOT_CHECKED')
        self.assertNotEqual(self.first['summary']['overall_verdict'], 'PASS')

    def test_incremental_new_plugin_new_run(self):
        ids=FIRST+['pin_count']
        nxt=engine.assemble('test_run_002',ids,[engine.load('qor_gate_stricter'),engine.load('pin_count')],self.first,{'content_compare','macro_diff','sta_setup_wns'},engine.current_reuse_specs({'content_compare','macro_diff','sta_setup_wns'}))
        self.assertEqual(len(nxt['checks']),6)
        self.assertEqual(nxt['summary']['overall_verdict'],'FAIL')
        self.assertEqual(nxt['checks']['macro_diff']['reused_from_run_id'],'test_run_001')
        self.assertEqual(self.first['checks']['qor_gate']['verdict'],'PASS')

    def test_duplicate_check_id_rejected(self):
        x=engine.load('content_compare')
        with self.assertRaisesRegex(ValueError,'collision'):
            engine.assemble('dup',FIRST,[x,x])

    def test_wrong_target_rejected(self):
        x=engine.load('macro_diff');x['target']['revision_id']='rev_wrong'
        with self.assertRaisesRegex(ValueError,'target'):
            engine.assemble('wrong',FIRST,[x])

    def test_unplanned_plugin_rejected(self):
        with self.assertRaisesRegex(ValueError,'unregistered'):
            engine.assemble('wrong',FIRST,[engine.load('pin_count')])

    def test_metric_must_not_claim_pass(self):
        x=engine.load('sta_setup_wns'); x['verdict']='PASS'
        with self.assertRaisesRegex(ValueError,'must not'):
            engine.assemble('wrong',FIRST,[x])

    def test_gate_must_have_measurement(self):
        with self.assertRaisesRegex(ValueError,'missing usable'):
            engine.assemble('wrong',FIRST,[engine.load('qor_gate')])

    def test_gate_must_reference_not_duplicate_measurement(self):
        gate=engine.load('qor_gate');gate['metrics']=[{'name':'setup_wns','value':-0.04,'unit':'ns'}]
        with self.assertRaisesRegex(ValueError,'must reference'):
            engine.assemble('wrong',FIRST,[engine.load('sta_setup_wns'),gate])

    def test_gate_threshold_matches_verdict(self):
        gate=engine.load('qor_gate');gate['parameters']['threshold']=-0.05
        with self.assertRaisesRegex(ValueError,'does not follow'):
            engine.assemble('wrong',FIRST,[engine.load('sta_setup_wns'),gate])

    def test_plugin_upgrade_invalidates_reuse(self):
        specs=engine.current_reuse_specs({'macro_diff'})
        specs['macro_diff']['implementation_version']='99.0.0'
        with self.assertRaisesRegex(ValueError,'stale cache'):
            engine.assemble('wrong',FIRST,[],self.first,{'macro_diff'},specs)

    def test_param_change_invalidates_reuse(self):
        specs=engine.current_reuse_specs({'content_compare'})
        specs['content_compare']['parameters']['comparison']='ADJACENT_REVISIONS'
        with self.assertRaisesRegex(ValueError,'stale cache'):
            engine.assemble('wrong',FIRST,[],self.first,{'content_compare'},specs)

    def test_no_implicit_reuse_of_unverified_check(self):
        ids=FIRST+['pin_count'];nxt=engine.assemble('test_run_002',ids,[engine.load('qor_gate_stricter'),engine.load('pin_count')],self.first,{'content_compare','macro_diff','sta_setup_wns'},engine.current_reuse_specs({'content_compare','macro_diff','sta_setup_wns'}))
        self.assertEqual(nxt['checks']['lef_liberty_alignment']['execution_status'],'NOT_RUN')
        self.assertEqual(nxt['checks']['lef_liberty_alignment']['verdict'],'NOT_CHECKED')

    def test_reusing_unfinished_check_rejected(self):
        with self.assertRaisesRegex(ValueError,'cannot reuse'):
            engine.assemble('wrong',FIRST,[],self.first,{'lef_liberty_alignment'},engine.current_reuse_specs({'lef_liberty_alignment'}))

    def test_published_output_immutable(self):
        with tempfile.TemporaryDirectory() as temp:
            original_out=engine.OUT
            try:
                engine.OUT=Path(temp)
                one=copy.deepcopy(self.first);one['run_id']='test_immutable'
                first_path=engine.publish(one)
                self.assertEqual(engine.publish(one),first_path)
                one['summary']['overall_verdict']='PASS'
                with self.assertRaises(FileExistsError):engine.publish(one)
            finally:engine.OUT=original_out

if __name__=='__main__':unittest.main(verbosity=2)
