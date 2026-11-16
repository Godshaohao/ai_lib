"""Generate a fresh synthetic multi-vendor fixture; never overwrite existing data."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from ai_lib_qor.sources.delivery_builder import build_delivery
from ai_lib_qor.facts.parsers import parse_delivery_file
from ai_lib_qor.versions.store import write_atomic
from ai_lib_qor.versions.__main__ import parser as version_parser, run as version_run


def main(destination):
    dest=Path(destination).resolve();dest.mkdir(parents=True,exist_ok=False)
    work=dest/'work';plans=dest/'plans';plans.mkdir();raw=dest/'RAW'; facts_dir=dest/'facts'
    items=[('vendor_a','lib_a','ip_a'),('vendor_a','lib_b','ip_b'),('vendor_b','lib_c','ip_c'),('vendor_b','lib_d',None),('vendor_c','lib_e',None)]
    sources=[];stats={'vendors':3,'libraries':5,'deliveries':0,'business_ips':0,'effective_versions':0}
    for vendor,library,ip in items:
        libraw=raw/vendor/library;sources.append({'vendor_id':vendor,'source_library_id':library,'root':str(libraw)})
        effective=work/'vendors'/vendor/'libraries'/library/'ips'/str(ip)/'effective'
        previous_facts=None;delivery_paths=[]
        for n in range(1,5):
            version=f'V{n:02d}';base=libraw/version;base.mkdir(parents=True)
            (base/'core.lef').write_text(f'MACRO MAC_A\n SIZE {100+n} BY 80 ;\n PIN A\n DIRECTION INPUT ;\n END A\n END MAC_A\n')
            (base/'tt.lib').write_text('library(tt) { cell(MAC_A) { pin(A) { direction : input; } } }\n')
            delivery_id=f'delivery_{n:02d}';mapping={'core.lef':{'file_key':f'{library}:lef:core'},'tt.lib':{'file_key':f'{library}:liberty:tt','corner':'tt'}}
            meta={'delivery_id':delivery_id,'vendor_id':vendor,'source_library_id':library,'supplier_version':version,'delivery_order':n,'received_at':datetime.now(timezone.utc).isoformat(),'package_mode':'FULL','scope_confirmed':True}
            rec=build_delivery(base,meta,mapping);dp=work/'vendors'/vendor/'libraries'/library/'deliveries'/delivery_id/'delivery.json';write_atomic(dp,rec,immutable=True);delivery_paths.append(str(dp));stats['deliveries']+=1
            if not ip:continue
            if n==1:
                args=['init','--effective-dir',str(effective),'--delivery',str(dp),'--set-id',f'{ip}_set','--owner-id',ip,'--home-library',library,'--owner-type','BUSINESS_IP'];stats['business_ips']+=1
            else:args=['apply','--effective-dir',str(effective),'--delivery',str(dp)]
            revision=version_run(version_parser().parse_args(args))['revision_id'];stats['effective_versions']+=1
            current={}
            for f in rec['files']:
                fact=parse_delivery_file(rec,f['file_id']);path=facts_dir/vendor/library/version/(f['file_id']+'.json');write_atomic(path,fact,immutable=True);current[f['view']]=str(path)
            plan={'run_id':'fixture','run_at':datetime.now(timezone.utc).isoformat(),'ruleset_id':'synthetic_lef_liberty_v1','target_revision':str(effective/'versions'/f'{revision}.json'),'report_deliveries':delivery_paths.copy(),'comparisons':[],'pin_pairs':[{'lef_key':f'{library}:lef:core','liberty_key':f'{library}:liberty:tt','lef_facts':current['LEF'],'liberty_facts':current['LIBERTY']}]}
            if previous_facts:
                plan['baseline_revision']=str(effective/'versions'/f'rev_{n-1:04d}.json');plan['comparisons']=[{'file_key':f'{library}:lef:core','old_facts':previous_facts['LEF'],'new_facts':current['LEF']}]
            write_atomic(plans/f'{vendor}_{library}_{revision}.json',plan,immutable=True);previous_facts=current
    write_atomic(work/'scan_sources.json',{'sources':sources},immutable=True)
    write_atomic(dest/'manifest.json',{'simulation':True,**stats},immutable=True)
    print(json.dumps(stats,ensure_ascii=False))

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('用法: python examples/build_scale_synthetic.py <不存在的目标目录>')
    main(sys.argv[1])
