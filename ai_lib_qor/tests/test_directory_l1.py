import tempfile
import unittest
from pathlib import Path
from ai_lib_qor.workbench.app import create_app

ROOT=Path(__file__).resolve().parents[1]
class DirectoryTests(unittest.TestCase):
    def test_directory_is_bounded_and_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);work=root/'work';work.mkdir();(work/'inside').mkdir();(work/'inside/a.json').write_text('{}');(work/'escape').symlink_to(root,target_is_directory=True)
            client=create_app(ROOT/'examples/pipeline',root/'runs',work).test_client()
            self.assertEqual(client.get('/directories?root=work&path=inside').status_code,200)
            self.assertEqual(client.get('/directories?root=work&path=../').status_code,400)
            self.assertEqual(client.get('/directories?root=work&path=escape').status_code,400)
