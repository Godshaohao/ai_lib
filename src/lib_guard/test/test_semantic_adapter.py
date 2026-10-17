import copy
import unittest


def evidence(view='lef'):
    return {'library_id': 'ip/demo', 'source_version': 'full', 'effective_relpath': view + '/a',
            'source_relpath': view + '/a', 'file_type': view, 'parser_result_ref': 'parser_results/' + view + '/a.json'}


def parser_result(view='lef', *, complete=False):
    data = {'macros': {'M': {'size': {'x': 1000, 'y': 2000}, 'origin': {'x': 0, 'y': 0},
        'pins': {'CLK': {'direction': 'INPUT', 'use': 'SIGNAL', 'layers': ['M2']}}}},
        'database_microns': 1000, 'busbitchars': '[]', 'geometry_detail': 'full'}
    if view == 'liberty':
        data = {'libraries': {'L': {'cells': {'M': {'area': 12, 'pins': {'CLK': {'direction': 'input'}},
                'pg_pins': {'VDD': {'pg_type': 'primary_power'}}, 'is_macro': True}}}}}
    if view == 'verilog':
        data = {'parse_strategy': 'lightweight_rtl_interface', 'unparsed_features': ['instance'],
                'modules': {'M': {'ports': {'CLK': {'direction': 'input', 'width': 1}}}}}
    if complete:
        data['semantic_coverage'] = {'schema_version': 'semantic_parser_coverage.v1',
            'validated': True, 'basis': 'controlled professional fixture',
            'port_set': 'PRESENT', 'pg_port_set': 'PRESENT'}
    return {'status': 'PASS', 'parser_name': 'FixtureParser' if complete else 'LegacyParser',
            'parser_version': '1', 'file_type': view, 'data': data}


