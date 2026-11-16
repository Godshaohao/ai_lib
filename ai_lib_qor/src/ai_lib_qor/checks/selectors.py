"""Read-only latest/previous file occurrences without inferring scan completeness."""
from ai_lib_qor.versions.store import validate


def latest_previous(deliveries,file_key,scan_coverage):
    if not file_key:raise ValueError('file_key 必须明确')
    if not deliveries:return {'status':'UNKNOWN_COVERAGE','latest':None,'previous':None}
    for delivery in deliveries:validate(delivery,'delivery_record')
    libs={d['source_library_id'] for d in deliveries}
    orders=[d['delivery_order'] for d in deliveries];ids=[d['delivery_id'] for d in deliveries]
    if len(libs)!=1 or len(set(orders))!=len(orders) or len(set(ids))!=len(ids):raise ValueError('交付库、身份或顺序不唯一')
    ordered=sorted(deliveries,key=lambda d:d['delivery_order'],reverse=True)
    observations=[]; uncertain=[]
    for i,d in enumerate(ordered):
        found=[f for f in d['files'] if f['file_key']==file_key and f['classification']=='RESOLVED']
        if len(found)>1:raise ValueError('同次交付中的文件位不唯一')
        if scan_coverage.get(d['delivery_id'])!='COMPLETE' or any(f['classification']=='UNRESOLVED' for f in d['files']):uncertain.append(i)
        if found:observations.append((i,{'delivery_id':d['delivery_id'],'delivery_order':d['delivery_order'],'file_id':found[0]['file_id'],'file_key':file_key}))
    last_index=observations[1][0] if len(observations)>1 else len(ordered)-1
    status='UNKNOWN_COVERAGE' if any(i<=last_index for i in uncertain) else 'CONFIRMED'
    return {'status':status,'latest':observations[0][1] if observations else None,'previous':observations[1][1] if len(observations)>1 else None}
