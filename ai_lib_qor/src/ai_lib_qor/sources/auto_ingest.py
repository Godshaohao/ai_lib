"""Publish conservative delivery records for explicitly configured version roots."""
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from ai_lib_qor.sources.classifier_adapter import classify_observation
from ai_lib_qor.sources.delivery_builder import build_delivery
from ai_lib_qor.sources.update_scan import scan_library
from ai_lib_qor.versions.store import locked, read_json, write_atomic
from ai_lib_qor.workbench.registration import SAFE


def auto_ingest(work, source, scan):
    vendor, library = source['vendor_id'], source['source_library_id']
    if not all(SAFE.fullmatch(v) and v not in ('.','..') for v in (vendor, library)):
        raise ValueError('来源标识不安全')
    raw=Path(source['root']).resolve(strict=True); work=Path(work).resolve(strict=True)
    if work.is_relative_to(raw): raise ValueError('工作目录不能位于 RAW 内')
    if (scan.get('root'), scan.get('vendor_id'), scan.get('source_library_id')) != (str(raw),vendor,library):
        raise ValueError('扫描与配置不匹配')
    classified=classify_observation(scan,source)
    result={'created':0,'duplicates':0,'modified':0,'blocked':0,'files':len(classified['files']),'reasons':[]}
    parts=[work/'vendors',work/'vendors'/vendor,work/'vendors'/vendor/'libraries',work/'vendors'/vendor/'libraries'/library]
    if any(p.is_symlink() for p in parts): raise ValueError('工作目录包含符号链接')
    parent=parts[-1]/'deliveries'
    if parent.is_symlink() or not parent.resolve().is_relative_to(work): raise ValueError('交付目录越界')
    with locked(parent):
        existing=[]
        for path in parent.glob('*/delivery.json'):
            if path.is_symlink() or path.parent.is_symlink(): continue
            item=read_json(path,'delivery_record')
            evidence_path=path.parent/'source_evidence.json'
            evidence=json.loads(evidence_path.read_text()) if evidence_path.is_file() and not evidence_path.is_symlink() else {}
            existing.append((item,evidence))
        for version, relative in source.get('version_paths',{}).items():
            if not SAFE.fullmatch(version) or version in ('.','..'):
                result['blocked']+=1;result['reasons'].append('版本标识不安全');continue
            candidate=raw/relative
            path_parts=Path(relative).parts
            has_link=any(raw.joinpath(*path_parts[:i]).is_symlink() for i in range(1,len(path_parts)+1))
            if has_link or not candidate.resolve().is_relative_to(raw) or not candidate.is_dir():
                result['blocked']+=1;result['reasons'].append(f'{version}: 版本目录不可用');continue
            rows=[x for x in classified['files'] if x['supplier_version']==version]
            if not rows:
                result['blocked']+=1;result['reasons'].append(f'{version}: 无可确认文件');continue
            prefix=Path(relative).as_posix().rstrip('/')+'/'
            expected={x['path'][len(prefix):]:(x['size'],x['mtime_ns']) for x in rows}
            prior=[(a,b) for a,b in existing if a['supplier_version']==version and a['source_root']==str(candidate.resolve())]
            if prior:
                old=prior[0][1].get('files')
                old_data={x['path']:(x['size'],x['mtime_ns']) for x in old} if old is not None else None
                if old_data == expected: result['duplicates']+=1
                else:
                    result['modified']+=1;result['reasons'].append(f'{version}: 已归档来源发生变化或历史证据缺失')
                continue
            def observed():
                current=scan_library(candidate,vendor,library,metadata_only=True)
                return current, {x['path']:(x['size'],x['mtime_ns']) for x in current['files']}
            current, before=observed()
            if current['status']!='COMPLETE' or expected!=before:
                result['blocked']+=1;result['reasons'].append(f'{version}: 扫描后文件变化或范围不完整');continue
            mapping={x['path'][len(prefix):]:{'file_key':x['file_key'],'view':x['view']} for x in rows}
            delivery_id='delivery_'+uuid.uuid4().hex
            metadata={'delivery_id':delivery_id,'vendor_id':vendor,'source_library_id':library,
                      'supplier_version':version,'delivery_order':max([a['delivery_order'] for a,_ in existing],default=0)+1,
                      'received_at':scan['finished_at'],'package_mode':'UNKNOWN','scope_confirmed':False}
            record=build_delivery(candidate,metadata,mapping)
            after_scan, after=observed()
            if after_scan['status']!='COMPLETE' or after!=before:
                result['blocked']+=1;result['reasons'].append(f'{version}: 发布前文件变化');continue
            temp=Path(tempfile.mkdtemp(prefix='.ingest-',dir=parent));target=parent/delivery_id
            try:
                evidence={'schema_version':'delivery_source_evidence.v1','scan_id':scan['scan_id'],'files':after_scan['files'],'order_basis':'system_receipt_order'}
                write_atomic(temp/'source_evidence.json',evidence,immutable=True)
                write_atomic(temp/'delivery.json',record,immutable=True)
                os.rename(temp,target)
            finally:
                if temp.exists(): shutil.rmtree(temp)
            existing.append((record,evidence));result['created']+=1
    return result
