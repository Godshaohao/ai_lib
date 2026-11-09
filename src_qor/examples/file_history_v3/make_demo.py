"""Create a tiny local example without EDA vendor files."""
from __future__ import annotations
import gzip
import json
from pathlib import Path

root = Path(__file__).parent
raw = root / "example_data" / "Vendor_A" / "phy_128g"
for v in range(1, 5):
    (raw / f"V0{v}").mkdir(parents=True, exist_ok=True)

def put(v, rel, data):
    p = raw / f"V0{v}" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.name.endswith(".gz"):
        with gzip.open(p, "wb") as fh:
            fh.write(data.encode())
    else:
        p.write_text(data, encoding="utf-8")

put(1,"LEF/core.lef", "MACRO CORE\nSIZE 10 BY 10 ;\nEND CORE\n")
put(1,"LIB/tt.lib.gz", "library(tt) { cell(CORE) {} }\n")
put(1,"LIB/ff.lib.gz", "library(ff) { cell(CORE) {} }\n")
put(1,"LIB/ss.lib.gz", "library(ss) { cell(CORE) {} }\n")
put(2,"LIB/tt.lib.gz", "library(tt) { cell(CORE) { area: 2; } }\n")
put(3,"LEF/core.lef", "MACRO CORE\nSIZE 11 BY 10 ;\nEND CORE\n")
put(4,"LIB/ff.lib.gz", "library(ff) { cell(CORE) {} }\n")
formal = root / "example_data" / "formal_stage" / "IP"
(formal / "LIB").mkdir(parents=True, exist_ok=True)
(formal / "LEF").mkdir(parents=True, exist_ok=True)
for link, src in [
    (formal / "LEF" / "core.lef", raw / "V03" / "LEF" / "core.lef"),
    (formal / "LIB" / "tt.lib.gz", raw / "V02" / "LIB" / "tt.lib.gz"),
    (formal / "LIB" / "ff.lib.gz", raw / "V01" / "LIB" / "ff.lib.gz"),
]:
    if not link.exists() and not link.is_symlink():
        link.symlink_to(src.resolve())

cfg = {
    "ip_name": "dwc_128g_phy_pma_ns_txrx_top",
    "libraries": [
        {"library_id": "Vendor_A.phy_128g", "deliveries": [
            {"id": f"V0{i}", "order": i, "root": f"example_data/Vendor_A/phy_128g/V0{i}"}
            for i in range(1, 5)
        ]},
    ],
    "formal_manifest": "example_formal.list",
    "formal_groups": ["dwc_128g_phy_pma_ns_txrx_top"],
    "formal_root": "example_data/formal_stage",
}
(root / "example_config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
(root / "example_formal.list").write_text(
    "#dwc_128g_phy_pma_ns_txrx_top#\n"
    "core.lef IP/LEF/\n"
    "tt.lib.gz IP/LIB/\n"
    "ff.lib.gz IP/LIB/\n"
    "ss.lib.gz IP/LIB/\n",
    encoding="utf-8")
# The two input files from the actual workflow: business IP roster and formal manifest.
(root / "ipall.list").write_text(
    "dwc_128g_phy_pma_ns_txrx_top\n"
    "dwc_hdmi21_dp21_tx_phy_x4\n"
    "unknown_ip_not_delivered\n",
    encoding="utf-8")

batch_cfg = {
    "ip_list": "ipall.list",
    "raw_root": "example_data",  # Vendor/Library/V01,V02,...
    "formal_manifest": "example_formal.list",
    "formal_root": "example_data/formal_stage",
}
(root / "roster_config.json").write_text(json.dumps(batch_cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("Demo data ready: ipall.list + example_formal.list + roster_config.json")
