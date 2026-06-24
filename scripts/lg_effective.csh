#!/bin/csh
set script_dir = "$0:h"
set project_root = "$script_dir/.."
set src_dir = "$project_root/src"
setenv LIB_GUARD_PROJECT_ROOT "$project_root"
if ( $?PYTHONPATH ) then
    setenv PYTHONPATH "${src_dir}:${PYTHONPATH}"
else
    setenv PYTHONPATH "$src_dir"
endif
exec python -m lib_guard.effective.cli $argv:q
