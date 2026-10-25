# V19: audio silence and layer-scroll analysis

## Audio cause confirmed in source

The composite renderer (`app/video_engine/ffmpeg_backend.py`) used to collect
embedded soundtracks only when `clip["is_main"]` was true. That condition was
the direct cause of silent overlay clips: the overlay's video was included in
the visual compositor, but its audio stream was never added to the audio mix.
Dedicated audio tracks worked through a separate path, which made the behavior
seem inconsistent depending on whether a sound came from the main clip, an
overlay, or a dedicated audio lane.

## V19 audio behavior

- Every video clip in the visible video stack is considered for embedded audio.
- Clips with no audio stream are skipped after probing.
- Track mute and volume are carried through `build_snapshot`; a muted layer or
  a zero-volume layer contributes no embedded audio.
- Dedicated audio clips continue to use their own track mute/volume values.
- The audio graph uses one shared mix and a limiter, preventing a raw sum of
  several overlapping soundtracks from clipping as easily.
- Preview cache profile changed to `composite360-audio-v4`, forcing the old
  main-only composite cache to be regenerated.

If multiple overlay videos are duplicates of the same source and each layer is
unmuted, each soundtrack is intentionally mixed. Use the layer context menu's
**Volume…** action or **Mute Layer** to control those contributions.

## Layer scrolling cause / fix

The timeline already had a shared vertical-scroll coordinator for the clip
canvas, layer sidebar, and edit gutter. However, wheel gestures over header
controls could be handled by the child widget instead of reaching the scroll
area. V19 installs a wheel-event filter on each layer header and its child
controls, forwarding handled wheel events to the shared master scroll bar.

The timeline's dedicated bottom creation area was only 8 pixels high. V19
reserves two track rows plus a small margin and aligns a matching add-layer zone
in the sidebar when the stack is tall enough to scroll.

## Import / preview latency

The old project setting defaulted proxy creation off. V19 performs a one-time
settings migration to enable it by default, queues current timeline/bin videos,
and generates 640x360 H.264 ultrafast + AAC proxies in a background worker.
Versioned proxy markers prevent old-resolution or stale-profile proxies from
being mistaken for current ones. Originals are still used for final export.

After edits settle, a debounced background composite render is scheduled. This
usually moves the render delay before the user presses Play; it does not make
rendering instantaneous. The first composite after a meaningful edit still has
to be built, and heavy projects can still take time.

## Tests performed

- Automated regression suite: 41 passed.
- Python source compilation passed.
- Real FFmpeg smoke test with overlapping main/overlay videos and distinct
  embedded audio streams produced a valid H.264/AAC MP4. ffprobe confirmed both
  streams and `volumedetect` confirmed the audio output was not silent.

The Qt GUI could not be launched in the current build environment because
PySide6 is unavailable here. The new scroll forwarding and desktop behavior
still need confirmation on Windows.
