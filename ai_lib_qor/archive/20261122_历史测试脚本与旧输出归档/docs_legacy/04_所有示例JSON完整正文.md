# 所有 13 份示例记录 · 完整 JSON 正文

> 所有内容均是合成示例，逐份原样列出，以便人工审查对象与来源关联；正式交付时每个实例位于 `examples/` 对应目录。

## 示例 01 · `examples/file_facts/facts_core_v07.json`

```json
{
  "schema_version": "file_facts.v1",
  "facts_id": "facts_core_v07",
  "source_ref": {
    "kind": "delivery_file",
    "source_library_id": "lib_rtavfs",
    "delivery_id": "dlv_20260907_001",
    "file_id": "f001"
  },
  "view": "LEF",
  "parser": {
    "name": "lef_parser",
    "version": "demo-1"
  },
  "parse_status": "COMPLETE",
  "covered_sections": [
    "MACRO_NAME",
    "MACRO_SIZE",
    "PIN_NAME",
    "PIN_DIRECTION"
  ],
  "units": {
    "distance": "um"
  },
  "objects": {
    "macros": [
      {
        "name": "MAC_A",
        "size_um": [
          120.0,
          80.0
        ],
        "pins": [
          {
            "name": "A",
            "direction": "INPUT"
          },
          {
            "name": "B",
            "direction": "OUTPUT"
          }
        ]
      }
    ]
  }
}
```

## 示例 02 · `examples/file_facts/facts_core_v08.json`

```json
{
  "schema_version": "file_facts.v1",
  "facts_id": "facts_core_v08",
  "source_ref": {
    "kind": "delivery_file",
    "source_library_id": "lib_rtavfs",
    "delivery_id": "dlv_20261019_001",
    "file_id": "f001"
  },
  "view": "LEF",
  "parser": {
    "name": "lef_parser",
    "version": "demo-1"
  },
  "parse_status": "COMPLETE",
  "covered_sections": [
    "MACRO_NAME",
    "MACRO_SIZE",
    "PIN_NAME",
    "PIN_DIRECTION"
  ],
  "units": {
    "distance": "um"
  },
  "objects": {
    "macros": [
      {
        "name": "MAC_A",
        "size_um": [
          124.0,
          80.0
        ],
        "pins": [
          {
            "name": "A",
            "direction": "INPUT"
          },
          {
            "name": "B",
            "direction": "OUTPUT"
          },
          {
            "name": "C",
            "direction": "INPUT"
          }
        ]
      }
    ]
  }
}
```

## 示例 03 · `examples/file_facts/facts_tt_v08.json`

```json
{
  "schema_version": "file_facts.v1",
  "facts_id": "facts_tt_v08",
  "source_ref": {
    "kind": "delivery_file",
    "source_library_id": "lib_rtavfs",
    "delivery_id": "dlv_20261019_001",
    "file_id": "f002"
  },
  "view": "LIBERTY",
  "parser": {
    "name": "liberty_parser",
    "version": "demo-1"
  },
  "parse_status": "COMPLETE",
  "covered_sections": [
    "CELL_NAME",
    "PIN_NAME",
    "PIN_DIRECTION"
  ],
  "units": {
    "time": "ns",
    "capacitance": "pf"
  },
  "objects": {
    "cells": [
      {
        "name": "MAC_A",
        "pins": [
          {
            "name": "A",
            "direction": "input"
          },
          {
            "name": "B",
            "direction": "output"
          },
          {
            "name": "C",
            "direction": "input"
          }
        ]
      }
    ]
  }
}
```

## 示例 04 · `examples/work/formal_nl/NL2.5.3/snapshots/snap_nl253_0001.json`

