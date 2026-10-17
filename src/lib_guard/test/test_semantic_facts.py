import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lib_guard.test.test_semantic_adapter import evidence, parser_result


class SemanticFactsTest(unittest.TestCase):
    def test_same_parser_content_reuses_facts_with_fresh_source_references(self):
        from lib_guard.semantic.facts import FileFactsStore
        from lib_guard.semantic.adapters import adapt_result
        with tempfile.TemporaryDirectory() as td:
            store = FileFactsStore(td)
            payload = parser_result(complete=True)
            first_evidence = evidence()
            second_evidence = {**evidence(), 'source_version': 'fix',
                               'source_relpath': 'renamed/M.lef', 'corner': 'TT',
                               'parser_result_ref': 'new_scan/parser_results/lef/new.json'}
            with patch('lib_guard.semantic.facts.adapt_result', wraps=adapt_result) as adapt:
                first = store.get_or_adapt({**payload, 'file': 'old.lef'}, first_evidence)
                second = store.get_or_adapt({**payload, 'file': 'renamed.lef'}, second_evidence)
                self.assertEqual(adapt.call_count, 1)
            self.assertEqual(first['fact_id'], second['fact_id'])
            self.assertEqual(first['file_identity']['source_version'], 'full')
            self.assertEqual(second['file_identity']['source_version'], 'fix')
            self.assertEqual(second['parser']['result_ref'], second_evidence['parser_result_ref'])
            self.assertIsNone(first['corner'])
            self.assertEqual(second['corner'], 'TT')
            record = json.loads(Path(first['fact_ref']).read_text())
            self.assertNotIn('file_identity', record['fact'])
            self.assertNotIn('corner', record['fact'])
            self.assertNotIn('result_ref', record['fact']['parser'])

    def test_parser_adapter_and_payload_changes_have_separate_immutable_facts(self):
        from lib_guard.semantic.facts import FileFactsStore
        with tempfile.TemporaryDirectory() as td:
            store = FileFactsStore(td)
            payload = parser_result(complete=True)
            first = store.get_or_adapt(payload, evidence())
            before = Path(first['fact_ref']).read_bytes()
            changed = copy.deepcopy(payload)
            changed['data']['macros']['M']['size']['x'] = 1100
            second = store.get_or_adapt(changed, evidence())
            upgraded = store.get_or_adapt({**payload, 'parser_version': 'next'}, evidence())
            with patch('lib_guard.semantic.facts.ADAPTER_VERSION', 'semantic_adapter.next'):
                adapted = FileFactsStore(td).get_or_adapt(payload, evidence())
            self.assertEqual(len({f['fact_id'] for f in (first, second, upgraded, adapted)}), 4)
            self.assertEqual(Path(first['fact_ref']).read_bytes(), before)

    def test_corrupted_cache_rebuilds_without_upgrading_parser_coverage(self):
        from lib_guard.semantic.facts import FileFactsStore
        with tempfile.TemporaryDirectory() as td:
            store = FileFactsStore(td)
            first = store.get_or_adapt(parser_result(), evidence())
            path = Path(first['fact_ref'])
            damaged = json.loads(path.read_text())
            damaged['fact']['objects'][0]['coverage']['port_set'] = 'PRESENT'
            path.write_text(json.dumps(damaged))
            second = store.get_or_adapt(parser_result(), evidence())
            self.assertEqual(second, first)
            self.assertEqual(second['objects'][0]['coverage']['port_set'], 'NOT_EXTRACTED')

    def test_recompute_and_reuse_have_identical_semantics_and_do_not_rewrite_facts(self):
        from lib_guard.semantic.facts import FileFactsStore
        with tempfile.TemporaryDirectory() as td:
            store = FileFactsStore(td)
            first = store.get_or_adapt(parser_result(complete=True), evidence())
            stamp = Path(first['fact_ref']).stat().st_mtime_ns
            second = FileFactsStore(td, reuse=False).get_or_adapt(parser_result(complete=True), evidence())
            self.assertEqual(first, second)
            self.assertEqual(Path(first['fact_ref']).stat().st_mtime_ns, stamp)
