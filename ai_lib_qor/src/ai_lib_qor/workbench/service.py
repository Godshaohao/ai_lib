"""Run an explicit trusted check plan through the existing v3 CLI services."""
import json
import uuid
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

from ai_lib_qor.__main__ import run

ARTIFACTS = ('input_plan.json', 'check.json', 'report.html', 'report.xlsx', 'parser_evidence.json', 'parser_evidence.html', 'overall.xlsx', 'overall.json')


def plans_in(root):
    root = Path(root).resolve()
    return sorted(p.name for p in root.glob('*.json') if p.is_file() and not p.is_symlink())


def select_plan(root, name):
    if name not in plans_in(root):
        raise ValueError('请选择计划目录中存在的 JSON 文件')
    return Path(root).resolve() / name


def _write_status(folder, data):
    path = folder / 'status.json'
    temp = folder / 'status.tmp'
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def execute(plan_path, runs_root, owner=None, expected_revision=None):
    folder = Path(runs_root) / ('run_' + uuid.uuid4().hex)
    folder.mkdir(parents=True, exist_ok=False)
    status = {'id': folder.name, 'plan': plan_path.name, 'state': 'RUNNING',
              'started_at': datetime.now(timezone.utc).isoformat()}
    if owner is not None: status['owner'] = owner
    if expected_revision is not None: status['expected_revision'] = expected_revision
    _write_status(folder, status)
    try:
        from ai_lib_qor.versions.store import write_atomic
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        plan['run_id'] = status['id']
        plan['run_at'] = status['started_at']
        run_plan = folder / 'input_plan.json'
        write_atomic(run_plan, plan, immutable=True)
        run(Namespace(command='check', plan=str(run_plan), out=str(folder / 'check.json')))
        check = json.loads((folder / 'check.json').read_text(encoding='utf-8'))
        status['target'] = check['target']['id']
        status['target_kind'] = check['target']['kind']
        status['summary'] = check['summary']
        facts = []
        for row in plan.get('comparisons', []): facts.extend((row['old_facts'], row['new_facts']))
        for row in plan.get('pin_pairs', []): facts.extend((row['lef_facts'], row['liberty_facts']))
        for row in plan.get('auto_pair_facts', []): facts.append(row['facts'])
        options = dict(command='report', check=str(folder / 'check.json'),
                       html=str(folder / 'report.html'), excel=str(folder / 'report.xlsx'),
                       delivery=list(dict.fromkeys([plan[k] for k in ('baseline_delivery', 'target_delivery') if k in plan] + plan.get('report_deliveries', []))),
                       facts=list(dict.fromkeys(facts)), formal_snapshot=plan.get('report_formal_snapshot'),
                       source_snapshot=plan.get('formal_snapshots', []),
                       target_revision=plan.get('target_revision'), baseline_revision=plan.get('baseline_revision'),
                       accepted_revision=plan.get('report_accepted_revision'), effective_index=plan.get('report_effective_index'))
        run(Namespace(**options))
        status['state'] = 'SUCCEEDED'
    except Exception as exc:
        status['state'] = 'FAILED'
        status['error'] = f'{type(exc).__name__}: {exc}'
    status['finished_at'] = datetime.now(timezone.utc).isoformat()
    _write_status(folder, status)
    return status


def history(root):
    result = []
    for path in Path(root).glob('run_*/status.json'):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('id') == path.parent.name:
                check_path = path.parent / 'check.json'
                if 'summary' not in data and check_path.is_file() and not check_path.is_symlink():
                    try:
                        from ai_lib_qor.versions.store import read_json
                        data['summary'] = read_json(check_path, 'check_result')['summary']
                    except (OSError, ValueError, KeyError): pass
                result.append(data)
        except (OSError, ValueError):
            continue
    return sorted(result, key=lambda x: x.get('started_at', ''), reverse=True)


