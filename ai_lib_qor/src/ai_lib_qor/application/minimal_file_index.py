"""Rebuildable ordered path histories over the three minimal source contracts."""
import json
import os
from collections import Counter
from datetime import date
from pathlib import Path, PurePosixPath

from ai_lib_qor.sources.layout import library_folder
from ai_lib_qor.sources.timestamps import instant
from ai_lib_qor.versions.store import locked,write_atomic,validate
from .minimal_effective import _deliveries,_history


def _relative(value):
    if not isinstance(value,str) or not value or '\\' in value or PurePosixPath(value).is_absolute() or any(x in ('','.','..') for x in value.split('/')):
        raise ValueError('文件相对路径无效')
    return value


def _root(value):
    if not isinstance(value,str) or not os.path.isabs(value) or os.path.normpath(value)!=value:raise ValueError('来源根路径无效')
    return value


def _configured_times(work,vendor,library):
    from .path_config import registration_times
    return registration_times(work,vendor,library)


def _ordered(records,times):
    if not isinstance(times,dict):raise ValueError('用户登记时间配置无效')
    rows=[]
    for item in records:
        version=item['version'];value=item['version_date']
        if value:
            try:
                day=date.fromisoformat(value)
                from ai_lib_qor.sources.minimal_delivery import version_date
                if day.isoformat()!=value or version_date(version)!=value:raise ValueError('版本顺序日期与版本名不一致')
            except (TypeError,ValueError):raise ValueError('版本顺序日期无效') from None
            when=instant(times[version]) if version in times else None
            rows.append((day,when,item))
        elif version in times:
            when=instant(times[version]);rows.append((when.date(),when,item))
        else:raise ValueError(f'版本顺序未确认，缺少用户登记时间: {version}')
    for i,(day,when,_) in enumerate(rows):
        for other_day,other_when,_ in rows[i+1:]:
            if day==other_day and (when is None or other_when is None or when==other_when):
                raise ValueError('版本顺序未确认：同日记录无法比较')
    rows.sort(key=lambda r:(r[0],r[1] if r[1] else None))
    return [row[2] for row in rows]


def build_index(work,vendor,library):
    folder=library_folder(work,vendor,library);deliveries=_deliveries(folder,vendor,library)
    ordered=_ordered(list(deliveries.values()),_configured_times(work,vendor,library))
    if not ordered:raise ValueError('没有来源交付')
    index={'vendor':vendor,'library':library,'deliveries':[],'nl_snapshots':[],'revisions':[],'views':{}}
    def node(view,path):return index['views'].setdefault(view,{}).setdefault(path,{'raw':[],'nl':[],'effective':[]})
    known={}
    for d in ordered:
        root=_root(d['root']);index['deliveries'].append({'version':d['version'],'version_date':d['version_date'],'root':root})
        for view,paths in d['views'].items():
            if not isinstance(view,str) or not isinstance(paths,list):raise ValueError('交付 View 无效')
            for rel in paths:
                _relative(rel);key=(view,d['version'],rel)
                if key in known:raise ValueError('同一来源文件重复')
                absolute=os.path.join(root,rel);known[key]=absolute
                node(view,rel)['raw'].append({'version':d['version'],'path':absolute})
    snapshots=[]
    for p in folder.glob('formal_*.json'):
        if p.is_symlink():raise ValueError('正式快照不能为软链接')
        f=json.loads(p.read_text(encoding='utf-8'))
        validate(f,'formal_path')
        if set(f)!={'version','vendor','library','root','observed_at','views'} or (f['vendor'],f['library'])!=(vendor,library):raise ValueError('正式快照范围或格式不正确')
        snapshots.append((instant(f['observed_at']),p.name,f))
    snapshots.sort(key=lambda x:(x[0],x[1]))
    for _,_,f in snapshots:
        root=_root(f['root']);index['nl_snapshots'].append({'nl_version':f['version'],'observed_at':f['observed_at'],'root':root})
        for view,versions in f['views'].items():
            for version,links in versions.items():
                d=deliveries.get(version)
                if d is None:raise ValueError('正式来源版本不存在')
                raw_root=_root(d['root'])
                for link in links:
                    link_rel=_relative(link['path']);resolved=_root(link['resolved'])
                    if not Path(resolved).is_relative_to(raw_root):raise ValueError('正式来源不在记录的版本目录')
                    rel=_relative(Path(resolved).relative_to(raw_root).as_posix())
                    if known.get((view,version,rel))!=resolved:raise ValueError('正式来源不在交付清单中')
                    if not isinstance(link['target'],str):raise ValueError('正式链接目标无效')
                    link_path=os.path.join(root,link_rel)
                    textual=os.path.normpath(link['target'] if os.path.isabs(link['target']) else os.path.join(os.path.dirname(link_path),link['target']))
                    node(view,rel)['nl'].append({'version':f['version'],'observed_at':f['observed_at'],
                      'link_path':link_path,'link_target':link['target'],'resolved_path':resolved,
                      'source_match':'MATCHED_RAW' if textual==resolved else 'UNVERIFIED'})
    for _,_,effective in _history(folder,library):
        if (effective.get('vendor'),effective.get('library'))!=(vendor,library):raise ValueError('有效版本范围不一致')
        revision=effective['revision'];index['revisions'].append(revision);seen=set()
        for view,versions in effective['views'].items():
            for version,paths in versions.items():
                for rel in paths:
                    _relative(rel);key=(view,rel)
                    if key in seen:raise ValueError('有效文件成员重复')
                    seen.add(key);source=known.get((view,version,rel))
                    if source is None:raise ValueError('有效版本来源不在交付清单中')
                    node(view,rel)['effective'].append({'revision':revision,'version':version,'path':source})
    index['views']={v:dict(sorted(files.items())) for v,files in sorted(index['views'].items())}
    validate(index,'file_index_path')
    return index


