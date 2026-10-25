# Skyzen Engine Audit — V29 implementation baseline

## Current architecture (verified from source)

- UI/application: Python + PySide6 (`main.py`, `app/main_window`, panel modules).
- Timeline state and interactions: `app/timeline_panel/core.py` (~152 KB), with layout helpers and synchronized scrollbars.
- Preview controller: `app/video_engine/controller.py`. The active controller uses FFmpeg-rendered low-resolution project composites for synchronized playback; it does not activate the per-clip `LiveMultitrackEngine`.
- FFmpeg command construction: `app/video_engine/ffmpeg_backend.py`. It builds filter-complex graphs for project previews/still frames and applies crop, transforms, grading, chroma key, and compositing.
- Preview render worker: `app/video_engine/render_worker.py`.
- Proxy generation: `app/media/proxy_service.py`, currently a single-worker queue using libx264 ultrafast proxies.
- Preview profiles: `app/video_engine/preview_profile.py` (Performance, Balanced, Clear). Profiles affect preview/proxy settings, not final export quality.
- Final export: `app/export/export_worker.py` and `app/export/codec_profiles.py`.
- The older per-clip Qt playback/compositor exists in `app/player_panel/live_playback.py` and `live_composite.py`, but source comments and tests say it is deliberately not the active playback owner.

## Highest-priority bottleneck

The active preview path renders a complete low-resolution composite project file and plays that single file. This gives a common clock for picture and mixed audio, but an edit can invalidate the composite and require a new render. A 1-minute project can still be slow to prepare even with few tracks if the source codec is expensive or effects require full-frame processing. This is the first engine architecture decision to benchmark and improve.

## What exists already (do not rebuild blindly)

- Snapshot/fingerprint tracking and signature-based composite cache names.
- Delayed background pre-render after edits.
- Cancellation of stale preview workers and latest-frame debounce.
- Disk cache pruning (currently up to 1 GiB; should become configurable/adaptive for small SSDs).
- Preview quality profiles and proxy generation.
- Original-source export path is separate from proxy preview path.
- FFmpeg filters are omitted for neutral grading settings to reduce unnecessary processing.
- Separate tests for video engine, playback contracts, preview profiles, track layout, audio/import, and startup regressions.

## Missing or not yet proven

1. Truly interactive, low-latency multitrack preview without full-project recomposition after every meaningful edit.
2. Adaptive proxy policy based on source resolution/codec and actual dropped frames; current profiles are static.
3. Optional hardware decoding/encoding capability detection with reliable software fallback. The current proxy worker explicitly uses `libx264`; GPU acceleration is not an established feature.
4. Configurable cache budgets based on free disk/RAM and clear cache-management UI.
5. Robust seeking and frame-accurate scrubbing across VFR sources, unusual codecs, and overlapping tracks.
6. Direct manipulation crop overlay matching the reference (the V28 toolbar action only navigates to numeric crop controls).
7. Full real-Windows GUI validation. PySide6 is not installed in the current build environment, so GUI launch and interaction cannot be claimed verified here.
8. Automated end-to-end test with real video + image + audio layers, audio sync, save/reopen, and final export comparison.

## Recommended order

1. Establish repeatable baseline tests and benchmark clips (H.264 CFR, H.265, VFR phone footage, image overlay, audio overlay).
2. Fix correctness contracts: project-time/source-time mapping, clip interval boundaries, missing media handling, audio mix, stale-worker cancellation, and export snapshot consistency.
3. Improve still-frame cache and scrub scheduler; do not launch duplicate workers for every mouse movement.
4. Implement adaptive proxies and configurable cache budget; originals remain authoritative for export.
5. Benchmark current composite playback, then choose whether to incrementally improve it or replace it with a native frame scheduler/compositor. Do not run two competing playback clocks.
6. Add optional hardware decode/encode only after probing supported FFmpeg backends; keep CPU-only path first-class.
7. Port remaining tools and UI details against explicit behavior tests.

## Performance acceptance targets (targets, not yet measured)

- A 60-second 1080p H.264 project with one main video, one image overlay, and one audio layer should open and scrub without UI freezes.
- Proxy generation and thumbnail creation must run off the UI thread and must not saturate all CPU cores.
- Repeated playback should reuse valid composite/cache artifacts.
- Export should use original media unless the user explicitly chooses proxy export.
- If hardware acceleration fails, preview/export should fall back cleanly to software.
- No feature is marked complete based only on the presence of a button.
