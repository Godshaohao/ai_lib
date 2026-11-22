"""Create an isolated simulated RAW/NL dataset and run v3 checks and Excel reports."""
import argparse
import json
import os
from pathlib import Path

from ai_lib_qor.application.data_query import LibraryDataQuery
from ai_lib_qor.application.effective_json import create_revision
from ai_lib_qor.application.effective_publisher import publish_v2
from ai_lib_qor.application.scans import ingest_result, run_scan_and_ingest
from ai_lib_qor.application.simple_sources import simple_raw
from ai_lib_qor.application.v3_checks import run_v3_ip
from ai_lib_qor.sources.formal_sync import sync_formal


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True,help='必须是尚不存在的模拟输出目录')
    args=parser.parse_args();root=Path(args.out).absolute();root.mkdir(parents=True,exist_ok=False)
    work=root/'work';work.mkdir();raw=root/'raw';raw.mkdir();runs=root/'runs';runs.mkdir();plans=root/'plans';plans.mkdir()
    keys={'lef/core.lef':'simlib:lef:core','lib/core.lib':'simlib:liberty:core'}
    layouts={'V01':['lef/core.lef','lib/core.lib','gds/core.gds','verilog/core.v'],
             'V02':['lef/core.lef'],'V03':['lib/core.lib']}
    for version,paths in layouts.items():
        for rel in paths:
            p=raw/version/rel;p.parent.mkdir(parents=True,exist_ok=True)
            if rel.endswith('.lef'):
                p.write_text(f'MACRO CORE\n SIZE {10 if version=="V01" else 12} BY 20 ;\n PIN A\n DIRECTION INPUT ;\n END A\nEND CORE\n')
            elif rel.endswith('.lib'):
                p.write_text('library(test) { cell(CORE) { pin(A) { direction : input; } } }')
            else:p.write_text('模拟占位文件；不作为内容检查输入\n')
    source={'vendor_id':'SIM_VENDOR','source_library_id':'simlib','root':str(raw),
            'version_paths':{v:v for v in layouts},'delivery_orders':{'V01':1,'V02':2,'V03':3},
            'file_mapping':{v+'/'+p:{'file_key':keys[p]} for v,paths in layouts.items() for p in paths if p in keys}}
    (work/'scan_sources.json').write_text(json.dumps({'sources':[source]},ensure_ascii=False,indent=2))
    scan=run_scan_and_ingest(runs,work,source);ingest=ingest_result(runs,scan)
    if scan['status']!='COMPLETE' or ingest['created']!=3:raise ValueError('模拟交付登记未完成：'+str(ingest))
    nl=root/'formal'/'NL_SIM';nl.mkdir(parents=True)
    for rel in ('lef/core.lef','lib/core.lib'):
        link=nl/rel;link.parent.mkdir(parents=True,exist_ok=True)
        link.symlink_to(os.path.relpath(raw/'V01'/rel,link.parent))
    q=LibraryDataQuery(work,runs);records=[x['record'] for x in q.deliveries]
    formal=sync_formal(runs,{'formal_nl_id':'NL_SIM','root':str(nl)},records,work)
    if formal['snapshot_action']!='CREATED':raise ValueError('模拟 Formal 快照未生成：'+str(formal))
    folder=work/'libraries/SIM_VENDOR/simlib';q=LibraryDataQuery(work,runs);parent=None
    for n in (1,2,3):
        revision=create_revision(simple_raw(q,'SIM_VENDOR','simlib',f'V0{n}'),
            owner={'type':'BUSINESS_IP','id':'sim_core'},revision=f'rev_{n:04}',created_at=f'2026-01-0{n}',
            include_views=['LEF','LIBERTY','GDS','VERILOG'],parent=parent)
        publish_v2(work,folder/f'effective_sim_core_{n:03}.json',revision,parent);parent=revision
    profile={'pin_pairs':[{'lef_path':'lef/core.lef','liberty_path':'lib/core.lib'}]}
    (plans/'v3_profile_sim_core.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2))
    status=run_v3_ip(work,runs,vendor='SIM_VENDOR',library='simlib',set_id='sim_core',profile=profile)
    (root/'demo_result.json').write_text(json.dumps(status,ensure_ascii=False,indent=2))
    (root/'README.md').write_text('本目录全部为模拟数据。GDS/Verilog 仅为来源占位文件；本次只检查配置中 LEF/Liberty 的 Macro、Pin 和接口，检查完成不代表全 IP 通过或采纳。\n',encoding='utf-8')
    print(json.dumps({'root':str(root),'scan':scan['scan_id'],'formal_snapshot':formal['snapshot_id'],'run':status},ensure_ascii=False,indent=2))
    if status['state']!='SUCCEEDED':raise SystemExit(1)


if __name__=='__main__':main()
