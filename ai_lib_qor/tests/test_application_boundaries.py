"""Application use cases must be callable without command-line argument objects."""
import ast
import json
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class ApplicationBoundaryTests(unittest.TestCase):
    def test_application_workflows_do_not_import_argparse(self):
        for name in ('application/pipeline.py','application/runs.py','versions/service.py','workbench/app.py'):
            path=ROOT/'src/ai_lib_qor'/name
            tree=ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node,ast.Import):
                    self.assertNotIn('argparse',[x.name for x in node.names],name)
                elif isinstance(node,ast.ImportFrom):
                    self.assertNotEqual(node.module,'argparse',name)

    def test_check_use_case_accepts_plain_paths(self):
        from ai_lib_qor.application.pipeline import check_plan
        plan=json.loads((ROOT/'examples/pipeline/check_effective.example.json').read_text())
        for key in ('target_revision','baseline_revision'):plan[key]=str(ROOT/plan[key])
        plan['formal_snapshots']=[str(ROOT/p) for p in plan['formal_snapshots']]
        for item in plan['comparisons']:
            for key in ('old_facts','new_facts'):item[key]=str(ROOT/item[key])
        for item in plan['pin_pairs']:
            for key in ('lef_facts','liberty_facts'):item[key]=str(ROOT/item[key])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); path=root/'plan.json';out=root/'check.json'
            path.write_text(json.dumps(plan))
            result=check_plan(path,out)
            self.assertEqual(json.loads(out.read_text())['target']['id'],'rev_0002')
            self.assertEqual(result['output'],str(out))

    def test_version_application_has_plain_apply_interface(self):
        from ai_lib_qor.versions.service import apply_version
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'尚未初始化'):
                apply_version(Path(directory)/'effective',Path(directory)/'delivery.json')

    def test_direct_initialization_requires_exactly_one_source(self):
        from ai_lib_qor.versions.service import run_version
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'effective'
            with self.assertRaisesRegex(ValueError,'唯一.*来源'):
                run_version('init',effective_dir=root,delivery='raw.json',snapshot='formal.json',
                            owner_type='BUSINESS_IP',owner_id='ip',home_library='lib',set_id='set')
            self.assertFalse(root.exists())


if __name__=='__main__':unittest.main()
