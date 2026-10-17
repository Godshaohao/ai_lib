import json
import unittest


class SemanticContractTest(unittest.TestCase):
    def test_json_roundtrip_deterministic(self):
        from lib_guard.semantic.model import canonical_json, attribute
        a = {'z': attribute(2, 'PRESENT', unit='um'), 'a': [1, '中文']}
        self.assertEqual(canonical_json(a), canonical_json(dict(reversed(list(a.items())))))
        self.assertEqual(json.loads(canonical_json(a)), a)

    def test_rejects_invalid_coverage_and_nan(self):
        from lib_guard.semantic.model import attribute, canonical_json
        with self.assertRaises(ValueError):
            attribute(None, 'PRESENT')
        with self.assertRaises(ValueError):
            attribute(1, 'PASS')
        with self.assertRaises(ValueError):
            canonical_json({'value': float('nan')})

    def test_entity_identity_excludes_run_context(self):
        from lib_guard.semantic.model import entity_id, check_result
        self.assertEqual(entity_id('ip/a', 'M', None), entity_id('ip/a', 'M', None))
        self.assertNotEqual(entity_id('ip/a', 'M', None), entity_id('ip/b', 'M', None))
        self.assertNotEqual(entity_id('ip/a', 'M', None), entity_id('ip/a', 'M', 'functional'))
        row = check_result('SIGNAL_PORT_SET', 'M', 'NOT_CHECKED', 'INCOMPLETE_PORT_COVERAGE', ['b', 'a'])
        self.assertEqual(row['evidence_refs'], ['a', 'b'])
        with self.assertRaises(ValueError):
            check_result('SIGNAL_PORT_SET', 'M', 'UNCHANGED', '', [])
