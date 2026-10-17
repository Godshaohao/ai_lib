"""Immutable result snapshots and history reads using shared file facts."""

from copy import deepcopy
import errno
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat

from lib_guard.atomic import atomic_write_json, atomic_write_text
from .facts import attach_source, load_file_fact
from .model import canonical_json


def _digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _map_fact_refs(value, convert):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'fact_ref' and isinstance(item, str):
                value[key] = convert(item)
            else:
                _map_fact_refs(item, convert)
    elif isinstance(value, list):
        for item in value:
            _map_fact_refs(item, convert)


def _relative_fact_ref(out, ref):
    path = Path(ref)
    return str(path.relative_to(out)) if path.is_absolute() and path.is_relative_to(out) else ref


def _absolute_fact_ref(out, ref):
    path = Path(ref)
    if path.is_absolute():
        return ref
    resolved = (out / path).resolve()
    if not resolved.is_relative_to(out):
        raise ValueError('结果快照 Facts 引用越界')
    return str(resolved)


def freeze_index(index, out):
    if index is None:
        return None
    value = {key: deepcopy(item) for key, item in index.items() if key != 'facts'}
    value['schema_version'] = 'semantic_effective_index_refs.v1'
    value['fact_refs'] = [{'fact_id': fact['fact_id'], 'fact_ref': fact['fact_ref'],
                           'evidence': deepcopy(fact['file_identity'])} for fact in index['facts']]
    _map_fact_refs(value, lambda ref: _relative_fact_ref(out, ref))
    return value


def freeze_bindings(bindings, out):
    result = deepcopy(bindings)
    for binding in result:
        binding['schema_version'] = 'semantic_binding_refs.v1'
        for obs in binding['observations']:
            obs['object_ref'] = obs.pop('object')['local_id']
    _map_fact_refs(result, lambda ref: _relative_fact_ref(out, ref))
    return result


def result_identity(summary, index, base_index, bindings, checks, delta):
    def semantic_value(value):
        if isinstance(value, dict):
            return {key: semantic_value(item) for key, item in value.items() if key != 'fact_ref'}
        if isinstance(value, list):
            return [semantic_value(item) for item in value]
        return value
    return _digest(semantic_value({'summary': summary, 'index': index, 'base_index': base_index,
                                   'bindings': bindings, 'checks': checks, 'delta': delta}))


def write_snapshot(out, summary, index, base_index, bindings, checks, delta, markdown):
    payloads = {
        'semantic_effective_index': {'current': index, 'base': base_index},
        'macro_bindings': {'schema_version': 'semantic_binding_refs.v1', 'bindings': bindings},
        'check_results': {'checks': checks, 'delta': delta},
    }
    digests = {key: _digest(value) for key, value in payloads.items()}
    digests['markdown'] = hashlib.sha256(markdown.encode()).hexdigest()
    descriptor = {'schema_version': 'semantic_snapshot.v1', 'summary': summary, 'digests': digests}
    descriptor_path = out / summary['artifacts']['snapshot_manifest']
    completed = descriptor_path.exists()
    all_payloads = {**payloads, 'snapshot_manifest': descriptor}
    for key, value in all_payloads.items():
        path = out / summary['artifacts'][key]
        if not path.exists() and completed:
            raise ValueError(f'已完成的结果快照缺少文件，拒绝改写：{path}')
        if path.exists() and canonical_json(json.loads(path.read_text(encoding='utf-8'))) != canonical_json(value):
            raise ValueError(f'已存在的结果快照内容不一致，拒绝覆盖：{path}')
    markdown_path = out / summary['artifacts']['markdown']
    if completed and not markdown_path.exists():
        raise ValueError(f'已完成的结果快照缺少摘要，拒绝改写：{markdown_path}')
    if markdown_path.exists() and markdown_path.read_text(encoding='utf-8') != markdown:
        raise ValueError(f'已存在的结果快照摘要不一致，拒绝覆盖：{markdown_path}')
    for key, value in payloads.items():
        path = out / summary['artifacts'][key]
        if not path.exists():
            atomic_write_json(path, value)
    if not markdown_path.exists():
        atomic_write_text(markdown_path, markdown)
    if not completed:
        atomic_write_json(descriptor_path, descriptor)