```json
{
  "schema_version": "formal_snapshot.v1",
  "formal_nl_id": "NL2.5.3",
  "formal_snapshot_id": "snap_nl253_0001",
  "previous_snapshot_id": null,
  "observed_at": "2026-09-09T10:00:00+08:00",
  "source_root": "/example/library/lib_NL2.5.3",
  "coverage": "COMPLETE_IN_SCOPE",
  "scope": {
    "source_library_ids": [
      "lib_rtavfs"
    ],
    "views": [
      "LEF",
      "LIBERTY"
    ],
    "note": "本示例只扫描该 SourceLibrary 的 LEF 与 func Liberty"
  },
  "linked_files": [
    {
      "file_id": "nf001",
      "file_key": "lib_rtavfs:lef:core",
      "link_path": "lef/core.lef",
      "resolved_path": "/example/raw/vendor_orion/lib_rtavfs/V07/lef/core.lef",
      "source_match": "MATCHED_RAW",
      "source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20260907_001",
        "file_id": "f001"
      }
    },
    {
      "file_id": "nf002",
      "file_key": "lib_rtavfs:liberty:func_tt",
      "link_path": "lib/func_tt.lib",
      "resolved_path": "/example/raw/vendor_orion/lib_rtavfs/V07/lib/func_tt.lib",
      "source_match": "MATCHED_RAW",
      "source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20260907_001",
        "file_id": "f002"
      }
    },
    {
      "file_id": "nf003",
      "file_key": "lib_rtavfs:liberty:func_ff",
      "link_path": "lib/func_ff.lib",
      "resolved_path": "/example/raw/vendor_orion/lib_rtavfs/V07/lib/func_ff.lib",
      "source_match": "MATCHED_RAW",
      "source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20260907_001",
        "file_id": "f003"
      }
    }
  ]
}
```

## 示例 05 · `examples/work/formal_nl/NL2.5.3/snapshots/snap_nl253_0002.json`

```json
{
  "schema_version": "formal_snapshot.v1",
  "formal_nl_id": "NL2.5.3",
  "formal_snapshot_id": "snap_nl253_0002",
  "previous_snapshot_id": "snap_nl253_0001",
  "observed_at": "2026-10-21T10:00:00+08:00",
  "source_root": "/example/library/lib_NL2.5.3",
  "coverage": "COMPLETE_IN_SCOPE",
  "scope": {
    "source_library_ids": [
      "lib_rtavfs"
    ],
    "views": [
      "LEF",
      "LIBERTY"
    ],
    "note": "本示例只扫描该 SourceLibrary 的 LEF 与 func Liberty"
  },
  "linked_files": [
    {
      "file_id": "nf001",
      "file_key": "lib_rtavfs:lef:core",
      "link_path": "lef/core.lef",
      "resolved_path": "/example/raw/vendor_orion/lib_rtavfs/V07/lef/core.lef",
      "source_match": "MATCHED_RAW",
      "source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20260907_001",
        "file_id": "f001"
      }
    },
    {
      "file_id": "nf002",
      "file_key": "lib_rtavfs:liberty:func_tt",
      "link_path": "lib/func_tt.lib",
      "resolved_path": "/example/raw/vendor_orion/lib_rtavfs/V08/lib/func_tt.lib",
      "source_match": "MATCHED_RAW",
      "source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20261019_001",
        "file_id": "f002"
      }
    },
    {
      "file_id": "nf003",
      "file_key": "lib_rtavfs:liberty:func_ff",
      "link_path": "lib/func_ff.lib",
      "resolved_path": "/example/raw/vendor_orion/lib_rtavfs/V07/lib/func_ff.lib",
      "source_match": "MATCHED_RAW",
      "source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20260907_001",
        "file_id": "f003"
      }
    }
  ]
}
```

## 示例 06 · `examples/work/vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20260907_001/delivery.json`

```json
{
  "schema_version": "delivery_record.v1",
  "delivery_id": "dlv_20260907_001",
  "vendor_id": "vendor_orion",
  "source_library_id": "lib_rtavfs",
  "supplier_version": "V07",
  "delivery_order": 7,
  "received_at": "2026-09-07T11:00:00+08:00",
  "source_root": "/example/raw/vendor_orion/lib_rtavfs/V07",
  "package_mode": "FULL",
  "package_scope": {
    "file_keys": [
      "lib_rtavfs:lef:core",
      "lib_rtavfs:liberty:func_tt",
      "lib_rtavfs:liberty:func_ff"
    ],
    "scope_confirmed": true
  },
  "explicit_removed_file_keys": [],
  "files": [
    {
      "file_id": "f001",
      "file_key": "lib_rtavfs:lef:core",
      "classification": "RESOLVED",
      "relative_path": "lef/core.lef",
      "view": "LEF",
      "corner": null,
      "mode": null
    },
    {
      "file_id": "f002",
      "file_key": "lib_rtavfs:liberty:func_tt",
      "classification": "RESOLVED",
      "relative_path": "lib/func_tt.lib",
      "view": "LIBERTY",
      "corner": "tt",
      "mode": "func"
    },
    {
      "file_id": "f003",
      "file_key": "lib_rtavfs:liberty:func_ff",
      "classification": "RESOLVED",
      "relative_path": "lib/func_ff.lib",
      "view": "LIBERTY",
      "corner": "ff",
      "mode": "func"
    }
  ]
}
```

