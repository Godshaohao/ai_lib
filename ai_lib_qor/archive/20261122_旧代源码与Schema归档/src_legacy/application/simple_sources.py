"""Non-authoritative simplified exports from existing records, with pure path-based calculation."""
from pathlib import Path, PurePosixPath
import re
import posixpath
from datetime import datetime


def version_date_order(records):
    """Validate all YYYYMMDD_* labels and reject same-day ambiguity."""
    rows=[]
    for record in records:
        version=record['context']['version']
        match=re.fullmatch(r'(20\d{6})(?:[_-].+)?',version)
        if not match:raise ValueError('版本名称不符合已确认的日期前缀规则')
        try:date=datetime.strptime(match.group(1),'%Y%m%d').date()
        except ValueError:raise ValueError('版本日期无效') from None
        rows.append((date,record['delivery_id']))
    if len({x[0] for x in rows})!=len(rows):raise ValueError('多个交付日期相同，不能判断先后')
    return [ident for _,ident in sorted(rows)]


def _alias(query, vendor, library, delivery_id):
    matches=[x for x in query.deliveries if (x['record']['vendor_id'],x['record']['source_library_id'],x['record']['delivery_id'])==(vendor,library,delivery_id)]
    if len(matches)!=1:raise ValueError('来源交付不存在或不唯一')
    path=Path(matches[0]['path']);name=path.stem
    expected=Path(query.work).resolve()/'libraries'/vendor/library
    # Only the flat library filename is a locally unique numbered delivery alias.
    return name if path.parent==expected and re.fullmatch(r'delivery_\d+',name) else delivery_id


def simple_raw(query,vendor,library,version,delivery_id=None):
    projection=query.get_raw_files(vendor,library,version,delivery_id=delivery_id)
    ctx=dict(projection['context']);original=ctx.pop('delivery_id')
    return {'schema':'raw.simple.v1','delivery_id':_alias(query,vendor,library,original),
            'context':ctx,'views':projection['views']}


def simple_formal(query,vendor,library,nl,snapshot_id):
    result=query.get_formal_files(vendor,library,nl,snapshot_id);ctx=dict(result['context'])
    ctx.pop('coverage');ctx.pop('snapshot_id',None);views={}
    records=[x for x in query.repo.formal() if (x['record']['formal_nl_id'],x['record']['formal_snapshot_id'])==(nl,snapshot_id)]
    name=Path(records[0]['path']).stem if len(records)==1 else ''
    simple_id=name if re.fullmatch('formal_'+re.escape(nl)+r'_\d+',name) else snapshot_id
    for kind,group in result['views'].items():
        for path,row in group.items():
            source=row.get('raw_source');entry={}
            if source:
                entry={'raw_version':source['version'],'raw_path':source['path']}
                if source['vendor']!=vendor:entry['vendor']=source['vendor']
                if source['library']!=library:entry['library']=source['library']
                candidates=[x for x in query.deliveries if (x['record']['vendor_id'],x['record']['source_library_id'],x['record']['supplier_version'])==(source['vendor'],source['library'],source['version'])]
                if len(candidates)!=1:entry['delivery']=_alias(query,source['vendor'],source['library'],source['delivery_id'])
                if row['path_match_basis']!='CONTRACT_REFERENCE':entry['match_basis']=row['path_match_basis'] or 'UNKNOWN'
            else:
                entry={'raw_version':None,'raw_path':None,'resolved_path':row.get('resolved_path'),'match_basis':'UNKNOWN'}
            target=row.get('link_target');entry['link_target']=target
            if target is None:
                entry['link_target_status']='NOT_RECORDED'
            else:
                direct=posixpath.normpath(target if posixpath.isabs(target) else posixpath.join(posixpath.dirname(posixpath.join(ctx['root'],path)),target))
                if row.get('resolved_path') and direct!=posixpath.normpath(row['resolved_path']):
                    entry['resolved_path']=row['resolved_path']
            views.setdefault(kind,{})[path]=entry
    output={'schema':'formal.simple.v3','snapshot_id':simple_id,'context':ctx,'views':views}
    if result['unassigned']:output['unassigned']=result['unassigned']
    from ai_lib_qor.versions.store import validate
    validate(output,'formal_simple_v3')
    return output


