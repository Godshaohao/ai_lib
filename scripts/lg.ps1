$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")
$Src = Join-Path $ProjectRoot "src"
$env:LIB_GUARD_PROJECT_ROOT = $ProjectRoot

if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$Src;$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $Src
}

python -m lib_guard.short_cli @args
exit $LASTEXITCODE
