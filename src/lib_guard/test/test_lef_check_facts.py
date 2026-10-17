import copy
import json
from pathlib import Path
import tempfile
import unittest

from lib_guard.scan.parsers.lef import parse_lef_text, LEF_PARSER_VERSION
from lib_guard.semantic.adapters import adapt_result

LEF = '''VERSION 5.8 ;
BUSBITCHARS "[]" ;
UNITS
DATABASE MICRONS 1000 ;
END UNITS
MACRO M
CLASS BLOCK ;
ORIGIN 0 0 ;
SIZE 10 BY 20 ;
SYMMETRY X Y ;
PIN A
DIRECTION INPUT ;
USE SIGNAL ;
PORT
LAYER M1 ;
RECT 0 0 1 1 ;
RECT 2 2 3 3 ;
END
END A
OBS
LAYER M2 ;
RECT 1 1 2 2 ;
END
END M
END LIBRARY
'''


def lef_index(session, text=LEF, *, ref='scan/new.json', digest='new'):
    data = parse_lef_text(text)
    payload = {'parser_name': 'LefParser', 'parser_version': LEF_PARSER_VERSION, 'file_type': 'lef',
               'status': 'PASS', 'data': data}
    evidence = {'library_id': 'ip/demo', 'effective_relpath': 'lef/M.lef', 'source_relpath': 'lef/M.lef',
                'file_type': 'lef', 'source_version': digest, 'parser_result_ref': ref}
    session.add(evidence, payload)
    fact = adapt_result(payload, evidence)
    return {'library_id': 'ip/demo', 'effective_id': digest, 'effective_digest': digest,
            'facts': [fact], 'files': [{'effective_relpath': 'lef/M.lef', 'file_type': 'lef', 'fact_status': 'AVAILABLE'}]}


def scoped_index(index, *, macros=None, mapping=None):
    from lib_guard.semantic.binding import build_effective_model
    from lib_guard.semantic.profile import load_review_profile
    from lib_guard.semantic.runner import _lef_scope_index
    profile = load_review_profile(profile_name='lef_basic')
    profile['config']['macros'] = macros or []
    model = build_effective_model(index, profile, mapping=mapping, allow_unused_mapping=True)
    return _lef_scope_index(index, model, profile['config'])


