"""Minimal local filesystem store for one effective set (POSIX advisory lock)."""
import contextlib
import fcntl
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator
from .composer import verify_delta
from .index_projector import project

SCHEMAS = Path(__file__).resolve().parents[3] / 'schemas'
REV = re.compile(r'rev_(\d{4,})\Z')


def flat_effective(root):
    root=Path(root)
    return root.name.startswith('effective_') and root.parent.parent.parent.name=='libraries'


def revision_path(root, revision):
    root=Path(root); match=REV.fullmatch(revision)
    if not match: raise ValueError('有效版本标识无效')
    return root.parent/f'{root.name}_{int(match.group(1)):03d}.json' if flat_effective(root) else root/'versions'/f'{revision}.json'


def index_path(root):
    root=Path(root)
    return root.parent/f'{root.name}_index.json' if flat_effective(root) else root/'index.json'


def event_path(root):
    root=Path(root)
    return root.parent/f'{root.name}_acceptance.jsonl' if flat_effective(root) else root/'acceptance.jsonl'


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def validate(data, name):
    if name=='formal_snapshot' and isinstance(data,dict) and data.get('schema_version')=='formal_snapshot.v2':name='formal_snapshot_v2'
    schema = json.loads((SCHEMAS / f'{name}.schema.json').read_text(encoding='utf-8'))
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: str(list(e.absolute_path)))
    if errors:
        raise ValueError(f"{name} Schema 校验失败: {errors[0].message}")


def read_json(path, schema):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    validate(data, schema)
    return data


@contextlib.contextmanager
def locked(root):
    root = Path(root)
    if root.is_symlink(): raise ValueError('锁目录不能为符号链接')
    root.mkdir(parents=True, exist_ok=True)
    lockfile=root / '.versions.lock'
    if lockfile.is_symlink(): raise ValueError('锁文件不能为符号链接')
    with lockfile.open('a+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _payload(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def write_atomic(path, obj, immutable=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.tmp-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(_payload(obj)); f.flush(); os.fsync(f.fileno())
        if immutable:
            os.link(tmp, path)  # atomic create, never overwrites history
        else:
            os.replace(tmp, path)
        dirfd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(dirfd)
        finally: os.close(dirfd)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def revisions(root):
    root=Path(root); flat=flat_effective(root); directory = root.parent if flat else root/'versions'
    files = list(directory.glob(f'{root.name}_[0-9]*.json' if flat else '*.json')) if directory.exists() else []
    def revision_for(path):
        return 'rev_'+path.stem[len(root.name)+1:].zfill(4) if flat else path.stem
    if any(not REV.fullmatch(revision_for(p)) for p in files):
        raise ValueError('版本目录存在无效文件名')
    files.sort(key=lambda p: int(REV.fullmatch(revision_for(p)).group(1)))
    result = []
    for i, file in enumerate(files):
        if file.is_symlink():raise ValueError('版本文件不能为符号链接')
        item = read_json(file, 'effective_version')
        if item['revision_id'] != revision_for(file):
            raise ValueError('版本文件名与 ID 不匹配')
        parent = result[-1] if result else None
        if item['parent_revision_id'] != (parent['revision_id'] if parent else None):
            raise ValueError('版本历史不是单一连续父版本链')
        if parent and (item['owner'] != parent['owner'] or item['effective_set_id'] != parent['effective_set_id']):
            raise ValueError('版本所有者或有效集发生变化')
        verify_delta(parent, item)
        result.append(item)
    return result


def events(root):
    path = event_path(root)
    if path.is_symlink(): raise ValueError('采纳日志不能为符号链接')
    if not path.exists(): return []
    result = []
    with path.open(encoding='utf-8') as f:
        for number, line in enumerate(f, 1):
            try:
                event = json.loads(line); validate(event, 'acceptance_event'); result.append(event)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f'采纳事件第 {number} 行损坏: {exc}') from exc
    return result


def append_event(root, event):
    path = event_path(root)
    if path.is_symlink(): raise ValueError('采纳日志不能为符号链接')
    text = json.dumps(event, ensure_ascii=False, separators=(',', ':')) + '\n'
    with path.open('a', encoding='utf-8') as f:
        f.write(text); f.flush(); os.fsync(f.fileno())


def rebuild_index(root, revs=None, evts=None):
    revs = revisions(root) if revs is None else revs
    evts = events(root) if evts is None else evts
    index = project(revs, evts, now())
    validate(index, 'effective_index')
    if index_path(root).is_symlink():raise ValueError('有效索引不能为符号链接')
    write_atomic(index_path(root), index)
    if flat_effective(root):
        from ai_lib_qor.application.latest_pointers import refresh_library_locked
        root=Path(root);refresh_library_locked(root.parent.parent.parent.parent,root.parent.parent.name,root.parent.name)
    return index


def archive_delivery(root, delivery):
    """Freeze consumed source records and prevent unintentional out-of-order application."""
    if flat_effective(root):
        from ai_lib_qor.application.source_repository import SourceRepository
        root=Path(root); work=root.parent.parent.parent.parent
        records=SourceRepository(work).deliveries()
        matches=[x['record'] for x in records if x['record']['delivery_id']==delivery['delivery_id']
                 and x['record']['source_library_id']==delivery['source_library_id'] and x['record']['vendor_id']==delivery['vendor_id']]
        if len(matches)!=1 or matches[0]!=delivery:
            raise ValueError('交付记录未唯一登记或内容冲突')
        others=[x['record'] for x in records if x['record']['source_library_id']==delivery['source_library_id']
                and x['record']['delivery_id']==delivery['delivery_id'] and x['record']['vendor_id']!=delivery['vendor_id']]
        if any({f['file_id'] for f in old['files']} & {f['file_id'] for f in delivery['files']} for old in others):
            raise ValueError('跨供应商交付文件引用不唯一')
        used={r['reason']['ref_id'] for r in revisions(root) if r['reason']['kind']=='RAW_DELIVERY'}
        for item in records:
            old=item['record']
            if old['delivery_id'] in used and old['source_library_id']==delivery['source_library_id'] and old['delivery_id']!=delivery['delivery_id'] and old['delivery_order']>=delivery['delivery_order']:
                raise ValueError('交付顺序不递增或出现相同 order')
        return
    directory = Path(root) / '_inputs' / 'deliveries'
    directory.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(delivery['delivery_id'].encode('utf-8')).hexdigest()
    target = directory / (key + '.json')
    existing = [read_json(p, 'delivery_record') for p in directory.glob('*.json')]
    for old in existing:
        if old['delivery_id'] == delivery['delivery_id'] and old != delivery:
            raise ValueError('同一 delivery_id 的内容发生变化，不能覆盖历史')
        if old['source_library_id'] == delivery['source_library_id'] and old['delivery_id'] != delivery['delivery_id']:
            if old['delivery_order'] >= delivery['delivery_order']:
                raise ValueError('交付顺序不递增或出现相同 order；回退请使用采纳回退')
    if not target.exists():
        write_atomic(target, delivery, immutable=True)
