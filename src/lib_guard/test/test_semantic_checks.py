import copy
import unittest
from lib_guard.test.test_semantic_binding import facts
from lib_guard.semantic.binding import bind_macros


class SemanticChecksTest(unittest.TestCase):
    def test_disabled_rules_do_not_execute(self):
        from unittest.mock import patch
        from lib_guard.semantic.checks import check_bindings, compare_bindings
        bindings = bind_macros(facts())
        with patch('lib_guard.semantic.checks._ports', side_effect=AssertionError('disabled port rule ran')):
            rows = check_bindings(bindings, enabled_checks={'MACRO_BINDING'})
        self.assertEqual([row['check_id'] for row in rows], ['MACRO_BINDING'])
        self.assertEqual(compare_bindings(bindings, bindings, enabled_checks=set()), [])

    def test_liberty_port_delta_is_scoped_to_the_changed_corner(self):
        from lib_guard.semantic.checks import check_bindings, compare_bindings
        rows = facts()
        rows[1].update(corner='TT', corner_status='CONFIRMED')
        ss = copy.deepcopy(rows[1])
        ss['corner'] = 'SS'
        rows.append(ss)
        before = bind_macros(rows)
        rows[1]['objects'][0]['ports'][0]['name'] = 'CHANGED_CLK'
        after = bind_macros(rows)
        delta = compare_bindings(before, after, enabled_checks={'LIB_PORT_DELTA'})
        signal = {row['corner']: row['status'] for row in delta if row['attribute'] == 'signal_ports'}
        self.assertEqual(signal, {'SS': 'UNCHANGED', 'TT': 'CHANGED'})
        self.assertEqual(next(row for row in check_bindings(after) if row['check_id'] == 'SIGNAL_PORT_SET')['status'], 'FAIL')
        self.assertTrue(all(row['status'] == 'UNKNOWN' for row in compare_bindings([], after, enabled_checks={'LIB_PORT_DELTA'})))

    def test_declared_geometry_requires_actual_shapes(self):
        from lib_guard.test.test_semantic_adapter import parser_result, evidence
        from lib_guard.semantic.adapters import adapt_result
        from lib_guard.semantic.checks import compare_bindings
        source = parser_result(complete=True)
        source['data']['semantic_coverage'].update(pin_geometry='PRESENT', pin_layers='PRESENT')
        pin = source['data']['macros']['M']['pins']['CLK']
        pin['rects'] = [{'layer': 'M2', 'x1': 0, 'y1': 0, 'x2': 1, 'y2': 1}]
        rows = facts()
        rows[0] = adapt_result(source, evidence())
        self.assertEqual(next(row for row in compare_bindings(bind_macros(rows), bind_macros(rows)) if row['attribute'] == 'geometry')['status'], 'UNCHANGED')
        del pin['rects']
        rows[0] = adapt_result(source, evidence())
        self.assertEqual(next(row for row in compare_bindings(bind_macros(rows), bind_macros(rows)) if row['attribute'] == 'geometry')['status'], 'UNKNOWN')
        del pin['layers']
        rows[0] = adapt_result(source, evidence())
        self.assertEqual(next(row for row in compare_bindings(bind_macros(rows), bind_macros(rows)) if row['attribute'] == 'layers')['status'], 'UNKNOWN')

    def test_missing_layers_not_unchanged(self):
        from lib_guard.semantic.adapters import adapt_result
        from lib_guard.test.test_semantic_adapter import parser_result, evidence
        from lib_guard.semantic.checks import compare_bindings
        source = parser_result(complete=True)
        del source['data']['macros']['M']['pins']['CLK']['layers']
        rows = facts()
        rows[0] = adapt_result(source, evidence())
        row = next(row for row in compare_bindings(bind_macros(rows), bind_macros(rows)) if row['attribute'] == 'layers')
        self.assertEqual(row['status'], 'UNKNOWN')

    def check(self, rows, rule):
        from lib_guard.semantic.checks import check_bindings
        return next(item for item in check_bindings(bind_macros(rows)) if item['check_id'] == rule)

    def test_complete_signal_ports_pass_T07(self):
        self.assertEqual(self.check(facts(), 'SIGNAL_PORT_SET')['status'], 'PASS')
        self.assertEqual(self.check(facts(), 'SIGNAL_PORT_DIRECTION')['status'], 'PASS')

    def test_real_missing_port_fail_with_source_T08(self):
        rows = facts()
        rows[0]['objects'][0]['ports'] = []
        result = self.check(rows, 'SIGNAL_PORT_SET')
        self.assertEqual(result['status'], 'FAIL')
        self.assertIn('parser_results/lef/a.json', result['evidence_refs'])
        self.assertIn('CLK', str(result['actual']))
        direction = self.check(rows, 'SIGNAL_PORT_DIRECTION')
        self.assertEqual(direction['status'], 'NOT_CHECKED')
        self.assertEqual(direction['reason_code'], 'UNALIGNED_PORT_SET')

    def test_direction_contradiction_fails(self):
        rows = facts()
        rows[0]['objects'][0]['ports'][0]['direction'] = 'OUTPUT'
        self.assertEqual(self.check(rows, 'SIGNAL_PORT_DIRECTION')['status'], 'FAIL')

    def test_incomplete_and_ambiguous_never_pass_T09(self):
        rows = facts()
        rows[0]['objects'][0]['coverage']['port_set'] = 'NOT_EXTRACTED'
        self.assertEqual(self.check(rows, 'SIGNAL_PORT_SET')['status'], 'NOT_CHECKED')
        rows = facts()
        self.assertEqual(self.check(rows + [copy.deepcopy(rows[0])], 'SIGNAL_PORT_SET')['status'], 'NOT_CHECKED')

    def test_pg_separate_from_verilog_and_role_error_T10_T11(self):
        rows = facts()
        rows[0]['objects'][0]['ports'].append({'name': 'VDD', 'kind': 'POWER'})
        self.assertEqual(self.check(rows, 'PG_PORT_LEF_LIB')['status'], 'PASS')
        rows[0]['objects'][0]['ports'][-1]['kind'] = 'GROUND'
        self.assertEqual(self.check(rows, 'PG_PORT_LEF_LIB')['status'], 'FAIL')

    def test_area_not_cross_compared_and_flags_are_configured_T17(self):
        from lib_guard.semantic.checks import check_bindings
        rows = check_bindings(bind_macros(facts()))
        flags = next(row for row in rows if row['check_id'] == 'LIB_MACRO_FLAGS')
        self.assertEqual(flags['status'], 'NOT_APPLICABLE')
        rows = check_bindings(bind_macros(facts()), flag_policy={'is_macro': False})
        self.assertEqual(next(row for row in rows if row['check_id'] == 'LIB_MACRO_FLAGS')['status'], 'FAIL')
        self.assertFalse(any(row['check_id'] == 'LIB_LEF_AREA' for row in rows))

    def test_size_delta_evidence_tolerance_T16_T27(self):
        from lib_guard.semantic.checks import compare_bindings
        old = bind_macros(facts())
        current = copy.deepcopy(old)
        obs = next(row for row in current[0]['observations'] if row['view'] == 'lef')
        obs['object']['attributes']['width_um']['value'] = 1100
        rows = compare_bindings(old, current)
        delta = next(row for row in rows if row['check_id'] == 'LEF_SIZE_DELTA' and row['attribute'] == 'width_um')
        self.assertEqual(delta['status'], 'CHANGED')
        self.assertEqual((delta['old'], delta['new']), (1000, 1100))
        self.assertTrue(delta['old_evidence'] and delta['new_evidence'])
        obs['object']['attributes']['width_um']['value'] = 1000 + 1e-8
        delta = next(row for row in compare_bindings(old, current) if row['attribute'] == 'width_um')
        self.assertEqual(delta['status'], 'UNCHANGED')
        self.assertTrue(all(row['status'] == 'UNKNOWN' for row in compare_bindings([], current)))

    def test_incomplete_geometry_unknown_T15(self):
        from lib_guard.semantic.checks import compare_bindings
        bindings = bind_macros(facts())
        row = next(row for row in compare_bindings(bindings, bindings) if row['attribute'] == 'geometry')
        self.assertEqual(row['status'], 'UNKNOWN')

    def test_orientation_separate_from_bit_set_T14(self):
        from lib_guard.semantic.checks import compare_bindings
        rows = facts()
        rows[2]['objects'][0]['ports'][0].update(name='DATA', declared_range='[31:0]', width=32)
        old = bind_macros(rows)
        rows[2]['objects'][0]['ports'][0]['declared_range'] = '[0:31]'
        delta = next(row for row in compare_bindings(old, bind_macros(rows)) if row['check_id'] == 'PORT_DECLARATION_DELTA')
        self.assertEqual(delta['status'], 'CHANGED')
