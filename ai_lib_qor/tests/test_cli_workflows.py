import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CliWorkflowTests(unittest.TestCase):
    def cli(self, *args):
        env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(ROOT / 'src'), str(ROOT.parent / 'src'), os.environ.get('PYTHONPATH', ''))))
        return subprocess.run([sys.executable, '-m', 'ai_lib_qor', *map(str, args)],
                              text=True, capture_output=True, env=env)

    def test_cli_scan_and_formal_results_are_visible_to_web(self):
        from ai_lib_qor.workbench.app import create_app
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); work = root / 'work'; work.mkdir(); runs = root / 'runs'
            raw = root / 'raw'; target = raw / 'V07' / 'core.lef'
            target.parent.mkdir(parents=True); target.write_text('LEF')
            formal = root / 'formal'; formal.mkdir(); (formal / 'core.lef').symlink_to(target)
            (work / 'scan_sources.json').write_text(json.dumps({'sources': [{'vendor_id':'v', 'source_library_id':'lib', 'root':str(raw), 'version_paths':{'V07':'V07'}}]}))
            (work / 'formal_sources.json').write_text(json.dumps({'sources':[{'formal_nl_id':'NL1','root':str(formal)}]}))
            scan = self.cli('scan', '--work', work, '--runs', runs)
            self.assertEqual(scan.returncode, 0, scan.stderr)
            self.assertEqual(len(list(work.glob('libraries/*/*/delivery_*.json'))), 1)
            sync = self.cli('formal-sync', '--work', work, '--runs', runs)
            self.assertEqual(sync.returncode, 0, sync.stderr)
            self.assertEqual(len(list(work.glob('libraries/*/*/formal_*.json'))), 1)
            client = create_app(ROOT/'examples/pipeline', runs, work).test_client()
            page = client.get('/library?vendor=v&library=lib').get_data(as_text=True)
            self.assertIn('V07', page)
            self.assertIn('core.lef', page)

    def test_cli_rejects_missing_configured_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'scan_sources.json').write_text('{"sources":[]}')
            result = self.cli('scan', '--work', root, '--runs', root/'runs')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('没有', result.stderr)

    def test_cli_runs_both_versions_and_web_reads_same_reports(self):
        from ai_lib_qor.workbench.app import create_app
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); plans=root/'plans'; plans.mkdir(); runs=root/'runs'
            work=ROOT/'examples/work'
            revs=work/'vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/versions'
            snap=work/'formal_nl/NL2.5.3/snapshots/snap_nl253_0001.json'
            facts=ROOT/'examples/file_facts'
            common={'ruleset_id':'test','formal_snapshots':[str(snap)]}
            first={**common,'target_revision':str(revs/'rev_0001.json'), 'baseline_revision':str(revs/'rev_0001.json'),
                   'comparisons':[{'file_key':'lib_rtavfs:lef:core','old_facts':str(facts/'facts_core_v07.json'),'new_facts':str(facts/'facts_core_v07.json')}], 'pin_pairs':[]}
            second={**common,'target_revision':str(revs/'rev_0002.json'), 'baseline_revision':str(revs/'rev_0001.json'),
                    'comparisons':[{'file_key':'lib_rtavfs:lef:core','old_facts':str(facts/'facts_core_v07.json'),'new_facts':str(facts/'facts_core_v08.json')}],
                    'pin_pairs':[{'lef_key':'lib_rtavfs:lef:core','liberty_key':'lib_rtavfs:liberty:func_tt','lef_facts':str(facts/'facts_core_v08.json'),'liberty_facts':str(facts/'facts_tt_v08.json')}]}
            (plans/'r1.json').write_text(json.dumps(first)); (plans/'r2.json').write_text(json.dumps(second))
            result=self.cli('run-ip','--work',work,'--runs',runs,'--plans',plans,'--vendor','vendor_orion','--library','lib_rtavfs','--ip','rtavfs')
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            status=json.loads(result.stdout); self.assertEqual(status['state'],'SUCCEEDED')
            self.assertTrue((runs/status['id']/'overall.xlsx').is_file())
            self.assertEqual(len(status['children']),2)
            from openpyxl import load_workbook
            overall_data=json.loads((runs/status['id']/'overall.json').read_text())
            overall_book=load_workbook(runs/status['id']/'overall.xlsx',data_only=True)
            aggregate={r[0]:r for r in list(overall_book['版本运行汇总'].values)[3:]}
            for child in status['children']:
                self.assertTrue((runs/child['id']/'check.json').is_file())
                self.assertTrue((runs/child['id']/'report.xlsx').is_file())
                check=json.loads((runs/child['id']/'check.json').read_text())
                batch_row=next(r for r in overall_data['versions'] if r['revision']==child['revision'])
                self.assertEqual(batch_row['run_id'],check['check_run_id'])
                self.assertEqual(batch_row['summary'],check['summary'])
                summary_row=aggregate[child['revision']]
                self.assertEqual(summary_row[3],check['check_run_id'])
                self.assertEqual(summary_row[6:8],(check['summary']['failed_checks'],check['summary']['inconclusive_checks']))
                single_book=load_workbook(runs/child['id']/'report.xlsx',data_only=True)
                overview=list(single_book['00-概览'].values)[4]
                self.assertEqual((overview[1],overview[4]),(child['revision'],check['check_run_id']))
                self.assertEqual(overview[9:11],(check['summary']['failed_checks'],check['summary']['inconclusive_checks']))
                single_book.close()
            overall_book.close()
            client=create_app(plans,runs,work).test_client()
            body=client.get('/runs/'+status['id']).get_data(as_text=True)
            self.assertIn('整体 IP 报告',body)
            for child in status['children']:
                self.assertIn(child['revision'],body)
                self.assertIn(child['id'],body)
            single=self.cli('run-plan','--plan',plans/'r2.json','--runs',runs,'--work',work,
                            '--vendor','vendor_orion','--library','lib_rtavfs','--ip','rtavfs','--revision','rev_0002')
            self.assertEqual(single.returncode,0,single.stdout+single.stderr)
            single_status=json.loads(single.stdout)
            self.assertEqual(single_status['owner']['ip'],'rtavfs')
            self.assertIn('report.xlsx',client.get('/runs/'+single_status['id']).get_data(as_text=True))
            wrong=self.cli('run-plan','--plan',plans/'r2.json','--runs',runs,'--work',work,
                           '--vendor','vendor_orion','--library','lib_rtavfs','--ip','rtavfs','--revision','rev_0001')
            self.assertNotEqual(wrong.returncode,0)

    def test_failed_plan_has_nonzero_exit_and_persisted_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); plan=root/'bad.json';plan.write_text('{}')
            result=self.cli('run-plan','--plan',plan,'--runs',root/'runs')
            self.assertNotEqual(result.returncode,0)
            status=json.loads(result.stdout)
            self.assertEqual(status['state'],'FAILED')
            self.assertTrue((root/'runs'/status['id']/'status.json').is_file())

    def test_cli_scan_failure_is_nonzero_and_records_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); work=root/'work';work.mkdir()
            (work/'scan_sources.json').write_text(json.dumps({'sources':[{'vendor_id':'v','source_library_id':'lib','root':str(root/'missing')}]}))
            result=self.cli('scan','--work',work,'--runs',root/'runs')
            self.assertNotEqual(result.returncode,0)
            row=json.loads(result.stdout)['sources'][0]
            self.assertEqual(row['status'],'FAILED')
            self.assertTrue((root/'runs'/'scans'/(row['scan_id']+'.json')).is_file())

    def test_cli_evidence_creates_web_visible_run(self):
        from ai_lib_qor.workbench.app import create_app
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); work=root/'work';work.mkdir(); raw=root/'raw'; leaf=raw/'V01/core.lef'
            leaf.parent.mkdir(parents=True);leaf.write_text('MACRO A\n SIZE 2 BY 2 ;\n END A\n')
            (work/'scan_sources.json').write_text(json.dumps({'sources':[{'vendor_id':'v','source_library_id':'lib','root':str(raw),'version_paths':{'V01':'V01'}}]}))
            scanned=self.cli('scan','--work',work,'--runs',root/'runs');self.assertEqual(scanned.returncode,0,scanned.stderr)
            from ai_lib_qor.versions.store import read_json
            delivery=next(work.glob('libraries/*/*/delivery_*.json')); file_id=read_json(delivery,'delivery_record')['files'][0]['file_id']
            result=self.cli('run-evidence','--delivery',delivery,'--file-id',file_id,'--runs',root/'runs')
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            run=json.loads(result.stdout);self.assertTrue((root/'runs'/run['id']/'parser_evidence.json').is_file())
            client=create_app(ROOT/'examples/pipeline',root/'runs',work).test_client()
            self.assertIn('parser_evidence.html',client.get('/runs/'+run['id']).get_data(as_text=True))


if __name__ == '__main__': unittest.main()
