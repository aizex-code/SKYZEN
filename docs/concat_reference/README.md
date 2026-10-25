# Supplied Concat source references

These are byte-for-byte copies of the Rust files supplied in `src(5).zip` and
`src(6).zip`. They are preserved as reference material, not compiled into
Skyzen. Skyzen is currently a Python/PySide6 application and its active render
path is Python + FFmpeg; Rust modules cannot be dropped into that runtime
without a deliberate FFI/build integration.

## Mapping to Skyzen

| Concat source concept | Skyzen integration point |
|---|---|
| `core/time.rs` | `app/timeline_panel/core.py` timing and frame positioning; `app/video_engine/project_snapshot.py` render snapshot |
| `core/timeline.rs` | `app/timeline_panel/core.py` editable tracks/clips and `app/video_engine/project_snapshot.py` immutable render data |
| `core/arena.rs` | Future stable IDs/undo history for clips, tracks and effects |
| `core/animate.rs`, `core/retime.rs` | Future keyframe and variable-speed models; these reference files do not mean the features are implemented |
| `media/probe.rs` | `app/left_panel/main.py` media import metadata |
| `media/decode.rs`, `media/pool.rs`, `media/prefetch.rs` | Current FFmpeg preview path in `app/video_engine/` and `app/player_panel/`; current path is not a direct port of Concat's reader pool |
| `media/peaks.rs`, `media/samples.rs`, `media/audio.rs` | Audio waveform/mix pipeline in `app/video_engine/ffmpeg_backend.py` |
| `media/encode.rs`, `media/treat.rs`, `media/hardware.rs` | Export and preview rendering in `app/export/` and `app/video_engine/ffmpeg_backend.py` |

## Important

- Files in this folder are reference-only and intentionally left unmodified.
- The supplied snippets do not include a complete Cargo workspace, crate
  manifests, or all dependencies needed to build Concat as a standalone engine.
- Preserve the upstream SPDX/copyright headers in the source files.
- Before copying/adapting any Concat implementation into Skyzen, review the
  upstream AGPL-3.0-or-later license and any applicable exceptions, then retain
  all required notices and comply with the license.
