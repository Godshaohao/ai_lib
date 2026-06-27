Status: archived
Archive reason: moved out of current lib_guard documentation.

---
name: library-candidate-selection
description: Use when inspecting raw library roots, vendor drops, process-node folders, or unclear directory trees to identify real library versions, reject non-library directories, and propose catalog/scan commands without applying release changes.
---

# Library Candidate Selection

## Core Principle

Identify real library versions from messy raw roots by combining directory structure, file evidence, naming patterns, and exclusion rules. Do not treat this as a generic directory search. The goal is to produce auditable candidates for `catalog` and `scan`.

## Inputs

Accept any of:

- Raw root path.
- Process node or vendor context.
- Library type: `stdcell`, `memory`, `ip`, `io`, `analog`, `foundation`.
- Candidate version name, release line, or fuzzy filter.
- Existing `catalog.json` and manual override hints.

## Evidence Model

Score candidates using multiple signals:

- View directories: `lib`, `lef`, `gds`, `oas`, `db`, `cdl`, `verilog`, `rtl`, `sdc`, `upf`, `cpf`, `doc`.
- File types: `.lib`, `.db`, `.lef`, `.gds`, `.oas`, `.v`, `.sv`, `.cdl`, `.sp`, `.spi`, `.sdc`, `.upf`, `.cpf`.
- Naming patterns: `tt`, `ss`, `ff`, `nldm`, `ccs`, `ecsm`, `release`, `rel`, `v*`, `YYYYMMDD`, `stable`, `final`, `initial`, `ad-hoc`.
- Marker files: `README`, `release_note`, `manifest`, `checksum`, `md5`, vendor notes.
- Negative patterns: `backup`, `temp`, `log`, `report`, `diff`, `work`, `scratch`, `output`, `.snapshot`, `old_compare`, `simulation_output`.

Do not rely on directory names alone. A version-like directory with only reports is not a library version.

## Required Output

Always return five sections:

1. Conclusion
2. Evidence
3. Risks
4. Recommended Commands
5. Manual Confirmation

Also provide structured data when possible:

```json
{
  "candidates": [
    {
      "path": ".../stdcell/rel_20260601",
      "library_type": "stdcell",
      "library_name": "stdcell",
      "version_id": "rel_20260601",
      "confidence": 0.92,
      "evidence": {
        "views": ["liberty", "lef", "db", "gds", "cdl"],
        "file_type_counts": {
          "liberty": 120,
          "lef": 1,
          "db": 120,
          "gds": 1,
          "cdl": 1
        },
        "markers": ["README", "release_note.txt"]
      },
      "risks": [],
      "recommended_command": "python -m lib_guard.cli catalog scan ..."
    }
  ],
  "rejected": [
    {
      "path": ".../reports",
      "reason": "report/log only, no library view files"
    }
  ]
}
```

## Command Policy

Default to generating commands, not executing them.

Allowed read-only or analysis commands:

```bash
find
du
ls
python -m lib_guard.cli catalog scan
python -m lib_guard.cli scan --mode candidate
```

Do not run by default:

```bash
rm
cp to release_area
python -m lib_guard.cli release link --apply
overwrite operations
```

## Boundaries

This skill does not decide whether a version is signoff-ready. It does not decide whether a version should be released. It does not modify raw roots, delete directories, apply release links, or overwrite release outputs.

## Common Mistakes

- Mistaking `docs`, `reports`, or `backup` directories for library versions.
- Treating every two-level folder as a library version.
- Ignoring multiple versions under the same library name.
- Hiding uncertainty instead of creating manual confirmation items.
- Producing prose only, without candidate confidence or evidence.
