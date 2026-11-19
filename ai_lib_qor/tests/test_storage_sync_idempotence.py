import tempfile
import unittest
from pathlib import Path

from ai_lib_qor.application.scans import run_scan_and_ingest, ingest_result


class SourceSyncIdempotenceTests(unittest.TestCase):
    def test_ten_scans_do_not_duplicate_and_modified_raw_is_not_republished(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);work=base/'work';work.mkdir();raw=base/'raw';v=raw/'V01';v.mkdir(parents=True)
            (v/'core.lef').write_text('LEF')
            source={'vendor_id':'v','source_library_id':'lib','root':str(raw),'version_paths':{'V01':'V01'}}
            for _ in range(10):
                scan=run_scan_and_ingest(base/'runs',work,source)
                self.assertEqual(scan['status'],'COMPLETE')
                self.assertEqual(ingest_result(base/'runs',scan)['blocked'],0)
            deliveries=list(work.glob('libraries/v/lib/delivery_*.json'))
            self.assertEqual(len(deliveries),1);before=deliveries[0].read_bytes()
            (v/'core.lef').write_text('LEF MODIFIED')
            scan=run_scan_and_ingest(base/'runs',work,source)
            self.assertEqual(ingest_result(base/'runs',scan)['modified'],1)
            self.assertEqual(deliveries[0].read_bytes(),before)
            self.assertEqual(len(list(work.glob('libraries/v/lib/delivery_*.json'))),1)


if __name__=='__main__': unittest.main()
