"""CLI entry point for effective-version operations."""
import sys
from .cli import parser, run, main

if __name__ == '__main__':
    sys.exit(main())
