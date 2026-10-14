from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest


class LibDbCorrespondenceTest(unittest.TestCase):
    def test_scan_html_markdown_and_web_reuse_the_same_file_correspondence(self):
        from lib_guard.scan.scanner import ScanRunner
        from lib_guard.render.html_report import render_scan_html
        from lib_guard.web.read_model import list_file_tree_rows
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            raw=root/'raw'
            raw.mkdir()
            for name in ['a','b']:
                (raw/f'{name}.lib').write_text(f'library({name}) {{ cell({name}) {{ area : 1; }} }}')
            (raw/'a.db').write_bytes(b'synthetic DB')
            scan=root/'scan'
            result=ScanRunner(SimpleNamespace(root_path=str(raw),out_dir=str(scan),library_type='ip',library_name='demo',version='v1',
                scan_mode='scan',scan_id='test_pairing',state_dir=str(root/'state'),cache_dir=str(root/'cache'),
                tool_version='0.5.0',schema_version='1.0',hash_policy='none',parse_jobs=1)).run()
            self.assertEqual(result.status,'PASS')
            self.assertEqual(result.stats['hashed_files'],0)
            self.assertEqual(result.bundle.issues['issues'],[])
            markdown=(scan/'review/scan_review.md').read_text()
            self.assertIn('Liberty 2 个 / DB 1 个',markdown)
            self.assertIn(str(raw/'b.lib'),markdown)
            rendered=render_scan_html(scan,root/'html')
            html=Path(rendered['index_html']).read_text()
            self.assertIn('Liberty / DB 配套清单',html)
            self.assertIn('仅 Liberty',html)
            self.assertIn(str(raw/'a.db'),html)
            # Older evidence does not need a new integrity record to draw the table.
            (scan/'integrity.json').unlink()
            web_state={'catalog_html':str(root/'catalog/html'),'catalog':{'libraries':[{'library_name':'demo','library_id':'ip/demo',
                'versions':[{'version_id':'v1','raw_path':str(raw),'scan':{'scan_dir':str(scan),'status':'SCANNED'}}]}]}}
            web=list_file_tree_rows(web_state,'demo','v1')
            self.assertEqual(web['status'],'PASS')
            self.assertEqual(web['lib_db_correspondence'],result.bundle.integrity['lib_db_correspondence'])

    def test_lists_names_paths_and_counts_without_judging_delivery(self):
        from lib_guard.scan.artifacts import build_lib_db_correspondence, IntegrityBuilder
        records=[{'path':p,'file_type':t} for p,t in [('lib/a.lib','liberty'),('lib/b.lib.gz','liberty'),('db/a.db','db'),('db/c.ndm','db')]]
        result=build_lib_db_correspondence(records,'/raw/v1')
        self.assertEqual(result['liberty_count'],2)
        self.assertEqual(result['db_count'],1)
        self.assertEqual(result['rows'][0]['relation'],'同名两侧均有')
        self.assertEqual(result['rows'][1]['relation'],'仅 Liberty')
        self.assertEqual(result['rows'][1]['liberty_files'],['/raw/v1/lib/b.lib.gz'])
        integrity=IntegrityBuilder().build(records,{}, {},SimpleNamespace(root_path='/raw/v1'))
        self.assertEqual(integrity['status'],'PASS')
        self.assertEqual(integrity['issues'],[])
        self.assertEqual(integrity['lib_db_correspondence'],result)

    def test_same_counts_do_not_hide_different_names_or_duplicates(self):
        from lib_guard.scan.artifacts import build_lib_db_correspondence
        records=[{'path':p,'file_type':t} for p,t in [('x/a.lib','liberty'),('y/a.lib','liberty'),('db/a.db','db'),('db/b.db.gz','db')]]
        result=build_lib_db_correspondence(records,'/raw')
        self.assertEqual(result['rows'][0]['relation'],'同名多文件')
        self.assertEqual(len(result['rows'][0]['liberty_files']),2)
        self.assertEqual(result['rows'][1]['relation'],'仅 DB')
