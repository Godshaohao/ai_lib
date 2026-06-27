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
$PROJ/scripts/lg.csh rel <LIBRARY> <VERSION> --check-first
```

Open `$WORK/catalog/html/index.html` after catalog or comparison commands.

Use `--rescan` when parser evidence itself must be regenerated. Use
`--scan-if-missing` when existing scan evidence can be reused.

