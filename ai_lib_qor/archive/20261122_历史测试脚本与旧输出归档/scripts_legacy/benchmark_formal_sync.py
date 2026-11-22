#!/usr/bin/env python3
"""Reproducible isolated Formal NL benchmark; creates only temporary synthetic data."""
import argparse
import json
import os
import tempfile
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from ai_lib_qor.sources.delivery_builder import build_delivery
from ai_lib_qor.sources.formal_sync import sync_formal


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--libraries',type=int,default=30)
    parser.add_argument('--files-per-library',type=int,default=100)
    args=parser.parse_args()
    if args.libraries < 1 or args.files_per_library < 1:
        parser.error('counts must be positive')
    with tempfile.TemporaryDirectory(prefix='qor-formal-bench-') as tmp:
        root=Path(tmp); work=root/'work'; work.mkdir(); formal=root/'formal'; formal.mkdir()
        records=[]
        for i in range(args.libraries):
            name=f'lib_{i:04d}'; raw=root/name; raw.mkdir(); links=formal/name; links.mkdir()
            mapping={}
            for j in range(args.files_per_library):
                filename=f'f_{j:05d}.lef'; (raw/filename).write_text('LEF\n')
                (links/filename).symlink_to(raw/filename)
                mapping[filename]={'file_key':f'{name}:lef:{j:05d}'}
            meta={'delivery_id':f'd_{name}','vendor_id':'v','source_library_id':name,
                  'supplier_version':'v1','delivery_order':1,'received_at':'2026-11-18T00:00:00Z','package_mode':'UNKNOWN'}
            records.append(build_delivery(raw,meta,mapping))
        cfg={'formal_nl_id':'NL','root':str(formal)}
        actual_walk=os.walk
        def run():
            start=perf_counter()
            with patch('os.walk',wraps=actual_walk) as walk:
                result=sync_formal(root/'runs',cfg,records,work)
            counts={k:sum(x['action']==k for x in result['snapshots']) for k in ('CREATED','REUSED','NONE')}
            if result['status']!='COMPLETE' or walk.call_count!=1 or counts['NONE']:
                raise RuntimeError(f'同步失败或目录被重复盘点: {result}')
            return {'seconds':round(perf_counter()-start,3),'walks':walk.call_count,'actions':counts}
        initial=run(); unchanged=run()
        extra=root/'new'; extra.mkdir(); (extra/'replacement.lef').write_text('LEF changed\n')
        meta={'delivery_id':'d_new','vendor_id':'v','source_library_id':'lib_0000','supplier_version':'v2',
              'delivery_order':2,'received_at':'2026-11-18T00:00:00Z','package_mode':'UNKNOWN'}
        records.append(build_delivery(extra,meta,{'replacement.lef':{'file_key':'lib_0000:lef:00000'}}))
        link=formal/'lib_0000'/'f_00000.lef'; link.unlink(); link.symlink_to(extra/'replacement.lef')
        changed=run()
        if initial['actions']['CREATED']!=args.libraries or unchanged['actions']['REUSED']!=args.libraries or changed['actions']!={'CREATED':1,'REUSED':args.libraries-1,'NONE':0}:
            raise RuntimeError('结果与增量更新规则不一致')
        print(json.dumps({'libraries':args.libraries,'links':args.libraries*args.files_per_library,
                          'initial':initial,'unchanged':unchanged,'one_changed':changed},ensure_ascii=False,indent=2))


if __name__=='__main__': main()
