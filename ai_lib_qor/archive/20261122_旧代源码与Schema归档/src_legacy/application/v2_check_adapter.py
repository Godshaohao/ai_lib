"""Resolve saved v2 members to confirmed v1 check identities without rewriting history."""
from pathlib import Path
import re
from .data_query import get_effective_v2_files


def load_v2_for_check(path, work):
    path=Path(path)
    root=Path(work).resolve(strict=True)
    if path.is_symlink():raise ValueError('有效版本文件不能是符号链接')
    resolved=path.resolve(strict=True)
    try:parts=resolved.relative_to(root).parts
    except ValueError:raise ValueError('版本文件不在 work 目录内') from None
    if len(parts)!=4 or parts[0]!='libraries':raise ValueError('版本路径不符合库目录结构')
    match=re.fullmatch(r'effective_(.+)_(\d+)\.json',parts[3])
    if not match:raise ValueError('有效版本文件名无效')
    set_id=match.group(1);revision='rev_'+match.group(2).zfill(4)
    value=get_effective_v2_files(root,parts[1],parts[2],set_id,revision)
    from .source_repository import SourceRepository
    from collections import Counter
    identities=Counter((d['record']['source_library_id'],d['record']['delivery_id'],f['file_id'])
                       for d in SourceRepository(root).deliveries() for f in d['files'])
    members={}
    for item in value['files']:
        if item['resolution']!='RECORDED' or item['identity_status']!='CONFIRMED' or item['classification']!='RESOLVED' or not item['file_key'] or not item['file_id']:
            raise ValueError(f"文件身份或来源未确认，不能用于旧检查: {item['path']}")
        key=item['file_key']
        if key in members:raise ValueError('有效版本包含重复文件位')
        if identities[(item['source']['library'],item['delivery_id'],item['file_id'])]!=1:
            raise ValueError('旧检查引用在跨供应商记录中不唯一')
        members[key]={'kind':'delivery_file','source_library_id':item['source']['library'],
                      'delivery_id':item['delivery_id'],'file_id':item['file_id']}
    if not members:raise ValueError('有效版本无可检查的已确认文件')
    return {'revision_id':value['revision'],'parent_revision_id':value['parent'],'effective_set_id':set_id,
            'owner':{'owner_type':value['owner']['type'],'owner_id':value['owner']['id'],
                     'home_source_library_id':value['scope']['library']},'members':members,
            'scope':value['scope'],'source_roots':sorted({f['source_root'] for f in value['files'] if f['source_root']})}
