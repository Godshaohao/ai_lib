"""Start a local workbench for explicitly configured plans."""
import argparse
from pathlib import Path
from .app import create_app


def main():
    parser = argparse.ArgumentParser(description='ai_lib_qor 本地检查工作台')
    project=Path(__file__).resolve().parents[3]
    parser.add_argument('--plans', default=str(project/'examples/pipeline'), help='旧流程的可信检查计划 JSON 目录')
    parser.add_argument('--runs', default=str(project/'workbench_runs'), help='旧流程的运行输出目录')
    parser.add_argument('--work', help='工作目录；可自动识别路径式或旧契约')
    parser.add_argument('--port', type=int, default=5050)
    parser.add_argument('--path-mode',action='store_true',help='使用新路径式三级工作台')
    args = parser.parse_args()
    if args.path_mode and not args.work:parser.error('--path-mode 需要 --work')
    create_app(args.plans, args.runs, args.work, path_mode=True if args.path_mode else None).run(host='127.0.0.1', port=args.port, debug=False)

if __name__ == '__main__': main()
