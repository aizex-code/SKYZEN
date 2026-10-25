# Skyzen architecture

Skyzen is a small desktop video editor. Keep the editing model, preview engine,
panels, and export code separate. Fix a component in its own module unless a
public interface genuinely needs to change.

## Run

1. Install Python 3.10+.
2. Run `python -m pip install -r requirements.txt`.
3. Install FFmpeg and FFprobe and place them on PATH, or in the project's
   `ffmpeg` directory.
4. Run `run.bat` on Windows or `python main.py`.

## Responsibilities

| Path | Responsibility |
|---|---|
| `main.py` | Application entry point and crash logging. |
| `app/main_window/main.py` | Builds the window, panels, splitters, and signal connections. |
| `app/ui/theme.py` | Shared UI colors and styling. |
| `app/left_panel/main.py` | Media import, folder browsing, thumbnails, and drag/drop. |
| `app/media/thumbnail_service.py` | Background thumbnail generation. |
| `app/media/proxy_service.py` | Optional source proxies; never overwrites originals. |
| `app/player_panel/main.py` | Player surface, controls, and source/timeline mode. |
| `app/player_panel/live_playback.py` | Legacy per-clip decoder implementation retained for reference; it is not attached to the active project controller. |
| `app/player_panel/live_composite.py` | Draws overlapping video and image layers into one preview canvas. |
| `app/player_panel/preview_frame.py` | Displays a rendered paused frame. |
| `app/video_engine/controller.py` | Coordinates cached composite playback, paused-frame rendering, and timeline clock updates. |
| `app/video_engine/project_snapshot.py` | Copies timeline state into stable render data. |
| `app/video_engine/ffmpeg_backend.py` | Builds FFmpeg commands for paused frames and export previews. |
| `app/video_engine/render_worker.py` | Runs FFmpeg in a background worker. |
| `app/timeline_panel/core.py` | Timeline data, clip arrangement, trimming, splitting, deletion, and playhead. |
| `app/timeline_panel/alignment.py` | Keeps timeline, layer labels, and edit gutter vertically synchronized. |
| `app/timeline_panel/track_layout.py` | Main-track positioning rules. |
| `app/inspector_panel/main.py` | Selected-clip transform controls. |
| `app/export/` | Export dialog, codec profiles, and export worker. |

## Preview behavior

### Project playback (single clip or multiple tracks)

Normal timeline playback uses `build_project_command()` to render a low-resolution
composite MP4 in a background worker. It composites all visible video/image
layers in timeline stack order and mixes the main video's soundtrack with
separate audio-track clips. Overlay video soundtracks are muted by default.
Qt then plays one file through the existing `QMediaPlayer`/`QVideoWidget`, so
all layers and mixed audio share a single playback clock instead of independent
per-clip clocks and decoders.

Play/Pause is the only action that changes playback state; selecting media, selecting a timeline clip, and opening fullscreen do not start a paused project. Pausing a valid composite holds its current frame instead of scheduling a competing still render. The first Play after an edit may take time to prepare the preview. The completed
composite is cached by project signature and reused until the timeline changes. Cache identity includes both original and selected proxy input file stamps.
This is a responsiveness tradeoff: playback is more predictable, but changes
made during playback require pausing and rebuilding the composite. The cached
preview is low resolution and never affects final export quality.

### Paused scrubbing

While paused, the controller asks FFmpeg to render a single low-resolution frame
in the background. It coalesces rapid playhead changes rather than launching a
render for every scrub event. Final export remains a separate FFmpeg operation. Preview transform offsets are scaled from the 1280x720 project coordinate space to the selected preview/export resolution.

## Timeline layout

`TimelinePanel` owns clip data and editing interactions. `alignment.py` keeps
the track area, left-side layer controls, and edit gutter at one vertical scroll
position. `track_layout.py` keeps the main lane centered with no overlays,
moves it down for one or two overlays, and pins it near the bottom when the
overlay stack grows.

## Media and export

- Imported originals are left untouched.
- Optional proxies are background editing copies shared by every clip that
  references the same source.
- MOV is a container, not a universal playback speed improvement.
- Final export settings are independent from preview quality.

## Diagnostics and validation

Python and FFmpeg preview diagnostics are written to `skyzen-crash.log` beside
`main.py`. Pure-Python regression tests can be run with:

```bash
python -m unittest discover -s tests -t .
```

The GUI and native Qt Multimedia backend must still be tested on Windows; syntax
and source-level tests cannot prove device-specific decoder stability.
