# Reference architecture notes

Skyzen keeps its existing Python/PySide6 + FFmpeg architecture. The uploaded
OpenCut and Concat repositories are used as design references, not as copied
source modules.

## Principles applied in Skyzen V27

- **Explicit layer order:** the snapshot sorts visual clips bottom-to-top before
  constructing the FFmpeg filter graph.
- **One synchronized playback output:** video layers and their audio are
  combined into one composite, avoiding separate players drifting out of sync.
- **Immutable render snapshots:** the preview worker receives a snapshot of the
  current timeline state instead of querying widgets while rendering.
- **Selection-aware inspector:** controls write to the currently selected clip;
  the empty inspector does not expose active editing controls.
- **Profile-specific preview artifacts:** changing quality changes the render
  signature and cache profile; a low-resolution proxy is never accepted as a
  proxy for a different quality profile.
- **Bounded CPU use:** one proxy worker at a time, ultrafast encoding and a
  Performance default; Clear mode is optional and uses originals.

## Reference concepts not yet ported

OpenCut's command/undo architecture, keyframe editing, effect stacks and richer
property registry are broader than the current Skyzen model. Concat's rational
frame-time model, linear-light working space, shader passes, alpha-correct GPU
compositor, masks, transitions, HDR paths and scopes require a dedicated engine
project. They are not claimed to exist in V27, and the original repositories'
source files have not been merged into Skyzen.

## Licensing note

OpenCut and Concat retain their own licenses and attribution requirements.
This build does not copy their implementation files; only general architectural
ideas are documented here. Any future source-level port should be reviewed for
license compatibility before code is merged.
