"""Shared in-memory JSON projections. Never scan or open source files."""
from collections import defaultdict
from pathlib import PurePosixPath, Path
import posixpath
import json

from .catalog import load_catalog
from .source_repository import SourceRepository
from ai_lib_qor.versions.composer import changes_between, members_map


def _view(value, path):
    value=(value or 'OTHER').upper()
    name=path.lower()
    if name.endswith('.gz'):name=name[:-3]
    ext=PurePosixPath(name).suffix
    if value=='CDL' and ext in ('.spice','.sp'):return 'SPICE'
    if value not in ('OTHER','UNKNOWN'):return value
    return {'.lef':'LEF','.lib':'LIBERTY','.gds':'GDS','.cdl':'CDL','.db':'DB','.spice':'SPICE','.sp':'SPICE','.pdf':'DOC','.xlsx':'DOC','.xls':'DOC','.txt':'DOC','.md':'DOC','.v':'VERILOG','.sv':'VERILOG'}.get(ext,value)


def _subgroup(view, path):
    parts=[p.upper() for p in PurePosixPath(path).parts]
    if view=='LIBERTY':return next((p for p in parts if p in ('NLDM','CCS','ECSM')), 'UNKNOWN')
    if view=='DOC':
        return {'.PDF':'PDF','.XLS':'EXCEL','.XLSX':'EXCEL','.TXT':'TEXT','.MD':'TEXT'}.get(PurePosixPath(path).suffix.upper(),'OTHER')
    return None


