"""Rebuildable, read-only catalog of saved v3 records and observations."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import re

from .catalog import load_catalog, file_rows, member_rows
from .source_repository import SourceRepository
from .projections import build_file_matrix, result_matches
from .runs import history
from .scans import sources, observations, observation_index, ingest_result
from ai_lib_qor.sources.formal_sync import formal_sources, formal_history_index
from ai_lib_qor.versions.store import read_json


class LibraryCatalog:
    def __init__(self, work, runs):
        self.work = Path(work) if work else None
        self.runs = Path(runs)

    def refresh(self):
        """Read saved records only; never scan, parse, or write business data."""
        # Scoped to this refresh: no cross-request cache or stale-record assumptions.
        records={}
        def read_once(path,schema):
            key=(Path(path),schema)
            if key not in records: records[key]=read_json(path,schema)
            return records[key]
        all_entries, self.snapshots, self.warnings = load_catalog(self.work,reader=read_once)
        self.entries=[e for e in all_entries if e['index']['owner']['owner_type']=='BUSINESS_IP']
        library_sets=[e for e in all_entries if e['index']['owner']['owner_type']=='SOURCE_LIBRARY']
        self.configured = sources(self.work)
        self.formal_configured = formal_sources(self.work)
        self.libraries = {}
        for source in self.configured:
            self.libraries[(source['vendor_id'],source['source_library_id'])] = {'source':source,'deliveries':[],'ips':[]}
        for entry in self.entries:
            key=(entry['vendor'],entry['library'])
            self.libraries.setdefault(key,{'source':None,'deliveries':[],'ips':[]})['ips'].append(entry)
        for entry in library_sets:
            key=(entry['vendor'],entry['library'])
            self.libraries.setdefault(key,{'source':None,'deliveries':[],'ips':[]}).setdefault('effective_sets',[]).append(entry)
        if self.work:
            root=self.work.resolve()
            for item in SourceRepository(root,reader=read_once,warnings=[]).deliveries():
                record=item['record'];vendor=record['vendor_id'];library=record['source_library_id']
                self.libraries.setdefault((vendor,library),{'source':None,'deliveries':[],'ips':[]})['deliveries'].append(record)
        self.deliveries_by_ref=defaultdict(list)
        for (vendor,library),data in self.libraries.items():
            data['deliveries'].sort(key=lambda d:d['delivery_order'],reverse=True)
            for d in data['deliveries']:
                for f in d['files']:
                    self.deliveries_by_ref[(library,d['delivery_id'],f['file_id'])].append((vendor,library,d,f))
        self.owners=defaultdict(set)
        for e in self.entries:
            for rev in e['versions']:
                for member in rev['members']:
                    ref=member['source_ref']
                    if ref['kind']=='delivery_file':
                        key=('raw',ref['source_library_id'],ref['delivery_id'],ref['file_id'])
                    else:
                        key=('formal',ref['formal_nl_id'],ref['formal_snapshot_id'],ref['file_id'])
                    self.owners[key].add((e['vendor'],e['library'],e['ip']))
        return self

    def overview(self):
        rows=[]; scan_rows=[]
        scan_history=observation_index(self.runs)
        formal_history=formal_history_index(self.runs)
        for (vendor,library),data in sorted(self.libraries.items()):
            source=data['source']; hist=scan_history.get((vendor,library,str(Path(source['root']).resolve())),[]) if source else []
            latest=hist[0] if hist else None
            changing=next((r for r in hist if r.get('changes') and any(r['changes'][k] for k in ('added','changed','removed'))),None)
            rows.append({'vendor':vendor,'library':library,'configured':bool(source),'last_attempt':latest,
                'last_success':next((r for r in hist if r['status']=='COMPLETE'),None),'last_change':changing,
                'ingest':ingest_result(self.runs,latest),'delivery_count':len(data['deliveries']),'ip_count':len(data['ips'])})
            if source:
                scan_rows.append({'source':source,'observations':hist,'candidate_dirs':[],
                    'last_success':next((r for r in hist if r['status']=='COMPLETE'),None),
                    'deliveries':data['deliveries'],'ingest':ingest_result(self.runs,latest)})
        configs={x['formal_nl_id']:x for x in self.formal_configured}
        ids=set(configs)|{s['formal_nl_id'] for s in self.snapshots}
        formal=[]; formal_observations=[]
        for ident in sorted(ids):
            hist=formal_history.get((ident,str(Path(configs[ident]['root']).resolve())),[]) if ident in configs else []
            latest=hist[0] if hist else None
            if ident in configs:
                obs_groups={}; unmatched=[]
                for item in latest.get('files',[]) if latest else []:
                    source=item.get('source')
                    if source: obs_groups.setdefault((source['vendor'],source['library']),[]).append(item)
                    else: unmatched.append(item)
                formal_observations.append({'source':configs[ident],'observations':hist,
                    'last_success':next((r for r in hist if r['status']=='COMPLETE'),None),
                    'groups':obs_groups,'unmatched':unmatched})
            details=self.formal_detail(ident)
            groups=defaultdict(list)
            latest_per_library={}
            for link in details['links']:
                owner=(link['vendor'],link['library'])
                if link['vendor'] and owner not in latest_per_library: latest_per_library[owner]=link['snapshot_id']
            for link in details['links']:
                owner=(link['vendor'],link['library'])
                if link['vendor'] and latest_per_library[owner] != link['snapshot_id']: continue
                if not link['vendor'] and link['snapshot_position'] != 0: continue
                label=', '.join(link['ips']) if link['ips'] else '归属未知'
                groups[(link['vendor'] or '来源未匹配',link['library'] or '未知源库',label)].append(link)
            formal.append({'id':ident,'configured':ident in configs,'last_attempt':latest,
                'last_success':next((r for r in hist if r['status']=='COMPLETE'),None),
                'last_change':next((r for r in hist if r.get('changes') and any(r['changes'][k] for k in ('added','changed','removed'))),None),
                'groups':[{'vendor':k[0],'library':k[1],'ip':k[2],'files':v} for k,v in sorted(groups.items())],
                'snapshot_count':len(details['snapshots'])})
        return {'raw_rows':rows,'formal_rows':formal,'scan_rows':scan_rows,'formal_observation_rows':formal_observations,
                'ip_total':len(self.entries),'warnings':self.warnings,'work_enabled':bool(self.work)}

    def library_detail(self,vendor,library):
        data=self.libraries.get((vendor,library))
        if data is None:return None
        source=data['source']; hist=observations(self.runs,source) if source else []
        latest=hist[0] if hist else None; ingest=ingest_result(self.runs,latest);classified=[]
        if latest and re.fullmatch(r'scan_[0-9a-f]{32}',latest.get('scan_id','')):
            path=self.runs/'classified'/f"{latest['scan_id']}.json"
            try:
                if path.is_file() and not path.is_symlink():
                    item=json.loads(path.read_text(encoding='utf-8'))
                    if item.get('scan_id')==latest['scan_id'] and isinstance(item.get('files'),list):classified=item['files']
            except (OSError,ValueError,TypeError): pass
        if not classified and ingest and isinstance(ingest.get('classified'),list):classified=ingest['classified']
        if not classified and latest and latest.get('status')=='COMPLETE':
            classified=[{'path':f['path'],'view':'未知','file_key':None,'classification':'UNKNOWN','reason':'历史扫描未保存分类'} for f in latest.get('files',[])]
        formal_links=[]
        for ident in sorted({s['formal_nl_id'] for s in self.snapshots}):
            detail=self.formal_detail(ident)
            if not detail['snapshots']:continue
            library_links=[link for link in detail['links'] if (link['vendor'],link['library'])==(vendor,library)]
            latest_id=library_links[0]['snapshot_id'] if library_links else None
            for link in library_links:
                if link['snapshot_id']==latest_id:
                    formal_links.append({'nl':ident,'path':link['link_path'],'target':link['resolved_path'],
                        'source':{'version':link['raw_version'],'delivery_id':link['delivery_id'],'file_key':link['file_key']}})
        return {**data,'effective_sets':data.get('effective_sets',[]),'latest':latest,'ingest':ingest,'file_rows':file_rows(data['deliveries']),
                'formal_links':formal_links,'warnings':self.warnings,'classified':classified}

    def formal_detail(self,nl_id):
        snapshots=sorted((s for s in self.snapshots if s['formal_nl_id']==nl_id),key=lambda s:s['observed_at'],reverse=True)
        links=[]
        counts=Counter(s['formal_snapshot_id'] for s in snapshots)
        for snapshot_position,snap in enumerate(snapshots):
            for f in snap['linked_files']:
                ref=f.get('source_ref'); found=[]
                if ref and ref.get('kind')=='delivery_file':
                    found=[x for x in self.deliveries_by_ref.get((ref['source_library_id'],ref['delivery_id'],ref['file_id']),[]) if x[3].get('file_key')==f.get('file_key')]
                duplicate=counts[snap['formal_snapshot_id']]>1
                match=found[0] if len(found)==1 and not duplicate else None
                owners=set(self.owners.get(('formal',nl_id,snap['formal_snapshot_id'],f['file_id']),set()))
                if duplicate: owners=set()
                if match:
                    owners.update(x for x in self.owners.get(('raw',ref['source_library_id'],ref['delivery_id'],ref['file_id']),set()) if x[:2]==match[:2])
                links.append({'snapshot_id':snap['formal_snapshot_id'],'snapshot_position':snapshot_position,'file_id':f['file_id'],'file_key':f.get('file_key'),
                    'link_path':f['link_path'],'resolved_path':f.get('resolved_path'),'source_match':f['source_match'],
                    'vendor':match[0] if match else None,'library':match[1] if match else None,
                    'raw_version':match[2]['supplier_version'] if match else None,'delivery_id':ref.get('delivery_id') if ref else None,
                    'ips':sorted({o[2] for o in owners if not match or o[:2]==match[:2]}),
                    'resolution':'AMBIGUOUS_SNAPSHOT' if duplicate else 'RESOLVED' if match else 'AMBIGUOUS' if len(found)>1 else 'UNKNOWN'})
        return {'nl_id':nl_id,'snapshots':snapshots,'links':links}

    def ip_detail(self,vendor,library,ip,revision_id=None,baseline_id=None,run=None,formal_snapshot=None):
        selected=next((e for e in self.entries if (e['vendor'],e['library'],e['ip'])==(vendor,library,ip)),None)
        if not selected:return None
        versions=selected['versions'];revision_id=revision_id or selected['index']['latest_calculated_revision']
        revision=next((r for r in versions if r['revision_id']==revision_id),None)
        baseline_id=baseline_id or (revision.get('parent_revision_id') if revision else None)
        baseline=next((r for r in versions if r['revision_id']==baseline_id),None)
        selected_runs=[r for r in history(self.runs) if r.get('owner')=={'vendor':vendor,'library':library,'ip':ip}]
        if revision and (not baseline_id or baseline):
            from ai_lib_qor.checks.evidence import validate_check_result
            for item in selected_runs:
                if run is not None: break
                if item.get('state')!='SUCCEEDED' or not re.fullmatch(r'run_[0-9a-f]{32}',item.get('id','')): continue
                if (item.get('expected_revision') or item.get('target'))!=revision['revision_id']:continue
                folder=self.runs/item['id']; check_path=folder/'check.json'; plan_path=folder/'input_plan.json'
                if any(p.is_symlink() or not p.is_file() for p in (check_path,plan_path)):continue
                try:
                    result=read_json(check_path,'check_result');validate_check_result(result)
                    plan=json.loads(plan_path.read_text(encoding='utf-8'))
                    if read_json(plan['target_revision'],'effective_version')!=revision:continue
                    plan_base=read_json(plan['baseline_revision'],'effective_version') if plan.get('baseline_revision') else None
                    if plan_base!=baseline or result['check_run_id']!=item['id'] or not result_matches(result,revision,baseline):continue
                    run=result
                except (OSError,ValueError,KeyError,TypeError):continue
        # Include other libraries only when their fixed identifiers resolve uniquely.
        deliveries=[d for data in self.libraries.values() for d in data['deliveries']]
        return {'entry':selected,'revision':revision,'baseline':baseline,'members':member_rows(revision,deliveries,self.snapshots),
                'runs':selected_runs,'matching_result':run,
                'matrix':build_file_matrix(revision,baseline,deliveries,self.snapshots,run,home_library=library,formal_snapshot=formal_snapshot)}
