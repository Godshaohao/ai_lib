"""Read-only projections: effective members are not delivery observations."""


def _resolve(ref, key, deliveries, snapshots, home_library):
    if ref is None: return None
    matches=[]
    if ref['kind']=='delivery_file':
        for d in deliveries:
            if (d['source_library_id'],d['delivery_id']) == (ref['source_library_id'],ref['delivery_id']):
                for f in d['files']:
                    if f['file_id']==ref['file_id'] and f.get('file_key')==key:
                        matches.append({'version':d['supplier_version'],'path':f['relative_path'],'view':f['view'],'corner':f.get('corner'),'mode':f.get('mode')})
        label=f"{ref['source_library_id']} / {ref['delivery_id']} / {ref['file_id']}"
        missing='OUT_OF_SCOPE' if home_library and ref['source_library_id'] != home_library else 'MISSING'
    else:
        for s in snapshots:
            if (s['formal_nl_id'],s['formal_snapshot_id']) == (ref['formal_nl_id'],ref['formal_snapshot_id']):
                for f in s['linked_files']:
                    if f['file_id']==ref['file_id'] and f.get('file_key')==key:
                        details={'version':s['formal_nl_id'],'path':f['link_path'],'view':'未知','corner':None,'mode':None}
                        if f.get('source_ref'):
                            origin=_resolve(f['source_ref'],key,deliveries,[],home_library)
                            if origin and origin['state']=='RESOLVED':
                                for field in ('view','corner','mode'): details[field]=origin[field]
                        matches.append(details)
        label=f"{ref['formal_nl_id']} / {ref['formal_snapshot_id']} / {ref['file_id']}";missing='MISSING'
    state='RESOLVED' if len(matches)==1 else 'AMBIGUOUS' if len(matches)>1 else missing
    data=matches[0] if len(matches)==1 else {'version':None,'path':None,'view':'未知','corner':None,'mode':None}
    return {**data,'state':state,'label':label,'ref':ref}


def build_file_matrix(target_revision, baseline_revision, deliveries, snapshots, compatible_run=None, *, home_library=None, formal_snapshot=None):
    if not target_revision:return {'rows':[],'baseline_known':False,'changes':None,'objects':[],'run':None}
    target={x['file_key']:x['source_ref'] for x in target_revision['members']}
    base={x['file_key']:x['source_ref'] for x in baseline_revision['members']} if baseline_revision else {}
    changes={x['file_key']:x for x in compatible_run['file_changes']} if compatible_run else {}
    rows=[];objects=[]
    for key in sorted(target.keys() | base.keys()):
        a,b=base.get(key),target.get(key)
        relation=('UNKNOWN' if baseline_revision is None else 'ADDED' if a is None else 'REMOVED' if b is None else 'UNCHANGED' if a==b else 'REPLACED')
        current=_resolve(b,key,deliveries,snapshots,home_library);previous=_resolve(a,key,deliveries,snapshots,home_library)
        source=current or previous;fact=changes.get(key)
        # A result only describes this exact file pair; mismatch is not evidence.
        if fact and (fact['old_source_ref']!=a or fact['new_source_ref']!=b):fact=None
        check_items=[q for q in compatible_run['quality_checks'] if key in q['scope_file_keys']] if compatible_run else []
        if fact:
            for item in fact['object_changes']:objects.append({'file_key':key,**item})
        formal='未对照'
        if formal_snapshot:
            files=[f for f in formal_snapshot['linked_files'] if f.get('file_key')==key]
            if not files: formal='快照未列出'
            elif len(files)>1:formal='文件位不唯一'
            else:
                direct={'kind':'formal_file','formal_nl_id':formal_snapshot['formal_nl_id'],'formal_snapshot_id':formal_snapshot['formal_snapshot_id'],'file_id':files[0]['file_id']}
                if b==direct or (b and files[0].get('source_ref') and b==files[0]['source_ref']):formal='来源一致'
                elif b and b.get('kind')=='delivery_file' and files[0].get('source_ref'):formal='来源不同'
                else:formal='来源未知'
        rows.append({'file_key':key,'target':current,'baseline':previous,'view':source['view'] if source else '未知','corner':source['corner'] if source else None,'mode':source['mode'] if source else None,'source_relation':relation,'content_status':fact['content_status'] if fact else 'NOT_CHECKED','checks':check_items,'formal_relation':formal})
    counts={x:sum(r['source_relation']==x for r in rows) for x in ('ADDED','REPLACED','REMOVED','UNCHANGED')} if baseline_revision else None
    return {'rows':rows,'baseline_known':baseline_revision is not None,'changes':counts,'objects':objects,'run':compatible_run}


def result_matches(result, target, baseline):
    """Identity and recorded sources must match; this does not prove freshness."""
    if result.get('target') != {'kind':'EFFECTIVE_REVISION','id':target['revision_id']}:return False
    expected={'kind':'EFFECTIVE_REVISION','id':baseline['revision_id']} if baseline else None
    if result.get('baseline') != expected or result.get('effective_set_id') != target['effective_set_id']:return False
    new={m['file_key']:m['source_ref'] for m in target['members']};old={m['file_key']:m['source_ref'] for m in baseline['members']} if baseline else {}
    return all(x['file_key'] in (new.keys()|old.keys()) and x['old_source_ref']==old.get(x['file_key']) and x['new_source_ref']==new.get(x['file_key']) for x in result['file_changes'])
