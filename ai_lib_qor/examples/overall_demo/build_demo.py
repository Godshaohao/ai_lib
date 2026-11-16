"""Create a self-contained synthetic RAW / formal / v3 work fixture once.

Run from any directory with PYTHONPATH=<project>/src. Never points at production RAW.
"""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from ai_lib_qor.facts.parsers import parse_delivery_file

ROOT = Path(__file__).resolve().parents[2]
DEST = Path(__file__).resolve().parent/'dataset'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def main():
    DEST.mkdir(exist_ok=False)
    work=DEST/'work';shutil.copytree(ROOT/'examples/work',work)
    raw=DEST/'RAW'
    for version,size,ports,corners in [('V07',120,('A','B'),('tt','ff')),('V08',124,('A','B','C'),('tt',))]:
        base=raw/version;(base/'lef').mkdir(parents=True);(base/'lib').mkdir()
        pins=''.join(f' PIN {pin}\n DIRECTION {"OUTPUT" if pin == "B" else "INPUT"} ;\n END {pin}\n' for pin in ports)
        (base/'lef/core.lef').write_text(f'MACRO MAC_A\n SIZE {size} BY 80 ;\n{pins}END MAC_A\n',encoding='utf-8')
        for corner in corners:
            lpins=' '.join(f'pin({pin}) {{ direction : {"output" if pin == "B" else "input"}; }}' for pin in ports)
            (base/f'lib/func_{corner}.lib').write_text(f'library({corner}) {{ cell(MAC_A) {{ {lpins} }} }}\n',encoding='utf-8')
    lib=work/'vendors/vendor_orion/libraries/lib_rtavfs'
    deliveries=[]
    for did,version in [('dlv_20260907_001','V07'),('dlv_20261019_001','V08')]:
        path=lib/'deliveries'/did/'delivery.json';record=json.loads(path.read_text(encoding='utf-8'))
        record['source_root']=str((raw/version).resolve());path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');deliveries.append((path,record))
    facts={}
    for (path,record),version in zip(deliveries,('V07','V08')):
        for item in record['files']:
            out=DEST/'facts'/f'{version}_{item["file_id"]}.json'
            write(out,parse_delivery_file(record,item['file_id']));facts[(version,item['file_id'])]=str(out)
    snaps=[]
    for sid,is_updated in [('snap_nl253_0001',False),('snap_nl253_0002',True)]:
        path=work/'formal_nl/NL2.5.3/snapshots'/f'{sid}.json';snapshot=json.loads(path.read_text(encoding='utf-8'))
        formal=DEST/'formal'/sid;formal.mkdir(parents=True)
        for item in snapshot['linked_files']:
            relative=Path(item['link_path']);link=formal/relative;link.parent.mkdir(parents=True,exist_ok=True)
            version='V08' if is_updated and item['file_id']=='nf002' else 'V07'
            real=(raw/version/relative).resolve();link.symlink_to(real)
            item['resolved_path']=str(real)
        snapshot['source_root']=str(formal.resolve());path.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');snaps.append(path)
    effective=lib/'ips/rtavfs/effective'; rev1=effective/'versions/rev_0001.json';rev2=effective/'versions/rev_0002.json';index=effective/'index.json'
    common={'formal_snapshots':[str(snaps[0])], 'ruleset_id':'synthetic_lef_liberty_v1','run_at':datetime.now(timezone.utc).isoformat(), 'report_effective_index':str(index),'report_accepted_revision':str(rev1)}
    def pair(lef,corner,liberty):return {'lef_key':'lib_rtavfs:lef:core','liberty_key':f'lib_rtavfs:liberty:func_{corner}','lef_facts':lef,'liberty_facts':liberty}
    rev1_plan={**common,'target_revision':str(rev1),'run_id':'demo_rev_0001','comparisons':[], 'pin_pairs':[pair(facts[('V07','f001')],'tt',facts[('V07','f002')]),pair(facts[('V07','f001')],'ff',facts[('V07','f003')])], 'report_deliveries':[str(deliveries[0][0])], 'report_formal_snapshot':str(snaps[0])}
    rev2_plan={**common,'target_revision':str(rev2),'baseline_revision':str(rev1),'run_id':'demo_rev_0002','comparisons':[{'file_key':'lib_rtavfs:lef:core','old_facts':facts[('V07','f001')],'new_facts':facts[('V08','f001')]}], 'pin_pairs':[pair(facts[('V08','f001')],'tt',facts[('V08','f002')]),pair(facts[('V08','f001')],'ff',facts[('V07','f003')])], 'report_deliveries':[str(x[0]) for x in deliveries], 'report_formal_snapshot':str(snaps[1])}
    write(DEST/'plans/rev_0001.json',rev1_plan);write(DEST/'plans/rev_0002.json',rev2_plan)
    print('Synthetic dataset:',DEST)
    print('Plan directory:',DEST/'plans')
    print('Work directory:',work)

if __name__=='__main__':main()
