#!/bin/csh -f
# Preserve spaces while resolving a launcher symlink in another directory.
setenv AI_LIB_QOR_LAUNCHER "$0"
set launcher = "`env printenv -0 AI_LIB_QOR_LAUNCHER | xargs -0 realpath --`"
unsetenv AI_LIB_QOR_LAUNCHER
if ( "$launcher" == "" ) exit 1
set project = "$launcher:h"

if ( $#argv == 0 ) then
    set action = "--help"
else
    set action = "$argv[1]"
    shift argv
endif

if ( "$action" == "--help" || "$action" == "-h" ) then
    echo "Usage: $0 install [pip options]"
    echo "       $0 init --work PATH [--config FILE]"
    echo "       $0 web --work PATH [--host HOST] [--port PORT]"
    echo "       $0 cli COMMAND [arguments]"
    echo "Set AI_LIB_QOR_PYTHON to select another Python 3.11+ interpreter."
    exit 0
endif

set python = python3
if ( $?AI_LIB_QOR_PYTHON ) then
    set python = "$AI_LIB_QOR_PYTHON"
endif
if ( $?PYTHONPATH ) then
    setenv PYTHONPATH "${project}/src:${PYTHONPATH}"
else
    setenv PYTHONPATH "${project}/src"
endif

switch ( "$action" )
case install:
    exec "$python" -m pip install -r "${project}/requirements-pipeline.txt" $argv:q
case init:
    exec "$python" -P -m ai_lib_qor init-work $argv:q
case web:
    exec "$python" -P -m ai_lib_qor.workbench $argv:q
case cli:
    exec "$python" -P -m ai_lib_qor $argv:q
default:
    echo "Unknown action: $action. Run $0 --help." >& /dev/stderr
    exit 2
endsw
