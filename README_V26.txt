Skyzen V26 — Precision Inspector & Chroma Key
=============================================

Changes from V25
----------------
- Numeric spinboxes no longer consume the mouse wheel unless that exact field
  has focus and the pointer is over it. Otherwise the wheel can scroll the
  inspector normally.
- Slider resolution increased tenfold while retaining the same parameter
  ranges. Numeric fields display three decimal places for finer grading.
- Chroma key is now connected to the FFmpeg compositor:
  * Click Enable chroma key.
  * Click Pick color, then click a pixel inside the player preview.
  * Color tolerance controls how much of the sampled color is removed.
  * Edge softness controls the transition around the keyed color.
  * Foreground opacity controls the alpha of the remaining foreground.
- Key color and settings are stored on the selected clip, included in project
  fingerprints/cache signatures, and used by paused-frame and full-project
  renders. Turning on the key defaults to green until another color is picked.
- Preview H.264 quality increased from CRF 32 to CRF 27; the preview remains
  640x360, ultrafast, and low-latency to avoid a large playback performance hit.
- Reduced inspector padding and adjusted the initial workspace/timeline split.

Chroma-key behavior
-------------------
The eyedropper samples a pixel from the visible player surface. Keying uses
FFmpeg's colorkey filter in RGBA before the clip is composited onto the project
canvas. Color tolerance and edge softness are the active keying parameters.
Foreground opacity multiplies the remaining alpha, preserving transparent
pixels. It is not a full node-based keyer and does not yet include advanced
spill suppression, masks, or per-channel curves.

Playback
--------
Playback still uses a single synchronized composite file for reliable mixed
audio and multitrack timing. It remains a CPU/FFmpeg render pipeline, not a
GPU-native real-time compositor. Proxies, cancellation of stale renders,
bounded preview refreshes, and a low-resolution preview remain enabled.

Validation
----------
The source is compiled and the automated suite is run before packaging.
