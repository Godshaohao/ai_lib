"""Explicit JSON-only effective-set calculation (independent of v1 version store)."""
from copy import deepcopy
import re
from urllib.parse import quote

from .simple_sources import _paths


def _view_items(node):
    if isinstance(node, list):
        for path in _paths(node):
            yield (), path
    elif isinstance(node, dict):
        for name, child in node.items():
            if not isinstance(name, str) or not name:
                raise ValueError('View 子分类无效')
            for sub, path in _view_items(child):
                yield (name,) + sub, path
    else:
        raise ValueError('View 必须为路径数组或子分类字典')


def create_revision(raw, *, owner, revision, created_at, include_views, parent=None, formal_baseline=None, allow_cross_library=False):
    """Calculate an isolated single-library revision; caller explicitly selects views."""
    if raw.get('schema') != 'raw.simple.v1': raise ValueError('不支持的 RAW 格式')
    if not isinstance(owner,dict) or set(owner)!={'type','id'} or owner['type'] not in ('SOURCE_LIBRARY','BUSINESS_IP') or not isinstance(owner['id'],str) or not owner['id']:
        raise ValueError('所有者无效')
    if not re.fullmatch(r'rev_\d{4,}',revision or '') or not isinstance(created_at,str) or not created_at:
        raise ValueError('版本或时间无效')
    if not isinstance(include_views,(list,tuple,set)) or not include_views or not all(isinstance(x,str) and x for x in include_views):
        raise ValueError('必须显式选择 View')
    ctx=raw.get('context',{});vendor=ctx.get('vendor');library=ctx.get('library');version=ctx.get('version');delivery=raw.get('delivery_id')
    if not all(isinstance(x,str) and x for x in (vendor,library,version,delivery)):
        raise ValueError('RAW 来源上下文不完整')
    if version.startswith('@'):raise ValueError('RAW 版本名称不能使用保留的跨库键前缀')
    if parent:
        from ai_lib_qor.versions.store import validate
        validate(parent,'effective_simple_v2')
        if parent.get('schema')!='effective.simple.v2' or parent.get('owner')!=owner or (parent.get('scope')!={'vendor':vendor,'library':library} and not allow_cross_library):
            raise ValueError('父版本来源范围或所有者不一致')
        if not re.fullmatch(r'rev_\d{4,}',parent.get('revision','')) or int(revision[4:])!=int(parent['revision'][4:])+1:
            raise ValueError('版本必须紧随父版本')
        if not isinstance(parent.get('sources'),dict) or not isinstance(parent.get('views'),dict):
            raise ValueError('父版本来源或 View 无效')
        def verify_bucket(bucket):
            if not isinstance(bucket,dict):raise ValueError('父版本 View 无效')
            for key,value in bucket.items():
                if isinstance(value,dict):verify_bucket(value)
                elif isinstance(value,str) and value in parent['sources']:
                    list(_paths([key]))
                else:raise ValueError('父版本包含无法解析的来源')
        for bucket in parent['views'].values():verify_bucket(bucket)
        out=deepcopy(parent);out['parent']=parent['revision'];out['revision']=revision;out['created_at']=created_at
        if formal_baseline is not None:raise ValueError('Formal 基准只允许在初始化时指定')
    else:
        if revision!='rev_0001':raise ValueError('初始版本必须为 rev_0001')
        out={'schema':'effective.simple.v2','owner':deepcopy(owner),'scope':{'vendor':vendor,'library':library},
             'revision':revision,'parent':None,'created_at':created_at,'sources':{},'views':{}}
        if formal_baseline is not None:raise ValueError('RAW 初始化不能声称使用 Formal 基准')
    cross=out['scope']!={'vendor':vendor,'library':library}
    source_key=('@'+ '/'.join(quote(s,safe='') for s in (vendor,library,version))) if cross else version
    source_value={'vendor':vendor,'library':library,'version':version,'delivery':delivery} if cross else delivery
    if source_key in out['sources'] and out['sources'][source_key]!=source_value:
        raise ValueError('相同 RAW 版本对应多个交付')
    selected=set(include_views); seen=set(); count=0
    for kind, node in raw.get('views',{}).items():
        if kind not in selected:continue
        for groups, path in _view_items(node):
            if (kind,path) in seen:raise ValueError('同一 View 内路径重复')
            seen.add((kind,path));count+=1
            bucket=out['views'].setdefault(kind,{})
            for group in groups:
                bucket=bucket.setdefault(group,{})
                if not isinstance(bucket,dict):raise ValueError('View 子分类冲突')
            if path in bucket and isinstance(bucket[path],dict):raise ValueError('View 路径冲突')
            bucket[path]=source_key
    if not count:raise ValueError('所选 View 没有文件')
    out['sources'][source_key]=source_value
    def unique_paths(bucket, seen):
        for key, value in bucket.items():
            if isinstance(value,dict):unique_paths(value,seen)
            else:
                if key in seen:raise ValueError('同一 View 内路径重复')
                seen.add(key)
    for bucket in out['views'].values():unique_paths(bucket,set())
    from ai_lib_qor.versions.store import validate
    validate(out,'effective_simple_v2')
    return out


