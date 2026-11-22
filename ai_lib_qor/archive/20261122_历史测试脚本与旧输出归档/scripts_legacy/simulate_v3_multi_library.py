"""Build 3 simulated vendors, 5 libraries, 20 deliveries and 3 IP reports."""
import argparse
import json
import os
from pathlib import Path

from ai_lib_qor.application.data_query import LibraryDataQuery
from ai_lib_qor.application.effective_json import create_revision
from ai_lib_qor.application.effective_publisher import publish_v2
from ai_lib_qor.application.scans import ingest_result,run_scan_and_ingest
from ai_lib_qor.application.simple_sources import simple_raw
from ai_lib_qor.application.v3_checks import run_v3_ip
from ai_lib_qor.sources.formal_sync import sync_formal


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True);args=p.parse_args()
    root=Path(args.out).absolute();root.mkdir(parents=True,exist_ok=False)
    work=root/'work';work.mkdir();runs=root/'runs';runs.mkdir();plans=root/'plans';plans.mkdir();raw=root/'raw';raw.mkdir()
    groups=[('SIM_A','lib_a1',True),('SIM_A','lib_a2',False),('SIM_B','lib_b1',True),('SIM_B','lib_b2',False),('SIM_C','lib_c1',True)]
    layout={'V01':['lef/core.lef','lib/core.lib','gds/core.gds','verilog/core.v'],
            'V02':['lef/core.lef'],'V03':['lib/core.lib'],'V04':['lef/core.lef','lib/core.lib']}
    sources=[]
    for vendor,library,_ in groups:
        base=raw/vendor/library
        for version,paths in layout.items():
            for rel in paths:
                f=base/version/rel;f.parent.mkdir(parents=True,exist_ok=True)
                if rel.endswith('.lef'):
                    size={'V01':10,'V02':12,'V04':14}[version]
                    f.write_text(f'MACRO CORE\n SIZE {size} BY 20 ;\n PIN A\n DIRECTION INPUT ;\n END A\nEND CORE\n')
                elif rel.endswith('.lib'):
                    extra='pin(B) { direction : output; }' if version=='V04' else ''
                    f.write_text('library(test) { cell(CORE) { pin(A) { direction : input; } '+extra+' } }')
                else:f.write_text('模拟占位文件，不参与内容检查\n')
        keys={'lef/core.lef':library+':lef:core','lib/core.lib':library+':liberty:core'}
        sources.append({'vendor_id':vendor,'source_library_id':library,'root':str(base),
          'version_paths':{v:v for v in layout},'delivery_orders':{f'V0{n}':n for n in range(1,5)},
          'file_mapping':{v+'/'+path:{'file_key':keys[path]} for v,paths in layout.items() for path in paths if path in keys}})
    (work/'scan_sources.json').write_text(json.dumps({'sources':sources},ensure_ascii=False,indent=2))
    reports=[]
    for source,(_,library,is_ip) in zip(sources,groups):
        vendor=source['vendor_id'];scan=run_scan_and_ingest(runs,work,source);ingest=ingest_result(runs,scan)
        if scan['status']!='COMPLETE' or ingest['created']!=4:raise ValueError(f'{vendor}/{library}: 登记失败: {ingest}')
        nl=root/'formal'/vendor/library;nl.mkdir(parents=True)
        for rel in ('lef/core.lef','lib/core.lib'):
            link=nl/rel;link.parent.mkdir(parents=True,exist_ok=True)
            link.symlink_to(os.path.relpath(Path(source['root'])/'V01'/rel,link.parent))
        q=LibraryDataQuery(work,runs);records=[x['record'] for x in q.deliveries if (x['record']['vendor_id'],x['record']['source_library_id'])==(vendor,library)]
        snapshot=sync_formal(runs,{'formal_nl_id':'NL_SIM','root':str(nl)},records,work)
        if snapshot['snapshot_action']!='CREATED':raise ValueError(f'{vendor}/{library}: 正式快照未生成')
        q=LibraryDataQuery(work,runs);folder=work/'libraries'/vendor/library;owner={'type':'BUSINESS_IP' if is_ip else 'SOURCE_LIBRARY','id':library+'_ip' if is_ip else library};set_id=owner['id'];parent=None
        for n in range(1,5):
            rev=create_revision(simple_raw(q,vendor,library,f'V0{n}'),owner=owner,revision=f'rev_{n:04}',created_at=f'2026-01-0{n}',
                include_views=['LEF','LIBERTY','GDS','VERILOG'],parent=parent)
            publish_v2(work,folder/f'effective_{set_id}_{n:03}.json',rev,parent);parent=rev
        if is_ip:
            profile={'pin_pairs':[{'lef_path':'lef/core.lef','liberty_path':'lib/core.lib'}]}
            (plans/f'v3_profile_{library}.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2))
            status=run_v3_ip(work,runs,vendor=vendor,library=library,set_id=set_id,profile=profile)
            if status['state']!='SUCCEEDED':raise ValueError(f'{vendor}/{library}: 检查运行不完整: {status}')
            reports.append({'vendor':vendor,'library':library,'set_id':set_id,'status':status})
    summary={'simulated':True,'vendors':3,'libraries':5,'deliveries':20,'effective_revisions':20,
             'business_ips':3,'reports':reports,'note':'V04 Liberty 故意增加 B 引脚，用于验证质量 FAIL 与执行成功的区别。'}
    (root/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    (root/'README.md').write_text('此目录全部是模拟数据。V04 故意让 Liberty 多出 B 引脚；检查执行成功不代表质量通过。GDS/Verilog 为占位文件，仅作为来源，不作内容检查。\n',encoding='utf-8')
    print(json.dumps({'root':str(root),'vendors':3,'libraries':5,'deliveries':20,'effective_revisions':20,
                      'business_ips':3,'report_runs':[x['status']['id'] for x in reports]},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
