# Mercy 0.2.1 - Windows upgrade, acceptance and rollback

Target: Windows 11, Python 3.12 (`py -3.12`), Ollama at `http://127.0.0.1:11434`.
Build: **0.2.1 = commit `418f9a6` plus diagnostics/packaging** (see `CHANGELOG.md`; exact hashes in
`releases/0.2.1/SHA256SUMS.txt` and `BUILD_INFO.txt`).

**Status of these steps:** the upgrade/rollback sequence was rehearsed on Linux (Python 3.12 venv, your
original 0.2.0 wheel, a seeded profile). The Windows PowerShell commands themselves, the Windows UI, and
everything involving your real GPU/models have **not** been run by me. Report any command that misbehaves.

Your data lives in `%LOCALAPPDATA%\BlackLantern\Mercy-v02` (identity.json, config.json, mercy.sqlite3).
Installing or removing a wheel never touches that folder.

---
## 0. Get the exact build

**Option A - git (recommended; also gives you the test/tool scripts):**
```powershell
$Work = "$env:USERPROFILE\MercyUpgrade"
New-Item -ItemType Directory -Force $Work | Out-Null
Set-Location $Work
git clone --branch claude/ecstatic-goldberg-3wxxve https://github.com/froggyhatchett-creator/Black-Lantern-Forge.git forge
$Src = "$Work\forge\black-lantern-mercy"
Get-Content "$Src\releases\0.2.1\BUILD_INFO.txt"
```
**Option B - no git:** download the branch ZIP in your browser while logged in to GitHub
(`https://github.com/froggyhatchett-creator/Black-Lantern-Forge/archive/refs/heads/claude/ecstatic-goldberg-3wxxve.zip`),
then:
```powershell
$Work = "$env:USERPROFILE\MercyUpgrade"; New-Item -ItemType Directory -Force $Work | Out-Null
Expand-Archive "$env:USERPROFILE\Downloads\Black-Lantern-Forge-claude-ecstatic-goldberg-3wxxve.zip" "$Work\forge" -Force
$Src = (Get-ChildItem "$Work\forge" -Directory | Select-Object -First 1).FullName + "\black-lantern-mercy"
```
The wheels are in `$Src\releases\`. The same files were also delivered in the chat session.

**Verify the hashes** (compare with `SHA256SUMS.txt`; do not continue on a mismatch):
```powershell
Get-Content "$Src\releases\0.2.1\SHA256SUMS.txt"
Get-FileHash -Algorithm SHA256 "$Src\releases\0.2.1\black_lantern_mercy-0.2.1-py3-none-any.whl", "$Src\releases\0.2.0\black_lantern_mercy-0.2.0-py3-none-any.whl" | Format-Table Hash, Path -AutoSize
```
The 0.2.0 wheel must hash to `81ea6a640cdc2ebab92d58e4421d0a43083908416dcaf98aaf26ead174848a39` (your original release).

## 1. Read-only look at your current profile (and the "Capability rejected" error)
Close Mercy first (it holds a profile lock; the report itself is read-only).
```powershell
$MercyData = "$env:LOCALAPPDATA\BlackLantern\Mercy-v02"
py -3.12 "$Src\tools\profile_report.py" --profile $MercyData --diagnose
```
Under "turns that did not complete, or whose tool request failed" each turn gets a plain-language cause:
deadline during a permission wait, rejection by Mercy's validation before any prompt, user denial, or an inference
timeout. Save/paste that output - it identifies exactly which one produced your error (see section 8).

## 2. Back up, snapshot, upgrade
```powershell
$Backup = "$env:USERPROFILE\MercyBackups\pre-0.2.1-$(Get-Date -Format yyyyMMdd-HHmmss)"
New-Item -ItemType Directory -Force $Backup | Out-Null
Copy-Item -Recurse -Force $MercyData "$Backup\Mercy-v02"
py -3.12 "$Src\tools\profile_report.py" --profile $MercyData --json "$Backup\before.json" | Out-Null
py -3.12 -m pip show black-lantern-mercy        # note Version and Location; the upgrade must target this same Python
```
Upgrade (no network, no dependencies):
```powershell
py -3.12 -m pip install --no-index --no-deps --force-reinstall "$Src\releases\0.2.1\black_lantern_mercy-0.2.1-py3-none-any.whl"
Set-Location $env:USERPROFILE     # IMPORTANT: leave the source folder so the INSTALLED copy is what runs
py -3.12 -I -c "import mercy; print(mercy.__version__, mercy.__file__)"
```
Expected: `0.2.1` and a path under `site-packages`. If you originally ran Mercy straight from a source folder
instead of pip, launch from the new `$Src` folder; the data folder is shared either way.

**Prove your data is unchanged** (profile untouched by installation):
```powershell
py -3.12 "$Src\tools\profile_report.py" --profile $MercyData --json "$Backup\after.json" | Out-Null
$b = Get-Content "$Backup\before.json" | ConvertFrom-Json; $a = Get-Content "$Backup\after.json" | ConvertFrom-Json
foreach ($k in 'schema','conversations','messages','turns','memories','audit','messages_fingerprint','memories_fingerprint','identity.json_sha256','config.json_sha256') {
  "{0,-24} {1} -> {2}  {3}" -f $k, $b.$k, $a.$k, $(if ($b.$k -eq $a.$k) {'OK'} else {'CHANGED'}) }
