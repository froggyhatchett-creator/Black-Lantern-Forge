# Changelog — Mercy development milestone: responsiveness (post-v0.2)

Baseline: v0.2.0 "The Vessel", imported verbatim (commit 3e1e7d1). 67 tests, OK.

## 0.2.1 (release build; supersedes Unreleased below)

Version bumped 0.2.0 -> 0.2.1 so pip treats it as a distinct upgrade and 0.2.0 stays a clean rollback target.
Contains commit 418f9a6 (context-window fix) plus the items below.

### Added
- `tools/profile_report.py`: read-only profile report (counts, fingerprints, config) and `--diagnose`, which explains
  non-complete turns and turns with failed tool requests (deadline vs validation rejection vs denial vs inference).
- Harness: prefers the INSTALLED `mercy` and prints which file ran; GPU/CPU placement from `/api/ps`;
  explicit `think=false` honored check; real tool-call shape probe (stage 11); 5-turn identity/continuity check;
  `--think off|both` (default off), `--all`; default models `qwen3.5:4b` then `mercy-heretic:latest`.
- `DEPLOY_WINDOWS.md`: upgrade, data-preservation proof, acceptance, rollback; `tests/test_profile_report.py`.
- `tests/ui_smoke.py` now covers the model dropdown (fed by discovery), think checkbox and num_ctx validation.

### Fixed (test tooling only)
- The acceptance harness and `scripts/quick_checks.ps1` made some `/api/chat` calls without `num_ctx`, which on a small
  GPU would load the model at Ollama's default window (the original 13 GB / CPU-spill bug). All calls now send an
  explicit window (`--num-ctx`, default 8192) and the unset-window probe was removed. Regression test:
  `tests/test_harness.py` (fails on the old harness, passes now).

### Findings (no app behavior changed for these)
- `Capability rejected or failed` is a tool result given to the *model* (capabilities.py); it is not a Mercy UI error.
  Two causes share it: validation rejection before any prompt (ValueError) and deadline during a permission wait
  (DeadlineExceeded). See DEPLOY_WINDOWS.md section 8.
- Rollback to 0.2.0 requires restoring config.json: 0.2.0 rejects the new `think`/`num_ctx` fields.

### Verified (Linux, Python 3.12): 93 unit tests pass (1 Windows-only skip); Tk smoke PASS under a virtual display;
upgrade 0.2.0 -> 0.2.1 leaves message/memory/identity/config fingerprints identical; rollback procedure restores a
working 0.2.0 with all data. **Not verified: Windows, real Ollama, the RTX 4050.**

## Unreleased (history)

### Fixed (urgent): unset context window made Ollama use the model maximum
Real hardware (RTX 5060 Ti 16 GB, qwen3.5:4b): `ollama ps` showed CONTEXT 262144, SIZE 13 GB,
75% CPU / 25% GPU. Cause: Mercy sent no `num_ctx`.
- `num_ctx` is now **always** sent in `/api/chat` `options`; default **8192**; valid range 4096-131072
  (`0`/unset, floats, bools, strings are rejected). A `config.json` written by the previous build with
  `num_ctx: 0` is migrated to 8192 on load.
- Mercy's context character budget is derived from the window (`window_budget`), so history shrinks
  before the identity prompt is ever clipped. Identity too large for the window fails loudly.
- Provider refuses to send a prompt whose conservative estimate (2.5 chars/token) exceeds
  window - 512 tokens, and raises if the server reports a prompt that filled the window
  (`prompt_eval_count >= num_ctx - 64`) instead of truncating silently.
- Verified only with unit tests and the fake server. **Not verified on real hardware.**

### Changed
- **Ollama: reasoning is now explicitly off by default** (`think: false` sent on `/api/chat`).
  Config field `think` (bool, default `false`) enables it. Reasoning tokens
  (`message.thinking`) are never shown or stored in either mode. If a model rejects the
  `think` field (HTTP 400 mentioning it), the request is retried once without it.
- **Checkpointing is throttled** to once per 250 ms (first token still persisted at once).
  Terminal states always persist the full text. Trade-off: a hard process kill can lose
  up to ~250 ms of streamed text instead of one token. Measured baseline cost of the old
  per-token commit: ~1.2 ms/token on Linux/local disk (not measured on Windows).

### Added
- `num_ctx` config (0 = server default, else 512-262144) sent as `options.num_ctx`. UI: editable
  model dropdown filled from `/api/tags` discovery, `think` checkbox, `num_ctx` field. **UI code is
  compile-checked only; Tk is not installed in the dev sandbox, so `tests/ui_smoke.py` has not been
  run on these changes.**
- `tools/real_model_acceptance.py`, `scripts/run_acceptance.ps1`, `scripts/quick_checks.ps1`,
  `ACCEPTANCE.md`: discovery, selection, cold/warm benchmarks (think on/off), streaming, identity,
  context-truncation canary, cancellation, persistence - through the real ApplicationService path.
- `tools/fake_ollama.py`: simulator used only to test the harness (`--simulate`).
- `tests/test_ollama_protocol.py` (9 tests): wire-protocol behavior against a **local fake
  server**, config validation, checkpoint throttling. A fake server is not evidence that real
  Ollama works.

### Compatibility
- v0.2 `config.json` files without `think` load unchanged (defaults to `false`).
- Provider event contract, permissions, broker, audit and schema are untouched.

### Verified / NOT verified
- Verified: full suite 78 tests, 1 skipped (Windows-only process-handle test), on Linux, Python 3.13.
- Harness verified end-to-end only against the FAKE server (simulated). PowerShell scripts never executed (no PowerShell in sandbox).
- NOT verified: anything against a real Ollama/model. No Ollama binary or reachable
  endpoint in this environment. Effect of `think:false` on real latency is unmeasured.
