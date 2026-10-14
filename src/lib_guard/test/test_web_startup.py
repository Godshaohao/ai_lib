import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class WebStartupTest(unittest.TestCase):
    def test_missing_config_and_occupied_port_do_not_spawn(self):
        from lib_guard.web.app import start_background_server
        with tempfile.TemporaryDirectory() as td, patch('subprocess.Popen') as spawn:
            config=Path(td)/'lib_guard.yml'
            with self.assertRaisesRegex(ValueError,'配置不存在'):
                start_background_server(config,'127.0.0.1',5067)
            config.write_text('workspace: '+td)
            with patch('socket.socket') as socket:
                socket.return_value.__enter__.return_value.bind.side_effect=OSError('occupied')
                with self.assertRaisesRegex(ValueError,'端口.*已占用'):
                    start_background_server(config,'127.0.0.1',5067)
            spawn.assert_not_called()

    def test_background_start_confirms_own_process_and_records_log_and_config(self):
        from lib_guard.web.app import start_background_server
        with tempfile.TemporaryDirectory() as td, patch('socket.socket'), patch('subprocess.Popen') as spawn, patch('urllib.request.urlopen') as http:
            config=Path(td)/'lib_guard.yml'
            config.write_text('workspace: '+td)
            spawn.return_value.pid=12345
            spawn.return_value.poll.return_value=None
            http.return_value.__enter__.return_value.read.return_value=json.dumps({'status':'PASS','service':'lib_guard_web','pid':12345}).encode()
            result=start_background_server(config,'127.0.0.1',5067)
            self.assertEqual(result['url'],'http://127.0.0.1:5067/')
            self.assertEqual(result['config'],str(config))
            self.assertTrue(spawn.call_args.kwargs['start_new_session'])
            self.assertNotIn('--background',spawn.call_args.args[0])
            self.assertTrue(Path(result['log']).is_file())
            self.assertEqual(json.loads(Path(result['state']).read_text())['pid'],12345)

    def test_child_exit_is_not_reported_as_ready(self):
        from lib_guard.web.app import start_background_server
        with tempfile.TemporaryDirectory() as td, patch('socket.socket'), patch('subprocess.Popen') as spawn:
            config=Path(td)/'lib_guard.yml'
            config.write_text('workspace: '+td)
            spawn.return_value.poll.return_value=1
            with self.assertRaisesRegex(RuntimeError,'启动失败'):
                start_background_server(config,'127.0.0.1',5067)

    def test_health_from_a_different_process_is_not_accepted(self):
        from lib_guard.web.app import start_background_server
        with tempfile.TemporaryDirectory() as td, patch('socket.socket'), patch('subprocess.Popen') as spawn, patch('urllib.request.urlopen') as http, patch('time.sleep'), patch('time.monotonic',side_effect=[0,0,11]):
            config=Path(td)/'lib_guard.yml'
            config.write_text('workspace: '+td)
            spawn.return_value.pid=12345
            spawn.return_value.poll.return_value=None
            http.return_value.__enter__.return_value.read.return_value=json.dumps({'status':'PASS','service':'lib_guard_web','pid':54321}).encode()
            with self.assertRaisesRegex(RuntimeError,'未就绪'):
                start_background_server(config,'127.0.0.1',5067)
            spawn.return_value.terminate.assert_called_once()
            self.assertFalse((Path(td)/'web_server_5067.json').exists())
