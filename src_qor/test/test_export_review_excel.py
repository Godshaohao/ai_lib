import posixpath
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from lib_guard.export_review_excel import export_review_excel
from lib_guard.review_runner import _finding_rows


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _cell_text(workbook_path: Path, sheet_name: str, address: str) -> tuple[str, bool]:
    with zipfile.ZipFile(workbook_path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {item.attrib["Id"]: item.attrib["Target"]
                   for item in relationships.findall(f"{{{PKG_REL_NS}}}Relationship")}
        sheet = next(item for item in workbook.findall(f".//{{{MAIN_NS}}}sheet")
                     if item.attrib["name"] == sheet_name)
        target = targets[sheet.attrib[f"{{{REL_NS}}}id"]]
        sheet_path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else f"xl/{target}")
        worksheet = ET.fromstring(archive.read(sheet_path))
        cell = next(item for item in worksheet.findall(f".//{{{MAIN_NS}}}c")
                    if item.attrib.get("r") == address)
        formula = cell.find(f"{{{MAIN_NS}}}f") is not None
        if cell.attrib.get("t") == "s":
            shared = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            strings = ["".join(text.text or "" for text in item.findall(f".//{{{MAIN_NS}}}t"))
                       for item in shared.findall(f"{{{MAIN_NS}}}si")]
            return strings[int(cell.findtext(f"{{{MAIN_NS}}}v"))], formula
        inline = cell.find(f"{{{MAIN_NS}}}is")
        if inline is not None:
            return "".join(text.text or "" for text in inline.findall(f".//{{{MAIN_NS}}}t")), formula
        return cell.findtext(f"{{{MAIN_NS}}}v", ""), formula


class ExportReviewExcelTests(unittest.TestCase):
    def test_oversized_non_geometry_lef_value_is_rejected_without_truncation(self):
        finding = _finding_rows({"ip": {"id": "IP_A"}, "checks": {"lef_review": {
            "selected": True, "status": "COMPLETE", "result_ref": "evidence/lef_review.json",
            "result": {"comparison": {"changes": [{"macro": "MACRO_A", "field": "size",
                "old": "x" * 32768, "new": "unchanged"}]}}
        }}})
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "oversized_lef.xlsx"
            with self.assertRaises(ValueError) as raised:
                export_review_excel({"04-关注项": finding}, output)

            self.assertIn("Sheet=04-关注项", str(raised.exception))
            self.assertIn("实际长度=", str(raised.exception))
            self.assertIn("限制=32767", str(raised.exception))
            self.assertFalse(output.exists())

    def test_overlength_cell_fails_before_touching_existing_workbook(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "latest.xlsx"
            sentinel = b"previous complete workbook"
            output.write_bytes(sentinel)
            text = "SENSITIVE-" + "x" * (32768 - len("SENSITIVE-"))

            with self.assertRaises(ValueError) as raised:
                export_review_excel({"03-问答": [{"问题": "检查", "回答": text}]}, output)

            message = str(raised.exception)
            self.assertIn("Sheet=03-问答", message)
            self.assertIn("行=5", message)
            self.assertIn("列=3", message)
            self.assertIn("实际长度=32768", message)
            self.assertIn("限制=32767", message)
            self.assertNotIn("SENSITIVE", message)
            self.assertEqual(output.read_bytes(), sentinel)

    def test_exact_excel_cell_text_limit_is_written_without_truncation(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "boundary.xlsx"
            value = "x" * 32767

            export_review_excel({"03-问答": [{"问题": "边界", "回答": value}]}, output)

            actual, formula = _cell_text(output, "03-问答", "C5")
            self.assertEqual(len(actual), 32767)
            self.assertEqual(actual, value)
            self.assertFalse(formula)

    def test_formula_like_text_is_stored_as_literal_text(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "formula.xlsx"

            export_review_excel({"03-问答": [{"问题": "输入", "回答": "=SUM(1,2)"}]}, output)

            value, formula = _cell_text(output, "03-问答", "C5")
            self.assertEqual(value, "'=SUM(1,2)")
            self.assertFalse(formula)

    def test_dynamic_title_scope_note_and_header_are_length_checked(self):
        cases = (
            ("title", {"T" * 32768: []}, "scope"),
            ("scope_note", {"03-问答": [{"问题": "Q", "回答": "A"}]}, "s" * 32768),
            ("header", {"Custom": [{"H" * 32768: "value"}]}, "scope"),
        )
        for label, sheets, scope_note in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / "never-created.xlsx"
                if label == "title":
                    title = next(iter(sheets))
                    sheets = {title: [{"value": "x"}]}
                with self.assertRaises(ValueError):
                    export_review_excel(sheets, output, scope_note=scope_note)
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
