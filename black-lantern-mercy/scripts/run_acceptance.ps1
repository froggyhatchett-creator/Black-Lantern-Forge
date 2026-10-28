<#
.SYNOPSIS
  Mercy real-model acceptance + benchmark against your local Ollama.
.EXAMPLE
  .\scripts\run_acceptance.ps1 -Quick        # qwen3.5:9b + qwen3.5:4b only, ~10-20 min
  .\scripts\run_acceptance.ps1               # all four models
.NOTES
  Read-only toward your setup: no model pulls, no installs, throwaway Mercy profile in %TEMP%.
  It temporarily unloads models (keep_alive 0) so cold-start timings are real.
#>
param(
  [string]$Endpoint = "http://127.0.0.1:11434",
  [string]$Models = "qwen3.5:9b,ministral-3:8b,qwen3.5:4b,qwen3:4b-instruct",
  [switch]$Quick,
  [int]$Runs = 3
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if ($Quick) { $Models = "qwen3.5:9b,qwen3.5:4b" }

# Pick a Python >= 3.11 (py launcher first; the Microsoft Store "python" stub fails the version test and is skipped)
function Find-Python {
  foreach ($c in @(@{exe="py"; pre=@("-3")}, @{exe="python"; pre=@()}, @{exe="python3"; pre=@()})) {
    if (-not (Get-Command $c.exe -ErrorAction SilentlyContinue)) { continue }
    try {
      $v = & $c.exe @($c.pre) -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
      if ($LASTEXITCODE -eq 0 -and [version]$v -ge [version]"3.11") { return $c }
    } catch { }
  }
}
$py = Find-Python
if (-not $py) { throw "Python 3.11+ not found on PATH." }

Write-Host "== Pre-check: Ollama reachable? ==" -ForegroundColor Cyan
try {
  $tags = Invoke-RestMethod -Uri "$Endpoint/api/tags" -TimeoutSec 10
  $tags.models | ForEach-Object { "{0}  ({1:N1} GB)" -f $_.name, ($_.size / 1GB) }
} catch { throw "Cannot reach $Endpoint. Start Ollama first. $_" }

$results = Join-Path $root "acceptance-results"
New-Item -ItemType Directory -Force -Path $results | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$json = Join-Path $results "mercy-acceptance-REAL-$stamp.json"
$txt  = Join-Path $results "mercy-acceptance-REAL-$stamp.txt"

$env:PYTHONIOENCODING = "utf-8"
$script = Join-Path $root "tools\real_model_acceptance.py"
$ErrorActionPreference = "Continue"   # Windows PowerShell 5.1 turns native stderr into terminating errors under "Stop"
& $py.exe @($py.pre) $script --endpoint $Endpoint --models $Models --runs $Runs --out $json 2>&1 | Tee-Object -FilePath $txt
Write-Host "`nSend back: $json  and  $txt" -ForegroundColor Green
Write-Host "GPU check while running (second window):  nvidia-smi -l 2" -ForegroundColor DarkGray
Write-Host "Loaded models afterwards:                  ollama ps" -ForegroundColor DarkGray
