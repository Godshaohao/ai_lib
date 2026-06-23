"""
lib_guard.scan.progress

Lightweight scan progress reporter.

What it does:
- Prints stage/step progress through logging.
- Writes real-time JSONL progress to <scan_out>/logs/scan_progress.jsonl.
- Writes latest heartbeat to <scan_out>/logs/scan_progress_latest.json.
- Keeps simple timing data for stages.

This module has no third-party dependency. It is safe in csh/NFS batch runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
import json
import logging
import os
import sys
import tempfile
import time


LOGGER = logging.getLogger("lib_guard.scan.progress")


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
            f.write("\n")
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:
            pass


@dataclass
class StageTiming:
    name: str
    started_at: float
    ended_at: float | None = None

    @property
    def elapsed_seconds(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.time()
        return max(0.0, end - self.started_at)


@dataclass
class ProgressReporter:
    config: Any
    context: Any
    enabled: bool = True
    progress_interval: int = 50
    started_at: float = field(default_factory=time.time)
    current_stage: str | None = None
    stage_timings: dict[str, StageTiming] = field(default_factory=dict)
    console_progress: bool = True

    def __post_init__(self) -> None:
        self.enabled = not bool(_get(self.config, "no_progress", False))
        try:
            self.progress_interval = int(_get(self.config, "progress_interval", 50) or 50)
        except Exception:
            self.progress_interval = 50
        self.progress_interval = max(self.progress_interval, 1)
        console_progress = _get(self.config, "console_progress", None)
        self.console_progress = sys.stderr.isatty() if console_progress is None else bool(console_progress)

        self.out_dir = Path(str(_get(self.context, "out_dir", "scan_output")))
        self.logs_dir = self.out_dir / "logs"
        self.jsonl_path = self.logs_dir / "scan_progress.jsonl"
        self.latest_path = self.logs_dir / "scan_progress_latest.json"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def stage(self, name: str, message: str = "", **extra: Any) -> None:
        now = time.time()
        if self.current_stage and self.current_stage in self.stage_timings:
            old = self.stage_timings[self.current_stage]
            if old.ended_at is None:
                old.ended_at = now

        self.current_stage = name
        self.stage_timings[name] = StageTiming(name=name, started_at=now)

        event = self._event("stage", stage=name, message=message, **extra)
        self._emit(event)

    def step(self, stage: str, done: int, total: int, message: str = "", force: bool = False, **extra: Any) -> None:
        if not force and done not in {1, total} and done % self.progress_interval != 0:
            return
        percent = None
        if total:
            percent = round(done * 100.0 / total, 2)
        event = self._event(
            "step",
            stage=stage,
            done=done,
            total=total,
            percent=percent,
            message=message,
            **extra,
        )
        self._emit(event)

    def event(self, event_type: str, stage: str, message: str = "", **extra: Any) -> None:
        self._emit(self._event(event_type, stage=stage, message=message, **extra))

    def finish(self, status: str = "UNKNOWN", **extra: Any) -> None:
        now = time.time()
        if self.current_stage and self.current_stage in self.stage_timings:
            timing = self.stage_timings[self.current_stage]
            if timing.ended_at is None:
                timing.ended_at = now
        event = self._event("finish", stage="finish", message=f"scan finished: {status}", status=status, **extra)
        self._emit(event, force=True)
        if self.enabled and self.console_progress:
            sys.stderr.write("\n")
            sys.stderr.flush()

    def performance(self) -> dict[str, Any]:
        return {
            "total_seconds": round(time.time() - self.started_at, 3),
            "stages": {
                name: round(timing.elapsed_seconds, 3)
                for name, timing in self.stage_timings.items()
            },
        }

    def _event(self, event_type: str, stage: str, message: str = "", **extra: Any) -> dict[str, Any]:
        return {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "epoch": time.time(),
            "event": event_type,
            "stage": stage,
            "message": message,
            "scan_id": _get(self.context, "scan_id", None),
            "scan_mode": _get(self.context, "scan_mode", None),
            "out_dir": str(self.out_dir),
            **extra,
        }

    def _emit(self, event: dict[str, Any], force: bool = False) -> None:
        # Always write latest/jsonl. Logging can be disabled by --no-progress.
        self._write_files(event)
        if self.enabled or force:
            if self.enabled and self.console_progress:
                self._write_console_line(event)
            prefix = f"[{event.get('stage')}]"
            msg = event.get("message", "")
            if event.get("event") == "step":
                done = event.get("done")
                total = event.get("total")
                percent = event.get("percent")
                LOGGER.info("%s %s/%s %s%% %s", prefix, done, total, percent, msg)
            else:
                LOGGER.info("%s %s", prefix, msg)

    def _write_files(self, event: dict[str, Any]) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        with self.jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
            f.write("\n")
        latest = {**event, "latest": event, "performance": self.performance()}
        _atomic_write_json(self.latest_path, latest)

    def _write_console_line(self, event: dict[str, Any]) -> None:
        stage = str(event.get("stage") or "")
        message = str(event.get("message") or "")
        done = event.get("done")
        total = event.get("total")
        percent = event.get("percent")
        summary = event.get("summary") if isinstance(event.get("summary"), Mapping) else {}
        running = summary.get("running", 0) if isinstance(summary, Mapping) else 0
        failed = summary.get("failed", 0) if isinstance(summary, Mapping) else 0
        pass_empty = summary.get("pass_empty", 0) if isinstance(summary, Mapping) else 0
        cache_hit = summary.get("cache_hit", 0) if isinstance(summary, Mapping) else 0
        if done is not None and total is not None:
            pct = f"{percent}%" if percent is not None else ""
            line = f"{stage} {done}/{total} {pct} running={running} failed={failed} empty={pass_empty} cache={cache_hit} {message}"
        else:
            line = f"{stage} {message}"
        width = 160
        if len(line) > width:
            line = line[: width - 3] + "..."
        sys.stderr.write("\r" + line.ljust(width))
        sys.stderr.flush()
