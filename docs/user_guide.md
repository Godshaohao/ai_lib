Status: current

# User Guide

Use the short wrapper for normal review work:

```csh
setenv PROJ /path/to/ai_lib/repo
setenv WORK $PROJ/work/review
setenv RAW  /path/to/raw_delivery

$PROJ/scripts/lg.csh init $WORK --raw-root $RAW --library-type ip
$PROJ/scripts/lg.csh cat --full --with-evidence
$PROJ/scripts/lg.csh scan <LIBRARY> <VERSION>
$PROJ/scripts/lg.csh cmp <LIBRARY> <VERSION> --base <BASE_VERSION> --scan-if-missing
$PROJ/scripts/lg.csh fd <LIBRARY> <VERSION> <REL_PATH> --base <BASE_VERSION> --type <FILE_TYPE>
$PROJ/scripts/lg.csh rv-check <LIBRARY> <VERSION> --gate current
$PROJ/scripts/lg.csh rv-accept <LIBRARY> <VERSION> --item <ITEM_ID> --by <USER> --reason "..."
$PROJ/scripts/lg.csh rel <LIBRARY> <VERSION> --check-first --link-mode symlink
```

Open `$WORK/catalog/html/index.html` after catalog or comparison commands.

Use `--rescan` when parser evidence itself must be regenerated. Use
`--scan-if-missing` when existing scan evidence can be reused.

Version Review is the normal single-version page. Standalone `scan_html` remains
debug evidence. File Diff recommendations are focused attention items; they do
not block `current` release unless policy explicitly requires them.
