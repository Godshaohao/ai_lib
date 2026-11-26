"""Tests for multi-track business IP partitioning, track-isolated Effective/Checks/Acceptance, CLI & backward compatibility."""
import json
from pathlib import Path
import tempfile
import unittest

from ai_lib_qor.application.ip_partition import (
    load_partition,
    match_ips_in_text,
    partition_library_ips,
    partition_path,
)
from ai_lib_qor.application.minimal_checks import run_library, run_revision
from ai_lib_qor.application.minimal_effective import _history
from ai_lib_qor.application.minimal_file_index import index_manifest_matches, refresh_index
from ai_lib_qor.application.path_acceptance import (
    accept_revision,
    acceptance_status,
    acceptance_summary_by_ip_type,
    rollback_acceptance,
)
from ai_lib_qor.application.path_batch import check_pending
from ai_lib_qor.application.path_query import PathDataQuery, find_latest_check
from ai_lib_qor.application.path_refresh import refresh_all, refresh_l1, refresh_l2, refresh_status
from ai_lib_qor.application.path_storage import clean_cache
from ai_lib_qor.cli import parser as cli_parser, run as cli_run
from ai_lib_qor.versions.store import validate


def _lef_text(macro: str, w: float, h: float) -> str:
    return (
        f'VERSION 5.8 ;\n'
        f'MACRO {macro}\n'
        f'  SIZE {w:.2f} BY {h:.2f} ;\n'
        f'  PIN A\n'
        f'    DIRECTION INPUT ;\n'
        f'    USE SIGNAL ;\n'
        f'  END A\n'
        f'END {macro}\n'
        f'END LIBRARY\n'
    )


def _lib_text(cell: str) -> str:
    return (
        f'library({cell}_lib) {{\n'
        f'  cell({cell}) {{\n'
        f'    pin(A) {{ direction : input; }}\n'
        f'  }}\n'
        f'}}\n'
    )


def _write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