class LibraryDataQuery:
    def __init__(self,work,runs):
        self.work=work
        self.repo=SourceRepository(work)
        self.deliveries=self.repo.deliveries()
        cfg=Path(work)/'scan_sources.json';self._order_rules={}
        if cfg.is_file() and not cfg.is_symlink():
            data=json.loads(cfg.read_text(encoding='utf-8'))
            for source in data.get('sources',[]):
                rule=source.get('order_rule')
                if rule:self._order_rules[(source['vendor_id'],source['source_library_id'])]=rule
        self.entries,self.snapshots,warnings=load_catalog(work)
        if warnings:raise ValueError('查询记录存在冲突或损坏：'+'；'.join(warnings))
        self._snapshot_owners={}
        for item in self.repo.formal():
            record=item['record'];parts=Path(item['path']).relative_to(Path(work).resolve()).parts
            owner=(parts[1],parts[2]) if parts[0]=='libraries' else (parts[1],parts[3]) if parts[0]=='vendors' else None
            self._snapshot_owners[(record['formal_nl_id'],record['formal_snapshot_id'])]=owner
        self._refs=defaultdict(list)
        self._history=defaultdict(list)
        self._recorded_paths=defaultdict(list)
        for item in self.deliveries:
            d=item['record']
            for f in item['files']:
                self._refs[(d['source_library_id'],d['delivery_id'],f['file_id'])].append((d,f))
                self._history[(d['vendor_id'],d['source_library_id'],_view(f['view'],f['relative_path']),f['relative_path'])].append((item,f))
                rel=PurePosixPath(f['relative_path'])
                if posixpath.isabs(d['source_root']) and not rel.is_absolute() and '..' not in rel.parts:
                    self._recorded_paths[posixpath.normpath(posixpath.join(d['source_root'],str(rel)))].append((d,f))

    def _delivery(self,vendor,library,version,delivery_id=None):
        matches=[x for x in self.deliveries if (x['record']['vendor_id'],x['record']['source_library_id'],x['record']['supplier_version'])==(vendor,library,version) and (not delivery_id or x['record']['delivery_id']==delivery_id)]
        if len(matches)!=1:raise ValueError('交付版本不存在或不唯一，请使用明确交付 ID')
        return matches[0]

    def _raw_reference(self,ref):
        if not ref or ref.get('kind')!='delivery_file':return None
        matches=self._refs.get((ref['source_library_id'],ref['delivery_id'],ref['file_id']),[])
        if len(matches)!=1:return None
        d,f=matches[0]
        return {'vendor':d['vendor_id'],'library':d['source_library_id'],'delivery_id':d['delivery_id'],
                'version':d['supplier_version'],'path':f['relative_path'],'view':_view(f['view'],f['relative_path']),
                'file_key':f['file_key'],'identity_status':f['identity_status']}

    def get_raw_files(self,vendor,library,version,view=None,delivery_id=None):
        item=self._delivery(vendor,library,version,delivery_id);d=item['record'];views={}
        for f in item['files']:
            kind=_view(f['view'],f['relative_path'])
            if view and kind!=view.upper():continue
            sub=_subgroup(kind,f['relative_path'])
            if sub:views.setdefault(kind,{}).setdefault(sub,[]).append(f['relative_path'])
            else:views.setdefault(kind,[]).append(f['relative_path'])
        return {'schema':'raw_view.v1','context':{'vendor':vendor,'library':library,'version':version,
                'delivery_id':d['delivery_id'],'root':d['source_root'],'recorded_at':d['received_at']},'views':views}

    def get_file_history(self,vendor,library,view,path):
        occurrences=[]
        for item,f in self._history.get((vendor,library,view.upper(),path),[]):
            d=item['record']
            occurrences.append({'delivery_id':d['delivery_id'],'version':d['supplier_version'],
                'file_id':f['file_id'],'file_key':f['file_key'],'identity_status':f['identity_status'],
                'delivery_order':d['delivery_order'],'order_basis':item['order_basis'],'ordering_status':item['ordering_status']})
        orders=[x['delivery_order'] for x in occurrences]
        confirmed=bool(occurrences) and all(x['ordering_status']=='CONFIRMED' for x in occurrences) and len(set(orders))==len(orders)
        basis='CONFIGURED_SEQUENCE' if confirmed else None;warning=None
        rule=self._order_rules.get((vendor,library))
        if not confirmed and rule=={'type':'VERSION_DATE_PREFIX','confirmed':True}:
            from .simple_sources import version_date_order
            raw=[{'delivery_id':x['record']['delivery_id'],'context':{'version':x['record']['supplier_version']}}
                 for x in self.deliveries if (x['record']['vendor_id'],x['record']['source_library_id'])==(vendor,library)]
            try:
                ordered=version_date_order(raw);rank={ident:i for i,ident in enumerate(ordered)}
                occurrences.sort(key=lambda x:rank[x['delivery_id']]);confirmed=bool(occurrences);basis='CONFIRMED_VERSION_DATE_PREFIX'
            except (ValueError,KeyError) as exc:warning=str(exc)
        elif confirmed:occurrences.sort(key=lambda x:x['delivery_order'])
        return {'view':view.upper(),'path':path,'occurrences':occurrences,'ordering_status':'CONFIRMED' if confirmed else 'ORDER_UNCONFIRMED',
                'order_basis':basis,'ordering_warning':warning,'latest':occurrences[-1] if confirmed else None,'previous':occurrences[-2] if confirmed and len(occurrences)>1 else None}

    def get_history_index(self,vendor,library):
        result={}
        for v,l,kind,path in self._history:
            if (v,l)==(vendor,library):result.setdefault(kind,{})[path]=self.get_file_history(v,l,kind,path)
        return {'context':{'vendor':vendor,'library':library},'views':result}

    def _revision(self,vendor,library,owner,revision):
        matches=[r for e in self.entries if (e['vendor'],e['library'],e['ip'])==(vendor,library,owner) for r in e['versions'] if r['revision_id']==revision]
        if len(matches)!=1:raise ValueError('有效版本不存在或不唯一')
        return matches[0]

    def get_effective_files(self,vendor,library,owner,revision,view=None):
        record=self._revision(vendor,library,owner,revision);views={};unresolved=[]
        for m in record['members']:
            ref=m['source_ref'];source=None
            if ref['kind']=='delivery_file':
                source=self._raw_reference(ref)
                if source and source['file_key']!=m['file_key']:source=None
            elif ref['kind']=='formal_file':
                matches=[f for s in self.snapshots if (s['formal_nl_id'],s['formal_snapshot_id'])==(ref['formal_nl_id'],ref['formal_snapshot_id']) for f in s['linked_files'] if f['file_id']==ref['file_id']]
                if len(matches)==1 and matches[0]['file_key']==m['file_key']:
                    f=matches[0];source={'path':f['link_path'],'view':_view(None,f['link_path']),'formal_ref':ref,'resolved_path':f['resolved_path']}
                    if f.get('source_ref'):source['raw_source']=self._raw_reference(f['source_ref'])
            if source is None:unresolved.append({'file_key':m['file_key'],'source_ref':ref});continue
            kind=source['view'];path=source['path']
            if view and kind!=view.upper():continue
            bucket=views.setdefault(kind,{})
            if path in bucket:raise ValueError(f'多个有效成员使用相同 View 和路径，不能覆盖: {kind}/{path}')
            bucket[path]={**source,'source_ref':ref,'effective_file_key':m['file_key']}
        return {'schema':'effective_view.v1','context':{'vendor':vendor,'library':library,'owner':owner,'revision':revision,'effective_set_id':record['effective_set_id']},'views':views,'unresolved':unresolved}

    def get_formal_files(self,vendor,library,nl,snapshot_id,view=None):
        matches=[s for s in self.snapshots if (s['formal_nl_id'],s['formal_snapshot_id'])==(nl,snapshot_id) and library in s['scope']['source_library_ids']]
        if len(matches)!=1:raise ValueError('正式快照不存在、不唯一或不在该库范围')
        snap=matches[0];views={}
        owner=self._snapshot_owners.get((nl,snapshot_id))
        if owner and owner!=(vendor,library):raise ValueError('正式快照属于其他供应商或库')
        unassigned=[]
        for f in snap['linked_files']:
            raw=self._raw_reference(f['source_ref']) if f.get('source_ref') else None
            if raw and raw['file_key']!=f['file_key']:raw=None
            basis='CONTRACT_REFERENCE' if raw else None
            if not raw and f.get('resolved_path'):
                candidates=self._recorded_paths.get(posixpath.normpath(f['resolved_path']),[])
                if len(candidates)==1:
                    d,df=candidates[0]
                    ref={'kind':'delivery_file','source_library_id':d['source_library_id'],'delivery_id':d['delivery_id'],'file_id':df['file_id']}
                    raw=self._raw_reference(ref);basis='ARCHIVED_PATH_TEXT'
            if raw and (raw['vendor'],raw['library'])!=(vendor,library):continue
            if not owner and not raw:
                unassigned.append({'link_path':f['link_path'],'resolved_path':f['resolved_path'],'source_match':f['source_match'],
                                   'link_target':f.get('link_target'),'link_target_status':'RECORDED' if 'link_target' in f else 'NOT_RECORDED'})
                continue
            kind=raw['view'] if raw else _view(None,f['link_path'])
            if view and kind!=view.upper():continue
            bucket=views.setdefault(kind,{})
            if f['link_path'] in bucket:raise ValueError('正式链接路径重复')
            bucket[f['link_path']]={'raw_source':raw,'path_match_basis':basis,'resolved_path':f['resolved_path'],'source_match':f['source_match'],
                                    'file_key':f['file_key'],'source_ref':f['source_ref'],
                                    'link_target':f.get('link_target'),'link_target_status':'RECORDED' if 'link_target' in f else 'NOT_RECORDED'}
        return {'schema':'formal_view.v1','context':{'vendor':vendor,'library':library,'version':nl,'snapshot_id':snapshot_id,
                'root':snap['source_root'],'recorded_at':snap['observed_at'],'coverage':snap['coverage']},'views':views,'unassigned':unassigned}

    def compare_effective(self,vendor,library,owner,rev_a,rev_b):
        a=self._revision(vendor,library,owner,rev_a);b=self._revision(vendor,library,owner,rev_b)
        if a['effective_set_id']!=b['effective_set_id']:raise ValueError('不能对比不同有效集')
        return {'from':rev_a,'to':rev_b,'meaning':'SOURCE_RELATIONSHIP_ONLY','changes':changes_between(members_map(a),members_map(b))}


