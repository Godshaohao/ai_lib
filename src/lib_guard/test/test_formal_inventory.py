from pathlib import Path
import tempfile
import unittest
import json


class FormalInventoryTest(unittest.TestCase):
    def test_integrated_inventory_filters_restart_and_preserves_source_facts(self):
        from lib_guard.catalog.index import scan_catalog
        from lib_guard.short_cli_config import write_default_config
        from lib_guard.web.app import create_app
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            workspace=root/'workspace'
            raw=root/'raw'
            formal=root/'formal'
            formal.mkdir()
            for version in ['20260101_full','20260102_fix']:
                directory=raw/'a'/version
                directory.mkdir(parents=True)
                for index in range(2):
                    source=directory/f'cell_{index}.lef'
                    source.write_text('VERSION 5.8 ;')
                    (formal/f'{version}_{index}.lef').symlink_to(source)
            config=write_default_config(workspace,raw_root=raw)
            scan_catalog(raw,out_dir=workspace/'catalog',force=True)
            asset=(workspace/'catalog/catalog.json').read_bytes()
            pointer=workspace/'effective/current_test.json'
            pointer.parent.mkdir()
            pointer.write_text('{"current_effective_id":"keep"}')
            original_links={p.name:p.readlink() for p in formal.iterdir()}
            client=create_app(config_path=config,cwd=root,test_config={'TESTING':True}).test_client()
            self.assertEqual(client.post('/api/formal-directory/refresh',json={'root':str(formal)}).status_code,200)
            result=client.get('/api/formal-directory?library=a&version=20260102_fix&type=lef').get_json()
            self.assertEqual(result['matched_count'],2)
            self.assertEqual(result['versions'],['20260101_full','20260102_fix'])
            self.assertTrue(all(item['version']=='20260102_fix' for item in result['files']))
            restarted=create_app(config_path=config,cwd=root,test_config={'TESTING':True}).test_client()
            self.assertEqual(restarted.get('/api/formal-directory').get_json()['root'],str(formal))
            self.assertEqual((workspace/'catalog/catalog.json').read_bytes(),asset)
            self.assertEqual(pointer.read_text(),'{"current_effective_id":"keep"}')
            self.assertEqual({p.name:p.readlink() for p in formal.iterdir()},original_links)

    def test_web_refresh_is_independent_of_temporary_release_root_and_keeps_previous_snapshot_on_error(self):
        from lib_guard.web.app import create_app
        from lib_guard.short_cli_config import write_default_config
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            raw=root/'raw'
            raw.mkdir()
            workspace=root/'workspace'
            config=write_default_config(workspace,raw_root=raw)
            (workspace/'release_area').rmdir()
            formal=root/'company/lib_NL2.1.0'
            formal.mkdir(parents=True)
            for index in range(105):
                (formal/f'file_{index}.lef').write_text('VERSION 5.8 ;')
            client=create_app(config_path=config,cwd=root,test_config={'TESTING':True}).test_client()
            response=client.post('/api/formal-directory/refresh',json={'root':str(formal)})
            self.assertEqual(response.status_code,200,response.get_json())
            result=client.get('/api/formal-directory').get_json()
            self.assertEqual(result['file_count'],105)
            self.assertEqual(len(result['files']),100)
            self.assertEqual(len(client.get('/api/formal-directory?offset=100&check=unknown').get_json()['files']),5)
            previous=(workspace/'config/formal_directory_inventory.json').read_bytes()
            self.assertEqual(client.post('/api/formal-directory/refresh',json={'root':str(root/'absent')}).status_code,400)
            self.assertEqual((workspace/'config/formal_directory_inventory.json').read_bytes(),previous)
            self.assertFalse((workspace/'release_area').exists())
            self.assertEqual(len(list(formal.iterdir())),105)

    def test_ambiguous_version_roots_are_not_automatically_assigned(self):
        from lib_guard.release.inventory import inventory_directory
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            raw=root/'raw'
            raw.mkdir()
            (raw/'x.db').write_bytes(b'not parsed')
            formal=root/'formal'
            formal.mkdir()
            (formal/'x.db').symlink_to(raw/'x.db')
            catalog={'libraries':[{'library_name':name,'versions':[{'version_id':'v1','raw_path':str(raw)}]} for name in ['a','b']]}
            result=inventory_directory(formal,catalog)
            self.assertEqual(result['files'][0]['source_status'],'归属冲突')
            self.assertEqual(result['unknown_count'],1)

    def test_flat_mixed_files_keep_multiple_versions_and_unknown_sources(self):
        from lib_guard.release.inventory import inventory_directory
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            delivery = root/'formal'
            delivery.mkdir()
            versions=[]
            for lib, version in [('a','v1'),('a','v2'),('b','v1')]:
                raw=root/'raw'/lib/version
                raw.mkdir(parents=True)
                source=raw/f'{lib}_{version}.lef'
                source.write_text('VERSION 5.8 ;')
                (delivery/source.name).symlink_to(source)
                versions.append((lib,version,raw))
            (delivery/'lost.gds').symlink_to(root/'missing.gds')
            (delivery/'copied.lib').write_text('library(x) {}')
            (delivery/'external').symlink_to(root/'raw', target_is_directory=True)
            catalog={'libraries':[{'library_name':lib,'library_type':'ip','versions':[{'version_id':v,'raw_path':str(p)} for l,v,p in versions if l==lib]} for lib in ['a','b']]}
            result=inventory_directory(delivery,catalog)
            self.assertEqual(result['file_count'],5)
            self.assertEqual(result['unknown_count'],2)
            self.assertEqual(result['broken_count'],1)
            self.assertEqual(result['libraries'][0]['versions'],['v1','v2'])
            self.assertEqual(result['libraries'][0]['file_count'],2)
            self.assertEqual(len(list(delivery.iterdir())),6)
            self.assertEqual(result['files'][0]['file_type'],'lef')
