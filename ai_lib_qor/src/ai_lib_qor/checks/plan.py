"""Plan only unambiguous LEF/Liberty pairs from explicitly selected v3 facts."""
from ai_lib_qor.versions.store import validate


def pair_interfaces(inputs):
    keys = [x['file_key'] for x in inputs]
    if len(keys) != len(set(keys)): raise ValueError('自动配对文件位重复')
    lefs, libs = [], []
    for item in inputs:
        f = item['facts'];validate(f,'file_facts')
        if f['parse_status'] != 'COMPLETE': raise ValueError('自动配对要求完整的名称覆盖')
        if f['view'] == 'LEF':
            if 'MACRO_NAME' not in f['covered_sections'] or 'macros' not in f['objects']: raise ValueError('缺少 Macro 名称覆盖')
            names = [x['name'] for x in f['objects']['macros']]
            if not names or len(names) != len(set(names)): raise ValueError('Macro 名称为空或重复')
            lefs.append((item, set(names)))
        elif f['view'] == 'LIBERTY':
            if 'CELL_NAME' not in f['covered_sections'] or 'cells' not in f['objects']: raise ValueError('缺少 Cell 名称覆盖')
            names = [x['name'] for x in f['objects']['cells']]
            if not names or len(names) != len(set(names)): raise ValueError('Cell 名称为空或重复')
            libs.append((item, set(names)))
        else: raise ValueError('自动配对仅支持 LEF 和 Liberty')
    if not lefs or not libs: raise ValueError('自动配对需要 LEF 和 Liberty')
    owners={}
    for item,names in lefs:
        for name in names:
            if name in owners: raise ValueError('Macro 属于多个 LEF，无法唯一配对')
            owners[name]=item['file_key']
    pairs=[]
    for lib,names in libs:
        matched=False
        for lef,macros in lefs:
            if macros <= names:
                pairs.append({'lef_key':lef['file_key'],'liberty_key':lib['file_key'],'lef':lef['facts'],'liberty':lib['facts']});matched=True
        if not matched: raise ValueError('Liberty 未找到可完整匹配的 LEF')
    return pairs
