import unittest
from ai_lib_qor.checks.registry import REGISTRY, resolve_plugins
from ai_lib_qor.checks.runner import run_contributions

class PluginRunnerTests(unittest.TestCase):
    def test_registered_plugin_runs_in_order(self):
        def first(ctx): return {'quality_checks':[{'check_id':'first'}]}
        def second(ctx): return {'quality_checks':[{'check_id':'second'}]}
        registry={'A':first,'B':second}
        result=run_contributions(['B','A'], {'scope':'test'}, registry)
        self.assertEqual([item['check_id'] for item in result['quality_checks']],['second','first'])
    def test_unknown_or_duplicate_plugin_is_rejected(self):
        for names in (['UNKNOWN'],['LEF_MACRO_DIFF','LEF_MACRO_DIFF']):
            with self.assertRaises(ValueError): resolve_plugins(names, REGISTRY)
    def test_bad_contribution_is_not_silently_discarded(self):
        with self.assertRaises(ValueError): run_contributions(['BAD'],{}, {'BAD':lambda ctx:{'future_field':42}})

    def test_cli_plan_automatic_pairing_and_plugin_selection(self):
        import json, tempfile
        from pathlib import Path
        from argparse import Namespace
        from ai_lib_qor.__main__ import run
        root=Path(__file__).resolve().parents[1]
        plan=json.loads((root/'examples/pipeline/check_effective.example.json').read_text())
        for key in ('target_revision','baseline_revision'): plan[key]=str(root/plan[key])
        plan['formal_snapshots']=[str(root/p) for p in plan['formal_snapshots']]
        plan['comparisons']=[]; plan['pin_pairs']=[]
        plan['auto_pair_facts']=[{'file_key':'lib_rtavfs:lef:core','facts':str(root/'examples/file_facts/facts_core_v08.json')},{'file_key':'lib_rtavfs:liberty:func_tt','facts':str(root/'examples/file_facts/facts_tt_v08.json')}]
        plan['plugins']=['LEF_LIBERTY_PIN_MATCH']
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'plan.json';p.write_text(json.dumps(plan));out=Path(temp)/'check.json'
            run(Namespace(command='check',plan=str(p),out=str(out)))
            result=json.loads(out.read_text())
            self.assertEqual(result['quality_checks'][0]['result'],'PASS')
            self.assertEqual(result['file_changes'],[])
