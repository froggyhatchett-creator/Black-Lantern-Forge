# Myth v0.3.0 proof of concept: one-command run on a Windows machine with a GPU.
#
#   cd <repo>\experiments\myth_poc
#   powershell -ExecutionPolicy Bypass -File .\run_on_windows.ps1            # headless test + comparison
#   powershell -ExecutionPolicy Bypass -File .\run_on_windows.ps1 -Window    # also open the interactive viewer
#
# What it does, and nothing else:
#   1. creates .venv here (isolated; Forge's own environment is not touched) with Python 3.10+;
#   2. pip installs exactly myth-py==0.3.0 (one prebuilt wheel, ~8 MB, MIT; no other packages, no Rust build);
#   3. runs myth_poc.py headless (renders into myth_out\), then compare.py against reference\ (committed);
#   4. zips myth_out\ into myth_poc_results.zip. Send that zip back.
# Needs: Python 3.10+ (py launcher or python on PATH) and an up-to-date GPU driver (DX12 or Vulkan).
param([switch]$Window)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Test-Py([string[]]$cmd) {
    try { $exe, $rest = $cmd; $v = & $exe @rest -c "import sys; print(sys.version_info >= (3, 10))" 2>$null; return ($v -eq "True") }
    catch { return $false }
}
$pyCmd = $null
if (Test-Py @("py", "-3")) { $pyCmd = @("py", "-3") } elseif (Test-Py @("python")) { $pyCmd = @("python") }
if (-not $pyCmd) { throw "Python 3.10 or newer was not found (install it from python.org and tick 'Add to PATH')." }
Write-Host ("Using " + ($pyCmd -join " "))

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    $exe, $rest = $pyCmd
    & $exe @rest -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "could not create .venv" }
}
$vpy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $vpy -m pip install --disable-pip-version-check -q "myth-py==0.3.0"
if ($LASTEXITCODE -ne 0) { throw "pip install myth-py==0.3.0 failed" }
& $vpy -c "import myth, platform; print('myth-py', getattr(myth, '__version__', '0.3.0'), platform.platform())"

$sw = [System.Diagnostics.Stopwatch]::StartNew()
& $vpy myth_poc.py
$pocExit = $LASTEXITCODE
& $vpy compare.py
$cmpExit = $LASTEXITCODE
$sw.Stop()
Write-Host ("Headless test + comparison took {0:N1} s (myth_poc exit {1}, compare exit {2})" -f $sw.Elapsed.TotalSeconds, $pocExit, $cmpExit)

if (Test-Path "myth_poc_results.zip") { Remove-Item "myth_poc_results.zip" }
Compress-Archive -Path "myth_out\*" -DestinationPath "myth_poc_results.zip"
Write-Host "Results: $PSScriptRoot\myth_poc_results.zip  (myth_metrics.json, compare_report.json, *_side_by_side.png)"

if ($Window) { & $vpy myth_poc.py --window }
