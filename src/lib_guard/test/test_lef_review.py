import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
ASAP7 = ROOT / 'tests/fixtures/raw/vendor_A/openroad_asap7'
NANGATE = ROOT / 'tests/fixtures/raw/vendor_A/openroad_nangate45/20260615_nangate45/nangate45_source_package/lef'


class LefReviewCommandTest(unittest.TestCase):
    def run_review(self, old, new, out):
        env = os.environ.copy()
        env['PYTHONPATH'] = str(ROOT / 'src')
        return subprocess.run(
            [sys.executable, '-m', 'lib_guard.lef_review', str(old), str(new), '--out-dir', str(out)],
            cwd=ROOT, env=env, capture_output=True, text=True,
        )

    def test_real_asap7_same_file_produces_only_two_outputs(self):
        name = 'asap7sc7p5t_28_SL_1x_220121a.lef'
        old = ASAP7 / '20260624_asap7/asap7_source_package/lef' / name
        new = ASAP7 / '20260627_asap7/upstream_ae9a8ed9/lef' / name
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'review'
            run = self.run_review(old, new, out)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)['status'], 'DONE')
            self.assertEqual({path.name for path in out.iterdir()}, {'lef_analysis.json', 'lef_review.md'})
            data = json.loads((out / 'lef_analysis.json').read_text())
            self.assertEqual(data['schema_version'], 'lef_analysis.v1')
            self.assertEqual(data['comparison']['content']['status'], 'SAME')
            self.assertEqual(data['comparison']['macro_names']['status'], 'COMPARED')
            self.assertEqual(len(data['extraction']['old']['macro_names']), 212)
            self.assertEqual(data['extraction']['old']['macro_names'], data['extraction']['new']['macro_names'])
            self.assertEqual(data['comparison']['macro_names']['added'], [])
            self.assertEqual(data['comparison']['macro_names']['removed'], [])
            report = (out / 'lef_review.md').read_text()
            self.assertIn('两个 LEF 文件内容相同吗', report)
            self.assertIn('这两个文件分别包含什么', report)
            self.assertEqual(data['statistics']['old']['macro_count'], 212)
            self.assertEqual(data['statistics']['old']['pin_count'], 1326)
            self.assertEqual(data['statistics']['old']['pin_rect_count'], 2900)
            self.assertEqual(data['statistics']['old']['obs_rect_count'], 2797)
            self.assertEqual(data['statistics']['old']['class_counts']['CORE'], 200)
            self.assertEqual(data['statistics']['old']['pin_direction_counts']['INPUT'], 698)
            self.assertIn('| Pin | 1326 | 1326 |', report)
            self.assertIn('| Pin RECT | 2900 | 2900 |', report)
            self.assertIn('| 已识别层 | 5 | 5 |', report)
            self.assertIn('CORE：200', report)
            self.assertIn('M1', report)
            self.assertIn('完整 Macro 索引', report)
            self.assertIn('附录：Macro 逐项索引', report)
            self.assertIn('POWER 212/212；GROUND 212/212', report)
            self.assertLess(report.index('POWER 212/212；GROUND 212/212'),
                            report.index('| `A2O1A1Ixp33_ASAP7_75t_SL` |'))
            self.assertIn('| Pin RECT | OBS RECT |', report)
            self.assertIn('| 电源脚 | 地脚 |', report)
            self.assertIn('| `AND2x2_ASAP7_75t_SL` | CORE | asap7sc7p5t | 0.324 × 0.27 | 5 | 3 | `VDD` | `VSS` |', report)
            self.assertIn('目标文件中所有 Macro 均声明 POWER 和 GROUND Pin', report)
            self.assertIn('## 对接入有什么提示？', report)
            self.assertIn('其他视图未比较', report)
            self.assertNotIn('这不代表未解析字段相同', report)
            self.assertIn('文件字节相同', report)
            self.assertEqual(len([line for line in report.splitlines() if line.startswith('| `')]), 212)
            self.assertIn('| `AND2x2_ASAP7_75t_SL` |', report)

    def test_real_nangate_macro_name_addition_is_complete(self):
        old = NANGATE / 'NangateOpenCellLibrary.macro.lef'
        new = NANGATE / 'NangateOpenCellLibrary.macro.mod.lef'
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'review'
            run = self.run_review(old, new, out)
            self.assertEqual(run.returncode, 0, run.stderr)
            data = json.loads((out / 'lef_analysis.json').read_text())
            self.assertEqual(data['comparison']['macro_names']['added'], ['TAPCELL_X1'])
            self.assertEqual(data['comparison']['macro_names']['removed'], [])
            self.assertEqual(len(data['extraction']['old']['macro_names']), 134)
            self.assertEqual(len(data['extraction']['new']['macro_names']), 135)
            self.assertEqual(data['statistics']['old']['macro_count'], 134)
            self.assertEqual(data['statistics']['new']['macro_count'], 135)
            self.assertIn('TAPCELL_X1', (out / 'lef_review.md').read_text())
            self.assertIn('pin_geometry', data['comparison']['unverified'])
            self.assertIn('pins.use', data['comparison']['unverified'])
            self.assertFalse(any(change['field'] == 'pins.A1.use' for change in data['comparison']['changes']))
            self.assertIn('不判断是否变化', (out / 'lef_review.md').read_text())
            self.assertIn('核对布局', (out / 'lef_review.md').read_text())
            self.assertIn('| Pin RECT | 未确认 | 2551 |', (out / 'lef_review.md').read_text())
            self.assertIn('| OBS RECT | 未确认 | 1554 |', (out / 'lef_review.md').read_text())

    def test_controlled_size_pin_geometry_and_obs_changes(self):
        template = '''VERSION 5.8 ;
MACRO M
CLASS BLOCK ;
SIZE {size} BY 20 ;
SITE CORE ;
PIN A
DIRECTION {direction} ;
USE SIGNAL ;
PORT
LAYER M1 ;
RECT 0 0 {rect} 1 ;
END
END A
OBS
LAYER M2 ;
RECT 0 0 {obs} 2 ;
END
END M
END LIBRARY
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new = root / 'old.lef', root / 'new.lef'
            old.write_text(template.format(size=10, direction='INPUT', rect=1, obs=1))
            new.write_text(template.format(size=11, direction='OUTPUT', rect=2, obs=2))
            out = root / 'review'
            run = self.run_review(old, new, out)
            self.assertEqual(run.returncode, 0, run.stderr)
            data = json.loads((out / 'lef_analysis.json').read_text())
            fields = {change['field'] for change in data['comparison']['changes']}
            self.assertEqual(data['comparison']['macro_names']['added'], [])
            self.assertTrue({'size', 'pins.A.direction', 'pins.A.rects', 'obs'} <= fields)
            report = (out / 'lef_review.md').read_text()
            self.assertIn('M', report)
            self.assertIn('尺寸', report)
            self.assertIn('几何', report)

    def test_macro_without_power_or_ground_pin_is_listed_as_an_exception(self):
        template = '''VERSION 5.8 ;
