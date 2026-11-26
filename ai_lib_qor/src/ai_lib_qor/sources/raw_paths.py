"""Read-only source path resolution and RAW observations."""
import csv
from os import PathLike
from pathlib import Path


def source_directories(value):
    if not value:
        return ()
    values = [value] if isinstance(value, (str, PathLike)) else value
    if not isinstance(values, (list, tuple)) or any(not isinstance(x, (str, PathLike)) or not x for x in values):
        raise ValueError('RAW 根目录必须为路径或路径数组')
    roots = tuple(dict.fromkeys(Path(x).expanduser().resolve(strict=True) for x in values))
    if any(not root.is_dir() for root in roots):
        raise ValueError('RAW 根路径必须是目录')
    return roots


def resolve_source(path, roots):
    try:
        real = path.resolve(strict=True)
    except RuntimeError as exc:
        raise ValueError(f'来源链接循环: {path}') from exc
    if not any(real.is_relative_to(root) for root in roots):
        raise ValueError(f'来源链接超出允许目录: {path} → {real}')
    return real


def read_raw_observations(folder):
    root_path = folder / 'raw_observations.tsv'
    observation = root_path if root_path.exists() or root_path.is_symlink() else folder / 'log/raw_observations.tsv'
    if observation.is_symlink() or observation.parent.is_symlink():
        raise ValueError('RAW 观察记录不能为软链接')
    records = {}
    if observation.is_file():
        with observation.open(encoding='utf-8', newline='') as stream:
            for row in csv.reader(stream, delimiter='\t'):
                if len(row) not in (5, 6):
                    raise ValueError('RAW 观察记录格式无效')
                records.setdefault((row[0], row[1]), (int(row[2]), int(row[3]), row[5] if len(row) == 6 else None))
    return records


def observed_raw_file(root, rel, absolute, record):
    if absolute != Path(root) / rel:
        raise ValueError('RAW 文件路径与交付不一致')
    try:
        real = absolute.resolve(strict=True)
    except RuntimeError as exc:
        raise ValueError(f'RAW 文件链接循环: {absolute}') from exc
    recorded_target = record[2] if record and len(record) == 3 else None
    expected = Path(recorded_target) if recorded_target else absolute
    if real != expected or not real.is_file():
        raise ValueError('RAW 文件不存在、越界或链接目标与归档不一致')
    if record is not None:
        stat = real.stat()
        if (stat.st_size, stat.st_mtime_ns) != record[:2]:
            raise ValueError('RAW 文件相对首次观察已变化，不能当作历史文件解析')
    return real
