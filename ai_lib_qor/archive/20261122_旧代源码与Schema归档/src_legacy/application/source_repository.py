"""Read-only access to archived source records; never opens RAW or Formal roots."""
from copy import deepcopy
import json
from pathlib import Path

from ai_lib_qor.versions.store import read_json
from ai_lib_qor.sources.layout import evidence_path


def archive_fingerprint(work):
    """Observe archive metadata only; never walk RAW or Formal source trees."""
    root=Path(work).resolve();patterns=('scan_sources.json','libraries/*/*/delivery_*.json','libraries/*/*/evidence_delivery_*.json',
        'libraries/*/*/formal_*.json','libraries/*/*/effective_*_[0-9]*.json','libraries/*/*/file_index.json',
        'vendors/*/libraries/*/deliveries/*.json','vendors/*/libraries/*/deliveries/*/delivery.json',
        'vendors/*/libraries/*/ips/*/effective/versions/*.json',
        'vendors/*/libraries/*/formal_nl/*/snapshots/*/snapshot.json','raw/*/*/*.json',
        'formal_nl/*/snapshots/*.json','formal_nl/*/snapshots/*/snapshot.json','formal/*/*.json')
    paths=sorted({p for pattern in patterns for p in root.glob(pattern)})
    result=[]
    for path in paths:
        s=path.lstat();result.append((str(path.relative_to(root)),s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns))
    return tuple(result)


