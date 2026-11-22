import json
import tempfile
import unittest
import shutil
from pathlib import Path
from unittest.mock import patch

from ai_lib_qor.versions.service import run_version

ROOT=Path(__file__).resolve().parents[1]
EX=ROOT/'examples/work/vendors/vendor_orion/libraries/lib_rtavfs/deliveries'


class JsonOnlyVersionsTests(unittest.TestCase):
    def test_offline_init_apply_selected_and_acceptance(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); effective=base/'effective'
            inputs=[]
            for n, rel in enumerate(('dlv_20260907_001','dlv_20261019_001')):
                data=json.loads((EX/rel/'delivery.json').read_text())
                data['source_root']=str(base/'not_available'/str(n))
                path=base/f'd{n}.json'; path.write_text(json.dumps(data));inputs.append(path)
            with patch('os.walk',side_effect=AssertionError('不得扫描来源')):
                run_version('init',effective_dir=effective,delivery=inputs[0],set_id='set',owner_type='BUSINESS_IP',owner_id='ip',home_library='lib_rtavfs')
                run_version('accept',effective_dir=effective,revision='rev_0001',actor='tester',reason='review')
                run_version('apply',effective_dir=effective,delivery=inputs[1],file_key=['lib_rtavfs:lef:core'])
            rev=json.loads((effective/'versions/rev_0002.json').read_text())
            members={x['file_key']:x['source_ref']['delivery_id'] for x in rev['members']}
            self.assertEqual(members['lib_rtavfs:lef:core'],'dlv_20261019_001')
            self.assertEqual(members['lib_rtavfs:liberty:func_ff'],'dlv_20260907_001')
            index=json.loads((effective/'index.json').read_text())
            self.assertEqual(index['latest_calculated_revision'],'rev_0002')
            self.assertEqual(index['current_accepted_revision'],'rev_0001')

    def test_explicit_verification_requires_source(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); data=json.loads((EX/'dlv_20260907_001/delivery.json').read_text())
            data['source_root']=str(base/'missing'); path=base/'d.json';path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'来源目录不可访问'):
                run_version('init',effective_dir=base/'effective',delivery=path,set_id='set',owner_type='BUSINESS_IP',owner_id='ip',home_library='lib_rtavfs',verify_files=True)

    def test_known_filename_candidate_requires_explicit_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); data=json.loads((EX/'dlv_20260907_001/delivery.json').read_text())
            path=base/'delivery.json';path.write_text(json.dumps(data))
            candidate=data['files'][0]
            (base/'source_evidence.json').write_text(json.dumps({'classification':{candidate['relative_path']:{'basis':'filename_unique_candidate'}}}))
            kwargs=dict(delivery=path,set_id='set',owner_type='BUSINESS_IP',owner_id='ip',home_library='lib_rtavfs')
            with self.assertRaisesRegex(ValueError,'候选'):
                run_version('init',effective_dir=base/'blocked',**kwargs)
            result=run_version('init',effective_dir=base/'chosen',file_key=[candidate['file_key']],**kwargs)
            self.assertEqual(result['revision_id'],'rev_0001')

    def test_web_does_not_auto_select_filename_candidates(self):
        from ai_lib_qor.workbench.app import create_app
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);work=base/'work';shutil.copytree(ROOT/'examples/overall_demo/dataset/work',work)
            lib=work/'vendors/vendor_orion/libraries/lib_rtavfs'
            effective=lib/'ips/rtavfs/effective';(effective/'versions/rev_0002.json').unlink()
            folder=lib/'deliveries/dlv_20261019_001';path=folder/'delivery.json'
            delivery=json.loads(path.read_text());
            delivery['files'].append({'file_id':'doc','file_key':None,'classification':'UNRESOLVED','relative_path':'readme.txt','view':'OTHER','corner':None,'mode':None})
            path.write_text(json.dumps(delivery))
            classification={f['relative_path']:{'basis':'filename_unique_candidate'} for f in delivery['files'] if f['file_key']}
            (folder/'source_evidence.json').write_text(json.dumps({'classification':classification}))
            client=create_app(ROOT/'examples/pipeline',base/'runs',work).test_client()
            with client.session_transaction() as session:session['csrf']='token'
            response=client.post('/effective/apply',data={'csrf':'token','vendor':'vendor_orion','library':'lib_rtavfs','ip':'rtavfs','delivery':'dlv_20261019_001'})
            self.assertEqual(response.status_code,409)
            self.assertFalse((effective/'versions/rev_0002.json').exists())


if __name__=='__main__':unittest.main()
