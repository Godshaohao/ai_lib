"""Zero-dependency runtime progress, cooperative cancellation, and DI hook registry primitives."""

_HOOKS: dict = {}


def register_hook(name: str, fn) -> None:
    """Register an application/reporting composition-root hook without creating upward layer imports."""
    _HOOKS[name] = fn


def get_hook(name: str):
    """Return a registered composition-root hook or None."""
    return _HOOKS.get(name)


class JobCancelledError(RuntimeError):
    """Raised cooperatively when a running background job is cancelled by the user."""


def check_cancel(cancel_event, message: str = '任务已被用户终止'):
    if cancel_event is not None and cancel_event.is_set():
        raise JobCancelledError(message)


def emit_progress(progress_cb, stage: str, message: str, *, completed=None, total=None):
    if progress_cb is not None:
        progress_cb(stage, message, completed=completed, total=total)