def query_data(work,runs,kind,**options):
    if not Path(work).is_dir():raise ValueError('work 目录不存在')
    required={'raw':('vendor','library','version'),'simple-raw':('vendor','library','version'),'history':('vendor','library','view','path'),'history-index':('vendor','library'),
              'effective':('vendor','library','owner','revision'),'effective-v2':('vendor','library','set_id','revision'),'simple-effective':('vendor','library','owner','revision'),'formal':('vendor','library','version','snapshot'),
              'simple-formal':('vendor','library','version','snapshot'),'compare':('vendor','library','owner','revision','other_revision')}
    if kind not in required:raise ValueError('不支持的查询类型')
    missing=[k for k in required[kind] if not options.get(k)]
    if missing:raise ValueError('缺少查询参数：'+', '.join(missing))
    if kind=='effective-v2':
        return get_effective_v2_files(work,options['vendor'],options['library'],options['set_id'],options['revision'],options.get('view'))
    q=LibraryDataQuery(work,runs);v=options.get('vendor');l=options.get('library');view=options.get('view')
    if kind=='raw':return q.get_raw_files(v,l,options['version'],view,options.get('delivery_id'))
    if kind=='simple-raw':
        from .simple_sources import simple_raw
        return simple_raw(q,v,l,options['version'],options.get('delivery_id'))
    if kind=='simple-formal':
        from .simple_sources import simple_formal
        return simple_formal(q,v,l,options['version'],options['snapshot'])
    if kind=='simple-effective':
        from .simple_sources import simple_effective
        return simple_effective(q,v,l,options['owner'],options['revision'])
    if kind=='history':return q.get_file_history(v,l,view,options['path'])
    if kind=='history-index':return q.get_history_index(v,l)
    if kind=='effective':return q.get_effective_files(v,l,options['owner'],options['revision'],view)
    if kind=='formal':return q.get_formal_files(v,l,options['version'],options['snapshot'],view)
    return q.compare_effective(v,l,options['owner'],options['revision'],options['other_revision'])


