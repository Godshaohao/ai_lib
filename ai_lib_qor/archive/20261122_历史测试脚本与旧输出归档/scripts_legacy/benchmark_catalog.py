#!/usr/bin/env python3
"""Read-only existing dataset benchmark, or generate isolated synthetic records."""
import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path
from ai_lib_qor.application.library_catalog import LibraryCatalog
from ai_lib_qor.application.scans import observations, observation_index

PROJECT=Path(__file__).resolve().parents[1]


def generate(root):
    work=root/'work';runs=root/'runs';work.mkdir();scans=runs/'scans';scans.mkdir(parents=True)
    sample=json.loads((PROJECT/'examples/work/vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20260907_001/delivery.json').read_text())
    sources=[]
    for vendor in range(3):
        for library in range(5):
            v=f'Ve{vendor}'; lib=f'Li{library}'; raw=root/'raw'/v/lib
            source={'vendor_id':v,'source_library_id':lib,'root':str(raw)};sources.append(source)
            for version in range(1,21):
                record=json.loads(json.dumps(sample));record.update(vendor_id=v,source_library_id=lib,delivery_id=f'delivery_{version:03}',supplier_version=f'V{version:03}',delivery_order=version)
                record['source_root']=str(raw/f'V{version:03}')
                for item in record['files']:
                    if item['file_key']:item['file_key']=item['file_key'].replace('lib_rtavfs:',lib+':',1)
                record['package_scope']['file_keys']=[key.replace('lib_rtavfs:',lib+':',1) for key in record['package_scope']['file_keys']]
                path=work/'vendors'/v/'libraries'/lib/'deliveries'/record['delivery_id']/'delivery.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(record),encoding='utf-8')
            for number in range(40):
                scan={'scan_id':f'scan_{vendor}_{library}_{number:03}',**source,'started_at':f'2026-01-01T00:{number:02}:00Z',
                      'finished_at':f'2026-01-01T00:{number:02}:01Z','status':'COMPLETE','files':[],'changes':None}
                (scans/(scan['scan_id']+'.json')).write_text(json.dumps(scan),encoding='utf-8')
    (work/'scan_sources.json').write_text(json.dumps({'sources':sources}),encoding='utf-8')
    return work,runs


def measure(work,runs,repeats):
    durations=[]
    for _ in range(repeats):
        t=time.perf_counter();catalog=LibraryCatalog(work,runs).refresh();overview=catalog.overview();durations.append(time.perf_counter()-t)
    t=time.perf_counter();reference=[observations(runs,s) for s in catalog.configured];legacy=time.perf_counter()-t
    t=time.perf_counter();index=observation_index(runs);bulk=time.perf_counter()-t
    matches=all(index.get((s['vendor_id'],s['source_library_id'],str(Path(s['root']).resolve())),[])==rows for s,rows in zip(catalog.configured,reference))
    return {'libraries':len(catalog.libraries),'vendors':len({x[0] for x in catalog.libraries}),
            'ips':len(catalog.entries),'deliveries':sum(len(x['deliveries']) for x in catalog.libraries.values()),
            'snapshots':len(catalog.snapshots),'scan_observations':sum(map(len,index.values())),
            'warnings':len(catalog.warnings),'catalog_refresh_overview_seconds':[round(x,4) for x in durations],
            'median_seconds':round(statistics.median(durations),4),'individual_history_seconds':round(legacy,4),
            'bulk_history_seconds':round(bulk,4),'histories_identical':matches,
            'note':'Warm filesystem, single process; JSON metadata reads only, no RAW content, no write to source.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work');parser.add_argument('--runs');parser.add_argument('--repeats',type=int,default=3)
    args=parser.parse_args()
    if bool(args.work)!=bool(args.runs) or args.repeats<1:parser.error('--work and --runs must be provided together; repeats >= 1')
    if args.work:
        work=Path(args.work);runs=Path(args.runs)
        if not work.is_dir():parser.error('work directory does not exist')
        result=measure(work,runs,args.repeats);result['dataset']='existing'
    else:
        with tempfile.TemporaryDirectory(prefix='ai_lib_catalog_benchmark_') as tmp:
            work,runs=generate(Path(tmp));result=measure(work,runs,args.repeats);result['dataset']='synthetic'
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['histories_identical'] and not result['warnings'] else 1


if __name__=='__main__':raise SystemExit(main())
