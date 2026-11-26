"""Tests for A+ non-Formal delivery initialization with history folding window (`initial_delivery_tail`)."""
import json
from pathlib import Path
import tempfile
import unittest


def _lef(width: int) -> str:
    return (
        'VERSION 5.8 ;\n'
        'MACRO TOP_IP\n'
        f'  SIZE {width} BY 10 ;\n'
        '  PIN CLK\n'
        '    DIRECTION INPUT ;\n'
        '  END CLK\n'
        '  PIN DOUT\n'
        '    DIRECTION OUTPUT ;\n'
        '  END DOUT\n'
        'END TOP_IP\n'
        'END LIBRARY\n'
    )


_LIB = (
    'library(top_lib) {\n'
    '  cell(TOP_IP) {\n'
    '    pin(CLK) { direction : input; }\n'
    '    pin(DOUT) { direction : output; }\n'
    '  }\n'
    '}\n'
)


class DeliveryInitFoldTests(unittest.TestCase):
    def test_single_track_non_formal_folds_early_history_preserves_files_and_supports_lef_diff(self):
        from ai_lib_qor.application.path_batch import check_pending
        from ai_lib_qor.application.path_config import initial_delivery_tail
        from ai_lib_qor.application.path_refresh import refresh_all, refresh_l2

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()

            # 10 chronological deliveries with NO Formal NL symlinks at all:
            # - v01 delivers full set including GDS (never re-delivered later!)
            # - v04 adds DOC/release_note.txt (never re-delivered later!)
            # - v02..v10 are incremental LEF (+ LIB on v07 & v10) updates with width = 10 + i
            for i in range(1, 11):
                ver = f'202610{i:02d}_r{i:02d}'
                vdir = raw / 'V1/LPDDR6' / ver
                (vdir / 'LEF').mkdir(parents=True)
                (vdir / 'LEF/top.lef').write_text(_lef(10 + i), encoding='utf-8')
                if i in (1, 7, 10):
                    (vdir / 'LIB').mkdir(parents=True, exist_ok=True)
                    (vdir / 'LIB/top.lib').write_text(_LIB, encoding='utf-8')
                if i == 1:
                    (vdir / 'GDS').mkdir(parents=True, exist_ok=True)
                    (vdir / 'GDS/top.gds').write_text('gds-v01', encoding='utf-8')
                if i == 4:
                    (vdir / 'DOC').mkdir(parents=True, exist_ok=True)
                    (vdir / 'DOC/release_note.txt').write_text('note-v04', encoding='utf-8')

            (work / 'path_sources.json').write_text(json.dumps({
                'raw_root': str(raw),
                'nl_root': str(nl),
                'nl_version': 'NL1',
            }), encoding='utf-8')
            self.assertEqual(initial_delivery_tail(work, 'V1', 'LPDDR6'), 3)

            res = refresh_all(work)
            self.assertEqual(res['l1']['delivery_created'], 10)
            self.assertEqual(res['l1']['formal_created'], 0)
            # Default tail=3: fold v01..v07 into rev_0001, evolve v08/v09/v10 into rev_0002..rev_0004
            self.assertEqual(res['l2']['initialized'], 1)
            self.assertEqual(res['l2']['effective_published'], 3)

            folder = work / 'libraries/V1/LPDDR6'
            eff_files = sorted((folder / 'effective').glob('effective_LPDDR6_*.json'))
            self.assertEqual(len(eff_files), 4)
            rev1 = json.loads((folder / 'effective/effective_LPDDR6_001.json').read_text(encoding='utf-8'))
            rev4 = json.loads((folder / 'effective/effective_LPDDR6_004.json').read_text(encoding='utf-8'))

            # rev_0001 folded v01..v07: inherited GDS from v01, DOC from v04, LEF & LIB from v07!
            self.assertEqual(rev1['views']['GDS'], {'20261001_r01': ['GDS/top.gds']})
            self.assertEqual(rev1['views']['DOC'], {'20261004_r04': ['DOC/release_note.txt']})
            self.assertEqual(rev1['views']['LEF'], {'20261007_r07': ['LEF/top.lef']})
            self.assertEqual(rev1['views']['LIBERTY'], {'20261007_r07': ['LIB/top.lib']})

            # rev_0004 (latest) still has GDS(v01) + DOC(v04) + LEF(v10) + LIB(v10) — zero lost files!
            self.assertEqual(rev4['views']['GDS'], {'20261001_r01': ['GDS/top.gds']})
            self.assertEqual(rev4['views']['DOC'], {'20261004_r04': ['DOC/release_note.txt']})
            self.assertEqual(rev4['views']['LEF'], {'20261010_r10': ['LEF/top.lef']})
            self.assertEqual(rev4['views']['LIBERTY'], {'20261010_r10': ['LIB/top.lib']})

            # Deleting .auto_effective_state.json + re-running L2 MUST NOT replay v01..v10 (watermark in audit log)
            state_file = folder / 'log/.auto_effective_state.json'
            state_file.unlink()
            again = refresh_l2(work)
            self.assertEqual(again['initialized'], 0)
            self.assertEqual(again['effective_published'], 0)
            self.assertEqual(again['unchanged'], 1)

            # check_pending runs ONLY 1 check (rev_0004 vs rev_0003) with full LEF cross-version diff!
            chk = check_pending(work)
            self.assertEqual(len(chk['checked']), 1)
            self.assertEqual(chk['checked'][0]['revision'], 'rev_0004')
            report = json.loads((folder / 'log' / chk['checked'][0]['check']).read_text(encoding='utf-8'))
            self.assertEqual(report['baseline'], 'rev_0003')
            self.assertTrue(any(c['check_id'] == 'LEF_LIBERTY_PIN_MATCH' and c['result'] == 'PASS' for c in report['checks']))
            size_change = next(c for c in report['changes'] if c['attribute'] == 'SIZE')
            self.assertEqual((size_change['old_value'], size_change['new_value']), ([19.0, 10.0], [20.0, 10.0]))

            # Adding v11 later evolves naturally to rev_0005
            v11 = raw / 'V1/LPDDR6/20261011_r11'
            (v11 / 'LEF').mkdir(parents=True)
            (v11 / 'LEF/top.lef').write_text(_lef(21), encoding='utf-8')
            r_next = refresh_all(work, formal=False)
            self.assertEqual(r_next['l2']['effective_published'], 1)
            self.assertEqual((folder / 'latest_effective.json').readlink().name, 'effective_LPDDR6_005.json')

    def test_custom_tail_values_full_history_tail_one_and_multi_track_fold(self):
        from ai_lib_qor.application.path_refresh import refresh_all

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()

            # Lib 1: tail=1 on 6 deliveries -> rev_0001 folds v01..v05, rev_0002 = v06 (2 revs total)
            for i in range(1, 7):
                p = raw / f'V1/TAIL_ONE/202610{i:02d}_v{i}/LEF/a.lef'
                p.parent.mkdir(parents=True)
                p.write_text(_lef(10 + i), encoding='utf-8')

            # Lib 2: tail=0 on 5 deliveries -> pure Option A full expansion (5 revs total)
            for i in range(1, 6):
                p = raw / f'V1/FULL_HIST/202610{i:02d}_v{i}/LEF/a.lef'
                p.parent.mkdir(parents=True)
                p.write_text(_lef(10 + i), encoding='utf-8')

            # Lib 3: small 2-delivery lib with default tail=3 -> 2 revs (rev_0001=v1, rev_0002=v2)
            for i in range(1, 3):
                p = raw / f'V1/SMALL_TWO/202610{i:02d}_v{i}/LEF/a.lef'
                p.parent.mkdir(parents=True)
                p.write_text(_lef(10 + i), encoding='utf-8')

            # Lib 4: multi-track IP with 6 deliveries & default tail=3 -> 4 revs on track IP_A
            for i in range(1, 7):
                p = raw / f'V1/MULTI_NO_FORMAL/202610{i:02d}_IP_A_v{i}/LEF/a.lef'
                p.parent.mkdir(parents=True)
                p.write_text(_lef(20 + i), encoding='utf-8')

            (work / 'path_sources.json').write_text(json.dumps({
                'raw_root': str(raw),
                'nl_root': str(nl),
                'nl_version': 'NL1',
                'libraries': {
                    'V1': {
                        'TAIL_ONE': {'initial_delivery_tail': 1},
                        'FULL_HIST': {'initial_delivery_tail': 0},
                        'MULTI_NO_FORMAL': {'ip_type': 'PHY', 'ip_list': ['IP_A']},
                    }
                },
            }), encoding='utf-8')

            refresh_all(work)

            self.assertEqual(len(list((work / 'libraries/V1/TAIL_ONE/effective').glob('effective_*.json'))), 2)
            self.assertEqual(len(list((work / 'libraries/V1/FULL_HIST/effective').glob('effective_*.json'))), 5)
            self.assertEqual(len(list((work / 'libraries/V1/SMALL_TWO/effective').glob('effective_*.json'))), 2)
            mt_revs = sorted((work / 'libraries/V1/MULTI_NO_FORMAL/effective').glob('effective_MULTI_NO_FORMAL__IP_A_*.json'))
            self.assertEqual(len(mt_revs), 4)
            mt_rev1 = json.loads(mt_revs[0].read_text(encoding='utf-8'))
            self.assertEqual(mt_rev1['views']['LEF'], {'20261003_IP_A_v3': ['LEF/a.lef']})

    def test_check_and_overall_date_ip_naming_and_idempotent_dedup_reuse(self):
        from ai_lib_qor.application.minimal_checks import run_library, run_revision
        from ai_lib_qor.application.path_refresh import refresh_all

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw, nl, work = root / 'raw', root / 'NL1', root / 'work'
            nl.mkdir()
            work.mkdir()

            # Single-track library + multi-track business IP library
            for ver, w in (('20261001_v1', 10), ('20261002_v2', 12)):
                p = raw / 'V1/SRAM_A' / ver / 'LEF/a.lef'
                p.parent.mkdir(parents=True)
                p.write_text(_lef(w), encoding='utf-8')
                lb = raw / 'V1/SRAM_A' / ver / 'LIB/a.lib'
                lb.parent.mkdir(parents=True)
                lb.write_text(_LIB, encoding='utf-8')
                cdl = raw / 'V1/SRAM_A' / ver / 'CDL/a.cdl'
                cdl.parent.mkdir(parents=True)
                cdl.write_text('.SUBCKT TOP_IP CLK DOUT\n.ENDS TOP_IP\n', encoding='utf-8')

            for ver, w in (('20261001_DDR5_v1', 20), ('20261002_DDR5_v2', 22)):
                p = raw / 'V1/PHY_PKG' / ver / 'LEF/d.lef'
                p.parent.mkdir(parents=True)
                p.write_text(_lef(w), encoding='utf-8')
                lb = raw / 'V1/PHY_PKG' / ver / 'LIB/d.lib'
                lb.parent.mkdir(parents=True)
                lb.write_text(_LIB, encoding='utf-8')

            (work / 'path_sources.json').write_text(json.dumps({
                'raw_root': str(raw),
                'nl_root': str(nl),
                'nl_version': 'NL1',
                'libraries': {'V1': {'PHY_PKG': {'ip_type': 'PHY', 'ip_list': ['DDR5']}}},
            }), encoding='utf-8')
            refresh_all(work)

            # 1) Single-track check: clean date+library filename (no 32-char UUID), repeated checks reuse with ZERO junk
            r1 = run_revision(work, 'V1', 'SRAM_A', 'rev_0002', render=False)
            self.assertFalse(r1['reused'])
            self.assertRegex(Path(r1['check']).name, r'^check_SRAM_A_rev_0002_\d{8}\.json$')
            self.assertRegex(r1['run_id'], r'^\d{8}$')

            # Repeating with render=True reuses the same JSON and renders Excel in place (still 1 JSON, 1 XLSX)
            r2 = run_revision(work, 'V1', 'SRAM_A', 'rev_0002', render=True)
            self.assertTrue(r2['reused'])
            self.assertEqual(r2['check'], r1['check'])
            self.assertTrue(Path(r2['excel']).is_file())

            r3 = run_revision(work, 'V1', 'SRAM_A', 'rev_0002', render=True)
            self.assertTrue(r3['reused'])
            self.assertEqual(r3['check'], r1['check'])
            sram_log = work / 'libraries/V1/SRAM_A/log'
            self.assertEqual(len(list(sram_log.glob('check_*.json'))), 1)
            self.assertEqual(len(list(sram_log.glob('check_*.xlsx'))), 1)

            # 2) Same-day config change (enable CDL parsing) produces a distinct `_2` file without overwriting history
            cfg = json.loads((work / 'path_sources.json').read_text(encoding='utf-8'))
            cfg['skip_parse_views'] = []
            (work / 'path_sources.json').write_text(json.dumps(cfg), encoding='utf-8')
            r4 = run_revision(work, 'V1', 'SRAM_A', 'rev_0002', render=False)
            self.assertFalse(r4['reused'])
            self.assertRegex(Path(r4['check']).name, r'^check_SRAM_A_rev_0002_\d{8}_2\.json$')
            self.assertEqual(len(list(sram_log.glob('check_*.json'))), 2)

            # 3) Multi-track check & overall: clean date + business_ip naming + dedup reuse
            m1 = run_revision(work, 'V1', 'PHY_PKG', 'rev_0002', business_ip='DDR5', render=True)
            self.assertRegex(Path(m1['check']).name, r'^check__DDR5__rev_0002_\d{8}\.json$')
            m2 = run_revision(work, 'V1', 'PHY_PKG', 'rev_0002', business_ip='DDR5', render=True)
            self.assertTrue(m2['reused'])
            phy_log = work / 'libraries/V1/PHY_PKG/log'
            self.assertEqual(len(list(phy_log.glob('check__DDR5__*.json'))), 1)

            ov1 = run_library(work, 'V1', 'PHY_PKG', business_ip='DDR5', rerun=False)
            self.assertFalse(ov1['reused'])
            self.assertRegex(Path(ov1['overall']).name, r'^overall__DDR5__\d{8}\.json$')
            ov2 = run_library(work, 'V1', 'PHY_PKG', business_ip='DDR5', rerun=False)
            self.assertTrue(ov2['reused'])
            self.assertEqual(ov2['overall'], ov1['overall'])
            self.assertEqual(len(list(phy_log.glob('overall__DDR5__*.json'))), 1)


if __name__ == '__main__':
    unittest.main()
