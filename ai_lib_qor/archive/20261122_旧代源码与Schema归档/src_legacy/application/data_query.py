"""Shared JSON projections; explicit check methods alone read selected source files."""
from collections import defaultdict
from pathlib import PurePosixPath, Path
import posixpath
import json

from .catalog import load_catalog
from .source_repository import SourceRepository, archive_fingerprint
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
        self._archive_snapshot=archive_fingerprint(work)
        self.repo=SourceRepository(work)
        self.deliveries=self.repo.deliveries()
        cfg=Path(work)/'scan_sources.json';self._order_rules={};self._source_configs={}
        if cfg.is_file() and not cfg.is_symlink():
            data=json.loads(cfg.read_text(encoding='utf-8'))
            for source in data.get('sources',[]):
                self._source_configs[(source['vendor_id'],source['source_library_id'])]=source
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
        self._file_index_cache={}
        self._published_index_cache={}
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

    def list_deliveries(self,vendor,library):
        """List all registered deliveries, sorting only when the basis is confirmed."""
        from .simple_sources import _alias
        from .file_index import repository_order
        records=[x for x in self.deliveries if (x['record']['vendor_id'],x['record']['source_library_id'])==(vendor,library)]
        ordered,basis=repository_order(records,self._source_configs.get((vendor,library),{}))
        return {'vendor':vendor,'library':library,'ordering_status':'CONFIRMED' if ordered is not None else 'ORDER_UNCONFIRMED',
                'order_basis':basis,'deliveries':[{'delivery_id':x['record']['delivery_id'],
                  'delivery':_alias(self,vendor,library,x['record']['delivery_id']),
                  'version':x['record']['supplier_version'],'root':x['record']['source_root'],
                  'recorded_at':x['record']['received_at']} for x in (ordered if ordered is not None else records)]}

    def _simple_revision(self,vendor,library,set_id,revision):
        import re
        from ai_lib_qor.sources.layout import SAFE,library_folder
        from ai_lib_qor.versions.store import read_json
        from .simple_sources import simple_effective
        if not isinstance(set_id,str) or not SAFE.fullmatch(set_id):raise ValueError('有效集标识无效')
        m=re.fullmatch(r'rev_(\d{4,})',revision or '')
        if not m:raise ValueError('版本标识无效')
        folder=library_folder(self.work,vendor,library);path=folder/f'effective_{set_id}_{int(m.group(1)):03d}.json'
        if path.is_symlink():raise ValueError('历史版本不能是软链接')
        if path.is_file():
            data=json.loads(path.read_text(encoding='utf-8'))
            if data.get('schema')=='effective.simple.v2':
                data=read_json(path,'effective_simple_v2')
                if data['revision']!=revision or data['scope']!={'vendor':vendor,'library':library}:raise ValueError('版本归属不一致')
                return data
        matches=[e for e in self.entries if (e['vendor'],e['library'],e['index']['effective_set_id'])==(vendor,library,set_id)]
        if len(matches)!=1:raise ValueError('有效集不存在或不唯一')
        return simple_effective(self,vendor,library,matches[0]['index']['owner']['owner_id'],revision)

    def compare_revisions(self,vendor,library,set_id,rev_a,rev_b):
        from .effective_json import compare_revisions
        return compare_revisions(self._simple_revision(vendor,library,set_id,rev_a),self._simple_revision(vendor,library,set_id,rev_b))

    def compare_revisions_logical(self,vendor,library,set_id,rev_a,rev_b):
        """Compare confirmed file identities; otherwise match exact View and path."""
        from .effective_json import _flat_views
        def select(rev):
            output=[]
            for (view,path),source in _flat_views(self._simple_revision(vendor,library,set_id,rev)).items():
                loc=self._source_location(source,view,path)
                if loc['resolution']!='RECORDED':raise ValueError('有效文件来源无法唯一定位')
                confirmed=loc['identity_status']=='CONFIRMED' and loc['classification']=='RESOLVED' and bool(loc.get('file_key'))
                output.append({'view':view,'path':path,'source':source,'delivery_id':loc['delivery_id'],
                               'file_key':loc.get('file_key'),'identity_status':loc['identity_status'],'_confirmed':confirmed})
            keys=[(x['view'],x['source']['vendor'],x['source']['library'],x['file_key']) for x in output if x['_confirmed']]
            if len(keys)!=len(set(keys)):raise ValueError('同一版本的逻辑文件身份不唯一')
            return output
        before=select(rev_a);after=select(rev_b);rows=[];matched=set();matched_old=set()
        def logical(x):return (x['view'],x['source']['vendor'],x['source']['library'],x['file_key'])
        def emit(old,new,basis):
            change='ADDED' if old is None else 'REMOVED' if new is None else 'UNCHANGED' if (old['delivery_id'],old['path'])==(new['delivery_id'],new['path']) else 'SOURCE_CHANGED'
            clean=lambda x:{k:v for k,v in x.items() if k!='_confirmed'} if x else None
            rows.append({'match_basis':basis,'change':change,'before':clean(old),'after':clean(new),'content_status':'NOT_CHECKED'})
        for j,old in enumerate(before):
            choices=[i for i,new in enumerate(after) if i not in matched and old['_confirmed'] and new['_confirmed'] and logical(old)==logical(new)]
            if len(choices)>1:raise ValueError('有效文件匹配不唯一')
            if choices:matched_old.add(j);matched.add(choices[0]);emit(old,after[choices[0]],'CONFIRMED_KEY')
        for j,old in enumerate(before):
            if j in matched_old:continue
            choices=[i for i,new in enumerate(after) if i not in matched and (old['view'],old['path'])==(new['view'],new['path'])]
            if len(choices)>1:raise ValueError('有效文件匹配不唯一')
            if choices:matched.add(choices[0]);emit(old,after[choices[0]],'PATH')
            else:emit(old,None,'UNMATCHED')
        for i,new in enumerate(after):
            if i not in matched:emit(None,new,'UNMATCHED')
        return {'from':rev_a,'to':rev_b,'meaning':'CONFIRMED_IDENTITY_OR_EXACT_PATH_SOURCE_ONLY','files':rows}

    def get_check_context(self,vendor,library,set_id,revision,baseline=None,selected_views=None):
        """Build one in-memory check input from validated archives and the published index."""
        from .effective_json import _flat_views
        index=self.published_v3_index(vendor,library)
        effective=index.get('effective_sets',{}).get(set_id)
        if not effective:raise ValueError('有效集不在索引中')
        revisions=[x for x in effective['revisions'] if x['revision']==revision]
        if len(revisions)!=1:raise ValueError('目标版本不在索引中')
        parent=revisions[0]['parent'];baseline=parent if baseline is None else baseline
        if selected_views is not None and not isinstance(selected_views,(list,tuple,set)):raise ValueError('检查 View 选择无效')
        views=set(selected_views) if selected_views is not None else None
        if views is not None and (not views or any(not isinstance(x,str) or not x for x in views)):raise ValueError('检查 View 选择无效')
        unresolved=[];formal=[]
        def files_for(rev):
            if not rev:return []
            record=self._simple_revision(vendor,library,set_id,rev);result=[]
            for (view,path),source in _flat_views(record).items():
                if views is not None and view not in views:continue
                node=index.get('views',{}).get(view,{}).get('files',{}).get(path,{})
                indexed=[x for x in node.get('effective',{}).get(set_id,[]) if x.get('revision')==rev]
                if len(indexed)!=1:raise ValueError('有效文件在索引中不存在或不唯一')
                source_path=indexed[0].get('source_path',path)
                loc=self._source_location(source,view,source_path)
                if loc['resolution']!='RECORDED':unresolved.append({'revision':rev,'view':view,'path':path,'reason':loc['resolution']})
                confirmed=loc.get('identity_status')=='CONFIRMED' and loc.get('classification')=='RESOLVED'
                row={'view':view,'effective_path':path,'source_scope':{'vendor':source['vendor'],'library':source['library']},
                     'delivery_id':loc.get('delivery_id'),'file_id':loc.get('file_id'),'file_key':loc.get('file_key') if confirmed else None,
                     'identity_status':loc.get('identity_status','UNKNOWN'),'source_relative_path':source_path,'absolute_path':loc.get('absolute_path'),
                     'resolution':loc['resolution'],'subtype':node.get('model')}
                result.append(row)
                if rev==revision:
                    for ref in node.get('formal',[]):formal.append({'view':view,'path':path,**ref})
            return result
        selected=files_for(revision);base=files_for(baseline)
        changes=[];logical=[]
        if baseline:
            changes=[{**x,'content_status':'NOT_CHECKED'} for x in self.compare_revisions(vendor,library,set_id,baseline,revision)['files'] if views is None or x['view'] in views]
            try:logical=self.compare_revisions_logical(vendor,library,set_id,baseline,revision)['files']
            except ValueError as exc:unresolved.append({'revision':baseline,'reason':str(exc)})
            if views is not None:logical=[x for x in logical if (x.get('after') or x.get('before'))['view'] in views]
        for view,group in index.get('views',{}).items():
            if views is not None and view not in views:continue
            for item in group.get('unmatched_formal',[]):formal.append({'view':view,'unmatched':True,**item})
        return {'target':{'owner':effective['owner'],'set_id':set_id,'revision':revision,'parent':parent},
                'selected_files':selected,'baseline_files':base,'source_changes':changes,'logical_matches':logical,
                'formal_refs':formal,'unresolved':unresolved,'provenance':{'status':'VALID','source':'PUBLISHED_INDEX','content_status':'NOT_CHECKED'}}

    def published_v3_index(self,vendor,library):
        from ai_lib_qor.sources.layout import library_folder
        from copy import deepcopy
        _,state=self._verified_file_index(vendor,library)
        if state!='VALID':raise ValueError('v3 索引不可用：'+state)
        saved=self._published_index_cache.get((vendor,library))
        if not saved:raise ValueError('需要已发布的 v3 索引')
        path=library_folder(self.work,vendor,library)/'file_index.json';stat=path.stat()
        if path.is_symlink() or (stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)!=saved[1]:raise ValueError('索引在核验后发生变化')
        return deepcopy(saved[0])

    def file_timeline(self,vendor,library,set_id,view,path,revisions):
        from .effective_json import file_timeline
        return file_timeline([self._simple_revision(vendor,library,set_id,r) for r in revisions],view,path)

    def _source_location(self,source,view,path):
        matches=[x for x in self.deliveries if (x['record']['vendor_id'],x['record']['source_library_id'],x['record']['supplier_version'])==
                 (source['vendor'],source['library'],source['version']) and
                 (x['record']['delivery_id']==source['delivery'] or Path(x['path']).stem==source['delivery'])]
        row={**source,'view':view,'path':path,'root':None,'absolute_path':None,'resolution':'MISSING_DELIVERY'}
        if len(matches)>1:row['resolution']='AMBIGUOUS_DELIVERY'
        elif len(matches)==1:
            item=matches[0];files=[f for f in item['files'] if f['relative_path']==path and _view(f['view'],path)==view]
            if len(files)>1:row['resolution']='AMBIGUOUS_FILE'
            elif not files:row['resolution']='MISSING_FILE_RECORD'
            elif not posixpath.isabs(item['record']['source_root']):row['resolution']='INVALID_ROOT'
            else:row.update(resolution='RECORDED',root=item['record']['source_root'],
                            absolute_path=posixpath.join(item['record']['source_root'],path),delivery_id=item['record']['delivery_id'],
                            file_id=files[0]['file_id'],file_key=files[0]['file_key'],
                            classification=files[0]['classification'],identity_status=files[0]['identity_status'])
        return row

    def get_changed_file_pairs(self,vendor,library,set_id,rev_a,rev_b):
        comparison=self.compare_revisions(vendor,library,set_id,rev_a,rev_b);pairs=[]
        for row in comparison['files']:
            if row['change']!='SOURCE_CHANGED':continue
            pairs.append({'view':row['view'],'path':row['path'],'change':row['change'],'content_status':'NOT_CHECKED',
                          'before':self._source_location(row['before'],row['view'],row['path']),
                          'after':self._source_location(row['after'],row['view'],row['path'])})
        return {'from':rev_a,'to':rev_b,'meaning':'SOURCE_ONLY','pairs':pairs}

    def parse_changed_file_pairs(self,vendor,library,set_id,rev_a,rev_b,*,views):
        """Parse only explicitly selected source-change pairs; no cache on disk."""
        if not isinstance(views,(list,tuple,set)) or not views or any(x not in ('LEF','LIBERTY') for x in views):
            raise ValueError('必须明确选择 LEF 或 LIBERTY')
        from ai_lib_qor.facts.parsers import parse_delivery_file
        pairs=self.get_changed_file_pairs(vendor,library,set_id,rev_a,rev_b)['pairs'];out=[];cache={}
        for pair in pairs:
            if pair['view'] not in views:continue
            item={**pair,'status':'NOT_CHECKED','before_facts':None,'after_facts':None}
            try:
                for side in ('before','after'):
                    source=pair[side]
                    if source['resolution']!='RECORDED' or source.get('identity_status')!='CONFIRMED' or source.get('classification')!='RESOLVED':
                        raise ValueError(f"{side} 来源缺失、歧义或身份未确认")
                    if len(self._refs[(source['library'],source['delivery_id'],source['file_id'])]) != 1:
                        raise ValueError(f"{side} 旧版文件身份跨供应商不唯一")
                    key=(source['vendor'],source['library'],source['delivery_id'],source['file_id'])
                    if key not in cache:
                        record=self._delivery(source['vendor'],source['library'],source['version'],source['delivery_id'])['record']
                        cache[key]=parse_delivery_file(record,source['file_id'])
                    item[side+'_facts']=cache[key]
                item['status']='PARSED'
            except (OSError,ValueError,KeyError) as exc:
                item.update(status='NOT_CHECKED',reason=str(exc),before_facts=None,after_facts=None)
            out.append(item)
        return {'from':rev_a,'to':rev_b,'pairs':out,'meaning':'SELECTED_FILE_FACTS_ONLY'}

    def check_changed_lefs(self,vendor,library,set_id,rev_a,rev_b,*,run_id,ruleset_id,run_at,pin_liberty_path=None):
        """Build one existing CheckResult only from fully resolved changed LEFs."""
        from ai_lib_qor.checks.assembler import build_check_result
        parsed=self.parse_changed_file_pairs(vendor,library,set_id,rev_a,rev_b,views=['LEF'])
        if not parsed['pairs'] or any(x['status']!='PARSED' for x in parsed['pairs']):
            return {'status':'NOT_CHECKED','pairs':parsed['pairs'],'result':None}
        comparisons=[];old_members={};new_members={};facts=[]
        for pair in parsed['pairs']:
            old_key=pair['before']['file_key'];new_key=pair['after']['file_key']
            if not old_key or old_key!=new_key or old_key in old_members:
                return {'status':'NOT_CHECKED','pairs':parsed['pairs'],'result':None,
                        'reason':'旧检查文件位不一致或不唯一'}
            old=pair['before_facts'];new=pair['after_facts']
            old_members[old_key]=old['source_ref'];new_members[old_key]=new['source_ref']
            comparisons.append({'file_key':old_key,'old':old,'new':new});facts.extend((old,new))
        pin_pairs=[];plugins=['LEF_MACRO_DIFF']
        if pin_liberty_path is not None:
            from .effective_json import _flat_views
            from ai_lib_qor.facts.parsers import parse_delivery_file
            effective=_flat_views(self._simple_revision(vendor,library,set_id,rev_b))
            source=effective.get(('LIBERTY',pin_liberty_path))
            if source is None or len(parsed['pairs'])!=1:
                raise ValueError('接口检查需要明确选择有效 Liberty 和唯一的变化 LEF')
            location=self._source_location(source,'LIBERTY',pin_liberty_path)
            if (location['resolution']!='RECORDED' or location.get('identity_status')!='CONFIRMED'
                or location.get('classification')!='RESOLVED' or not location.get('file_key')
                or len(self._refs[(location['library'],location['delivery_id'],location['file_id'])])!=1):
                raise ValueError('Liberty 来源缺失、歧义或身份未确认')
            record=self._delivery(location['vendor'],location['library'],location['version'],location['delivery_id'])['record']
            lib=parse_delivery_file(record,location['file_id']);lef=parsed['pairs'][0]['after_facts']
            lk=parsed['pairs'][0]['after']['file_key'];bk=location['file_key']
            if bk in new_members:raise ValueError('Liberty 文件位与 LEF 冲突')
            new_members[bk]=lib['source_ref'];facts.append(lib)
            pin_pairs=[{'lef_key':lk,'liberty_key':bk,'lef':lef,'liberty':lib}]
            plugins.append('LEF_LIBERTY_PIN_MATCH')
        result=build_check_result(target={'kind':'EFFECTIVE_REVISION','id':rev_b},
            baseline={'kind':'EFFECTIVE_REVISION','id':rev_a},effective_set_id=set_id,
            run_id=run_id,ruleset_id=ruleset_id,run_at=run_at,comparisons=comparisons,pin_pairs=pin_pairs,
            target_members=new_members,baseline_members=old_members,plugin_ids=plugins)
        result['evidence_note']=('比较来源变化的 LEF 文件的 Macro SIZE 和 Pin；' +
            ('检查指定有效 LEF 与 Liberty 的信号 Pin 对齐；' if pin_pairs else '未检查 LEF–Liberty 对齐；') +
            '未检查全部文件或完整 IP。来源变化不等于内容变化。')
        return {'status':'CHECKED','result':result,'facts':facts,'pairs':parsed['pairs']}

    def compare_formal_vs_effective(self,vendor,library,nl,snapshot,set_id,revision):
        from .effective_json import _flat_views
        effective=_flat_views(self._simple_revision(vendor,library,set_id,revision))
        formal=self.get_formal_files(vendor,library,nl,snapshot);rows=[]
        for view,group in formal['views'].items():
            for formal_path,item in group.items():
                raw=item.get('raw_source');selected=effective.get((view,raw['path'])) if raw else None
                # Compare only archived path text: an indirect symlink can legitimately
                # differ, so a mismatch is inconclusive rather than proof of tampering.
                path_status='UNAVAILABLE';expected=None
                if raw and item.get('resolved_path'):
                    registered=self._delivery(raw['vendor'],raw['library'],raw['version'],raw['delivery_id'])['record']
                    if posixpath.isabs(registered['source_root']) and posixpath.isabs(item['resolved_path']):
                        expected=posixpath.normpath(posixpath.join(registered['source_root'],raw['path']))
                        path_status='MATCH' if expected==posixpath.normpath(item['resolved_path']) else 'MISMATCH_OR_INDIRECT'
                relation='UNKNOWN'
                if raw and path_status=='MATCH' and not selected:relation='NOT_IN_EFFECTIVE'
                elif raw and selected and path_status=='MATCH':
                    location=self._source_location(selected,view,raw['path'])
                    if (raw['vendor'],raw['library'],raw['version'])!=(selected['vendor'],selected['library'],selected['version']):relation='DIFFERENT_SOURCE'
                    elif location['resolution']=='RECORDED':relation='SAME_SOURCE' if raw['delivery_id']==location['delivery_id'] else 'DIFFERENT_SOURCE'
                rows.append({'view':view,'formal_path':formal_path,'link_target':item.get('link_target'),
                             'link_target_status':item.get('link_target_status'),'raw_source':raw,
                             'effective_source':selected,'relation':relation,'content_status':'NOT_CHECKED',
                             'resolved_path':item.get('resolved_path'),'archived_raw_path':expected,
                             'archived_path_status':path_status,'verification_scope':'ARCHIVED_RECORDS_ONLY'})
        return {'nl':nl,'snapshot':snapshot,'revision':revision,'coverage':formal['context']['coverage'],
                'unassigned':formal['unassigned'],'meaning':'SOURCE_ONLY','files':rows}

    def get_file_history(self,vendor,library,view,path):
        occurrences=[]
        for item,f in self._history.get((vendor,library,view.upper(),path),[]):
            d=item['record']
            occurrences.append({'delivery_id':d['delivery_id'],'version':d['supplier_version'],
                'file_id':f['file_id'],'file_key':f['file_key'],'identity_status':f['identity_status'],
                'delivery_order':d['delivery_order'],'order_basis':item['order_basis'],'ordering_status':item['ordering_status']})
        listing=self.list_deliveries(vendor,library)
        confirmed=bool(occurrences) and listing['ordering_status']=='CONFIRMED'
        basis=listing['order_basis'] if confirmed else None;warning=None
        index,index_status=self._verified_file_index(vendor,library)
        if confirmed:
            indexed=index['views'].get(view.upper(),{}).get(path,{}).get('timeline',[]) if index else []
            rank={item['delivery_id']:i for i,item in enumerate(reversed(indexed))} if indexed else {item['delivery_id']:i for i,item in enumerate(listing['deliveries'])}
            occurrences.sort(key=lambda x:rank[x['delivery_id']])
        return {'view':view.upper(),'path':path,'occurrences':occurrences,'ordering_status':'CONFIRMED' if confirmed else 'ORDER_UNCONFIRMED',
                'order_basis':basis,'ordering_warning':warning,'index_status':index_status,'latest':occurrences[-1] if confirmed else None,'previous':occurrences[-2] if confirmed and len(occurrences)>1 else None}

    def _verified_file_index(self,vendor,library):
        """Validate an optional derived index against archived records, never write it."""
        from .file_index import repository_index_state
        from ai_lib_qor.sources.layout import library_folder
        key=(vendor,library)
        if self._archive_snapshot!=archive_fingerprint(self.work):return (None,'STALE')
        if key in self._file_index_cache:return self._file_index_cache[key]
        path=library_folder(self.work,vendor,library)/'file_index.json'
        if path.is_symlink() or not path.is_file():
            self._file_index_cache[key]=(None,'MISSING');return self._file_index_cache[key]
        items=[x for x in self.deliveries if (x['record']['vendor_id'],x['record']['source_library_id'])==(vendor,library)]
        try:
            st=path.stat();fingerprint=(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
            saved=json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(saved,dict):raise ValueError('索引格式无效')
            if self.list_deliveries(vendor,library)['ordering_status']!='CONFIRMED':
                result=(None,'ORDER_UNCONFIRMED')
            elif saved.get('schema')=='file_index.v3':
                from .file_index_v3 import build_library_index,raw_compat,preserves_history
                expected=build_library_index(self.work,vendor,library,query=self)
                after=path.stat()
                if fingerprint!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise ValueError('索引核验中发生变化')
                if saved==expected:
                    self._published_index_cache[key]=(saved,fingerprint);result=(raw_compat(saved),'VALID')
                elif preserves_history(saved,expected):result=(None,'STALE')
                else:result=(None,'INVALID')
            else:
                index,action,_=repository_index_state(items,self._source_configs.get((vendor,library),{}),saved)
                result=(index,'VALID') if action=='UNCHANGED' else (None,'STALE')
        except (OSError,ValueError,KeyError,TypeError):result=(None,'INVALID')
        self._file_index_cache[key]=result
        return result

    def get_file_at_delivery(self,vendor,library,view,path,delivery_id):
        """Select the last appearance at or before an explicitly identified Delivery."""
        from .file_index import _path
        _path(path)
        listing=self.list_deliveries(vendor,library)
        if listing['ordering_status']!='CONFIRMED':raise ValueError('交付顺序未确认，无法按时间点选择文件')
        ids=[x['delivery_id'] for x in listing['deliveries']]
        if delivery_id not in ids:raise ValueError('所选交付不存在')
        index,status=self._verified_file_index(vendor,library)
        if index is not None:
            timeline=index['views'].get(view.upper(),{}).get(path,{}).get('timeline',[])
            by_id={x['delivery_id']:x for x in timeline}
        else:
            by_id={x['delivery_id']:x for x in self.get_file_history(vendor,library,view,path)['occurrences']}
        chosen=next((by_id[i] for i in reversed(ids[:ids.index(delivery_id)+1]) if i in by_id),None)
        source=next((x for x in listing['deliveries'] if chosen and x['delivery_id']==chosen['delivery_id']),None)
        if chosen and source:chosen={**chosen,'version':source['version']}
        identity='UNKNOWN'
        if chosen:
            identities=[f['identity_status'] for item,f in self._history.get((vendor,library,view.upper(),path),[])
                        if item['record']['delivery_id']==chosen['delivery_id'] and f['file_id']==chosen.get('file_id')]
            if len(identities)==1:identity=identities[0]
        return {'vendor':vendor,'library':library,'view':view.upper(),'path':path,'at_delivery_id':delivery_id,
                'occurrence':chosen,'source_root':source['root'] if source else None,
                'delivery_record_path':self._delivery(vendor,library,source['version'],source['delivery_id'])['path'] if source else None,
                'absolute_path':posixpath.join(source['root'],path) if source else None,
                'identity_status':identity,'index_status':status,'meaning':'LAST_RECORDED_APPEARANCE_NOT_EFFECTIVE_OR_CONTENT'}

    def get_history_index(self,vendor,library):
        result={}
        for v,l,kind,path in self._history:
            if (v,l)==(vendor,library):result.setdefault(kind,{})[path]=self.get_file_history(v,l,kind,path)
        return {'context':{'vendor':vendor,'library':library},'index_status':self.file_index_status(vendor,library)['status'],'views':result}

    def file_index_status(self,vendor,library):
        _,status=self._verified_file_index(vendor,library)
        return {'vendor':vendor,'library':library,'status':status,
                'message':{'VALID':'索引与已归档交付一致','MISSING':'尚未建立索引，查询使用归档交付',
                           'STALE':'索引未包含最新归档或需要迁移；查询使用归档交付',
                           'ORDER_UNCONFIRMED':'交付顺序未确认，不能使用有序索引；查询使用归档交付',
                           'INVALID':'索引与归档记录不一致，查询使用归档交付；请核验后重建'}[status]}

    def get_logical_file_timeline(self,vendor,library,view,file_key):
        """Combine only explicitly confirmed file identities, including path changes."""
        if not isinstance(file_key,str) or not file_key.strip():raise ValueError('必须指定非空文件身份')
        rows=[];unconfirmed=0
        for (v,l,kind,path),items in self._history.items():
            if (v,l,kind)!=(vendor,library,view.upper()):continue
            for item,f in items:
                if f.get('file_key')!=file_key:continue
                if f.get('identity_status')!='CONFIRMED' or f.get('classification')!='RESOLVED':
                    unconfirmed+=1;continue
                d=item['record']
                rows.append({'delivery_id':d['delivery_id'],'version':d['supplier_version'],
                             'path':path,'file_id':f['file_id'],'file_key':file_key,
                             'identity_status':'CONFIRMED','root':d['source_root']})
        ids=[x['delivery_id'] for x in rows]
        if len(set(ids))!=len(ids):raise ValueError('同一交付中存在多个已确认的相同文件身份，无法唯一合并')
        listing=self.list_deliveries(vendor,library)
        if listing['ordering_status']=='CONFIRMED':
            rank={x['delivery_id']:i for i,x in enumerate(listing['deliveries'])}
            rows.sort(key=lambda x:rank[x['delivery_id']])
        return {'vendor':vendor,'library':library,'view':view.upper(),'file_key':file_key,
                'occurrences':rows,'unconfirmed_count':unconfirmed,'ordering_status':listing['ordering_status'],
                'order_basis':listing['order_basis'],'meaning':'CONFIRMED_IDENTITY_NOT_CONTENT_CHANGE'}

    def _revision(self,vendor,library,owner,revision):
        matches=[r for e in self.entries if (e['vendor'],e['library'],e['ip'])==(vendor,library,owner) for r in e['versions'] if r['revision_id']==revision]
        if len(matches)!=1:raise ValueError('有效版本不存在或不唯一')
        return matches[0]

    def get_effective_files(self,vendor,library,owner,revision,view=None):
        from ai_lib_qor.sources.layout import SAFE,library_folder
        import re
        m=re.fullmatch(r'rev_(\d{4,})',revision or '')
        if isinstance(owner,str) and SAFE.fullmatch(owner) and m:
            candidate=library_folder(self.work,vendor,library)/f'effective_{owner}_{int(m.group(1)):03d}.json'
            if candidate.is_file() and not candidate.is_symlink():
                value=json.loads(candidate.read_text(encoding='utf-8'))
                if isinstance(value,dict) and value.get('schema')=='effective.simple.v2':
                    result=get_effective_v2_files(self.work,vendor,library,owner,revision,view,deliveries=self.deliveries)
                    views={};unresolved=[]
                    for row in result['files']:
                        views.setdefault(row['view'],{})[row['path']]=row
                        if row['resolution']!='RECORDED':unresolved.append(row)
                    return {'schema':'effective_view.v2','context':{'vendor':vendor,'library':library,
                            'owner':result['owner']['id'],'revision':revision,'effective_set_id':owner},
                            'views':views,'unresolved':unresolved}
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


def parse_recorded_file(work,runs,vendor,library,delivery_id,view,path):
    """Parse an exact archived v1 Delivery row; do not invent identities."""
    from .file_index import _path
    from ai_lib_qor.facts.parsers import parse_delivery_file
    _path(path);q=LibraryDataQuery(work,runs)
    matches=[x for x in q.deliveries if (x['record']['vendor_id'],x['record']['source_library_id'],x['record']['delivery_id'])==(vendor,library,delivery_id)]
    if len(matches)!=1:raise ValueError('交付不存在或不唯一')
    item=matches[0];rows=[f for f in item['files'] if f['relative_path']==path and _view(f['view'],path)==view.upper()]
    if len(rows)!=1 or not rows[0].get('file_id') or rows[0]['classification']!='RESOLVED':
        raise ValueError('交付文件不存在、身份不唯一或分类未解决')
    ref=(library,delivery_id,rows[0]['file_id'])
    if len(q._refs[ref])!=1:raise ValueError('旧 FileFacts 引用跨供应商不唯一')
    return parse_delivery_file(item['record'],rows[0]['file_id'])


def query_data(work,runs,kind,**options):
    if not Path(work).is_dir():raise ValueError('work 目录不存在')
    required={'raw':('vendor','library','version'),'simple-raw':('vendor','library','version'),'history':('vendor','library','view','path'),'history-index':('vendor','library'),
              'history-at':('vendor','library','view','path','delivery_id'),'index-status':('vendor','library'),'index-v3':('vendor','library'),
              'logical-history':('vendor','library','view','file_key'),
              'effective':('vendor','library','owner','revision'),'effective-v2':('vendor','library','set_id','revision'),'simple-effective':('vendor','library','owner','revision'),'formal':('vendor','library','version','snapshot'),
              'simple-formal':('vendor','library','version','snapshot'),'compare':('vendor','library','owner','revision','other_revision'),
              'deliveries':('vendor','library'),'compare-revisions':('vendor','library','set_id','revision','other_revision'),
              'compare-revisions-logical':('vendor','library','set_id','revision','other_revision'),
              'changed-pairs':('vendor','library','set_id','revision','other_revision'),
              'check-context':('vendor','library','set_id','revision'),
              'formal-effective':('vendor','library','set_id','revision','version','snapshot'),
              'effective-timeline':('vendor','library','set_id','view','path','revisions')}
    if kind not in required:raise ValueError('不支持的查询类型')
    missing=[k for k in required[kind] if not options.get(k)]
    if missing:raise ValueError('缺少查询参数：'+', '.join(missing))
    if kind=='effective-v2':
        return get_effective_v2_files(work,options['vendor'],options['library'],options['set_id'],options['revision'],options.get('view'))
    q=LibraryDataQuery(work,runs);v=options.get('vendor');l=options.get('library');view=options.get('view')
    if kind=='check-context':return q.get_check_context(v,l,options['set_id'],options['revision'],baseline=options.get('other_revision'),selected_views=[view] if view else None)
    if kind=='index-v3':
        status=q.file_index_status(v,l)['status']
        return {'index_status':status,'index':q.published_v3_index(v,l) if status=='VALID' else None}
    if kind=='deliveries':return q.list_deliveries(v,l)
    if kind=='compare-revisions':return q.compare_revisions(v,l,options['set_id'],options['revision'],options['other_revision'])
    if kind=='compare-revisions-logical':return q.compare_revisions_logical(v,l,options['set_id'],options['revision'],options['other_revision'])
    if kind=='changed-pairs':return q.get_changed_file_pairs(v,l,options['set_id'],options['revision'],options['other_revision'])
    if kind=='formal-effective':return q.compare_formal_vs_effective(v,l,options['version'],options['snapshot'],options['set_id'],options['revision'])
    if kind=='effective-timeline':return q.file_timeline(v,l,options['set_id'],view,options['path'],options['revisions'])
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
    if kind=='history-at':return q.get_file_at_delivery(v,l,view,options['path'],options['delivery_id'])
    if kind=='index-status':return q.file_index_status(v,l)
    if kind=='logical-history':return q.get_logical_file_timeline(v,l,view,options['file_key'])
    if kind=='history-index':return q.get_history_index(v,l)
    if kind=='effective':return q.get_effective_files(v,l,options['owner'],options['revision'],view)
    if kind=='formal':return q.get_formal_files(v,l,options['version'],options['snapshot'],view)
    return q.compare_effective(v,l,options['owner'],options['revision'],options['other_revision'])


def get_effective_v2_files(work,vendor,library,set_id,revision,view=None,*,deliveries=None):
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
    deliveries=SourceRepository(work).deliveries() if deliveries is None else deliveries;files=[]
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