## 示例 07 · `examples/work/vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20261019_001/checks/run_001.json`

```json
{
  "schema_version": "check_result.v1",
  "check_run_id": "run_001",
  "target": {
    "kind": "RAW_DELIVERY",
    "id": "dlv_20261019_001"
  },
  "baseline": {
    "kind": "RAW_DELIVERY",
    "id": "dlv_20260907_001"
  },
  "effective_set_id": null,
  "run_at": "2026-10-19T18:00:00+08:00",
  "ruleset_id": "qor_rules_202610",
  "file_changes": [
    {
      "file_key": "lib_rtavfs:lef:core",
      "old_source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20260907_001",
        "file_id": "f001"
      },
      "new_source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20261019_001",
        "file_id": "f001"
      },
      "source_changed": true,
      "content_status": "CHANGED",
      "object_changes": [
        {
          "object_type": "MACRO",
          "object_name": "MAC_A",
          "attribute": "SIZE",
          "old_value": [
            120.0,
            80.0
          ],
          "new_value": [
            124.0,
            80.0
          ],
          "unit": "um",
          "facts_refs": [
            "facts_core_v07",
            "facts_core_v08"
          ]
        }
      ]
    },
    {
      "file_key": "lib_rtavfs:liberty:func_tt",
      "old_source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20260907_001",
        "file_id": "f002"
      },
      "new_source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20261019_001",
        "file_id": "f002"
      },
      "source_changed": true,
      "content_status": "UNKNOWN",
      "object_changes": []
    }
  ],
  "quality_checks": [],
  "summary": {
    "files_with_new_source": 2,
    "files_with_confirmed_content_change": 1,
    "failed_checks": 0,
    "inconclusive_checks": 0
  },
  "evidence_note": "交付前来源对比，不代表文件已进入有效版本"
}
```

## 示例 08 · `examples/work/vendors/vendor_orion/libraries/lib_rtavfs/deliveries/dlv_20261019_001/delivery.json`

```json
{
  "schema_version": "delivery_record.v1",
  "delivery_id": "dlv_20261019_001",
  "vendor_id": "vendor_orion",
  "source_library_id": "lib_rtavfs",
  "supplier_version": "V08",
  "delivery_order": 8,
  "received_at": "2026-10-19T15:00:00+08:00",
  "source_root": "/example/raw/vendor_orion/lib_rtavfs/V08",
  "package_mode": "INCREMENTAL",
  "package_scope": {
    "file_keys": [
      "lib_rtavfs:lef:core",
      "lib_rtavfs:liberty:func_tt"
    ],
    "scope_confirmed": true
  },
  "explicit_removed_file_keys": [],
  "files": [
    {
      "file_id": "f001",
      "file_key": "lib_rtavfs:lef:core",
      "classification": "RESOLVED",
      "relative_path": "lef/core.lef",
      "view": "LEF",
      "corner": null,
      "mode": null
    },
    {
      "file_id": "f002",
      "file_key": "lib_rtavfs:liberty:func_tt",
      "classification": "RESOLVED",
      "relative_path": "lib/func_tt.lib",
      "view": "LIBERTY",
      "corner": "tt",
      "mode": "func"
    }
  ]
}
```

## 示例 09 · `examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/checks/rev_0002/run_001.json`

