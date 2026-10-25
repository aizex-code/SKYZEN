# OpenCut → Skyzen Port Map (reference only)

OpenCut's web/TypeScript/Rust implementation is not a direct drop-in for PySide6. Port behavior and data contracts, not source syntax. Keep OpenCut's license and notices intact and review licensing before distributing a derivative.

## Timeline

| OpenCut reference | Skyzen area | Port focus |
|---|---|---|
| `apps/web/src/timeline/components/timeline-track.tsx` | `app/timeline_panel/core.py`, `track_layout.py` | Track ordering, row geometry, selection, clip placement |
| `apps/web/src/timeline/components/timeline-element.tsx` | `app/timeline_panel/core.py` | Clip hit-testing, trim handles, drag feedback |
| `apps/web/src/timeline/components/timeline-ruler.tsx` | `app/timeline_panel/timebar/` | Time labels, ticks, zoom math |
| `apps/web/src/timeline/components/timeline-playhead.tsx` | `app/timeline_panel/marker/`, `timebar/timemarker.py` | Playhead geometry and frame snapping |
| `apps/web/src/timeline/controllers/resize-controller.ts` | `app/timeline_trim_math.py`, timeline core | Trim math and source in/out constraints |
| `apps/web/src/timeline/controllers/drag-drop-controller.ts` | timeline core and media import | Drop targets and track creation |
| `apps/web/src/timeline/controllers/zoom-controller.ts` | timeline core/timebar | Zoom anchor and scroll stability |
| `apps/web/src/timeline/hooks/use-scroll-sync.ts` | `app/timeline_panel/alignment.py` | Shared scroll ownership and lane alignment |

## Renderer/media

| OpenCut reference | Skyzen area | Port focus |
|---|---|---|
| `apps/web/src/core/managers/timeline-manager.ts` | `app/video_engine/project_snapshot.py`, timeline core | Canonical project timeline data and time mapping |
| `apps/web/src/services/renderer/scene-builder.ts` | `app/video_engine/ffmpeg_backend.py` | Layer ordering and project snapshot → render graph |
| `apps/web/src/services/renderer/gpu-renderer.ts` | no equivalent active GPU compositor verified | Treat as architecture reference; do not translate line-for-line |
| `apps/web/src/services/renderer/compositor/wasm-compositor.ts` | FFmpeg filter graph / possible future native compositor | Alpha, blend order, frame scheduling |
| `apps/web/src/services/renderer/nodes/video-node.ts` | FFmpeg input/filter graph | Video clip timing and transforms |
| `apps/web/src/services/renderer/nodes/image-node.ts` | image input in FFmpeg graph and preview widget | Still duration, scaling, alpha |
| `apps/web/src/media/mediabunny.ts` | FFmpeg/FFprobe backend | Probe, decode, source metadata |
| `apps/web/src/media/waveform-summary.ts` | media/waveform code if present | Cached waveform summaries |

## Rules for a safe port

- First write a behavior contract and test cases for the specific OpenCut feature.
- Keep project-time, source-time, frame rate, and half-open clip interval semantics consistent.
- Preserve current working Skyzen features; avoid parallel playback clocks.
- Prefer FFmpeg and PySide6 APIs already in the project before adding a new runtime.
- Introduce C++/Rust only after profiling shows a bottleneck and a small native module has a measurable benefit.
- Hardware acceleration is optional and capability-probed; CPU-only fallback must remain supported.
