# Streaming + UX Overhaul - 2026-06-11

This note records the perceived-latency overhaul done after the first real
manual quality pass. The runtime policy (Ollama text, A1111 images, hard
text-to-image handoff) is unchanged; this pass fixed how honestly and how
early the app communicates what the runtime is doing.

## Problems This Fixes

1. **Fake streaming.** `/chat` was a blocking POST; the "typewriter" was a
   client-side animation replayed after the full reply arrived.
2. **No real image progress.** The per-beat progress bars existed but were
   never fed live data; the A1111 client never polled `/sdapi/v1/progress`.
3. **Startup-gate deadlock.** A transient text warmup failure (e.g. racing
   the A1111 cold boot for VRAM) left the composer permanently disabled at
   "Warming Engines..." while the banner claimed "Local engines ready."
   No retry existed.
4. **Composer lock during renders.** Steady-state model swaps re-locked the
   gate, so you could not write while an image rendered.
5. **Frozen status during cold boot.** `/status` blocked on the engine
   service locks while `ensure_loaded` held them (up to 6 minutes for an
   A1111 cold start), freezing the readiness UI exactly when it mattered.
6. **Stale frontend caching.** `app.js`/`style.css` had no cache busting, so
   UI fixes silently did not reach the browser.
7. **Spawn fragility.** If the parent environment carries
   `NoDefaultCurrentDirectoryInExePath=1` (some sandboxed shells set it),
   `cmd /c webui-user.bat` could not resolve `call webui.bat` and the A1111
   boot died instantly.

## What Changed

### Backend
- `POST /chat/{id}/stream`: real token streaming. A dedicated worker thread
  owns the runtime lock for the whole generation (RLock stays on one thread)
  and pushes NDJSON events (`status` / `tok` / `done` / `err`) through a
  queue drained by the `StreamingResponse`. Frames, auto-image jobs, and
  summary cadence behave exactly like the non-streaming route, which remains
  in place for Regenerate and the smoke harnesses.
- `TextGenerationService.chat_reply_stream` / `_generate_stream`: Ollama
  `stream: true` with per-chunk yield.
- `ImageGenerationService._start_progress_poller`: polls A1111
  `/sdapi/v1/progress` once per second during the render and feeds real
  step counts + ETA into the status stream.
- Runtime coordinator: startup warmup now verifies the text model actually
  loaded and retries 3x with backoff; on final failure the gate enters an
  honest `error` state. `POST /runtime/retry-warmup` + a "Retry Engines"
  button re-run warmup. Readiness is **sticky**: once startup succeeds, the
  composer stays usable and mid-render requests simply queue on the runtime
  lock.
- `snapshot()` on both engine services is lock-free, so `/status` and the
  SSE stream stay live during cold boots and long loads.
- `ensure_loaded` no longer reports "Text model ready" after a failed
  warmup.
- Static assets are served with `?v=<mtime>` cache busting (per request).
- The A1111 spawn strips `NoDefaultCurrentDirectoryInExePath` from the child
  environment.

### Frontend
- The composer posts to the streaming endpoint via fetch + NDJSON reader;
  tokens render into a live streaming beat with a cursor. The old fake
  typewriter is gone.
- `window.__streamActive` pauses both timeline-refresh mechanisms (SSE
  image-finalize hook and the auto-image poll) while a stream is rendering,
  so refreshes can no longer destroy the live beat mid-generation.
- Auto-image toggle and image preset persist in localStorage across turns,
  reloads, and restarts.
- Honest button states: "Writing..." while streaming, enabled during
  background renders, "Engines Failed - Retry Above" on warmup failure.

## Verified (live browser, this machine)
- Warm turn: text visible ~14s, real progress bar ("Rendering image 9/10 -
  ETA 1s"), image visible ~45s, composer usable throughout, prefs persisted.
- Cold boot: full stack killed, relaunched; gate narrated
  "Warming A1111 image backend" -> "Loading story text model" ->
  "Ready to write" with `/status` responsive throughout; gate auto-released
  without refresh; first streamed turn clean. Zero console errors all night.
- New regression smoke: `scripts/smoke_stream_chat.py` (mock-mode streaming
  route end-to-end, persistence checked, self-cleaning).

## Known Remaining (not in this pass)
- Per-character/original-character image identity is still prompt-anchored
  only; OCs without `source_media` drift (e.g. hair color).
- Prose formatting is stochastic (occasional quote-wrapped narration);
  agency violations still possible. These are model/prompt issues, not
  runtime issues.
- The ~16s pre-render unload + ~13s post-render rewarm orchestration tax is
  inherent to the hard handoff policy on 12 GB.
