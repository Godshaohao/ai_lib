"""Compare only explicitly covered LEF macro size and pin presence facts."""


def _unique(records,label):
    result={}
    for item in records:
        if item['name'] in result:raise ValueError(f'重复 {label}: {item["name"]}')
        result[item['name']]=item
    return result


def compare(old,new):
    required={'MACRO_NAME','MACRO_SIZE','PIN_NAME','PIN_DIRECTION'}
    if any(f['view']!='LEF' or f['parse_status']!='COMPLETE' or not required.issubset(f['covered_sections']) for f in (old,new)):
        return None
    a=_unique(old['objects']['macros'],'Macro');b=_unique(new['objects']['macros'],'Macro');result=[]
    if old['units'].get('distance')!='um' or new['units'].get('distance')!='um': return None
    def add(typ,name,attr,x,y,unit):
        result.append({'object_type':typ,'object_name':name,'attribute':attr,'old_value':x,'new_value':y,'unit':unit,'facts_refs':[old['facts_id'],new['facts_id']]})
    for name in sorted(set(a)^set(b)):add('MACRO',name,'PRESENCE',name in a,name in b,None)
    for name in sorted(set(a)&set(b)):
        if a[name]['size_um']!=b[name]['size_um']: add('MACRO',name,'SIZE',a[name]['size_um'],b[name]['size_um'],'um')
        ap=_unique(a[name]['pins'],'Pin');bp=_unique(b[name]['pins'],'Pin')
        for pin in sorted(set(ap)^set(bp)):add('PIN',name+'/'+pin,'PRESENCE',pin in ap,pin in bp,None)
        for pin in sorted(set(ap)&set(bp)):
            if ap[pin]['direction'].upper()!=bp[pin]['direction'].upper():add('PIN',name+'/'+pin,'DIRECTION',ap[pin]['direction'],bp[pin]['direction'],None)
    return result
