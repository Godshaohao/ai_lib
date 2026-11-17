import json
import os
import tempfile
import unittest
from pathlib import Path

from ai_lib_qor.workbench.app import create_app

ROOT = Path(__file__).resolve().parents[1]

class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plans = self.root / 'plans'
        self.plans.mkdir()
        example = json.loads((ROOT / 'examples/pipeline/check_effective.example.json').read_text())
        for key in ('target_revision', 'baseline_revision'):
            example[key] = str(ROOT / example[key])
        example['formal_snapshots'] = [str(ROOT / x) for x in example['formal_snapshots']]
        for row in example['comparisons']:
            for key in ('old_facts', 'new_facts'): row[key] = str(ROOT / row[key])
        for row in example['pin_pairs']:
            for key in ('lef_facts', 'liberty_facts'): row[key] = str(ROOT / row[key])
        (self.plans / 'check.json').write_text(json.dumps(example), encoding='utf-8')
        self.app = create_app(self.plans, self.root / 'runs')
        self.app.testing = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session['csrf'] = 'test-token'

    def test_check_report_and_download(self):
        page = self.client.get('/?view=manual')
        self.assertEqual(page.status_code, 200)
        self.assertIn('check.json', page.get_data(as_text=True))
        run = self.client.post('/runs', data={'plan':'check.json', 'csrf':'test-token'})
        self.assertEqual(run.status_code, 303)
        detail = self.client.get(run.location)
        self.assertEqual(detail.status_code, 200)
        self.assertIn('rev_0002', detail.get_data(as_text=True))
        for name in ('check.json', 'report.html', 'report.xlsx'):
            response = self.client.get(run.location + '/artifacts/' + name)
            self.assertEqual(response.status_code, 200, name)
            response.close()
        history = self.client.get('/?view=history').get_data(as_text=True)
        self.assertIn('rev_0002', history)

    def test_rejects_invalid_token_and_plan_path(self):
        self.assertEqual(self.client.post('/runs', data={'plan':'check.json'}).status_code, 403)
        self.assertEqual(self.client.post('/runs', data={'plan':'../check.json', 'csrf':'test-token'}).status_code, 400)
        self.assertEqual(self.client.get('/runs/../../etc/passwd/artifacts/check.json').status_code, 404)

    def test_failed_run_is_visible_without_fabricated_outputs(self):
        (self.plans / 'bad.json').write_text('{}', encoding='utf-8')
        run = self.client.post('/runs', data={'plan':'bad.json', 'csrf':'test-token'})
        self.assertEqual(run.status_code, 303)
        page = self.client.get(run.location)
        self.assertIn('失败', page.get_data(as_text=True))
        self.assertEqual(self.client.get(run.location + '/artifacts/report.xlsx').status_code, 404)

if __name__ == '__main__': unittest.main()

