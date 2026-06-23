#!/usr/bin/env csh
# Example flow for the library registry layer.
# Usage:
#   setenv PROJ /path/to/ai_lib
#   setenv WORK $PROJ/work/N7_IP
#   setenv RAW  $WORK/raw
#   csh scripts/lg_library_registry_flow.csh

if (! $?PROJ) then
  echo "ERROR: setenv PROJ /path/to/ai_lib"
  exit 1
endif
if (! $?WORK) then
  echo "ERROR: setenv WORK /path/to/workspace"
  exit 1
endif
if (! $?RAW) then
  echo "ERROR: setenv RAW /path/to/raw"
  exit 1
endif

$PROJ/scripts/lg.csh init $WORK --raw-root $RAW
cd $WORK

# 1) Discover candidate library roots. The editable file is config/library.list.
$PROJ/scripts/lg.csh library discover --default-status REVIEW

echo ""
echo "NEXT: edit $WORK/config/library.list"
echo "      Set status=OK for real library roots; set IGNORE for false candidates."
echo "      library_id is RAW-relative path joined by underscores, e.g. Vendor_A_模拟IP_UVIP_ucie."
echo ""
echo "After edit, run:"
echo "  $PROJ/scripts/lg.csh library apply"
echo "  $PROJ/scripts/lg.csh catalog"
echo "  $PROJ/scripts/lg.csh scan <library_id> --limit 3"
