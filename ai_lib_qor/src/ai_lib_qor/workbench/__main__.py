"""Start the local path-mode AI LIB workbench."""
import argparse
from pathlib import Path
from .path_app import create_path_app


def main():
    parser = argparse.ArgumentParser(description='ai_lib_qor 本地三层工作台')
    project = Path(__file__).resolve().parents[3]
    parser.add_argument('--work', default=str(project / 'work'), help='路径式工作目录（默认 ./work）')
    parser.add_argument('--port', type=int, default=5050)
    args = parser.parse_args()
    create_path_app(args.work).run(host='127.0.0.1', port=args.port, debug=False)


if __name__ == '__main__':
    main()