```json
{
  "schema_version": "check_result.v1",
  "check_run_id": "run_001",
  "target": {
    "kind": "EFFECTIVE_REVISION",
    "id": "rev_0002"
  },
  "baseline": {
    "kind": "EFFECTIVE_REVISION",
    "id": "rev_0001"
  },
  "effective_set_id": "rtavfs_primary",
  "run_at": "2026-10-20T14:00:00+08:00",
  "ruleset_id": "qor_rules_202610",
  "file_changes": [
    {
      "file_key": "lib_rtavfs:lef:core",
      "old_source_ref": {
        "kind": "formal_file",
        "formal_nl_id": "NL2.5.3",
        "formal_snapshot_id": "snap_nl253_0001",
        "file_id": "nf001"
      },
      "new_source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20261019_001",
        "file_id": "f001"
      },
      "source_changed": true,
      "content_status": "CHANGED",
      "object_changes": [
        {
          "object_type": "MACRO",
          "object_name": "MAC_A",
          "attribute": "SIZE",
          "old_value": [
            120.0,
            80.0
          ],
          "new_value": [
            124.0,
            80.0
          ],
          "unit": "um",
          "facts_refs": [
            "facts_core_v07",
            "facts_core_v08"
          ]
        },
        {
          "object_type": "PIN",
          "object_name": "MAC_A/C",
          "attribute": "PRESENCE",
          "old_value": false,
          "new_value": true,
          "unit": null,
          "facts_refs": [
            "facts_core_v07",
            "facts_core_v08"
          ]
        }
      ]
    },
    {
      "file_key": "lib_rtavfs:liberty:func_tt",
      "old_source_ref": {
        "kind": "formal_file",
        "formal_nl_id": "NL2.5.3",
        "formal_snapshot_id": "snap_nl253_0001",
        "file_id": "nf002"
      },
      "new_source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20261019_001",
        "file_id": "f002"
      },
      "source_changed": true,
      "content_status": "UNKNOWN",
      "object_changes": []
    }
  ],
  "quality_checks": [
    {
      "check_id": "LEF_LIBERTY_PIN_MATCH",
      "scope_file_keys": [
        "lib_rtavfs:lef:core",
        "lib_rtavfs:liberty:func_tt"
      ],
      "result": "PASS",
      "coverage": "COMPLETE",
      "facts_refs": [
        "facts_core_v08",
        "facts_tt_v08"
      ],
      "detail": "示例规则比较 MAC_A 的逻辑 Pin 名称与方向；未覆盖时序弧和 PG Pin"
    }
  ],
  "summary": {
    "files_with_new_source": 2,
    "files_with_confirmed_content_change": 1,
    "failed_checks": 0,
    "inconclusive_checks": 0
  },
  "evidence_note": "演示数据，PASS 仅对应所述 Pin 检查范围"
}
```

## 示例 10 · `examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/acceptance.jsonl`

```jsonl
{"schema_version": "acceptance_event.v1", "event_id": "accept_0001", "effective_set_id": "rtavfs_primary", "action": "ACCEPT", "revision_id": "rev_0001", "acted_at": "2026-09-11T14:00:00+08:00", "actor": "ip_owner", "reason": "初始正式基线核对完成"}
```

## 示例 11 · `examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/index.json`

```json
{
  "schema_version": "effective_index.v1",
  "effective_set_id": "rtavfs_primary",
  "owner": {
    "owner_type": "BUSINESS_IP",
    "owner_id": "rtavfs",
    "home_source_library_id": "lib_rtavfs"
  },
  "latest_calculated_revision": "rev_0002",
  "current_accepted_revision": "rev_0001",
  "updated_at": "2026-10-20T11:05:00+08:00"
}
```

## 示例 12 · `examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/versions/rev_0001.json`

