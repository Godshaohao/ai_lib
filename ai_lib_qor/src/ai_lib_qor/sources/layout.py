"""Safe flat library paths and v1 evidence sidecars."""
from pathlib import Path
import re

SAFE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')


def library_folder(work, vendor, library):
    if any(not isinstance(v,str) or not SAFE.fullmatch(v) or v in ('.','..') for v in (vendor,library)):
        raise ValueError('供应商或库标识不安全')
    root=Path(work).resolve(strict=True)
    folder=root/'libraries'/vendor/library
    if any(p.is_symlink() for p in [folder,*folder.parents] if p != root and p.is_relative_to(root)) or not folder.resolve().is_relative_to(root):
        raise ValueError('库目录越界或包含符号链接')
    return folder


def evidence_path(delivery_path):
    path=Path(delivery_path)
    if path.name=='delivery.json' or path.parent.name=='deliveries':return path.parent/'source_evidence.json'
    return path.with_name('evidence_'+path.stem+'.json')


def delivery_filename(delivery_id):
    if not isinstance(delivery_id,str) or not SAFE.fullmatch(delivery_id) or delivery_id in ('.','..'):
        raise ValueError('交付标识不安全')
    return (delivery_id if delivery_id.startswith('delivery_') else 'delivery_'+delivery_id)+'.json'


def next_filename(folder, prefix, *, with_evidence=False):
    """Caller holds the library lock; display sequence is not business order."""
    folder=Path(folder)
    if not isinstance(prefix,str) or not SAFE.fullmatch(prefix):raise ValueError('文件名前缀不安全')
    regex=re.compile(re.escape(prefix)+r'_(\d+)\.json\Z')
    numbers=[int(m.group(1)) for p in folder.glob(prefix+'_*.json') if (m:=regex.fullmatch(p.name))]
    number=max(numbers,default=0)+1
    while True:
        name=f'{prefix}_{number:03d}.json'; path=folder/name
        if not path.exists() and (not with_evidence or not evidence_path(path).exists()):return name
        number+=1


def formal_filename(nl, sid):
    if any(not isinstance(v,str) or not SAFE.fullmatch(v) or v in ('.','..') for v in (nl,sid)):
        raise ValueError('NL 或快照标识不安全')
    return f'formal_{nl}_{sid}.json'
