"""Small JSON contracts; extraction, coverage and judgement stay separate."""

import hashlib
import importlib
import json
from pathlib import Path

COVERAGE = {'PRESENT', 'ABSENT_VERIFIED', 'NOT_EXTRACTED', 'NOT_APPLICABLE', 'FAILED'}
CHECK_STATUS = {'PASS', 'FAIL', 'REVIEW_REQUIRED', 'NOT_CHECKED', 'NOT_APPLICABLE'}
POLICY_VERSION = 'semantic_rules.v1'
FACT_SCHEMA_VERSION = 'semantic_file_fact.v1'


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))


def implementation_identity(*modules):
    """Fingerprint the small Python implementations, never source library files."""
    return {name: 'sha256:' + hashlib.sha256(Path(importlib.import_module(name).__file__).read_bytes()).hexdigest()
            for name in modules}


def entity_id(library, name, variant=None):
    key = canonical_json([library, name, variant])
    return 'macro:' + hashlib.sha256(key.encode()).hexdigest()[:24]


def port_id(macro_id, logical_bit):
    return 'port:' + hashlib.sha256(canonical_json([macro_id, logical_bit]).encode()).hexdigest()[:24]


def attribute(value, coverage, *, unit=None):
    if coverage not in COVERAGE or (coverage == 'PRESENT' and value is None):
        raise ValueError('Invalid semantic attribute coverage')
    return {'value': value, 'coverage': coverage, 'unit': unit}


def check_result(check_id, macro_id, status, reason_code, evidence_refs, **details):
    if status not in CHECK_STATUS:
        raise ValueError('Invalid semantic check status')
    return {'schema_version': 'semantic_check_result.v1', 'check_id': check_id,
            'macro_id': macro_id, 'status': status, 'reason_code': reason_code,
            'evidence_refs': sorted(set(evidence_refs)), 'policy_version': POLICY_VERSION, **details}
