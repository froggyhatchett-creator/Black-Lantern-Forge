# Mercy real-model acceptance (Windows, local Ollama)

**Status: NOT YET RUN on real hardware.** Everything below was developed against a fake
Ollama server (`tools/fake_ollama.py`). Simulated numbers prove the harness works, not that
any model does.

## Run it (PowerShell, from the `black-lantern-mercy` folder)

```powershell
.\scripts\run_acceptance.ps1 -Quick     # qwen3.5:9b + qwen3.5:4b, roughly 10-20 min
.\scripts\run_acceptance.ps1            # all four models
.\scripts\quick_checks.ps1              # optional: no-Python spot checks of API + thinking on/off
```
If scripts are blocked: `powershell -ExecutionPolicy Bypass -File .\scripts\run_acceptance.ps1 -Quick`

Send back the two files it prints from `acceptance-results\` (`.json` and `.txt`).
Optional second window during the run: `nvidia-smi -l 2`. Afterwards: `ollama ps`.

It uses a throwaway Mercy profile in `%TEMP%`, never pulls models, and auto-denies every tool request.
It briefly unloads models (`keep_alive 0`) so cold-start numbers are genuine.

## What each stage answers

| Stage | Question | Pass means |
| --- | --- | --- |
| 1 discovery | Does `/api/tags` list the models? | all expected names present |
| 2 selection | Does Mercy's provider path accept each name? | status "Ready" via the real subprocess provider |
| 2 (manual) | Does the UI dropdown list them? | Provider=ollama, Save/check, open the Exact model name box. **Tk UI change is untested** |
| 5 bench | Cold/warm time to first visible token, tokens/s, total, think off vs on | numbers only (INFO) |
| 6 stream | Does text arrive incrementally through Mercy? | many text events, first one well before the end |
| 7 identity | Does she answer as Mercy, not as the model? | **keyword heuristic**; read the printed replies yourself |
| 8 context | Does the window hold identity + tools, and a worst-case full 16,000-char context? | a random codeword at the very start of the system prompt is still recalled |
| 9 cancel | Does Cancel stop generation quickly and free the backend? | state `cancelled`, under 3 s, next request not slowed |
| 10 persistence | Is history identical after closing and reopening the profile? | exact match |

## Reading the context result
Mercy does not set `num_ctx` by default, so Ollama picks the window (check the CONTEXT column of
`ollama ps`). If stage 8 says `FAIL ... Ollama default` but `PASS ... num_ctx=8192`, set
**Context window in tokens** to 8192 in Provider/profile (or `"num_ctx": 8192` in `config.json`).
That costs extra VRAM; with 16 GB it should fit both 9B and 4B models, but verify with `nvidia-smi`.

## Not covered
Output *quality*, tool-call behavior of each model (tool requests are denied), long-session soak,
LM Studio, and the Tk UI. The `think` option is sent on every request and models that reject it
are retried once without it; the harness reports such models as UNSUPPORTED for think=True.
