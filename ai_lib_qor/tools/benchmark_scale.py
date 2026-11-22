"""Multi-vendor, multi-version scale & bloat benchmark over real open-source PDK seeds.

Strictly isolated from real `work/`; writes only to `--sandbox` (default: temp dir).
"""
import argparse
from datetime import date, timedelta
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time

from ai_lib_qor.application.minimal_checks import run_revision
from ai_lib_qor.application.path_refresh import refresh_all, refresh_l1, refresh_l3, refresh_status


SEEDS = [
    ('SKYWATER130', 'sky130_fd_sc_hd', 'sky130hd/lef/sky130_fd_sc_hd_merged.lef', ['sky130hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib']),
    ('GF180MCU', 'gf180mcu_fd_sc_mcu7t5v0', 'gf180/lef/gf180mcu_2LM_1TM_30K_7t_sc.lef', [
        'gf180/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib.gz',
        'gf180/lib/gf180mcu_fd_sc_mcu7t5v0__ff_n40C_5v50.lib.gz',
        'gf180/lib/gf180mcu_fd_sc_mcu7t5v0__ss_125C_4v50.lib.gz',
    ]),
    ('NANGATE45', 'nangate45_stdcell', 'nangate45/lef/NangateOpenCellLibrary.macro.lef', ['nangate45/lib/NangateOpenCellLibrary_typical.lib']),
    ('ASAP7', 'asap7sc7p5t_dff', 'asap7/lef/asap7sc7p5t_DFFHQNV2X.lef', [
        'asap7/lib/NLDM/asap7sc7p5t_DFFHQNV2X_RVT_FF_nldm_FAKE.lib',
        'asap7/lib/NLDM/asap7sc7p5t_DFFHQNV2X_RVT_SS_nldm_FAKE.lib',
        'asap7/lib/NLDM/asap7sc7p5t_DFFHQNV2X_RVT_TT_nldm_FAKE.lib',
    ]),
]


def _mutate_lef_size(src: Path, dst: Path, delta: float):
    text = src.read_text(encoding='utf-8', errors='replace')
    pattern = re.compile(r'(\bSIZE\s+)([0-9.]+)(\s+BY\s+)([0-9.]+)(\s*;)')
    def repl(match):
        w = float(match.group(2))
        h = float(match.group(4)) + delta
        return f"{match.group(1)}{w:.4f}{match.group(3)}{h:.4f}{match.group(5)}"
    new_text, count = pattern.subn(repl, text, count=1)
    dst.write_text(new_text if count else text, encoding='utf-8')