MACRO {name}
CLASS {macro_class} ;
SIZE 1 BY 1 ;
SITE CORE ;
{pins}
END {name}
END LIBRARY
'''
        powered = '''PIN VDD
DIRECTION INOUT ;
USE POWER ;
END VDD
PIN VSS
DIRECTION INOUT ;
USE GROUND ;
END VSS
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new = root / 'old.lef', root / 'new.lef'
            old.write_text(template.format(name='LOGIC', macro_class='CORE', pins=powered))
            new.write_text(template.format(name='LOGIC', macro_class='CORE', pins=powered) +
                           template.format(name='BLACKBOX', macro_class='BLOCK', pins=''))
            out = root / 'review'
            run = self.run_review(old, new, out)
            self.assertEqual(run.returncode, 0, run.stderr)
            report = (out / 'lef_review.md').read_text()
            self.assertIn('| `LOGIC` | CORE | CORE | 1 × 1 | 2 | 0 | `VDD` | `VSS` |', report)
            self.assertIn('未声明 POWER：`BLACKBOX`', report)
            self.assertIn('未声明 GROUND：`BLACKBOX`', report)

    def test_incomplete_macro_discovery_does_not_claim_addition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new = root / 'old.lef', root / 'new.lef'
            old.write_text('MACRO M\nCLASS BLOCK ;\nEND M\nEND LIBRARY\n')
            new.write_text('MACRO M\nCLASS BLOCK ;\nEND M\nMACRO N\nCLASS BLOCK ;\n')
            out = root / 'review'
            run = self.run_review(old, new, out)
            self.assertEqual(run.returncode, 0, run.stderr)
            data = json.loads((out / 'lef_analysis.json').read_text())
            self.assertEqual(data['comparison']['macro_names']['status'], 'UNVERIFIED')
            self.assertIsNone(data['comparison']['macro_names']['added'])
            report = (out / 'lef_review.md').read_text()
            self.assertIn('无法确认完整', report)
            self.assertIn('已提取 Macro 候选', report)
            self.assertNotIn('完整 Macro 索引', report)
            self.assertIn('不判断是否变化', report)
            self.assertNotIn('两侧完整提取的 RECT', report)


if __name__ == '__main__':
    unittest.main()
