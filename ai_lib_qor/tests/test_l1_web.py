import json
import tempfile
import unittest
from pathlib import Path
from ai_lib_qor.workbench.app import create_app
ROOT=Path(__file__).resolve().parents[1]

class L1WebTests(unittest.TestCase):
    def test_global_page_does_not_offer_unscoped_ip_navigation(self):
        with tempfile.TemporaryDirectory() as d:
            client=create_app(ROOT/'examples/pipeline',Path(d)/'runs',ROOT/'examples/work').test_client()
            body=client.get('/').get_data(as_text=True)
            self.assertNotIn('>01 IP 总览</a>',body)
            self.assertNotIn('>03 检查与验收</a>',body)
            body=client.get('/?vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs').get_data(as_text=True)
            self.assertIn('>01 IP 总览</a>',body)
    def test_missing_raw_and_version_config_explain_blockers(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);work=root/'work';work.mkdir();raw=root/'raw';raw.mkdir();(raw/'file.lef').write_text('LEF')
            source={'vendor_id':'v','source_library_id':'lib','root':str(raw)}
            (work/'scan_sources.json').write_text(json.dumps({'sources':[source]}))
            client=create_app(ROOT/'examples/pipeline',root/'runs',work).test_client()
            with client.session_transaction() as session: session['csrf']='token'
            self.assertEqual(client.post('/scan',data={'csrf':'token','vendor':'v','library':'lib'}).status_code,303)
            body=client.get('/library?vendor=v&library=lib').get_data(as_text=True)
            self.assertIn('没有识别出交付版本目录',body);self.assertIn('尚未建立该来源库与 BusinessIP',body)
            (raw/'file.lef').unlink();raw.rmdir()
            self.assertEqual(client.post('/scan',data={'csrf':'token','vendor':'v','library':'lib'}).status_code,303)
            body=client.get('/library?vendor=v&library=lib').get_data(as_text=True)
            self.assertIn('FAILED',body);self.assertIn('扫描未完整完成',body)
            self.assertFalse(list(work.glob('libraries/*/*/delivery_*.json')))

    def test_existing_library_connects_to_ip_workbench(self):
        with tempfile.TemporaryDirectory() as d:
            client=create_app(ROOT/'examples/pipeline',Path(d)/'runs',ROOT/'examples/work').test_client()
            response=client.get('/library?vendor=vendor_orion&library=lib_rtavfs')
            self.assertEqual(response.status_code,200)
            body=response.get_data(as_text=True)
            self.assertIn('aria-label="供应商和库"',body)
            self.assertIn('aria-current="page"',body)
            self.assertIn('ip=rtavfs',body);self.assertIn('rev_0002',body)
            ip=client.get('/?view=overview&vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs')
            self.assertEqual(ip.status_code,200);self.assertIn('当前有效文件矩阵',ip.get_data(as_text=True))
            self.assertIn('/library?vendor=vendor_orion&amp;library=lib_rtavfs',ip.get_data(as_text=True))
            self.assertIn('aria-label="当前位置"',ip.get_data(as_text=True))
            ip=client.get('/?view=checks&vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs&revision=rev_0001')
            from html.parser import HTMLParser
            from urllib.parse import parse_qs, urlparse
            class ScopeLinks(HTMLParser):
                def __init__(self): super().__init__(); self.active=False; self.links=[]
                def handle_starttag(self,tag,attrs):
                    attrs=dict(attrs)
                    if tag=='nav' and attrs.get('aria-label')=='库与 IP 视角切换': self.active=True
                    if self.active and tag=='a': self.links.append(attrs.get('href',''))
                def handle_endtag(self,tag):
                    if tag=='nav': self.active=False
            links=ScopeLinks();links.feed(ip.get_data(as_text=True))
            self.assertTrue(any(parse_qs(urlparse(link).query).get('revision')==['rev_0001'] for link in links.links))

    def test_library_workspace_is_accessible_without_an_ip(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);work=root/'work';work.mkdir();raw=root/'raw';p=raw/'V07/lef/core.lef';p.parent.mkdir(parents=True);p.write_text('LEF')
            (work/'scan_sources.json').write_text(json.dumps({'sources':[{'vendor_id':'v','source_library_id':'lib','root':str(raw),'version_paths':{'V07':'V07'}}]}))
            client=create_app(ROOT/'examples/pipeline',root/'runs',work).test_client()
            with client.session_transaction() as session: session['csrf']='token'
            self.assertEqual(client.post('/scan',data={'csrf':'token','vendor':'v','library':'lib'}).status_code,303)
            overview=client.get('/').get_data(as_text=True)
            self.assertIn('/library?vendor=v&amp;library=lib',overview)
            response=client.get('/library?vendor=v&library=lib')
            self.assertEqual(response.status_code,200)
            body=response.get_data(as_text=True)
            for text in ('库工作台','V07','core.lef','未确认','尚无已登记 IP'): self.assertIn(text,body)
            self.assertEqual(client.get('/library?vendor=v&library=unknown').status_code,404)

    def test_scan_then_formal_sync_and_read_only_refresh(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); work=root/'work';work.mkdir();raw=root/'raw';target=raw/'V07/core.lef';target.parent.mkdir(parents=True);target.write_text('LEF')
            formal=root/'formal';formal.mkdir();(formal/'core.lef').symlink_to(target)
            (work/'scan_sources.json').write_text(json.dumps({'sources':[{'vendor_id':'v','source_library_id':'lib','root':str(raw),'version_paths':{'V07':'V07'},'file_mapping':{'V07/core.lef':{'file_key':'lib:lef:core'}}}]}))
            (work/'formal_sources.json').write_text(json.dumps({'sources':[{'formal_nl_id':'NL1','root':str(formal)}]}))
            client=create_app(ROOT/'examples/pipeline',root/'runs',work).test_client()
            with client.session_transaction() as session: session['csrf']='token'
            self.assertEqual(client.get('/').status_code,200); self.assertFalse(list(work.glob('libraries/*/*/delivery_*.json')))
            self.assertEqual(client.post('/scan',data={'csrf':'token','vendor':'v','library':'lib'}).status_code,303)
            record=json.loads(next(work.glob('libraries/*/*/delivery_*.json')).read_text())
            self.assertEqual(record['files'][0]['file_key'],'lib:lef:core')
            self.assertEqual(client.post('/formal-sync',data={'csrf':'token','formal_nl_id':'NL1'}).status_code,303)
            observation=json.loads(next((root/'runs/formal_observations').glob('*.json')).read_text())
            self.assertEqual(observation['files'][0]['source']['delivery_id'],record['delivery_id'])
            snapshot=json.loads(next((work/'libraries/v/lib').glob('formal_NL1_*.json')).read_text())
            self.assertEqual(snapshot['coverage'],'PARTIAL')
            self.assertEqual(snapshot['linked_files'][0]['source_ref']['delivery_id'],record['delivery_id'])
            before=set(root.rglob('*')); page=client.get('/').get_data(as_text=True); after=set(root.rglob('*'))
            self.assertEqual(before,after)
            for value in ('RAW 来源','Formal NL 来源','输出目录','NL1','v / lib / 归属未知'): self.assertIn(value,page)
