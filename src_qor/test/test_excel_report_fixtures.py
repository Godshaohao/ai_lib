import hashlib
import json
import posixpath
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from lib_guard.export_review_excel import export_review_excel
from lib_guard.review_runner import _finding_rows, _review_summary, build_workbook_model


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = ROOT / "src_qor/test-results/formal_nl_20261024/libraries"
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _column_number(reference: str) -> int:
    value = 0
    for character in reference:
        if not character.isalpha():
            break
        value = value * 26 + ord(character.upper()) - ord("A") + 1
    return value


def _workbook_sheets(path: Path) -> dict[str, dict[int, dict[int, str]]]:
    with zipfile.ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {item.attrib["Id"]: item.attrib["Target"]
                   for item in relationships.findall(f"{{{PKG_REL_NS}}}Relationship")}
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(text.text or "" for text in item.findall(f".//{{{MAIN_NS}}}t"))
                      for item in root.findall(f"{{{MAIN_NS}}}si")]
        result = {}
        for sheet in workbook.findall(f".//{{{MAIN_NS}}}sheet"):
            target = targets[sheet.attrib[f"{{{REL_NS}}}id"]]
            member = posixpath.normpath(target.lstrip("/") if target.startswith("/") else f"xl/{target}")
            root = ET.fromstring(archive.read(member))
            matrix = {}
            for row in root.findall(f".//{{{MAIN_NS}}}row"):
                row_number = int(row.attrib["r"])
                cells = {}
                for cell in row.findall(f"{{{MAIN_NS}}}c"):
                    value = cell.findtext(f"{{{MAIN_NS}}}v", "")
                    if cell.attrib.get("t") == "s":
                        value = shared[int(value)]
                    elif cell.attrib.get("t") == "inlineStr":
                        value = "".join(text.text or "" for text in cell.findall(f".//{{{MAIN_NS}}}t"))
                    cells[_column_number(cell.attrib["r"])] = value
                matrix[row_number] = cells
            result[sheet.attrib["name"]] = matrix
        return result


def _review_from_fixture(library_name: str) -> tuple[dict, Path, Path, Path]:
    library_dir = FIXTURE_ROOT / library_name
    pointer_path = library_dir / "latest_workbook.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    run_dir = library_dir / "runs" / pointer["review_id"]
    record_path = run_dir / "review_result.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    checks = {}
    for name, item in record.get("checks", {}).items():
        reference = item.get("result_ref") or ""
        evidence_path = run_dir / reference if reference else None
        result = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path and evidence_path.is_file() else {}
        checks[name] = {"selected": name in (record.get("requested_checks") or []),
                        "status": item.get("execution_status", "NOT_RUN"),
                        "result_ref": reference, "result": result}
    review = {"ip": {"id": record.get("library_id"), "name": record.get("library_id"),
                      "library_id": record.get("library_id")},
              "review_id": record.get("review_id"),
              "requested_checks": record.get("requested_checks") or [],
              "review_result": record, "review_result_ref": "review_result.json",
              "checks": checks}
    return review, record_path, run_dir / "evidence/lef_review.json", library_dir / "latest.xlsx"