class TestIpPartitionAndMultiTrack(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.raw = self.root / 'RAW'
        self.nl = self.root / 'lib_NL2.5_3'
        self.work = self.root / 'work'
        self.raw.mkdir()
        self.nl.mkdir()
        self.work.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _write_config(self, libraries_cfg: dict):
        cfg = {
            'raw_root': str(self.raw),
            'nl_root': str(self.nl),
            'nl_version': 'NL2.5.3',
            'update_raw': True,
            'update_formal': True,
            'update_index': True,
            'auto_effective': True,
            'libraries': libraries_cfg,
        }
        (self.work / 'path_sources.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')

    def test_longest_match_subsumption_and_independent_conflict(self):
        ips = ['DDR5_PHY', 'DDR5_PHY_LITE', 'PCIE5_PHY']
        # Substring DDR5_PHY inside DDR5_PHY_LITE is subsumed -> unique hit
        self.assertEqual(match_ips_in_text('20261001_ddr5_phy_lite_v1', ips), ['DDR5_PHY_LITE'])
        # Independent occurrence of both DDR5_PHY_LITE and DDR5_PHY -> conflict
        self.assertEqual(
            sorted(match_ips_in_text('ddr5_phy_lite_plus_ddr5_phy', ips)),
            ['DDR5_PHY', 'DDR5_PHY_LITE'],
        )
        # Disjoint two IPs -> conflict
        self.assertEqual(
            sorted(match_ips_in_text('20261001_DDR5_PHY_and_PCIE5_PHY', ips)),
            ['DDR5_PHY', 'PCIE5_PHY'],
        )
        # Case-insensitive unique hit
        self.assertEqual(match_ips_in_text('pcie5_phy_top.lef', ips), ['PCIE5_PHY'])
        # No hit
        self.assertEqual(match_ips_in_text('20261001_misc_bundle', ips), [])

    def test_two_stage_partition_and_incremental_manual_preservation(self):
        lib_raw = self.raw / 'V1' / 'PHY_COMBO'
        # Stage 1: longest-name subsumption -> DDR5_PHY_LITE
        _write_file(lib_raw / '20261001_ddr5_phy_lite_r1/LEF/top.lef', _lef_text('LITE', 10.0, 20.0))
        # Stage 2a: core EDA file match -> DDR5_PHY
        _write_file(lib_raw / '20261002_rel_a/LEF/ddr5_phy.lef', _lef_text('DDR5', 12.0, 24.0))
        _write_file(lib_raw / '20261002_rel_a/DOC/readme.txt', 'generic note')
        # Stage 2b: fallback to all filenames -> PCIE5_PHY
        _write_file(lib_raw / '20261003_rel_b/LEF/common_macro.lef', _lef_text('PCIE', 8.0, 16.0))
        _write_file(lib_raw / '20261003_rel_b/DOC/pcie5_phy_guide.txt', 'guide')
        # Stage 1 conflict
        _write_file(lib_raw / '20261004_ddr5_phy_pcie5_phy/LEF/combo.lef', _lef_text('COMBO', 5.0, 5.0))
        # Stage 2a conflict (two core files match two different IPs)
        _write_file(lib_raw / '20261005_rel_c/LEF/ddr5_phy.lef', _lef_text('A', 1.0, 1.0))
        _write_file(lib_raw / '20261005_rel_c/LIB/pcie5_phy.lib', _lib_text('B'))
        # Unassigned
        _write_file(lib_raw / '20261006_rel_unknown/LEF/misc.lef', _lef_text('M', 2.0, 2.0))

        self._write_config({
            'V1': {
                'PHY_COMBO': {
                    'ip_type': 'PHY',
                    'ip_list': ['DDR5_PHY', 'DDR5_PHY_LITE', 'PCIE5_PHY'],
                }
            }
        })

        refresh_l1(self.work, formal=False)
        refresh_index(self.work, 'V1', 'PHY_COMBO')
        res1 = partition_library_ips(self.work, 'V1', 'PHY_COMBO')

        self.assertEqual(res1['state'], 'NEEDS_REVIEW')
        self.assertTrue(res1['changed'])
        self.assertEqual(res1['tracks']['DDR5_PHY_LITE'], ['20261001_ddr5_phy_lite_r1'])
        self.assertEqual(res1['tracks']['DDR5_PHY'], ['20261002_rel_a'])
        self.assertEqual(res1['tracks']['PCIE5_PHY'], ['20261003_rel_b'])
        self.assertEqual(res1['auto_trace']['20261001_ddr5_phy_lite_r1']['stage'], 'stage1_version_name')
        self.assertEqual(res1['auto_trace']['20261002_rel_a']['stage'], 'stage2_core_eda_files')
        self.assertEqual(res1['auto_trace']['20261003_rel_b']['stage'], 'stage2_all_files')

        conflict_vers = [c['version'] for c in res1['needs_review']['conflicts']]
        self.assertEqual(conflict_vers, ['20261004_ddr5_phy_pcie5_phy', '20261005_rel_c'])
        unassigned_vers = [u['version'] for u in res1['needs_review']['unassigned']]
        self.assertEqual(unassigned_vers, ['20261006_rel_unknown'])

        # Idempotent re-run must not change file mtime
        pfile = partition_path(self.work, 'V1', 'PHY_COMBO')
        mtime_before = pfile.stat().st_mtime_ns
        res_idemp = partition_library_ips(self.work, 'V1', 'PHY_COMBO')
        self.assertFalse(res_idemp['changed'])
        self.assertEqual(pfile.stat().st_mtime_ns, mtime_before)

        # Simulate human editing work/libraries/V1/PHY_COMBO/ip_partition.json:
        # 1) manually resolve conflicts & unassigned into tracks
        # 2) choose a custom version order in DDR5_PHY
        edited = json.loads(pfile.read_text(encoding='utf-8'))
        edited['tracks']['DDR5_PHY'] = ['20261004_ddr5_phy_pcie5_phy', '20261002_rel_a', '20261005_rel_c']
        edited['tracks']['PCIE5_PHY'] = ['20261006_rel_unknown', '20261003_rel_b']
        pfile.write_text(json.dumps(edited, ensure_ascii=False, indent=2), encoding='utf-8')

        # Add a brand-new delivery and re-run partition incrementally
        _write_file(lib_raw / '20261010_pcie5_phy_r2/LEF/common_macro.lef', _lef_text('PCIE', 9.0, 16.0))
        refresh_l1(self.work, formal=False)
        refresh_index(self.work, 'V1', 'PHY_COMBO')
        res2 = partition_library_ips(self.work, 'V1', 'PHY_COMBO')

        self.assertEqual(res2['state'], 'UPDATED')
        self.assertEqual(res2['needs_review'], {'conflicts': [], 'unassigned': []})
        # Exact human order & assignments MUST be preserved untouched
        self.assertEqual(
            res2['tracks']['DDR5_PHY'],
            ['20261004_ddr5_phy_pcie5_phy', '20261002_rel_a', '20261005_rel_c'],
        )
        # New version appended after human-confirmed order
        self.assertEqual(
            res2['tracks']['PCIE5_PHY'],
            ['20261006_rel_unknown', '20261003_rel_b', '20261010_pcie5_phy_r2'],
        )
        self.assertEqual(len(res2['newly_assigned']), 1)
        self.assertEqual(res2['newly_assigned'][0]['version'], '20261010_pcie5_phy_r2')

    def test_same_library_name_across_vendors_isolated_and_legacy_migrated(self):
        from ai_lib_qor.application.ip_partition import legacy_partition_path
        from ai_lib_qor.application.path_query import query_json_inventory
        from ai_lib_qor.application.path_storage import clean_cache, storage_stats

        # 1) Same library name under two different vendors (Metax/rtavfs & Vendor_B/rtavfs) stay strictly isolated
        _write_file(self.raw / 'Metax' / 'rtavfs' / '20261001_ip_m1/LEF/m1.lef', _lef_text('M1', 1.0, 1.0))
        _write_file(self.raw / 'Vendor_B' / 'rtavfs' / '20261001_ip_b1/LEF/b1.lef', _lef_text('B1', 2.0, 2.0))
        # 2) Legacy root file scenario (Vendor_B/pvt owns legacy work/ip_partition_pvt.json; Vendor_G/pvt must NOT collide)
        _write_file(self.raw / 'Vendor_B' / 'pvt' / '20261001_pvt_b_v1/LEF/pb1.lef', _lef_text('PB1', 1.0, 1.0))
        _write_file(self.raw / 'Vendor_B' / 'pvt' / '20261002_pvt_b_v2/LEF/pb2.lef', _lef_text('PB2', 1.0, 2.0))
        _write_file(self.raw / 'Vendor_G' / 'pvt' / '20261001_pvt_g_v1/LEF/pg1.lef', _lef_text('PG1', 3.0, 3.0))

        self._write_config({
            'Metax': {'rtavfs': {'ip_type': 'ANALOG', 'ip_list': ['IP_M1']}},
            'Vendor_B': {
                'rtavfs': {'ip_type': 'ANALOG', 'ip_list': ['IP_B1']},
                'pvt': {'ip_type': 'PVT', 'ip_list': ['PVT_B']},
            },
            'Vendor_G': {'pvt': {'ip_type': 'PVT', 'ip_list': ['PVT_G']}},
        })
        refresh_l1(self.work, formal=False)
        for v, lib in (('Metax', 'rtavfs'), ('Vendor_B', 'rtavfs'), ('Vendor_B', 'pvt'), ('Vendor_G', 'pvt')):
            refresh_index(self.work, v, lib)

        # Both vendors partition `rtavfs` cleanly into separate per-library ip_partition.json files
        r_m = partition_library_ips(self.work, 'Metax', 'rtavfs')
        r_b = partition_library_ips(self.work, 'Vendor_B', 'rtavfs')
        p_m = partition_path(self.work, 'Metax', 'rtavfs')
        p_b = partition_path(self.work, 'Vendor_B', 'rtavfs')
        self.assertNotEqual(p_m, p_b)
        self.assertTrue(p_m.is_file() and p_b.is_file())
        self.assertEqual(r_m['tracks'], {'IP_M1': ['20261001_ip_m1']})
        self.assertEqual(r_b['tracks'], {'IP_B1': ['20261001_ip_b1']})

        # Seed a legacy root work/ip_partition_pvt.json owned by Vendor_B with a human-chosen custom order
        legacy_pvt = legacy_partition_path(self.work, 'pvt')
        legacy_pvt.write_text(json.dumps({
            'schema_version': 'ip_partition.v1',
            'vendor': 'Vendor_B',
            'library': 'pvt',
            'ip_type': 'PVT',
            'ip_list': ['PVT_B'],
            'tracks': {'PVT_B': ['20261002_pvt_b_v2', '20261001_pvt_b_v1']},
            'needs_review': {'conflicts': [], 'unassigned': []},
            'auto_trace': {},
            'updated_at': '2026-11-24T00:00:00Z',
        }, ensure_ascii=False, indent=2), encoding='utf-8')

        # Vendor_B reads legacy human order; Vendor_G ignores Vendor_B's legacy file without crashing!
        loaded_b = load_partition(self.work, 'Vendor_B', 'pvt')
        self.assertIsNotNone(loaded_b)
        self.assertEqual(loaded_b['tracks']['PVT_B'], ['20261002_pvt_b_v2', '20261001_pvt_b_v1'])
        self.assertIsNone(load_partition(self.work, 'Vendor_G', 'pvt'))

        # JSON inventory must NOT show Vendor_B's legacy file under Vendor_G/pvt
        inv_g_before = query_json_inventory(self.work, vendor='Vendor_G', library='pvt')
        self.assertFalse(any(row['category'] == '业务 IP 分轨配置' for row in inv_g_before['rows']))

        # Partitioning Vendor_B migrates losslessly to libraries/Vendor_B/pvt/ip_partition.json preserving custom order
        res_pb = partition_library_ips(self.work, 'Vendor_B', 'pvt')
        self.assertTrue(res_pb['migrated_from_legacy'])
        self.assertEqual(res_pb['tracks']['PVT_B'], ['20261002_pvt_b_v2', '20261001_pvt_b_v1'])
        self.assertTrue(partition_path(self.work, 'Vendor_B', 'pvt').is_file())
        self.assertTrue(legacy_pvt.is_file())  # legacy file preserved untouched

        # Partitioning Vendor_G creates its own isolated libraries/Vendor_G/pvt/ip_partition.json
        res_pg = partition_library_ips(self.work, 'Vendor_G', 'pvt')
        self.assertFalse(res_pg['migrated_from_legacy'])
        self.assertEqual(res_pg['tracks'], {'PVT_G': ['20261001_pvt_g_v1']})
        self.assertTrue(partition_path(self.work, 'Vendor_G', 'pvt').is_file())

        # Storage stats classify ip_partition.json as authoritative config (never legacy_root, never deleted by clean_cache)
        st_m = storage_stats(self.work, vendor='Metax', library='rtavfs')
        self.assertGreater(st_m['libraries'][0]['bytes_by_kind']['config'], 0)
        self.assertEqual(st_m['libraries'][0]['legacy_root_file_count'], 0)
        clean_cache(self.work, vendor='Metax', library='rtavfs', dry_run=False)
        self.assertTrue(p_m.is_file())

        # Corrupting a per-library ip_partition.json with wrong vendor or duplicate track version is still strictly rejected
        bad_vendor = json.loads(p_m.read_text(encoding='utf-8'))
        bad_vendor['vendor'] = 'OTHER_VENDOR'
        p_m.write_text(json.dumps(bad_vendor), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '跨供应商'):
            load_partition(self.work, 'Metax', 'rtavfs')

        bad_dup = json.loads(p_b.read_text(encoding='utf-8'))
        bad_dup['tracks'] = {'IP_B1': ['20261001_ip_b1'], 'IP_B2': ['20261001_ip_b1']}
        p_b.write_text(json.dumps(bad_dup), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '同时出现在多个轨道'):
            load_partition(self.work, 'Vendor_B', 'rtavfs')

    def test_multi_track_effective_checks_acceptance_storage_and_cli(self):
        lib_raw = self.raw / 'V1' / 'PHY_MULTI'
        # DDR5_PHY v1 & v2 (macro height changes from 20.0 -> 25.0, plus v1 has a GDS missing in v2 -> must NOT delete)
        _write_file(lib_raw / '20261001_ddr5_phy_v1/LEF/ddr5.lef', _lef_text('DDR5_M', 10.0, 20.0))
        _write_file(lib_raw / '20261001_ddr5_phy_v1/LIB/ddr5.lib', _lib_text('DDR5_M'))
        _write_file(lib_raw / '20261001_ddr5_phy_v1/GDS/ddr5.gds', 'gds-bytes')
        _write_file(lib_raw / '20261002_ddr5_phy_v2/LEF/ddr5.lef', _lef_text('DDR5_M', 10.0, 25.0))
        _write_file(lib_raw / '20261002_ddr5_phy_v2/LIB/ddr5.lib', _lib_text('DDR5_M'))
        _write_file(lib_raw / '20261002_ddr5_phy_v2/DOC/ddr5_extra.txt', 'unadopted doc')
        # PCIE5_PHY v1 (completely different macro & files)
        _write_file(lib_raw / '20261003_pcie5_phy_v1/LEF/pcie5.lef', _lef_text('PCIE5_M', 30.0, 40.0))
        _write_file(lib_raw / '20261003_pcie5_phy_v1/LIB/pcie5.lib', _lib_text('PCIE5_M'))
        # Unassigned version (triggers needs_review)
        _write_file(lib_raw / '20261004_unassigned/LEF/unknown.lef', _lef_text('UNK', 1.0, 1.0))

        self._write_config({
            'V1': {
                'PHY_MULTI': {
                    'ip_type': 'PHY',
                    'ip_list': ['DDR5_PHY', 'PCIE5_PHY'],
                }
            }
        })

        # 1) strict_partition=True pauses L2 evolution when needs_review is non-empty
        r_strict = refresh_all(self.work, formal=False, strict_partition=True)
        self.assertTrue(any('严格模式暂停' in w for w in r_strict['warnings']))
        folder = self.work / 'libraries/V1/PHY_MULTI'
        self.assertEqual(_history(folder, 'PHY_MULTI', business_ip='DDR5_PHY'), [])

        # 2) Default strict_partition=False skips unassigned and builds isolated tracks
        r_norm = refresh_l2(self.work)
        self.assertTrue(any('跳过未归类项' in w for w in r_norm['warnings']))
        self.assertEqual(r_norm['initialized'], 2)
        self.assertEqual(r_norm['effective_published'], 1)  # DDR5_PHY rev_0002

        ddr_hist = _history(folder, 'PHY_MULTI', business_ip='DDR5_PHY')
        pcie_hist = _history(folder, 'PHY_MULTI', business_ip='PCIE5_PHY')
        self.assertEqual([h[2]['revision'] for h in ddr_hist], ['rev_0001', 'rev_0002'])
        self.assertEqual([h[2]['revision'] for h in pcie_hist], ['rev_0001'])
        self.assertEqual(ddr_hist[0][1].name, 'effective_PHY_MULTI__DDR5_PHY_001.json')
        self.assertEqual(ddr_hist[1][1].name, 'effective_PHY_MULTI__DDR5_PHY_002.json')
        self.assertEqual(pcie_hist[0][1].name, 'effective_PHY_MULTI__PCIE5_PHY_001.json')

        # Schema & track metadata verified; missing GDS in v2 is inherited, and new DOC in higher version v2 is auto-merged
        validate(ddr_hist[1][2], 'effective_path')
        self.assertEqual(ddr_hist[1][2]['business_ip'], 'DDR5_PHY')
        self.assertEqual(ddr_hist[1][2]['ip_type'], 'PHY')
        self.assertEqual(ddr_hist[1][2]['track_id'], 'V1/PHY_MULTI::DDR5_PHY')
        self.assertIn('GDS', ddr_hist[1][2]['views'])
        self.assertEqual(ddr_hist[1][2]['views']['DOC'], {'20261002_ddr5_phy_v2': ['DOC/ddr5_extra.txt']})

        # Pure file_index.json untouched by minimal_file_index.py and stays FRESH
        matched, _ = index_manifest_matches(self.work, 'V1', 'PHY_MULTI')
        self.assertTrue(matched)
        idx_obj = PathDataQuery(self.work).index('V1', 'PHY_MULTI')
        self.assertEqual(idx_obj['revisions'], [])

        # 3) Checks strictly isolated per track; cross-IP / missing --ip rejected
        with self.assertRaisesRegex(ValueError, '多业务 IP 分轨'):
            run_revision(self.work, 'V1', 'PHY_MULTI', 'rev_0001', render=False)
        with self.assertRaisesRegex(ValueError, '禁止跨业务 IP 对比'):
            PathDataQuery(self.work).get_check_context('V1', 'PHY_MULTI', 'rev_0001', baseline='rev_0002', business_ip='PCIE5_PHY')

        chk_ddr = run_revision(self.work, 'V1', 'PHY_MULTI', 'rev_0002', business_ip='DDR5_PHY', render=False)
        self.assertEqual(chk_ddr['business_ip'], 'DDR5_PHY')
        ddr_report = json.loads(Path(chk_ddr['check']).read_text(encoding='utf-8'))
        validate(ddr_report, 'check_result_path')
        self.assertEqual(ddr_report['business_ip'], 'DDR5_PHY')
        self.assertEqual(ddr_report['baseline'], 'rev_0001')
        # Confirms LEF_MACRO_DIFF ran strictly inside DDR5_PHY track (height 20 -> 25)
        self.assertTrue(any(ch['object_name'] == 'DDR5_M' for ch in ddr_report['changes']))
        self.assertFalse(any(ch['object_name'] == 'PCIE5_M' for ch in ddr_report['changes']))
        self.assertTrue((folder / 'latest_check__DDR5_PHY.json').is_symlink())
        self.assertFalse((folder / 'latest_check.json').exists())

        # check_pending runs ONLY remaining PCIE5_PHY track, skips already-checked DDR5_PHY
        pend1 = check_pending(self.work, ip_type='PHY')
        self.assertEqual(pend1['checked_count'], 1)
        self.assertEqual(pend1['checked'][0]['business_ip'], 'PCIE5_PHY')
        self.assertEqual(pend1['skipped_already_checked_count'], 1)
        self.assertEqual(pend1['skipped_already_checked'][0]['business_ip'], 'DDR5_PHY')

        # Second check_pending skips BOTH tracks
        pend2 = check_pending(self.work, ip_type='PHY')
        self.assertEqual(pend2['checked_count'], 0)
        self.assertEqual(pend2['skipped_already_checked_count'], 2)

        # Lookup isolation by business_ip
        hit_ddr = find_latest_check(self.work, 'V1', 'PHY_MULTI', revision='rev_0002', business_ip='DDR5_PHY')
        hit_pcie = find_latest_check(self.work, 'V1', 'PHY_MULTI', revision='rev_0001', business_ip='PCIE5_PHY')
        self.assertIsNotNone(hit_ddr)
        self.assertIsNotNone(hit_pcie)
        self.assertEqual(hit_ddr['business_ip'], 'DDR5_PHY')
        self.assertEqual(hit_pcie['business_ip'], 'PCIE5_PHY')
        self.assertIsNone(find_latest_check(self.work, 'V1', 'PHY_MULTI', revision='rev_0002', business_ip='PCIE5_PHY'))

        # clean_cache(--orphan-facts) MUST preserve shared facts referenced by multi-track checks
        facts_before = sorted((folder / 'facts').glob('fact_ca_*.json.gz'))
        self.assertGreater(len(facts_before), 0)
        cleaned = clean_cache(self.work, clean_excel=False, clean_orphan_facts=True, dry_run=False)
        self.assertEqual(cleaned['removed_count'], 0)
        self.assertEqual(sorted((folder / 'facts').glob('fact_ca_*.json.gz')), facts_before)

        # 4) Track-isolated acceptance & ip_type aggregation
        acc_res = accept_revision(self.work, 'V1', 'PHY_MULTI', 'rev_0002', actor='qa', reason='DDR5 审核通过', business_ip='DDR5_PHY')
        self.assertEqual(acc_res['state'], 'ACCEPTED')
        self.assertEqual(acceptance_status(self.work, 'V1', 'PHY_MULTI', business_ip='DDR5_PHY')['accepted_revision'], 'rev_0002')
        self.assertIsNone(acceptance_status(self.work, 'V1', 'PHY_MULTI', business_ip='PCIE5_PHY')['accepted_revision'])

        rb_res = rollback_acceptance(self.work, 'V1', 'PHY_MULTI', 'rev_0001', actor='qa', reason='回退复测', business_ip='DDR5_PHY')
        self.assertEqual(rb_res['state'], 'ROLLED_BACK')
        self.assertEqual(acceptance_status(self.work, 'V1', 'PHY_MULTI', business_ip='DDR5_PHY')['accepted_revision'], 'rev_0001')

        agg = acceptance_summary_by_ip_type(self.work, ip_type='PHY')
        self.assertEqual(agg['total_tracks'], 2)
        self.assertEqual(agg['accepted_tracks'], 1)

        # 5) run_library scoped to one track
        ov = run_library(self.work, 'V1', 'PHY_MULTI', business_ip='DDR5_PHY', rerun=False)
        self.assertEqual(ov['business_ip'], 'DDR5_PHY')
        self.assertEqual([v['revision'] for v in ov['versions']], ['rev_0001', 'rev_0002'])
        self.assertTrue((folder / 'latest_overall__DDR5_PHY.xlsx').is_symlink())

        # 6) CLI commands roundtrip
        p = cli_parser()
        cli_part = cli_run(p.parse_args(['partition-ips', '--work', str(self.work), '--vendor', 'V1', '--library', 'PHY_MULTI']))
        self.assertEqual(cli_part['library'], 'PHY_MULTI')
        cli_tracks = cli_run(p.parse_args(['path-tracks', '--work', str(self.work), '--ip-type', 'PHY']))
        self.assertEqual(cli_tracks['count'], 2)
        cli_acc = cli_run(p.parse_args(['acceptance-status', '--work', str(self.work), '--ip-type', 'PHY']))
        self.assertEqual(cli_acc['accepted_tracks'], 1)
        cli_ctx = cli_run(p.parse_args(['path-check-context', '--work', str(self.work), '--vendor', 'V1', '--library', 'PHY_MULTI', '--revision', 'rev_0002', '--ip', 'DDR5_PHY']))
        self.assertEqual(cli_ctx['business_ip'], 'DDR5_PHY')
        self.assertEqual(cli_ctx['baseline'], 'rev_0001')

        st = refresh_status(self.work)
        self.assertTrue(st['libraries'][0]['is_multi_track'])
        self.assertEqual(st['libraries'][0]['ip_type'], 'PHY')

    def test_single_track_backward_compatibility_unchanged(self):
        lib_raw = self.raw / 'V1' / 'STD_SINGLE'
        v1_lef = lib_raw / '20261001_v1/LEF/cell.lef'
        _write_file(v1_lef, _lef_text('CELL1', 5.0, 5.0))
        _write_file(lib_raw / '20261001_v1/LIB/cell.lib', _lib_text('CELL1'))
        # Create Formal symlink for standard single-track auto-init
        link = self.nl / 'IP' / 'LEF' / 'cell.lef'
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(v1_lef)

        self._write_config({})
        res = refresh_all(self.work)
        self.assertEqual(res['l2']['initialized'], 1)
        self.assertFalse(partition_path(self.work, 'V1', 'STD_SINGLE').exists())

        folder = self.work / 'libraries/V1/STD_SINGLE'
        eff_file = folder / 'effective/effective_STD_SINGLE_001.json'
        self.assertTrue(eff_file.is_file())
        eff_data = json.loads(eff_file.read_text(encoding='utf-8'))
        self.assertNotIn('business_ip', eff_data)
        self.assertNotIn('track_id', eff_data)

        chk = run_revision(self.work, 'V1', 'STD_SINGLE', 'rev_0001', render=False)
        self.assertRegex(Path(chk['check']).name, r'^check_STD_SINGLE_rev_0001_\d{8}(?:_\d+)?\.json$')
        chk_data = json.loads(Path(chk['check']).read_text(encoding='utf-8'))
        self.assertNotIn('business_ip', chk_data)

    def test_formal_subset_init_and_manual_cross_track_guard(self):
        from ai_lib_qor.application.minimal_effective import preview_update

        lib_raw = self.raw / 'V1' / 'PHY_FORMAL'
        ddr_lef = lib_raw / '20261001_ddr5_phy_v1/LEF/ddr5.lef'
        _write_file(ddr_lef, _lef_text('DDR5_M', 10.0, 20.0))
        _write_file(lib_raw / '20261001_ddr5_phy_v1/LIB/ddr5.lib', _lib_text('DDR5_M'))
        _write_file(lib_raw / '20261002_pcie5_phy_v1/LEF/pcie5.lef', _lef_text('PCIE5_M', 30.0, 40.0))

        # Formal snapshot links ONLY ddr5.lef (subset of DDR5_PHY, none of PCIE5_PHY)
        link = self.nl / 'IP' / 'LEF' / 'ddr5.lef'
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(ddr_lef)

        self._write_config({
            'V1': {
                'PHY_FORMAL': {
                    'ip_type': 'PHY',
                    'ip_list': ['DDR5_PHY', 'PCIE5_PHY'],
                }
            }
        })

        res = refresh_all(self.work)
        self.assertEqual(res['l2']['initialized'], 2)
        folder = self.work / 'libraries/V1/PHY_FORMAL'
        ddr_hist = _history(folder, 'PHY_FORMAL', business_ip='DDR5_PHY')
        pcie_hist = _history(folder, 'PHY_FORMAL', business_ip='PCIE5_PHY')
        # DDR5_PHY initialized from Formal subset -> only LEF (not LIB)
        self.assertEqual(list(ddr_hist[0][2]['views'].keys()), ['LEF'])
        # PCIE5_PHY had no Formal coverage -> initialized from track head delivery
        self.assertEqual(list(pcie_hist[0][2]['views'].keys()), ['LEF'])

        # Manual preview_update on DDR5_PHY must REJECT referencing PCIE5_PHY's delivery version
        with self.assertRaisesRegex(ValueError, '不属于业务 IP 轨道 DDR5_PHY'):
            preview_update(
                self.work,
                'V1',
                'PHY_FORMAL',
                {'set': [{'view': 'LEF', 'version': '20261002_pcie5_phy_v1', 'path': 'LEF/pcie5.lef'}], 'remove': []},
                business_ip='DDR5_PHY',
            )

    def test_multitrack_excel_reports_and_overview_ip_type_rollup(self):
        import openpyxl
        from ai_lib_qor.reporting.check_renderer import render_excel_from_check, render_overall_excel_from_saved
        from ai_lib_qor.reporting.work_overview_excel import render_work_overview_excel

        # Library 1: multi-track PHY library with 2 IPs + 1 unassigned delivery (needs_review)
        phy_raw = self.raw / 'V1' / 'PHY_EXCEL'
        _write_file(phy_raw / '20261001_ddr5_phy_v1/LEF/ddr5.lef', _lef_text('DDR5_M', 10.0, 20.0))
        _write_file(phy_raw / '20261001_ddr5_phy_v1/LIB/ddr5.lib', _lib_text('DDR5_M'))
        _write_file(phy_raw / '20261005_ddr5_phy_v2/LEF/ddr5.lef', _lef_text('DDR5_M', 10.0, 24.0))
        _write_file(phy_raw / '20261005_ddr5_phy_v2/LIB/ddr5.lib', _lib_text('DDR5_M'))
        _write_file(phy_raw / '20261002_pcie5_phy_v1/LEF/pcie5.lef', _lef_text('PCIE5_M', 30.0, 40.0))
        _write_file(phy_raw / '20261002_pcie5_phy_v1/LIB/pcie5.lib', _lib_text('PCIE5_M'))
        _write_file(phy_raw / '20261009_misc_v1/DOC/readme.txt', 'unmatched\n')

        # Library 2: single-track SRAM library with ip_type=SRAM (no ip_list)
        sram_raw = self.raw / 'V2' / 'SRAM_SINGLE'
        sram_lef = sram_raw / '20261001_v1/LEF/sram.lef'
        _write_file(sram_lef, _lef_text('SRAM_M', 5.0, 6.0))
        _write_file(sram_raw / '20261001_v1/LIB/sram.lib', _lib_text('SRAM_M'))
        link = self.nl / 'IP' / 'LEF' / 'sram.lef'
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(sram_lef)

        self._write_config({
            'V1': {'PHY_EXCEL': {'ip_type': 'PHY', 'ip_list': ['DDR5_PHY', 'PCIE5_PHY']}},
            'V2': {'SRAM_SINGLE': {'ip_type': 'SRAM'}},
        })
        refresh_all(self.work)

        # Single-revision Excel rendering on multi-track DDR5_PHY rev_0002 (verifies facts_pool track projection!)
        chk = run_revision(self.work, 'V1', 'PHY_EXCEL', 'rev_0002', business_ip='DDR5_PHY', render=True)
        accept_revision(self.work, 'V1', 'PHY_EXCEL', 'rev_0002', actor='qa', reason='DDR5 放行', business_ip='DDR5_PHY')
        re_xlsx = self.root / 'ddr5_rerender.xlsx'
        render_excel_from_check(self.work, 'V1', 'PHY_EXCEL', Path(chk['check']).name, re_xlsx)
        wb = openpyxl.load_workbook(re_xlsx, data_only=True)
        ov_text = '\n'.join(str(v) for row in wb['00-决策概览'].iter_rows(values_only=True) for v in row if v is not None)
        self.assertIn('DDR5_PHY', ov_text)
        self.assertIn('PHY', ov_text)
        self.assertIn('当前版本已采纳', ov_text)
        sh2 = list(wb['02-文件版本矩阵'].iter_rows(min_row=6, values_only=True))
        ddr_lef_row = next(r for r in sh2 if r[2] == 'LEF/ddr5.lef')
        self.assertEqual(ddr_lef_row[0], '当前有效')
        self.assertEqual(ddr_lef_row[3], '来源变化')
        self.assertEqual(ddr_lef_row[7], '内容变化')

        # Multi-revision Overall Excel + read-only re-render for DDR5_PHY
        ov = run_library(self.work, 'V1', 'PHY_EXCEL', business_ip='DDR5_PHY', rerun=False)
        ov_re = self.root / 'ddr5_overall_re.xlsx'
        render_overall_excel_from_saved(self.work, 'V1', 'PHY_EXCEL', Path(ov['overall']).name, ov_re)
        wb_ov = openpyxl.load_workbook(ov_re, data_only=True)
        self.assertIn('DDR5_PHY', str(wb_ov['00-版本运行汇总']['A1'].value))
        self.assertIn('IP 类型: PHY', str(wb_ov['00-版本运行汇总']['A2'].value))
        ov_rows = list(wb_ov['00-版本运行汇总'].iter_rows(min_row=6, values_only=True))
        self.assertEqual([r[0] for r in ov_rows], ['rev_0001', 'rev_0002'])
        self.assertEqual(ov_rows[1][1], '最新且已采纳')

        # Workspace Overview Excel: 3 sheets including 02-IP类型汇总, per-track rows, P2 · 分轨 todo
        work_xlsx = self.root / 'work_overview_multi.xlsx'
        res = render_work_overview_excel(self.work, work_xlsx, overwrite=True)
        self.assertEqual(res['library_count'], 2)
        self.assertEqual(res['track_row_count'], 3)  # DDR5_PHY, PCIE5_PHY, SRAM_SINGLE
        wb_w = openpyxl.load_workbook(work_xlsx, data_only=True)
        self.assertEqual(wb_w.sheetnames, ['00-全库总览', '01-待处理与风险清单', '02-IP类型汇总'])
        rows0 = list(wb_w['00-全库总览'].iter_rows(min_row=7, values_only=True))
        self.assertEqual([(r[1], r[16], r[17]) for r in rows0], [
            ('PHY_EXCEL', 'PHY', 'DDR5_PHY'),
            ('PHY_EXCEL', 'PHY', 'PCIE5_PHY'),
            ('SRAM_SINGLE', 'SRAM', '单轨'),
        ])
        todos = list(wb_w['01-待处理与风险清单'].iter_rows(min_row=4, values_only=True))
        self.assertTrue(any(r[1] == '分轨待复核' and r[3] == 'PHY_EXCEL' for r in todos))
        ip_rollup = {r[0]: r for r in wb_w['02-IP类型汇总'].iter_rows(min_row=4, values_only=True)}
        self.assertEqual(ip_rollup['PHY'][2], 2)   # 2 tracks
        self.assertEqual(ip_rollup['PHY'][4], 1)   # 1 accepted track
        self.assertEqual(ip_rollup['PHY'][9], 1)   # 1 needs_review
        self.assertEqual(ip_rollup['SRAM'][2], 1)

    def test_multitrack_web_workbench_and_api_flows(self):
        from ai_lib_qor.workbench.path_app import create_path_app

        lib_raw = self.raw / 'V1' / 'PHY_WEB'
        _write_file(lib_raw / '20261001_ddr5_phy_v1/LEF/ddr5.lef', _lef_text('DDR5_M', 10.0, 20.0))
        _write_file(lib_raw / '20261001_ddr5_phy_v1/LIB/ddr5.lib', _lib_text('DDR5_M'))
        _write_file(lib_raw / '20261005_ddr5_phy_v2/LEF/ddr5.lef', _lef_text('DDR5_M', 10.0, 26.0))
        _write_file(lib_raw / '20261005_ddr5_phy_v2/LIB/ddr5.lib', _lib_text('DDR5_M'))
        _write_file(lib_raw / '20261002_pcie5_phy_v1/LEF/pcie5.lef', _lef_text('PCIE5_M', 30.0, 40.0))
        _write_file(lib_raw / '20261002_pcie5_phy_v1/LIB/pcie5.lib', _lib_text('PCIE5_M'))
        _write_file(lib_raw / '20261009_unknown_v1/DOC/notes.txt', 'unclassified\n')

        self._write_config({
            'V1': {'PHY_WEB': {'ip_type': 'PHY', 'ip_list': ['DDR5_PHY', 'PCIE5_PHY']}},
        })
        refresh_all(self.work)

        app = create_path_app(self.work)
        self.addCleanup(app.extensions['jobs'].shutdown, wait=True)
        client = app.test_client()

        # 1) Overview shows ip_type filter, clickable track pills, needs_review banner, JSON inventory, zero simulation copy
        r_ov = client.get('/')
        self.assertEqual(r_ov.status_code, 200)
        ov_html = r_ov.get_data(as_text=True)
        self.assertIn('id="lib-iptype-select"', ov_html)
        self.assertIn('业务 IP 分轨存在待复核项', ov_html)
        self.assertIn('DDR5_PHY', ov_html)
        self.assertIn('PCIE5_PHY', ov_html)
        self.assertIn('V1/PHY_WEB/ip_partition.json', ov_html)
        self.assertIn('effective_PHY_WEB__DDR5_PHY_002.json', ov_html)
        self.assertNotIn('隐藏模拟库', ov_html)

        # 2) Read-only JSON APIs
        r_tr = client.get('/api/v1/tracks?ip_type=PHY')
        self.assertEqual(r_tr.status_code, 200)
        tr_json = r_tr.get_json()
        self.assertEqual(tr_json['count'], 2)
        self.assertEqual({t['business_ip'] for t in tr_json['tracks']}, {'DDR5_PHY', 'PCIE5_PHY'})

        r_lib_api = client.get('/api/v1/library?vendor=V1&library=PHY_WEB&ip=DDR5_PHY')
        self.assertEqual(r_lib_api.status_code, 200)
        lib_api = r_lib_api.get_json()
        self.assertEqual(lib_api['business_ip'], 'DDR5_PHY')
        self.assertEqual(lib_api['revisions'], ['rev_0001', 'rev_0002'])

        # 3) Library page track switcher, needs_review details, and track isolation
        r_ddr = client.get('/path/library?vendor=V1&library=PHY_WEB&ip=DDR5_PHY')
        self.assertEqual(r_ddr.status_code, 200)
        ddr_html = r_ddr.get_data(as_text=True)
        self.assertIn('业务 IP 轨道', ddr_html)
        self.assertIn('分轨待复核', ddr_html)
        self.assertIn('20261009_unknown_v1', ddr_html)
        self.assertIn('LEF/ddr5.lef', ddr_html)
        self.assertNotIn('LEF/pcie5.lef', ddr_html)
        check_panel = ddr_html.split('id="check-scope"', 1)[1].split('</section>', 1)[0]
        self.assertIn('检查当前版本', check_panel)
        self.assertIn('检查此 IP 的全部版本', check_panel)
        self.assertEqual(check_panel.count('name="ip" value="DDR5_PHY"'), 4)
        self.assertIn('<option value="rev_0001"', check_panel)

        r_pcie = client.get('/path/library?vendor=V1&library=PHY_WEB&ip=PCIE5_PHY')
        self.assertEqual(r_pcie.status_code, 200)
        pcie_html = r_pcie.get_data(as_text=True)
        self.assertIn('LEF/pcie5.lef', pcie_html)
        self.assertNotIn('LEF/ddr5.lef', pcie_html)

        self.assertEqual(client.get('/path/library?vendor=V1&library=PHY_WEB&ip=UNKNOWN_IP').status_code, 400)

        with client.session_transaction() as sess:
            csrf = sess['csrf']

        # 4) POST /path/partition idempotent re-run
        r_part = client.post('/path/partition', data={
            'csrf': csrf, 'vendor': 'V1', 'library': 'PHY_WEB', 'ip': 'DDR5_PHY',
        }, follow_redirects=True)
        self.assertEqual(r_part.status_code, 200)
        self.assertIn('业务 IP 分轨完成', r_part.get_data(as_text=True))

        # 5) POST /path/check on DDR5_PHY + check/view + lazy multi-track Excel download
        r_chk = client.post('/path/check', data={
            'csrf': csrf, 'vendor': 'V1', 'library': 'PHY_WEB', 'ip': 'DDR5_PHY',
            'revision': 'rev_0002', 'baseline': 'rev_0001', 'lazy_excel': '1',
        }, follow_redirects=True)
        self.assertEqual(r_chk.status_code, 200)
        self.assertIn('检查已完成', r_chk.get_data(as_text=True))
        chk_files = list((self.work / 'libraries/V1/PHY_WEB/log').glob('check__DDR5_PHY__rev_0002_*.json'))
        self.assertEqual(len(chk_files), 1)
        chk_name = chk_files[0].name
        self.assertRegex(chk_name, r'^check__DDR5_PHY__rev_0002_\d{8}(?:_\d+)?\.json$')

        r_cv = client.get(f'/path/check/view?vendor=V1&library=PHY_WEB&name={chk_name}')
        self.assertEqual(r_cv.status_code, 200)
        cv_html = r_cv.get_data(as_text=True)
        self.assertIn('DDR5_PHY', cv_html)
        self.assertIn('ip=DDR5_PHY', cv_html)
        check_doc = json.loads(chk_files[0].read_text())
        check_ref = next(row['facts'] for row in check_doc['files'] if row.get('facts'))
        facts_page = client.get('/path/facts/view', query_string={
            'vendor': 'V1', 'library': 'PHY_WEB', 'check': chk_name, 'ref': Path(check_ref).name,
        }).get_data(as_text=True)
        self.assertIn('ip=DDR5_PHY&amp;revision=rev_0002&amp;baseline=rev_0001#checks', facts_page)

        xlsx_name = chk_files[0].with_suffix('.xlsx').name
        r_xlsx = client.get(f'/path/artifact?vendor=V1&library=PHY_WEB&name={xlsx_name}')
        try:
            self.assertEqual(r_xlsx.status_code, 200)
            self.assertGreater(len(r_xlsx.data), 2000)
        finally:
            r_xlsx.close()

        # 6) Track-isolated acceptance via POST /path/acceptance
        r_acc = client.post('/path/acceptance', data={
            'csrf': csrf, 'vendor': 'V1', 'library': 'PHY_WEB', 'ip': 'DDR5_PHY',
            'action': 'accept', 'revision': 'rev_0002', 'reason': 'Web 人工复核通过',
        }, follow_redirects=True)
        self.assertEqual(r_acc.status_code, 200)
        self.assertIn('轨道 DDR5_PHY', r_acc.get_data(as_text=True))
        self.assertEqual(acceptance_status(self.work, 'V1', 'PHY_WEB', business_ip='DDR5_PHY')['accepted_revision'], 'rev_0002')
        self.assertIsNone(acceptance_status(self.work, 'V1', 'PHY_WEB', business_ip='PCIE5_PHY')['accepted_revision'])

        # 7) Index page & manual effective preview/apply on DDR5_PHY track
        r_idx = client.get('/path/index?vendor=V1&library=PHY_WEB&ip=DDR5_PHY')
        self.assertEqual(r_idx.status_code, 200)
        self.assertIn('DDR5_PHY', r_idx.get_data(as_text=True))

        r_prev = client.post('/path/effective/preview', data={
            'csrf': csrf, 'vendor': 'V1', 'library': 'PHY_WEB', 'ip': 'DDR5_PHY',
            'action': 'remove', 'view': 'LIBERTY', 'path': 'LIB/ddr5.lib',
        })
        self.assertEqual(r_prev.status_code, 200)
        self.assertIn('DDR5_PHY', r_prev.get_data(as_text=True))
        r_apply = client.post('/path/effective/apply', data={
            'csrf': csrf, 'vendor': 'V1', 'library': 'PHY_WEB', 'ip': 'DDR5_PHY',
        }, follow_redirects=True)
        self.assertEqual(r_apply.status_code, 200)
        self.assertIn('rev_0003', r_apply.get_data(as_text=True))
        # PCIE5_PHY track stays untouched at rev_0001
        self.assertEqual(len(_history(self.work / 'libraries/V1/PHY_WEB', 'PHY_WEB', business_ip='PCIE5_PHY')), 1)


if __name__ == '__main__':
    unittest.main()
