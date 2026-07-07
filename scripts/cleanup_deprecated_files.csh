#!/bin/csh -f

set apply = 0

foreach arg ($argv)
  if ("$arg" == "--apply") then
    set apply = 1
  else if ("$arg" == "-h" || "$arg" == "--help") then
    echo "Usage: scripts/cleanup_deprecated_files.csh [--apply]"
    echo ""
    echo "Default mode is dry-run. Pass --apply to delete known deprecated files."
    exit 0
  else
    echo "ERROR: unknown argument: $arg"
    echo "Usage: scripts/cleanup_deprecated_files.csh [--apply]"
    exit 2
  endif
end

set repo_root = ""

if ($?LIB_GUARD_PROJECT_ROOT) then
  if (-d "$LIB_GUARD_PROJECT_ROOT/src/lib_guard" && -d "$LIB_GUARD_PROJECT_ROOT/scripts") then
    set repo_root = "$LIB_GUARD_PROJECT_ROOT"
  endif
endif

if ("$repo_root" == "" && $?PROJ) then
  if (-d "$PROJ/src/lib_guard" && -d "$PROJ/scripts") then
    set repo_root = "$PROJ"
  else if (-d "$PROJ/repo/src/lib_guard" && -d "$PROJ/repo/scripts") then
    set repo_root = "$PROJ/repo"
  endif
endif

if ("$repo_root" == "") then
  set script_dir = "$0:h"
  if ("$script_dir" == "$0") set script_dir = "."
  set script_repo = "$script_dir/.."
  if (-d "$script_repo/src/lib_guard" && -d "$script_repo/scripts") then
    set repo_root = "$script_repo"
  endif
endif

if ("$repo_root" == "") then
  set probe = "$cwd"
  while ("$probe" != "/" && "$probe" != "")
    if (-d "$probe/src/lib_guard" && -d "$probe/scripts") then
      set repo_root = "$probe"
      break
    endif
    set parent = "$probe:h"
    if ("$parent" == "$probe") break
    set probe = "$parent"
  end
endif

if ("$repo_root" == "") then
  echo "ERROR: cannot find lib_guard repo root." >&2
  echo "Hint: run from inside the repo, set PROJ to the repo root, or set LIB_GUARD_PROJECT_ROOT." >&2
  exit 2
endif

cd "$repo_root"
if ($status != 0) then
  echo "ERROR: cannot cd to repo root: $repo_root"
  exit 2
endif

if (! -d src/lib_guard || ! -d scripts) then
  echo "ERROR: this does not look like the lib_guard repo root: $cwd"
  exit 2
endif

if ($apply) then
  echo "Cleanup mode: APPLY"
else
  echo "Cleanup mode: DRY-RUN"
  echo "Pass --apply to delete the listed files."
endif

set removed = 0

set pycache_dirs = (`find src/lib_guard tests -type d -name __pycache__ -print`)
foreach target ($pycache_dirs)
  if (-e "$target") then
    echo "deprecated cache: $target"
    if ($apply) then
      rm -rf "$target"
      if ($status != 0) exit 1
    endif
    @ removed = $removed + 1
  endif
end

set explicit_targets = ( \
  "src/lib_guard/test/test_catalog_timeline.py.bak_ip_user_v2" \
  "src/lib_guard/test/test_version_detail_report.py.bak_ip_user_v2" \
  "fix_ip_user_view_tests.py" \
  "lib_guard_ip_user_patch_v2.zip" \
  "lib_guard_ip_user_patch_v2" \
  "er view test contract" \
  "1" \
)

foreach target ($explicit_targets)
  if (-e "$target") then
    echo "deprecated artifact: $target"
    if ($apply) then
      rm -rf "$target"
      if ($status != 0) exit 1
    endif
    @ removed = $removed + 1
  endif
end

if ($removed == 0) then
  echo "No deprecated files found."
else if ($apply) then
  echo "Deleted deprecated entries: $removed"
else
  echo "Deprecated entries found: $removed"
endif