def execute_evidence(delivery, file_id, runs_root):
    from ai_lib_qor.facts.rich_evidence import parse_delivery_evidence
    from ai_lib_qor.versions.store import write_atomic
    root = Path(runs_root).resolve()
    if root.is_relative_to(Path(delivery['source_root']).resolve()):
        raise ValueError('运行目录不能位于 RAW 来源目录')
    folder = root / ('run_' + uuid.uuid4().hex)
    folder.mkdir(parents=True, exist_ok=False)
    status = {'id':folder.name,'plan':'解析证据','state':'RUNNING',
              'target':delivery['delivery_id'], 'target_kind':'RAW_DELIVERY',
              'started_at':datetime.now(timezone.utc).isoformat()}
    _write_status(folder,status)
    try:
        evidence = parse_delivery_evidence(delivery,file_id)
        write_atomic(folder/'parser_evidence.json', evidence, immutable=True)
        from ai_lib_qor.reporting.evidence_html import render_evidence_html
        with (folder/'parser_evidence.html').open('x', encoding='utf-8') as output:
            output.write(render_evidence_html(evidence))
        status['state']='SUCCEEDED'
    except Exception as exc:
        status['state']='FAILED';status['error']=f'{type(exc).__name__}: {exc}'
    status['finished_at']=datetime.now(timezone.utc).isoformat()
    _write_status(folder,status)
    return status


def plans_for_revision(plans_root, revision):
    """Only offer plans that resolve to the exact selected revision record."""
    from ai_lib_qor.versions.store import read_json
    matched = []
    for name in plans_in(plans_root):
        try:
            plan = json.loads((Path(plans_root) / name).read_text(encoding='utf-8'))
            target = plan.get('target_revision')
            if target and 'target_delivery' not in plan and read_json(target, 'effective_version') == revision:
                matched.append(name)
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return matched


def execute_ip_batch(selected, plans_root, runs_root):
    """Run exactly one matched plan per saved revision, then publish an explicit overview."""
    from ai_lib_qor.versions.store import read_json, write_atomic
    from ai_lib_qor.checks.evidence import validate_check_result
    from ai_lib_qor.reporting.overall_excel import render_overall_excel
    versions=selected['versions']
    if not versions: raise ValueError('没有可检查的有效版本')
    matched=[(r,plans_for_revision(plans_root,r)) for r in versions]
    if any(len(names)!=1 for _,names in matched): raise ValueError('每个版本必须有且只有一个匹配计划')
    owner={key:selected[key] for key in ('vendor','library','ip')}
    folder=Path(runs_root)/('run_'+uuid.uuid4().hex);folder.mkdir(parents=True,exist_ok=False)
    status={'id':folder.name,'owner':owner,'plan':'整体 IP 报告','target':owner['ip'],
            'target_kind':'IP_VERSION_BATCH','state':'RUNNING','started_at':datetime.now(timezone.utc).isoformat()}
    _write_status(folder,status)
    rows=[]
    try:
        for rev,names in matched:
            child=execute(select_plan(plans_root,names[0]),runs_root,owner=owner,expected_revision=rev['revision_id'])
            row={'revision':rev['revision_id'],'plan':names[0],'run_id':child['id'],'state':child['state'],'error':child.get('error')}
            path=Path(runs_root)/child['id']/'check.json'
            if path.is_file():
                check=read_json(path,'check_result');validate_check_result(check)
                if check['target']['id']!=rev['revision_id'] or check['effective_set_id']!=rev['effective_set_id']:
                    raise ValueError('逐版本结果与所选版本不一致')
                row.update(summary=check['summary'],comparison_count=len(check['file_changes']),baseline=(check.get('baseline') or {}).get('id'),checks=check['quality_checks'],note=check['evidence_note'])
            rows.append(row)
        write_atomic(folder/'overall.json',{'owner':owner,'versions':rows},immutable=True)
        render_overall_excel(owner,rows,folder/'overall.xlsx')
        status['children']=[{'id':r['run_id'],'revision':r['revision'],'state':r['state'],'summary':r.get('summary')} for r in rows]
        status['state']='SUCCEEDED' if all(r['state']=='SUCCEEDED' for r in rows) else 'PARTIAL'
    except Exception as exc:
        status['state']='FAILED';status['error']=f'{type(exc).__name__}: {exc}'
        status['children']=[{'id':r['run_id'],'revision':r['revision'],'state':r['state'],'summary':r.get('summary')} for r in rows]
    status['finished_at']=datetime.now(timezone.utc).isoformat();_write_status(folder,status)
    return status
