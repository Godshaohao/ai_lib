#!/usr/bin/env csh

set script_path = "$0"
set script_dir = "$script_path:h"
if ("$script_dir" == "$script_path") set script_dir = "."
set project_root = "$script_dir/.."
set src_dir = "$project_root/src"
setenv LIB_GUARD_PROJECT_ROOT "$project_root"

if ($?PYTHONPATH) then
  setenv PYTHONPATH "${src_dir}:${PYTHONPATH}"
else
  setenv PYTHONPATH "${src_dir}"
endif

exec python -m lib_guard.short_cli $argv:q
