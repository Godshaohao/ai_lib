from __future__ import annotations

from typing import Any, Mapping


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


class ScanPolicy:
    DEFAULT_PARSE_MODES = {"candidate", "release", "diff", "refresh", "full"}
    SMART_SKIP_EXTENSIONS = {
        ".lef",
        ".lib",
        ".db",
        ".cdl",
        ".spi",
        ".spice",
        ".spef",
        ".gds",
        ".gdsii",
        ".oas",
        ".oasis",
        ".gz",
        ".tgz",
        ".tar",
        ".zip",
        ".7z",
        ".bz2",
        ".xz",
        ".fsdb",
        ".vcd",
        ".saif",
    }
    SMART_SKIP_COMBINED_EXTENSIONS = {
        ".lef.gz",
        ".lib.gz",
        ".db.gz",
        ".cdl.gz",
        ".spi.gz",
        ".spice.gz",
        ".spef.gz",
        ".gds.gz",
        ".gdsii.gz",
        ".oas.gz",
        ".oasis.gz",
    }
    DEFAULT_SMALL_FILE_MAX_BYTES = 16 * 1024 * 1024

    def __init__(self, config: Any = None) -> None:
        self.config = config

    @classmethod
    def from_config(cls, config: Any) -> "ScanPolicy":
        return cls(config)

    def should_hash(self, record: Any, context: Any) -> bool:
        return self.hash_decision(record, context)["should_hash"]

    def hash_decision(self, record: Any, context: Any) -> dict[str, Any]:
        mode = str(_get(context, "scan_mode", "inventory"))
        if mode in {"quick", "inventory"}:
            return {"policy": "none", "should_hash": False, "hash_status": "NOT_REQUIRED", "reason": "scan_mode"}
        policy = str(_get(self.config, "hash_policy", _get(self.config, "hash", "smart")) or "smart").lower()
        if mode == "full" or policy == "full":
            return {"policy": "full", "should_hash": True, "hash_status": "CALCULATED", "reason": "full_hash"}
        extension = str(_get(record, "extension", "") or "").lower()
        combined = str(_get(record, "combined_extension", "") or "").lower()
        if policy == "smart":
            if extension in self.SMART_SKIP_EXTENSIONS or combined in self.SMART_SKIP_COMBINED_EXTENSIONS:
                return {
                    "policy": "smart",
                    "should_hash": False,
                    "hash_status": "SKIPPED_BY_SMART_POLICY",
                    "reason": "heavy_eda_or_archive_extension",
                }
            max_bytes = int(_get(self.config, "small_file_sha256_max_bytes", self.DEFAULT_SMALL_FILE_MAX_BYTES) or self.DEFAULT_SMALL_FILE_MAX_BYTES)
            size = int(_get(record, "size_bytes", 0) or 0)
            if size > max_bytes:
                return {"policy": "smart", "should_hash": False, "hash_status": "SKIPPED_BY_SMART_POLICY", "reason": "large_file"}
            return {"policy": "smart", "should_hash": True, "hash_status": "CALCULATED", "reason": "small_file"}
        return {
            "policy": policy,
            "should_hash": bool(_get(record, "is_key_file", False)),
            "hash_status": "CALCULATED" if bool(_get(record, "is_key_file", False)) else "NOT_REQUIRED",
            "reason": "legacy_key_file_policy",
        }

    def should_parse(self, record: Any, context: Any) -> bool:
        mode = str(_get(context, "scan_mode", "inventory"))
        if mode in {"quick", "inventory", "signature"}:
            return False
        configured_types = _get(self.config, "parse_file_types", None)
        if configured_types:
            allowed = {str(item).strip().lower() for item in configured_types}
            return str(_get(record, "file_type", "unknown")).lower() in allowed
        return mode in self.DEFAULT_PARSE_MODES and bool(_get(record, "is_key_file", False))
