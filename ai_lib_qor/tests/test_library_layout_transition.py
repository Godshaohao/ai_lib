import json
import tempfile
import unittest
from pathlib import Path
from ai_lib_qor.sources.root_inventory import build_from_roots
from ai_lib_qor.application.minimal_effective import initialize_from_formal

class LibraryLayoutTransitionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  root=Path(self.tmp.name);self.raw=root/'raw';self.nl=root/'NL1';self.nl.mkdir();self.work=root/'work'
  f=self.raw/'v/lib/20261001_a/LEF/a.lef';f.parent.mkdir(parents=True);f.write_text('MACRO A\n SIZE 1 BY 2 ;\nEND A\n')
  (self.nl/'a.lef').symlink_to(f)
  build_from_roots(self.raw,self.nl,self.work)
  self.folder=self.work/'libraries/v/lib'
 def test_subdirectories_and_relative_latest_links(self):
  self.assertEqual(len(list((self.folder/'delivery').glob('delivery_*.json'))),1)
  self.assertEqual(len(list((self.folder/'formal').glob('formal_*.json'))),1)
  self.assertTrue((self.folder/'latest_delivery.json').is_symlink())
  self.assertTrue((self.folder/'latest_delivery.json').resolve().is_file())
  self.assertEqual((self.folder/'latest_delivery.json').resolve().parent.name,'delivery')
  formal=next((self.folder/'formal').glob('formal_*.json'))
  initialize_from_formal(self.work,'v','lib',formal)
  self.assertEqual((self.folder/'latest_effective.json').resolve().parent.name,'effective')
 def test_check_outputs_paired_and_no_persistent_facts(self):
  from ai_lib_qor.application.minimal_checks import run_revision
  formal=next((self.folder/'formal').glob('formal_*.json'))
  initialize_from_formal(self.work,'v','lib',formal)
  result=run_revision(self.work,'v','lib','rev_0001')
  self.assertEqual(Path(result['check']).parent,self.folder/'log')
  self.assertEqual(Path(result['check']).stem,Path(result['excel']).stem)
  self.assertFalse(list(self.folder.rglob('facts_*.json')))
  self.assertTrue((self.folder/'latest_check.json').is_symlink())
  self.assertTrue((self.folder/'latest_check.xlsx').is_symlink())
  self.assertTrue((self.folder/'log/runs.jsonl').is_file())
 def test_overall_reuses_saved_results_and_marks_missing(self):
  from ai_lib_qor.application.minimal_checks import run_revision,run_library
  formal=next((self.folder/'formal').glob('formal_*.json'))
  initialize_from_formal(self.work,'v','lib',formal)
  first=run_library(self.work,'v','lib')
  self.assertEqual(first['versions'][0]['state'],'NOT_CHECKED')
  self.assertFalse(list((self.folder/'log').glob('check_rev_*.json')))
  check=run_revision(self.work,'v','lib','rev_0001')
  second=run_library(self.work,'v','lib')
  self.assertEqual(second['versions'][0]['run_id'],check['run_id'])
  self.assertEqual(len(list((self.folder/'log').glob('check_rev_*.json'))),1)
  self.assertTrue((self.folder/'latest_overall.xlsx').is_symlink())
  row=json.loads(Path(check['check']).read_text())
  self.assertTrue(row['facts_evidence'])
  self.assertTrue(all(ref in row['facts_evidence'] for c in row['checks'] for ref in c['facts_refs']))
 def test_migrate_flat_history_preserves_index_and_legacy_check_refs(self):
  from ai_lib_qor.application.library_layout_migration import migrate_library_layout
  from ai_lib_qor.application.minimal_file_index import build_index
  formal=next((self.folder/'formal').glob('formal_*.json'));initialize_from_formal(self.work,'v','lib',formal)
  before=build_index(self.work,'v','lib')
  for kind in ('delivery','formal','effective'):
   for f in (self.folder/kind).iterdir():f.rename(self.folder/f.name)
  for ptr in self.folder.glob('latest_*.json'):
   target=ptr.readlink().name;ptr.unlink();ptr.symlink_to(target)
  old=self.folder/'facts_OLD.json';old.write_text('{}')
  result=migrate_library_layout(self.work,'v','lib')
  self.assertIn('facts_OLD.json',result['preserved_legacy_artifacts'])
  self.assertTrue(old.exists());self.assertEqual(before,build_index(self.work,'v','lib'))
  self.assertEqual((self.folder/'latest_delivery.json').resolve().parent.name,'delivery')
  self.assertEqual((self.folder/'latest_effective.json').resolve().parent.name,'effective')
  self.assertEqual(migrate_library_layout(self.work,'v','lib')['moved'],0)
