# lib_guard Parsers

Each parser module owns one file family and returns the shared `ParserResult`
envelope through `parse_*_file()` and `BaseParser.parse()`.

## Contract

Parser results use this shape:

```json
{
  "schema_version": "1.0",
  "result_type": "parser_result",
  "parser_name": "LefParser",
  "parser_version": "2.0",
  "parser_schema_version": "1.0",
  "file": "lef/a.lef",
  "abs_path": "/proj/raw/lef/a.lef",
  "file_type": "lef",
  "compression": null,
  "status": "PASS",
  "stats": {},
  "data": {},
  "issues": []
}
```

Allowed statuses are:

```text
PASS
PASS_EMPTY
FAILED
SKIPPED
UNSUPPORTED
METADATA_ONLY
```

## Adding A Parser

1. Add a focused module under `src/lib_guard/scan/parsers/`.
2. Reuse helpers from `base.py` for compression, text reading, and result
   wrapping.
3. Register the parser where scan execution selects parsers by file type.
4. Add a smoke or unit test under `src/lib_guard/test/`.
5. Add summary or diff support only when the extracted fields are meaningful
   for review.

Parser behavior is governed by this contract and the active parser tests.
