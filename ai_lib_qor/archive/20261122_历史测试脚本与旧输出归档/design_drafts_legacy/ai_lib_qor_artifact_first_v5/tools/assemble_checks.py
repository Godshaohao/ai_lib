#!/usr/bin/env python3
"""Executable composition demo: multiple plugin contributions -> ONE immutable run JSON.

The input fragments are temporary plugin messages, not additional business contracts.
No real EDA checks are performed here.
"""
from __future__ import annotations
import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "plugin_fragments"
OUT = ROOT / "examples" / "published_runs"
OUT.mkdir(parents=True, exist_ok=True)

TARGET = {"kind": "effective_revision", "set_id": "rtavfs_primary", "revision_id": "rev_0008"}
INPUT_GENERATION = "input_gen_008"
VALID_KINDS = {"DIFF", "QUALITY", "MEASUREMENT", "EVALUATION"}
VALID_STATUS = {"COMPLETED", "NOT_CHECKED", "FAILED", "NOT_RUN", "REUSED"}
VALID_VERDICT = {"PASS", "FAIL", "REVIEW_REQUIRED", "NOT_CHECKED", None}


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE / (name + ".json")).read_text(encoding="utf-8"))


def validate(contribution: dict[str, Any], expected_id: str) -> None:
    """Minimal boundary checks for this demonstration, not a production schema."""
    require = {"check_id", "implementation_version", "kind", "execution_status", "verdict", "target", "input_generation", "parameters", "findings", "metrics", "evidence_refs", "input_refs", "environment_id"}
    missing = require - contribution.keys()
    if missing:
        raise ValueError(f"{expected_id}: missing {sorted(missing)}")
    if contribution["check_id"] != expected_id:
        raise ValueError(f"wrong check_id: expected {expected_id}")
    if contribution["target"] != TARGET or contribution["input_generation"] != INPUT_GENERATION:
        raise ValueError(f"{expected_id}: target or input generation changed")
    if contribution["kind"] not in VALID_KINDS or contribution["execution_status"] not in VALID_STATUS:
        raise ValueError(f"{expected_id}: invalid category or execution status")
    if contribution["verdict"] not in VALID_VERDICT:
        raise ValueError(f"{expected_id}: invalid verdict")
    if contribution["kind"] in {"DIFF", "MEASUREMENT"} and contribution["verdict"] not in {None, "NOT_CHECKED"}:
        raise ValueError(f"{expected_id}: observation/measurement must not be labelled PASS")
    if contribution["execution_status"] in {"NOT_CHECKED", "FAILED", "NOT_RUN"} and contribution["verdict"] not in {"NOT_CHECKED", None}:
        raise ValueError(f"{expected_id}: non-executed check falsely reported a verdict")
    if contribution["kind"] in {"QUALITY", "EVALUATION"} and contribution["execution_status"] == "COMPLETED" and contribution["verdict"] is None:
        raise ValueError(f"{expected_id}: evaluated quality check lacks verdict")
    if not isinstance(contribution["findings"], list) or not isinstance(contribution["metrics"], list):
        raise ValueError(f"{expected_id}: findings or metrics not an array")


def summarize(checks: dict[str, dict]) -> dict[str, Any]:
    # A metric-only or DIFF result does NOT imply an overall quality PASS.
    assessed = [c for c in checks.values() if c["kind"] in {"QUALITY", "EVALUATION"}]
    verdicts = [c["verdict"] for c in assessed]
    statuses = [c["execution_status"] for c in checks.values()]
    if any(v == "FAIL" for v in verdicts):
        overall = "FAIL"
    elif any(v == "REVIEW_REQUIRED" for v in verdicts):
        overall = "REVIEW_REQUIRED"
    elif any(v == "NOT_CHECKED" for v in verdicts) or any(s in {"FAILED", "NOT_CHECKED", "NOT_RUN"} for s in statuses):
        overall = "INCOMPLETE"
    elif assessed and all(v == "PASS" for v in verdicts):
        overall = "PASS"
    else:
        overall = "INCOMPLETE"
    return {
        "overall_verdict": overall,
        "total_plugins": len(checks),
        "completed_or_reused": sum(c["execution_status"] in {"COMPLETED", "REUSED"} for c in checks.values()),
        "not_checked_or_failed": [k for k, v in sorted(checks.items()) if v["execution_status"] in {"NOT_RUN", "NOT_CHECKED", "FAILED"}],
        "quality_evaluations": len(assessed),
    }


