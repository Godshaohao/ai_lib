"""Command-line adapter for effective version operations."""
import argparse
import json
import sys
from pathlib import Path
from .service import run_version


def parser():
    p = argparse.ArgumentParser(description='根据 v3 交付或正式快照维护有效版本和采纳事件')
    subs = p.add_subparsers(dest='command', required=True)
    def base(name):
        sub = subs.add_parser(name); sub.add_argument('--effective-dir', required=True, type=Path); return sub
    init = base('init'); source = init.add_mutually_exclusive_group(required=True)
    source.add_argument('--delivery', type=Path); source.add_argument('--snapshot', type=Path)
    for x in ('set-id', 'owner-id', 'home-library'): init.add_argument('--'+x, required=True)
    init.add_argument('--owner-type', required=True, choices=['BUSINESS_IP','SOURCE_LIBRARY'])
    init.add_argument('--file-key', action='append', help='仅选择已确认文件位作为初始有效成员')
    init.add_argument('--verify-files', action='store_true', help='显式验证 RAW 文件存在；默认只读取已归档 JSON')
    apply = base('apply'); apply.add_argument('--delivery', required=True, type=Path)
    apply.add_argument('--allow-source-library', action='append', default=[], help='显式确认与此有效集关联的其他来源库，可重复')
    apply.add_argument('--file-key', action='append', help='只采用指定文件位，可重复；省略时采用记录中的全部明确文件和显式删除')
    apply.add_argument('--verify-files', action='store_true', help='显式验证 RAW 文件存在；默认只读取已归档 JSON')
    for action in ('accept', 'rollback', 'revoke'):
        sub = base(action)
        for x in ('revision','actor','reason'): sub.add_argument('--'+x, required=True)
    base('rebuild-index')
    return p


def run(args):
    return run_version(**vars(args))


def main():
    try:
        print(json.dumps(run(parser().parse_args()), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as exc:
        print(f'错误: {exc}', file=sys.stderr)
        return 1
    return 0