def _flat_views(revision):
    from ai_lib_qor.versions.store import validate
    validate(revision,'effective_simple_v2')
    result={}
    def walk(kind,bucket):
        for path,value in bucket.items():
            if isinstance(value,dict):walk(kind,value);continue
            list(_paths([path]))
            if (kind,path) in result:raise ValueError('同一 View 路径重复')
            if value not in revision['sources']:raise ValueError('来源不存在')
            src=revision['sources'][value]
            if isinstance(src,str):
                src={'vendor':revision['scope']['vendor'],'library':revision['scope']['library'],'version':value,'delivery':src}
            result[(kind,path)]=src
    for kind,group in revision['views'].items():walk(kind,group)
    return result


def compare_revisions(before,after):
    if before['scope']!=after['scope'] or before['owner']!=after['owner']:raise ValueError('不能比较不同有效集合')
    a=_flat_views(before);b=_flat_views(after);files=[]
    for key in sorted(a.keys()|b.keys()):
        old=a.get(key);new=b.get(key)
        change='ADDED' if old is None else 'REMOVED' if new is None else 'UNCHANGED' if old==new else 'SOURCE_CHANGED'
        files.append({'view':key[0],'path':key[1],'change':change,'before':old,'after':new})
    return {'meaning':'SOURCE_ONLY','from':before['revision'],'to':after['revision'],'files':files}


def file_timeline(revisions,view,path):
    if not revisions:raise ValueError('没有版本')
    for index,r in enumerate(revisions):
        if index and (r['parent']!=revisions[index-1]['revision'] or r['owner']!=revisions[0]['owner'] or r['scope']!=revisions[0]['scope']):
            raise ValueError('版本不是连续父版本链')
    return {'view':view,'path':path,'meaning':'SOURCE_ONLY',
            'versions':[{'revision':r['revision'],'source':_flat_views(r).get((view,path))} for r in revisions]}


def create_formal_revision(formal, raws, *, owner, created_at, include_views, allow_cross_library=False):
    """Explicitly construct baseline from saved Formal links and saved RAW JSON."""
    from .data_query import _subgroup
    if formal.get('schema')!='formal.simple.v3' or not formal.get('snapshot_id'):
        raise ValueError('需要带快照身份的 formal.simple.v3')
    from ai_lib_qor.versions.store import validate
    validate(formal,'formal_simple_v3')
    if formal.get('unassigned'):raise ValueError('快照存在未归属链接，不能作为基准')
    ctx=formal.get('context',{});vendor=ctx.get('vendor');library=ctx.get('library')
    if not isinstance(include_views,(list,tuple,set)) or not include_views:raise ValueError('需要显式选择 View')
    selected=set(include_views); records={}
    for raw in raws:
        if raw.get('schema')!='raw.simple.v1':raise ValueError('RAW 格式不支持')
        c=raw['context'];records.setdefault((c['vendor'],c['library'],c['version']),[]).append(raw)
    normalized=[]
    for kind,links in formal.get('views',{}).items():
        if kind not in selected:continue
        for formal_path,link in links.items():
            if not isinstance(link,dict) or not link.get('raw_version') or not link.get('raw_path') or link.get('match_basis')=='UNKNOWN':
                raise ValueError('正式链接 RAW 来源未确认')
            v=link.get('vendor',vendor);l=link.get('library',library);ver=link['raw_version'];path=link['raw_path']
            if (v,l)!=(vendor,library) and not allow_cross_library:raise ValueError('跨库来源需要显式确认')
            candidates=records.get((v,l,ver),[])
            if link.get('delivery'):candidates=[r for r in candidates if r['delivery_id']==link['delivery']]
            if len(candidates)!=1:raise ValueError('正式链接来源交付不存在或不唯一')
            raw=candidates[0]
            if path not in set(_paths(raw['views'].get(kind,[]))):raise ValueError('正式链接路径不在 RAW 中')
            normalized.append((kind,path,raw))
    if not normalized:raise ValueError('所选 View 无可用正式链接')
    out={'schema':'effective.simple.v2','owner':deepcopy(owner),'scope':{'vendor':vendor,'library':library},
         'revision':'rev_0001','parent':None,'created_at':created_at,'sources':{},'views':{},'formal_baseline':formal['snapshot_id'],
         'formal_nl':ctx['version']}
    for kind,path,raw in normalized:
        c=raw['context'];ver=c['version'];cross=(c['vendor'],c['library'])!=(vendor,library)
        if ver.startswith('@'):raise ValueError('RAW 版本名称不能使用保留的跨库键前缀')
        key=('@'+'/'.join(quote(s,safe='') for s in (c['vendor'],c['library'],ver))) if cross else ver
        src={'vendor':c['vendor'],'library':c['library'],'version':ver,'delivery':raw['delivery_id']} if cross else raw['delivery_id']
        if key in out['sources'] and out['sources'][key]!=src:raise ValueError('来源版本对应多个交付')
        out['sources'][key]=src
        bucket=out['views'].setdefault(kind,{})
        sub=_subgroup(kind,path)
        if sub:bucket=bucket.setdefault(sub,{})
        if path in bucket:raise ValueError('多个正式链接对应同一 RAW 路径')
        bucket[path]=key
    _flat_views(out)
    return out
