from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


class StaticReviewPacketTest(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[dict, Path, Path, Path]:
        target_scan = root / "scan" / "target"
        base_scan = root / "scan" / "base"
        diff = root / "diff" / "target"
        target_scan.mkdir(parents=True)
        base_scan.mkdir(parents=True)
        diff.mkdir(parents=True)
        (target_scan / "manifest.json").write_text(json.dumps({"files": ["lib/a.lib", "lef/a.lef"]}), encoding="utf-8")
        (base_scan / "manifest.json").write_text(json.dumps({"files": ["lib/a.lib"]}), encoding="utf-8")
        (diff / "compare_manifest.json").write_text(json.dumps({"old": "base", "new": "target"}), encoding="utf-8")
        (diff / "view_diff.json").write_text(
            json.dumps(
                {
                    "views": [
                        {"view_type": "liberty", "added": 0, "removed": 0, "changed": 1},
                        {"view_type": "lef", "added": 1, "removed": 0, "changed": 0},
                    ]
                }
            ),
            encoding="utf-8",
        )
        catalog = {
            "libraries": [
                {
                    "library_id": "ip/demo",
                    "library_name": "demo",
                    "versions": [
                        {
                            "version_id": "base",
                            "raw_path": str(root / "raw" / "base"),
                            "scan": {"scan_dir": str(base_scan), "status": "PASS"},
                        },
                        {
                            "version_id": "target",
                            "raw_path": str(root / "raw" / "target"),
                            "scan": {"scan_dir": str(target_scan), "status": "PASS"},
                            "diff": {"base_version": "base", "diff_dir": str(diff), "status": "DIFF"},
                        },
                    ],
                }
            ]
        }
        policy = root / "review_policy.yaml"
        policy.write_text(
            "\n".join(
                [
                    "version: review-policy-test.v1",
                    "review_owner: ip_owner",
                    "max_review_items: 10",
                    "routing:",
                    "  timing: Timing",
                    "  physical: Physical",
                    "  integration: Integration",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return catalog, target_scan, base_scan, policy

    def test_prepare_freezes_identity_and_routes_questions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog, target_scan, _base_scan, policy = self._fixture(root)
            from lib_guard.review.static_packet import prepare_review_packet

            first = prepare_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            second = prepare_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            self.assertEqual(first["packet_id"], second["packet_id"])
            self.assertEqual(first["packet_dir"], second["packet_dir"])
            packet = json.loads((Path(first["packet_dir"]) / "packet.json").read_text(encoding="utf-8"))
            self.assertEqual(packet["schema_version"], "review_packet.v1")
            self.assertEqual(packet["target_manifest_sha256"], first["target_manifest_sha256"])
            items = (Path(first["packet_dir"]) / "review_items.tsv").read_text(encoding="utf-8")
            self.assertIn("Timing", items)
            self.assertIn("Physical", items)
            self.assertNotIn("raw JSON", items)

            (target_scan / "manifest.json").write_text(json.dumps({"files": ["lib/a.lib", "lef/a.lef", "rtl/a.v"]}), encoding="utf-8")
            changed = prepare_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            self.assertNotEqual(first["packet_id"], changed["packet_id"])

    def test_submit_and_collect_enforce_decisions_and_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog, _target_scan, _base_scan, policy = self._fixture(root)
            from lib_guard.review.static_packet import collect_review_packet, prepare_review_packet, submit_review_response

            prepared = prepare_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            with self.assertRaises(ValueError):
                submit_review_response(catalog, "demo", "target", review_root=root / "reviews", review_id="missing", decision="PASS", reviewer="alice")
            with self.assertRaises(ValueError):
                submit_review_response(catalog, "demo", "target", review_root=root / "reviews", review_id="timing_001", decision="BLOCK", reviewer="alice")

            item_ids = [row.split("\t", 1)[0] for row in (Path(prepared["packet_dir"]) / "review_items.tsv").read_text(encoding="utf-8").splitlines()[1:]]
            self.assertEqual(len(item_ids), 2)
            submit_review_response(catalog, "demo", "target", review_root=root / "reviews", review_id=item_ids[0], decision="PASS", reviewer="alice", now="2026-08-18T01:00:00Z")
            waiting = collect_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            self.assertEqual(waiting["status"], "WAITING")
            self.assertEqual(len(list((Path(prepared["packet_dir"]) / "responses").glob("*.tsv"))), 1)

            submit_review_response(catalog, "demo", "target", review_root=root / "reviews", review_id=item_ids[1], decision="BLOCK", note="LEF pin change needs owner confirmation", reviewer="bob", now="2026-08-18T01:01:00Z")
            blocked = collect_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            self.assertEqual(blocked["status"], "BLOCKED")
            self.assertEqual(blocked["blocking_open"], 1)
            self.assertIn("LEF pin change", (Path(prepared["packet_dir"]) / "review_report.md").read_text(encoding="utf-8"))

            # A later response from the same reviewer wins by submitted_at, never by mtime.
            submit_review_response(catalog, "demo", "target", review_root=root / "reviews", review_id=item_ids[1], decision="PASS", reviewer="bob", now="2026-08-18T01:02:00Z")
            for path in (Path(prepared["packet_dir"]) / "responses").glob("*.tsv"):
                os.utime(path, (1, 1))
            approved = collect_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            self.assertEqual(approved["status"], "APPROVED")
            gate = Path(prepared["packet_dir"]) / "review_gate.json"
            report = Path(prepared["packet_dir"]) / "review_report.md"
            gate.unlink()
            report.unlink()
            rebuilt = collect_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            self.assertEqual(rebuilt["status"], "APPROVED")
            self.assertTrue(gate.exists())
            self.assertTrue(report.exists())

            from lib_guard.review.state import build_review_version_state

            _lib, version_state = build_review_version_state(catalog, out_dir=root / "catalog" / "html", library="demo", version="target")
            self.assertEqual(version_state["review_gate"]["status"], "APPROVED")
            self.assertEqual(version_state["review_packet"]["packet_id"], prepared["packet_id"])

    def test_old_packet_response_is_stale_after_subject_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog, target_scan, _base_scan, policy = self._fixture(root)
            from lib_guard.review.static_packet import collect_review_packet, prepare_review_packet, submit_review_response

            old = prepare_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            item_id = (Path(old["packet_dir"]) / "review_items.tsv").read_text(encoding="utf-8").splitlines()[1].split("\t", 1)[0]
            submit_review_response(catalog, "demo", "target", review_root=root / "reviews", review_id=item_id, decision="PASS", reviewer="alice")
            (target_scan / "manifest.json").write_text(json.dumps({"files": ["lib/a.lib", "lef/a.lef", "rtl/new.v"]}), encoding="utf-8")
            new = prepare_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            self.assertNotEqual(old["packet_id"], new["packet_id"])
            result = collect_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            self.assertEqual(result["status"], "WAITING")
            self.assertEqual(result["stale_response_count"], 1)
            self.assertNotEqual(result["packet_id"], old["packet_id"])

    def test_collect_is_byte_deterministic_and_does_not_use_wall_clock(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog, _target_scan, _base_scan, policy = self._fixture(root)
            from lib_guard.review.static_packet import collect_review_packet, prepare_review_packet, submit_review_response

            prepared = prepare_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            item_ids = [row.split("\t", 1)[0] for row in (Path(prepared["packet_dir"]) / "review_items.tsv").read_text(encoding="utf-8").splitlines()[1:]]
            for item_id in item_ids:
                submit_review_response(
                    catalog,
                    "demo",
                    "target",
                    review_root=root / "reviews",
                    review_id=item_id,
                    decision="PASS",
                    reviewer="alice",
                    now="2026-08-18T01:00:00Z",
                )
            collect_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            gate_path = Path(prepared["packet_dir"]) / "review_gate.json"
            report_path = Path(prepared["packet_dir"]) / "review_report.md"
            first_gate = gate_path.read_bytes()
            first_report = report_path.read_bytes()
            collect_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            self.assertEqual(first_gate, gate_path.read_bytes())
            self.assertEqual(first_report, report_path.read_bytes())

    def test_policy_routing_change_invalidates_packet_even_when_policy_version_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog, _target_scan, _base_scan, policy = self._fixture(root)
            from lib_guard.review.static_packet import prepare_review_packet

            first = prepare_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            policy.write_text(policy.read_text(encoding="utf-8").replace("timing: Timing", "timing: Integration"), encoding="utf-8")
            second = prepare_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            self.assertNotEqual(first["packet_id"], second["packet_id"])

    def test_compare_evidence_change_invalidates_packet(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog, _target_scan, _base_scan, policy = self._fixture(root)
            from lib_guard.review.static_packet import prepare_review_packet

            first = prepare_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            (root / "diff" / "target" / "view_diff.json").write_text(json.dumps({"views": [{"view_type": "liberty", "changed": 2}]}), encoding="utf-8")
            second = prepare_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            self.assertNotEqual(first["packet_id"], second["packet_id"])

    def test_policy_can_route_one_view_to_multiple_departments(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog, _target_scan, _base_scan, policy = self._fixture(root)
            (root / "diff" / "target" / "view_diff.json").write_text(json.dumps({"views": [{"view_type": "spef", "changed": 1}]}), encoding="utf-8")
            policy.write_text(policy.read_text(encoding="utf-8") + "  spef: Timing, Physical\n", encoding="utf-8")
            from lib_guard.review.static_packet import prepare_review_packet

            prepared = prepare_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            item_text = (Path(prepared["packet_dir"]) / "review_items.tsv").read_text(encoding="utf-8")
            self.assertIn("Timing", item_text)
            self.assertIn("Physical", item_text)

    def test_machine_facts_are_blockers_not_human_questions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog, _target_scan, _base_scan, policy = self._fixture(root)
            target = catalog["libraries"][0]["versions"][1]
            target["package_type"] = "UNKNOWN_PACKAGE"
            target["required_views"] = ["liberty", "gds"]
            from lib_guard.review.static_packet import collect_review_packet, prepare_review_packet

            prepared = prepare_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            result = collect_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any(item["id"] == "machine.unknown_package" for item in result["machine_blockers"]))
            self.assertTrue(any(item["id"].startswith("machine.required_view_missing") for item in result["machine_blockers"]))
            item_ids = [row.split("\t", 1)[0] for row in (Path(prepared["packet_dir"]) / "review_items.tsv").read_text(encoding="utf-8").splitlines()[1:]]
            self.assertTrue(item_ids)
            self.assertTrue(all(not item_id.startswith("machine.") for item_id in item_ids))

    def test_machine_fact_change_creates_new_packet(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog, _target_scan, _base_scan, policy = self._fixture(root)
            from lib_guard.review.static_packet import prepare_review_packet

            first = prepare_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            catalog["libraries"][0]["versions"][1]["package_type"] = "UNKNOWN_PACKAGE"
            second = prepare_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            self.assertNotEqual(first["packet_id"], second["packet_id"])

    def test_packet_items_are_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog, _target_scan, _base_scan, policy = self._fixture(root)
            from lib_guard.review.static_packet import collect_review_packet, prepare_review_packet

            prepared = prepare_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            items = Path(prepared["packet_dir"]) / "review_items.tsv"
            items.write_text(items.read_text(encoding="utf-8").replace("请确认", "请恶意修改"), encoding="utf-8")
            with self.assertRaises(ValueError):
                prepare_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            result = collect_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any(item["id"] == "machine.review_items_tampered" for item in result["machine_blockers"]))

    def test_response_department_mismatch_is_not_counted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog, _target_scan, _base_scan, policy = self._fixture(root)
            from lib_guard.review.static_packet import collect_review_packet, prepare_review_packet

            prepared = prepare_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            item_id = (Path(prepared["packet_dir"]) / "review_items.tsv").read_text(encoding="utf-8").splitlines()[1].split("\t", 1)[0]
            response = Path(prepared["packet_dir"]) / "responses" / "bad.tsv"
            response.write_text(
                "schema_version\tpacket_id\treview_id\tdepartment\tdecision\tnote\treviewer\tsubmitted_at\n"
                f"review_response.v1\t{prepared['packet_id']}\t{item_id}\tWrong\tPASS\t\talice\t2026-08-18T01:00:00Z\n",
                encoding="utf-8",
            )
            result = collect_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            self.assertEqual(result["status"], "WAITING")
            self.assertEqual(result["items"][0]["decision"], "WAITING")
            self.assertTrue(any("department" in item["reason"] for item in result["invalid_responses"]))

    def test_waiver_only_resolves_an_active_block_and_unknown_waiver_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog, _target_scan, _base_scan, policy = self._fixture(root)
            from lib_guard.review.static_packet import collect_review_packet, prepare_review_packet, submit_review_response

            prepared = prepare_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            item_ids = [row.split("\t", 1)[0] for row in (Path(prepared["packet_dir"]) / "review_items.tsv").read_text(encoding="utf-8").splitlines()[1:]]
            submit_review_response(catalog, "demo", "target", review_root=root / "reviews", review_id=item_ids[0], decision="PASS", reviewer="alice", now="2026-08-18T01:00:00Z")
            (Path(prepared["packet_dir"]) / "waiver").mkdir()
            (Path(prepared["packet_dir"]) / "waiver" / "override.json").write_text(
                json.dumps({"waivers": [{"review_id": item_ids[1], "authorized_by": "owner", "reason": "not a blocker"}, {"review_id": "missing", "authorized_by": "owner", "reason": "unknown"}]}),
                encoding="utf-8",
            )
            waiting = collect_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            self.assertEqual(waiting["status"], "WAITING")
            self.assertTrue(any("review_id" in item["reason"] for item in waiting["invalid_responses"]))
            submit_review_response(catalog, "demo", "target", review_root=root / "reviews", review_id=item_ids[1], decision="BLOCK", note="known risk", reviewer="bob", now="2026-08-18T01:01:00Z")
            approved = collect_review_packet(catalog, "demo", "target", review_root=root / "reviews", policy_path=policy)
            self.assertEqual(approved["status"], "APPROVED")


if __name__ == "__main__":
    unittest.main()
