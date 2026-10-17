# Blender bridge Phase 0 proof on a Windows machine. Downloads NOTHING unless you pass -InstallBpy.
#
#   cd <repo>\experiments\blender_bridge
#   # A: an installed Blender (recommended; the portable zip from blender.org works too)
#   powershell -ExecutionPolicy Bypass -File .\run_on_windows.ps1 -BlenderExe "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
#   # B: Blender as a Python module in an isolated venv here (pip bpy==5.2.2, ~340 MB wheel, needs Python 3.13)
#   powershell -ExecutionPolicy Bypass -File .\run_on_windows.ps1 -InstallBpy
#   # another Blender version: add  -ExpectVersion 4.2.3  (recorded in every result.json; the default pin is 5.2.2)
#
# Needs: the Rodin GLB at ..\rodin_reference\source\base.glb (checksum-checked) and Forge's Python (numpy) for the
# Forge-side checks. Runs the jobs (inspect, round trip, simplify 10 %, board slab v0, board UV islands v2), verifies each with
# Forge's own reader and validator (verify.py), and zips the small results (no input copies) into blender_bridge_results.zip.
param([string]$BlenderExe = "", [switch]$InstallBpy, [string]$ExpectVersion = "5.2.2")
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Test-Py([string[]]$cmd, [string]$check) {
    try { $exe, $rest = $cmd; $v = & $exe @rest -c $check 2>$null; return ($v -eq "True") } catch { return $false }
}
$forgePy = $null
foreach ($c in @(@("py", "-3"), @("python"))) { if (Test-Py $c "import sys, numpy; print(sys.version_info >= (3, 10))") { $forgePy = $c; break } }
if (-not $forgePy) { throw "Forge's Python (3.10+ with numpy) was not found." }
$fexe, $frest = $forgePy

if ($InstallBpy) {
    if (-not (Test-Path ".bpy-venv\Scripts\python.exe")) {
        if (-not (Test-Py @("py", "-3.13") "import sys; print(sys.version_info[:2] == (3, 13))")) { throw "bpy 5.2.2 needs Python 3.13 (py -3.13)." }
        & py -3.13 -m venv .bpy-venv
    }
    & .\.bpy-venv\Scripts\python.exe -m pip install --disable-pip-version-check -q "bpy==5.2.2"
    if ($LASTEXITCODE -ne 0) { throw "pip install bpy==5.2.2 failed" }
    $launcher = "bpy"; $exe = (Resolve-Path ".bpy-venv\Scripts\python.exe").Path
} elseif ($BlenderExe) {
    if (-not (Test-Path $BlenderExe)) { throw "Blender not found: $BlenderExe" }
    $launcher = "blender"; $exe = $BlenderExe
} else { throw "Pass -BlenderExe <path to blender.exe> or -InstallBpy." }

& $fexe @frest bridge.py version --launcher $launcher --exe $exe
$summary = @()
foreach ($j in @("inspect_rodin", "roundtrip_rodin", "simplify_rodin_10pct", "extract_board_slab_v0", "extract_board_uv_islands_v2")) {
    $before = @(Get-ChildItem jobs -Directory -ErrorAction SilentlyContinue | ForEach-Object Name)
    & $fexe @frest bridge.py run "jobspecs\$j.json" --launcher $launcher --exe $exe --expect-version $ExpectVersion
    $runExit = $LASTEXITCODE
    $jd = Get-ChildItem jobs -Directory | Where-Object { $before -notcontains $_.Name } | Sort-Object Name | Select-Object -Last 1
    if ($jd) {
        & $fexe @frest verify.py $jd.FullName
        $summary += "{0}: run exit {1}, verify exit {2}, dir {3}" -f $j, $runExit, $LASTEXITCODE, $jd.Name
    } else { $summary += "{0}: run exit {1}, no job directory (refused before Blender ran)" -f $j, $runExit }
}
$summary | ForEach-Object { Write-Host $_ }
$summary | Set-Content -Path "jobs\summary.txt"
if (Test-Path "blender_bridge_results.zip") { Remove-Item "blender_bridge_results.zip" }
$stage = Join-Path $env:TEMP ("blender_bridge_results_" + [guid]::NewGuid())   # keeps each job's folder (same file names per job)
$root = (Resolve-Path "jobs").Path
Get-ChildItem jobs -Recurse -File | Where-Object { $_.Name -notlike "input.*" -and $_.Length -lt 50MB } | ForEach-Object {
    $dest = Join-Path $stage $_.FullName.Substring($root.Length + 1)
    New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
    Copy-Item $_.FullName $dest
}
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath "blender_bridge_results.zip"
Remove-Item -Recurse -Force $stage
Write-Host "Results: $PSScriptRoot\blender_bridge_results.zip (result.json, verify.json, report.json, blender.log, output GLBs)"