class SourceRepository:
    def __init__(self, root, *, reader=None, warnings=None):
        self.root = Path(root).resolve()
        self.reader = reader or read_json
        self.warnings = warnings

    def _paths(self, patterns):
        for path in sorted({p for pattern in patterns for p in self.root.glob(pattern)}):
            if any(p.is_symlink() for p in [path, *path.parents] if p != self.root and p.is_relative_to(self.root)):
                continue
            if path.is_file():
                yield path

    def deliveries(self, *, vendor=None, library=None):
        if (vendor is None)!=(library is None):raise ValueError('必须同时限定供应商和库')
        if vendor is not None:
            from ai_lib_qor.sources.layout import SAFE
            if any(not isinstance(x,str) or not SAFE.fullmatch(x) or x in ('.','..') for x in (vendor,library)):
                raise ValueError('供应商或库标识不安全')
            patterns=(f'vendors/{vendor}/libraries/{library}/deliveries/*.json',
                      f'vendors/{vendor}/libraries/{library}/deliveries/*/delivery.json',
                      f'raw/{vendor}/{library}/*.json',f'libraries/{vendor}/{library}/delivery_*.json')
        else:
            patterns=('vendors/*/libraries/*/deliveries/*.json',
                      'vendors/*/libraries/*/deliveries/*/delivery.json', 'raw/*/*/*.json',
                      'libraries/*/*/delivery_*.json')
        records={}; conflicts=set()
        for path in self._paths(patterns):
            try:
                record=self.reader(path,'delivery_record')
                parts=path.relative_to(self.root).parts
                vendor,library=(parts[1],parts[3]) if parts[0]=='vendors' else (parts[1],parts[2])
                if (vendor,library)!=(record['vendor_id'],record['source_library_id']):
                    raise ValueError(f'交付归属与目录不一致: {path}')
                key=(vendor,library,record['delivery_id'])
                if key in records and records[key]['record'] != record:
                    conflicts.add(key)
                    raise ValueError(f"交付身份冲突: {records[key]['path']} 与 {path}")
                if key not in records:
                    records[key]={'record':record,'path':path,'evidence':None}
                evidence=evidence_path(path)
                if evidence.is_file() and not evidence.is_symlink():
                    data=json.loads(evidence.read_text(encoding='utf-8'))
                    old=records[key]['evidence']
                    if old is not None and old!=data:
                        conflicts.add(key)
                        raise ValueError(f'交付证据冲突: {evidence}')
                    records[key]['evidence']=data
            except (OSError,ValueError,KeyError,TypeError) as exc:
                if self.warnings is None: raise
                self.warnings.append(f'{path}: 交付不可读取: {exc}')
        output=[]
        for key,item in records.items():
            if key in conflicts: continue
            record=item['record']; evidence=item['evidence'] or {}
            observations={x['path']:x for x in evidence.get('files',[]) if isinstance(x,dict) and 'path' in x}
            classifications=evidence.get('classification',{})
            files=[]
            for f in record['files']:
                file=deepcopy(f); rel=f['relative_path']; obs=observations.get(rel,{})
                basis=classifications.get(rel,{}).get('basis')
                file['identity_status']=('CONFIRMED' if basis=='explicit' else 'CANDIDATE' if basis=='filename_unique_candidate'
                                         else 'UNKNOWN')
                file['classification_basis']=basis
                file['observation']={k:obs[k] for k in ('size','mtime_ns') if k in obs}
                files.append(file)
            confirmed=[(f['view'],f['file_key']) for f in files if f['identity_status']=='CONFIRMED' and f.get('file_key')]
            if len(confirmed)!=len(set(confirmed)):
                raise ValueError(f"交付 {record['delivery_id']} 中已确认文件身份重复")
            order_basis=evidence.get('order_basis')
            output.append({'record':record,'path':str(item['path']),'evidence':item['evidence'],
                           'files':files,'ordering_status':'CONFIRMED' if order_basis in ('configured_order','manual_confirmation') else 'UNCONFIRMED',
                           'order_basis':order_basis})
        return output

    def formal(self):
        patterns=('formal_nl/*/snapshots/*.json','formal_nl/*/snapshots/*/snapshot.json',
                  'vendors/*/libraries/*/formal_nl/*/snapshots/*/snapshot.json','formal/*/*.json',
                  'libraries/*/*/formal_*.json')
        records={};conflicts=set()
        for path in self._paths(patterns):
            try:
                record=self.reader(path,'formal_snapshot')
                parts=path.relative_to(self.root).parts
                if parts[0]=='vendors' and (record['formal_nl_id']!=parts[5] or record['scope']['source_library_ids']!=[parts[3]]):
                    raise ValueError(f'正式快照范围与目录不一致: {path}')
                if parts[0]=='formal' and record['formal_nl_id']!=parts[1]:
                    raise ValueError(f'正式快照阶段与目录不一致: {path}')
                if parts[0]=='libraries' and record['scope']['source_library_ids']!=[parts[2]]:
                    raise ValueError(f'正式快照范围与目录不一致: {path}')
                key=(record['formal_nl_id'],record['formal_snapshot_id'])
                if key in records and records[key]['record']!=record:
                    conflicts.add(key)
                    raise ValueError(f"正式快照身份冲突: {records[key]['path']} 与 {path}")
                records.setdefault(key,{'record':record,'path':str(path)})
            except (OSError,ValueError,KeyError,TypeError) as exc:
                if self.warnings is None: raise
                self.warnings.append(f'{path}: 正式快照不可读取: {exc}')
        return [item for key,item in records.items() if key not in conflicts]

    def file_history(self, vendor, library, file_key):
        occurrences=[]
        for item in self.deliveries():
            delivery=item['record']
            if (delivery['vendor_id'],delivery['source_library_id']) != (vendor,library):
                continue
            for f in item['files']:
                if f['file_key']==file_key:
                    occurrences.append({'delivery_id':delivery['delivery_id'], 'supplier_version':delivery['supplier_version'],
                        'delivery_order':delivery['delivery_order'], 'ordering_status':item['ordering_status'],
                        'file_id':f['file_id'], 'identity_status':f['identity_status'], 'relative_path':f['relative_path']})
        orders=[x['delivery_order'] for x in occurrences]
        confirmed=bool(occurrences) and all(x['ordering_status']=='CONFIRMED' and x['identity_status']=='CONFIRMED' for x in occurrences) and len(orders)==len(set(orders))
        if confirmed: occurrences.sort(key=lambda x:x['delivery_order'],reverse=True)
        return {'file_key':file_key,'ordering_status':'CONFIRMED' if confirmed else 'ORDER_UNCONFIRMED',
                'occurrences':occurrences,'latest':occurrences[0] if confirmed else None,
                'previous':occurrences[1] if confirmed and len(occurrences)>1 else None}
