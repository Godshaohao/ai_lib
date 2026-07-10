from __future__ import annotations

from pathlib import Path
from typing import Any
import json


class ScanReportWriter:
    def __init__(self, config: Any = None) -> None:
        self.config = config

    def write_bundle(self, bundle: Any, context: Any) -> None:
        out = Path(context.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "summary").mkdir(exist_ok=True)
        (out / "signatures").mkdir(exist_ok=True)
        (out / "logs").mkdir(exist_ok=True)
        (out / "parser_results").mkdir(exist_ok=True)

        self._write_json(out / "scan_meta.json", bundle.scan_meta)
        self._write_json(out / "manifest.json", bundle.manifest)
        self._write_json(out / "scan_summary.json", bundle.manifest)
        self._write_json(out / "type_distribution.json", bundle.manifest.get("file_type_counts", {}))
        version_profile = dict(bundle.manifest.get("version_profile", {}) or {})
        version_profile["hash_policy"] = bundle.manifest.get("hash_policy", {})
        self._write_json(out / "version_profile.json", version_profile)
        self._write_json(out / "file_inventory.json", bundle.file_inventory)
        self._write_json(out / "parser_task_list.json", bundle.parser_task_list)
        self._write_json(out / "parser_manifest.json", bundle.parser_manifest)
        self._write_json(out / "parser_results.json", bundle.parser_results)
        self._write_parser_result_files(out, bundle)
        self._write_json(out / "state_delta.json", bundle.state_delta)
        self._write_json(out / "integrity.json", bundle.integrity)
        self._write_json(out / "scan_issues.json", bundle.issues)
        self._write_json(out / "summary" / "parser_quality.json", bundle.parser_quality)
        self._write_json(out / "signatures" / "signatures.json", bundle.signatures)
        self._write_json(out / "logs" / "parser_errors.json", bundle.logs.get("parser_errors", []))
        self._write_json(out / "logs" / "cache_events.json", bundle.logs.get("cache_events", []))
        from .evidence_export import write_scan_review_evidence

        write_scan_review_evidence(out, bundle, context)

    def _write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")

    def _write_parser_result_files(self, out: Path, bundle: Any) -> None:
        for rel_path, result in (bundle.parser_results or {}).items():
            if not str(rel_path).startswith("parser_results/"):
                continue
            self._write_json(out / rel_path, result)