class LefCheckFactsTest(unittest.TestCase):
    def test_quoted_semicolons_and_comment_characters_are_not_statements(self):
        text = LEF.replace('MACRO M\n', 'LAYER M1\nTYPE ROUTING ;\n'
            'PROPERTY LEF58_TYPE "TYPE ROUTING ; # literal \\" ; still quoted" ;\nEND M1\nMACRO M\n')
        data = parse_lef_text(text)
        self.assertEqual(data['semantic_coverage']['macro_set'], 'PRESENT')
        self.assertEqual(data['parse_limitation_count'], 0)
        self.assertEqual(data['layers']['M1']['type'], 'ROUTING')

    def test_multiple_scalar_statements_keep_geometry_and_line_numbers(self):
        text = LEF.replace('DIRECTION INPUT ;\nUSE SIGNAL ;', 'DIRECTION INPUT ; USE SIGNAL ;')
        text = text.replace('RECT 0 0 1 1 ;\nRECT 2 2 3 3 ;', 'RECT 0 0 1 1 ; RECT 2 2 3 3 ; # tail')
        data = parse_lef_text(text)
        pin = data['macros']['M']['pins']['A']
        self.assertEqual((pin['direction'], pin['use'], pin['rect_count']), ('INPUT', 'SIGNAL', 2))
        self.assertEqual(data['semantic_coverage']['pin_geometry'], 'PRESENT')
        self.assertEqual(pin['line_start'], text.splitlines().index('PIN A') + 1)

    def test_multiline_properties_do_not_invent_macro_and_broken_quotes_are_incomplete(self):
        text = 'PROPERTYDEFINITIONS\nLIBRARY NOTE STRING ;\nEND PROPERTYDEFINITIONS\n'
        text += 'PROPERTY NOTE "first ;\nMACRO FAKE # literal\nlast ;" ;\n' + LEF
        data = parse_lef_text(text)
        self.assertEqual(data['macro_order'], ['M'])
        self.assertEqual(data['semantic_coverage']['macro_set'], 'PRESENT')
        broken = parse_lef_text(text + 'PROPERTY NOTE "unclosed ;\n')
        self.assertEqual(broken['semantic_coverage']['macro_set'], 'NOT_EXTRACTED')

    def test_existing_asap7_technology_lef_does_not_poison_macro_discovery(self):
        import re
        path = Path(__file__).resolve().parents[3] / 'tests/fixtures/raw/vendor_A/openroad_asap7/20260627_asap7/upstream_ae9a8ed9/lef/asap7_tech_1x_201209.lef'
        text = path.read_text()
        data = parse_lef_text(text)
        self.assertEqual(data['macros'], {})
        self.assertEqual(set(data['layers']), set(re.findall(r'^LAYER\s+(\S+)\s*$', text, re.M)))
        self.assertEqual(data['semantic_coverage']['macro_set'], 'PRESENT')
        self.assertEqual(data['parse_limitation_count'], 0)

    def test_via_rule_layer_references_do_not_overwrite_technology_layers(self):
        prefix = 'LAYER M1\nTYPE ROUTING ;\nWIDTH 0.1 ;\nEND M1\n'
        via = 'VIARULE V12 GENERATE\nLAYER M1 ;\nWIDTH 0.2 TO 0.3 ;\nEND V12\n'
        data = parse_lef_text(prefix + via + LEF)
        self.assertEqual(data['layers']['M1']['width'], 0.1)
        self.assertEqual(data['macro_order'], ['M'])
        self.assertEqual(data['semantic_coverage']['macro_set'], 'PRESENT')
        broken = parse_lef_text(prefix + via.replace('END V12', ''))
        self.assertEqual(broken['semantic_coverage']['macro_set'], 'NOT_EXTRACTED')

    def test_macro_filter_does_not_hide_incomplete_discovery_in_an_empty_file(self):
        from lib_guard.semantic.lef_checks import LefCheckFacts, compare_lef, build_macro_index
        session = LefCheckFacts()
        old = scoped_index(lef_index(session, ref='old', digest='old'), macros=['M'])
        new = scoped_index(lef_index(session, 'VERSION 5.8 ;\nPROPERTYDEFINITIONS\n'), macros=['M'])
        self.assertFalse(build_macro_index(new, session)['complete'])
        self.assertTrue(all(row['status'] == 'INCOMPLETE' for row in compare_lef(old, new, session)))

    def test_canonical_macro_aliases_are_shared_with_binding_identity(self):
        from lib_guard.semantic.lef_checks import LefCheckFacts, compare_lef, build_macro_index
        session = LefCheckFacts()
        mapping = {'confirmed': True, 'macro_aliases': [{'view': 'lef', 'object': 'N', 'macro': 'M'}]}
        old = scoped_index(lef_index(session, ref='old', digest='old'), mapping=mapping)
        renamed = LEF.replace('MACRO M', 'MACRO N').replace('END M', 'END N')
        new = scoped_index(lef_index(session, renamed), mapping=mapping)
        self.assertTrue(all(row['status'] == 'UNCHANGED' for row in compare_lef(old, new, session)))
        both = LEF.replace('END LIBRARY', renamed[renamed.index('MACRO N'):])
        duplicate = scoped_index(lef_index(session, both, ref='duplicate'), mapping=mapping)
        duplicate_row = build_macro_index(duplicate, session)['macros'][0]
        self.assertEqual(duplicate_row['status'], 'AMBIGUOUS')
        self.assertEqual({row['source_object'] for row in duplicate_row['candidates']}, {'M', 'N'})
        self.assertTrue(all(row['status'] == 'INCOMPLETE' for row in compare_lef(old, duplicate, session)))

    def test_missing_selected_file_prevents_claiming_unique_macro_or_unchanged(self):
        from lib_guard.semantic.lef_checks import LefCheckFacts, compare_lef, build_macro_index
        session = LefCheckFacts()
        old = lef_index(session, ref='old', digest='old')
        new = lef_index(session)
        new['files'].append({'effective_relpath': 'missing.lef', 'file_type': 'lef',
                             'fact_status': 'NOT_CHECKED', 'reason_code': 'PARSER_RESULT_MISSING'})
        self.assertNotEqual(build_macro_index(new, session)['macros'][0]['status'], 'READY')
        self.assertTrue(all(row['status'] == 'INCOMPLETE' for row in compare_lef(old, new, session)))

    def test_incomplete_interface_result_does_not_serialize_the_whole_pin_map(self):
        from lib_guard.semantic.lef_checks import LefCheckFacts, compare_lef
        session = LefCheckFacts()
        old = lef_index(session, ref='old', digest='old')
        new = lef_index(session, LEF.replace('USE SIGNAL ;', ''))
        row = next(row for row in compare_lef(old, new, session) if row['attribute'] == 'interface')
        self.assertEqual(row['status'], 'INCOMPLETE')
        self.assertNotIn('old', row['details'])
        self.assertNotIn('new', row['details'])
        self.assertEqual(row['details']['missing_attributes']['new']['count'], 1)
        self.assertEqual(row['details']['missing_attributes']['new']['sample'], ['A'])

    def test_unclosed_or_mismatched_port_blocks_are_not_complete(self):
        from lib_guard.semantic.lef_checks import LefCheckFacts, compare_lef
        for text in (LEF.replace('END\nEND A', 'END A'),
                     LEF.replace('PIN A\n', 'PIN A\nPIN B\n'),
                     LEF.replace('PIN A\n', 'MACRO N\nEND N\nPIN A\n'),
                     LEF.replace('END\nEND A', 'END\nEND WRONG\nEND A'),
                     LEF.replace('END\nEND A', 'END\nEND')):
            with self.subTest(text=text):
                session = LefCheckFacts()
                old = lef_index(session, ref='old', digest='old')
                new = lef_index(session, text)
                self.assertTrue(all(row['status'] == 'INCOMPLETE' for row in compare_lef(old, new, session)))

    def test_rect_and_symmetry_order_do_not_produce_delta(self):
        from lib_guard.semantic.lef_checks import LefCheckFacts, compare_lef
        session = LefCheckFacts()
        old = lef_index(session, ref='old', digest='old')
        text = LEF.replace('SYMMETRY X Y', 'SYMMETRY Y X').replace(
            'RECT 0 0 1 1 ;\nRECT 2 2 3 3 ;', 'RECT 2 2 3 3 ;\nRECT 0 0 1 1 ;')
        new = lef_index(session, text)
        self.assertTrue(all(row['status'] == 'UNCHANGED' for row in compare_lef(old, new, session)))

    def test_physical_only_rules_do_not_build_interface_or_geometry(self):
        from lib_guard.semantic.lef_checks import LefCheckFacts, compare_lef
        class UnusedPins(dict):
            def items(self):
                raise AssertionError('unselected interface/geometry was built')
        session = LefCheckFacts(enabled_checks={'LEF_PHYSICAL_DELTA'})
        old = lef_index(session, ref='old', digest='old')
        new = lef_index(session)
        for payload in session.payloads.values():
            payload['data']['macros']['M']['pins'] = UnusedPins(payload['data']['macros']['M']['pins'])
        rows = compare_lef(old, new, session, enabled_checks={'LEF_PHYSICAL_DELTA'})
        self.assertTrue(all(row['status'] == 'UNCHANGED' for row in rows))
        rows = compare_lef(old, new, session, enabled_checks={'LEF_GEOMETRY_DELTA'})
        self.assertTrue(all(row['status'] == 'INCOMPLETE' for row in rows))

    def test_many_unsupported_shapes_keep_bounded_diagnostics(self):
        text = LEF.replace('RECT 0 0 1 1 ;', '\n'.join(['POLYGON 0 0 1 0 1 1 ;'] * 300))
        result = parse_lef_text(text)
        self.assertLessEqual(len(result['parse_limitations']), 100)
        self.assertGreater(result['parse_limitation_count'], 100)
        self.assertEqual(result['semantic_coverage']['pin_geometry'], 'NOT_EXTRACTED')

    def test_lef_keywords_have_canonical_case_in_physical_summary(self):
        self.assertEqual(parse_lef_text(LEF.replace('CLASS BLOCK', 'CLASS block'))['macros']['M']['class'], 'BLOCK')

    def test_property_definition_macro_keyword_is_not_a_physical_macro(self):
        text = LEF.replace('MACRO M\n', 'PROPERTYDEFINITIONS\nMACRO width INTEGER ;\nEND PROPERTYDEFINITIONS\nMACRO M\n')
        data = parse_lef_text(text)
        self.assertEqual(list(data['macros']), ['M'])
        self.assertEqual(data['semantic_coverage']['macro_set'], 'PRESENT')

    def test_macro_index_is_small_and_detects_duplicate_and_truncated_objects(self):
        from lib_guard.semantic.lef_checks import LefCheckFacts, build_macro_index
        session = LefCheckFacts()
        index = lef_index(session)
        result = build_macro_index(index, session)
        self.assertTrue(result['complete'])
        row = result['macros'][0]
        self.assertEqual((row['name'], row['size_um'], row['class'], row['pin_count'], row['status']),
                         ('M', [10, 20], 'BLOCK', 1, 'READY'))
        self.assertNotIn('geometry', json.dumps(row))
        self.assertNotIn('pins', row)
        duplicate = lef_index(session, LEF.replace('END LIBRARY', LEF[LEF.index('MACRO M'):]), ref='duplicate')
        self.assertEqual(build_macro_index(duplicate, session)['macros'][0]['status'], 'AMBIGUOUS')
        truncated = lef_index(session, LEF.split('END A')[0], ref='truncated')
        self.assertFalse(build_macro_index(truncated, session)['complete'])
        self.assertNotEqual(build_macro_index(truncated, session)['macros'][0]['status'], 'READY')

    def test_interface_physical_and_obstruction_changes_are_separate(self):
        from lib_guard.semantic.lef_checks import LefCheckFacts, compare_lef
        session = LefCheckFacts()
        old = lef_index(session, ref='old', digest='old')
        text = LEF.replace('INPUT', 'OUTPUT').replace('USE SIGNAL', 'USE CLOCK').replace('RECT 0 0 1 1', 'RECT 0 0 2 1').replace('RECT 1 1 2 2', 'RECT 1 1 3 2')
        new = lef_index(session, text)
        rows = compare_lef(old, new, session)
        self.assertEqual(next(r for r in rows if r['attribute'] == 'interface')['status'], 'CHANGED')
        self.assertEqual(next(r for r in rows if r['attribute'] == 'pin_geometry')['status'], 'CHANGED')
        self.assertEqual(next(r for r in rows if r['attribute'] == 'obstructions')['status'], 'CHANGED')
        self.assertEqual(next(r for r in rows if r['attribute'] == 'size_um')['status'], 'UNCHANGED')
        self.assertIn('A', str(next(r for r in rows if r['attribute'] == 'interface')['details']))

    def test_port_group_change_is_not_hidden_by_same_flat_rectangles(self):
        from lib_guard.semantic.lef_checks import LefCheckFacts, compare_lef
        session = LefCheckFacts()
        old = lef_index(session, ref='old', digest='old')
        text = LEF.replace('RECT 2 2 3 3 ;', 'END\nPORT\nLAYER M1 ;\nRECT 2 2 3 3 ;')
        new = lef_index(session, text)
        self.assertEqual(next(r for r in compare_lef(old, new, session) if r['attribute'] == 'pin_geometry')['status'], 'CHANGED')

    def test_unsupported_geometry_is_explicitly_incomplete(self):
        from lib_guard.semantic.lef_checks import LefCheckFacts, compare_lef
        for geometry in ('POLYGON 0 0 1 0 1 1 ;', 'VIA 0 0 V12 ;', 'RECT MASK 1 0 0 1 1 ;', 'RECT ITERATE 0 0 1 1 DO 2 BY 1 STEP 1 0 ;'):
            with self.subTest(geometry=geometry):
                session = LefCheckFacts()
                old = lef_index(session, ref='old', digest='old')
                new = lef_index(session, LEF.replace('RECT 0 0 1 1 ;', geometry))
                geometry_row = next(r for r in compare_lef(old, new, session) if r['attribute'] == 'pin_geometry')
                self.assertEqual(geometry_row['status'], 'INCOMPLETE')
                self.assertTrue(geometry_row['requirements'])

    def test_comment_changes_reuse_task_facts_and_do_not_produce_delta(self):
        from lib_guard.semantic.lef_checks import LefCheckFacts, compare_lef
        session = LefCheckFacts()
        old = lef_index(session, ref='old', digest='old')
        new = lef_index(session, '# comment\n' + LEF.replace('RECT 0 0 1 1 ;', 'RECT 0 0 1 1 ; # comment'))
        self.assertTrue(all(row['status'] == 'UNCHANGED' for row in compare_lef(old, new, session)))
        before = session.build_count
        compare_lef(old, new, session)
        self.assertEqual(session.build_count, before)

    def test_missing_base_never_reports_all_macros_as_added(self):
        from lib_guard.semantic.lef_checks import LefCheckFacts, compare_lef
        session = LefCheckFacts()
        new = lef_index(session)
        rows = compare_lef(None, new, session)
        self.assertTrue(rows)
        self.assertTrue(all(row['status'] == 'INCOMPLETE' for row in rows))

    def test_file_facts_store_does_not_copy_full_lef_geometry(self):
        from lib_guard.semantic.facts import FileFactsStore
        with tempfile.TemporaryDirectory() as td:
            data = parse_lef_text(LEF)
            payload = {'parser_name': 'LefParser', 'parser_version': LEF_PARSER_VERSION,
                       'status': 'PASS', 'file_type': 'lef', 'data': data}
            fact = FileFactsStore(td).get_or_adapt(payload, {'file_type': 'lef'})
            stored = json.loads(Path(fact['fact_ref']).read_text())['fact']
            self.assertTrue(all(port.get('geometry') is None for obj in stored['objects'] for port in obj['ports']))

    def test_macro_add_remove_and_rename_pin_without_count_change(self):
        from lib_guard.semantic.lef_checks import LefCheckFacts, compare_lef, build_macro_index
        session = LefCheckFacts()
        old = lef_index(session, ref='old', digest='old')
        text = LEF.replace('PIN A', 'PIN B').replace('END A', 'END B')
        text = text.replace('END LIBRARY', LEF[LEF.index('MACRO M'):].replace('MACRO M', 'MACRO N').replace('END M', 'END N'))
        new = lef_index(session, text)
        rows = compare_lef(old, new, session)
        added = next(r for r in rows if r['attribute'] == 'presence' and r['macro'] == 'N')
        self.assertEqual(added['details']['change'], 'ADDED')
        self.assertEqual(next(r for r in rows if r['attribute'] == 'interface' and r['macro'] == 'M')['status'], 'CHANGED')
        self.assertEqual(build_macro_index(old, session)['macros'][0]['pin_count'], build_macro_index(new, session)['macros'][0]['pin_count'])
        removed = next(r for r in compare_lef(new, old, session) if r['attribute'] == 'presence' and r['macro'] == 'N')
        self.assertEqual(removed['details']['change'], 'REMOVED')

    def test_confirmed_new_macro_does_not_create_seven_fake_incomplete_comparisons(self):
        from lib_guard.semantic.lef_checks import LefCheckFacts, compare_lef
        session = LefCheckFacts()
        old = lef_index(session, ref='old', digest='old')
        text = LEF.replace('END LIBRARY', LEF[LEF.index('MACRO M'):].replace('MACRO M', 'MACRO N').replace('END M', 'END N'))
        new = lef_index(session, text)
        added = [row for row in compare_lef(old, new, session) if row['macro'] == 'N']
        self.assertEqual(len(added), 1)
        self.assertEqual((added[0]['attribute'], added[0]['status'], added[0]['details']['change']), ('presence', 'CHANGED', 'ADDED'))

    def test_same_name_in_different_files_is_ambiguous_and_variants_stay_separate(self):
        from lib_guard.semantic.lef_checks import LefCheckFacts, build_macro_index
        session = LefCheckFacts()
        left = lef_index(session, ref='one')
        right = lef_index(session, ref='two')
        both = {**left, 'facts': left['facts'] + right['facts'], 'files': left['files'] + right['files']}
        self.assertEqual(build_macro_index(both, session)['macros'][0]['status'], 'AMBIGUOUS')
        right['facts'][0]['variant'] = 'confirmed-other-variant'
        self.assertEqual(len(build_macro_index(both, session)['macros']), 2)

    def test_lef_profile_is_integrated_with_effective_and_historical_results(self):
        from lib_guard.effective.manifest import build_effective_manifest
        from lib_guard.semantic.runner import run_semantic_review
        from lib_guard.semantic.results import load_review_snapshot
        from lib_guard.test.test_release_levels import _scan
        from lib_guard.test.semantic_fixture import write_json
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = {'libraries': [{'library_id': 'ip/demo', 'library_name': 'demo', 'versions': []}]}
            for version, text in [('full', LEF), ('fix', LEF.replace('RECT 1 1 2 2', 'RECT 1 1 3 2'))]:
                raw, scan = root / 'raw' / version, root / 'scan' / version
                raw.mkdir(parents=True)
                (raw / 'M.lef').write_text(text)
                _scan(raw, scan, mode='scan', version=version, parse_file_types=['lef'])
                meta = json.loads((scan / 'scan_meta.json').read_text())
                catalog['libraries'][0]['versions'].append({'version_id': version, 'raw_path': str(raw),
                    'scan': {'scan_dir': str(scan), 'snapshot_identity': meta['snapshot_identity']}})
            cat, old, new = root / 'catalog.json', root / 'old.json', root / 'new.json'
            write_json(cat, catalog)
            write_json(old, build_effective_manifest(catalog, 'demo', 'full', []))
            write_json(new, build_effective_manifest(catalog, 'demo', 'full', [('fix', ['lef'])]))
            result = run_semantic_review(new, cat, root / 'report', base_manifest_path=old, profile_name='lef_basic')
            self.assertEqual(result['index']['macro_index']['macros'][0]['status'], 'READY')
            self.assertFalse(any(row['reason_code'] == 'NO_SEMANTIC_OBJECTS' for row in result['checks']))
            self.assertEqual(next(r for r in result['delta'] if r['attribute'] == 'obstructions')['status'], 'CHANGED')
            self.assertEqual(load_review_snapshot(root / 'report'), result)
            markdown = (root / 'report' / result['summary']['artifacts']['markdown']).read_text()
            self.assertIn('物理对象索引', markdown)
            self.assertIn('obstructions', markdown)
            self.assertNotIn('| size_um | UNCHANGED |', markdown)
            self.assertIn('check_results.json', markdown)
