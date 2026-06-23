from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import hashlib
import json


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


class ScanCache:
    def __init__(self, config: Any = None) -> None:
        self.config = config
        self.cache_dir = Path(str(_get(config, "cache_dir", "work/index/parser_cache")))
        self.no_cache = bool(_get(config, "no_cache", False))
        self.skip_cache = bool(_get(config, "skip_cache", False))

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.cache_dir / digest[:2] / f"{digest}.json"

    def get_parser_result(self, key: str, **_: Any) -> Any | None:
        if self.no_cache or self.skip_cache:
            return None
        path = self._path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def put_parser_result(self, key: str, result: Any, **_: Any) -> None:
        if self.no_cache:
            return
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