def _link_or_copy(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _measure_work(work: Path):
    buckets = {
        'delivery': 0, 'effective': 0, 'formal': 0, 'file_index': 0,
        'facts_pool': 0, 'check_json': 0, 'excel': 0, 'formal_obs': 0, 'other': 0,
    }
    file_counts = {k: 0 for k in buckets}
    for p in work.rglob('*'):
        if p.is_symlink() or not p.is_file():
            continue
        size = p.stat().st_size
        name = p.name
        if name.startswith('delivery_') and name.endswith('.json'):
            k = 'delivery'
        elif name.startswith('effective_') and name.endswith('.json'):
            k = 'effective'
        elif name.startswith('formal_') and name.endswith('.json'):
            k = 'formal'
        elif name in ('file_index.json', '.file_index_manifest.json'):
            k = 'file_index'
        elif p.parent.name == 'facts' or name.startswith('facts_') or name.startswith('fact_ca_'):
            k = 'facts_pool'
        elif (name.startswith('check_') or name.startswith('overall_')) and name.endswith('.json'):
            k = 'check_json'
        elif name.endswith('.xlsx'):
            k = 'excel'
        elif name == 'formal_observations.tsv':
            k = 'formal_obs'
        else:
            k = 'other'
        buckets[k] += size
        file_counts[k] += 1
    return {
        'total_bytes': sum(buckets.values()),
        'total_files': sum(file_counts.values()),
        'bytes_by_kind': buckets,
        'files_by_kind': file_counts,
    }


def run_benchmark(seed_root: Path, sandbox: Path, *, libraries: int, versions: int, checks_per_lib: int, formal_repeats: int, render_excel: bool):
    raw_root = sandbox / 'RAW'
    nl_root = sandbox / 'NL2.5.3'
    work_root = sandbox / 'work'
    raw_root.mkdir(parents=True, exist_ok=True)
    nl_root.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)

    # Build library list from real open PDK seeds
    lib_specs = []
    for idx in range(libraries):
        vendor, base_lib, lef_rel, lib_rels = SEEDS[idx % len(SEEDS)]
        suffix = '' if idx < len(SEEDS) else f'_inst{idx // len(SEEDS):02d}'
        lib_specs.append((vendor, base_lib + suffix, seed_root / lef_rel, [seed_root / r for r in lib_rels]))

    # Generate multi-version RAW deliveries + Formal NL symlinks pointing to V01
    start_day = date(2025, 1, 1)
    for vendor, lib, lef_src, lib_srcs in lib_specs:
        for v_idx in range(versions):
            v_day = (start_day + timedelta(days=v_idx * 10)).strftime('%Y%m%d')
            ver_name = f'{v_day}_r{v_idx + 1:02d}'
            v_dir = raw_root / vendor / lib / ver_name
            lef_dst = v_dir / 'LEF' / lef_src.name
            lef_dst.parent.mkdir(parents=True, exist_ok=True)
            if v_idx == 0:
                _link_or_copy(lef_src, lef_dst)
                for lsrc in lib_srcs:
                    ldst = v_dir / 'LIB' / lsrc.name
                    _link_or_copy(lsrc, ldst)
                    link = nl_root / vendor / lib / 'LIB' / lsrc.name
                    link.parent.mkdir(parents=True, exist_ok=True)
                    link.symlink_to(ldst)
                link = nl_root / vendor / lib / 'LEF' / lef_src.name
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(lef_dst)
            elif v_idx % 4 == 0:
                # Real LEF SIZE mutation on every 4th version
                _mutate_lef_size(lef_src, lef_dst, delta=0.05 * (v_idx // 4))
            else:
                # Incremental delivery reusing exact same content (simulates unchanged LEF / partial Liberty drop)
                _link_or_copy(lef_src, lef_dst)
                if v_idx % 2 == 0:
                    _link_or_copy(lib_srcs[0], v_dir / 'LIB' / lib_srcs[0].name)

    (work_root / 'path_sources.json').write_text(json.dumps({
        'raw_root': str(raw_root),
        'nl_root': str(nl_root),
        'nl_version': 'NL2.5.3',
    }), encoding='utf-8')

    # Stage 1: Full L1 -> L2 -> L3 refresh
    t0 = time.perf_counter()
    res_all = refresh_all(work_root)
    t_refresh_all = time.perf_counter() - t0

    # Stage 2: No-op L3 refresh (should skip rebuilds)
    t0 = time.perf_counter()
    res_l3_noop = refresh_l3(work_root)
    t_l3_noop = time.perf_counter() - t0

    # Stage 3: Repeated unchanged Formal scans (tests formal_observations.tsv bloat)
    t0 = time.perf_counter()
    for _ in range(formal_repeats):
        refresh_l1(work_root, raw=False, formal=True)
    t_formal_repeats = time.perf_counter() - t0

    # Stage 4: Run single-revision checks across libraries & multiple revisions
    t0 = time.perf_counter()
    checks_executed = 0
    for vendor, lib, _, _ in lib_specs:
        st = refresh_status(work_root)
        lib_row = next(x for x in st['libraries'] if (x['vendor'], x['library']) == (vendor, lib))
        rev_count = lib_row['revision_count']
        if rev_count < 2:
            continue
        target_revs = [f'rev_{r:04d}' for r in range(max(2, rev_count - checks_per_lib + 1), rev_count + 1)]
        for rev in target_revs:
            try:
                run_revision(work_root, vendor, lib, rev, render=render_excel)
            except TypeError:
                run_revision(work_root, vendor, lib, rev)
            checks_executed += 1
    t_checks = time.perf_counter() - t0

    # Stage 5: Measure overview read time
    from ai_lib_qor.workbench.path_app import create_path_app
    app = create_path_app(work_root)
    client = app.test_client()
    t0 = time.perf_counter()
    resp = client.get('/')
    t_overview = time.perf_counter() - t0
    assert resp.status_code == 200

    disk = _measure_work(work_root)
    return {
        'config': {
            'libraries': libraries,
            'versions_per_library': versions,
            'checks_per_library': checks_per_lib,
            'formal_repeats': formal_repeats,
            'render_excel': render_excel,
        },
        'counts': {
            'deliveries_created': res_all['l1']['delivery_created'],
            'formals_created': res_all['l1']['formal_created'],
            'effective_initialized': res_all['l2']['initialized'],
            'effective_evolved': res_all['l2']['effective_published'],
            'l3_noop_skipped': res_l3_noop['indexes_skipped_rebuild'],
            'checks_executed': checks_executed,
        },
        'timings_seconds': {
            'refresh_all_l1_l2_l3': round(t_refresh_all, 3),
            'l3_noop_refresh': round(t_l3_noop, 3),
            'formal_repeats': round(t_formal_repeats, 3),
            'checks_total': round(t_checks, 3),
            'web_overview_get': round(t_overview, 4),
        },
        'disk': disk,
    }


def main():
    p = argparse.ArgumentParser(description='Multi-vendor multi-version scale & bloat benchmark')
    p.add_argument('--seeds', default=str(Path(__file__).resolve().parents[1] / 'examples/open_pdk_seeds'))
    p.add_argument('--sandbox', help='Persistent sandbox output directory (default: temporary directory)')
    p.add_argument('--libraries', type=int, default=8)
    p.add_argument('--versions', type=int, default=12)
    p.add_argument('--checks-per-lib', type=int, default=4)
    p.add_argument('--formal-repeats', type=int, default=5)
    p.add_argument('--no-excel', action='store_true')
    args = p.parse_args()

    if args.sandbox:
        sb = Path(args.sandbox).resolve()
        if sb.exists():
            shutil.rmtree(sb)
        sb.mkdir(parents=True)
        out = run_benchmark(Path(args.seeds), sb, libraries=args.libraries, versions=args.versions,
                            checks_per_lib=args.checks_per_lib, formal_repeats=args.formal_repeats,
                            render_excel=not args.no_excel)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            out = run_benchmark(Path(args.seeds), Path(tmp), libraries=args.libraries, versions=args.versions,
                                checks_per_lib=args.checks_per_lib, formal_repeats=args.formal_repeats,
                                render_excel=not args.no_excel)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
