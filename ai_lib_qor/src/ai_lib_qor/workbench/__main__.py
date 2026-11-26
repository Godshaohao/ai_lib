"""Start the local path-mode AI LIB workbench."""
import argparse
from pathlib import Path
from .path_app import create_path_app


def main():
    parser = argparse.ArgumentParser(description='ai_lib_qor 本地三层工作台')
    project = Path(__file__).resolve().parents[3]
    parser.add_argument('--work', default=str(project / 'work'), help='路径式工作目录（默认 ./work）')
    parser.add_argument('--host')
    parser.add_argument('--port', type=int)
    parser.add_argument('--in-process-jobs', action='store_true', help='禁用子进程隔离，在主进程线程中执行后台任务')
    args = parser.parse_args()
    app = create_path_app(args.work, subprocess_jobs=not args.in_process_jobs)
    app.run(host=args.host or app.config['QOR_BIND_HOST'],
            port=args.port or app.config['QOR_BIND_PORT'], debug=False)


if __name__ == '__main__':
    main()
