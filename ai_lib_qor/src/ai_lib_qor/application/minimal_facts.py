"""Build path-based FileFacts from the validated minimal file index."""
from pathlib import Path
import json

from ai_lib_qor.facts import parsers
from ai_lib_qor.sources.layout import library_folder,next_filename
from ai_lib_qor.sources.timestamps import instant,utc_text
from ai_lib_qor.versions.store import locked,validate,write_atomic
from .minimal_file_index import build_index,query_path


def _stat_key(path):
    stat=path.stat()
    return (stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)


def build_facts(work,vendor,library,view,relative_path,*,version=None,revision=None,_capture=False):
    if (version is None)==(revision is None):raise ValueError('必须且只能指定一个交付版本或有效版本')
    if view not in ('LEF','LIBERTY','VERILOG','CDL','SPICE'):raise ValueError('此 View 暂不支持 FileFacts 解析')
    row=query_path(work,vendor,library,view,relative_path,revision=revision,version=version)
    chosen=row['effective'] if revision else row['as_of']
    if not chosen or (version and chosen['version']!=version):raise ValueError('指定版本没有该文件')
    source_version=chosen['version'];absolute=Path(chosen['path'])
    folder=library_folder(work,vendor,library)
    index_path=folder/'file_index.json'
    if index_path.is_symlink() or not index_path.is_file():raise ValueError('索引不存在或无效')
    data=json.loads(index_path.read_text(encoding='utf-8'))
    deliveries=[d for d in data['deliveries'] if d['version']==source_version]
    if len(deliveries)!=1:raise ValueError('来源版本不唯一')
    root=Path(deliveries[0]['root']).resolve(strict=True)
    real=absolute.resolve(strict=True)
    if not real.is_relative_to(root) or not real.is_file() or real!=absolute:raise ValueError('RAW 文件不存在、越界或包含符号链接')
    before=_stat_key(real);digest=parsers._file_digest(real)
    if _stat_key(real)!=before:raise ValueError('读取 RAW 文件时发生变化')
    payload=parsers.parse_file_payload(real,view,allow_pg=True)
    if _stat_key(real)!=before or parsers._file_digest(real)!=digest:raise ValueError('解析期间 RAW 文件发生变化')
    if _stat_key(real)!=before:raise ValueError('解析期间 RAW 文件发生变化')
    at=utc_text()
    facts={'schema_version':'file_facts.path.v1',
           'source':{'vendor':vendor,'library':library,'version':source_version,'relative_path':relative_path,
                     'absolute_path':str(absolute),'historical_content':'UNVERIFIED'},
           'selection':{'kind':'EFFECTIVE' if revision else 'DELIVERY','value':revision or version},
           'parsed_at':at,**payload}
    validate(facts,'file_facts_path')
    with locked(folder):
        if index_path.is_symlink() or not index_path.is_file():raise ValueError('索引不存在或无效')
        saved=json.loads(index_path.read_text(encoding='utf-8'))
        if build_index(work,vendor,library)!=saved:raise ValueError('解析期间索引已过期')
        latest=saved['views'].get(view,{}).get(relative_path,{})
        entries=latest.get('effective' if revision else 'raw',[])
        if sum(x.get('version')==source_version and x.get('path')==str(absolute) and (not revision or x.get('revision')==revision) for x in entries)!=1:
            raise ValueError('解析期间文件来源发生变化')
        if _stat_key(real)!=before:raise ValueError('保存前 RAW 文件发生变化')
        stamp=instant(at).strftime('%Y%m%dT%H%M%SZ')
        output=folder/next_filename(folder,f'facts_{view}_{stamp}')
        write_atomic(output,facts,immutable=True)
    result={'state':'CREATED','path':str(output),'view':view,'version':source_version}
    if _capture:result['_source_stamp']=(before,digest)
    return result
