"""Catalog build reads each persisted observation and delivery at most once per refresh."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from ai_lib_qor.application.library_catalog import LibraryCatalog

ROOT=Path(__file__).resolve().parents[1]


class CatalogBuildTests(unittest.TestCase):
    def test_catalog_cli_builds_read_only_summary_and_rejects_missing_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);work=root/'work';shutil.copytree(ROOT/'examples/work',work);runs=root/'runs'
            env={**os.environ,'PYTHONPATH':str(ROOT/'src')+os.pathsep+str(ROOT.parent/'src')+os.pathsep+os.environ.get('PYTHONPATH','')}
            command=[sys.executable,'-m','ai_lib_qor','catalog-refresh','--work',str(work),'--runs',str(runs)]
            result=subprocess.run(command,env=env,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            output=json.loads(result.stdout)
            self.assertEqual(output['deliveries'],2);self.assertEqual(output['ips'],1)
            self.assertEqual(output['storage'],'memory_only');self.assertFalse(runs.exists())
            command[command.index(str(work))]=str(root/'missing')
            self.assertNotEqual(subprocess.run(command,env=env,text=True,capture_output=True).returncode,0)

    def test_corrupt_record_reports_partial_and_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);work=root/'work';shutil.copytree(ROOT/'examples/work',work)
            path=work/'vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20261019_001/delivery.json'
            path.write_text('{invalid')
            env={**os.environ,'PYTHONPATH':str(ROOT/'src')+os.pathsep+str(ROOT.parent/'src')+os.pathsep+os.environ.get('PYTHONPATH','')}
            result=subprocess.run([sys.executable,'-m','ai_lib_qor','catalog-refresh','--work',str(work),'--runs',str(root/'runs')],env=env,text=True,capture_output=True)
            self.assertNotEqual(result.returncode,0)
            result=json.loads(result.stdout)
            self.assertEqual(result['state'],'PARTIAL');self.assertEqual(result['deliveries'],1)
            self.assertTrue(result['warnings'])

    def test_bulk_histories_match_individual_queries_and_ignore_bad_records(self):
        from ai_lib_qor.application.scans import observations,observation_index
        from ai_lib_qor.sources.formal_sync import formal_history,formal_history_index
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);runs=root/'runs';scan_dir=runs/'scans';formal_dir=runs/'formal_observations'
            scan_dir.mkdir(parents=True);formal_dir.mkdir()
            source={'vendor_id':'v','source_library_id':'lib','root':str(root/'raw')}
            config={'formal_nl_id':'NL','root':str(root/'formal')}
            for n in range(3):
                (scan_dir/f'scan_{n}.json').write_text(json.dumps({**source,'started_at':f'2026-01-0{n+1}','scan_id':str(n)}))
                (formal_dir/f'formal_{n}.json').write_text(json.dumps({**config,'observed_at':f'2026-01-0{n+1}','observation_id':str(n)}))
            (scan_dir/'scan_bad.json').write_text('{');(formal_dir/'formal_bad.json').write_text('{')
            (scan_dir/'scan_link.json').symlink_to(scan_dir/'scan_1.json')
            (formal_dir/'formal_link.json').symlink_to(formal_dir/'formal_1.json')
            scan_key=('v','lib',str(Path(source['root']).resolve()))
            formal_key=('NL',str(Path(config['root']).resolve()))
            self.assertEqual(observation_index(runs)[scan_key],observations(runs,source))
            self.assertEqual(formal_history_index(runs)[formal_key],formal_history(runs,config))

    def test_refresh_reads_records_once_and_reloads_after_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);work=root/'work';runs=root/'runs';shutil.copytree(ROOT/'examples/work',work)
            source=[]
            for n in range(3):
                source.append({'vendor_id':f'v{n}','source_library_id':f'lib{n}','root':str(root/f'raw{n}')})
            (work/'scan_sources.json').write_text(json.dumps({'sources':source}))
            scans=runs/'scans';scans.mkdir(parents=True)
            for n in range(3):
                for v in range(2):
                    row={'vendor_id':f'v{n}','source_library_id':f'lib{n}','root':str(root/f'raw{n}'),
                         'scan_id':f'scan_{n}{v}','started_at':f'2026-01-0{v+1}','status':'COMPLETE','files':[],'changes':None}
                    (scans/f'scan_{n}{v}.json').write_text(json.dumps(row))
            reads=Counter();original=Path.read_text
            def tracked(path,*args,**kwargs):
                if path.name=='delivery.json' or path.parent==scans: reads[str(path)]+=1
                return original(path,*args,**kwargs)
            with patch.object(Path,'read_text',autospec=True,side_effect=tracked):
                catalog=LibraryCatalog(work,runs).refresh();overview=catalog.overview()
            self.assertEqual(len(overview['raw_rows']),4)
            self.assertTrue(reads)
            self.assertTrue(all(count==1 for count in reads.values()),reads)
            self.assertEqual(overview['raw_rows'][0]['last_attempt']['scan_id'],'scan_01')
            extra={'vendor_id':'v0','source_library_id':'lib0','root':str(root/'raw0'),
                   'scan_id':'scan_new','started_at':'2026-01-03','status':'COMPLETE','files':[],'changes':None}
            (scans/'scan_new.json').write_text(json.dumps(extra))
            catalog.refresh(); self.assertEqual(catalog.overview()['raw_rows'][0]['last_attempt']['scan_id'],'scan_new')


if __name__=='__main__': unittest.main()
