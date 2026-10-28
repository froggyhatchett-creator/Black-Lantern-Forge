# Changelog — Mercy development milestone: responsiveness (post-v0.2)

Baseline: v0.2.0 "The Vessel", imported verbatim (commit 3e1e7d1). 67 tests, OK.

## Unreleased

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
- `tests/test_ollama_protocol.py` (9 tests): wire-protocol behavior against a **local fake
  server**, config validation, checkpoint throttling. A fake server is not evidence that real
  Ollama works.

### Compatibility
- v0.2 `config.json` files without `think` load unchanged (defaults to `false`).
- Provider event contract, permissions, broker, audit and schema are untouched.

### Verified / NOT verified
- Verified: full suite 76 tests, 1 skipped (Windows-only process-handle test), on Linux, Python 3.13.
- NOT verified: anything against a real Ollama/model. No Ollama binary or reachable
  endpoint in this environment. Effect of `think:false` on real latency is unmeasured.