def deduplicate_report(out, store_root, generation, facts_dir):
    """Share immutable report bytes across Web jobs without changing their paths."""
    out, store_root, facts_dir = Path(out).resolve(), Path(store_root).resolve(), Path(facts_dir).resolve()
    files = sorted(path for path in (out / 'snapshots' / generation).iterdir() if path.is_file())
    if facts_dir == out / 'facts':
        files.extend(sorted(facts_dir.rglob('*.json')))
    for path in files:
        if path.is_symlink():
            continue
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        key = digest.hexdigest()
        bucket = store_root / key[:2]
        bucket.mkdir(parents=True, exist_ok=True)
        if not bucket.resolve().is_relative_to(store_root):
            raise ValueError('Artifact store path escapes its root')
        canonical = bucket / key
        if canonical.is_symlink():
            raise ValueError('Artifact store contains a symlink')
        try:
            os.link(path, canonical)
        except FileExistsError:
            pass
        except OSError as error:
            if error.errno in {errno.EXDEV, errno.EPERM, errno.EACCES, errno.EROFS}:
                continue
            raise
        if hashlib.sha256(canonical.read_bytes()).hexdigest() != key:
            raise ValueError('Artifact store content does not match its digest')
        canonical.chmod(stat.S_IMODE(canonical.stat().st_mode) & ~0o222)
        if path.samefile(canonical):
            continue
        temporary = path.with_name(f'.{path.name}.{os.getpid()}.{secrets.token_hex(4)}')
        try:
            os.link(canonical, temporary)
            os.replace(temporary, path)
        except OSError as error:
            if error.errno not in {errno.EXDEV, errno.EPERM, errno.EACCES, errno.EROFS}:
                raise
        finally:
            temporary.unlink(missing_ok=True)


def _restore_index(index, out):
    if index is None:
        return None
    result = deepcopy(index)
    _map_fact_refs(result, lambda ref: _absolute_fact_ref(out, ref))
    result['schema_version'] = 'semantic_effective_index.v1'
    result['facts'] = [attach_source(load_file_fact(ref['fact_ref'], ref['fact_id']), ref['evidence'],
                                     ref['fact_id'], ref['fact_ref']) for ref in result.pop('fact_refs')]
    return result


def load_review_snapshot(out_dir, generation=None):
    """Read a completed result without Catalog, RAW, scan, HTML or rule execution."""
    out = Path(out_dir).resolve()
    if generation is None:
        generation = json.loads((out / 'summary.json').read_text(encoding='utf-8'))['generation']
    if not isinstance(generation, str) or len(generation) != 64 or any(c not in '0123456789abcdef' for c in generation):
        raise ValueError('结果快照 generation 无效')
    snapshot = out / 'snapshots' / generation
    descriptor = json.loads((snapshot / 'snapshot.json').read_text(encoding='utf-8'))
    if descriptor.get('schema_version') != 'semantic_snapshot.v1':
        raise ValueError('不支持的结果快照格式')
    summary = descriptor['summary']
    if summary.get('generation') != generation:
        raise ValueError('结果快照身份不一致')
    payloads = {}
    for key, digest in descriptor['digests'].items():
        path = (out / summary['artifacts'][key]).resolve()
        if not path.is_relative_to(snapshot.resolve()):
            raise ValueError('结果快照产物路径越界')
        text = path.read_text(encoding='utf-8')
        value = text if key == 'markdown' else json.loads(text)
        actual = hashlib.sha256(text.encode()).hexdigest() if key == 'markdown' else _digest(value)
        if actual != digest:
            raise ValueError(f'结果快照校验失败：{path}')
        payloads[key] = value
    frozen = payloads['semantic_effective_index']
    checks = payloads['check_results']
    bindings = payloads['macro_bindings']['bindings']
    base_summary = {key: value for key, value in summary.items() if key not in {'generation', 'artifacts'}}
    if result_identity(base_summary, frozen['current'], frozen['base'], bindings, checks['checks'], checks['delta']) != generation:
        raise ValueError('结果快照输入与产物身份校验失败')
    current, base = _restore_index(frozen['current'], out), _restore_index(frozen['base'], out)
    facts = {fact['fact_id']: fact for fact in current['facts']}
    _map_fact_refs(bindings, lambda ref: _absolute_fact_ref(out, ref))
    for binding in bindings:
        binding['schema_version'] = 'semantic_binding.v1'
        for obs in binding['observations']:
            obj_id = obs.pop('object_ref')
            fact = facts[obs['evidence']['fact_id']]
            obs['object'] = deepcopy(next(obj for obj in fact['objects'] if obj['local_id'] == obj_id))
    return {'summary': summary, 'index': current, 'base_index': base, 'bindings': bindings, **checks}