def simple_effective(query, vendor, library, owner, revision):
    """Export an existing revision; never infer additional effective members."""
    from .data_query import _subgroup
    record = query._revision(vendor, library, owner, revision)
    projection = query.get_effective_files(vendor, library, owner, revision)
    if projection['unresolved']:
        raise ValueError('有效成员来源无法解析，不能导出简化版本')
    sources, views = {}, {}
    for kind, rows in projection['views'].items():
        for source in rows.values():
            raw = source.get('raw_source') if 'formal_ref' in source else source
            if not raw:
                raise ValueError('正式基准的 RAW 来源无法解析，不能导出简化版本')
            from urllib.parse import quote
            cross = (raw['vendor'], raw['library']) != (vendor, library)
            version = raw['version']
            if version.startswith('@'):raise ValueError('RAW 版本名称不能使用保留的跨库键前缀')
            candidates = [item for item in query.deliveries if
                          (item['record']['vendor_id'], item['record']['source_library_id'],
                           item['record']['supplier_version']) == (raw['vendor'], raw['library'], version)]
            if len(candidates) != 1:
                raise ValueError('RAW 版本对应交付不唯一，不能导出')
            alias = _alias(query, raw['vendor'], raw['library'], raw['delivery_id'])
            source_key = '@'+'/'.join(quote(s,safe='') for s in (raw['vendor'],raw['library'],version)) if cross else version
            source_value = {'vendor':raw['vendor'],'library':raw['library'],'version':version,'delivery':alias} if cross else alias
            if source_key in sources and sources[source_key] != source_value:
                raise ValueError('RAW 版本对应交付不唯一，不能导出')
            sources[source_key] = source_value
            path = raw['path']; actual_kind = raw['view']
            bucket = views.setdefault(actual_kind, {})
            subgroup = _subgroup(actual_kind, path)
            if subgroup:
                bucket = bucket.setdefault(subgroup, {})
            if path in bucket:
                raise ValueError('多个有效成员使用相同 View 和路径，不能导出')
            bucket[path] = source_key
    output = {'schema':'effective.simple.v2',
              'owner':{'type':record['owner']['owner_type'], 'id':record['owner']['owner_id']},
              'scope':{'vendor':vendor,'library':library},
              'revision':record['revision_id'], 'parent':record['parent_revision_id'],
              'created_at':record['created_at'], 'sources':sources, 'views':views}
    if record.get('reason', {}).get('kind') == 'FORMAL_BASELINE':
        output['formal_baseline'] = record['reason']['ref_id']
    from ai_lib_qor.versions.store import validate
    validate(output, 'effective_simple_v2')
    return output


def _paths(node):
    if isinstance(node,list):
        for path in node:
            if (not isinstance(path,str) or not path or '\\' in path or PurePosixPath(path).is_absolute()
                    or any(part in ('','.','..') for part in path.split('/'))):
                raise ValueError('文件路径无效')
            yield path
    elif isinstance(node,dict):
        for value in node.values():yield from _paths(value)
    else:raise ValueError('View 必须是路径数组或子分类字典')


def build_effective(raw_records, ordered_delivery_ids, *, include_views):
    """Use explicitly selected views and delivery order; absence never means deletion."""
    if not isinstance(include_views,(list,tuple,set,frozenset)) or not include_views or not all(isinstance(v,str) and v for v in include_views):
        raise ValueError('必须明确选择参与计算的 View 范围')
    selected_views=set(include_views)
    records={}
    for record in raw_records:
        if record.get('schema')!='raw.simple.v1':raise ValueError('RAW 格式不支持')
        ident=record['delivery_id']
        if ident in records:raise ValueError('交付 ID 不唯一，需要明确库范围')
        records[ident]=record
    if len(set(ordered_delivery_ids))!=len(ordered_delivery_ids) or set(ordered_delivery_ids)!=set(records):
        raise ValueError('交付顺序必须明确且恰好覆盖提供的记录')
    views={}
    for ident in ordered_delivery_ids:
        record=records[ident];context=record['context'];vendor=context['vendor'];library=context['library'];seen=set()
        for kind,values in record['views'].items():
            if kind not in selected_views:continue
            for path in _paths(values):
                if (kind,path) in seen:raise ValueError('单次交付路径重复')
                seen.add((kind,path));bucket=views.setdefault(kind,{})
                old=bucket.get(path)
                if old and (old['vendor'],old['library'])!=(vendor,library):raise ValueError('跨库同名路径冲突，需要明确映射')
                bucket[path]={'vendor':vendor,'library':library,'delivery':ident}
    return {'schema':'effective.simple.v1','ordering':'EXPLICIT_INPUT_ORDER','included_views':sorted(selected_views),'views':views}