def refresh_index_locked(work,vendor,library):
    folder=library_folder(work,vendor,library);path=folder/'file_index.json'
    if path.is_symlink():raise ValueError('索引不能为软链接')
    new=build_index(work,vendor,library)
    if path.exists():
        old=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(old,dict) or set(old)!={'vendor','library','deliveries','nl_snapshots','revisions','views'} or (old['vendor'],old['library'])!=(vendor,library):raise ValueError('已有索引属于其他格式，拒绝覆盖')
        if old==new:return {'state':'UNCHANGED','path':str(path)}
        def contains(before,after):
            encode=lambda v:json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'))
            return not (Counter(map(encode,before))-Counter(map(encode,after)))
        try:
            preserved=all(contains(old[key],new[key]) for key in ('deliveries','nl_snapshots','revisions'))
            for view,files in old['views'].items():
                for relative,row in files.items():
                    target=new['views'].get(view,{}).get(relative)
                    if not target or not all(contains(row[k],target[k]) for k in ('raw','nl','effective')):preserved=False
        except (KeyError,TypeError,AttributeError):preserved=False
        if not preserved:raise ValueError('已发布索引的历史记录发生变更，拒绝覆盖')
    write_atomic(path,new)
    return {'state':'UPDATED','path':str(path)}


def refresh_index(work,vendor,library):
    folder=library_folder(work,vendor,library)
    if not folder.is_dir():raise ValueError('库目录不存在')
    with locked(folder):return refresh_index_locked(work,vendor,library)


def query_path(work,vendor,library,view,path,*,revision=None,version=None):
    if revision is not None and version is not None:raise ValueError('只能指定 Effective 版本或交付版本')
    folder=library_folder(work,vendor,library);index_path=folder/'file_index.json'
    if index_path.is_symlink() or not index_path.is_file():raise ValueError('索引不存在或无效')
    with locked(folder):
        saved=json.loads(index_path.read_text(encoding='utf-8'))
        try:current=build_index(work,vendor,library)
        except (OSError,ValueError,KeyError,TypeError) as exc:raise ValueError('索引已过期或来源无效: '+str(exc)) from exc
        if saved!=current:raise ValueError('索引已过期，请重建')
        row=saved['views'].get(view,{}).get(_relative(path))
        if row is None:raise ValueError('文件不在索引中')
        result={'vendor':vendor,'library':library,'view':view,'path':path,**row}
        if revision is not None:
            if revision not in saved['revisions']:raise ValueError('有效版本不存在')
            matches=[r for r in row['effective'] if r['revision']==revision]
            if len(matches)>1:raise ValueError('有效版本来源不唯一')
            result['effective']=matches[0] if matches else None
        if version is not None:
            order=[item['version'] for item in saved['deliveries']]
            if version not in order:raise ValueError('交付版本不存在')
            rank={v:i for i,v in enumerate(order)};at=rank[version]
            candidates=[item for item in row['raw'] if rank[item['version']]<=at]
            result['as_of']=candidates[-1] if candidates else None
        return result
