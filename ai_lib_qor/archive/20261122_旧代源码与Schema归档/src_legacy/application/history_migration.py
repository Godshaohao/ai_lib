"""Create an auditable v2 shadow copy of a v1 history, never overwriting it."""
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from .data_query import LibraryDataQuery
from .simple_sources import simple_effective
from .effective_json import _flat_views
from ai_lib_qor.versions.index_projector import project, project_simple
from ai_lib_qor.versions.store import now


def migrate_history(work, runs, *, vendor, library, owner, output):
    work=Path(work).resolve(); output=Path(output).resolve()
    if output==work or output.is_relative_to(work):raise ValueError('迁移输出不能位于原工作目录内')
    if output.exists():raise FileExistsError(f'迁移输出已存在: {output}')
    q=LibraryDataQuery(work,runs)
    for item in q.deliveries:
        root=Path(item['record']['source_root']).resolve()
        if output==root or output.is_relative_to(root):raise ValueError('迁移输出不能位于 RAW 来源内')
    for snapshot in q.snapshots:
        root=Path(snapshot['source_root']).resolve()
        if output==root or output.is_relative_to(root):raise ValueError('迁移输出不能位于 Formal 来源内')
    entries=[e for e in q.entries if (e['vendor'],e['library'],e['ip'])==(vendor,library,owner)]
    if len(entries)!=1:raise ValueError('有效集不存在或不唯一')
    entry=entries[0]; old=entry['versions']; acceptance=entry['acceptance']
    if not old or acceptance is None:raise ValueError('旧版本或采纳记录不可用')
    index=entry['index']; set_id=index['effective_set_id']
    from ai_lib_qor.sources.layout import SAFE
    if not SAFE.fullmatch(set_id):raise ValueError('有效集标识不安全')
    projected=project(old,acceptance,now())
    if any(index[k]!=projected[k] for k in ('owner','effective_set_id','latest_calculated_revision','current_accepted_revision')):
        raise ValueError('旧索引与版本/采纳历史不一致，不能迁移')
    versions=[]; counts=[]
    for i,rev in enumerate(old):
        expected=old[i-1]['revision_id'] if i else None
        if rev['parent_revision_id']!=expected:raise ValueError('旧版本不是连续父版本链')
        converted=simple_effective(q,vendor,library,owner,rev['revision_id'])
        flat=_flat_views(converted)
        if len(flat)!=len(rev['members']):raise ValueError('转换前后成员数量不一致')
        versions.append(converted);counts.append({'revision':rev['revision_id'],'members':len(flat)})
    new_index=project_simple(versions,acceptance,set_id,now())
    if any(index[k]!=new_index[k] for k in ('owner','effective_set_id','latest_calculated_revision','current_accepted_revision')):
        raise ValueError('v2 版本重放采纳结果与旧索引不一致')
    output.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.effective-migrate-',dir=output.parent))
    def dump(name,obj):
        (staging/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    made=False; linked=[]
    try:
        for v in versions:
            n=int(v['revision'][4:]);dump(f'effective_{set_id}_{n:03d}.json',v)
        dump(f'effective_{set_id}_index.json',index)
        (staging/f'effective_{set_id}_acceptance.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n' for x in acceptance),encoding='utf-8')
        manifest={'schema':'effective_migration_report.v1','status':'SHADOW_ONLY',
                  'source_work':str(work),'vendor':vendor,'library':library,'owner':owner,'effective_set_id':set_id,
                  'source_format':'effective_version.v1','target_format':'effective.simple.v2',
                  'revision_count':len(versions),'revisions':counts,'acceptance_events':len(acceptance),
                  'latest_calculated_revision':index['latest_calculated_revision'],'current_accepted_revision':index['current_accepted_revision'],
                  'limitations':['v1 file_key, source_ref, changes and non-baseline reasons are not preserved in v2',
                                 'v2 files are not yet consumable by the v1 workbench or version service']}
        manifest['output_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(staging.iterdir())}
        dump('migration_report.json',manifest)
        os.mkdir(output);made=True
        for file in staging.iterdir():
            target=output/file.name
            os.link(file,target);linked.append(target)
        return manifest
    except BaseException:
        if made:
            for target in linked:
                try:target.unlink()
                except FileNotFoundError:pass
            try:output.rmdir()
            except OSError:pass
        raise
    finally:
        shutil.rmtree(staging)
