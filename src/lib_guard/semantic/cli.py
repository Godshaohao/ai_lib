"""Independent advisory diagnostics; no changes to the daily short CLI."""

import argparse
import json
import sys
from .runner import run_semantic_review
from .facts import FactsStorageError


def main(argv=None):
    parser = argparse.ArgumentParser(description='跨视图技术检查（只读建议，非发布门禁）')
    parser.add_argument('--effective-manifest', required=True, help='明确选择的候选或当前 Effective Manifest')
    parser.add_argument('--base-effective-manifest', help='明确选择的旧 Effective；不提供则不判定版本变化')
    parser.add_argument('--catalog', required=True, help='现有 Catalog 路径，自动合并 runtime；只读取指定库已有扫描证据')
    parser.add_argument('--mapping', help='已确认的小型 JSON 实体/端口别名映射；不做模糊匹配')
    parser.add_argument('--config', help='检查方案 JSON，默认读取 configs/semantic_review.json')
    parser.add_argument('--profile', help='配置内的方案名称；省略时使用 default_profile')
    parser.add_argument('--out', required=True, help='独立诊断输出目录，summary.json 指向完整快照')
    parser.add_argument('--artifact-store', help='可选的跨任务不可变产物存储，仅共享相同字节，不改变报告路径')
    args = parser.parse_args(argv)
    try:
        result = run_semantic_review(args.effective_manifest, args.catalog, args.out,
            base_manifest_path=args.base_effective_manifest, mapping_path=args.mapping,
            profile_config_path=args.config, profile_name=args.profile, artifact_store=args.artifact_store)
    except (OSError, ValueError, KeyError, TypeError, FactsStorageError) as error:
        print(f'语义诊断未完成：{error}', file=sys.stderr)
        return 2
    print(json.dumps(result['summary'], ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