class ExcelReportFixtureTests(unittest.TestCase):
    def test_sram22_rect_summary_preserves_findings_quality_and_evidence(self):
        review, record_path, lef_evidence_path, latest_path = _review_from_fixture(
            "SRAM22.sram22_256x16m8w8__cc3957909056")
        run_dir = record_path.parent
        archived_workbook = run_dir / "ip_review.xlsx"
        pointer_path = latest_path.parent / "latest_workbook.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        self.assertEqual(pointer["review_id"], review["review_result"]["review_id"])
        self.assertEqual(record_path.relative_to(latest_path.parent).as_posix(),
                         f"runs/{pointer['review_id']}/review_result.json")
        self.assertEqual(review["review_result"]["reports"]["xlsx"], "ip_review.xlsx")
        self.assertTrue((run_dir / review["review_result"]["reports"]["xlsx"]).is_file())
        for check in review["checks"].values():
            reference = check.get("result_ref")
            if reference:
                self.assertTrue((run_dir / reference).is_file(), reference)
        checksums_before = {path: _sha256(path) for path in (
            record_path, lef_evidence_path, archived_workbook,
            pointer_path, latest_path,
        )}
        lef_evidence = json.loads(lef_evidence_path.read_text(encoding="utf-8"))
        changes = lef_evidence["comparison"]["changes"]
        rects = {item["field"]: item for item in changes
                 if item.get("field") in {"pins.vdd.rects", "pins.vss.rects"}}
        self.assertEqual((len(rects["pins.vdd.rects"]["old"]),
                          len(rects["pins.vdd.rects"]["new"])), (544, 552))
        self.assertEqual((len(rects["pins.vss.rects"]["old"]),
                          len(rects["pins.vss.rects"]["new"])), (532, 540))

        summary = _review_summary(review)
        self.assertEqual(summary["quality_assessment"]["status"], review["review_result"]["quality_status"])
        for kind in ("CHANGED", "MISMATCH", "UNVERIFIED"):
            self.assertEqual(summary["counts"][kind], review["review_result"]["summary"]["counts"][kind])
        findings = _finding_rows(review)
        self.assertEqual(len(findings), 2)
        self.assertEqual(sum(row["kind"] == "CHANGED" for row in findings), 2)
        self.assertTrue(all(row["evidence"] == "evidence/lef_review.json" for row in findings))

        model = build_workbook_model([review])
        self.assertEqual(len(model["04-关注项"]), 2)
        self.assertEqual(list(model), [
            "00-概览", "01-工程检查", "02-执行记录", "03-问答", "04-关注项",
            "05-MacroView", "06-MacroView文件", "07-正式文件", "08-LEF宏",
            "09-Liberty角", "10-Liberty单元", "RAW文件清单",
        ])
        with zipfile.ZipFile(archived_workbook) as archive:
            previous = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            strings = ["".join(text.text or "" for text in item.findall(f".//{{{MAIN_NS}}}t"))
                       for item in previous.findall(f"{{{MAIN_NS}}}si")]
            previous_sheet = ET.fromstring(archive.read("xl/worksheets/sheet5.xml"))
            old_findings = {}
            for row in previous_sheet.findall(f".//{{{MAIN_NS}}}row"):
                cells = {cell.attrib.get("r"): strings[int(cell.findtext(f"{{{MAIN_NS}}}v"))]
                         for cell in row.findall(f"{{{MAIN_NS}}}c")
                         if cell.attrib.get("t") == "s"}
                if row.attrib.get("r") in {"5", "6"}:
                    old_findings[row.attrib["r"]] = cells["F" + row.attrib["r"]]
        self.assertEqual([len(old_findings[str(row)]) for row in (5, 6)], [32767, 32767])

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "ip_review.xlsx"
            export_review_excel(model, output, scope_note="SRAM22 temporary evidence projection")
            workbook = _workbook_sheets(output)
            self.assertEqual(list(workbook), list(model))
            new_vdd = workbook["04-关注项"][5][6]
            new_vss = workbook["04-关注项"][6][6]
            for text, old_count, new_count in ((new_vdd, 544, 552), (new_vss, 532, 540)):
                self.assertLess(len(text), 300)
                self.assertIn(str(old_count), text)
                self.assertIn(str(new_count), text)
                self.assertIn("物理区域等价性未验证", text)
                self.assertNotIn("x1", text)
            self.assertEqual(workbook["04-关注项"][5][9], "evidence/lef_review.json")
            self.assertEqual(workbook["04-关注项"][6][9], "evidence/lef_review.json")

        self.assertEqual({path: _sha256(path) for path in checksums_before}, checksums_before)
        self.assertEqual(lef_evidence["sources"]["old"]["sha256"],
                         "b851c50331adc100c0d2499e3ea6bc1c75434ed0678b434edb29b40dac89b2e6")
        self.assertEqual(lef_evidence["sources"]["new"]["sha256"],
                         "9cdfd21aafbb2b1f6dabf2ebd8f59ce9bac83371bd23618eb93c7ae7b64050b3")

    def test_ihp_504_cell_instances_and_pin_issue_types_remain_visible(self):
        review, record_path, _lef_evidence_path, latest_path = _review_from_fixture(
            "IHP.sg13g2_stdcell__4e6f52ba1f04")
        before = {record_path: _sha256(record_path), latest_path: _sha256(latest_path),
                  latest_path.parent / "latest_workbook.json": _sha256(latest_path.parent / "latest_workbook.json")}

        model = build_workbook_model([review])
        summary = _review_summary(review)
        self.assertEqual(len(model["10-Liberty单元"]), 504)
        self.assertEqual(summary["quality_assessment"]["status"],
                         review["review_result"]["quality_status"])
        for kind in ("CHANGED", "MISMATCH", "UNVERIFIED"):
            self.assertEqual(summary["counts"][kind],
                             review["review_result"]["summary"]["counts"][kind])
        self.assertEqual(summary["counts"]["CHANGED"]["affected_objects"], 33)
        self.assertEqual(summary["counts"]["MISMATCH"],
                         {"finding_records": 2, "affected_objects": 504})
        self.assertEqual(summary["counts"]["UNVERIFIED"]["affected_objects"], 5)
        self.assertTrue(any("PG脚缺失" in row["差异类型"] for row in model["10-Liberty单元"]))
        self.assertTrue(any("信号Pin多出" in row["差异类型"] for row in model["10-Liberty单元"]))

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "ihp_review.xlsx"
            export_review_excel(model, output, scope_note="IHP temporary evidence projection")
            workbook = _workbook_sheets(output)
            self.assertEqual(sum(bool(row.get(4)) for number, row in workbook["10-Liberty单元"].items()
                                  if number >= 5), 504)

        self.assertEqual({path: _sha256(path) for path in before}, before)


if __name__ == "__main__":
    unittest.main()
