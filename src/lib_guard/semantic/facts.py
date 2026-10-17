"""Content-addressed view facts, with source references attached only on read."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from lib_guard.atomic import atomic_write_json, file_lock
from lib_guard.view_types import canonical_file_type
from .adapters import adapt_result
from .model import FACT_SCHEMA_VERSION, canonical_json, implementation_identity

ADAPTER_VERSION = 'semantic_adapter.v1'


class FactsStorageError(RuntimeError):
    pass


def _digest(value):
    return 'sha256:' + hashlib.sha256(canonical_json(value).encode()).hexdigest()


def load_file_fact(path, fact_id):
    record = json.loads(Path(path).read_text(encoding='utf-8'))
    if (record.get('schema_version') != 'semantic_fact_record.v1'
            or record.get('fact_id') != fact_id or _digest(record.get('identity')) != fact_id
            or _digest(record.get('fact')) != record.get('payload_digest')
            or record['fact'].get('schema_version') != FACT_SCHEMA_VERSION):
        raise ValueError(f'文件事实校验失败：{path}')
    return record['fact']


def attach_source(fact, evidence, fact_id, fact_ref):
    value = deepcopy(fact)
    value.update(fact_id=fact_id, fact_ref=str(fact_ref), file_identity={**deepcopy(evidence),
                 'fact_id': fact_id, 'fact_ref': str(fact_ref)},
                 variant=evidence.get('variant'), corner=evidence.get('corner'),
                 corner_status='CONFIRMED' if evidence.get('corner') else 'UNRESOLVED')
    value['parser']['result_ref'] = evidence.get('parser_result_ref')
    return value


class FileFactsStore:
    def __init__(self, directory, *, reuse=True):
        self.directory = Path(directory).resolve()
        self.reuse = reuse
        self.adapter_identity = {'version': ADAPTER_VERSION, 'code': implementation_identity(
            'lib_guard.semantic.adapters', 'lib_guard.semantic.normalize', 'lib_guard.semantic.model', 'lib_guard.semantic.facts')}
        self.stats = {'hits': 0, 'adapted': 0}

    def get_or_adapt(self, result, evidence):
        try:
            return self._get_or_adapt(result, evidence)
        except OSError as error:
            raise FactsStorageError(f'文件事实存储失败：{self.directory}；{error}') from error

    def _get_or_adapt(self, result, evidence):
        # This hashes already-read parser evidence, not RAW bytes or a partial RAW fingerprint.
        parser_input = {key: result.get(key) for key in ('parser_name', 'parser_version', 'status', 'data')}
        parser_input['file_type'] = canonical_file_type(result.get('file_type') or evidence['file_type'])
        identity = {'schema_version': FACT_SCHEMA_VERSION, 'adapter': self.adapter_identity,
                    'parser_evidence_digest': _digest(parser_input)}
        fact_id = _digest(identity)
        digest = fact_id.split(':', 1)[1]
        path = self.directory / digest[:2] / f'{digest}.json'
        with file_lock(path.with_suffix('.lock')):
            cached = None
            if path.exists():
                try:
                    cached = load_file_fact(path, fact_id)
                except (ValueError, KeyError, TypeError):
                    pass
            if self.reuse and cached is not None:
                self.stats['hits'] += 1
                fact = cached
            else:
                fact = adapt_result(result, {'file_type': parser_input['file_type']})
                if fact['view'] == 'lef':
                    for obj in fact['objects']:
                        for port in obj['ports']:
                            port['geometry'] = None
                            port['layers'] = None
                        obj['coverage'].update(pin_geometry='NOT_EXTRACTED', pin_layers='NOT_EXTRACTED')
                for key in ('file_identity', 'corner', 'corner_status', 'variant'):
                    fact.pop(key, None)
                fact['parser'].pop('result_ref', None)
                self.stats['adapted'] += 1
                if cached is not None and cached != fact:
                    raise FactsStorageError('相同 Parser 输入与转换版本产生不同 Facts，拒绝覆盖已有事实')
                if cached != fact:
                    atomic_write_json(path, {'schema_version': 'semantic_fact_record.v1',
                        'fact_id': fact_id, 'identity': identity, 'fact': fact, 'payload_digest': _digest(fact)})
        return attach_source(fact, evidence, fact_id, path)
