"""Library-local run log and constrained artifact names; legacy runs remain separate."""
import json
import os
import re
from pathlib import Path
from ai_lib_qor.sources.layout import library_folder
from ai_lib_qor.versions.store import locked

RUN_ID=re.compile(r'run_[0-9a-f]{32}\Z')
FACT_FILE=re.compile(r'facts_[0-9a-f]{24}_[0-9a-f]{24}\.json\Z')


def paths(folder,run_id):
    if not RUN_ID.fullmatch(run_id or ''):raise ValueError('运行 ID 无效')
    folder=Path(folder)
    return {'check.json':folder/f'check_{run_id}.json', 'report.xlsx':folder/f'report_{run_id}.xlsx',
            'report.html':folder/f'report_{run_id}.html','overall.json':folder/f'overall_{run_id}.json',
            'overall.xlsx':folder/f'overall_{run_id}.xlsx'}


def append_status(folder,status):
    """Single locked append with fsync; other runs are never overwritten."""
    if not RUN_ID.fullmatch(status.get('id','')):raise ValueError('运行 ID 无效')
    folder=Path(folder);log=folder/'runs.jsonl'
    with locked(folder):
        if log.is_symlink():raise ValueError('运行日志不能是软链接')
        if status.get('state')=='RUNNING':
            if any(p.exists() or p.is_symlink() for p in paths(folder,status['id']).values()):
                raise ValueError('运行 ID 已存在，不能覆盖产物')
            if log.exists():
                with log.open(encoding='utf-8') as previous:
                    for line in previous:
                        try:entry=json.loads(line)
                        except (ValueError,TypeError):continue
                        if isinstance(entry,dict) and entry.get('kind')=='CHECK_RUN' and entry.get('id')==status['id']:
                            raise ValueError('运行 ID 已存在，不能覆盖历史')
        fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_APPEND|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(fd,'a',encoding='utf-8') as f:
            f.write(json.dumps({'kind':'CHECK_RUN',**status},ensure_ascii=False,separators=(',',':'))+'\n')
            f.flush();os.fsync(f.fileno())


def history(work):
    """Latest log entry per run; duplicate IDs across libraries are rejected."""
    if not work:return []
    root=Path(work).resolve();seen={};scope={}
    for log in sorted(root.glob('libraries/*/*/runs.jsonl')):
        if log.is_symlink() or any(p.is_symlink() for p in (log.parent,log.parent.parent)) or not log.is_file():continue
        vendor,library=log.parent.parent.name,log.parent.name
        try:
            if library_folder(root,vendor,library)!=log.parent.resolve():continue
            with log.open(encoding='utf-8') as f:
                for line in f:
                    try:entry=json.loads(line)
                    except (ValueError,TypeError):continue
                    if not isinstance(entry,dict) or entry.get('kind')!='CHECK_RUN' or not isinstance(entry.get('id'),str) or not RUN_ID.fullmatch(entry['id']):continue
                    owner=entry.get('owner') or {}
                    if not isinstance(owner,dict):continue
                    if (owner.get('vendor'),owner.get('library'))!=(vendor,library):continue
                    ident=entry['id']
                    if ident in scope and scope[ident]!=(vendor,library):raise ValueError('运行 ID 跨库重复')
                    scope[ident]=(vendor,library);seen[ident]={**entry,'storage':'LIBRARY'}
        except (OSError,UnicodeError):continue
    return sorted(seen.values(),key=lambda x:x.get('started_at',''),reverse=True)


def artifact(work,status,name):
    owner=status.get('owner') or {};folder=library_folder(work,owner.get('vendor',''),owner.get('library',''))
    allowed=paths(folder,status.get('id',''))
    if name in allowed:path=allowed[name]
    elif FACT_FILE.fullmatch(name or '') and name in status.get('facts_files',[]):path=folder/name
    else:raise ValueError('产物名称无效')
    if path.is_symlink() or not path.is_file() or path.parent.resolve()!=folder.resolve():raise ValueError('产物不可用')
    return path
