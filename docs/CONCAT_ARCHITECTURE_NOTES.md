# Concat architecture reference for Skyzen

The exact supplied Rust source files are retained under `docs/concat_reference/`.
See that folder's README for the file-by-file mapping. They are not silently
translated or represented as running code: Skyzen remains a Python/PySide6
editor using FFmpeg for its active preview and export path.

## Rules for changes

1. Preserve one shared timeline time axis for ruler, clips, playhead and preview.
2. Keep timeline/document data separate from timeline presentation and scroll state.
3. Keep visual layer order explicit and composite all visible layers through one
   project render path.
4. Keep a single active project playback clock/player; do not reintroduce
   per-clip playback clocks.
5. Keep expensive decoding, proxy generation and composite rendering off the Qt
   GUI thread.
6. Keep preview quality independent from export quality.
7. Add a regression test for each fix to scrolling, audio mixing, timing,
   playback state, import or export before changing adjacent components.

## Current Skyzen mapping

- Editable clips/tracks and timeline interactions: `app/timeline_panel/core.py`
- Track positioning and synchronized scroll helpers: `app/timeline_panel/track_layout.py`,
  `app/timeline_panel/alignment.py`, and `app/timeline_panel/timebar/`
- Immutable render snapshot: `app/video_engine/project_snapshot.py`
- FFmpeg graph and command construction: `app/video_engine/ffmpeg_backend.py`
- Background render process: `app/video_engine/render_worker.py`
- Project preview clock/cache: `app/video_engine/controller.py`
- UI composition and theme: `app/ui/editor_layout.py`, `app/ui/theme.py`
- Panel integration and shortcuts: `app/main_window/main.py`

The current application is an implementation of selected architecture
principles, not a complete port of Concat's Rust engine. The source references
are useful for designing future improvements but do not by themselves add
Concat's decoding, cache, animation or retiming features to Skyzen.
