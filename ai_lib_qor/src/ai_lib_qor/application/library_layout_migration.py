"""Move path-contract archives into their per-library folders without rewriting history."""
import os
import json
import re
from pathlib import Path
from ai_lib_qor.sources.layout import library_folder,storage_dir
from ai_lib_qor.sources.root_inventory import update_pointer
from ai_lib_qor.versions.store import locked,validate


def migrate_library_layout(work,vendor,library):
    from .minimal_file_index import build_index
    folder=library_folder(work,vendor,library)
    if not folder.is_dir():raise ValueError('库目录不存在')
    with locked(folder):
        original=build_index(work,vendor,library)
        pending=[]
        for kind,pattern in [('delivery','delivery_*.json'),('formal','formal_*.json'),('effective','effective_'+library+'_*.json')]:
            for source in sorted(folder.glob(pattern)):
                if kind=='effective' and not re.fullmatch(r'effective_'+re.escape(library)+r'_\d+\.json',source.name):continue
                if source.is_symlink() or not source.is_file():raise ValueError('历史归档不能是软链接')
                pending.append((source,storage_dir(folder,kind)/source.name))
        for name in ('raw_observations.tsv','effective_operations.tsv','.auto_effective_state.json'):
            source=folder/name
            if source.is_symlink():raise ValueError('操作记录不能为软链接')
            if source.is_file():pending.append((source,storage_dir(folder,'log')/name))
        if any(dest.exists() or dest.is_symlink() for _,dest in pending):raise ValueError('目标文件已存在，停止迁移')
        pointers={p.name:os.readlink(p) for p in folder.glob('latest_*.json') if p.is_symlink()}
        # All latest source pointers must already resolve to one known immutable file.
        for name,target in pointers.items():
            if not (folder/target).is_file():raise ValueError('历史指针失效，停止迁移: '+name)
        moved=[]
        try:
            for source,dest in pending:os.rename(source,dest);moved.append((source,dest))
            for name,target in pointers.items():
                source=folder/target
                destination=next((dest for old,dest in moved if old==source),None)
                if destination:update_pointer(folder,name,str(destination.relative_to(folder)))
            if build_index(work,vendor,library)!=original:raise ValueError('迁移前后索引内容不一致')
        except Exception:
            for source,dest in reversed(moved):os.rename(dest,source)
            for name,target in pointers.items():update_pointer(folder,name,target)
            raise
        # Old checks/facts may contain absolute references to one another; keep them untouched.
        legacy=[p.name for pattern in ('facts_*.json','check_run_*.json','report_run_*.xlsx','overall_run_*.json','overall_run_*.xlsx') for p in folder.glob(pattern) if not p.is_symlink()]
        # Initialize legacy latest pointers only from complete JSON/Excel pairs.
        checks=[]
        for path in folder.glob('check_run_*.json'):
            if path.is_symlink():continue
            try:
                row=json.loads(path.read_text(encoding='utf-8'))
                validate(row,'check_result_path')
                excel=folder/('report_'+row['run_id']+'.xlsx')
                if (row.get('vendor'),row.get('library'))!=(vendor,library) or not excel.is_file() or excel.is_symlink():continue
                checks.append((row['run_at'],row['run_id'],path,excel))
            except (OSError,ValueError,KeyError,TypeError):continue
        if checks and not (folder/'latest_check.json').exists() and not (folder/'latest_check.json').is_symlink() and not (folder/'latest_check.xlsx').exists() and not (folder/'latest_check.xlsx').is_symlink():
            _,_,check,excel=max(checks)
            update_pointer(folder,'latest_check.json',check.name);update_pointer(folder,'latest_check.xlsx',excel.name)
        overall=[p for p in folder.glob('overall_run_*.xlsx') if p.is_file() and not p.is_symlink() and p.with_suffix('.json').is_file()]
        if overall and not (folder/'latest_overall.xlsx').exists() and not (folder/'latest_overall.xlsx').is_symlink():
            update_pointer(folder,'latest_overall.xlsx',max(overall,key=lambda p:(p.stat().st_mtime_ns,p.name)).name)
        return {'vendor':vendor,'library':library,'moved':len(moved),'preserved_legacy_artifacts':sorted(legacy)}
