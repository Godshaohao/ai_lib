#!/usr/bin/env python3
"""Create a disposable synthetic IP roster, RAW deliveries, and formal links."""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
from pathlib import Path


SERDES = 'dwc_128g_phy_pma_ns_cm_serdes_top'
TXRX = 'dwc_128g_phy_pma_ns_txrx_top'


def lef(macro: str, width: int) -> str:
    return f'''VERSION 5.8 ;
BUSBITCHARS "[]" ;
DIVIDERCHAR "/" ;
MACRO {macro}
  CLASS BLOCK ;
  ORIGIN 0 0 ;
  SIZE {width} BY 10 ;
  PIN A
    DIRECTION INPUT ;
    USE SIGNAL ;
  END A
  PIN Z
    DIRECTION OUTPUT ;
    USE SIGNAL ;
  END Z
END {macro}
END LIBRARY
'''


def liberty(macro: str, corner: str, voltage: str, temperature: int) -> str:
    return f'''library ({corner}) {{
  operating_conditions ({corner}) {{ process : 1; voltage : {voltage}; temperature : {temperature}; }}
  cell ({macro}) {{ area : 10; pin (A) {{ direction : input; }} pin (Z) {{ direction : output; }} }}
}}
'''


def build(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=False)
    examples = Path(__file__).resolve().parent
    for name in ('ipall.list', 'formal_files.list'):
        shutil.copyfile(examples / name, root / name)
    config = {'ip_list': 'ipall.list', 'formal_manifest': 'formal_files.list',
              'raw_root': 'RAW', 'formal_root': 'lib_NL_demo'}
    (root / 'roster_config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    raw = root / 'RAW' / 'DemoVendor'
    formal = root / 'lib_NL_demo' / 'IP'

    def put(library: str, version: str, view: str, name: str, content: str) -> Path:
        path = raw / library / version / view / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name.endswith('.gz'):
            with gzip.open(path, 'wt', encoding='utf-8') as handle:
                handle.write(content)
        else:
            path.write_text(content, encoding='utf-8')
        return path

    def link(view: str, name: str, source: Path) -> None:
        target = formal / view / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source.resolve())

    a_lef = f'{SERDES}_merged.lef'
    a_tt = f'{SERDES}_tt0p75v25c_Nominal_pg.lib.gz'
    a_ff = f'{SERDES}_ff0p825vm40c_RCmax_pg.lib.gz'
    a_ss = f'{SERDES}_ss0p675v125c_RCmin_pg.lib.gz'
    put('serdes_physical', 'V01', 'LEF', a_lef, lef('SERDES_A', 10))
    new_lef = put('serdes_physical', 'V03', 'LEF', a_lef, lef('SERDES_A', 11))
    put('serdes_physical', 'V01', 'LIB', a_tt, liberty('SERDES_A', 'tt', '0.75', 25))
    new_tt = put('serdes_physical', 'V02', 'LIB', a_tt, liberty('SERDES_A', 'tt', '0.75', 25))
    old_ff = put('serdes_physical', 'V01', 'LIB', a_ff, liberty('SERDES_A', 'ff', '0.825', -40))
    put('serdes_physical', 'V03', 'LIB', a_ff, liberty('SERDES_A', 'ff', '0.825', -40))
    put('serdes_physical', 'V01', 'LIB', a_ss, liberty('SERDES_A', 'ss', '0.675', 125))
    link('LEF', a_lef, new_lef)
    link('LIB', a_tt, new_tt)
    link('LIB', a_ff, old_ff)
    for view, name in [('DB', f'{SERDES}_tt0p75v25c_Nominal_pg.db'),
                       ('VERILOG', f'{SERDES}_gate_level.v'),
                       ('GDS', f'{SERDES}.gds.gz'), ('SPICE', f'{SERDES}.cdl'),
                       ('NDM', f'{SERDES}_merged.ndm')]:
        source = put('serdes_physical', 'V01', view, name, f'SYNTHETIC DEMO {view}\n')
        link(view, name, source)

    b_lef = f'{TXRX}_merged.lef'
    b_lib = f'{TXRX}_tt0p75v25c_Nominal_pg.lib.gz'
    b_db = f'{TXRX}_ff0p825vm40c_RCmax_pg.db'
    put('txrx_physical', 'V01', 'LEF', b_lef, lef('TXRX_A', 8))
    link('LEF', b_lef, put('txrx_physical', 'V02', 'LEF', b_lef, lef('TXRX_A', 9)))
    link('LIB', b_lib, put('txrx_physical', 'V01', 'LIB', b_lib, liberty('TXRX_A', 'tt', '0.75', 25)))
    link('DB', b_db, put('txrx_physical', 'V01', 'DB', b_db, 'SYNTHETIC DEMO DB\n'))

    c_name = 'MXCML2CMOS.lef'
    put('MXCML2CMOS', 'V01', 'LEF', c_name, lef('MXCML2CMOS', 3))
    copy = formal / 'LEF' / c_name
    copy.write_text(lef('MXCML2CMOS', 3), encoding='utf-8')
    print(f'模拟数据已创建：{root}')


def main() -> None:
    parser = argparse.ArgumentParser(description='创建截图格式的独立模拟数据；目标目录必须不存在')
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    build(args.out.expanduser().resolve())


if __name__ == '__main__':
    main()
