"""End-to-end synthetic RAW: three deliveries and independent Liberty corners."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from ai_lib_qor.sources.delivery_builder import build_delivery
from ai_lib_qor.facts.parsers import parse_delivery_file
from ai_lib_qor.checks.plan import pair_interfaces
from ai_lib_qor.checks.assembler import build_check_result
from ai_lib_qor.reporting.view import build_report
from ai_lib_qor.reporting.html import render_html
from ai_lib_qor.reporting.excel import render_excel

ROOT = Path(__file__).resolve().parents[1]

class MultiVersionCorners(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.raw=self.base/'RAW';self.effective=self.base/'effective'
        self.records=[]; self.record_files=[]
        for number, corners in ((7,('tt','ff')),(8,('tt',)),(9,('ss',))):
            root=self.raw/f'V{number:02d}';(root/'lef').mkdir(parents=True);(root/'lib').mkdir()
            (root/'lef/core.lef').write_text(f'MACRO MAC_A\n SIZE {100+number} BY 80 ;\n PIN A\n DIRECTION INPUT ;\n END A\n PIN Z\n DIRECTION OUTPUT ;\n END Z\n END MAC_A\n')
            mapping={'lef/core.lef':{'file_key':'lib:lef:core','view':'LEF','corner':None,'mode':None}}
            for corner in corners:
                direction='input' if corner=='ff' else 'output'
                (root/f'lib/{corner}.lib').write_text(f'library({corner}) {{ cell(MAC_A) {{ pin(A) {{ direction : input; }} pin(Z) {{ direction : {direction}; }} }} }}')
                mapping[f'lib/{corner}.lib']={'file_key':f'lib:liberty:{corner}','view':'LIBERTY','corner':corner,'mode':'functional'}
            metadata={'delivery_id':f'delivery_{number:02d}','vendor_id':'vendor_a','source_library_id':'lib','supplier_version':f'V{number:02d}', 'delivery_order':number,'received_at':f'2026-01-{number:02d}T00:00:00Z','package_mode':'FULL' if number==7 else 'INCREMENTAL','scope_confirmed':True}
            record=build_delivery(root,metadata,mapping);path=self.base/f'delivery_{number}.json';path.write_text(json.dumps(record));self.records.append(record);self.record_files.append(path)
        self.before={str(p.relative_to(self.raw)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.raw.rglob('*') if p.is_file()}

    def version(self,*args):
        env={**os.environ,'PYTHONPATH':str(ROOT/'src')+os.pathsep+os.environ.get('PYTHONPATH','')}
        p=subprocess.run([sys.executable,'-m','ai_lib_qor.versions',*map(str,args)],text=True,capture_output=True,env=env)
        self.assertEqual(p.returncode,0,p.stderr)

    def fact(self,record,key):
        f=next(x for x in record['files'] if x['file_key']==key)
        return parse_delivery_file(record,f['file_id'])

    def test_three_revisions_and_three_corners_with_independent_results(self):
        d7,d8,d9=self.records;p7,p8,p9=self.record_files
        self.version('init','--effective-dir',self.effective,'--delivery',p7,'--set-id','ip_set','--owner-type','BUSINESS_IP','--owner-id','ip','--home-library','lib')
        self.version('accept','--effective-dir',self.effective,'--revision','rev_0001','--actor','owner','--reason','review')
        for path in (p8,p9):self.version('apply','--effective-dir',self.effective,'--delivery',path)
        rev2=json.loads((self.effective/'versions/rev_0002.json').read_text());rev3=json.loads((self.effective/'versions/rev_0003.json').read_text());index=json.loads((self.effective/'index.json').read_text())
        members={x['file_key']:x['source_ref'] for x in rev3['members']}
        self.assertEqual({key:members['lib:liberty:'+key]['delivery_id'] for key in ('tt','ff','ss')},{'tt':'delivery_08','ff':'delivery_07','ss':'delivery_09'})
        self.assertEqual(index['latest_calculated_revision'],'rev_0003');self.assertEqual(index['current_accepted_revision'],'rev_0001')
        from ai_lib_qor.workbench.read_models import build_file_matrix
        projection=build_file_matrix(rev3,rev2,self.records,[],home_library='lib')
        rows={r['file_key']:r for r in projection['rows']}
        self.assertEqual({c:rows['lib:liberty:'+c]['target']['version'] for c in ('tt','ff','ss')},{'tt':'V08','ff':'V07','ss':'V09'})
        self.assertEqual(rows['lib:liberty:ff']['source_relation'],'UNCHANGED')
        self.assertEqual(rows['lib:liberty:ss']['source_relation'],'ADDED')
        rev1=json.loads((self.effective/'versions/rev_0001.json').read_text())
        older={r['file_key']:r for r in build_file_matrix(rev3,rev1,self.records,[],home_library='lib')['rows']}
        self.assertEqual(older['lib:liberty:tt']['source_relation'],'REPLACED')
        old=self.fact(d8,'lib:lef:core');new=self.fact(d9,'lib:lef:core')
        corners=[self.fact(d8,'lib:liberty:tt'),self.fact(d7,'lib:liberty:ff'),self.fact(d9,'lib:liberty:ss')]
        inputs=[{'file_key':'lib:lef:core','facts':new}]+[{'file_key':f'lib:liberty:{key}','facts':f} for key,f in zip(('tt','ff','ss'),corners)]
        pairs=pair_interfaces(inputs);self.assertEqual(len(pairs),3)
        check=build_check_result(target={'kind':'EFFECTIVE_REVISION','id':'rev_0003'},baseline={'kind':'EFFECTIVE_REVISION','id':'rev_0002'},effective_set_id='ip_set',run_id='test_multi',ruleset_id='test',run_at='2026-01-10T00:00:00Z',comparisons=[{'file_key':'lib:lef:core','old':old,'new':new}],pin_pairs=pairs,target_members=members,baseline_members={x['file_key']:x['source_ref'] for x in rev2['members']})
        by_corner={q['scope_file_keys'][1]:q['result'] for q in check['quality_checks']}
        self.assertEqual(by_corner,{'lib:liberty:tt':'PASS','lib:liberty:ff':'FAIL','lib:liberty:ss':'PASS'})
        self.assertEqual(check['summary']['failed_checks'],1)
        report=build_report(check,deliveries=self.records,facts=[old,new,*corners],target_revision=rev3,baseline_revision=rev2)
        html=render_html(report)
        for corner in ('lib:liberty:tt','lib:liberty:ff','lib:liberty:ss'):self.assertIn(corner,html)
        from openpyxl import load_workbook
        path=self.base/'multi.xlsx';render_excel(report,path);wb=load_workbook(path,read_only=True,data_only=True)
        values='\n'.join(str(c) for ws in wb for row in ws.values for c in row if c is not None)
        for value in ('lib:liberty:tt','lib:liberty:ff','lib:liberty:ss','FAIL','rev_0003'):self.assertIn(value,values)
        wb.close()
        after={str(p.relative_to(self.raw)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.raw.rglob('*') if p.is_file()}
        self.assertEqual(self.before,after)
