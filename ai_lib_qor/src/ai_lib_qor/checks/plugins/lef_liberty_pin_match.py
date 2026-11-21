"""Compare supported scalar signal pin names and directions for matched objects."""
from .lef_macro_diff import _unique


def compare(lef,liberty,lef_key,liberty_key):
    req={'PIN_NAME','PIN_DIRECTION'}
    check={'check_id':'LEF_LIBERTY_PIN_MATCH','scope_file_keys':[lef_key,liberty_key],'result':'INCONCLUSIVE','coverage':'UNKNOWN','facts_refs':[lef['facts_id'],liberty['facts_id']],'detail':'无法确认完整的引脚覆盖'}
    if lef['view']!='LEF' or liberty['view']!='LIBERTY':raise ValueError('检查需要 LEF 和 Liberty 事实')
    if any(f['parse_status']!='COMPLETE' or not required.issubset(f['covered_sections']) for f,required in ((lef,req|{'MACRO_NAME'}),(liberty,req|{'CELL_NAME'}))):
        check['coverage']='PARTIAL';return check
    macros=_unique(lef['objects']['macros'],'Macro');cells=_unique(liberty['objects']['cells'],'Cell')
    if not macros: check['detail']='LEF 没有可确认的 Macro';return check
    problems=[]
    for name,macro in sorted(macros.items()):
        if name not in cells:problems.append(f'{name}: Liberty 未找到 Cell');continue
        lp={x['name']:x['direction'].upper() for x in _unique(macro['pins'],'LEF Pin').values() if str(x.get('use') or '').upper() not in ('POWER','GROUND')}
        bp={x['name']:x['direction'].upper() for x in _unique(cells[name]['pins'],'Liberty Pin').values()}
        if not lp or not bp:
            check.update(result='INCONCLUSIVE',coverage='PARTIAL',detail=f'{name}: 未发现可核实的信号 Pin；不能判断一致')
            return check
        if lp!=bp:
            differences=[]
            missing=sorted(set(lp)-set(bp));extra=sorted(set(bp)-set(lp))
            direction=[f'{pin}({lp[pin]}→{bp[pin]})' for pin in sorted(set(lp)&set(bp)) if lp[pin]!=bp[pin]]
            if missing:differences.append('Liberty 缺少 '+', '.join(missing))
            if extra:differences.append('Liberty 多出 '+', '.join(extra))
            if direction:differences.append('方向不一致 '+', '.join(direction))
            problems.append(f'{name}: '+ '; '.join(differences))
    check.update(result='FAIL' if problems else 'PASS',coverage='COMPLETE',detail='; '.join(problems) if problems else '所选 Macro 的信号 Pin 名称和方向一致；未检查 PG Pin 或时序弧')
    return check