```json
{
  "schema_version": "effective_version.v1",
  "effective_set_id": "rtavfs_primary",
  "owner": {
    "owner_type": "BUSINESS_IP",
    "owner_id": "rtavfs",
    "home_source_library_id": "lib_rtavfs"
  },
  "revision_id": "rev_0001",
  "parent_revision_id": null,
  "created_at": "2026-09-10T11:00:00+08:00",
  "reason": {
    "kind": "FORMAL_BASELINE",
    "ref_id": "snap_nl253_0001"
  },
  "members": [
    {
      "file_key": "lib_rtavfs:lef:core",
      "source_ref": {
        "kind": "formal_file",
        "formal_nl_id": "NL2.5.3",
        "formal_snapshot_id": "snap_nl253_0001",
        "file_id": "nf001"
      }
    },
    {
      "file_key": "lib_rtavfs:liberty:func_tt",
      "source_ref": {
        "kind": "formal_file",
        "formal_nl_id": "NL2.5.3",
        "formal_snapshot_id": "snap_nl253_0001",
        "file_id": "nf002"
      }
    },
    {
      "file_key": "lib_rtavfs:liberty:func_ff",
      "source_ref": {
        "kind": "formal_file",
        "formal_nl_id": "NL2.5.3",
        "formal_snapshot_id": "snap_nl253_0001",
        "file_id": "nf003"
      }
    }
  ],
  "changes": [
    {
      "file_key": "lib_rtavfs:lef:core",
      "action": "ADDED",
      "old_source_ref": null,
      "new_source_ref": {
        "kind": "formal_file",
        "formal_nl_id": "NL2.5.3",
        "formal_snapshot_id": "snap_nl253_0001",
        "file_id": "nf001"
      }
    },
    {
      "file_key": "lib_rtavfs:liberty:func_tt",
      "action": "ADDED",
      "old_source_ref": null,
      "new_source_ref": {
        "kind": "formal_file",
        "formal_nl_id": "NL2.5.3",
        "formal_snapshot_id": "snap_nl253_0001",
        "file_id": "nf002"
      }
    },
    {
      "file_key": "lib_rtavfs:liberty:func_ff",
      "action": "ADDED",
      "old_source_ref": null,
      "new_source_ref": {
        "kind": "formal_file",
        "formal_nl_id": "NL2.5.3",
        "formal_snapshot_id": "snap_nl253_0001",
        "file_id": "nf003"
      }
    }
  ]
}
```

## 示例 13 · `examples/work/vendors/vendor_orion/libraries/lib_rtavfs/ips/rtavfs/effective/versions/rev_0002.json`

```json
{
  "schema_version": "effective_version.v1",
  "effective_set_id": "rtavfs_primary",
  "owner": {
    "owner_type": "BUSINESS_IP",
    "owner_id": "rtavfs",
    "home_source_library_id": "lib_rtavfs"
  },
  "revision_id": "rev_0002",
  "parent_revision_id": "rev_0001",
  "created_at": "2026-10-20T11:00:00+08:00",
  "reason": {
    "kind": "RAW_DELIVERY",
    "ref_id": "dlv_20261019_001"
  },
  "members": [
    {
      "file_key": "lib_rtavfs:lef:core",
      "source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20261019_001",
        "file_id": "f001"
      }
    },
    {
      "file_key": "lib_rtavfs:liberty:func_tt",
      "source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20261019_001",
        "file_id": "f002"
      }
    },
    {
      "file_key": "lib_rtavfs:liberty:func_ff",
      "source_ref": {
        "kind": "formal_file",
        "formal_nl_id": "NL2.5.3",
        "formal_snapshot_id": "snap_nl253_0001",
        "file_id": "nf003"
      }
    }
  ],
  "changes": [
    {
      "file_key": "lib_rtavfs:lef:core",
      "action": "REPLACED",
      "old_source_ref": {
        "kind": "formal_file",
        "formal_nl_id": "NL2.5.3",
        "formal_snapshot_id": "snap_nl253_0001",
        "file_id": "nf001"
      },
      "new_source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20261019_001",
        "file_id": "f001"
      }
    },
    {
      "file_key": "lib_rtavfs:liberty:func_tt",
      "action": "REPLACED",
      "old_source_ref": {
        "kind": "formal_file",
        "formal_nl_id": "NL2.5.3",
        "formal_snapshot_id": "snap_nl253_0001",
        "file_id": "nf002"
      },
      "new_source_ref": {
        "kind": "delivery_file",
        "source_library_id": "lib_rtavfs",
        "delivery_id": "dlv_20261019_001",
        "file_id": "f002"
      }
    }
  ]
}
```
