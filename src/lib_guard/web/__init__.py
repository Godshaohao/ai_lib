"""Small Flask control plane for the existing Lib Guard facts and projections."""


def create_app(*args, **kwargs):
    """Import Flask only when the web server is actually requested."""

    from .app import create_app as _create_app

    return _create_app(*args, **kwargs)


__all__ = ["create_app"]
