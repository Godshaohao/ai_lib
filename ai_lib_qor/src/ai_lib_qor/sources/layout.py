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


def storage_dir(folder, name):
    if name not in ('delivery','formal','effective','log','facts'):raise ValueError('目录类别无效')
    path=Path(folder)/name
    if path.is_symlink():raise ValueError('存储目录不能为软链接')
    path.mkdir(parents=True,exist_ok=True)
    return path


def archive_files(folder, name, pattern):
    folder=Path(folder);directory=folder/name
    if directory.is_symlink():raise ValueError('存储目录不能为软链接')
    return sorted([*folder.glob(pattern),*directory.glob(pattern)])


def log_file(folder, name):
    old=Path(folder)/name
    return old if old.exists() else storage_dir(folder,'log')/name


def evidence_path(delivery_path):
    path=Path(delivery_path)
    if path.name=='delivery.json' or path.parent.name=='deliveries':return path.parent/'source_evidence.json'
    return path.with_name('evidence_'+path.stem+'.json')


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
