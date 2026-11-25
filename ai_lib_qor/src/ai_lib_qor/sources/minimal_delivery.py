"""Seven-field on-disk delivery schema helpers (directory_mtime), ordering, and legacy compatibility metadata."""
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath

DELIVERY_BASE_FIELDS = frozenset({'vendor', 'library', 'version', 'version_date', 'root', 'views'})
DELIVERY_FIELDS = DELIVERY_BASE_FIELDS | {'directory_mtime'}
LEGACY_DELIVERY_FIELDS = DELIVERY_BASE_FIELDS | {'directory_created_at'}


def is_delivery_minimal(data):
    """Return True if data matches canonical 7-field delivery (directory_mtime) or legacy 7-field archive (directory_created_at)."""
    if not isinstance(data, dict):
        return False
    keys = set(data)
    return keys == DELIVERY_FIELDS or keys == LEGACY_DELIVERY_FIELDS


def version_date(version):
    match=re.match(r'^(\d{8})(?:$|[_-])',version)
    if not match:return None
    try:return datetime.strptime(match.group(1),'%Y%m%d').date().isoformat()
    except ValueError:return None


def order_deliveries(records, times):
    """Order deliveries by date, registration time, directory mtime, and undated version name."""
    from .timestamps import instant
    from .source_discovery import natural_version_key
    if not isinstance(times, dict):
        raise ValueError('用户登记时间配置无效')
    rows = []
    dated_days = {}
    for item in records:
        version = item['version']
        value = item['version_date']
        if version in times:
            when = instant(times[version])
        elif item.get('directory_mtime'):
            when = instant(item['directory_mtime'])
        else:
            when = None
        if value:
            try:
                day = date.fromisoformat(value)
                if day.isoformat() != value or version_date(version) != value:
                    raise ValueError('版本顺序日期与版本名不一致')
            except (TypeError, ValueError):
                raise ValueError('版本顺序日期无效') from None
            known = dated_days.setdefault(day, set())
            if known and (when is None or None in known or when in known):
                raise ValueError('版本顺序未确认：同日记录无法比较')
            known.add(when)
        elif when is not None:
            day = when.date()
        else:
            day = date.min
        rows.append((day, when or datetime.min.replace(tzinfo=timezone.utc), natural_version_key(version), version, item))
    rows.sort(key=lambda row: row[:4])
    return [row[-1] for row in rows]


def directory_mtime(path):
    """Return directory modification time (st_mtime) in UTC ISO-8601 seconds, or None if unreadable."""
    try:
        value = Path(path).stat().st_mtime
        if value is not None:
            from .timestamps import utc_text
            return utc_text(datetime.fromtimestamp(value, timezone.utc))
    except (OSError, ValueError, OverflowError):
        pass
    return None


def simplify(record, *, mtime=None):
    views={}
    for row in record['files']:
        view=row['view'];name=row['relative_path'].lower().removesuffix('.gz')
        if view=='CDL' and name.endswith(('.spice','.sp')):view='SPICE'
        views.setdefault(view,[]).append(row['relative_path'])
    return {'vendor':record['vendor_id'],'library':record['source_library_id'],
            'version':record['supplier_version'],'version_date':version_date(record['supplier_version']),
            'directory_mtime':mtime,'root':record['source_root'],
            'views':{key:sorted(value) for key,value in sorted(views.items())}}


def compatibility(record):
    return {'metadata':{k:v for k,v in record.items() if k!='files'},'file_order':[row['relative_path'] for row in record['files']],
            'files':{row['relative_path']:{k:v for k,v in row.items() if k!='relative_path'} for row in record['files']}}


def expand(data,evidence):
    from ai_lib_qor.versions.store import validate
    validate(data,'delivery_minimal')
    if data['version_date']!=version_date(data['version']):raise ValueError('版本日期与版本名称不一致')
    if not Path(data['root']).is_absolute():raise ValueError('来源根目录必须是绝对路径')
    compat=evidence.get('legacy_compatibility') if isinstance(evidence,dict) else None
    if not isinstance(compat,dict):raise ValueError('简化交付缺少来源标识映射，无法安全读取历史引用')
    record=dict(compat.get('metadata') or {}); files=compat.get('files') or {};rows=[];seen=set()
    if (record.get('vendor_id'),record.get('source_library_id'),record.get('supplier_version'),record.get('source_root')) != (data['vendor'],data['library'],data['version'],data['root']):
        raise ValueError('简化交付与来源标识映射不一致')
    for view,paths in data['views'].items():
        for path in paths:
            p=PurePosixPath(path)
            if not path or p.is_absolute() or '\\' in path or any(part in ('','.','..') for part in path.split('/')) or path in seen:raise ValueError('交付路径无效或重复')
            seen.add(path)
            if path not in files:raise ValueError('简化交付缺少文件身份映射')
            stored=files[path]
            original_view=stored.get('view',view)
            if (original_view!=view and not (original_view=='CDL' and view=='SPICE' and path.lower().removesuffix('.gz').endswith(('.spice','.sp')))):
                raise ValueError('交付 View 与来源映射不一致')
            rows.append({**stored,'relative_path':path,'view':original_view})
    if seen!=set(files):raise ValueError('交付文件与来源身份映射不一致')
    order=compat.get('file_order')
    if not isinstance(order,list) or len(order)!=len(seen) or set(order)!=seen:raise ValueError('来源文件顺序映射无效')
    by_path={row['relative_path']:row for row in rows}
    record['files']=[by_path[path] for path in order]
    validate(record,'delivery_record')
    return record


def migrate_library(work,vendor,library):
    """Convert flat archived deliveries in place, preserving referenced identities."""
    from ai_lib_qor.sources.layout import library_folder,evidence_path
    from ai_lib_qor.versions.store import locked,write_atomic,validate
    folder=library_folder(work,vendor,library)
    if not folder.is_dir():raise ValueError('库目录不存在')
    converted=0;unchanged=0
    with locked(folder):
        pending=[]
        for path in sorted(folder.glob('delivery_*.json')):
            if path.is_symlink() or not path.is_file():raise ValueError('交付文件不可用或为软链接')
            data=json.loads(path.read_text(encoding='utf-8'))
            ep=evidence_path(path)
            if ep.is_symlink():raise ValueError('来源映射不可为软链接')
            evidence=json.loads(ep.read_text(encoding='utf-8')) if ep.exists() else {}
            if not isinstance(evidence,dict):raise ValueError('来源证据不是对象')
            if is_delivery_minimal(data):
                expand(data,evidence);unchanged+=1;continue
            validate(data,'delivery_record')
            if (data['vendor_id'],data['source_library_id'])!=(vendor,library):raise ValueError('交付不属于指定库')
            compat=compatibility(data)
            if 'legacy_compatibility' in evidence and evidence['legacy_compatibility']!=compat:raise ValueError('已有来源映射冲突')
            new_evidence={**evidence,'legacy_compatibility':compat}
            new=simplify(data)  # historical directory mtime was not recorded
            if expand(new,new_evidence)!=data:raise ValueError('转换将改变旧交付语义')
            pending.append((path,ep,new,new_evidence))
        for path,ep,new,evidence in pending:
            write_atomic(ep,evidence)
            write_atomic(path,new)
            converted+=1
    return {'vendor':vendor,'library':library,'converted':converted,'unchanged':unchanged}
