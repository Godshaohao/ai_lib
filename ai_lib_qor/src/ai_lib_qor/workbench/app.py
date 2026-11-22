"""Compatibility shim forwarding create_app() to the path-mode workbench."""
from .path_app import create_path_app


def create_app(plan_root=None, runs_root=None, work_root=None, *, path_mode=True):
    return create_path_app(work_root)
