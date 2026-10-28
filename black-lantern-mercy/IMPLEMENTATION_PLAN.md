# v0.2 — The Vessel

Acceptance 001 and the v0.1 release are frozen. Work is isolated in this source
copy; migrations use synthetic or copied databases only. Real inference is deferred.

1. Replace schema-v1 implicit initialization with transactional migrations and
   pre-migration backup. Add conversations, transactional turns, interruption
   recovery, and explicit durable-memory provenance/deletion metadata.
2. Add strict configuration, exclusive OS-held profile locks, and process-isolated
   provider execution so cancellation and deadlines bound uncooperative inference.
   Keep the existing Provider protocol and raw Ollama adapter unchanged.
3. Move composition and lifecycle coordination out of Tk into an application
   controller. Wire session switching, one-shot permission decisions, cancellation,
   validated provider settings, memory detail/deletion, and audit filtering into Tk.
4. Preserve the original regression suite; add meaningful failure/recovery,
   migration, isolation, configuration and lifecycle tests after each slice.
   Deliver exact results, limitations, changed-file inventory and release hashes.

No cosmetic redesign, cloud providers, model installation, dangerous capabilities,
voice/avatar/media, autonomous permissions, OS integration or v0.3 work.
