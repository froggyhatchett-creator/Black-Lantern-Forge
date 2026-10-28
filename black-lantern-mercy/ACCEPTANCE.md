# Mercy real-model acceptance (Windows, local Ollama)

**Status: NOT YET RUN on real hardware (RTX 4050 6 GB / Windows 11 is the target).** Everything below was developed against a fake
Ollama server (`tools/fake_ollama.py`). Simulated numbers prove the harness works, not that
any model does.

## Run it
Full Windows procedure (install, backup, GUI checks, harness, rollback): **`DEPLOY_WINDOWS.md`**.
Harness only, from the `black-lantern-mercy` folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_acceptance.ps1                 # qwen3.5:4b, then mercy-heretic:latest
powershell -ExecutionPolicy Bypass -File .\scripts\run_acceptance.ps1 -WithThinking   # also think=true
powershell -ExecutionPolicy Bypass -File .\scripts\run_acceptance.ps1 -All            # all five models
```
Results land in `acceptance-results\` **inside the folder you ran it from** (the black-lantern-mercy source folder):
`mercy-acceptance-REAL-<timestamp>.json` and `.txt`. Send both back.

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
| 11 tools | What tool-call JSON does this Ollama emit, and does Mercy's validation accept it? Permission is denied, never bypassed. | shape printed; PASS if accepted |
| 10 persistence | Is history identical after closing and reopening the profile? | exact match |

## Reading the context result
Mercy now always sends `num_ctx` (default **8192**, allowed 4096-131072) and sizes its own context to fit.
Without it Ollama loaded the model maximum (262144), which made qwen3.5:4b 13 GB and 75% CPU on a 16 GB card.
Stage 8 checks that `/api/ps` reports a window equal to Mercy's setting, and runs the codeword
canary at that same window. The harness never makes a request without `num_ctx` (an unset window loads the model
maximum, which is the original 13 GB / CPU-spill bug); `--num-ctx` changes the value for every call. After the run, `ollama ps`
should show CONTEXT 8192, a small SIZE and 100% GPU. To change it: Provider/profile > Context window.
Larger windows cost VRAM; measure with `nvidia-smi` before raising it.

## Not covered
Output *quality*, tool-call behavior of each model (tool requests are denied), long-session soak,
LM Studio, and the Tk UI. The `think` option is sent on every request and models that reject it
are retried once without it; the harness reports such models as UNSUPPORTED for think=True.
