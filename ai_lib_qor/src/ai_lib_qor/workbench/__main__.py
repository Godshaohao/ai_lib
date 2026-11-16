"""Start a local workbench for explicitly configured plans."""
import argparse
from .app import create_app


def main():
    parser = argparse.ArgumentParser(description='ai_lib_qor 本地检查工作台')
    parser.add_argument('--plans', required=True, help='可信检查计划 JSON 目录')
    parser.add_argument('--runs', required=True, help='工作台运行输出目录（与计划目录分开）')
    parser.add_argument('--work', help='已登记的 v3 work 目录；不提供时不展示 IP 目录')
    parser.add_argument('--port', type=int, default=5050)
    args = parser.parse_args()
    create_app(args.plans, args.runs, args.work).run(host='127.0.0.1', port=args.port, debug=False)

if __name__ == '__main__': main()
