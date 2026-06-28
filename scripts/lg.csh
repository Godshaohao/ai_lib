#!/usr/bin/env csh

set script_path = "$0"
set script_dir = "$script_path:h"
if ("$script_dir" == "$script_path") set script_dir = "."
set project_root = "$script_dir/.."
set src_dir = "$project_root/src"
setenv LIB_GUARD_PROJECT_ROOT "$project_root"

if (! $?LIB_GUARD_CONFIG) then
  if ($?WORK) then
    if (-e "$WORK/lib_guard.yml") setenv LIB_GUARD_CONFIG "$WORK/lib_guard.yml"
  endif
endif

if ($?PYTHONPATH) then
  setenv PYTHONPATH "${src_dir}:${PYTHONPATH}"
else
  setenv PYTHONPATH "${src_dir}"
endif

set py = ""
if ("$py" == "") then
  set found = `which python3.11`
  if ($status == 0) set py = "$found"
endif
if ("$py" == "") then
  set found = `which python3`
  if ($status == 0) set py = "$found"
endif
if ("$py" == "") then
  set found = `which python`
  if ($status == 0) set py = "$found"
endif
if ("$py" == "") then
  echo "ERROR: python3.11, python3, or python is required but was not found in PATH." >&2
  exit 127
endif

exec "$py" -m lib_guard.short_cli $argv:q