def get_effective_v2_files(work,vendor,library,set_id,revision,view=None):
    """Read an explicit saved v2 revision and archived delivery records only."""
    import re
    from .effective_json import _flat_views
    from ai_lib_qor.sources.layout import SAFE, library_folder
    from ai_lib_qor.versions.store import read_json
    if not isinstance(set_id,str) or not SAFE.fullmatch(set_id):raise ValueError('有效集标识无效')
    match=re.fullmatch(r'rev_(\d{4,})',revision or '')
    if not match:raise ValueError('版本标识无效')
    folder=library_folder(work,vendor,library)
    path=folder/f'effective_{set_id}_{int(match.group(1)):03d}.json'
    if path.is_symlink() or not path.is_file():raise ValueError('有效版本文件不存在或不安全')
    record=read_json(path,'effective_simple_v2')
    if record['revision']!=revision or record['scope']!={'vendor':vendor,'library':library}:
        raise ValueError('有效版本身份与目录不一致')
    deliveries=SourceRepository(work).deliveries();files=[]
    for (kind,rel),source in sorted(_flat_views(record).items()):
        if view and kind!=view.upper():continue
        matches=[x for x in deliveries if (x['record']['vendor_id'],x['record']['source_library_id'],x['record']['supplier_version']) ==
                 (source['vendor'],source['library'],source['version']) and
                 (x['record']['delivery_id']==source['delivery'] or Path(x['path']).stem==source['delivery'])]
        row={'view':kind,'path':rel,'source':source,'resolution':'MISSING_DELIVERY','identity_status':'UNKNOWN',
             'classification':'UNKNOWN','content_status':'NOT_CHECKED','source_root':None,'recorded_path':None,'file_key':None,'file_id':None,'delivery_id':None}
        if len(matches)>1:row['resolution']='AMBIGUOUS_DELIVERY'
        elif len(matches)==1:
            item=matches[0];matches_file=[f for f in item['files'] if f['relative_path']==rel and _view(f['view'],rel)==kind]
            row['source_root']=item['record']['source_root']
            row['delivery_id']=item['record']['delivery_id']
            if len(matches_file)>1:row['resolution']='AMBIGUOUS_FILE'
            elif not matches_file:row['resolution']='MISSING_FILE_RECORD'
            else:
                f=matches_file[0];row.update(resolution='RECORDED',identity_status=f['identity_status'],classification=f['classification'],
                    recorded_path=posixpath.join(item['record']['source_root'],rel),file_key=f['file_key'],file_id=f['file_id'])
        files.append(row)
    return {'schema':'effective_v2_read.v1','scope':record['scope'],'owner':record['owner'],'set_id':set_id,
            'revision':revision,'parent':record['parent'],'formal_baseline':record.get('formal_baseline'),
            'formal_nl':record.get('formal_nl'),'files':files,'meaning':'RECORDED_SOURCE_ONLY'}


def list_effective_v2(work,vendor,library):
    """Discover valid flat v2 revision records without reading source directories."""
    import re
    from ai_lib_qor.sources.layout import SAFE, library_folder
    from ai_lib_qor.versions.store import read_json
    folder=library_folder(work,vendor,library); result=[]
    for path in sorted(folder.glob('effective_*_[0-9]*.json')):
        match=re.fullmatch(r'effective_(.+)_(\d+)\.json',path.name)
        if not match or not SAFE.fullmatch(match.group(1)) or path.is_symlink():continue
        try:record=read_json(path,'effective_simple_v2')
        except (OSError,ValueError,KeyError):continue
        revision='rev_'+match.group(2).zfill(4)
        if record['revision']!=revision or record['scope']!={'vendor':vendor,'library':library}:continue
        result.append({'set_id':match.group(1),'revision':revision,'owner':record['owner']})
    return result
