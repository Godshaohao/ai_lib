import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(shutil.which('csh'), '需要 csh')
class SetupLauncherTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.outside = Path(holder.name) / 'external directory'
        self.outside.mkdir()
        self.script = Path(__file__).resolve().parents[1] / 'setup.csh'
        self.link = self.outside / 'start qor.csh'
        self.link.symlink_to(self.script)
        self.work = self.outside / 'work space'

    def launch(self, *args):
        result = subprocess.run(
            ['csh', '-f', str(self.link), *map(str, args)],
            cwd=self.outside,
            env={**os.environ, 'AI_LIB_QOR_PYTHON': sys.executable},
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_init_imports_external_config_and_preserves_existing_settings(self):
        config = self.outside / 'site config.json'
        settings = {'raw_roots': ['/mnt/a', '/mnt/b'], 'workbench': {'port': 6081}}
        config.write_text(json.dumps(settings))
        result = json.loads(self.launch('init', '--work', self.work.name, '--config', config.name))
        self.assertEqual(result['state'], 'CREATED')
        saved = self.work / 'path_sources.json'
        self.assertEqual(json.loads(saved.read_text()), settings)

        config.write_text(json.dumps({'raw_roots': ['/new/root']}))
        result = json.loads(self.launch('init', '--work', self.work.name, '--config', config.name))
        self.assertEqual(result['state'], 'UNCHANGED')
        self.assertEqual(json.loads(saved.read_text()), settings)

    def test_default_initialization_and_entrypoints_from_outside_project(self):
        self.launch('init', '--work', self.work)
        config = json.loads((self.work / 'path_sources.json').read_text())
        self.assertEqual(config['raw_roots'], [])
        self.assertEqual(config['workbench']['host'], '127.0.0.1')
        status = json.loads(self.launch('cli', 'refresh-status', '--work', self.work))
        self.assertEqual(status['totals']['libraries'], 0)
        self.assertIn('--port', self.launch('web', '--help'))
