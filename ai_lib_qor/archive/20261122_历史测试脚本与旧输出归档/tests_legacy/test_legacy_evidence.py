import json
import tempfile
import unittest
from pathlib import Path

from ai_lib_qor.facts.rich_evidence import parse_delivery_evidence
from ai_lib_qor.sources.delivery_builder import build_delivery

class LegacyEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'m.v').write_text('module MAC_A(input wire A, output wire Z); endmodule\n')
        (self.root/'m.cdl').write_text('.SUBCKT MAC_A A Z VDD VSS\nM1 Z A VSS VSS NMOS\n.ENDS MAC_A\n')
        (self.root/'m.lef').write_text('MACRO MAC_A\n SIZE 4 BY 8 ;\n PIN VDD\n DIRECTION INOUT ;\n USE POWER ;\n PORT\n LAYER M1 ;\n RECT 0 0 1 1 ;\n END\n END VDD\nEND MAC_A\n')
        meta={'delivery_id':'d1','vendor_id':'v','source_library_id':'lib','supplier_version':'v1','delivery_order':1,'received_at':'2026-01-01T00:00:00Z','package_mode':'FULL','scope_confirmed':True}
        mapping={name:{'file_key':'lib:'+name,'view':view,'corner':None,'mode':None} for name,view in [('m.v','VERILOG'),('m.cdl','CDL'),('m.lef','LEF')]}
        self.delivery=build_delivery(self.root,meta,mapping)
    def parse(self, view):
        file_id=next(x['file_id'] for x in self.delivery['files'] if x['view']==view)
        return parse_delivery_evidence(self.delivery,file_id)
    def test_verilog_module_and_pin_evidence(self):
        evidence=self.parse('VERILOG')
        self.assertEqual(evidence['view'],'VERILOG')
        self.assertEqual(evidence['data']['modules']['MAC_A']['ports']['A']['direction'],'input')
        self.assertEqual(len(evidence['source_sha256']),64)
    def test_cdl_subckt_and_devices_are_preserved(self):
        evidence=self.parse('CDL')
        self.assertEqual(evidence['data']['subckts']['MAC_A']['pins'],['A','Z','VDD','VSS'])
        self.assertEqual(evidence['data']['stats']['instance_count'],1)
        self.assertEqual(evidence['coverage'],'PARTIAL')
    def test_lef_pg_evidence_does_not_become_v3_facts(self):
        evidence=self.parse('LEF')
        self.assertEqual(evidence['data']['macros']['MAC_A']['pins']['VDD']['use'].upper(),'POWER')
        self.assertNotEqual(evidence['schema_version'],'file_facts.v1')
    def test_evidence_content_hash_detects_tampering(self):
        from ai_lib_qor.facts.rich_evidence import validate_evidence
        evidence=self.parse('VERILOG');evidence['data']['modules']['MAC_A']['ports']['A']['direction']='output'
        with self.assertRaises(ValueError): validate_evidence(evidence)

    def test_cli_exports_evidence_without_writing_raw(self):
        import os, subprocess, sys
        with tempfile.TemporaryDirectory() as output_dir:
            output=Path(output_dir); delivery=output/'delivery.json'; result=output/'evidence.json'
            delivery.write_text(json.dumps(self.delivery))
            file_id=next(x['file_id'] for x in self.delivery['files'] if x['view']=='VERILOG')
            env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')+':'+os.environ.get('PYTHONPATH','')}
            proc=subprocess.run([sys.executable,'-m','ai_lib_qor','facts-evidence','--delivery',str(delivery),'--file-id',file_id,'--out',str(result)],capture_output=True,text=True,env=env)
            self.assertEqual(proc.returncode,0,proc.stderr)
            self.assertEqual(json.loads(result.read_text())['view'],'VERILOG')
            proc2=subprocess.run([sys.executable,'-m','ai_lib_qor','facts-evidence','--delivery',str(delivery),'--file-id',file_id,'--out',str(self.root/'bad.json')],capture_output=True,text=True,env=env)
            self.assertNotEqual(proc2.returncode,0)
            self.assertFalse((self.root/'bad.json').exists())

    def test_html_escapes_evidence_text(self):
        from ai_lib_qor.reporting.evidence_html import render_evidence_html
        (self.root/'m.v').write_text('module MAC_A(input A); // <script>alert(1)</script>\n endmodule')
        html=render_evidence_html(self.parse('VERILOG'))
        self.assertNotIn('<script>alert(1)</script>',html)