def assemble(
    run_id: str,
    expected_ids: list[str],
    new_contributions: list[dict[str, Any]],
    previous_run: dict[str, Any] | None = None,
    reuse_ids: set[str] | None = None,
    reuse_specs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One deterministic assembler and one final writer.  No last-writer-wins."""
    if len(expected_ids) != len(set(expected_ids)):
        raise ValueError("duplicate check_id in check plan")
    new: dict[str, dict[str, Any]] = {}
    for record in new_contributions:
        check_id = record["check_id"]
        if check_id not in expected_ids:
            raise ValueError(f"unregistered check: {check_id}")
        if check_id in new:
            raise ValueError(f"collision on check_id {check_id}")
        validate(record, check_id)
        new[check_id] = copy.deepcopy(record)
    reuse_ids = reuse_ids or set()
    if reuse_ids & set(new):
        raise ValueError("same check_id both reused and freshly executed")
    if not reuse_ids <= set(expected_ids):
        raise ValueError("attempted to reuse unplanned plugin")
    if reuse_ids and previous_run is None:
        raise ValueError("no previous run supplied")
    if reuse_ids and not reuse_specs:
        raise ValueError("reuse requires explicit current plugin/parameter/input/environment specs")
    if previous_run and (previous_run["target"] != TARGET or previous_run["input_generation"] != INPUT_GENERATION):
        raise ValueError("previous run is based on another target/input generation")
    checks = {}
    for check_id in sorted(expected_ids):
        if check_id in new:
            checks[check_id] = new[check_id]
        elif check_id in reuse_ids:
            prior = previous_run["checks"].get(check_id)
            if not prior or prior["execution_status"] not in {"COMPLETED", "REUSED"}:
                raise ValueError(f"cannot reuse failed/unavailable {check_id}")
            current = reuse_specs.get(check_id, {})
            required_fields = {"implementation_version", "parameters", "input_refs", "environment_id"}
            if not required_fields <= set(current):
                raise ValueError(f"reuse spec incomplete for {check_id}")
            if any(prior[k] != current[k] for k in required_fields):
                raise ValueError(f"stale cache: spec changed for {check_id}")
            item = copy.deepcopy(prior)
            # In a real implementation, compare plugin code+parameter+input+environment fingerprints.
            item["execution_status"] = "REUSED"
            item["reused_from_run_id"] = previous_run["run_id"]
            checks[check_id] = item
        else:
            checks[check_id] = {
                "check_id": check_id, "implementation_version": "UNKNOWN", "kind": "QUALITY",
                "execution_status": "NOT_RUN", "verdict": "NOT_CHECKED", "target": TARGET,
                "input_generation": INPUT_GENERATION, "parameters": {}, "input_refs": [], "environment_id": "UNRESOLVED", "findings": [],
                "metrics": [], "evidence_refs": [], "reason": "No contribution and no valid reusable result",
            }
    # A QoR threshold verdict must refer to a measured value in the SAME run.
    gate = checks.get("qor_gate")
    if gate and gate["execution_status"] in {"COMPLETED", "REUSED"}:
        measurement = checks.get("sta_setup_wns")
        if not measurement or measurement["execution_status"] not in {"COMPLETED", "REUSED"}:
            raise ValueError("qor_gate missing usable sta_setup_wns measurement")
        met = next((m for m in measurement["metrics"] if m.get("name") == "setup_wns"), None)
        if not met or met.get("unit") != "ns":
            raise ValueError("qor_gate cannot establish comparable WNS evidence")
        dep = gate.get("depends_on")
        if dep != {"check_id": "sta_setup_wns", "metric_name": "setup_wns"}:
            raise ValueError("qor_gate dependency does not identify the exact measurement")
        if gate["metrics"]:
            raise ValueError("qor_gate must reference, not duplicate, WNS measurement")
        threshold = gate["parameters"].get("threshold")
        if not isinstance(threshold, (int, float)) or gate["parameters"].get("comparison") != ">=":
            raise ValueError("unsupported QoR gate parameters")
        expected_verdict = "PASS" if met["value"] >= threshold else "FAIL"
        if gate["verdict"] != expected_verdict:
            raise ValueError("qor_gate verdict does not follow threshold")

    return {
        "schema_version": "check_run.v1",
        "run_id": run_id,
        "target": TARGET,
        "input_generation": INPUT_GENERATION,
        "expected_checks": expected_ids,
        "checks": checks,
        "summary": summarize(checks),
        "published_state": "FINAL",
        "note": "SYNTHETIC DEMO: extracted old-script output is represented by fixture fragments; no real RAW/EDA content was scanned",
    }


def publish(result: dict) -> Path:
    """Demonstration: exclusive-create immutable file; production needs staging + atomic commit."""
    path = OUT / (result["run_id"] + ".json")
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != payload:
            raise FileExistsError(f"immutable output already exists with different content: {path}")
        return path  # idempotent with identical byte content
    with path.open("x", encoding="utf-8") as fp:
        fp.write(payload)
    return path


def current_reuse_specs(check_ids: set[str]) -> dict[str, dict[str, Any]]:
    """Current declared check profile, not inferred from the previous published run."""
    keys = ("implementation_version", "parameters", "input_refs", "environment_id")
    return {cid: {key: load(cid)[key] for key in keys} for cid in check_ids}


def main() -> None:
    first_ids = ["content_compare", "macro_diff", "lef_liberty_alignment", "sta_setup_wns", "qor_gate"]
    first = assemble("run_001", first_ids, [load(x) for x in first_ids])
    publish(first)
    # New qos threshold (only gate rerun) and new pin_count plugin; 3 unrelated results reused.
    second = assemble(
        "run_002", first_ids + ["pin_count"],
        [load("qor_gate_stricter"), load("pin_count")],
        previous_run=first,
        reuse_ids={"content_compare", "macro_diff", "sta_setup_wns"},
        reuse_specs=current_reuse_specs({"content_compare", "macro_diff", "sta_setup_wns"}),
    )
    publish(second)
    print("run_001", first["summary"])
    print("run_002", second["summary"])
    print("Published:", *(str(p) for p in [OUT / "run_001.json", OUT / "run_002.json"]))

if __name__ == "__main__":
    main()
