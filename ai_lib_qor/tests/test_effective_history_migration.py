import json
import tempfile
import unittest
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from ai_lib_qor.application.history_migration import migrate_history

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'exports/flat_library_review_rdyp0zdh'

@unittest.skipUnless(DATA.is_dir(),'需要模拟样例')
class HistoryMigrationTests(unittest.TestCase):
 def test_all_history_with_acceptance_and_no_changes_to_source(self):
  source=DATA/'work/libraries/SRAM22/sram22_256x16m8w8'
  old={p.name:p.read_bytes() for p in source.glob('effective_*.json')}
  with tempfile.TemporaryDirectory() as tmp:
   out=Path(tmp)/'migration'
   summary=migrate_history(DATA/'work',DATA/'runs',vendor='SRAM22',library='sram22_256x16m8w8',owner='sram22_256x16m8w8',output=out)
   self.assertEqual(summary['revision_count'],2)
   a=json.loads((out/'effective_sram22_256x16m8w8_001.json').read_text())
   b=json.loads((out/'effective_sram22_256x16m8w8_002.json').read_text())
   self.assertEqual((a['revision'],b['parent']),('rev_0001','rev_0001'))
   self.assertEqual(b['views']['LEF']['LEF/sram22_256x16m8w8.lef'],'20261024_de0a9a7')
   index=json.loads((out/'effective_sram22_256x16m8w8_index.json').read_text())
   self.assertEqual(index['latest_calculated_revision'],'rev_0002')
   self.assertTrue((out/'effective_sram22_256x16m8w8_acceptance.jsonl').is_file())
   with self.assertRaises(FileExistsError):migrate_history(DATA/'work',DATA/'runs',vendor='SRAM22',library='sram22_256x16m8w8',owner='sram22_256x16m8w8',output=out)
  self.assertEqual(old,{p.name:p.read_bytes() for p in source.glob('effective_*.json')})
 def test_output_inside_source_rejected_before_write(self):
  with self.assertRaisesRegex(ValueError,'输出'):
   migrate_history(DATA/'work',DATA/'runs',vendor='SRAM22',library='sram22_256x16m8w8',owner='sram22_256x16m8w8',output=DATA/'work'/'migration')
 def test_cli_migrates_without_scan(self):
  with tempfile.TemporaryDirectory() as tmp:
   output=Path(tmp)/'migration'
   p=subprocess.run([sys.executable,'-m','ai_lib_qor','effective-migrate','--work',str(DATA/'work'),'--runs',str(DATA/'runs'),
     '--vendor','SRAM22','--library','sram22_256x16m8w8','--owner','sram22_256x16m8w8','--out',str(output)],
     capture_output=True,text=True,env=os.environ.copy())
   self.assertEqual(p.returncode,0,p.stderr)
   self.assertEqual(json.loads(p.stdout)['status'],'SHADOW_ONLY')
 def test_incomplete_conversion_does_not_publish(self):
  with tempfile.TemporaryDirectory() as tmp:
   output=Path(tmp)/'migration'
   with patch('ai_lib_qor.application.history_migration.simple_effective',side_effect=ValueError('来源无法解析')):
    with self.assertRaisesRegex(ValueError,'来源无法解析'):
     migrate_history(DATA/'work',DATA/'runs',vendor='SRAM22',library='sram22_256x16m8w8',owner='sram22_256x16m8w8',output=output)
   self.assertFalse(output.exists())
 def test_v2_index_replays_existing_acceptance(self):
  from ai_lib_qor.versions.index_projector import project_simple
  with tempfile.TemporaryDirectory() as tmp:
   out=Path(tmp)/'migration'
   migrate_history(DATA/'work',DATA/'runs',vendor='SRAM22',library='sram22_256x16m8w8',owner='sram22_256x16m8w8',output=out)
   revisions=[json.loads(p.read_text()) for p in sorted(out.glob('effective_*_00[12].json'))]
   events=[json.loads(s) for s in (out/'effective_sram22_256x16m8w8_acceptance.jsonl').read_text().splitlines()]
   index=project_simple(revisions,events,'sram22_256x16m8w8','t')
   self.assertEqual(index['latest_calculated_revision'],'rev_0002')
   self.assertEqual(index['current_accepted_revision'],'rev_0001')
   revisions[1]['parent']='rev_9999'
   with self.assertRaisesRegex(ValueError,'父版本'):project_simple(revisions,events,'sram22_256x16m8w8','t')