class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = create_app(ROOT / 'examples/pipeline', Path(self.temp.name) / 'runs', ROOT / 'examples/work').test_client()

    def test_ip_navigation_and_v3_delivery_matrix(self):
        response = self.client.get('/?vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs')
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        for value in ('库与 IP', 'IP 总览', '检查与验收', '正式库快照', '文件出现历史', 'lib_rtavfs:lef:core', 'dlv_20261019_001', 'rev_0002', 'rev_0001'):
            self.assertIn(value, text)

    def test_primary_navigation_preserves_selected_revision(self):
        from html.parser import HTMLParser
        from urllib.parse import parse_qs, urlparse

        class Links(HTMLParser):
            def __init__(self):
                super().__init__(); self.hrefs = []; self.in_primary = False
            def handle_starttag(self, tag, attrs):
                if tag == 'nav' and dict(attrs).get('aria-label') == '工作台功能': self.in_primary = True
                if tag == 'a' and self.in_primary: self.hrefs.append(dict(attrs).get('href', ''))
            def handle_endtag(self, tag):
                if tag == 'nav': self.in_primary = False

        page = self.client.get('/?view=overview&vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs&revision=rev_0001')
        links = Links(); links.feed(page.get_data(as_text=True))
        for view in ('overview', 'analysis', 'checks'):
            candidates = [parse_qs(urlparse(href).query) for href in links.hrefs]
            self.assertTrue(any(q.get('view') == [view] and q.get('revision') == ['rev_0001'] for q in candidates), view)

    def test_delivery_comparison_and_formal_are_explicit(self):
        url = '/?vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs'
        compare = self.client.get(url + '&view=compare&base=dlv_20260907_001&target=dlv_20261019_001').get_data(as_text=True)
        self.assertIn('交付对比', compare)
        self.assertIn('lib_rtavfs:lef:core', compare)
        formal = self.client.get(url + '&view=formal&snapshot=NL2.5.3/snap_nl253_0001').get_data(as_text=True)
        self.assertIn('snap_nl253_0001', formal)
        self.assertIn('nf001', formal)

    def test_reject_unknown_catalog_selection(self):
        self.assertEqual(self.client.get('/?vendor=../../etc&library=x&ip=y').status_code, 400)

    def test_effective_version_history_and_revision_details(self):
        base = '/?vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs&view=versions'
        page = self.client.get(base + '&revision=rev_0002')
        self.assertEqual(page.status_code, 200)
        body = page.get_data(as_text=True)
        for value in ('有效版本', 'rev_0001', 'rev_0002', '最新计算', '当前采纳', '成员文件', 'lib_rtavfs:liberty:func_ff', 'snap_nl253_0001', 'dlv_20261019_001', 'ip_owner'):
            self.assertIn(value, body)
        previous = self.client.get(base + '&revision=rev_0001').get_data(as_text=True)
        self.assertIn('FORMAL_BASELINE', previous)
        self.assertIn('nf001', previous)
        self.assertEqual(self.client.get(base + '&revision=unknown').status_code, 400)

    def test_delivery_history_displays_recorded_delivery_semantics(self):
        page = self.client.get('/?view=deliveries&vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs')
        body = page.get_data(as_text=True)
        for value in ('交付版本', 'V07', 'V08', 'INCREMENTAL', 'dlv_20261019_001', 'rev_0002'):
            self.assertIn(value, body)

    def test_parse_registered_delivery_file_in_workbench(self):
        import shutil
        root = Path(self.temp.name)
        work = root/'work'; shutil.copytree(ROOT/'examples/work', work)
        delivery_path = work/'vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20261019_001/delivery.json'
        delivery = json.loads(delivery_path.read_text())
        raw = root/'raw'; (raw/'lef').mkdir(parents=True)
        (raw/'lef/core.lef').write_text('MACRO MAC_A\n SIZE 4 BY 8 ;\n PIN A\n DIRECTION INPUT ;\n END A\n END MAC_A\n')
        delivery['source_root']=str(raw); delivery_path.write_text(json.dumps(delivery))
        app=create_app(ROOT/'examples/pipeline',root/'evidence_runs',work);app.testing=True;client=app.test_client()
        with client.session_transaction() as session: session['csrf']='token'
        page=client.get('/?view=deliveries&vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs').get_data(as_text=True)
        self.assertIn('提取解析证据',page)
        response=client.post('/evidence',data={'csrf':'token','vendor':'vendor_orion','library':'lib_rtavfs','ip':'rtavfs','delivery':'dlv_20261019_001','file_id':'f001'})
        self.assertEqual(response.status_code,303)
        detail=client.get(response.location).get_data(as_text=True)
        self.assertIn('parser_evidence.json',detail)
        self.assertIn('parser_evidence.html',detail)
        evidence=client.get(response.location+'/artifacts/parser_evidence.json')
        self.assertEqual(evidence.status_code,200)
        self.assertEqual(evidence.get_json()['view'],'LEF')
        evidence.close()

    def test_version_member_filters_and_change_meaning(self):
        base='/?vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs&view=versions&revision=rev_0002'
        page=self.client.get(base+'&source=FORMAL&file_view=LIBERTY').get_data(as_text=True)
        self.assertIn('lib_rtavfs:liberty:func_ff',page)
        self.assertNotIn('lib_rtavfs:lef:core',page)
        self.assertIn('1 / 3',page)
        page=self.client.get(base+'&q=core&change=REPLACED').get_data(as_text=True)
        self.assertIn('lib_rtavfs:lef:core',page)
        self.assertNotIn('lib_rtavfs:liberty:func_ff',page)
        self.assertIn('替换',page)
        empty=self.client.get(base+'&q=no_such_member').get_data(as_text=True)
        self.assertIn('没有符合筛选条件的文件',empty)
        self.assertEqual(self.client.get(base+'&source=invalid').status_code,400)

    def test_sidebar_groups_vendor_library_and_isolates_repeated_ip(self):
        import shutil
        root=Path(self.temp.name);work=root/'grouped';shutil.copytree(ROOT/'examples/work',work)
        src=work/'vendors/vendor_orion/libraries/lib_rtavfs'
        other=work/'vendors/vendor_vega/libraries/lib_other';other.parent.mkdir(parents=True)
        shutil.copytree(src,other)
        for path in other.rglob('*.json'):
            path.write_text(path.read_text().replace('vendor_orion','vendor_vega').replace('lib_rtavfs','lib_other'))
        for path in other.rglob('*.jsonl'):
            path.write_text(path.read_text().replace('vendor_orion','vendor_vega').replace('lib_rtavfs','lib_other'))
        app=create_app(ROOT/'examples/pipeline',root/'group_runs',work);app.testing=True;client=app.test_client()
        response=client.get('/?view=versions&vendor=vendor_vega&library=lib_other&ip=rtavfs')
        self.assertEqual(response.status_code,200)
        body=response.get_data(as_text=True)
        self.assertIn('data-vendor="vendor_orion"',body)
        self.assertIn('data-vendor="vendor_vega"',body)
        self.assertIn('data-library="lib_other"',body)
        self.assertIn('lib_other:lef:core',body)
        self.assertNotIn('lib_rtavfs:lef:core',body)
        self.assertIn('aria-current="page"',body)

        from html.parser import HTMLParser
        class Groups(HTMLParser):
            def __init__(self): super().__init__(); self.groups = {}
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'details' and ('data-vendor' in attrs or 'data-library' in attrs):
                    self.groups[attrs.get('data-vendor', attrs.get('data-library'))] = 'open' in attrs
        groups = Groups(); groups.feed(body)
        self.assertFalse(groups.groups['vendor_orion'])
        self.assertTrue(groups.groups['vendor_vega'])
        self.assertTrue(groups.groups['lib_other'])
        groups = Groups(); groups.feed(client.get('/?view=discover').get_data(as_text=True))
        self.assertFalse(any(groups.groups.values()))

    def test_version_corner_filter_uses_recorded_delivery_mapping(self):
        base='/?vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs&view=versions&revision=rev_0002'
        page=self.client.get(base+'&corner=tt').get_data(as_text=True)
        self.assertIn('lib_rtavfs:liberty:func_tt',page)
        self.assertNotIn('lib_rtavfs:lef:core',page)
        self.assertNotIn('lib_rtavfs:liberty:func_ff',page)
        self.assertIn('1 / 3',page)
        self.assertEqual(self.client.get(base+'&corner=unlisted').status_code,400)

    def test_output_paths_and_open_only_known_run_directory(self):
        from unittest.mock import patch
        with self.client.session_transaction() as session: session['csrf']='token'
        run=self.client.post('/runs',data={'plan':'check_effective.example.json','csrf':'token'})
        self.assertEqual(run.status_code,303)
        page=self.client.get(run.location).get_data(as_text=True)
        self.assertIn('输出目录',page);self.assertIn('打开文件夹',page)
        with patch('ai_lib_qor.workbench.app.subprocess.run') as launch:
            launch.return_value.returncode=0
            result=self.client.post(run.location+'/open-folder',data={'csrf':'token'})
            self.assertEqual(result.status_code,303)
            cmd=launch.call_args.args[0]
            self.assertEqual(cmd[0],'xdg-open'); self.assertTrue(cmd[1].endswith(run.location.rsplit('/',1)[-1]))
        self.assertEqual(self.client.post('/runs/not_a_run/open-folder',data={'csrf':'token'}).status_code,404)
        self.assertEqual(self.client.post(run.location+'/open-folder').status_code,403)

    def test_version_page_lists_matched_check_plan_and_rejects_other_revision(self):
        with self.client.session_transaction() as session:session['csrf']='token'
        args={'vendor':'vendor_orion','library':'lib_rtavfs','ip':'rtavfs','revision':'rev_0002','plan':'check_effective.example.json','csrf':'token'}
        page=self.client.get('/?view=catalog&vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs').get_data(as_text=True)
        self.assertIn('单版本检查',page);self.assertIn('整体 IP 报告',page);self.assertIn('rev_0002',page)
        wrong=self.client.post('/version-run',data={**args,'revision':'rev_0001'})
        self.assertEqual(wrong.status_code,400)
        run=self.client.post('/version-run',data=args)
        self.assertEqual(run.status_code,303)
        detail=self.client.get(run.location).get_data(as_text=True)
        self.assertIn('rev_0002',detail);self.assertIn('report.xlsx',detail)

    def test_batch_rejects_incomplete_plans_and_builds_aggregate_when_ready(self):
        root=Path(self.temp.name);plans=root/'batch_plans';plans.mkdir()
        rootdir=ROOT/'examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/versions'
        snap=ROOT/'examples/work/formal_nl/NL2.5.3/snapshots/snap_nl253_0001.json'
        old=ROOT/'examples/file_facts/facts_core_v07.json';new=ROOT/'examples/file_facts/facts_core_v08.json';lib=ROOT/'examples/file_facts/facts_tt_v08.json'
        common={'ruleset_id':'test','run_at':'2026-10-20T00:00:00Z','formal_snapshots':[str(snap)]}
        first={**common,'run_id':'r1','target_revision':str(rootdir/'rev_0001.json'),'baseline_revision':str(rootdir/'rev_0001.json'),'comparisons':[{'file_key':'lib_rtavfs:lef:core','old_facts':str(old),'new_facts':str(old)}],'pin_pairs':[]}
        second={**common,'run_id':'r2','target_revision':str(rootdir/'rev_0002.json'),'baseline_revision':str(rootdir/'rev_0001.json'),'comparisons':[{'file_key':'lib_rtavfs:lef:core','old_facts':str(old),'new_facts':str(new)}],'pin_pairs':[{'lef_key':'lib_rtavfs:lef:core','liberty_key':'lib_rtavfs:liberty:func_tt','lef_facts':str(new),'liberty_facts':str(lib)}]}
        (plans/'r2.json').write_text(json.dumps(second))
        app=create_app(plans,root/'batch_runs',ROOT/'examples/work');app.testing=True;client=app.test_client()
        with client.session_transaction() as sess:sess['csrf']='token'
        data={'csrf':'token','vendor':'vendor_orion','library':'lib_rtavfs','ip':'rtavfs'}
        self.assertEqual(client.post('/ip-run',data=data).status_code,400)
        self.assertEqual(list((root/'batch_runs').glob('run_*')),[])
        (plans/'r1.json').write_text(json.dumps(first))
        response=client.post('/ip-run',data=data)
        self.assertEqual(response.status_code,303)
        text=client.get(response.location).get_data(as_text=True)
        self.assertIn('整体 IP 报告',text);self.assertIn('overall.xlsx',text)
        summary=client.get('/?view=checks&vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs').get_data(as_text=True)
        self.assertIn('最近一次整体报告',summary);self.assertIn(response.location,summary)
        result=client.get(response.location+'/artifacts/overall.xlsx');self.assertEqual(result.status_code,200)
        from openpyxl import load_workbook
        import io
        wb=load_workbook(io.BytesIO(result.data),data_only=True)
        values='\n'.join(str(x) for sheet in wb for row in sheet.values for x in row if x is not None)
        self.assertIn('rev_0001',values);self.assertIn('rev_0002',values);self.assertIn('不代表全部检查通过',values)
        wb.close();result.close()

    def test_batch_retains_failed_child_and_summarizes_remaining_versions(self):
        root=Path(self.temp.name);plans=root/'partial_plans';plans.mkdir()
        revs=ROOT/'examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/versions'
        plan=json.loads((ROOT/'examples/pipeline/check_effective.example.json').read_text())
        for k in ('target_revision','baseline_revision'):plan[k]=str(ROOT/plan[k])
        plan['formal_snapshots']=[str(ROOT/x) for x in plan['formal_snapshots']]
        for row in plan['comparisons']:
            for k in ('old_facts','new_facts'):row[k]=str(ROOT/row[k])
        for row in plan['pin_pairs']:
            for k in ('lef_facts','liberty_facts'):row[k]=str(ROOT/row[k])
        (plans/'r2.json').write_text(json.dumps(plan))
        (plans/'r1.json').write_text(json.dumps({'target_revision':str(revs/'rev_0001.json')}))
        app=create_app(plans,root/'partial_runs',ROOT/'examples/work');app.testing=True;client=app.test_client()
        with client.session_transaction() as session:session['csrf']='token'
        response=client.post('/ip-run',data={'csrf':'token','vendor':'vendor_orion','library':'lib_rtavfs','ip':'rtavfs'})
        self.assertEqual(response.status_code,303)
        body=client.get(response.location).get_data(as_text=True)
        self.assertIn('部分失败',body);self.assertIn('rev_0001',body);self.assertIn('rev_0002',body)
        run_dir=root/'partial_runs'/response.location.rsplit('/',1)[-1]
        data=json.loads((run_dir/'overall.json').read_text())
        self.assertEqual([(x['revision'],x['state']) for x in data['versions']],[('rev_0001','FAILED'),('rev_0002','SUCCEEDED')])

    def test_file_location_filter_history_and_formal_context(self):
        base='/?vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs'
        file_page=self.client.get(base+'&view=files&file_q=func_ff').get_data(as_text=True)
        self.assertIn('lib_rtavfs:liberty:func_ff',file_page)
        self.assertNotIn('lib_rtavfs:lef:core',file_page)
        self.assertIn('V07',file_page)
        compare=self.client.get(base+'&view=compare&base=dlv_20260907_001&target=dlv_20261019_001').get_data(as_text=True)
        self.assertIn('目标交付未列出',compare)
        formal=self.client.get(base+'&view=formal&snapshot=NL2.5.3/snap_nl253_0001').get_data(as_text=True)
        self.assertIn('2026-09-09T10:00:00+08:00',formal)
        self.assertIn('lib_rtavfs',formal)
        self.assertIn('/example/raw/vendor_orion/lib_rtavfs/V07/lef/core.lef',formal)

    def test_history_defaults_to_selected_ip_and_discloses_unbound(self):
        run_dir=Path(self.temp.name)/'runs'
        for ident,owner in [('a'*32,{'vendor':'vendor_orion','library':'lib_rtavfs','ip':'rtavfs'}),('b'*32,{'vendor':'another','library':'lib_rtavfs','ip':'rtavfs'}),('c'*32,None)]:
            path=run_dir/('run_'+ident);path.mkdir()
            status={'id':path.name,'plan':ident,'state':'SUCCEEDED','started_at':'2026-01-01','target':'rev_0002'}
            if owner:status['owner']=owner
            (path/'status.json').write_text(json.dumps(status))
        page=self.client.get('/?view=history&vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs').get_data(as_text=True)
        self.assertIn('a'*32,page);self.assertNotIn('b'*32,page);self.assertNotIn('c'*32,page)
        all_page=self.client.get('/?view=history&history_scope=all&vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs').get_data(as_text=True)
        self.assertIn('b'*32,all_page);self.assertIn('未关联',all_page)

    def test_compare_duplicate_file_keys_are_not_silently_overwritten(self):
        import copy
        from ai_lib_qor.workbench.catalog import compare_rows, file_rows
        root=ROOT/'examples/work/vendors/vendor_orion/libraries/lib_rtavfs/deliveries'
        a=json.loads((root/'dlv_20260907_001/delivery.json').read_text())
        b=json.loads((root/'dlv_20261019_001/delivery.json').read_text())
        duplicate=copy.deepcopy(b['files'][0]);duplicate['file_id']='different';duplicate['relative_path']='lef/duplicate.lef';b['files'].append(duplicate)
        rows=compare_rows([a,b],a['delivery_id'],b['delivery_id'])
        row=next(x for x in rows if x['key']==duplicate['file_key'])
        self.assertEqual(row['relation'],'文件位不唯一')
        self.assertIsNone(row['target'])
        file_row=next(x for x in file_rows([a,b]) if x['key']==duplicate['file_key'])
        self.assertTrue(file_row['ambiguous'])
        self.assertEqual(file_row['previous'],a['delivery_id'])

    def test_formal_snapshot_catalog_selection_and_file_filters(self):
        base='/?view=formal&vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs'
        page=self.client.get(base).get_data(as_text=True)
        for item in ('正式快照','snap_nl253_0001','snap_nl253_0002','声明范围','观察时间'):
            self.assertIn(item,page)
        page=self.client.get(base+'&snapshot=NL2.5.3/snap_nl253_0002&formal_q=func_ff').get_data(as_text=True)
        self.assertIn('lib_rtavfs:liberty:func_ff',page)
        self.assertNotIn('lib_rtavfs:lef:core',page)
        self.assertIn('1 / 3',page)
        self.assertIn('snap_nl253_0001',page)
        self.assertIn('只反映',page)

    def test_formal_duplicate_snapshot_identity_not_silently_selected(self):
        import shutil
        root=Path(self.temp.name);work=root/'ambiguous_work';shutil.copytree(ROOT/'examples/work',work)
        folder=work/'formal_nl/NL2.5.3/snapshots'
        (folder/'snap_nl253_0001').mkdir();shutil.copy(folder/'snap_nl253_0001.json',folder/'snap_nl253_0001/snapshot.json')
        app=create_app(ROOT/'examples/pipeline',root/'ambiguous_runs',work);app.testing=True;client=app.test_client()
        page=client.get('/?view=formal&snapshot=NL2.5.3/snap_nl253_0001')
        self.assertEqual(page.status_code,400)

    def test_task_navigation_groups_without_duplicate_entries(self):
        url='/?vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs'
        page=self.client.get(url+'&view=files').get_data(as_text=True)
        for label in ('库更新中心','IP 总览','文件与 Macro','检查与验收','已登记交付'):
            self.assertIn(label,page)
        for label in ('检查工作区','正式 NL','库与版本','正式来源'):
            self.assertNotIn('>'+label+'</a>',page)
        self.assertIn('文件定位',page);self.assertIn('交付对比',page);self.assertIn('已登记交付',page)
        formal=self.client.get(url+'&view=formal').get_data(as_text=True)
        self.assertNotIn('aria-label="业务视角"',formal)
        checks=self.client.get(url+'&view=checks').get_data(as_text=True)
        self.assertIn('单版本检查',checks);self.assertIn('整体 IP 报告',checks);self.assertIn('运行记录',checks)
        deliveries=self.client.get(url+'&view=deliveries').get_data(as_text=True)
        self.assertIn('V07',deliveries);self.assertIn('V08',deliveries)
        self.assertEqual(self.client.get(url+'&view=manual').status_code,200)
        self.assertEqual(self.client.get(url+'&view=catalog').status_code,200)

    def test_end_to_end_navigation_and_version_report(self):
        from io import BytesIO
        from openpyxl import load_workbook
        p='vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs'
        loc=self.client.get('/?view=files&'+p+'&file_q=func_ff').get_data(as_text=True)
        self.assertIn('lib_rtavfs:liberty:func_ff',loc)
        cmp=self.client.get('/?view=compare&'+p+'&base=dlv_20260907_001&target=dlv_20261019_001').get_data(as_text=True)
        self.assertIn('目标交付未列出',cmp)
        delivery=self.client.get('/?view=deliveries&'+p).get_data(as_text=True)
        self.assertIn('V07',delivery);self.assertIn('V08',delivery)
        version=self.client.get('/?view=versions&'+p+'&revision=rev_0002&corner=ff').get_data(as_text=True)
        self.assertIn('lib_rtavfs:liberty:func_ff',version)
        formal=self.client.get('/?view=formal&'+p+'&snapshot=NL2.5.3/snap_nl253_0001').get_data(as_text=True)
        self.assertIn('snap_nl253_0001',formal)
        page=self.client.get('/?view=checks&'+p).get_data(as_text=True)
        self.assertIn('check_effective.example.json',page)
        with self.client.session_transaction() as session:session['csrf']='token'
        response=self.client.post('/version-run',data={'csrf':'token','vendor':'vendor_orion','library':'lib_rtavfs','ip':'rtavfs','revision':'rev_0002','plan':'check_effective.example.json'})
        self.assertEqual(response.status_code,303)
        detail=self.client.get(response.location).get_data(as_text=True)
        self.assertIn('report.xlsx',detail);self.assertIn('输出目录',detail)
        self.assertIn('view=checks&amp;revision=rev_0002&amp;vendor=vendor_orion', detail)
        excel=self.client.get(response.location+'/artifacts/report.xlsx')
        self.assertEqual(excel.status_code,200)
        workbook=load_workbook(BytesIO(excel.data),read_only=True,data_only=True)
        self.assertIn('00-概览',workbook.sheetnames);workbook.close();excel.close()
        history=self.client.get('/?view=history&'+p).get_data(as_text=True)
        self.assertIn(response.location.rsplit('/',1)[-1],history)
        self.assertEqual(self.client.get('/outputs').status_code,200)

    def test_selected_revision_links_to_its_check_row(self):
        p='vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs'
        page=self.client.get('/?view=versions&revision=rev_0002&'+p).get_data(as_text=True)
        self.assertIn('#check-rev_0002',page)
        checks=self.client.get('/?view=checks&'+p).get_data(as_text=True)
        self.assertIn('id="check-rev_0002"',checks)

    def test_overall_report_readiness_names_missing_versions(self):
        p='vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs'
        page=self.client.get('/?view=checks&'+p).get_data(as_text=True)
        self.assertIn('1 / 2',page)
        self.assertIn('rev_0001',page)
        self.assertIn('缺少计划',page)
        self.assertIn('计划目录',page)
        self.assertIn('整体报告的输出',page)

    def test_bound_run_offers_return_to_same_ip(self):
        with self.client.session_transaction() as session:session['csrf']='token'
        data={'csrf':'token','vendor':'vendor_orion','library':'lib_rtavfs','ip':'rtavfs','revision':'rev_0002','plan':'check_effective.example.json'}
        response=self.client.post('/version-run',data=data)
        body=self.client.get(response.location).get_data(as_text=True)
        self.assertIn('返回当前 IP 的检查与报告',body)
        self.assertIn('view=checks',body)
        self.assertIn('vendor=vendor_orion',body)

    def test_failed_bound_version_run_appears_on_revision_row(self):
        root=Path(self.temp.name)/'runs';folder=root/('run_'+'d'*32);folder.mkdir()
        (folder/'status.json').write_text(json.dumps({'id':folder.name,'owner':{'vendor':'vendor_orion','library':'lib_rtavfs','ip':'rtavfs'},'expected_revision':'rev_0002','plan':'bad','state':'FAILED','started_at':'2026-01-01'}))
        page=self.client.get('/?view=checks&vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs').get_data(as_text=True)
        self.assertIn('/runs/'+folder.name,page)

    def test_report_context_from_explicit_plan_is_displayed(self):
        root=Path(self.temp.name);plans=root/'context_plans';plans.mkdir()
        plan=json.loads((ROOT/'examples/pipeline/check_effective.example.json').read_text())
        for k in ('target_revision','baseline_revision'):plan[k]=str(ROOT/plan[k])
        plan['formal_snapshots']=[str(ROOT/x) for x in plan['formal_snapshots']]
        for row in plan['comparisons']:
            for k in ('old_facts','new_facts'):row[k]=str(ROOT/row[k])
        for row in plan['pin_pairs']:
            for k in ('lef_facts','liberty_facts'):row[k]=str(ROOT/row[k])
        lib=ROOT/'examples/work/vendors/vendor_orion/libraries/lib_rtavfs'
        plan['report_deliveries']=[str(lib/'deliveries/dlv_20260907_001/delivery.json'),str(lib/'deliveries/dlv_20261019_001/delivery.json')]
        plan['report_formal_snapshot']=str(ROOT/'examples/work/formal_nl/NL2.5.3/snapshots/snap_nl253_0002.json')
        plan['report_effective_index']=str(lib/'ips/rtavfs/effective/index.json')
        plan['report_accepted_revision']=str(lib/'ips/rtavfs/effective/versions/rev_0001.json')
        (plans/'p.json').write_text(json.dumps(plan))
        app=create_app(plans,root/'ctx_runs',ROOT/'examples/work');app.testing=True;client=app.test_client()
        with client.session_transaction() as session:session['csrf']='token'
        response=client.post('/version-run',data={'csrf':'token','vendor':'vendor_orion','library':'lib_rtavfs','ip':'rtavfs','revision':'rev_0002','plan':'p.json'})
        self.assertEqual(response.status_code,303)
        from openpyxl import load_workbook
        from io import BytesIO
        download=client.get(response.location+'/artifacts/report.xlsx');self.assertEqual(download.status_code,200)
        wb=load_workbook(BytesIO(download.data),read_only=True,data_only=True)
        self.assertEqual(wb['00-概览']['L5'].value,'rev_0001')
        self.assertIn('NL2.5.3',str(list(wb['07-正式文件'].values)))
        self.assertIn('V08',str(list(wb['文件版本矩阵'].values)))
        wb.close();download.close()

    def test_overall_report_does_not_count_changes_without_baseline(self):
        from ai_lib_qor.reporting.overall_excel import render_overall_excel
        from openpyxl import load_workbook
        path=Path(self.temp.name)/'out.xlsx'
        render_overall_excel({'vendor':'v','library':'l','ip':'i'},[{'revision':'rev_1','baseline':None,'state':'SUCCEEDED','run_id':'r','plan':'x','summary':{'files_with_new_source':0,'files_with_confirmed_content_change':0,'failed_checks':0,'inconclusive_checks':0}}],path)
        wb=load_workbook(path,read_only=True,data_only=True);row=list(wb['版本运行汇总'].values)[3]
        self.assertEqual(row[4:6],('未对比','未对比'));wb.close()

    def test_overall_workbook_wraps_scope_and_marks_initial_uncompared(self):
        from ai_lib_qor.reporting.overall_excel import render_overall_excel
        from openpyxl import load_workbook
        path=Path(self.temp.name)/'layout.xlsx'
        rows=[{'revision':'rev_1','baseline':None,'state':'SUCCEEDED','run_id':'r','plan':'p','summary':{'files_with_new_source':0,'files_with_confirmed_content_change':0,'failed_checks':0,'inconclusive_checks':0},'note':'范围说明 '*30}]
        render_overall_excel({'vendor':'v','library':'l','ip':'i'},rows,path)
        wb=load_workbook(path);s=wb['版本运行汇总']
        self.assertEqual(s['E4'].value,'未对比');self.assertTrue(s['J4'].alignment.wrap_text)
        self.assertGreaterEqual(s.row_dimensions[4].height,45)
        self.assertIn('A2:K2',str(s.merged_cells.ranges));wb.close()

    def test_completed_batch_discloses_quality_failures_on_checks_page(self):
        root=Path(self.temp.name)/'runs';folder=root/('run_'+'e'*32);folder.mkdir()
        status={'id':folder.name,'owner':{'vendor':'vendor_orion','library':'lib_rtavfs','ip':'rtavfs'},'target':'rtavfs','target_kind':'IP_VERSION_BATCH','plan':'整体 IP 报告','state':'SUCCEEDED','started_at':'2026-01-01','children':[{'id':'run_'+'f'*32,'revision':'rev_0002','state':'SUCCEEDED','summary':{'failed_checks':1,'inconclusive_checks':0}}]}
        (folder/'status.json').write_text(json.dumps(status))
        page=self.client.get('/?view=checks&vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs').get_data(as_text=True)
        self.assertIn('1 项检查失败',page)
        self.assertIn('执行完成',page)

    def test_actual_run_id_and_time_are_recorded_not_reused_from_plan(self):
        with self.client.session_transaction() as session:session['csrf']='token'
        data={'csrf':'token','vendor':'vendor_orion','library':'lib_rtavfs','ip':'rtavfs','revision':'rev_0002','plan':'check_effective.example.json'}
        response=self.client.post('/version-run',data=data)
        root=Path(self.temp.name)/'runs'/response.location.rsplit('/',1)[-1]
        status=json.loads((root/'status.json').read_text());check=json.loads((root/'check.json').read_text())
        self.assertEqual(check['check_run_id'],status['id'])
        self.assertEqual(check['run_at'],status['started_at'])
        self.assertEqual(json.loads((root/'input_plan.json').read_text())['run_id'],status['id'])

