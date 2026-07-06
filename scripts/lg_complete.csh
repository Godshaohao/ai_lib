#!/usr/bin/env csh
#
# Source this file from csh/tcsh to enable lib_guard short-command completion:
#   source $PROJ/scripts/lg_complete.csh
#
# It registers static command/option completion only. Library/version names are
# runtime catalog data; use:
#   lg library list --plain
#   lg library list <LIBRARY> --versions --plain

if ($?PROJ) then
  set _lg_complete_proj = "$PROJ"
else if (-e "$cwd/scripts/lg.csh") then
  set _lg_complete_proj = "$cwd"
else
  set _lg_complete_proj = "."
endif

alias lg >& /dev/null
if ($status != 0) then
  alias lg "$_lg_complete_proj/scripts/lg.csh"
endif

foreach _lg_complete_name (lg lg.csh)
  complete $_lg_complete_name \
    'p/1/(init scan cat library cmp fd rel action intake window accept-window mark rv)/' \
    'n/library/(add discover accept apply list override)/' \
    'n/rv/(build check list accept waive)/' \
    'n/--stage/(initial stable final ad-hoc dated unknown)/' \
    'n/--mode/(current_effective previous_effective adjacent cumulative)/' \
    'n/--gate/(stage current approved)/' \
    'n/--hash-policy/(none smart full)/' \
    'n/--link-mode/(copy symlink)/' \
    'n/--package-type/(FULL_PACKAGE PARTIAL_UPDATE HOTFIX DOC_UPDATE UNKNOWN_PACKAGE)/' \
    'n/--compare-default/(previous_effective full_baseline none)/' \
    'n/--type/(lef cdl spice sp sdc upf cpf waiver ibis pwl snp touchstone cpm verilog systemverilog liberty lib spef db gds oas layout milkyway ndm unknown)/' \
    'c/-/(--help --config --dry-run --raw-root --library-type --missing --all-versions --limit --stage --with-evidence --hash-policy --parse-file-types --parse-exclude-file-types --parse-jobs --no-render --full --fast --update-detail --all --mode --rescan --refresh-catalog --out --json-out --html-out --max-depth --min-versions --max-dirs --max-candidates --default-status --registry --versions --plain --effective --root --display-name --vendor --middle-path --apply --parent --base --package-type --update-scope --standalone --base-required --base-full --previous-effective --compare-default --current-effective --manual-review --note --updated-by --scan-if-missing --force-large --alias --overwrite --link-mode --check-only --check-first --explain --only-checked --only-ready --force --force-reason --force-by --no-verify --action --since --plan-only --rebuild --accepted-by --item --by --reason)/'
end

unset _lg_complete_name
unset _lg_complete_proj
