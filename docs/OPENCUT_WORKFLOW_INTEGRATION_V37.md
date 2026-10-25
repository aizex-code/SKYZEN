# Skyzen V37 — OpenCut Workflow Integration Notes

## What was changed in V37

- Fixed timeline scroll synchronization to normalize the scroll value against the scrollbar that actually received the gesture (`source_bar`) before applying it to the timeline, layer sidebar, and edit gutter.
- The existing regression test expected this contract; it failed in V36 and now passes.
- No new runtime, external dependency, or second playback clock was introduced.

## Architecture findings

OpenCut Classic is implemented primarily with TypeScript/React plus Rust/WASM support. Skyzen is a native PySide6/Python application with an FFmpeg-backed project preview/export pipeline. OpenCut's source cannot be dropped directly into Skyzen as if both projects shared the same UI framework. The maintainable approach is to port behavior and data contracts into Skyzen's existing modules, while retaining required upstream license notices if any source code is copied.

## Panel-to-engine responsibilities

| UI / subsystem | Skyzen module | Contract to preserve |
|---|---|---|
| Media browser / import | `app/left_panel/main.py`, `app/main_window/main.py` | Import registers media in the bin; explicit add-to-timeline inserts it into the editable timeline model. |
| Timeline lanes, clips, selection, trim | `app/timeline_panel/main.py`, `core.py`, `track_layout.py`, `app/timeline_trim_math.py` | Timeline interactions update the same clip records used by preview and export. |
| Layer/sidebar and edit gutter scrolling | `app/timeline_panel/alignment.py` | Any of the three scroll columns may originate a gesture; visible rows must stay aligned. |
| Player and play/pause | `app/player_panel/main.py`, `app/video_engine/controller.py` | Playback should use one synchronized project composite, not independent per-layer playback clocks. |
| Preview/export render input | `app/video_engine/project_snapshot.py` | Build an immutable snapshot from the editable timeline. Preview proxies may be used only when available; export must use original sources. |
| FFmpeg composition | `app/video_engine/ffmpeg_backend.py`, `app/video_engine/render_worker.py` | Respect clip start/duration/source-in, track order, transforms, crop, opacity, audio gain/mute, and effect parameters. |
| Inspector | `app/inspector_panel/main.py` | Changes apply to the selected clip in the timeline model, then refresh preview from that same model. |
| Export | `app/export/` | Export consumes the project model/snapshot, not a separate preview-only state. |

## OpenCut behavior references inspected

- `apps/web/src/timeline/components/timeline-track.tsx` and `timeline-element.tsx`: lane layout and clip interaction.
- `apps/web/src/timeline/controllers/resize-controller.ts` and `drag-drop-controller.ts`: trim and placement interaction.
- `apps/web/src/timeline/hooks/use-scroll-sync.ts`: synchronized scroll behavior.
- `apps/web/src/core/managers/timeline-manager.ts`: edits are applied to the canonical timeline state through commands.
- `apps/web/src/core/managers/playback-manager.ts`: playback time is a single project-level state.
- `apps/web/src/services/renderer/scene-builder.ts` and renderer node modules: render composition is derived from timeline state.

## Validation

Run from this project directory:

```bat
python -m pytest -q
```

V37 result in the build environment: **77 passed, 3 skipped**.

## Important limitation

Passing automated tests is not proof of pixel-perfect visual parity or correctness on every codec/GPU/Windows machine. The three skipped tests were not executed in this environment. A final manual pass is still needed for import, add-to-timeline, drag, trim, crop, inspector edits, multi-layer video/audio playback, save/reopen if applicable, and export. Keep OpenCut attribution/license notices if copying any of its source code into a distributed derivative.