class VersionWorkspaceRequirements(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.client=create_app(ROOT/'examples/pipeline',Path(self.temp.name)/'runs',ROOT/'examples/work').test_client()

    def test_version_timeline_exposes_file_view_and_check_baseline(self):
        body=self.client.get('/?view=checks&vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs').get_data(as_text=True)
        for expected in ('版本时间线','rev_0001','rev_0002','LIBERTY','检查基线','运行单版本检查'):
            self.assertIn(expected,body)

    def test_nl_comparison_identifies_source_relationship_not_content_equality(self):
        url='/?view=versions&vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs&revision=rev_0002&snapshot=NL2.5.3/snap_nl253_0001'
        body=self.client.get(url).get_data(as_text=True)
        for expected in ('与正式 NL 对照','来源一致','来源不同','内容未比较'):
            self.assertIn(expected,body)

    def test_create_candidate_from_registered_delivery(self):
        import shutil
        root=Path(self.temp.name);work=root/'candidate_work';shutil.copytree(ROOT/'examples/overall_demo/dataset/work',work)
        effective=work/'vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective'
        (effective/'versions/rev_0002.json').unlink()
        app=create_app(ROOT/'examples/pipeline',root/'candidate_runs',work);app.testing=True;client=app.test_client()
        with client.session_transaction() as session: session['csrf']='token'
        response=client.post('/effective/apply',data={'csrf':'token','vendor':'vendor_orion','library':'lib_rtavfs','ip':'rtavfs','delivery':'dlv_20261019_001'})
        self.assertEqual(response.status_code,303)
        result=client.get(response.location).get_data(as_text=True)
        self.assertTrue((effective/'versions/rev_0002.json').is_file())
        self.assertIn('rev_0002',result)
        self.assertIn('检查计划',result)
        self.assertEqual(client.post('/effective/apply',data={'csrf':'token','vendor':'vendor_orion','library':'lib_rtavfs','ip':'rtavfs','delivery':'../../bad'}).status_code,400)

    def test_run_detail_shows_referenced_fact_inputs(self):
        import json
        from ai_lib_qor.workbench.service import execute
        root=Path(self.temp.name);plans=ROOT/'examples/overall_demo/dataset/plans'
        result=execute(plans/'rev_0002.json',root/'run_refs')
        self.assertEqual(result['state'],'SUCCEEDED')
        client=create_app(plans,root/'run_refs',ROOT/'examples/overall_demo/dataset/work').test_client()
        body=client.get('/runs/'+result['id']).get_data(as_text=True)
        self.assertIn('检查输入与中间事实',body)
        self.assertIn('V08_f001.json',body)
        self.assertIn('rev_0001.json',body)

    def test_completed_run_detail_distinguishes_check_failure(self):
        from ai_lib_qor.workbench.service import execute
        root=Path(self.temp.name);plans=ROOT/'examples/overall_demo/dataset/plans'
        result=execute(plans/'rev_0002.json',root/'status_runs')
        client=create_app(plans,root/'status_runs',ROOT/'examples/overall_demo/dataset/work').test_client()
        body=client.get('/runs/'+result['id']).get_data(as_text=True)
        self.assertIn('1 项检查失败',body)

class LibraryFlowNavigationTest(unittest.TestCase):
    def test_numbered_combined_navigation_and_legacy_links(self):
        with tempfile.TemporaryDirectory() as d:
            client=create_app(ROOT/'examples/pipeline',Path(d)/'runs',ROOT/'examples/work').test_client()
            for view in ('discover','deliveries','files','compare'):
                response=client.get('/?view='+view)
                self.assertEqual(response.status_code,200)
                body=response.get_data(as_text=True)
                for label in ('库更新中心','01 IP 总览','02 文件与 Macro','03 检查与验收','01 库更新','02 待确认交付','03 已登记交付','04 文件与版本'):
                    self.assertIn(label,body)
            body=client.get('/?view=discover').get_data(as_text=True)
            self.assertIn('扫描本身不会自动生成交付',body)
            self.assertNotIn('>数据登记</a>',body)

class ComponentReviewTests(unittest.TestCase):
    def test_nl_selection_and_member_filters_keep_each_other(self):
        with tempfile.TemporaryDirectory() as d:
            client=create_app(ROOT/'examples/pipeline',Path(d)/'runs',ROOT/'examples/work').test_client()
            body=client.get('/?view=versions&revision=rev_0002&snapshot=NL2.5.3/snap_nl253_0001&q=core&source=RAW').get_data(as_text=True)
            from html.parser import HTMLParser
            class Forms(HTMLParser):
                def __init__(self):super().__init__();self.forms=[];self.current=None
                def handle_starttag(self,tag,attrs):
                    a=dict(attrs)
                    if tag=='form':self.current={'attrs':a,'inputs':{}};self.forms.append(self.current)
                    if self.current is not None and tag=='input' and 'name' in a:self.current['inputs'][a['name']]=a.get('value','')
                def handle_endtag(self,tag):
                    if tag=='form':self.current=None
            f=Forms();f.feed(body)
            member=next(x for x in f.forms if x['attrs'].get('aria-label')=='筛选成员文件')
            self.assertEqual(member['inputs'].get('snapshot'),'NL2.5.3/snap_nl253_0001')
            nl=next(x for x in f.forms if x['attrs'].get('aria-label')=='选择正式快照')
            self.assertEqual(nl['inputs'].get('q'),'core');self.assertEqual(nl['inputs'].get('source'),'RAW')

    def test_version_history_shows_check_failure_separately(self):
        from ai_lib_qor.workbench.service import execute
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); plans=ROOT/'examples/overall_demo/dataset/plans'; work=ROOT/'examples/overall_demo/dataset/work'
            execute(plans/'rev_0002.json',root/'runs',owner={'vendor':'vendor_orion','library':'lib_rtavfs','ip':'rtavfs'},expected_revision='rev_0002')
            client=create_app(plans,root/'runs',work).test_client()
            body=client.get('/?view=checks&vendor=vendor_orion&library=lib_rtavfs&ip=rtavfs').get_data(as_text=True)
            self.assertIn('1 项检查失败',body)

class SourceSidebarTests(unittest.TestCase):
    def test_configured_libraries_and_registered_ips_are_distinct(self):
        with tempfile.TemporaryDirectory() as d:
            import shutil
            root=Path(d);work=root/'work';shutil.copytree(ROOT/'examples/work',work)
            (work/'scan_sources.json').write_text(json.dumps({'sources':[{'vendor_id':'vendor_other','source_library_id':'lib_new','root':str(root/'raw')},{'vendor_id':'vendor_orion','source_library_id':'lib_rtavfs','root':str(root/'raw')}]},ensure_ascii=False))
            client=create_app(ROOT/'examples/pipeline',root/'runs',work).test_client()
            body=client.get('/?view=discover&scan_q=vendor_other+lib_new').get_data(as_text=True)
            for value in ('库与 IP','vendor_other','lib_new','未登记 IP','rtavfs','scan_q=vendor_other+lib_new'):
                self.assertIn(value,body)
            self.assertIn('value="vendor_other lib_new"',body)