class SemanticAdapterTest(unittest.TestCase):
    def test_real_parameterized_hdl_and_liberty_bus_stay_not_checked(self):
        from lib_guard.semantic.adapters import adapt_result
        from lib_guard.scan.parsers.base import make_parser_envelope
        from lib_guard.scan.parsers.verilog import parse_verilog_text
        from lib_guard.scan.parsers.liberty import parse_liberty_text
        samples = [('verilog', parse_verilog_text, 'module M(DATA);\ninput [W-1:0] DATA;\nendmodule\n'),
                   ('liberty', parse_liberty_text, 'library(L) {\ncell(M) {\nbus(DATA) {\nbus_type : data_bus;\ndirection : input;\n}\n}\n}\n')]
        for view, parse, text in samples:
            payload = make_parser_envelope(parser_name=view, parser_version='2.0', file='M', file_type=view, data=parse(text))
            fact = adapt_result(payload, evidence(view))
            self.assertEqual(fact['objects'][0]['coverage']['port_set'], 'NOT_EXTRACTED')

    def test_missing_port_fields_are_not_verified_empty(self):
        from lib_guard.semantic.adapters import adapt_result
        for view, object_path, field in [('lef', ['macros', 'M'], 'pins'),
                                        ('liberty', ['libraries', 'L', 'cells', 'M'], 'pins'),
                                        ('verilog', ['modules', 'M'], 'ports')]:
            result = parser_result(view, complete=True)
            obj = result['data']
            for key in object_path:
                obj = obj[key]
            del obj[field]
            fact = adapt_result(result, evidence(view))
            self.assertEqual(fact['objects'][0]['coverage']['port_set'], 'NOT_EXTRACTED')
            self.assertEqual(fact['coverage']['port_set'], 'NOT_EXTRACTED')
            obj[field] = None
            fact = adapt_result(result, evidence(view))
            self.assertEqual(fact['coverage']['port_set'], 'NOT_EXTRACTED')

    def test_width_without_range_is_unknown_not_scalar(self):
        from lib_guard.semantic.adapters import adapt_result
        result = parser_result('verilog', complete=True)
        result['data']['modules']['M']['ports']['CLK']['width'] = 32
        fact = adapt_result(result, evidence('verilog'))
        self.assertEqual(fact['objects'][0]['coverage']['port_set'], 'NOT_EXTRACTED')
        self.assertEqual(fact['coverage']['port_set'], 'NOT_EXTRACTED')
        result['data']['modules']['M']['ports']['CLK']['declared_range'] = '[7:0]'
        fact = adapt_result(result, evidence('verilog'))
        self.assertEqual(fact['objects'][0]['coverage']['port_set'], 'NOT_EXTRACTED')

    def test_legacy_pass_does_not_claim_complete_ports_T09(self):
        from lib_guard.semantic.adapters import adapt_result
        for view in ('lef', 'liberty', 'verilog'):
            result = parser_result(view)
            before = copy.deepcopy(result)
            fact = adapt_result(result, evidence(view))
            self.assertEqual(fact['objects'][0]['coverage']['port_set'], 'NOT_EXTRACTED')
            self.assertEqual(result, before)

    def test_geometry_and_units_T15(self):
        from lib_guard.semantic.adapters import adapt_result
        result = parser_result(complete=True)
        result['data']['geometry_detail'] = 'counts_only'
        fact = adapt_result(result, evidence())
        self.assertEqual(fact['objects'][0]['coverage']['pin_geometry'], 'NOT_EXTRACTED')
        self.assertEqual(fact['objects'][0]['attributes']['width_um']['value'], 1000)
        result['data']['database_microns'] = None
        obj = adapt_result(result, evidence())['objects'][0]
        self.assertEqual(obj['attributes']['width_um']['coverage'], 'NOT_EXTRACTED')

    def test_unverified_geometry_is_not_duplicated_into_facts(self):
        from lib_guard.semantic.adapters import adapt_result
        result = parser_result()
        result['data']['macros']['M']['pins']['CLK']['rects'] = [{'x1': 1, 'y1': 2, 'x2': 3, 'y2': 4}]
        obj = adapt_result(result, evidence())['objects'][0]
        self.assertIsNone(obj['ports'][0]['geometry'])

    def test_corner_not_guessed_from_filename_T06(self):
        from lib_guard.semantic.adapters import adapt_result
        ref = {**evidence('liberty'), 'source_relpath': 'tt_0p8v_25c.lib'}
        fact = adapt_result(parser_result('liberty', complete=True), ref)
        self.assertIsNone(fact['corner'])
        self.assertEqual(fact['corner_status'], 'UNRESOLVED')
        self.assertEqual(fact['objects'][0]['ports'][1]['kind'], 'POWER')

    def test_failed_empty_and_binary_are_not_semantic_success_T25_T26(self):
        from lib_guard.semantic.adapters import adapt_result
        for status in ('FAILED', 'PASS_EMPTY', 'UNSUPPORTED', 'METADATA_ONLY', 'SKIPPED'):
            fact = adapt_result({**parser_result(), 'status': status}, evidence())
            self.assertEqual(fact['objects'], [])
            self.assertNotEqual(fact['coverage']['port_set'], 'PRESENT')
        fact = adapt_result({'status': 'PASS', 'file_type': 'db', 'data': {'size': 30}}, evidence('db'))
        self.assertEqual(fact['objects'], [])
        self.assertEqual(fact['parse_status'], 'METADATA_ONLY')

    def test_unknown_parameter_range_never_complete_T09(self):
        from lib_guard.semantic.adapters import adapt_result
        result = parser_result('verilog', complete=True)
        result['data']['modules']['M']['ports']['DATA'] = {'direction': 'input', 'declared_range': '[W-1:0]', 'width': '[W-1:0]'}
        fact = adapt_result(result, evidence('verilog'))
        self.assertEqual(fact['objects'][0]['coverage']['port_set'], 'NOT_EXTRACTED')
        self.assertEqual(fact['unparsed_features'], ['instance'])