```
Every line should say OK.

## 3. Launch and manual checks (qwen3.5:4b, num_ctx 8192)
```powershell
py -3.12 -m mercy
```
1. Mercy opens; your earlier conversations appear in the session box; Memory tab still lists your notes.
2. Provider / profile tab: Provider `ollama`, Exact model name `qwen3.5:4b` (the box is now a dropdown filled from
   Ollama's `/api/tags`; typing still works). **Context window = 8192** (an old config without the field shows 8192).
   Leave the reasoning checkbox **unticked**. Click **Save / check provider** - status should read "Ready".
3. Send `Mercy?` and then a second message. Watch that text streams in; try **Cancel** during a long reply.
4. While the model is loaded, in a second PowerShell window:
   ```powershell
   ollama ps
   nvidia-smi
   ```
   Expect **CONTEXT 8192**. Do **not** expect 100% GPU: on a 6 GB card the PROCESSOR column may show a CPU/GPU split;
   record whatever it shows.

## 4. Windows UI smoke test (from the source folder; uses a disposable profile, never yours)
```powershell
Set-Location $Src
py -3.12 -m tests.ui_smoke --data-dir "$env:TEMP\mercy-ui-smoke-$(Get-Random)"
```
Expected last line: `PASS: Tk startup, streaming, permission buttons, ... provider controls (model dropdown, think, num_ctx)`.
(Run from `$Src` this exercises the source tree, which is byte-identical to the wheel's `mercy/` package.
It also prints `mercy under test: <path>`.) Linux result so far: PASS on Python 3.12 under a virtual display.

## 5. Real-Ollama acceptance harness
```powershell
Set-Location $Src
powershell -ExecutionPolicy Bypass -File .\scripts\run_acceptance.ps1
```
Order: `qwen3.5:4b` first, then `mercy-heretic:latest`, `think=false` only. Add `-WithThinking` to also time
`think=true` (slow on 6 GB), `-All` for all five models. Direct form:
`py -3.12 .\tools\real_model_acceptance.py --models qwen3.5:4b,mercy-heretic:latest --out .\acceptance-results\run1.json`.
The first lines print `mercy package under test: ...` - when the wheel is installed this is the `site-packages` copy.

Immediately afterwards (models stay loaded for 5 minutes) capture the environment:
```powershell
$Results = "$Src\acceptance-results"
& { "== ollama version"; ollama --version; "== ollama ps"; ollama ps; "== nvidia-smi"; nvidia-smi
    "== mercy-heretic modelfile"; ollama show mercy-heretic:latest --modelfile
    "== profile diagnosis"; py -3.12 "$Src\tools\profile_report.py" --profile $MercyData --diagnose } *>&1 |
  Out-File "$Results\environment-$(Get-Date -Format yyyyMMdd-HHmmss).txt" -Encoding utf8
