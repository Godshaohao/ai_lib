import unittest

from lib_guard.scan.parsers.liberty import parse_liberty_text
from lib_guard.scan.parsers.verilog import parse_verilog_text


class DeclaredInterfacesTest(unittest.TestCase):
    def test_liberty_internal_node_is_not_an_external_signal_pin(self):
        from lib_guard.semantic.adapters import adapt_result
        from lib_guard.semantic.binding import bind_macros
        from lib_guard.semantic.checks import check_bindings
        text = 'library(L){cell(M){pin(A){direction:input;} pin(IQ){direction:internal; internal_node:"IQ";}}}'
        payload = {'file_type': 'liberty', 'status': 'PASS', 'data': parse_liberty_text(text)}
        liberty = adapt_result(payload, {'file_type': 'liberty', 'library_id': 'ip/demo', 'parser_result_ref': 'lib'})
        rtl = adapt_result({'file_type': 'verilog', 'status': 'PASS',
            'data': parse_verilog_text('module M(A); input A; endmodule')},
            {'file_type': 'verilog', 'library_id': 'ip/demo', 'parser_result_ref': 'rtl'})
        self.assertEqual([port['name'] for port in liberty['objects'][0]['ports']], ['A'])
        bindings = bind_macros([liberty, rtl], required_views=['liberty', 'verilog'])
        checks = check_bindings(bindings, enabled_checks=['SIGNAL_PORT_SET', 'SIGNAL_PORT_DIRECTION'])
        self.assertTrue(all(row['status'] == 'PASS' for row in checks))
        self.assertIn('IQ', payload['data']['libraries']['L']['cells']['M']['pins'])

    def test_liberty_nested_groups_do_not_close_library_or_steal_pin_attributes(self):
        text = '''/* cell (FAKE) { } */
library (L) {
  lu_table_template (T) { variable_1 : input_net_transition; }
  operating_conditions (TT) { voltage : 0.7; }
  cell (M) {
    area : 1.2;
    pin (A) { direction : input; }
    pin (Y) { direction : output; function : "A";
      timing () { related_pin : "A"; cell_rise (T) { values ("1, 2"); } }
    }
    pg_pin (VDD) { pg_type : primary_power; voltage_name : VDD; }
    pg_pin (VSS) { pg_type : primary_ground; voltage_name : VSS; }
  }
  cell (N) { pin (A) { direction : output; } }
}'''
        data = parse_liberty_text(text)
        self.assertEqual(data['stats']['cell_count'], 2)
        macro = data['libraries']['L']['cells']['M']
        self.assertEqual(macro['pins']['A']['direction'], 'input')
        self.assertEqual(macro['pins']['Y']['direction'], 'output')
        self.assertEqual(macro['pg_pins']['VDD']['pg_type'], 'primary_power')
        self.assertEqual(data['semantic_coverage']['port_set'], 'PRESENT')
        self.assertEqual(data['semantic_coverage']['pg_port_set'], 'PRESENT')

    def test_liberty_unsupported_bus_duplicate_or_truncation_never_claims_complete_ports(self):
        for text in ('library(L){cell(M){pin(A){direction:input;}',
                     'library(L){cell(M){pin(A){direction:input;} pin(A){direction:input;}}}',
                     'library(L){cell(M){pin(A){direction:input;} pin(B);}}',
                     'library(L){cell(M){pin(A){direction:input;timing(){pin(B);}}}}',
                     'library(L){cell(M){bus(A){bus_type:B; pin(A[0]){direction:input;}}}}',
                     'library(L){cell(M){area:1.2\npg_pin(VDD){pg_type:primary_power;} pin(A){direction:input;}}}',
                     'library(L){cell(M){pin(A){direction:input;}}} /* unclosed',
                     'library(L){cell(M){pin(A){function:"unclosed;}}}'):
            with self.subTest(text=text):
                data = parse_liberty_text(text)
                self.assertEqual(data.get('semantic_coverage', {}).get('port_set'), 'NOT_EXTRACTED')

    def test_trailing_udp_preprocessor_does_not_invalidate_complete_module_interfaces(self):
        text = 'module M(A); input A; endmodule\n`ifdef U\n`else\n`define U\nprimitive udp(q,a); output q; input a; endprimitive\n`endif'
        data = parse_verilog_text(text)
        self.assertEqual(data['semantic_coverage']['port_set'], 'PRESENT')
        guarded = '`ifdef FEATURE\nmodule M(A); input A; endmodule\n`endif'
        self.assertEqual(parse_verilog_text(guarded)['semantic_coverage']['port_set'], 'NOT_EXTRACTED')

    def test_guarded_primitives_between_modules_do_not_hide_unconditional_ports(self):
        text = 'module A(p); input p; endmodule\n`ifdef UDP\n`else\n`define UDP\nprimitive u(q,a); output q; input a; endprimitive\n`endif\nmodule B(p); output p; endmodule'
        self.assertEqual(parse_verilog_text(text)['semantic_coverage']['port_set'], 'PRESENT')

    def test_verilog_ports_are_scoped_to_their_module(self):
        text = 'module A(p); output p; endmodule\nmodule B(p); input p; endmodule\n'
        data = parse_verilog_text(text)
        self.assertEqual(data['modules']['A']['ports']['p']['direction'], 'output')
        self.assertEqual(data['modules']['B']['ports']['p']['direction'], 'input')
        self.assertEqual(data['semantic_coverage']['port_set'], 'PRESENT')

    def test_verilog_ansi_inheritance_and_unsupported_interfaces(self):
        text = 'module M(input wire [3:0] A, B, output logic Y); endmodule'
        data = parse_verilog_text(text)
        self.assertEqual(set(data['modules']['M']['ports']), {'A', 'B', 'Y'})
        self.assertEqual(data['modules']['M']['ports']['B']['direction'], 'input')
        self.assertEqual(data['modules']['M']['ports']['B']['width'], 4)
        self.assertEqual(data['semantic_coverage']['port_set'], 'PRESENT')
        for unsupported in ('module M(input [N-1:0] A); endmodule',
                            'module M(input A); output A; endmodule',
                            'module M(A); input A;',
                            'module M(A); input A; endmodule module M(A); input A; endmodule',
                            'module M(A); `ifdef X\ninput A;\n`endif\nendmodule'):
            self.assertEqual(parse_verilog_text(unsupported).get('semantic_coverage', {}).get('port_set'), 'NOT_EXTRACTED')
