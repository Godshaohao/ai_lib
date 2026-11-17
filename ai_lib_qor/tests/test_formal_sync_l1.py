import tempfile
import unittest
from pathlib import Path

class FormalSyncTests(unittest.TestCase):
    def test_observes_matching_and_broken_links_and_keeps_history(self):
        from ai_lib_qor.sources.formal_sync import sync_formal, formal_history
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); raw=root/'raw';raw.mkdir(); f=raw/'core.lef';f.write_text('one')
            formal=root/'formal';formal.mkdir();(formal/'core.lef').symlink_to(f)
            runs=root/'runs'; config={'formal_nl_id':'NL2.5.3','root':str(formal)}
            delivery={'vendor_id':'v','source_library_id':'lib','supplier_version':'V07','delivery_id':'d1','source_root':str(raw),'files':[{'relative_path':'core.lef','file_id':'f1','file_key':'lib:lef:core','classification':'RESOLVED'}]}
            first=sync_formal(runs,config,[delivery])
            self.assertEqual(first['status'],'COMPLETE');self.assertEqual(first['files'][0]['source_status'],'MATCHED_RAW')
            self.assertEqual(first['files'][0]['source']['delivery_id'],'d1')
            (formal/'broken.lef').symlink_to(raw/'missing.lef')
            second=sync_formal(runs,config,[delivery])
            self.assertEqual(second['status'],'PARTIAL')
            self.assertTrue(any(x['link_status']=='BROKEN' for x in second['files']))
            self.assertEqual(len(formal_history(runs,config)),2)
            self.assertEqual(formal_history(runs,config)[1]['status'],'COMPLETE')