```

### Where results go / what to send back
`acceptance-results\` is created **inside the source folder**, i.e. `$Src\acceptance-results\`
(`%USERPROFILE%\MercyUpgrade\forge\black-lantern-mercy\acceptance-results\` if you followed Option A). Send:
1. `mercy-acceptance-REAL-<timestamp>.json`
2. `mercy-acceptance-REAL-<timestamp>.txt`
3. `environment-<timestamp>.txt` (from the command above)
4. The step-1 `profile_report --diagnose` output (it is also inside the environment file, but section 1 ran *before* the upgrade)
5. What you saw in the GUI checks of section 3 (memories/conversations present, streaming, cancel, `ollama ps` line)

What the harness measures: discovery, selection, cold/warm time to first token, tokens/s, total latency, GPU/CPU
placement (`size_vram / size` from `/api/ps`, **not assumed**), loaded window == 8192, whether `think:false` is accepted
and honored, streaming, a 5-turn identity/continuity check, cancellation, the real tool-call shape Ollama emits,
and persistence across closing and reopening the (throwaway) profile.
Identity checks are keyword heuristics; the replies are printed so you can judge tone yourself.

## 6. Rollback to 0.2.0 (rehearsed on Linux)
Close Mercy, then:
```powershell
py -3.12 -m pip install --no-index --no-deps --force-reinstall "$Src\releases\0.2.0\black_lantern_mercy-0.2.0-py3-none-any.whl"
Copy-Item "$Backup\Mercy-v02\config.json" "$MercyData\config.json" -Force
Set-Location $env:USERPROFILE
py -3.12 -I -c "import mercy; print(mercy.__version__)"     # expect 0.2.0
py -3.12 "$Src\tools\profile_report.py" --profile $MercyData --diagnose | Select-Object -First 14
```
**The `config.json` restore is mandatory.** Once 0.2.1 has saved settings, `config.json` contains the new `think` and
`num_ctx` fields and 0.2.0 refuses to start with `Configuration contains unknown fields`. (If you never saved settings
in 0.2.1 the file is unchanged and the copy is harmless.) Conversations, memories and turns created while on 0.2.1
remain readable by 0.2.0: the database schema is the same (2).

Full restore to exactly the pre-upgrade state (discards anything done on 0.2.1):
```powershell
Rename-Item $MercyData "$MercyData.after-0.2.1"
Copy-Item -Recurse "$Backup\Mercy-v02" $MercyData
```

## 7. Notes for the 6 GB RTX 4050
- A 4B model plus an 8192-token window may still not fit fully in VRAM; the harness reports the real split.
  Lowering **Context window** (minimum 4096) trades history for VRAM; Mercy resizes its own context to match.
- `mercy-heretic:latest` is a custom model. Check the modelfile output for its own `SYSTEM` text and `num_ctx`;
  Mercy's request always sends its own identity prompt and `num_ctx`.
- Cold start (first token after load) will be much slower than warm; the harness reports them separately.

## 8. The `Assistant [timed_out]: <error> Capability rejected.` message - what it is
Found by reading the code and reproducing each path with the real `MercyCore`/`Broker` (scripted provider):
- `Capability rejected or failed` exists in exactly one place, `mercy/capabilities.py` (`Broker.execute`). It is a
  **tool result handed to the model**, not text Mercy prints. Mercy never shows it as an error dialog.
- `[timed_out]` is only the UI label for a turn whose state is `timed_out`: the **generation deadline** (default 60 s,
  which includes time spent waiting on a permission prompt) expired.
- `<error>` appears nowhere in Mercy's code, so the sentence the transcript showed was **written by the model**,
  paraphrasing a tool result it had received. It is not a Mercy message and not a permission verdict. A user denial
  produces a *different* tool result, `Permission denied`.
- The same tool result is produced by two different causes: (a) Mercy's validation rejecting the tool call **before any
  permission prompt** (extra/unknown fields in the call, or arguments - the capabilities accept none), reported with
  kind `ValueError`; (b) the deadline expiring during the permission wait, reported with kind `DeadlineExceeded`.
  Which one happened is recorded in the audit table; `profile_report.py --diagnose` prints it.
- Whether your Ollama emits tool calls Mercy rejects (hypothesis: newer Ollama adds fields such as `index` inside the
  function object) is **unverified**. The harness stage `11-tools` prints the exact shape and whether validation accepts
  it. Permission checks are never bypassed anywhere; the harness denies every prompt.
- On a slow 6 GB setup the likelier chain is: tool call -> result -> a long model reply -> deadline. If so, raising
  **Generation deadline** (Provider tab) is the only change needed. Not changed here pending your data.