def compare_formal(effective,formal,raw_records=None):
    if effective.get('schema')!='effective.simple.v1' or formal.get('schema') not in ('formal.simple.v1','formal.simple.v2','formal.simple.v3'):
        raise ValueError('输入格式不支持')
    views={}
    for kind,group in formal['views'].items():
        for path,item in group.items():
            source=item.get('raw_source');relation='UNKNOWN'
            if formal['schema'] in ('formal.simple.v2','formal.simple.v3') and item.get('raw_version') and item.get('raw_path'):
                ctx=formal['context'];v=item.get('vendor',ctx['vendor']);l=item.get('library',ctx['library'])
                matching=[r for r in (raw_records or []) if (r['context']['vendor'],r['context']['library'],r['context']['version'])==(v,l,item['raw_version']) and (not item.get('delivery') or r['delivery_id']==item['delivery'])]
                source=({'vendor':v,'library':l,'delivery':matching[0]['delivery_id'],'path':item['raw_path']}
                        if len(matching)==1 and item['raw_path'] in set(_paths(matching[0]['views'].get(kind,[]))) else None)
            if source:
                selected=effective['views'].get(kind,{}).get(source['path'])
                if not selected:relation='NOT_IN_EFFECTIVE'
                elif (selected['vendor'],selected['library'],selected['delivery'])==(source['vendor'],source['library'],source['delivery']):relation='SAME_SOURCE'
                else:relation='DIFFERENT_SOURCE'
            views.setdefault(kind,{})[path]={'relation':relation,'match_basis':item.get('match_basis')}
    return {'meaning':'RECORDED_SOURCE_ONLY','formal_coverage':formal.get('coverage','UNDECLARED'),'views':views}


def build_history(raw_records, ordered_delivery_ids=None, *, order_rule=None):
    records={}
    for record in raw_records:
        if record.get('schema')!='raw.simple.v1':raise ValueError('RAW 格式不支持')
        if record['delivery_id'] in records:raise ValueError('交付 ID 不唯一')
        records[record['delivery_id']]=record
    scopes={(r['context']['vendor'],r['context']['library']) for r in raw_records}
    if len(scopes)>1:raise ValueError('文件历史必须限定到单个供应商和库')
    basis='EXPLICIT_INPUT_ORDER'
    if order_rule is not None:
        if ordered_delivery_ids is not None:raise ValueError('不能同时提供交付顺序和排序规则')
        if order_rule!={'type':'VERSION_DATE_PREFIX','confirmed':True}:
            raise ValueError('版本日期规则未确认或不支持')
        ordered_delivery_ids=version_date_order(raw_records)
        basis='CONFIRMED_VERSION_DATE_PREFIX'
    if ordered_delivery_ids is not None:
        if len(set(ordered_delivery_ids))!=len(ordered_delivery_ids) or set(ordered_delivery_ids)!=set(records):
            raise ValueError('交付顺序必须明确且恰好覆盖提供的记录')
        sequence=ordered_delivery_ids
    else:sequence=list(records)
    views={}
    for ident in sequence:
        record=records[ident];seen=set()
        for kind,values in record['views'].items():
            for path in _paths(values):
                if (kind,path) in seen:raise ValueError('单次交付路径重复')
                seen.add((kind,path))
                views.setdefault(kind,{}).setdefault(path,[]).append({'delivery':ident,'version':record['context']['version']})
    confirmed=ordered_delivery_ids is not None
    for paths in views.values():
        for path,items in paths.items():
            paths[path]={'occurrences':items,'ordering_status':basis if confirmed else 'ORDER_UNCONFIRMED',
                         'latest':items[-1] if confirmed else None,'previous':items[-2] if confirmed and len(items)>1 else None}
    return {'schema':'history.simple.v1','views':views}
