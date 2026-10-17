import unittest
from lib_guard.test.test_semantic_adapter import parser_result, evidence
from lib_guard.semantic.adapters import adapt_result


def facts():
    return [adapt_result(parser_result(view, complete=True), evidence(view))
            for view in ('lef', 'liberty', 'verilog')]


class SemanticBindingTest(unittest.TestCase):
    def test_unique_exact_T01(self):
        from lib_guard.semantic.binding import bind_macros
        row = bind_macros(facts())[0]
        self.assertEqual(row['status'], 'UNIQUE_EXACT')
        port = next(port for port in row['ports'] if port['logical_bit'] == 'CLK')
        self.assertEqual(len(port['observations']), 3)
        self.assertTrue(port['port_id'].startswith('port:'))
        self.assertEqual(port['port_id'], next(port for port in bind_macros(facts())[0]['ports'] if port['logical_bit'] == 'CLK')['port_id'])

    def test_mismatched_names_no_fuzzy_T02_and_alias_T03(self):
        from lib_guard.semantic.binding import bind_macros
        rows = facts()
        rows[1]['objects'][0]['name'] = 'OTHER'
        self.assertTrue(all(row['status'] == 'UNRESOLVED' for row in bind_macros(rows)))
        mapping = {'confirmed': True, 'macro_aliases': [{'view': 'liberty', 'object': 'OTHER', 'macro': 'M'}]}
        self.assertEqual(bind_macros(rows, mapping=mapping)[0]['status'], 'CONFIRMED')
        with self.assertRaises(ValueError):
            bind_macros(rows, mapping={**mapping, 'confirmed': False})

    def test_duplicate_and_multicorner_T04_T05(self):
        from lib_guard.semantic.binding import bind_macros
        rows = facts()
        extra = adapt_result(parser_result('liberty', complete=True), evidence('liberty'))
        self.assertEqual(bind_macros(rows + [extra])[0]['status'], 'AMBIGUOUS')
        rows[1].update(corner='TT', corner_status='CONFIRMED')
        extra.update(corner='FF', corner_status='CONFIRMED')
        bound = bind_macros(rows + [extra])[0]
        self.assertEqual(bound['status'], 'UNIQUE_EXACT')
        self.assertEqual(len(bound['observations']), 4)
        extra.update(corner=None, corner_status='UNRESOLVED')
        self.assertEqual(bind_macros(rows + [extra])[0]['status'], 'AMBIGUOUS')

    def test_bus_context_no_guess_T12_T13_T14(self):
        from lib_guard.semantic.normalize import normalize_port
        self.assertEqual(normalize_port({'name': 'DATA<0>', 'bus_chars': '<>'})['bits'], ['DATA[0]'])
        self.assertEqual(normalize_port({'name': 'DATA<0>'})['bits'], ['DATA<0>'])
        self.assertNotEqual(normalize_port({'name': 'DATA_0'})['bits'], ['DATA[0]'])
        self.assertEqual(normalize_port({'name': 'DATA_0'}, aliases={'DATA_0': 'DATA[0]'})['bits'], ['DATA[0]'])
        descending = normalize_port({'name': 'DATA', 'declared_range': '[31:0]'})
        ascending = normalize_port({'name': 'DATA', 'declared_range': '[0:31]'})
        self.assertEqual(descending['bits'], ascending['bits'])
        self.assertNotEqual(descending['orientation'], ascending['orientation'])
        self.assertIsNone(normalize_port({'name': 'DATA', 'declared_range': '[W-1:0]'})['bits'])
        self.assertIsNone(normalize_port({'name': 'DATA', 'width': 32})['bits'])

    def test_direction_policy_and_escaped_names(self):
        from lib_guard.semantic.normalize import normalize_port
        self.assertEqual(normalize_port({'name': 'CLK', 'direction': 'input'})['direction'], 'INPUT')
        self.assertEqual(normalize_port({'name': 'CLK', 'direction': 'feedthru'})['direction'], 'UNKNOWN')
        self.assertEqual(normalize_port({'name': '\\DATA<0>', 'bus_chars': '<>'})['bits'], ['\\DATA<0>'])
