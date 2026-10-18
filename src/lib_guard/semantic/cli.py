"""Independent advisory diagnostics; no changes to the daily short CLI."""

import argparse
import json
import sys
import time
from pathlib import Path
from .runner import run_semantic_review
from .facts import FactsStorageError
from .profile import DEFAULT_CONFIG_PATH


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
    parser.add_argument('--catalog-html-out', help='同步 IP 阅读报告的目录；省略时仅识别标准 catalog/html 工作区')
    args = parser.parse_args(argv)
    started_epoch = time.time()
    config_path = args.config or DEFAULT_CONFIG_PATH
    try:
        result = run_semantic_review(args.effective_manifest, args.catalog, args.out,
            base_manifest_path=args.base_effective_manifest, mapping_path=args.mapping,
            profile_config_path=config_path, profile_name=args.profile, artifact_store=args.artifact_store)
    except (OSError, ValueError, KeyError, TypeError, FactsStorageError) as error:
        print(f'语义诊断未完成：{error}', file=sys.stderr)
        return 2
    html_out = args.catalog_html_out
    if not html_out and Path(args.catalog).parent.name == 'catalog':
        html_out = str(Path(args.catalog).parent / 'html')
    if html_out:
        try:
            from lib_guard.review.publication import publish_semantic_review
            publish_semantic_review(args.catalog, html_out, args.effective_manifest, args.out,
                                    profile_config_path=config_path, started_epoch=started_epoch)
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f'阅读报告未同步；技术检查结果已保留，可重新刷新：{error}', file=sys.stderr)
    else:
        print('阅读报告未同步：请指定 --catalog-html-out 以定位报告工作区。', file=sys.stderr)
    print(json.dumps(result['summary'], ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
