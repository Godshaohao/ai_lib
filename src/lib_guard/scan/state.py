from __future__ import annotations

from pathlib import Path
from typing import Any
import json


class ScanStateStore:
    def __init__(self, config: Any = None) -> None:
        self.config = config
        self.state_dir = Path(str(getattr(config, "state_dir", "work/index/scan_state")))

    def load_latest(self, context: Any) -> dict[str, Any] | None:
        path = self.state_dir / "last_snapshot.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, records: list[Any], bundle: Any, context: Any) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        data = {"schema_version": getattr(context, "schema_version", "1.0"), "scan_id": context.scan_id, "files": bundle.file_inventory["files"]}
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        (self.state_dir / "last_snapshot.json").write_text(text, encoding="utf-8")
        (self.state_dir / f"snapshot_{context.scan_id}.json").write_text(text, encoding="utf-8")
