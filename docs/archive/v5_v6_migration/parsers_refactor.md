Status: archived
Archive reason: moved out of current lib_guard documentation.

# parsers_refactor

Drop these files into:

```text
src/lib_guard/scan/parsers/
```

This refactor removes `text.py` as a parser hub. Generic reading helpers live in `base.py`; each format has its own module.

Key usage examples:

```python
from lib_guard.scan.parsers.lef import parse_lef_file, diff_lef_files
result = parse_lef_file("a.lef")
diff = diff_lef_files("old.lef", "new.lef")

from lib_guard.scan.parsers.liberty import parse_liberty_file
result = parse_liberty_file("ss_0p72v_125c.lib.gz")
```

Parser modules are canonical by format name only. The old `*_parser.py` shim
modules are intentionally removed.

Parser smoke script:

```csh
src/lib_guard/test/test_parse_any.csh /path/to/file [out_json]
```

The smoke script follows the Parser v2 vocabulary and prints `result_type`,
`parser_name`, `parser_schema_version`, `file_type`, `compression`, and
`status` from the canonical `ParserResult` envelope.

## v5 Parser v2

Parser v2 no longer supports legacy free-form parser outputs. Every
`parse_*_file()` API and every `BaseParser.parse()` implementation returns a
unified `ParserResult` envelope:

```json
{
  "schema_version": "1.0",
  "result_type": "parser_result",
  "parser_name": "LefParser",
  "parser_version": "2.0",
  "parser_schema_version": "1.0",
  "file": "lef/a.lef",
  "abs_path": "/proj/.../lef/a.lef",
  "file_type": "lef",
  "compression": null,
  "status": "PASS",
  "stats": {
    "object_count": 1,
    "warning_count": 0,
    "error_count": 0
  },
  "data": {},
  "issues": []
}
```

Allowed statuses:

```text
PASS
PASS_EMPTY
FAILED
SKIPPED
UNSUPPORTED
METADATA_ONLY
```

Parser v2 shared helpers live in `base.py`:

```text
detect_combined_extension(path)
detect_compression(path)
open_text_auto(path)
iter_lines_auto(path)
read_text_auto(path)
```

This makes compressed files such as `.v.gz`, `.lef.gz`, `.lib.gz`, and
`.spef.gz` behave the same as their uncompressed equivalents.

See `docs/lib_guard_v5_architecture_patch.md` for the full migration rationale
and the scan-flow deficiency table that drives the v5 Parser v2 work.
