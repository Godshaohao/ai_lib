#!/bin/csh -f

#
# lib_guard short CLI wrapper.
#
# 约束：
# - 使用 csh -f，避免读取 ~/.cshrc / ~/.login 导致 module 环境被污染。
# - 不自动寻找 Python，避免在内网环境里误用旧 Python 或触发 module 冲突。
# - 必须显式设置 LIB_GUARD_PYTHON，且 Python 版本必须 >= 3.11。
#

set script_path = "$0"
set script_dir = "$script_path:h"
if ("$script_dir" == "$script_path") set script_dir = "."
set project_root = "$script_dir/.."
set src_dir = "$project_root/src"
setenv LIB_GUARD_PROJECT_ROOT "$project_root"

if (! $?LIB_GUARD_CONFIG) then
  if ($?WORK) then
    if (-e "$WORK/lib_guard.yml") then
      setenv LIB_GUARD_CONFIG "$WORK/lib_guard.yml"
    endif
  endif
endif

if ($?PYTHONPATH) then
  setenv PYTHONPATH "${src_dir}:${PYTHONPATH}"
else
  setenv PYTHONPATH "${src_dir}"
endif

if (! $?LIB_GUARD_PYTHON) then
  echo "ERROR: LIB_GUARD_PYTHON 没有设置。"
  echo "原因：lib_guard 不会自动寻找 Python，避免误用旧 Python 或触发 module 冲突。"
  echo "下一步："
  echo "  1. 先确认 Python >= 3.11 的解释器路径。"
  echo "  2. 设置环境变量，例如："
  echo "     setenv LIB_GUARD_PYTHON /path/to/python3.11"
  echo "  3. 如已初始化 workspace，也建议设置："
  echo '     setenv LIB_GUARD_CONFIG $WORK/lib_guard.yml'
  exit 127
endif

if (! -x "$LIB_GUARD_PYTHON") then
  echo "ERROR: LIB_GUARD_PYTHON 不可执行：$LIB_GUARD_PYTHON"
  echo "下一步：请设置为明确的 Python >= 3.11 解释器，例如："
  echo "  setenv LIB_GUARD_PYTHON /path/to/python3.11"
  exit 127
endif

"$LIB_GUARD_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
if ($status != 0) then
  echo "ERROR: lib_guard 需要 Python >= 3.11。"
  echo -n "当前 LIB_GUARD_PYTHON: "
  "$LIB_GUARD_PYTHON" --version
  exit 127
endif

exec "$LIB_GUARD_PYTHON" -m lib_guard.short_cli $argv:q
