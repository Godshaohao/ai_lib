@echo off
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_ROOT=%%~fI"
set "PYTHONPATH=%PROJECT_ROOT%\src;%PYTHONPATH%"
set "LIB_GUARD_PROJECT_ROOT=%PROJECT_ROOT%"
python -m lib_guard.short_cli %*
exit /b %ERRORLEVEL%
