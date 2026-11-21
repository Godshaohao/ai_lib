import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_lib_qor.application.data_query import LibraryDataQuery
from ai_lib_qor.sources.auto_ingest import auto_ingest
from ai_lib_qor.sources.update_scan import scan_library


class FileIndexIntegrationTests(unittest.TestCase):
 def test_registered_time_fallback_shared_by_index_query_and_latest(self):
  from ai_lib_qor.sources.delivery_builder import build_delivery
  from ai_lib_qor.application.file_index import refresh_library_index_locked
  from ai_lib_qor.application.latest_pointers import refresh_library
  from ai_lib_qor.versions.store import locked
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);work=root/'work';folder=work/'libraries/v/lib';folder.mkdir(parents=True)
   versions=['20250101_old','vendor_release','20250301_new']
   for n,version in enumerate(versions,1):
    raw=root/f'raw{n}';raw.mkdir();(raw/'a.lef').write_text('LEF')
    metadata={'delivery_id':f'd{n}','vendor_id':'v','source_library_id':'lib','supplier_version':version,'delivery_order':n,
              'received_at':'2030-01-01T00:00:00Z','package_mode':'UNKNOWN'}
    (folder/f'delivery_{n:03}.json').write_text(json.dumps(build_delivery(raw,metadata,{'a.lef':{'file_key':'lib:lef:a'}})))
   source={'vendor_id':'v','source_library_id':'lib','root':str(root),'order_rule':{'type':'VERSION_DATE_PREFIX','confirmed':True},
           'order_timezone':'Asia/Singapore','delivery_registration_times':{'d2':'2025-02-15T10:00:00+08:00'}}
   (work/'scan_sources.json').write_text(json.dumps({'sources':[source]}))
   with locked(folder):self.assertEqual(refresh_library_index_locked(work,'v','lib',source)['action'],'REBUILD')
   q=LibraryDataQuery(work,root/'runs');listing=q.list_deliveries('v','lib')
   self.assertEqual([x['delivery_id'] for x in listing['deliveries']],['d1','d2','d3'])
   self.assertEqual(listing['order_basis'],'CONFIRMED_DATE_AND_REGISTERED_TIME')
   self.assertEqual([x['delivery_id'] for x in json.loads((folder/'file_index.json').read_text())['deliveries']],['d3','d2','d1'])
   refresh_library(work,'v','lib');self.assertEqual(json.loads((folder/'latest_delivery.json').read_text())['delivery_id'],'d3')
 def test_parse_exact_delivery_view_and_path_with_real_file_identity(self):
  from ai_lib_qor.application.data_query import parse_recorded_file
  from ai_lib_qor.sources.delivery_builder import build_delivery
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);work=root/'work';folder=work/'libraries/v/lib';folder.mkdir(parents=True)
   raw=root/'raw';p=raw/'LEF/a.lef';p.parent.mkdir(parents=True)
   p.write_text('MACRO A\n SIZE 1 BY 2 ;\n PIN A\n DIRECTION INPUT ;\n END A\nEND A\n')
   meta={'delivery_id':'d1','vendor_id':'v','source_library_id':'lib','supplier_version':'V01','delivery_order':1,'received_at':'2026-01-01T00:00:00Z','package_mode':'UNKNOWN'}
   record=build_delivery(raw,meta,{'LEF/a.lef':{'file_key':'lib:lef:a'}})
   (folder/'delivery_001.json').write_text(json.dumps(record))
   fact=parse_recorded_file(work,root/'runs','v','lib','d1','LEF','LEF/a.lef')
   self.assertEqual(fact['source_ref']['file_id'],record['files'][0]['file_id'])
   self.assertEqual(fact['objects']['macros'][0]['size_um'],[1,2])
   with self.assertRaises(ValueError):parse_recorded_file(work,root/'runs','v','lib','d1','LEF','LEF/missing.lef')
   import subprocess,sys
   out=root/'facts.json'
   proc=subprocess.run([sys.executable,'-m','ai_lib_qor','facts-at','--work',str(work),'--runs',str(root/'runs'),
      '--vendor','v','--library','lib','--delivery-id','d1','--view','LEF','--path','LEF/a.lef','--out',str(out)],capture_output=True,text=True)
   self.assertEqual(proc.returncode,0,proc.stderr);self.assertEqual(json.loads(out.read_text()),fact)
 def test_logical_history_only_merges_explicitly_confirmed_keys(self):
  from ai_lib_qor.sources.delivery_builder import build_delivery
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);work=root/'work';folder=work/'libraries/v/lib';folder.mkdir(parents=True)
   source={'vendor_id':'v','source_library_id':'lib','root':str(root/'raw'),'delivery_orders':{'V01':1,'V02':2,'V03':3}}
   (work/'scan_sources.json').write_text(json.dumps({'sources':[source]}))
   for n,(name,basis) in enumerate((('a_old.lef','explicit'),('a_new.lef','explicit'),('a_guess.lef','filename_unique_candidate')),1):
    raw=root/'raw'/f'V0{n}';p=raw/'LEF'/name;p.parent.mkdir(parents=True);p.write_text('LEF')
    metadata={'delivery_id':f'd{n}','vendor_id':'v','source_library_id':'lib','supplier_version':f'V0{n}',
              'delivery_order':n,'received_at':'2026-01-01T00:00:00Z','package_mode':'UNKNOWN'}
    record=build_delivery(raw,metadata,{f'LEF/{name}':{'file_key':'lib:lef:a'}})
    (folder/f'delivery_{n:03}.json').write_text(json.dumps(record))
    (folder/f'evidence_delivery_{n:03}.json').write_text(json.dumps({'classification':{f'LEF/{name}':{'basis':basis}}}))
   with patch('os.walk',side_effect=AssertionError('不得扫描 RAW')):
    rows=LibraryDataQuery(work,root/'runs').get_logical_file_timeline('v','lib','LEF','lib:lef:a')
   self.assertEqual([x['path'] for x in rows['occurrences']],['LEF/a_old.lef','LEF/a_new.lef'])
   self.assertEqual(rows['unconfirmed_count'],1)
 def test_registration_index_and_select_at_intervening_delivery(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);work=root/'work';work.mkdir();raw=root/'raw';raw.mkdir()
   source={'vendor_id':'v','source_library_id':'lib','root':str(raw),'version_paths':{'V01':'V01','V02':'V02','V03':'V03'},'delivery_orders':{'V01':1,'V02':2,'V03':3}}
   (work/'scan_sources.json').write_text(json.dumps({'sources':[source]}))
   for version,path in [('V01','lef/core.lef'),('V02','lib/other.lib')]:
    p=raw/version/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('test')
   first=auto_ingest(work,source,scan_library(raw,'v','lib',metadata_only=True))
   self.assertEqual(first['file_index']['action'],'REBUILD')
   index=work/'libraries/v/lib/file_index.json';before=index.stat().st_mtime_ns
   second=auto_ingest(work,source,scan_library(raw,'v','lib',metadata_only=True))
   self.assertEqual(second['file_index']['action'],'UNCHANGED');self.assertEqual(index.stat().st_mtime_ns,before)
   before_append=index.read_text()
   p=raw/'V03/lef/core.lef';p.parent.mkdir(parents=True);p.write_text('new')
   third=auto_ingest(work,source,scan_library(raw,'v','lib',metadata_only=True))
   self.assertEqual(third['file_index']['action'],'APPEND')
   data=json.loads(index.read_text());versions={x['delivery_id']:x['version'] for x in data['deliveries']}
   self.assertEqual(data['schema'],'file_index.v3')
   self.assertEqual([versions[x['delivery_id']] for x in data['views']['LEF']['files']['lef/core.lef']['raw']],['V03','V01'])
   updated=index.read_text();index.write_text(before_append)
   interrupted=LibraryDataQuery(work,root/'runs')
   self.assertEqual(interrupted.file_index_status('v','lib')['status'],'STALE')
   self.assertEqual(interrupted.get_file_history('v','lib','LEF','lef/core.lef')['latest']['version'],'V03')
   from ai_lib_qor.workbench.app import create_app
   (root/'plans').mkdir()
   client=create_app(root/'plans',root/'runs',work).test_client()
   page=client.get('/library',query_string={'vendor':'v','library':'lib'})
   self.assertEqual(page.status_code,200);self.assertIn('data-file-index-status="STALE"',page.get_data(as_text=True))
   index.write_text(updated)
   with patch('os.walk',side_effect=AssertionError('查询不能扫描 RAW')):
    q=LibraryDataQuery(work,root/'runs');listing=q.list_deliveries('v','lib');ids={x['version']:x['delivery_id'] for x in listing['deliveries']}
    history=q.get_file_history('v','lib','LEF','lef/core.lef')
    selected=q.get_file_at_delivery('v','lib','LEF','lef/core.lef',ids['V02'])
   self.assertEqual(history['latest']['version'],'V03');self.assertEqual(selected['occurrence']['version'],'V01')
   self.assertEqual(selected['index_status'],'VALID')
   self.assertEqual(selected['absolute_path'],str(raw/'V01/lef/core.lef'))
   response=client.get('/api/library-data',query_string={'kind':'history-at','vendor':'v','library':'lib','view':'LEF','path':'lef/core.lef','delivery_id':ids['V02']})
   self.assertEqual(response.status_code,200);self.assertEqual(response.get_json(),selected)
   # An edited archived manifest invalidates the projection; query falls back to source records.
   original=index.read_text()
   delivery=work/'libraries/v/lib/delivery_001.json'
   from ai_lib_qor.sources.layout import evidence_path
   changed=json.loads(delivery.read_text());changed['views']['LEF']=['lef/replaced.lef'];delivery.write_text(json.dumps(changed))
   ep=evidence_path(delivery);evidence=json.loads(ep.read_text());compat=evidence['legacy_compatibility'];mapping=compat['files'];mapping['lef/replaced.lef']=mapping.pop('lef/core.lef');compat['file_order']=['lef/replaced.lef' if x=='lef/core.lef' else x for x in compat['file_order']];ep.write_text(json.dumps(evidence))
   status=auto_ingest(work,source,scan_library(raw,'v','lib',metadata_only=True))['file_index']
   self.assertEqual(status['action'],'ERROR');self.assertEqual(index.read_text(),original)
   stale=LibraryDataQuery(work,root/'runs').get_file_at_delivery('v','lib','LEF','lef/core.lef',ids['V02'])
   self.assertEqual(stale['index_status'],'INVALID');self.assertIsNone(stale['occurrence'])

 def test_unconfirmed_order_never_creates_sorted_index(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);work=root/'work';work.mkdir();raw=root/'raw'
   for version in ('V01','V02'):
    p=raw/version/'core.lef';p.parent.mkdir(parents=True);p.write_text('test')
   source={'vendor_id':'v','source_library_id':'lib','root':str(raw),'version_paths':{'V01':'V01','V02':'V02'}}
   result=auto_ingest(work,source,scan_library(raw,'v','lib',metadata_only=True))
   self.assertEqual(result['created'],2);self.assertEqual(result['file_index']['action'],'ORDER_UNCONFIRMED')
   self.assertFalse((work/'libraries/v/lib/file_index.json').exists())
   from ai_lib_qor.versions.store import read_json
   records=[read_json(p,'delivery_record') for p in sorted((work/'libraries/v/lib').glob('delivery_*.json'))]
   ids={r['supplier_version']:r['delivery_id'] for r in records}
   source['delivery_order_ids']=[ids['V02'],ids['V01']]
   (work/'scan_sources.json').write_text(json.dumps({'sources':[source]}))
   listing=LibraryDataQuery(work,root/'runs').list_deliveries('v','lib')
   self.assertEqual(listing['ordering_status'],'CONFIRMED')
   self.assertEqual([x['version'] for x in listing['deliveries']],['V01','V02'])
   from ai_lib_qor.application.latest_pointers import refresh_library
   refresh_library(work,'v','lib')
   self.assertEqual(read_json(work/'libraries/v/lib/latest_delivery.json','delivery_record')['delivery_id'],ids['V02'])
