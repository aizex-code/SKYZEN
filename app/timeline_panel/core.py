from __future__ import annotations

import copy
import math
import re
import shutil
import subprocess
from pathlib import Path

SKYZEN_TIMELINE_DESIGN_VERSION = "v19-audio-layer-scroll-fix"

from PySide6.QtCore import (
    Qt,
    Signal,
    QMimeData,
    QPoint,
    QRectF,
    QTimer,
)
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QFontMetrics, QPixmap, QImageReader, QCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QMenu,
    QInputDialog,
    QScrollArea,
    QSlider,
    QComboBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from .alignment import SyncedColumn, TimelineScrollCoordinator
from .track_layout import reserved_bottom_gap, symmetric_outer_gap
from app.media.thumbnail_service import ThumbnailService
from app.timeline_trim_math import left_trim_frames, right_trim_frames
from app.timeline_insert_math import ripple_insert_plan, overlap_insert_boundary, contiguous_frame_starts

# ============================================================
# Skyzen Timeline Panel
#
# Visual target:
#   - CapCut-like compact toolbar
#   - fixed left layer panel
#   - clean track rows, no vertical grid inside layers
#   - exact 30 FPS time axis
#   - ruler + clip geometry share exactly one coordinate system
#   - continuous zoom anchored on the playhead
#   - real media duration -> exact clip width
#   - thumbnail strip / waveform
#   - free horizontal clip movement with direct pointer movement
#   - frame-accurate trim handles
#   - existing-track drops stay on that layer
#   - drop below tracks creates a new compatible layer
#
# This file is intentionally timeline-only.
# ============================================================


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".wmv"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}
AUDIO_EXTS = {".wav", ".mp3", ".flac", ".aac", ".m4a", ".ogg"}


COLORS = {
    "background": "#232323",
    "toolbar": "#2A2A2A",
    "ruler": "#202020",
    "ruler_tick": "#7F8791",
    "header": "#2A2A2A",
    "track": "#242424",
    "track_alt": "#292929",

    # Subtle separators only — never bright white/yellow.
    "track_line": "#3A3A3A",
    "border": "#3A3A3A",

    "text": "#EEEEEE",
    "muted": "#A5A5A5",

    # Skyzen timeline accent.
    "cyan": "#00D8E8",
    "cyan_dark": "#173137",
    "selection": "#00D8E8",

    "handle": "#19191B",
    "handle_hover": "#00D9FF",

    "video": "#0F6A72",
    "image": "#1FA88A",
    "audio": "#17627A",
    "audio_wave": "#6FD8EE",
    "tool_text": "#B27CFF",
    "tool_effect": "#F2A44A",
    "tool_adjustment": "#54C995",
    "tool_filter": "#5CB8FF",
    }


# ============================================================
# Media helpers
# ============================================================

_FREE_STRETCH_TOOL_TYPES = ("Text", "Effects", "Filters", "Adjustments")


def is_freely_stretchable_clip(clip: dict) -> bool:
    """True for clips with no real media source: still images and the
    synthetic overlay clips created by the Text/Effects/Filters/Adjustments
    tools. These have no intrinsic length, so either edge can be dragged
    freely, unlike video/audio whose edges are bounded by source media."""
    if str(clip.get("tool_type", "")) in _FREE_STRETCH_TOOL_TYPES:
        return True
    return str(clip.get("kind", "")).lower() == "image"


def detect_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in AUDIO_EXTS:
        return "Audio"
    if ext in IMAGE_EXTS:
        return "Image"
    if ext in VIDEO_EXTS:
        return "Video"
    return "Video"


def _find_local_binary(root_dir: Path, filename: str, path_name: str) -> Path | None:
    """
    Locate FFmpeg tools even when the editor lives in a nested project folder.

    Skyzen commonly has:
        D:\\SKYZEN\\ffmpeg\\ffprobe.exe
        D:\\SKYZEN\\Skyzen_Working_Editor_v1\\app\\...
    so checking only root_dir/ffmpeg can silently fall back to the old 5-second
    placeholder. We search the editor folder, its parents, the Skyzen root, and
    finally PATH.
    """
    root = Path(root_dir).resolve()

    candidates = []
    for base in (root, *root.parents):
        candidates.append(base / "ffmpeg" / filename)

    # Explicit project-root fallback for the normal Skyzen layout.
    try:
        candidates.append(Path("D:/SKYZEN") / "ffmpeg" / filename)
    except Exception:
        pass

    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue

    found = shutil.which(path_name)
    return Path(found).resolve() if found else None


def ffprobe_path(root_dir: Path) -> Path | None:
    return _find_local_binary(
        root_dir,
        "ffprobe.exe",
        "ffprobe",
    )


def ffmpeg_path(root_dir: Path) -> Path | None:
    return _find_local_binary(
        root_dir,
        "ffmpeg.exe",
        "ffmpeg",
    )


def _parse_ffmpeg_duration(stderr: str) -> float:
    match = re.search(
        r"Duration:\\s*(\\d+):(\\d+):(\\d+(?:\\.\\d+)?)",
        stderr or "",
        flags=re.IGNORECASE,
    )
    if not match:
        return 0.0

    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    return max(
        0.0,
        hours * 3600.0 + minutes * 60.0 + seconds,
    )


def source_duration(path: Path, root_dir: Path) -> float:
    """
    Read the real source duration.

    There is deliberately NO fake 5-second fallback anymore. If ffprobe is not
    found beside the project, FFmpeg itself is used as a fallback and its
    Duration field is parsed. This prevents a real 60+ second source from being
    represented as a 5-second timeline clip.
    """
    probe = ffprobe_path(root_dir)

    if probe is not None:
        try:
            result = subprocess.run(
                [
                    str(probe),
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
            )

            value = float(
                (result.stdout or "").strip()
            )

            if value > 0.0:
                return max(
                    1.0 / 30.0,
                    value,
                )
        except Exception:
            pass

    ffmpeg = ffmpeg_path(root_dir)
    if ffmpeg is not None:
        try:
            result = subprocess.run(
                [
                    str(ffmpeg),
                    "-hide_banner",
                    "-i",
                    str(path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=12,
            )

            value = _parse_ffmpeg_duration(
                result.stderr or ""
            )

            if value > 0.0:
                return max(
                    1.0 / 30.0,
                    value,
                )
        except Exception:
            pass

    # Last-resort value: one frame, not a fabricated 5-second clip.
    return 1.0 / 30.0


def thumbnail_cache_path(path: Path, root_dir: Path) -> Path:
    cache_dir = root_dir / "cache" / "timeline_thumbnails"
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        stat = path.stat()
        stamp = f"{stat.st_size}_{stat.st_mtime_ns}"
    except OSError:
        stamp = "0"
    key = abs(hash((str(path.resolve()), stamp))) & 0xFFFFFFFF
    return cache_dir / f"{path.stem}_{key:08x}.jpg"


def make_video_thumbnail(path: Path, root_dir: Path) -> QPixmap:
    cache = thumbnail_cache_path(path, root_dir)
    if not cache.exists():
        ffmpeg = ffmpeg_path(root_dir)
        if ffmpeg is not None:
            try:
                subprocess.run(
                    [
                        str(ffmpeg),
                        "-y",
                        "-ss", "0.25",
                        "-i", str(path),
                        "-frames:v", "1",
                        "-vf", "scale=480:-2",
                        str(cache),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=12,
                )
            except Exception:
                return QPixmap()
    return QPixmap(str(cache)) if cache.exists() else QPixmap()


def audio_waveform_pixmap(path: Path, width: int, height: int) -> QPixmap:
    """Deterministic lightweight waveform fallback. It is visual-only.

    Clip data may come from older projects or UI callbacks as a string path,
    so normalize it here rather than allowing a paintEvent to fail.
    """
    path = Path(str(path or ""))
    # A long audio clip can span a very wide timeline at high zoom. Never
    # allocate a pixmap proportional to the entire clip width during paint.
    width = max(2, min(4096, int(width)))
    height = max(2, min(256, int(height)))
    pix = QPixmap(width, height)
    pix.fill(QColor(COLORS["audio"]))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    seed = max(1, sum(path.name.encode("utf-8")))
    mid = height // 2
    pen = QPen(QColor(COLORS["audio_wave"]))
    pen.setWidth(1)
    painter.setPen(pen)
    for x in range(2, width - 2, 2):
        amp = 2 + abs(((x * 17 + seed) % max(4, height // 2)) - max(2, height // 4))
        amp = min(mid - 2, amp)
        painter.drawLine(x, mid - amp, x, mid + amp)
    painter.end()
    return pix


def frame_time(seconds: float, fps: int = 30) -> float:
    return max(0, int(round(max(0.0, float(seconds)) * fps))) / fps


def timecode(seconds: float, fps: int = 30) -> str:
    frames = max(0, int(round(float(seconds) * fps)))
    h, rem = divmod(frames, fps * 3600)
    m, rem = divmod(rem, fps * 60)
    s, f = divmod(rem, fps)
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def short_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    total = int(round(seconds))
    m, s = divmod(total, 60)
    return f"{m:02d}:{s:02d}"


# ============================================================
# Clip widget
# ============================================================

class ClipWidget(QWidget):
    selected = Signal(str, float, float, str)
    changed = Signal()

    # Narrow edge zones: the custom cursor is shown only when hovering an edge.
    HANDLE_PX = 10
    _edge_cursors = {}

    @classmethod
    def _edge_cursor(cls, side: str):
        """Create the requested CapCut-like </ and /> trim cursor affordances."""
        cursor = cls._edge_cursors.get(side)
        if cursor is not None:
            return cursor
        pixmap = QPixmap(34, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Dark, unobtrusive trim cursor so it stays readable without the
        # bright white cursor that previously competed with the clip UI.
        painter.setPen(QColor("#15191F"))
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "</" if side == "left" else "/>" )
        painter.end()
        cursor = QCursor(pixmap, 17, 12)
        cls._edge_cursors[side] = cursor
        return cursor

    def _trim_edge_at(self, x: float) -> str | None:
        """Return the edge under the pointer without overlapping tiny clips.

        Normal clips have narrow edge handles. When a clip is narrower than
        both handle zones combined, split its usable width at the midpoint so
        the right edge remains reachable instead of every click selecting the
        left edge.
        """
        width = max(1, self.width())
        if width <= 2:
            # A one/two-pixel clip has no usable body area; split the available
            # hit area evenly so either edge can still be reached.
            return "left" if x < width / 2.0 else "right"
        if width <= 2 * self.HANDLE_PX:
            # Keep a small center zone for moving narrow clips. Using the full
            # width as overlapping edge zones makes every click a trim.
            edge_zone = min(float(self.HANDLE_PX), width / 3.0)
            if x <= edge_zone:
                return "left"
            if x >= width - edge_zone:
                return "right"
            return None
        if x <= self.HANDLE_PX:
            return "left"
        if x >= width - self.HANDLE_PX:
            return "right"
        return None

    def _set_hover_cursor(self, x: float):
        edge = self._trim_edge_at(x)
        if edge == "left":
            self.setCursor(self._edge_cursor("left"))
        elif edge == "right":
            self.setCursor(self._edge_cursor("right"))
        else:
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def __init__(self, track: dict, clip: dict, timeline: "TimelinePanel", parent=None):
        super().__init__(parent)
        self.track = track
        self.clip = clip
        self.timeline = timeline

        self.drag_start = QPoint()
        self.original_start_frame = timeline.frame_from_seconds(clip["start"])
        self.original_duration_frames = max(
            1, timeline.frame_from_seconds(clip["duration"])
        )
        self.mode = "move"
        self.dragging = False
        self._move_started = False
        self._move_ghost = None
        self._ghost_offset = QPoint()
        self._drag_start_global = QPoint()
        # Freeze the timeline scale for the duration of a trim gesture. The
        # pointer-to-frame mapping must not drift if layout/zoom state updates
        # while the clip widget is being resized.
        self._trim_pixels_per_frame = max(0.001, float(timeline.pixels_per_frame))
        self._trim_original_source_in_frames = timeline.frame_from_seconds(
            clip.get("source_in", 0.0)
        )

        tool_type = str(clip.get("tool_type", ""))
        tool_colors = {
            "Text": COLORS["tool_text"],
            "Effects": COLORS["tool_effect"],
            "Adjustments": COLORS["tool_adjustment"],
            "Filters": COLORS["tool_filter"],
        }
        self.color = tool_colors.get(tool_type, {
            "Video": COLORS["video"], "Image": COLORS["image"], "Audio": COLORS["audio"],
        }.get(clip.get("kind"), COLORS["video"]))
        self.thumbnail = None if tool_type in ("Text", "Effects", "Filters", "Adjustments") else timeline.thumbnail_for(clip)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setMinimumWidth(2)
        from .track_layout import clip_height
        self.setFixedHeight(clip_height(timeline, track))
        # Clip surfaces intentionally have no hover tooltip; it obscures the edit.
        self.setToolTip("")

    # ---------- geometry / state ----------

    def _tooltip_text(self) -> str:
        return (
            f'{self.clip.get("path", "")}\n'
            f'{self.clip.get("kind", "Video")}\n'
            f'Start: {timecode(self.clip["start"], self.timeline.FPS)}\n'
            f'Duration: {timecode(self.clip["duration"], self.timeline.FPS)}'
        )

    def _sync_geometry(self):
        start_x = self.timeline.time_to_x(self.clip["start"])
        end_x = self.timeline.time_to_x(
            self.clip["start"] + self.clip["duration"]
        )
        width = max(2, end_x - start_x)
        from .track_layout import clip_height, row_height
        clip_h = clip_height(self.timeline, self.track)
        # Use the actual row geometry for compact typed layers as well as Main.
        # Using TRACK_HEIGHT here made typed clips extend beyond their row,
        # stealing hit-tests from the first lane and making edge trims unreliable.
        row_h = row_height(self.timeline, self.track)
        self.setGeometry(
            start_x,
            max(self.timeline.CLIP_TOP_MARGIN, (row_h - clip_h) // 2),
            width,
            clip_h,
        )
        # Clip surfaces intentionally have no hover tooltip; it obscures the edit.
        self.setToolTip("")
        self.update()

    def _set_selected(self):
        self.timeline.select_clip(self.clip, self)
        self.update()

    # ---------- mouse interaction ----------

    def _begin_direct_move(self, event):
        """Start a local visual drag without using Qt's drag/drop system."""
        if self._move_ghost is not None:
            return

        content = self.timeline.content
        self._move_ghost = QLabel(content)
        self._move_ghost.setPixmap(
            self.grab()
        )
        self._move_ghost.setScaledContents(True)
        self._move_ghost.setFixedSize(self.size())
        self._move_ghost.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        self._move_ghost.setStyleSheet(
            "QLabel { background: transparent; border: 0; }"
        )
        gp = self.mapToGlobal(event.position().toPoint())
        cp = content.mapFromGlobal(gp)
        self._ghost_offset = event.position().toPoint()
        self._move_ghost.move(
            cp.x() - self._ghost_offset.x(),
            cp.y() - self._ghost_offset.y(),
        )
        self._move_ghost.show()
        self._move_ghost.raise_()

        # Keep this widget alive to retain mouse capture, but move it offscreen.
        self.move(-10000, -10000)

    def _target_track_from_pointer(self, global_pos, vertical_delta=None):
        """Resolve an existing compatible layer only.

        Dragging a clip over an existing row can move it.  A vertical drag must
        never silently create a layer. New layers are created only through the
        explicit Edit Layer drop target, an insertion gap held long enough, or
        the dedicated bottom creation zone.
        """
        compatible = [
            track for track in self.timeline.display_tracks()
            if track.get("base") == self.track.get("base")
        ]
        if not compatible:
            return self.track

        # Prefer the exact row under the pointer.
        target = self.timeline.track_at_global_pos(global_pos, self.track.get("base"))
        if target is not None:
            return target

        # If the pointer is over a separator, choose the closest existing row.
        try:
            gp = global_pos
            content = self.timeline.content
            cp = content.mapFromGlobal(gp)
            y = float(cp.y())
        except Exception:
            return self.track

        best = None
        best_distance = float("inf")
        for track, row_top in self.timeline.track_row_positions():
            if track.get("base") != self.track.get("base"):
                continue
            center = row_top + self.timeline.TRACK_HEIGHT * 0.5
            distance = abs(y - center)
            if distance < best_distance:
                best_distance = distance
                best = track

        return best or self.track

    def _ghost_move(self, event):
        if self._move_ghost is None:
            return

        content = self.timeline.content
        gp = event.globalPosition().toPoint()
        cp = content.mapFromGlobal(gp)

        self._move_ghost.move(
            cp.x() - self._ghost_offset.x(),
            cp.y() - self._ghost_offset.y(),
        )
        self._move_ghost.raise_()
        # Show the destination and any clips that will ripple to the right.
        delta_x = float(gp.x() - self._drag_start_global.x())
        requested_frame = self.original_start_frame + int(round(
            delta_x / max(0.001, self.timeline.pixels_per_frame)
        ))
        target = self._target_track_from_pointer(gp, vertical_delta=0)
        requested_frame, hit_existing = self.timeline._resolve_clip_drop_frame(
            target, gp, requested_frame, exclude_clip=self.clip
        )
        self.timeline._update_clip_drag_preview(
            self.clip, target, requested_frame, gp
        )

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)

        if self.track.get("locked", False):
            self.setCursor(Qt.CursorShape.ForbiddenCursor)
            self._set_selected()
            event.accept()
            return

        self.drag_start = event.position().toPoint()
        self._drag_start_global = event.globalPosition().toPoint()
        self._trim_pixels_per_frame = max(
            0.001, float(self.timeline.pixels_per_frame)
        )
        self.original_start_frame = self.timeline.frame_from_seconds(
            self.clip["start"]
        )
        self.original_duration_frames = max(
            1,
            self.timeline.frame_from_seconds(self.clip["duration"])
        )
        # Trim calculations are always based on the clip state at mouse-down.
        # Reading source_in from self.clip during mouseMove is wrong because
        # each previous mouseMove has already mutated it; this made a single
        # continuous left trim accumulate the delta repeatedly.
        self._trim_original_source_in_frames = self.timeline.frame_from_seconds(
            self.clip.get("source_in", 0.0)
        )
        self._trim_source_len_frames = None
        self.mode = "move"
        self.dragging = True
        self._trim_history_pushed = False
        self._move_started = False
        self._move_ghost = None
        self._ghost_offset = QPoint()

        x = float(event.position().x())
        edge = self._trim_edge_at(x)
        if edge == "left":
            self.mode = "trim_left"
            self.setCursor(self._edge_cursor("left"))
        elif edge == "right":
            self.mode = "trim_right"
            self.setCursor(self._edge_cursor("right"))
        else:
            self.mode = "move"
            # Closed-hand is used only while the mouse is actually dragging.
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

        if self.mode in ("trim_left", "trim_right") and not self._is_freely_stretchable():
            from app.timeline_trim_math import resolve_source_length_frames
            source_in_frames = int(self._trim_original_source_in_frames)
            raw_source_duration = self.clip.get("source_duration")
            try:
                raw_source_duration = float(raw_source_duration)
            except (TypeError, ValueError):
                raw_source_duration = 0.0
            if raw_source_duration <= 0.0:
                try:
                    probed_duration = source_duration(
                        Path(str(self.clip.get("path", ""))).expanduser(),
                        self.timeline.root_dir,
                    )
                    if float(probed_duration) > 0.0:
                        raw_source_duration = float(probed_duration)
                        self.clip["source_duration"] = (
                            self.timeline.frame_from_seconds(raw_source_duration)
                            / self.timeline.FPS
                        )
                except Exception:
                    raw_source_duration = 0.0
            raw_source_frames = (
                self.timeline.frame_from_seconds(raw_source_duration)
                if raw_source_duration > 0.0
                else None
            )
            trim_speed = max(0.1, min(8.0, float(self.clip.get("speed", 1.0))))
            self._trim_source_len_frames = resolve_source_length_frames(
                raw_source_frames, source_in_frames, int(round(self.original_duration_frames * trim_speed))
            )

        self._set_selected()
        event.accept()

    def mouseMoveEvent(self, event):
        if not self.dragging or not (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            if not self.dragging:
                x = float(event.position().x())
                self._set_hover_cursor(x)
                self.update()
            return super().mouseMoveEvent(event)

        if self.mode == "move":
            dx = float(event.position().x() - self.drag_start.x())
            dy = float(event.position().y() - self.drag_start.y())

            if not self._move_started and (
                abs(dx) >= 4 or abs(dy) >= 4
            ):
                self._move_started = True
                self._begin_direct_move(event)

            if self._move_started:
                self._ghost_move(event)
                event.accept()
                return

        # A body drag starts in "move" mode. Until the pointer crosses the
        # drag threshold, leave the clip untouched; do not route that event
        # through the edge-trim math (which intentionally accepts trim modes
        # only). This prevents a harmless click/tiny movement from raising
        # ValueError("unknown trim mode: move") inside Qt's event loop.
        if self.mode == "move":
            event.accept()
            return

        self._trim_drag(event)

        self._sync_geometry()
        self.timeline._move_marker()
        self.changed.emit()
        event.accept()

    def _is_freely_stretchable(self) -> bool:
        """True for clips with no real media source, so either edge can be
        dragged freely: still images, and the synthetic overlay clips made by
        the Text/Effects/Filters/Adjustments tools. These have no intrinsic
        length, unlike video/audio whose edges are bounded by source media."""
        return is_freely_stretchable_clip(self.clip)

    def _trim_neighbours(self, original_start: int, original_end: int):
        """(previous clip end, next clip start) on this track, in frames."""
        prev_end = None
        next_start = None
        for other in self.track.get("clips", []):
            if other is self.clip:
                continue
            o_start = self.timeline.clip_start_frame(other)
            o_end = self.timeline.clip_end_frame(other)
            if o_end <= original_start:
                prev_end = o_end if prev_end is None else max(prev_end, o_end)
            elif o_start >= original_end:
                next_start = o_start if next_start is None else min(next_start, o_start)
        return prev_end, next_start

    def _trim_drag(self, event):
        """Trim one edge. Video/audio stay inside their real media length;
        images can be stretched freely. Edges snap to frames, the playhead and
        neighbouring clip edges."""
        from app.timeline_trim_math import drag_trim, pointer_delta_frames

        tl = self.timeline
        fps = tl.FPS
        if not getattr(self, "_trim_history_pushed", False):
            self._trim_history_pushed = True
            tl._push_history()

        ppf = max(0.001, float(getattr(
            self, "_trim_pixels_per_frame", tl.pixels_per_frame
        )))
        # Use global pointer coordinates. During a left-edge trim the clip
        # widget itself moves as its start time changes; local event.position()
        # therefore shifts with the widget and feeds back into the delta,
        # causing runaway/incorrect trimming. The global press position remains
        # stable regardless of the widget's changing geometry.
        current_global_x = float(event.globalPosition().x())
        delta = pointer_delta_frames(
            self._drag_start_global.x(), current_global_x, ppf
        )

        start0 = self.original_start_frame
        end0 = start0 + self.original_duration_frames
        is_image = self._is_freely_stretchable()
        source_len = None
        if not is_image:
            # Source length is resolved from the clip's original source range,
            # not from its shortened timeline duration. See the press-time
            # metadata resolution above for legacy projects.
            source_len = getattr(self, "_trim_source_len_frames", None)
            if source_len is None:
                raw_source_duration = self.clip.get("source_duration")
                try:
                    raw_source_duration = float(raw_source_duration)
                except (TypeError, ValueError):
                    raw_source_duration = 0.0
                raw_source_frames = (
                    tl.frame_from_seconds(raw_source_duration)
                    if raw_source_duration > 0.0
                    else None
                )
                source_in_for_bound = tl.frame_from_seconds(
                    self.clip.get("source_in", 0.0)
                )
                from app.timeline_trim_math import resolve_source_length_frames
                trim_speed = max(0.1, min(8.0, float(self.clip.get("speed", 1.0))))
                source_len = resolve_source_length_frames(
                    raw_source_frames, source_in_for_bound, int(round(self.original_duration_frames * trim_speed))
                )

        source_in = int(getattr(
            self, "_trim_original_source_in_frames",
            tl.frame_from_seconds(self.clip.get("source_in", 0.0)),
        ))

        prev_end, next_start = self._trim_neighbours(start0, end0)

        # Snap the edge being dragged (not the fixed one).
        edge0 = start0 if self.mode == "trim_left" else end0
        snapped = tl.snap_time((edge0 + delta) / fps, exclude=self.clip)
        delta = tl.frame_from_seconds(snapped) - edge0

        trim_speed = max(0.1, min(8.0, float(self.clip.get("speed", 1.0))))
        new_start, new_dur, new_in = drag_trim(
            self.mode, start0, self.original_duration_frames, source_in,
            source_len, delta, prev_end=prev_end, next_start=next_start, speed=trim_speed,
        )
        # Do not pin the MAIN CLIP's left edge to timeline frame zero. The
        # main TRACK stays in its fixed lane, but trimming its left edge must
        # still move the clip start right while preserving its original end.
        # Pinning new_start here without adjusting duration/source_in corrupted
        # the source-to-project mapping and made trimmed footage preview wrong.
        old_clip_start_seconds = start0 / fps
        self.clip["start"] = new_start / fps
        self.clip["duration"] = new_dur / fps
        try:
            from app.animation import trim_keyframes
            trim_keyframes(self.clip, old_clip_start_seconds, self.clip["start"], self.clip["duration"], fps=fps)
        except Exception:
            pass
        if not is_image:
            self.clip["source_in"] = new_in / fps
            if self.clip.get("speed_mode") == "curve" and self.clip.get("speed_curve"):
                try:
                    from app.animation import integrate_speed_curve
                    self.clip["speed_source_duration"] = integrate_speed_curve(self.clip["speed_curve"], self.clip["duration"], self.clip.get("speed", 1.0))
                except Exception:
                    self.clip["speed_source_duration"] = self.clip["duration"] * trim_speed
            else:
                self.clip["speed_source_duration"] = self.clip["duration"] * trim_speed


    def mouseReleaseEvent(self, event):
        if not self.dragging:
            event.accept()
            return

        self.dragging = False
        self._set_hover_cursor(float(event.position().x()))
        committed = False

        if self.mode == "move" and self._move_started:
            gp = event.globalPosition().toPoint()
            gap = self.timeline._layer_gap_at_global_pos(gp)
            if gap is not None:
                delta_x = float(gp.x() - self._drag_start_global.x())
                requested_frame = self.original_start_frame + int(round(
                    delta_x / max(0.001, self.timeline.pixels_per_frame)
                ))
                committed = self.timeline.move_clip_to_new_layer(
                    self.clip, gap, max(0, requested_frame)
                )

            # Horizontal position follows the exact timeline scale from the
            # original frame. This completely decouples sideways movement from
            # the layer-selection calculation.
            if not committed:
                delta_x = (
                    float(gp.x())
                    - float(self._drag_start_global.x())
                )
                requested_frame = (
                    self.original_start_frame
                    + int(round(delta_x / max(0.001, self.timeline.pixels_per_frame)))
                )
                requested_start = max(0.0, requested_frame / float(self.timeline.FPS))

                delta_y = (
                    float(gp.y())
                    - float(self._drag_start_global.y())
                )
                target = self._target_track_from_pointer(
                    gp,
                    vertical_delta=delta_y,
                )
                if target is None:
                    target = self.track

                # Resolve drops over another clip to an exact clip boundary.
                # The left half inserts before; the right half inserts after.
                # The same resolver drives the live preview and final commit,
                # so the preview cannot promise one position and commit another.
                requested_frame, hit_existing = self.timeline._resolve_clip_drop_frame(
                    target, gp, requested_frame, exclude_clip=self.clip
                )
                requested_start = requested_frame / float(self.timeline.FPS)

                committed = self.timeline.move_clip_object(
                    self.clip, target, requested_start,
                    force_insert=hit_existing,
                )

        elif self.mode in ("trim_left", "trim_right"):
            self.timeline.rebuild(keep_view=True)
            # Trimming changes the authoritative project snapshot (timeline
            # start, source in-point and/or duration). A time_changed signal
            # alone does not publish that edit to ProjectPreviewController, so
            # the old composite could remain on the player. Push the edited
            # active stack now; the controller fingerprints the project and
            # refreshes the paused frame / playback composite.
            self.timeline._emit_active_clips(
                self.timeline.playhead, push_to_player=True
            )
            self.timeline.time_changed.emit(self.timeline.playhead)
            self.changed.emit()
            committed = True

        if self._move_ghost is not None:
            self._move_ghost.deleteLater()
            self._move_ghost = None

        self.timeline._clear_clip_drag_preview()
        self.mode = "move"
        self._trim_source_len_frames = None
        self._trim_pixels_per_frame = max(
            0.001, float(self.timeline.pixels_per_frame)
        )
        self._trim_original_source_in_frames = self.timeline.frame_from_seconds(
            self.clip.get("source_in", 0.0)
        )

        if not committed:
            self.show()
            self._sync_geometry()

        event.accept()

    def leaveEvent(self, event):
        if not self.dragging:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().leaveEvent(event)

    def enterEvent(self, event):
        if not self.dragging:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().enterEvent(event)

    # ---------- drawing ----------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect()
        selected = self.timeline.selected_clip is self.clip
        radius = 6

        # Base clip surface.
        painter.setBrush(QColor(self.color))
        painter.setPen(QPen(
            QColor(COLORS["selection"] if selected else "#0A1016"),
            2 if selected else 1,
        ))
        painter.drawRoundedRect(
            QRectF(
                0.5,
                0.5,
                max(1.0, rect.width() - 1.0),
                max(1.0, rect.height() - 1.0),
            ),
            radius,
            radius,
        )

        # Media image strip.
        content_rect = QRectF(
            1,
            13,
            max(1, rect.width() - 2),
            max(1, rect.height() - 14),
        )

        if self.thumbnail and not self.thumbnail.isNull():
            tile_w = max(90, min(180, int(content_rect.height() * 1.78)))
            scaled = self.thumbnail.scaled(
                tile_w,
                int(content_rect.height()),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )

            painter.save()
            painter.setClipRect(content_rect)
            x = content_rect.left()
            while x < content_rect.right():
                painter.drawPixmap(
                    int(x),
                    int(content_rect.top()),
                    scaled
                )
                x += max(1, scaled.width())
            painter.restore()

            painter.fillRect(
                content_rect,
                QColor(0, 0, 0, 38)
            )

        elif str(self.clip.get("kind", "")).strip().casefold() == "audio":
            try:
                wave = audio_waveform_pixmap(
                    self.clip_path(),
                    int(max(2, content_rect.width())),
                    int(max(2, content_rect.height())),
                )
                if not wave.isNull():
                    painter.save()
                    painter.setClipRect(content_rect)
                    x = int(content_rect.left())
                    right = int(content_rect.right())
                    y = int(content_rect.top())
                    while x < right:
                        painter.drawPixmap(x, y, wave)
                        x += max(1, wave.width())
                    painter.restore()
            except Exception as exc:
                # Painting must remain resilient if a media path or pixmap is
                # malformed. Record it for diagnosis and retain the audio clip.
                try:
                    self.timeline._log_drop_failure("audio waveform paint", exc)
                except Exception:
                    pass

        # Put clip metadata directly on the clip surface (not in a separate
        # strip above the thumbnail). 60%-opacity text keeps the media visible.
        top_h = min(16, rect.height())
        if rect.width() >= 70:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(7, 10, 15, 155))
            painter.drawRect(QRectF(1, 1, max(1, rect.width() - 2), top_h))
        if rect.width() >= 100:
            font = QFont("Segoe UI")
            font.setPointSize(8)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(QPen(QColor(244, 248, 252, 153)))

            tool_type = str(self.clip.get("tool_type", ""))
            glyph = {"Video": "▶ ", "Image": "▣ ", "Audio": "♪ "}.get(self.clip.get("kind"), "")
            if tool_type:
                glyph = {"Text": "T  ", "Effects": "✦  ", "Filters": "◈  ", "Adjustments": "◐  "}.get(tool_type, "")
            name = glyph + str(self.clip.get("display_name") or self.clip.get("text") or Path(self.clip_path()).stem or "Media")
            name_rect = QRectF(7, 1, max(10, rect.width() - 14), top_h - 1)
            # Elide long filenames instead of letting Qt clip them at the
            # clip edge. The full filename remains available in the tooltip.
            name = QFontMetrics(font).elidedText(
                name, Qt.TextElideMode.ElideRight, int(name_rect.width())
            )
            painter.drawText(
                name_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                name,
            )

            # Very narrow clips are too small for both a label and duration.
            # Keep the duration on wider clips only to avoid visual collisions.
            if rect.width() >= 135:
                painter.setPen(QPen(QColor(231, 238, 244, 153)))
                painter.drawText(
                    QRectF(
                        7,
                        top_h + 1,
                        max(10, rect.width() - 14),
                        max(8, rect.height() - top_h - 2),
                    ),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    timecode(self.clip["duration"], self.timeline.FPS),
                )

        # Keyframe diamonds are shown only for the selected clip and the one
        # property currently selected in the Inspector. They are drawn on the
        # clip itself and are recalculated from clip-local frame times.
        if selected:
            prop = getattr(self.timeline, "_keyframe_display_property", None)
            points = (self.clip.get("keyframes", {}) or {}).get(prop, []) if prop else []
            if points and rect.width() >= 8 and rect.height() >= 12:
                try:
                    from app.animation import normalize_keyframes
                    keys = normalize_keyframes(points)
                    duration = max(1.0 / max(1, int(self.timeline.FPS)), float(self.clip.get("duration", 0.0)))
                    painter.save()
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                    painter.setPen(QPen(QColor("#071419"), 1))
                    painter.setBrush(QColor("#00D9E8"))
                    cy = max(8.0, float(rect.height()) - 7.0)
                    for key in keys:
                        x = max(4.0, min(float(rect.width()) - 4.0, float(key["time"]) / duration * float(rect.width())))
                        painter.save()
                        painter.translate(x, cy)
                        painter.rotate(45)
                        painter.drawRect(QRectF(-3.5, -3.5, 7.0, 7.0))
                        painter.restore()
                    painter.restore()
                except (TypeError, ValueError, RuntimeError, AttributeError):
                    pass

        painter.end()

    def contextMenuEvent(self, event):
        self.timeline.select_clip(self.clip, self)

        menu = QMenu(self)
        copy_action = menu.addAction("Copy")
        cut_action = menu.addAction("Cut")
        duplicate_action = menu.addAction("Duplicate")
        menu.addSeparator()
        split_action = menu.addAction("Split at Playhead")
        delete_action = menu.addAction("Delete Clip")
        trim_menu = menu.addMenu("Trim")
        trim_left_action = trim_menu.addAction("Trim Left to Playhead")
        trim_right_action = trim_menu.addAction("Trim Right to Playhead")
        menu.addSeparator()
        open_location = menu.addAction("Open File Location")

        action = menu.exec(event.globalPos())
        if action is None:
            return

        if action == copy_action:
            self.timeline.copy_selected()
        elif action == cut_action:
            self.timeline.cut_selected()
        elif action == duplicate_action:
            self.timeline.duplicate_selected()
        elif action == split_action:
            self.timeline.split_selected()
        elif action == delete_action:
            self.timeline.delete_selected()
        elif action == trim_left_action:
            self.timeline.trim_selected_left()
        elif action == trim_right_action:
            self.timeline.trim_selected_right()
        elif action == open_location:
            self.timeline.open_selected_file_location()

        event.accept()

    def clip_path(self) -> str:
        return str(self.clip.get("path", ""))


# ============================================================
# Track body
# ============================================================

class TrackArea(QFrame):
    dropped = Signal(str, str, float)

    @staticmethod
    def _tool_from_mime(mime):
        if not mime.hasFormat("application/x-skyzen-tool-asset"):
            return None
        try:
            import json
            raw = bytes(mime.data("application/x-skyzen-tool-asset")).decode("utf-8", errors="replace")
            payload = json.loads(raw)
            tool_type = str(payload.get("tool_type", ""))
            preset_id = str(payload.get("preset_id", ""))
            if tool_type in ("Text", "Effects", "Filters", "Adjustments") and preset_id:
                return tool_type, preset_id
        except Exception:
            return None
        return None

    @staticmethod
    def _media_from_mime(mime):
        if mime.hasFormat("application/x-skyzen-media"):
            try:
                raw = bytes(mime.data("application/x-skyzen-media")).decode("utf-8", errors="replace")
                kind, path = raw.split("|", 1)
                return kind, path
            except Exception:
                return None, None
        for url in mime.urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                return detect_kind(Path(path)), path
        return None, None

    def __init__(self, track: dict, timeline: "TimelinePanel", row_index: int, parent=None):
        super().__init__(parent)
        self.track = track
        self.timeline = timeline
        self.row_index = row_index

        self.setAcceptDrops(True)
        self._drop_preview_kind = None
        self._drop_preview_path = None
        from .track_layout import row_height
        self.setFixedHeight(row_height(timeline, track))
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.setMouseTracking(True)

    def dragEnterEvent(self, event):
        tool = self._tool_from_mime(event.mimeData())
        if tool and self.track.get("base") == "V":
            event.acceptProposedAction()
            return
        kind, path = self._media_from_mime(event.mimeData())
        if kind and path and not self.track.get("track_type") and self.track.get("base") == self.timeline._track_base_for_kind(kind):
            self._drop_preview_kind, self._drop_preview_path = kind, path
            self.timeline._update_external_drop_preview(
                path, kind, self.track,
                self.timeline.frame_from_seconds(self.timeline.x_to_time(event.position().x())),
            )
            event.acceptProposedAction()
        else:
            self.timeline._clear_clip_drag_preview()
            event.ignore()

    def dragMoveEvent(self, event):
        tool = self._tool_from_mime(event.mimeData())
        if tool and self.track.get("base") == "V":
            event.acceptProposedAction()
            return
        kind, path = self._media_from_mime(event.mimeData())
        if kind and path and not self.track.get("track_type") and self.track.get("base") == self.timeline._track_base_for_kind(kind):
            self._drop_preview_kind, self._drop_preview_path = kind, path
            self.timeline._update_external_drop_preview(
                path, kind, self.track,
                self.timeline.frame_from_seconds(self.timeline.x_to_time(event.position().x())),
            )
            event.acceptProposedAction()
        else:
            self.timeline._clear_clip_drag_preview()
            event.ignore()

    def dragLeaveEvent(self, event):
        self.timeline._clear_clip_drag_preview()
        self._drop_preview_kind = None
        self._drop_preview_path = None
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.timeline._clear_clip_drag_preview()
        start = self.timeline.x_to_time(event.position().x())
        tool = self._tool_from_mime(event.mimeData())
        if tool:
            if self.track.get("base") == "V":
                # Typed tools are always inserted into their own overlay lane;
                # dropping over Main uses its position only as a placement reference.
                self.timeline.add_tool_asset_at_time(tool[0], tool[1], start, self.track)
                event.acceptProposedAction()
            else:
                event.ignore()
            return

        if event.mimeData().hasFormat(
            "application/x-skyzen-media"
        ):
            if self.track.get("track_type"):
                event.ignore()
                return
            raw = bytes(
                event.mimeData().data(
                    "application/x-skyzen-media"
                )
            ).decode(
                "utf-8",
                errors="replace",
            )
            try:
                kind, path = raw.split(
                    "|",
                    1,
                )
            except ValueError:
                event.ignore()
                return

            self.timeline.add_to_existing_track(
                path,
                kind,
                start,
                self.track,
            )
            event.acceptProposedAction()
            return

        if self.track.get("track_type"):
            event.ignore()
            return
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                self.timeline.add_to_existing_track(
                    path,
                    detect_kind(Path(path)),
                    start,
                    self.track,
                )
                event.acceptProposedAction()
                return

        event.ignore()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.timeline.select_clip(None)
            self.timeline.set_playhead(
                self.timeline.x_to_time(event.position().x()),
                ensure_visible=False,
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        if self.timeline._scroll_timeline_wheel(event):
            return
        event.ignore()

    def contextMenuEvent(self, event):
        self.timeline.show_track_context_menu(
            self.track,
            event.globalPos(),
        )
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.track.get("is_main", False):
            background = "#262626"
        elif self.track.get("base") == "E":
            background = "#1A1A1C"
        else:
            background = COLORS["track_alt"] if self.row_index % 2 else COLORS["track"]
        painter.fillRect(self.rect(), QColor(background))

        painter.setPen(QPen(QColor("#2A2E34"), 1))
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1,)
        if self.track.get("is_main", False):
            painter.setPen(QPen(QColor("#4B5058"), 1))
            painter.drawLine(0, 0, self.width(), 0)
        painter.end()


# ============================================================
# Layer header
# ============================================================



# ============================================================
# Timeline panel
# ============================================================

from .left_layers_panel.layers import (
    LayerHeader,
    LayerAddDropButton,
    LayerInsertionGap,
    TopLayerDropArea,
    TimelineSectionRow,
    EffectDropRow,
    TimelineContent,
    LayerEditGutterContent,
    LayerSidebarContent,
)
from .timebar.timebar import TimeRuler


class TimelinePanel(QFrame):
    """
    One project-wide frame axis.

    Axis:
        frame 0 -> frame 1 -> frame 2 -> ... -> frame N

    No clip owns the timeline scale.
    A clip's width is simply:
        x(end_frame) - x(start_frame)

    Zoom changes pixels-per-frame only.
    """

    clip_selected = Signal(str, float, float, str)
    time_changed = Signal(float)
    project_time_changed = Signal(float)
    active_clips_changed = Signal(object)
    selection_cleared = Signal()
    project_preview_requested = Signal()

    HEADER_WIDTH = 138
    EDIT_GUTTER_WIDTH = 0
    LAYER_COLUMN_GAP = 0
    TRACK_HEIGHT = 50
    # The pinned base/main video lane is visibly larger like CapCut; overlays
    # retain TRACK_HEIGHT. Shared row geometry keeps every synced column aligned.
    MAIN_TRACK_HEIGHT = 66
    RULER_HEIGHT = 28
    CLIP_TOP_MARGIN = 3
    # Keep clip cards fully inside their 50 px lane, with equal 3 px top/bottom inset.
    CLIP_HEIGHT = TRACK_HEIGHT - (2 * CLIP_TOP_MARGIN)
    # Symmetric empty working zones around the visible track stack. The top
    # and bottom are kept equal and are represented in the same shared row
    # geometry for the canvas, label column and edit gutter.
    TOP_LAYER_DROP_HEIGHT = 2 * TRACK_HEIGHT + 12
    STACK_BOTTOM_MARGIN = 0
    NEW_LAYER_GAP_HEIGHT = 2 * TRACK_HEIGHT + 12
    MAIN_STICKY_GAP_HEIGHT = 0
    # A small, visible insertion zone between every pair of layers.  It is
    # deliberately not a real track: it is only a drop target for creating a
    # new layer at a precise stack position.
    LAYER_INSERT_GAP_HEIGHT = 3
    LAYER_INSERT_HOLD_MS = 150
    SECTION_HEADER_HEIGHT = 22
    EFFECT_DROP_HEIGHT = 42
    # Extra bottom range compensates for the timeline QScrollArea horizontal
    # scrollbar so hidden side columns share the exact same vertical range.
    LAYER_SCROLL_COMPENSATION_PX = 12
    FPS = 30

    MIN_CLIP_SECONDS = 1.0 / FPS

    DEFAULT_VISIBLE_SECONDS = 30.0
    MIN_VISIBLE_SECONDS = 1.0
    MIN_PROJECT_VIEW_SECONDS = 30.0
    MAX_VIEW_MULTIPLIER = 2.25

    ZOOM_MIN_VALUE = 0
    ZOOM_CENTER_VALUE = 5000
    ZOOM_MAX_VALUE = 10000

    # Magnetic edge snapping for moved media.
    SNAP_DISTANCE_PX = 14

    def __init__(self, root_dir: Path, parent=None, thumbnail_service=None):
        super().__init__(parent)

        self.root_dir = Path(root_dir).resolve()
        self.setObjectName("TimelinePanel")
        self.setMinimumHeight(180)

        self.tracks: list[dict] = []
        self.playhead = 0.0
        self.selected_clip: dict | None = None
        # Inspector-selected property whose keyframe diamonds are currently visible.
        self._keyframe_display_property = None
        self.snap_adjacent_enabled = True
        # UI visibility is separate from track.hidden: hiding an overlay here
        # only declutters the timeline; it NEVER stops that overlay from
        # participating in project playback/compositing.
        self.overlays_ui_visible = True
        self.effects_ui_visible = False
        self.audio_ui_visible = True

        # Concat-style timeline view state.  These are UI preferences only;
        # Skyzen's existing edit model remains the source of truth.
        self._concat_tool = "select"
        self._concat_magnetic = False
        self._concat_trim_follow = False
        self._concat_preview_axis = False
        self._concat_pan_mode = False
        self._concat_current_tab = 0

        # Independent frame-preview marker. It never starts playback and
        # never changes the real project playhead.
        self.preview_time = None
        self._preview_dragging = False

        # Renderer selection is a timeline/project preference only. The
        # timeline never requires a GPU; the future player/rendering engine may
        # honor this preference and fall back to CPU automatically.
        self.render_backend = "cpu"
        self.available_render_backends = ("cpu", "gpu")

        self.pixels_per_frame = 0.0
        self.pixels_per_second = 0.0
        # User-configurable wheel sensitivity; the main window loads/saves these.
        self.zoom_wheel_step = 150
        self.horizontal_pan_multiplier = 7
        self.vertical_scroll_multiplier = 1.0

        self._initial_scale_pending = True
        self._ready = False

        self._history: list[list[dict]] = []
        self._future: list[list[dict]] = []
        self._history_restoring = False

        self._thumbnail_cache: dict[str, QPixmap] = {}
        self.thumbnail_service = thumbnail_service or ThumbnailService(self.root_dir, self)
        self.thumbnail_service.thumbnail_ready.connect(self._on_shared_thumbnail_ready)
        self._clipboard_clip = None
        self._attribute_clipboard = None
        self._clip_drag_preview_widgets = []
        self._external_preview_cache = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---------------------------------------------------------
        # Concat-style tool tray.
        # The old Core / Timeline 3 strip was decorative in Skyzen and
        # consumed 32 px of vertical editor space. The toolbar now starts
        # immediately below the editor.
        # Timeline toolbar lives in toolbar/toolbar.py so the UI can be refined
        # independently without touching the timeline engine.
        from .toolbar.toolbar import build_toolbar
        toolbar = build_toolbar(self)
        toolbar.setObjectName("SkyzenTimelineToolbar")
        toolbar.setStyleSheet(
            "QFrame#SkyzenTimelineToolbar{background:#212123;border-bottom:1px solid #2A2E34;}"
        )
        root.addWidget(toolbar)


        # ---------------------------------------------------------
        # Main body
        # ---------------------------------------------------------
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        root.addLayout(body, 1)

        sidebar = QFrame()
        sidebar.setFixedWidth(self.HEADER_WIDTH)
        sidebar.setStyleSheet(
            f"""
            QFrame {{
                background:{COLORS['header']};
                border-right:1px solid #2A2E34;
            }}
            """
        )

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        sidebar_top = QFrame()
        sidebar_top.setFixedHeight(self.RULER_HEIGHT)
        sidebar_top.setStyleSheet(
            f"""
            QFrame {{
                background:{COLORS['header']};
                border-bottom:1px solid #2A2E34;
            }}
            """
        )

        top_layout = QHBoxLayout(sidebar_top)
        top_layout.setContentsMargins(8, 0, 7, 0)
        top_layout.setSpacing(4)

        title = QLabel("Layers")
        title.setStyleSheet(
            f"color:{COLORS['muted']}; font-size:9px; font-weight:700;"
        )
        top_layout.addWidget(title)

        # Track visibility is a workspace view preference, independent from
        # whether a track participates in playback or export.
        self.layer_view_combo = QComboBox()
        self.layer_view_combo.addItems(["Both", "Overlays", "Audio"])
        self.layer_view_combo.setCurrentText("Both")
        self.layer_view_combo.setToolTip(
            "Choose which timeline lanes are visible. Hidden lanes still play and export."
        )
        self.layer_view_combo.setFixedWidth(66)
        self.layer_view_combo.setFixedHeight(22)
        self.layer_view_combo.setStyleSheet(
            "QComboBox{background:#20252B;color:#DCE4EC;border:1px solid #3A424C;"
            "border-radius:4px;padding:2px 5px;font-size:10px;}"
            "QComboBox:hover{border-color:#00CFE8;}"
            "QComboBox QAbstractItemView{background:#20252B;color:#DCE4EC;"
            "selection-background-color:#075B68;}"
        )
        self.layer_view_combo.currentTextChanged.connect(self._set_layer_view_mode)
        top_layout.addWidget(self.layer_view_combo)
        top_layout.addStretch()

        hint = QLabel("✎")
        hint.setStyleSheet(
            f"color:{COLORS['muted']}; font-size:11px;"
        )
        top_layout.addWidget(hint)

        sidebar_layout.addWidget(sidebar_top)

        self.sidebar_scroll = SyncedColumn()
        self.sidebar_scroll.setStyleSheet("background:transparent; border:0;")

        self.sidebar_content = LayerSidebarContent(
            self
        )
        self.sidebar_scroll.setWidget(
            self.sidebar_content
        )
        sidebar_layout.addWidget(
            self.sidebar_scroll,
            1,
        )

        body.addWidget(sidebar)

        # ---------------------------------------------------------
        # Dedicated layer-edit gutter (CapCut-style separator).
        # The pencil controls live between the media/layer panel and
        # the timeline canvas instead of consuming row width.
        # ---------------------------------------------------------
        edit_gutter = QFrame()
        edit_gutter.setFixedWidth(self.EDIT_GUTTER_WIDTH)
        edit_gutter.setStyleSheet(
            f"""
            QFrame {{
                background:#232323;
                border-left:1px solid #0F131A;
                border-right:2px solid #252C35;
            }}
            """
        )

        edit_gutter_layout = QVBoxLayout(edit_gutter)
        edit_gutter_layout.setContentsMargins(0, 0, 0, 0)
        edit_gutter_layout.setSpacing(0)

        edit_top = QFrame()
        edit_top.setFixedHeight(self.RULER_HEIGHT)
        edit_top.setStyleSheet(
            f"""
            QFrame {{
                background:{COLORS['background']};
                border-bottom:1px solid #2A2E34;
            }}
            """
        )

        edit_top_layout = QHBoxLayout(edit_top)
        edit_top_layout.setContentsMargins(2, 2, 2, 2)
        edit_top_layout.setSpacing(0)

        self.edit_layer_button = LayerAddDropButton(self)
        self.edit_layer_button.setText("+")
        self.edit_layer_button.setToolTip(
            "Edit Layer — click to rename selected layer; drop media here to create a new layer"
        )
        self.edit_layer_button.setAutoRaise(True)
        self.edit_layer_button.setFixedSize(24, 28)
        self.edit_layer_button.setStyleSheet(
            f"""
            QToolButton {{
                color:{COLORS['muted']};
                background:transparent;
                border:1px solid transparent;
                border-radius:4px;
                font-size:15px;
                padding:0;
            }}
            QToolButton:hover {{
                color:{COLORS['text']};
                background:#2A2A2A;
                border-color:#3A3A3A;
            }}
            """
        )
        self.edit_layer_button.clicked.connect(
            self.edit_selected_layer
        )
        edit_top_layout.addWidget(
            self.edit_layer_button
        )
        edit_top_layout.addStretch()

        edit_gutter_layout.addWidget(edit_top)

        self.edit_gutter_scroll = SyncedColumn()
        self.edit_gutter_scroll.setStyleSheet("background:transparent; border:0;")

        self.edit_gutter_content = LayerEditGutterContent(
            self
        )
        self.edit_gutter_scroll.setWidget(
            self.edit_gutter_content
        )
        edit_gutter_layout.addWidget(
            self.edit_gutter_scroll,
            1,
        )

        body.addWidget(edit_gutter)
        body.addSpacing(self.LAYER_COLUMN_GAP)

        editor = QFrame()
        editor.setStyleSheet(
            "QFrame{background:#232323; border:0;}"
        )
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)

        self.ruler_viewport = QWidget()
        self.ruler_viewport.setFixedHeight(
            self.RULER_HEIGHT
        )
        self.ruler_viewport.setStyleSheet(
            f"""
            QWidget {{
                background:{COLORS['ruler']};
                border-bottom:1px solid #2A2E34;
            }}
            """
        )
        self.ruler_viewport.setAttribute(
            Qt.WidgetAttribute.WA_OpaquePaintEvent,
            True,
        )
        self.ruler_viewport.setMouseTracking(True)

        editor_layout.addWidget(
            self.ruler_viewport
        )

        self.ruler = TimeRuler(
            self,
            self.ruler_viewport,
        )
        self.ruler.show()

        self.tracks_scroll = QScrollArea()
        self.tracks_scroll.setWidgetResizable(False)
        self.tracks_scroll.setFrameShape(
            QFrame.Shape.NoFrame
        )
        self.tracks_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self.tracks_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.tracks_scroll.setStyleSheet(
            """
            QScrollArea {
                background:#232323;
                border:0;
            }
            QScrollBar:horizontal {
                height:10px;
                background:#252525;
                border:0;
            }
            QScrollBar::handle:horizontal {
                background:#3A3A3A;
                border-radius:5px;
                min-width:36px;
            }
            QScrollBar::handle:horizontal:hover {
                background:#555555;
            }
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal {
                width:0;
            }
            QScrollBar:vertical {
                width:9px;
                background:#252525;
                border:0;
            }
            QScrollBar::handle:vertical {
                background:#3A3A3A;
                border-radius:4px;
                min-height:30px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height:0;
            }
            """
        )

        self.content = TimelineContent(
            self
        )
        self.tracks_scroll.setWidget(
            self.content
        )

        editor_layout.addWidget(
            self.tracks_scroll,
            1,
        )

        body.addWidget(editor, 1)

        # Compatibility alias.
        self.scroll = self.tracks_scroll

        # Marker heads are isolated in marker/marker.py.
        from .marker.marker import create_marker_heads
        create_marker_heads(self)


        self.tracks_scroll.horizontalScrollBar().valueChanged.connect(
            self._on_horizontal_scroll
        )

        self._bound_media_player = None
        self._auto_bind_player_pending = True
        self._layer_scroll_syncing = False
        self._scroll_coordinator = TimelineScrollCoordinator(self)
        self._active_player_clip_key = None
        self._multitrack_engine = None
        self._active_stack_signature = None
        self._last_set_playhead_frame = None
        self._playhead_update_guard = False

        # Timeline owns timing/stack state. PlayerPanel owns actual decoding and
        # compositing. This avoids duplicating decoder work inside the timeline
        # while still publishing every active layer together.
        self.ENABLE_EMBEDDED_MULTITRACK = False

        # Source/project playback bridge state.
        self._player_source_clip_key = None
        self._player_project_anchor = 0.0
        self._player_source_in = 0.0
        self._player_switch_generation = 0
        self._switching_player = False

        # SOURCE -> PROJECT clock bridge for the existing QMediaPlayer.
        # The player reports source-local milliseconds; the timeline owns
        # one project-wide 30-FPS clock.
        self._player_clock_clip_key = None
        self._player_clock_anchor = None
        self._player_clock_source_in = 0.0
        self._player_clock_last_position_ms = None
        self._player_clock_playing = False

        # Skyzen always has one structural base video layer. It is the bottom
        # lane, anchored to project frame 0. Overlay layers are created above it.
        self._ensure_main_video_track()

        self.rebuild()
        QTimer.singleShot(
            0,
            self._apply_initial_scale,
        )
        QTimer.singleShot(
            0,
            self._auto_bind_player,
        )
        QTimer.singleShot(
            0,
            self._align_layer_scroll_ranges,
        )

    # ========================================================
    # Display-track ordering
    # ========================================================

    def _normalise_track_stack(self):
        """Repair/normalise track roles without changing clip timing."""
        videos = [t for t in self.tracks if t.get("base") == "V"]
        audios = [t for t in self.tracks if t.get("base") == "A"]
        effects = [t for t in self.tracks if t.get("base") == "E"]

        if not videos:
            videos = [self._ensure_main_video_track()]

        def num(track):
            try:
                return int(str(track.get("name", ""))[1:])
            except Exception:
                return 0

        mains = [t for t in videos if t.get("is_main", False)]
        if mains:
            main = min(mains, key=num)
        else:
            v1 = [t for t in videos if str(t.get("name", "")).upper() == "V1"]
            main = v1[0] if v1 else min(
                videos,
                key=lambda t: (float(t.get("_stack_order", 999999.0)), num(t)),
            )

        for t in videos:
            t["is_main"] = (t is main)
            t.setdefault("locked", False)
            t.setdefault("hidden", False)
            t.setdefault("muted", False)
            t.setdefault("volume", 1.0)
            t.setdefault("clips", [])

        overlays = [t for t in videos if t is not main]
        for i, t in enumerate(overlays):
            if "_stack_order" not in t:
                t["_stack_order"] = float(i - len(overlays))
        overlays.sort(key=lambda t: (float(t.get("_stack_order", 0.0)), num(t)))

        # Lower order = visually higher overlay. Main is always the lowest
        # video lane and never changes role when more overlays are added.
        if overlays:
            main["_stack_order"] = max(float(t.get("_stack_order", 0.0)) for t in overlays) + 1.0
        else:
            main["_stack_order"] = 0.0

        for group in (effects, audios):
            for i, track in enumerate(group):
                track.setdefault("_stack_order", float(i))
                track.setdefault("locked", False)
                track.setdefault("hidden", False)
                track.setdefault("muted", False)
                track.setdefault("volume", 1.0)
                track.setdefault("clips", [])

        effects.sort(key=lambda t: (float(t.get("_stack_order", 0.0)), num(t)))
        audios.sort(key=lambda t: (float(t.get("_stack_order", 0.0)), num(t)))
        return overlays, main, effects, audios

    def playback_tracks(self) -> list[dict]:
        """All project tracks used by playback, independent of UI visibility."""
        overlays, main, effects, audios = self._normalise_track_stack()
        # Effects are not media decoders yet; they are reserved for the
        # rendering/effect engine. They intentionally do not become fake video.
        return overlays + [main] + audios

    def display_tracks(self) -> list[dict]:
        """Tracks visible in the timeline UI, with clean overlay/effect sections."""
        overlays, main, effects, audios = self._normalise_track_stack()
        visible = []
        if self.overlays_ui_visible:
            visible.extend(overlays)
        visible.append(main)
        if self.effects_ui_visible:
            visible.extend(effects)
        if self.audio_ui_visible:
            visible.extend(audios)
        return visible

    def timeline_ui_rows(self) -> list[tuple]:
        """Return the minimal shared row list used by all timeline columns.

        Empty overlay tracks are not shown: a dropped clip creates/populates its
        own track, so empty persisted rows only make the timeline look broken.
        Section labels and decorative insertion gaps are intentionally omitted
        in this basic-editor stage. Track data itself is never deleted here.
        """
        overlays, main, effects, audios = self._normalise_track_stack()
        rows = []

        if self.overlays_ui_visible:
            visible_overlays = [track for track in overlays if track.get("clips")]
            # Narrow insertion targets sit before each overlay and between adjacent
            # overlays. The final gap permits insertion directly above Main.
            # A new lane is created only when a drop lands on one of these gaps.
            for track in visible_overlays:
                rows.append(("gap", None, "overlay"))
                rows.append(("track", track, "overlay"))
            if visible_overlays:
                rows.append(("gap", None, "overlay"))

        rows.append(("track", main, "main"))

        # Audio lanes are always immediately below Main. Dedicated 2–3 px
        # insertion gaps accept audio only, preventing music from being placed
        # into the overlay stack by mistake.
        if self.audio_ui_visible:
            visible_audios = [track for track in audios if track.get("clips")]
            for track in visible_audios:
                rows.append(("gap", None, "audio"))
                rows.append(("track", track, "audio"))
            # Keep a target available for the first/new audio lane even when
            # the project has no music tracks yet.
            rows.append(("gap", None, "audio"))

        if self.effects_ui_visible:
            rows.extend(
                ("track", track, "effect")
                for track in effects
                if track.get("clips")
            )

        return rows

    def _set_overlays_ui_visible(self, visible):
        self.overlays_ui_visible = bool(visible)
        self.rebuild(keep_view=True)

    def _set_effects_ui_visible(self, visible):
        self.effects_ui_visible = bool(visible)
        self.rebuild(keep_view=True)

    def _stack_rows_height(self) -> int:
        total = 0
        for kind, _v, _s in self.timeline_ui_rows():
            if kind == "track":
                from .track_layout import row_height
                total += row_height(self, _v)
            elif kind == "section":
                total += int(self.SECTION_HEADER_HEIGHT)
            elif kind == "effect_drop":
                total += int(self.EFFECT_DROP_HEIGHT)
            elif kind == "gap":
                total += int(self.LAYER_INSERT_GAP_HEIGHT)
        return total

    def _outer_layer_gap_height(self) -> int:
        """Return the same top/bottom workspace gap for every stack size.

        Short stacks expand symmetrically to fill the viewport. Taller stacks
        retain a fixed insertion workspace at both ends and scroll normally.
        """
        base = int(self.TOP_LAYER_DROP_HEIGHT)
        try:
            viewport_h = int(self.tracks_scroll.viewport().height())
        except Exception:
            viewport_h = 0
        rows_h = int(self._stack_rows_height())
        return symmetric_outer_gap(viewport_h, rows_h, base)

    def top_layer_drop_height(self) -> int:
        """Symmetric empty workspace above the topmost visible track."""
        return self._outer_layer_gap_height()

    def reanchor_if_needed(self):
        """Rebuild vertical columns when the viewport changed the top pad."""
        if getattr(self, "_initial_scale_pending", True):
            return
        if self.top_layer_drop_height() != getattr(self, "_built_top_pad", None):
            self.rebuild(keep_view=True)

    def bottom_new_layer_height(self) -> int:
        """Bottom workspace always mirrors the top workspace exactly."""
        return int(self._outer_layer_gap_height())

    def set_render_backend(self, backend: str):
        backend = str(backend or "cpu").lower()
        if backend not in ("cpu", "gpu"):
            backend = "cpu"
        self.render_backend = backend
        if hasattr(self, "render_button"):
            self.render_button.setText("GPU" if backend == "gpu" else "CPU")
        # Notify the player/rendering side without coupling the timeline to a
        # concrete compositor implementation.
        panel = getattr(self.window(), "player", None)
        setter = getattr(panel, "set_render_backend", None) if panel else None
        if callable(setter):
            try:
                setter(backend)
            except Exception:
                pass

    # ========================================================
    # Player synchronization
    # ========================================================

    def _auto_bind_player(self):
        if self._bound_media_player is not None:
            return

        window = self.window()
        panel = getattr(window, "player", None)

        if panel is None:
            if self._auto_bind_player_pending:
                QTimer.singleShot(
                    250,
                    self._auto_bind_player,
                )
            return

        candidates = [panel]
        for name in (
            "preview",
            "_preview",
            "video",
            "_video_panel",
        ):
            obj = getattr(panel, name, None)
            if obj is not None:
                candidates.append(obj)

        media = None

        for obj in candidates:
            for name in (
                "_player",
                "media_player",
                "_media_player",
                "player",
            ):
                candidate = getattr(
                    obj,
                    name,
                    None,
                )
                if (
                    candidate is not None
                    and hasattr(
                        candidate,
                        "positionChanged",
                    )
                    and hasattr(
                        candidate.positionChanged,
                        "connect",
                    )
                ):
                    media = candidate
                    break

            if media is not None:
                break

        if media is not None:
            try:
                media.positionChanged.connect(
                    self._on_media_player_position
                )
                if hasattr(media, "playbackStateChanged"):
                    media.playbackStateChanged.connect(
                        self._on_media_player_state_changed
                    )
                self._bound_media_player = media
                self._auto_bind_player_pending = False

                # The PlayerPanel creates its compositor lazily, only when a
                # real timeline video layer is sent. This keeps startup/source
                # preview independent from the experimental multi-layer surface.

                QTimer.singleShot(
                    0,
                    self.refresh_all_source_durations,
                )

                # Push the current frame immediately so a layer already sitting
                # under the playhead appears without waiting for a mouse event.
                QTimer.singleShot(
                    0,
                    lambda: self._emit_active_clips(self.playhead),
                )
                return
            except Exception:
                self._bound_media_player = None

        if self._auto_bind_player_pending:
            QTimer.singleShot(
                250,
                self._auto_bind_player,
            )

    def _player_is_source_preview(self) -> bool:
        """Return True when the player is previewing imported source media."""
        panel = getattr(self.window(), "player", None)
        if panel is None:
            return False

        # The FFmpeg preview backend's QMediaPlayer position is already project
        # time, not source-clip time. The ProjectPreviewController synchronizes
        # it directly; do not apply the legacy source-to-project clock mapping.
        if bool(getattr(panel, "timeline_mode", False)):
            return True

        candidates = [panel]
        for name in ("preview", "_preview", "video", "_video_panel"):
            obj = getattr(panel, name, None)
            if obj is not None:
                candidates.append(obj)

        for obj in candidates:
            try:
                mode = getattr(obj, "mode", None)
                if isinstance(mode, str) and mode.lower() == "source":
                    return True
            except Exception:
                pass

            try:
                if bool(getattr(obj, "source_preview_active", False)):
                    return True
            except Exception:
                pass

        return False

    @staticmethod
    def _clock_key(item):
        return (
            item.get("clip_id"),
            item.get("row"),
            item.get("start", 0.0),
            item.get("source_in", 0.0),
            str(item.get("path", "")),
        )

    def _prime_player_project_clock(self, seconds: float):
        """
        Establish SOURCE -> PROJECT mapping for the legacy single-source player.

        project_time = clip_start - source_in + source_time
        """
        try:
            active = self._active_timeline_layers(seconds)
        except Exception:
            active = []

        video_items = [
            item for item in active
            if item.get("base") == "V"
        ]

        if not video_items:
            self._player_clock_clip_key = None
            self._player_clock_anchor = None
            self._player_clock_source_in = 0.0
            return

        # The PlayerPanel compositor owns final rendering. The timeline only
        # supplies a stable project-clock reference when an old single-source
        # player is still present. Use the first deterministic video item so a
        # second/third overlay can never become an accidental playback master.
        item = video_items[0]
        key = self._clock_key(item)

        self._player_clock_clip_key = key
        self._player_clock_anchor = (
            float(item.get("start", 0.0))
            - float(item.get("source_in", 0.0))
        )
        self._player_clock_source_in = float(
            item.get("source_in", 0.0)
        )

    def _on_media_player_state_changed(self, state):
        """Track player play/pause without letting source stop reset the project."""
        if self._player_is_source_preview():
            self._player_clock_playing = False
            return

        media = self._bound_media_player
        if media is None:
            return

        try:
            playing_state = media.PlaybackState.PlayingState
            paused_state = media.PlaybackState.PausedState
        except Exception:
            return

        if state == playing_state:
            self._player_clock_playing = True
            self._prime_player_project_clock(self.playhead)
        elif state == paused_state:
            self._player_clock_playing = False
        else:
            # A source reaching its own end must not reset the project marker.
            self._player_clock_playing = False

    def _on_media_player_position(
        self,
        position_ms,
    ):
        """
        Convert the legacy player's SOURCE clock into the timeline's PROJECT clock.

        The previous implementation required _player_source_clip_key, but the
        current timeline-only path intentionally stopped maintaining that legacy
        field. That made positionChanged arrive successfully while the handler
        immediately returned, leaving the playhead frozen.
        """
        if self._player_is_source_preview():
            return

        try:
            milliseconds = float(position_ms)
        except (TypeError, ValueError):
            return

        self._player_clock_last_position_ms = milliseconds
        source_seconds = max(0.0, milliseconds / 1000.0)

        # Keep the anchor tied to whichever timeline clip is active at the
        # current project position.
        try:
            active = self._active_timeline_layers(self.playhead)
        except Exception:
            active = []

        video_items = [
            item for item in active
            if item.get("base") == "V"
        ]

        current_key = self._clock_key(video_items[-1]) if video_items else None

        if (
            self._player_clock_anchor is None
            or current_key != self._player_clock_clip_key
        ):
            self._prime_player_project_clock(self.playhead)

        anchor = self._player_clock_anchor
        if anchor is None:
            return

        project_time = float(anchor) + source_seconds

        project_end = self.project_end_seconds()
        if project_end > 0.0:
            project_time = min(project_time, project_end)

        self.set_playhead(
            project_time,
            emit=False,
            ensure_visible=True,
        )

    def set_playback_position(
        self,
        milliseconds: float,
    ):
        self._on_media_player_position(
            milliseconds
        )

    def set_playback_position(
        self,
        milliseconds: float,
    ):
        self._on_media_player_position(
            milliseconds
        )

    # ========================================================
    # Exact frame axis
    # ========================================================

    def frame_from_seconds(
        self,
        seconds: float,
        fps: int = 30,
    ) -> int:
        return max(
            0,
            int(
                round(
                    max(0.0, float(seconds))
                    * fps
                )
            ),
        )

    def snap_to_frame(
        self,
        seconds: float,
        fps: int = 30,
    ) -> float:
        return (
            self.frame_from_seconds(
                seconds,
                fps,
            )
            / fps
        )

    def frame_duration(
        self,
        clip: dict,
    ) -> int:
        return max(
            1,
            self.frame_from_seconds(
                clip.get("duration", 0.0),
                self.FPS,
            ),
        )

    def clip_start_frame(
        self,
        clip: dict,
    ) -> int:
        return self.frame_from_seconds(
            clip.get("start", 0.0),
            self.FPS,
        )

    def clip_end_frame(
        self,
        clip: dict,
    ) -> int:
        return (
            self.clip_start_frame(clip)
            + self.frame_duration(clip)
        )

    def time_to_x(
        self,
        seconds: float,
    ) -> int:
        frame = self.frame_from_seconds(
            seconds,
            self.FPS,
        )
        return int(
            round(
                frame
                * self.pixels_per_frame
            )
        )

    def x_to_time(
        self,
        x: float,
    ) -> float:
        frame = int(
            round(
                max(0.0, float(x))
                / max(
                    0.0001,
                    self.pixels_per_frame,
                )
            )
        )
        return frame / self.FPS

    def duration(self) -> float:
        end_frame = 0
        for track in self.tracks:
            for clip in track.get("clips", []):
                if clip.get("tool_type") == "Adjustments" and clip.get("scope") == "project":
                    continue
                end_frame = max(end_frame, self.clip_end_frame(clip))
        return end_frame / self.FPS

    def project_end_seconds(self) -> float:
        return self.duration()

    def project_last_frame(self) -> int:
        """Zero-based index of the final frame occupied by the project."""
        end_frame = 0
        for track in self.tracks:
            for clip in track.get("clips", []):
                end_frame = max(
                    end_frame,
                    self.clip_end_frame(clip),
                )
        return max(0, end_frame - 1)

    def project_last_frame_time(self) -> float:
        return self.project_last_frame() / self.FPS

    # ========================================================
    # Scale / zoom
    # ========================================================

    def max_zoom_out_seconds(self) -> float:
        project_duration = (
            self.project_end_seconds()
        )

        return max(
            self.MIN_PROJECT_VIEW_SECONDS,
            project_duration
            * self.MAX_VIEW_MULTIPLIER,
            self.DEFAULT_VISIBLE_SECONDS,
        )

    def default_visible_seconds(self) -> float:
        return self.DEFAULT_VISIBLE_SECONDS

    def _editor_viewport_width(self) -> float:
        if not hasattr(
            self,
            "tracks_scroll",
        ):
            return 900.0

        width = float(
            self.tracks_scroll.viewport().width()
        )

        return max(
            1.0,
            width if width > 0 else 900.0,
        )

    def visible_seconds_for_zoom(
        self,
        value: int,
    ) -> float:
        value = max(
            self.ZOOM_MIN_VALUE,
            min(
                self.ZOOM_MAX_VALUE,
                int(value),
            ),
        )

        max_view = max(
            self.MIN_VISIBLE_SECONDS,
            self.max_zoom_out_seconds(),
        )
        default_view = self.DEFAULT_VISIBLE_SECONDS
        min_view = self.MIN_VISIBLE_SECONDS

        if value <= self.ZOOM_CENTER_VALUE:
            if max_view <= default_view + 1e-9:
                return default_view

            t = (
                value
                / float(
                    self.ZOOM_CENTER_VALUE
                )
            )

            return (
                max_view
                * (
                    default_view
                    / max_view
                ) ** t
            )

        t = (
            value
            - self.ZOOM_CENTER_VALUE
        ) / float(
            self.ZOOM_MAX_VALUE
            - self.ZOOM_CENTER_VALUE
        )

        return (
            default_view
            * (
                min_view
                / default_view
            ) ** t
        )

    # Backward-compatible alias.
    def _visible_seconds_for_zoom(
        self,
        value: int,
    ) -> float:
        return self.visible_seconds_for_zoom(
            value
        )

    def current_visible_seconds(self) -> float:
        if self.pixels_per_second <= 0.0:
            return self.DEFAULT_VISIBLE_SECONDS

        return (
            self._editor_viewport_width()
            / self.pixels_per_second
        )

    def _pps_for_zoom(
        self,
        value: int,
    ) -> float:
        visible = self.visible_seconds_for_zoom(
            value
        )
        return (
            self._editor_viewport_width()
            / max(
                0.001,
                visible,
            )
        )

    def ruler_duration_frames(self) -> int:
        visible = self.current_visible_seconds()
        axis_seconds = max(
            self.MIN_VISIBLE_SECONDS,
            visible,
            self.project_end_seconds() + 2.0,
        )

        return int(
            math.ceil(
                axis_seconds * self.FPS
            )
        )

    def ruler_duration(self) -> float:
        return (
            self.ruler_duration_frames()
            / self.FPS
        )

    def content_width(self) -> int:
        return max(
            int(self._editor_viewport_width()),
            int(
                round(
                    self.ruler_duration_frames()
                    * self.pixels_per_frame
                )
            ),
        )

    def layer_content_height(self) -> int:
        """Natural content height shared by all timeline columns.

        All tracks, including the main video lane, occupy a normal row. This
        matches the OpenCut layout model: the label column and track viewport
        share the same scrollTop instead of pinning the main lane independently.
        """
        rows_height = int(self._stack_rows_height())
        # Top and bottom are the same live value. For a short stack their
        # combined height fills the available viewport without biasing either
        # side; once the stack overflows, both remain the fixed drop-zone size.
        gap = int(self._outer_layer_gap_height())
        return max(1, gap + rows_height + gap)

    def _apply_initial_scale(self):
        if not self._initial_scale_pending:
            return

        self._initial_scale_pending = False
        self._ready = True

        self.set_zoom(
            self.ZOOM_CENTER_VALUE,
            preserve_center=False,
        )

    def _update_zoom_label(
        self,
        visible_seconds: float,
    ):
        if visible_seconds <= 1.000001:
            self.zoom_label.setText(
                "1s / 30f"
            )
        elif visible_seconds < 10.0:
            self.zoom_label.setText(
                f"{visible_seconds:.1f}s"
            )
        else:
            self.zoom_label.setText(
                f"{visible_seconds:.0f}s"
            )

    def _concat_select_tab(self, index: int):
        self._concat_current_tab = int(index)
        for i, b in enumerate(getattr(self, "_timeline_tabs", [])):
            b.setChecked(i == self._concat_current_tab)

    def _concat_add_tab(self):
        # Skyzen currently has one real project timeline. Keep the + control
        # functional without inventing a second document model.
        self._concat_select_tab(0)

    def _concat_set_tool(self, tool: str):
        self._concat_tool = tool
        if tool == "split":
            self._razor_button.setChecked(True)
        else:
            self._razor_button.setChecked(False)

    def _concat_toggle_pan(self):
        self._concat_pan_mode = not self._concat_pan_mode
        self._pan_button.setChecked(self._concat_pan_mode)

    def _concat_toggle_trim_follow(self):
        self._concat_trim_follow = not self._concat_trim_follow
        self._trim_follow_button.setChecked(self._concat_trim_follow)

    def _concat_toggle_magnetic(self):
        self._concat_magnetic = not self._concat_magnetic
        self._magnetic_button.setChecked(self._concat_magnetic)

    def _concat_toggle_preview_axis(self):
        self._concat_preview_axis = not self._concat_preview_axis
        self._axis_button.setChecked(self._concat_preview_axis)
        self.preview_time = self.playhead if self._concat_preview_axis else None
        self._move_marker()

    def _concat_merge(self):
        # Merge is intentionally conservative until Skyzen has a multi-clip
        # merge command in its edit model.
        return

    def _concat_transform_menu(self):
        if not self.selected_clip:
            return
        menu = QMenu(self)
        mirror = menu.addAction("Mirror")
        rotate = menu.addAction("Rotate 90°")
        freeze = menu.addAction("Freeze")
        action = menu.exec(self.mapToGlobal(QPoint(self.width()//2, 20)))
        if action == mirror:
            self.toggle_clip_flag("mirror_x")
        elif action == rotate:
            self.rotate_selected()
        elif action == freeze:
            self.toggle_clip_flag("freeze")

    def _concat_captions(self):
        if hasattr(self, "project_preview_requested"):
            self.project_preview_requested.emit()

    def _concat_tts(self):
        if hasattr(self, "project_preview_requested"):
            self.project_preview_requested.emit()

    def _concat_fit_zoom(self):
        viewport = max(1.0, self._editor_viewport_width())
        duration = max(1.0, self.duration())
        # Match Concat's fit behavior: leave a small amount of breathing room.
        target_pps = viewport / (duration * 1.05)
        best = self.ZOOM_CENTER_VALUE
        best_err = float("inf")
        for value in range(self.ZOOM_MIN_VALUE, self.ZOOM_MAX_VALUE + 1, 25):
            pps = self._pps_for_zoom(value)
            err = abs(pps - target_pps)
            if err < best_err:
                best_err, best = err, value
        self.set_zoom(best, preserve_center=False)

    def set_zoom(
        self,
        value: int,
        preserve_center: bool = True,
    ):
        value = max(
            self.ZOOM_MIN_VALUE,
            min(
                self.ZOOM_MAX_VALUE,
                int(value),
            ),
        )

        viewport_width = (
            self._editor_viewport_width()
        )

        if preserve_center and self.pixels_per_second > 0.0:
            scroll_value = (
                self.tracks_scroll
                .horizontalScrollBar()
                .value()
            )
            old_x = self.time_to_x(
                self.playhead
            )
            marker_screen = (
                old_x - scroll_value
            )

            if 0 <= marker_screen <= viewport_width:
                anchor_screen = marker_screen
            else:
                anchor_screen = viewport_width / 2.0
        else:
            anchor_screen = viewport_width / 2.0

        visible = self.visible_seconds_for_zoom(
            value
        )
        pps = self._pps_for_zoom(value)

        self.pixels_per_second = pps
        self.pixels_per_frame = (
            pps / self.FPS
        )

        self._update_zoom_label(
            visible
        )

        self.rebuild(
            keep_view=False
        )

        new_x = self.time_to_x(
            self.playhead
        )

        scrollbar = (
            self.tracks_scroll
            .horizontalScrollBar()
        )
        maximum = scrollbar.maximum()

        desired = int(
            round(
                new_x
                - anchor_screen
            )
        )

        scrollbar.setValue(
            max(
                0,
                min(
                    maximum,
                    desired,
                ),
            )
        )

        self._on_horizontal_scroll(
            scrollbar.value()
        )
        self._move_marker()

    def zoom_step(
        self,
        direction: int,
    ):
        value = (
            self.zoom_slider.value()
        )

        # User-adjustable wheel zoom while keeping the slider fully continuous.
        step = max(40, min(350, int(getattr(self, "zoom_wheel_step", 150))))

        new_value = max(
            self.ZOOM_MIN_VALUE,
            min(
                self.ZOOM_MAX_VALUE,
                value
                + (
                    step
                    if direction > 0
                    else -step
                ),
            ),
        )

        if new_value != value:
            self.zoom_slider.setValue(
                new_value
            )

    # ========================================================
    # Playhead
    # ========================================================

    def set_playhead(
        self,
        seconds: float,
        emit: bool = True,
        ensure_visible: bool = True,
    ):
        target = self.snap_to_frame(
            seconds,
            self.FPS,
        )
        frame = self.frame_from_seconds(
            target
        )

        self.playhead = target
        self.refresh_keyframe_overlays()

        frame_changed = (
            frame
            != getattr(
                self,
                "_last_set_playhead_frame",
                None,
            )
        )
        stack_changed = False

        if frame_changed or emit:
            active = self._active_timeline_layers(target)
            signature = tuple(
                (
                    item.get("clip_id"),
                    item.get("row"),
                    self.frame_from_seconds(
                        item.get("start", 0.0)
                    ),
                    self.frame_from_seconds(
                        item.get("source_in", 0.0)
                    ),
                    self.frame_from_seconds(
                        item.get("duration", 0.0)
                    ),
                )
                for item in active
            )
            stack_changed = (
                signature
                != self._active_stack_signature
            )

            self._last_set_playhead_frame = frame
            self._active_stack_signature = signature

            self._emit_active_clips(
                target,
                push_to_player=bool(
                    emit
                    or stack_changed
                ),
            )

        if frame_changed:
            self.project_time_changed.emit(
                self.playhead
            )

        if emit:
            self.time_changed.emit(
                self.playhead
            )

        self._move_marker()

        if ensure_visible:
            self._ensure_playhead_visible()

    def _ensure_playhead_visible(self):
        if not hasattr(
            self,
            "tracks_scroll",
        ):
            return

        x = self.time_to_x(
            self.playhead
        )
        scroll = self.tracks_scroll.horizontalScrollBar()
        left = scroll.value()
        right = left + self._editor_viewport_width()
        margin = 32

        if x < left + margin:
            scroll.setValue(
                max(
                    0,
                    int(x - margin),
                )
            )
        elif x > right - margin:
            scroll.setValue(
                max(
                    0,
                    min(
                        scroll.maximum(),
                        int(
                            x
                            - self._editor_viewport_width()
                            + margin
                        ),
                    ),
                )
            )

    def _sync_layer_scrolls(self, value: int):
        """Compatibility slot; vertical synchronization lives in alignment.py."""
        coordinator = getattr(self, "_scroll_coordinator", None)
        if coordinator is not None:
            coordinator.sync_from_value(value)
        else:
            self._position_sticky_main_rows()

    def _position_sticky_main_rows(self):
        """Pin the Main row (tracks + label) to the viewport bottom."""
        for column in (
            getattr(self, "content", None),
            getattr(self, "sidebar_content", None),
            getattr(self, "edit_gutter_content", None),
        ):
            for method_name in ("_position_sticky_main", "_position_sticky_audio"):
                mover = getattr(column, method_name, None)
                if callable(mover):
                    mover()

    def _sticky_main_y(self):
        """Compatibility entry point; geometry is calculated in track_layout.py."""
        from .track_layout import sticky_main_lane_y
        return sticky_main_lane_y(self)

    def _align_layer_scroll_ranges(self):
        """Compatibility wrapper for the shared scroll coordinator."""
        coordinator = getattr(self, "_scroll_coordinator", None)
        if coordinator is not None:
            coordinator.align_ranges()

    def _on_horizontal_scroll(
        self,
        value: int,
    ):
        if not hasattr(
            self,
            "ruler",
        ):
            return

        self.ruler.move(
            -int(value),
            0,
        )

        x = self.time_to_x(
            self.playhead
        )
        viewport_x = (
            x - int(value)
        )

        self.marker_head.setGeometry(
            viewport_x - 7,
            0,
            14,
            14,
        )
        self.marker_head.raise_()

        self._move_marker()

    def set_preview_marker(self, seconds: float):
        if not self._concat_preview_axis:
            return
        target = self.snap_to_frame(max(0.0, float(seconds)), self.FPS)
        self.preview_time = target
        self._emit_active_clips(target, push_to_player=True)
        self._move_marker()

    def _move_marker(self):
        if not hasattr(
            self,
            "content",
        ):
            return

        x = self.time_to_x(
            self.playhead
        )

        self.content._playhead_line.setGeometry(
            x,
            0,
            2,
            max(
                1,
                self.content.height(),
            ),
        )
        self.content._playhead_line.raise_()

        scroll_x = (
            self.tracks_scroll
            .horizontalScrollBar()
            .value()
        )

        self.marker_head.setGeometry(
            x - scroll_x - 7,
            0,
            14,
            14,
        )
        self.marker_head.raise_()

        preview_head = getattr(self, "preview_marker_head", None)
        if preview_head is not None:
            if self._concat_preview_axis and self.preview_time is not None:
                px = self.time_to_x(self.preview_time) - scroll_x
                preview_head.setGeometry(px - 7, 0, 14, 14)
                preview_head.show()
                preview_head.raise_()
            else:
                preview_head.hide()

        preview_line = getattr(self.content, "_preview_line", None)
        if preview_line is not None:
            if self._concat_preview_axis and self.preview_time is not None:
                preview_line.setGeometry(
                    self.time_to_x(self.preview_time),
                    0,
                    1,
                    max(1, self.content.height()),
                )
                preview_line.show()
                preview_line.raise_()
            else:
                preview_line.hide()

    # ========================================================
    # Media thumbnails
    # ========================================================

    def thumbnail_for(
        self,
        clip: dict,
    ) -> QPixmap:
        """Return a thumbnail immediately; video extraction runs off the UI thread."""
        path = str(clip.get("path", ""))
        if not path:
            return QPixmap()

        cached = self._thumbnail_cache.get(path)
        if cached is not None:
            return cached

        p = Path(path)
        kind = str(clip.get("kind", "")).strip().casefold()
        # Imported image clips can originate from older project files whose
        # kind field is missing or differently cased. Detect from extension
        # so timeline still paints their source thumbnail.
        if kind != "image" and p.suffix.casefold() in IMAGE_EXTS:
            kind = "image"
        if kind == "image":
            try:
                reader = QImageReader(str(p))
                reader.setAutoTransform(True)
                size = reader.size()
                if size.isValid():
                    size.scale(480, 270, Qt.AspectRatioMode.KeepAspectRatio)
                    reader.setScaledSize(size)
                pix = QPixmap.fromImage(reader.read())
            except Exception:
                pix = QPixmap(str(p))
        elif kind == "video" or p.suffix.casefold() in VIDEO_EXTS:
            pix = self.thumbnail_service.request(p)
        else:
            pix = QPixmap()

        self._thumbnail_cache[path] = pix
        return pix

    def _on_shared_thumbnail_ready(self, source_path: str, pixmap: QPixmap):
        """Refresh visible clip widgets when the shared worker finishes."""
        if pixmap.isNull():
            return
        source_key = str(Path(source_path).resolve())
        self._thumbnail_cache[source_key] = pixmap
        # Normalize matching cache keys too, in case a project stored a
        # relative media path before it was resolved by the browser.
        for cached_path in list(self._thumbnail_cache):
            try:
                if str(Path(cached_path).resolve()) == source_key:
                    self._thumbnail_cache[cached_path] = pixmap
            except (OSError, RuntimeError):
                continue
        # Existing ClipWidgets retain their initial pixmap, so update those
        # instances explicitly without rebuilding the entire timeline.
        try:
            for widget in self.findChildren(ClipWidget):
                try:
                    if str(Path(widget.clip.get("path", "")).resolve()) == source_key:
                        widget.thumbnail = pixmap
                        widget.update()
                except (OSError, RuntimeError):
                    continue
        except RuntimeError:
            pass

    # Snapping / selection
    # ========================================================

    def snap_time(
        self,
        value: float,
        exclude=None,
    ) -> float:
        value = self.snap_to_frame(
            value,
            self.FPS,
        )

        points = [0.0, self.playhead]

        for track in self.tracks:
            for clip in track["clips"]:
                if (
                    exclude is not None
                    and clip is exclude
                ):
                    continue

                start = float(
                    clip.get("start", 0.0)
                )
                end = (
                    start
                    + float(
                        clip.get(
                            "duration",
                            0.0,
                        )
                    )
                )
                points.extend(
                    (
                        start,
                        end,
                    )
                )

        threshold = max(
            self.MIN_CLIP_SECONDS,
            6.0 / max(
                0.001,
                self.pixels_per_second,
            ),
        )

        nearest = min(
            points,
            key=lambda p: abs(
                p - value
            ),
        )

        if abs(nearest - value) <= threshold:
            return self.snap_to_frame(
                nearest,
                self.FPS,
            )

        return value

    def _scroll_timeline_wheel(self, event):
        """Ctrl+wheel zooms; plain wheel scrolls layers; Shift+wheel pans horizontally."""
        delta_y = int(event.angleDelta().y())
        delta_x = int(event.angleDelta().x())

        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            zoom_delta = delta_y if delta_y else int(event.pixelDelta().y()) * 3
            if zoom_delta:
                sensitivity = max(40, min(350, int(getattr(self, "zoom_wheel_step", 150))))
                units = zoom_delta / 120.0 if delta_y else zoom_delta / 120.0
                step = max(1, int(round(abs(units) * sensitivity)))
                current = int(self.zoom_slider.value())
                target = max(self.ZOOM_MIN_VALUE, min(self.ZOOM_MAX_VALUE,
                    current + (step if zoom_delta > 0 else -step)))
                if target != current:
                    self.zoom_slider.setValue(target)
                event.accept()
                return True
            return False

        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            delta = delta_x if delta_x else delta_y
            if delta:
                bar = self.tracks_scroll.horizontalScrollBar()
                step = max(1, int(bar.singleStep()) * int(getattr(self, "horizontal_pan_multiplier", 7)))
                value = bar.value() - int(round(delta / 120.0 * step))
                bar.setValue(max(0, min(bar.maximum(), value)))
                event.accept()
                return True
            return False

        if delta_y or event.pixelDelta().y():
            from .track_layout import wheel_scroll_delta
            bar = self.tracks_scroll.verticalScrollBar()
            amount = wheel_scroll_delta(
                delta_y, int(event.pixelDelta().y()), int(self.TRACK_HEIGHT)
            )
            amount = int(round(amount * float(getattr(self, "vertical_scroll_multiplier", 1.0))))
            bar.setValue(max(0, min(bar.maximum(), bar.value() + amount)))
            event.accept()
            return True

        return False

    def _request_project_preview(self):
        """Tell the host that no individual clip is selected."""
        self.selection_cleared.emit()
        self.project_preview_requested.emit()

        panel = getattr(self.window(), "player", None)
        if panel is None:
            return

        # Compatible with the current/next PlayerPanel without making the
        # timeline depend on its implementation.
        for name in (
            "return_to_project_preview",
            "show_project_preview",
            "clear_clip_selection",
        ):
            method = getattr(panel, name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass
                return

    def refresh_keyframe_overlays(self):
        """Repaint clip surfaces after the Inspector changes active property/time."""
        if not hasattr(self, "content"):
            return
        try:
            for area in self.content.findChildren(TrackArea):
                for child in area.findChildren(ClipWidget):
                    child.update()
        except (RuntimeError, AttributeError):
            pass

    def select_clip(
        self,
        clip: dict | None,
        widget: ClipWidget | None = None,
    ):
        old = self.selected_clip
        self.selected_clip = clip
        if clip is not None:
            try:
                self.setFocus(Qt.FocusReason.MouseFocusReason)
            except Exception:
                pass

        if clip is None:
            self.selection_cleared.emit()
            self._request_project_preview()

        # Refresh the old/new visible clip widgets immediately so the
        # selection border never depends on a full timeline rebuild.
        if hasattr(self, "content"):
            for area in self.content.findChildren(TrackArea):
                for child in area.findChildren(ClipWidget):
                    if child.clip is old or child.clip is clip:
                        child.update()

        if clip is not None:
            self.clip_selected.emit(
                str(clip.get("path", "")),
                float(clip.get("start", 0.0)),
                float(clip.get("duration", 0.0)),
                str(clip.get("kind", "Video")),
            )

    # ========================================================
    # Tracks
    # ========================================================

    def _track_base_for_kind(
        self,
        kind: str,
    ) -> str:
        normalized = str(kind or "Video").strip().casefold()
        return "A" if normalized == "audio" else ("E" if normalized == "effect" else "V")

    def _stack_order_for_track(
        self,
        track: dict,
        direction: int,
    ) -> float:
        """Return a stack order just beyond this track."""
        group = [
            item for item in self.tracks
            if item.get("base") == track.get("base")
        ]

        if not group:
            return 0.0

        current = float(
            track.get("_stack_order", 0.0)
        )

        if direction < 0:
            return current - 1.0

        return current + 1.0

    def _ensure_main_video_track(self) -> dict:
        """Return/create the permanent bottom V1 project lane."""
        videos = [t for t in self.tracks if t.get("base") == "V"]
        mains = [t for t in videos if t.get("is_main", False)]
        if mains:
            main = min(mains, key=lambda t: int(str(t.get("name", "V999"))[1:]) if str(t.get("name", "V0"))[1:].isdigit() else 999999)
            for t in videos:
                t["is_main"] = (t is main)
            main["is_main"] = True
            main.setdefault("_stack_order", 999999.0)
            return main

        v1 = next((t for t in videos if str(t.get("name", "")).upper() == "V1"), None)
        if v1 is not None:
            for t in videos:
                t["is_main"] = (t is v1)
            v1.setdefault("_stack_order", 999999.0)
            return v1

        # Create the structural lane directly so construction does not push
        # another history item or trigger a rebuild.
        existing_numbers = []
        for t in videos:
            try:
                existing_numbers.append(int(str(t.get("name", "V0"))[1:]))
            except Exception:
                pass
        track = {
            "name": "V1" if not videos else f"V{max(existing_numbers, default=0)+1}",
            "base": "V",
            "clips": [],
            "locked": False,
            "hidden": False,
            "volume": 1.0,
            "muted": False,
            "_stack_order": 999999.0,
            "is_main": True,
        }
        self.tracks.append(track)
        return track

    def _new_track(
        self,
        base: str,
        stack_order: float | None = None,
    ) -> dict:
        existing_numbers = []
        same_base = []

        for track in self.tracks:
            if track.get("base") != base:
                continue
            same_base.append(track)
            try:
                existing_numbers.append(int(str(track["name"])[1:]))
            except Exception:
                pass

        number = max(existing_numbers, default=0) + 1

        if stack_order is None:
            existing_orders = [
                float(t.get("_stack_order", 0.0))
                for t in same_base
            ]
            if base == "V":
                # Every additional video is an overlay above the main layer.
                stack_order = (
                    min(existing_orders) - 1.0
                    if existing_orders
                    else 0.0
                )
            else:
                stack_order = (
                    max(existing_orders, default=-1.0) + 1.0
                )

        is_main = (
            base == "V"
            and not same_base
        )

        track = {
            "name": f"{base}{number}",
            "base": base,
            "clips": [],
            "locked": False,
            "hidden": False,
            "volume": 1.0,
            "muted": False,
            "_stack_order": float(stack_order),
            "is_main": bool(is_main),
        }

        self.tracks.append(track)
        return track

    def add_empty_track(
        self,
        base: str = "V",
    ):
        self._push_history()
        track = self._new_track(base)
        if base == "V":
            track["is_main"] = False if any(
                t.get("base") == "V" and t is not track
                for t in self.tracks
            ) else True
        elif base == "E":
            track["effect_type"] = "Generic Effect"
            track["linked_tracks"] = []
        self.rebuild()

    def _track_for_selected_layer(self):
        if self.selected_clip is not None:
            for track in self.tracks:
                if self.selected_clip in track.get(
                    "clips",
                    []
                ):
                    return track

        display = self.display_tracks()
        main = next(
            (t for t in display if t.get("is_main")),
            None,
        )
        return main or (display[0] if display else None)

    def edit_layer(self, track: dict):
        if track is None:
            return

        current = str(
            track.get(
                "name",
                "Layer",
            )
        )

        value, ok = QInputDialog.getText(
            self,
            "Edit Layer",
            "Layer name:",
            text=current,
        )
        if not ok:
            return

        value = str(value).strip()
        if not value:
            return

        self._push_history()
        track["name"] = value
        self.rebuild(
            keep_view=True
        )

    def edit_selected_layer(self):
        track = self._track_for_selected_layer()
        if track is not None:
            self.edit_layer(track)

    def set_track_locked(
        self,
        track: dict,
        locked: bool,
    ):
        track["locked"] = bool(locked)
        for clip in track["clips"]:
            clip["_locked_ui"] = bool(locked)

        self.rebuild(
            keep_view=True
        )

    def set_track_hidden(
        self,
        track: dict,
        hidden: bool,
    ):
        track["hidden"] = bool(hidden)
        self._active_stack_signature = None
        self.rebuild(
            keep_view=True
        )
        self._emit_active_clips(
            self.playhead
        )

    def set_track_muted(
        self,
        track: dict,
        muted: bool,
    ):
        if track.get("muted", False) == bool(muted):
            return
        self._push_history()
        track["muted"] = bool(muted)
        # The composite renderer owns audio for all active video layers. Emit
        # the updated project snapshot so the next preview mix respects mute.
        self._emit_active_clips(self.playhead)
        self.rebuild(keep_view=True)

    def set_track_volume(self, track: dict, volume: float):
        """Set per-layer soundtrack volume from 0% to 200%."""
        try:
            normalized = max(0.0, min(2.0, float(volume)))
        except (TypeError, ValueError):
            return
        if abs(float(track.get("volume", 1.0)) - normalized) < 0.0001:
            return
        self._push_history()
        track["volume"] = normalized
        self._emit_active_clips(self.playhead)
        self.rebuild(keep_view=True)

    # ========================================================
    # Add / drop
    # ========================================================

    def _normalize_duration(
        self,
        seconds: float,
    ) -> float:
        frames = max(
            1,
            self.frame_from_seconds(
                seconds,
                self.FPS,
            ),
        )
        return frames / self.FPS

    def _clip_from_media(
        self,
        path_obj: Path,
        kind: str,
        start: float,
    ) -> dict:
        # Normalize media kind at the model boundary. Drag MIME payloads and
        # legacy projects may use inconsistent capitalization.
        normalized_kind = str(kind or "Video").strip().casefold()
        kind = {"audio": "Audio", "image": "Image", "effect": "Effect"}.get(
            normalized_kind, "Video"
        )
        # Still images have no intrinsic timeline duration. OpenCut's default
        # is a five-second still clip; keep video/audio duration from probing.
        if str(kind).strip().lower() == "image":
            duration = self._normalize_duration(5.0)
        else:
            duration = self._normalize_duration(
                source_duration(
                    path_obj,
                    self.root_dir,
                )
            )

        return {
            "path": str(path_obj),
            "kind": kind,
            "start": self.snap_to_frame(
                start,
                self.FPS,
            ),
            "duration": duration,
            "source_in": 0.0,
            "source_duration": duration,

            # Project-preview transform contract. 100 = full-size.
            # Position values are pixel offsets from the preview center.
            "scale": 1.0,
            "position_x": 0.0,
            "position_y": 0.0,
            "rotation": 0.0,
            "opacity": 1.0,
        }

    def refresh_clip_source_duration(
        self,
        clip: dict,
    ):
        """
        Re-read the source file duration and update a clip created by an older
        timeline version that may still contain the old 5-second placeholder.
        """
        if str(clip.get("kind", "")).lower() == "image":
            return False  # stills have no intrinsic length

        try:
            path_obj = Path(
                str(clip.get("path", ""))
            ).resolve()

            if not path_obj.is_file():
                return False

            duration = self._normalize_duration(
                source_duration(
                    path_obj,
                    self.root_dir,
                )
            )

            old_source_duration = self._normalize_duration(
                float(
                    clip.get(
                        "source_duration",
                        clip.get("duration", 0.0),
                    )
                )
            )
            current_duration = self._normalize_duration(
                float(clip.get("duration", 0.0))
            )

            if duration <= 0.0:
                return False

            source_in = max(
                0.0,
                float(clip.get("source_in", 0.0)),
            )
            available = max(
                self.MIN_CLIP_SECONDS,
                duration - source_in,
            )

            # Older versions used a fabricated 5-second source duration. When
            # the clip duration still equals that stored source duration, it is
            # an untrimmed clip and should expand to the real source length.
            was_untrimmed = abs(
                current_duration - old_source_duration
            ) <= (1.0 / self.FPS)

            clip["source_duration"] = duration

            if was_untrimmed:
                clip["duration"] = available
            else:
                # A genuinely trimmed clip keeps its edit, but may not extend
                # past the newly verified source duration.
                clip["duration"] = min(
                    current_duration,
                    available,
                )

            clip["duration"] = self._normalize_duration(
                clip["duration"]
            )

            # Expanding an old placeholder clip must not overlap another clip
            # already occupying the same layer.
            track_for_clip = None
            for candidate_track in self.tracks:
                if clip in candidate_track.get("clips", []):
                    track_for_clip = candidate_track
                    break

            if track_for_clip is not None:
                duration_frames = self.frame_duration(clip)
                safe_start = self._nearest_free_start_frame(
                    track_for_clip,
                    self.clip_start_frame(clip),
                    duration_frames,
                    exclude=clip,
                )
                clip["start"] = safe_start / self.FPS

            return (
                abs(
                    duration - old_source_duration
                ) > (1.0 / self.FPS)
                or was_untrimmed
            )
        except Exception:
            return False

    def refresh_all_source_durations(self):
        changed = False

        for track in self.tracks:
            for clip in track["clips"]:
                if self.refresh_clip_source_duration(clip):
                    changed = True

        if changed:
            self.rebuild(
                keep_view=True
            )

        return changed

    def add_tool_asset_at_playhead(self, tool_type: str, preset_id: str):
        """Create a typed Text/Effect/Adjustment clip at the current playhead."""
        return self.add_tool_asset_at_time(tool_type, preset_id, self.playhead, None)

    def add_tool_asset_at_time(self, tool_type: str, preset_id: str, start: float, target_track=None):
        """Insert a real, serializable typed layer while preserving normal media lanes."""
        from app.left_toolbar.catalog import preset_for
        from app.left_toolbar.assets import transparent_tool_asset
        from app.left_toolbar.text_tool.main import render_text_asset
        from pathlib import Path

        tool_type = str(tool_type or "")
        preset = preset_for(tool_type, str(preset_id))
        if preset is None or tool_type not in ("Text", "Effects", "Filters", "Adjustments"):
            return None
        if tool_type == "Text":
            asset_path = render_text_asset(self.root_dir, preset)
        else:
            asset_path = transparent_tool_asset(self.root_dir, tool_type, preset_id)
        if not Path(asset_path).is_file():
            return None

        self._push_history()
        if tool_type == "Adjustments" and preset.get("scope") == "project":
            clip_start = 0.0
            clip_duration = max(1.0 / self.FPS, self.duration())
        else:
            clip_start = self.snap_to_frame(max(0.0, float(start)), self.FPS)
            clip_duration = self._normalize_duration(5.0)

        track = None
        if target_track and target_track in self.tracks and target_track.get("track_type") == tool_type and not target_track.get("locked", False):
            track = target_track
        if track is None:
            stack_order = None
            if target_track and target_track in self.tracks and target_track.get("base") == "V":
                stack_order = float(target_track.get("_stack_order", 0.0)) - 0.5
            track = self._new_track("V", stack_order=stack_order)
            track["track_type"] = tool_type
            prefix = {"Text": "TEXT", "Effects": "FX", "Filters": "FILTER", "Adjustments": "ADJ"}[tool_type]
            same = [t for t in self.tracks if t.get("track_type") == tool_type]
            track["display_name"] = f"{prefix} {len(same)}"

        clip = {
            "path": str(Path(asset_path).resolve()),
            "kind": "Image",
            "tool_type": tool_type,
            "tool_preset": str(preset_id),
            "display_name": str(preset.get("name", tool_type)),
            "start": clip_start,
            "duration": clip_duration,
            "source_in": 0.0,
            "source_duration": clip_duration,
            "scale": 1.0, "position_x": 0.0, "position_y": 0.0,
            "position_z": 0.0, "rotation": 0.0, "opacity": 1.0,
            "text": str(preset.get("text", "")),
            "font_size": int(preset.get("font_size", 72)),
            "text_color": str(preset.get("color", "#FFFFFF")),
            "text_align": str(preset.get("align", "center")),
            "text_bold": bool(preset.get("bold", False)),
            "text_y": float(preset.get("y", 0.5)),
            "effect_type": str(preset.get("effect", "")),
            "intensity": float(preset.get("intensity", 1.0)),
            "scope": str(preset.get("scope", "below")),
            "brightness": float(preset.get("brightness", 0.0)),
            "contrast": float(preset.get("contrast", 1.0)),
            "saturation": float(preset.get("saturation", 1.0)),
            "gamma": float(preset.get("gamma", 1.0)),
            "temperature": float(preset.get("temperature", 0.0)),
            "tint": float(preset.get("tint", 0.0)),
            "highlights": float(preset.get("highlights", 0.0)),
            "shadows": float(preset.get("shadows", 0.0)),
            "hue": 0.0, "vibrance": 0.0,
        }
        track.setdefault("clips", []).append(clip)
        track["clips"].sort(key=lambda c: self.clip_start_frame(c))
        self.playhead = clip_start
        self.selected_clip = clip
        self._active_stack_signature = None
        self.rebuild(keep_view=True)
        self.select_clip(clip)
        self.time_changed.emit(self.playhead)
        self._emit_active_clips(self.playhead)
        return clip

    def refresh_tool_clip(self, clip):
        """Regenerate a tool's source asset after its editable properties change."""
        if not isinstance(clip, dict) or not clip.get("tool_type"):
            return
        from app.left_toolbar.catalog import preset_for
        from app.left_toolbar.assets import transparent_tool_asset
        from app.left_toolbar.text_tool.main import render_text_asset
        tool_type = str(clip.get("tool_type"))
        preset = preset_for(tool_type, str(clip.get("tool_preset", ""))) or {
            "id": clip.get("tool_preset", "custom"), "text": clip.get("text", "Your title"),
            "font_size": clip.get("font_size", 72), "color": clip.get("text_color", "#FFFFFF"),
            "align": clip.get("text_align", "center"), "y": clip.get("text_y", 0.5),
            "bold": clip.get("text_bold", False),
        }
        if tool_type == "Text":
            path = render_text_asset(self.root_dir, preset, clip.get("text"), clip.get("font_size"), clip.get("text_color"))
            clip["path"] = str(Path(path).resolve())
        self._active_stack_signature = None
        self.rebuild(keep_view=True)
        self._emit_active_clips(self.playhead)

    def add_media_at_playhead(
        self,
        path: str,
        kind: str,
    ):
        """Place media using the Concat-style base/overlay rule.

        The first visual clip belongs to the permanent V1 base lane. Every
        later visual clip becomes a new overlay. Audio creates/uses audio
        lanes independently. This prevents an empty V1 from appearing while
        the first clip is incorrectly created on V2.
        """
        path_obj = Path(path).resolve()
        if not path_obj.is_file():
            return

        base = self._track_base_for_kind(kind)
        self._push_history()

        target = None
        if base == "V":
            main = self._ensure_main_video_track()
            if not main.get("clips"):
                # The project starts with one base lane. Its first clip is the
                # base media and is anchored to frame 0.
                target = main
            else:
                # Subsequent visual media are real overlays.
                target = self._new_track("V")
        else:
            # Audio remains independent from the visual base/overlay stack.
            # Create a fresh audio lane for intentional placement.
            target = self._new_track("A")

        clip_start = self.playhead
        if base == "V" and target.get("is_main", False):
            clip_start = 0.0

        clip = self._clip_from_media(
            path_obj,
            kind,
            clip_start,
        )
        target["clips"].append(clip)
        target["clips"].sort(key=lambda c: c["start"])

        self.playhead = clip["start"]
        self.selected_clip = clip
        self._active_stack_signature = None

        self.rebuild(keep_view=False if target.get("is_main", False) else True)
        self.select_clip(clip)
        self.time_changed.emit(self.playhead)
        self._emit_active_clips(self.playhead)

    def _ripple_insert(self, track: dict, insert_frame: int, duration_frames: int, exclude=None) -> int:
        """Insert a clip without collisions and close the immediate right gap.

        The first clip to the right is repositioned to the inserted clip's end;
        later clips move by the same frame delta, preserving their spacing.
        A clip straddling the insertion point is shifted right far enough to
        clear the new clip. Returns the applied frame delta (which can be
        negative when closing an empty gap).
        """
        insert_frame = max(0, int(insert_frame))
        duration_frames = max(1, int(duration_frames))
        candidates = [
            other for other in track.get("clips", []) if other is not exclude
        ]
        shift, earliest_start = ripple_insert_plan(
            [
                (self.clip_start_frame(other), self.clip_end_frame(other))
                for other in candidates
            ],
            insert_frame,
            duration_frames,
        )
        if earliest_start is None:
            return 0
        for other in candidates:
            start = self.clip_start_frame(other)
            end = self.clip_end_frame(other)
            if start >= earliest_start or end > insert_frame:
                other["start"] = (start + shift) / self.FPS
        track["clips"].sort(key=lambda c: c.get("start", 0.0))
        return shift

    def add_to_existing_track(
        self,
        path: str,
        kind: str,
        start: float,
        track=None,
    ):
        path_obj = Path(path).resolve()
        if not path_obj.is_file():
            return

        target = track

        if target is None:
            sender = self.sender()
            if isinstance(
                sender,
                TrackArea,
            ):
                target = sender.track

        if target is None:
            return

        if target.get("base") != self._track_base_for_kind(
            kind
        ):
            return

        if target.get("locked", False):
            return

        self._push_history()

        clip = self._clip_from_media(
            path_obj,
            kind,
            self.snap_time(start),
        )

        duration_frames = max(1, self.frame_duration(clip))
        requested_frame = max(0, self.frame_from_seconds(start))
        if target.get("is_main", False):
            # Main is a sequence, never a free-form lane. Dropping anywhere on
            # an existing main clip selects the nearest side of that clip;
            # dropping into empty space selects the nearest sequence boundary.
            # The entire sequence is then rebuilt from frame 0 so gaps and
            # overlaps cannot survive an external media drop.
            ordered = sorted(
                list(target.get("clips", [])),
                key=lambda item: self.clip_start_frame(item),
            )
            insert_index = self._main_sequence_insert_index(target, requested_frame)
            ordered.insert(insert_index, clip)
            target["clips"] = ordered
            self._normalize_main_track(target)
            requested_frame = self.clip_start_frame(clip)
        else:
            self._ripple_insert(target, requested_frame, duration_frames)
            clip["start"] = requested_frame / self.FPS
            target["clips"].append(clip)
            target["clips"].sort(key=lambda c: c["start"])

        self.playhead = clip["start"]

        self.rebuild()

        self.select_clip(
            clip
        )
        self.time_changed.emit(
            self.playhead
        )

    def _log_drop_failure(self, operation: str, exc: Exception) -> None:
        """Record a failed drag/drop without allowing a bad payload to abort Qt."""
        try:
            log_path = Path(self.root_dir) / "logs" / "timeline_drop_errors.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                import traceback
                handle.write(f"\n[{operation}] {type(exc).__name__}: {exc}\n")
                handle.write(traceback.format_exc())
        except Exception:
            # Logging must never turn a recoverable drop failure into a crash.
            pass

    def _drop_new_track(
        self,
        path: str,
        kind: str,
        start: float,
    ):
        path_obj = Path(path).resolve()
        if not path_obj.is_file():
            return
        kind = {"audio": "Audio", "image": "Image", "video": "Video", "effect": "Effect"}.get(
            str(kind or "Video").strip().casefold(), "Video"
        )

        self._push_history()

        base = self._track_base_for_kind(kind)
        video_tracks = [
            t for t in self.tracks if t.get("base") == "V"
        ]

        main = next((t for t in video_tracks if t.get("is_main", False)), None)
        if base == "V" and main is None:
            main = self._ensure_main_video_track()
            video_tracks = [t for t in self.tracks if t.get("base") == "V"]

        if base == "V" and main is not None and not main.get("clips"):
            track = main
            placement = 0.0
        else:
            track = self._new_track(base)
            placement = self.snap_to_frame(start, self.FPS)

        clip = self._clip_from_media(
            path_obj,
            kind,
            placement,
        )
        track["clips"].append(clip)
        if track.get("is_main"):
            clip["start"] = 0.0

        self.playhead = clip["start"]
        self.rebuild()
        self.select_clip(clip)
        self.time_changed.emit(self.playhead)

    def insert_media_as_new_layer(
        self,
        path: str,
        kind: str,
        start: float,
        display_gap_index: int,
        before_track=None,
    ):
        """Insert a brand-new compatible overlay at an exact visual stack slot."""
        path_obj = Path(path).resolve()
        if not path_obj.is_file():
            return

        base = self._track_base_for_kind(kind)
        if base == "V":
            main_track = self._ensure_main_video_track()
            if not main_track.get("clips"):
                # The first visual media always becomes the Main layer at 0:00.
                self._drop_new_track(path, kind, 0.0)
                return
        self._push_history()

        display = self.display_tracks()
        group = [t for t in display if t.get("base") == base]

        if base == "V":
            main = next((t for t in group if t.get("is_main", False)), None)
            overlays = [t for t in group if t is not main]
            # before_track tells us the exact slot among compatible video rows.
            if before_track in overlays:
                slot = overlays.index(before_track)
            else:
                # If the gap is between main and its first overlay, insert at the
                # bottom of the overlay stack but still above main. Otherwise use
                # the number of compatible rows above the gap.
                slot = 0
                for idx, t in enumerate(display[:int(display_gap_index)+1]):
                    if t in overlays:
                        slot += 1
                slot = min(slot, len(overlays))

            orders = [float(t.get("_stack_order", i)) for i, t in enumerate(overlays)]
            if not orders:
                order = 0.0
            elif slot <= 0:
                order = min(orders) - 1.0
            elif slot >= len(overlays):
                # Bottom overlay: immediately above the main layer.
                main_order = float(main.get("_stack_order", max(orders)+1.0)) if main else max(orders)+1.0
                order = (max(orders) + main_order) / 2.0
            else:
                order = (orders[slot-1] + orders[slot]) / 2.0

            track = self._new_track("V", stack_order=order)
            track["is_main"] = False
            clip_start = self.snap_to_frame(start, self.FPS)
        else:
            # Audio has no structural main lane. Its drop gaps are local to the
            # audio stack, so never interpret a global row index as an audio slot.
            audio_group = [t for t in self.tracks if t.get("base") == "A"]
            audio_group.sort(key=lambda t: (float(t.get("_stack_order", 0.0)), str(t.get("name", ""))))
            if before_track in audio_group:
                slot = audio_group.index(before_track)
            else:
                slot = len(audio_group)
            orders = [float(t.get("_stack_order", i)) for i, t in enumerate(audio_group)]
            if not orders:
                order = 0.0
            elif slot <= 0:
                order = min(orders) - 1.0
            elif slot >= len(orders):
                order = max(orders) + 1.0
            else:
                order = (orders[slot-1] + orders[slot]) / 2.0
            track = self._new_track("A", stack_order=order)
            clip_start = self.snap_to_frame(start, self.FPS)

        clip = self._clip_from_media(path_obj, kind, clip_start)
        track["clips"].append(clip)
        track["clips"].sort(key=lambda c: c["start"])

        self.playhead = clip["start"]
        self._active_stack_signature = None
        self.rebuild(keep_view=True)
        self.select_clip(clip)
        self.time_changed.emit(self.playhead)

    def add_as_new_track(
        self,
        path: str,
        kind: str,
        start: float,
    ):
        """Compatibility API: create a new compatible layer at start."""
        self._drop_new_track(path, kind, start)

    def _clamp_zoom_out_to_project(self):
        return

    # ========================================================
    # Layer / clip placement helpers
    # ========================================================

    def _find_clip_by_drag_id(self, drag_id: int):
        for track in self.tracks:
            for clip in track.get("clips", []):
                if id(clip) == int(drag_id):
                    return track, clip
        return None, None

    def _snap_adjacent_start_frame(
        self,
        track: dict,
        desired_start_frame: int,
        duration_frames: int,
        exclude=None,
    ) -> int | None:
        """Snap a moved clip exactly before/after nearby media."""
        if not self.snap_adjacent_enabled:
            return None

        desired_start_frame = max(0, int(desired_start_frame))
        duration_frames = max(1, int(duration_frames))
        desired_end = desired_start_frame + duration_frames

        threshold_frames = max(
            2,
            int(round(
                self.SNAP_DISTANCE_PX
                / max(0.001, self.pixels_per_frame)
            )),
        )

        candidates: list[int] = []

        for other in track.get("clips", []):
            if other is exclude:
                continue
            other_start = self.clip_start_frame(other)
            other_end = self.clip_end_frame(other)

            candidates.append(max(0, other_start - duration_frames))
            candidates.append(max(0, other_end))

        nearby = [
            candidate
            for candidate in candidates
            if abs(candidate - desired_start_frame) <= threshold_frames
        ]

        # A direct drop over another clip should still lock to one of its exact
        # edges instead of leaving an arbitrary gap.
        if not nearby:
            for other in track.get("clips", []):
                if other is exclude:
                    continue
                other_start = self.clip_start_frame(other)
                other_end = self.clip_end_frame(other)
                if (
                    desired_start_frame < other_end
                    and desired_end > other_start
                ):
                    nearby.extend((
                        max(0, other_start - duration_frames),
                        max(0, other_end),
                    ))

        valid = [
            candidate
            for candidate in nearby
            if not self._frame_overlaps_track(
                track,
                candidate,
                duration_frames,
                exclude=exclude,
            )
        ]

        if not valid:
            return None

        return min(
            valid,
            key=lambda candidate:
            abs(candidate - desired_start_frame),
        )

    def _frame_overlaps_track(
        self,
        track: dict,
        start_frame: int,
        duration_frames: int,
        exclude=None,
    ) -> bool:
        """Return True when a proposed clip range intersects existing media."""
        start_frame = max(0, int(start_frame))
        end_frame = start_frame + max(1, int(duration_frames))
        for other in track.get("clips", []):
            if other is exclude:
                continue
            other_start = self.clip_start_frame(other)
            other_end = self.clip_end_frame(other)
            if start_frame < other_end and end_frame > other_start:
                return True
        return False

    def _nearest_free_start_frame(
        self,
        track: dict,
        desired_start_frame: int,
        duration_frames: int,
        exclude=None,
    ) -> int:
        duration_frames = max(1, int(duration_frames))
        desired_start_frame = max(0, int(desired_start_frame))

        clips = [
            clip
            for clip in track.get("clips", [])
            if clip is not exclude
        ]
        clips.sort(key=lambda c: self.clip_start_frame(c))

        candidates = []
        cursor = 0

        for clip in clips:
            start = self.clip_start_frame(clip)
            end = self.clip_end_frame(clip)

            if cursor <= start - duration_frames:
                gap_start = cursor
                gap_end = max(cursor, start - duration_frames)
                candidates.append(
                    min(
                        max(desired_start_frame, gap_start),
                        gap_end,
                    )
                )

            cursor = max(cursor, end)

            if cursor > desired_start_frame + duration_frames:
                break

        # Infinite tail after the last clip.
        candidates.append(max(cursor, desired_start_frame))

        return min(
            candidates,
            key=lambda value: abs(value - desired_start_frame),
        )

    def _prune_empty_tracks(self):
        # The primary video layer is structural and remains even when empty.
        # Overlay/audio layers are removed when they no longer contain media.
        self.tracks = [
            track
            for track in self.tracks
            if track.get("clips") or track.get("is_main", False) or track.get("base") == "E"
        ]

    def _main_sequence_insert_index(self, track: dict, requested_frame: int, exclude=None) -> int:
        """Choose a deterministic before/after insertion slot in the main sequence.

        Main-lane drops use the pointer's timeline frame only to choose order;
        they never retain that frame as a free-form start position. Within a
        clip, its midpoint divides before from after. In empty space, the nearest
        existing sequence boundary wins.
        """
        ordered = sorted(
            [item for item in track.get("clips", []) if item is not exclude],
            key=lambda item: self.clip_start_frame(item),
        )
        if not ordered:
            return 0
        frame = max(0, int(requested_frame))
        for index, item in enumerate(ordered):
            start = self.clip_start_frame(item)
            end = self.clip_end_frame(item)
            if frame < start:
                # Empty space before this item: choose the closer boundary.
                if index == 0:
                    return 0
                # Both boundaries lead to the same insertion slot between
                # these two clips; normalization removes any legacy gap.
                return index
            if start <= frame <= end:
                midpoint = start + max(1, end - start) // 2
                return index if frame < midpoint else index + 1
        return len(ordered)

    def _normalize_main_track(self, track: dict) -> None:
        """Pack main-lane clips consecutively from frame zero, with no gaps."""
        if not track or not track.get("is_main", False):
            return
        ordered = sorted(
            track.get("clips", []),
            key=lambda item: self.clip_start_frame(item),
        )
        starts = contiguous_frame_starts(
            [self.frame_duration(item) for item in ordered]
        )
        for item, start_frame in zip(ordered, starts):
            item["start"] = start_frame / self.FPS
        track["clips"] = ordered

    def move_clip_object(
        self,
        clip: dict,
        target_track: dict,
        requested_start: float,
        force_insert: bool = False,
    ) -> bool:
        """Move a clip using direct pointer geometry, not Qt drag/drop."""
        source_track = None
        for track in self.tracks:
            if clip in track.get("clips", []):
                source_track = track
                break

        if source_track is None:
            return False

        if target_track is None:
            target_track = source_track

        if target_track.get("locked", False):
            return False

        if target_track.get("base") != source_track.get("base"):
            return False

        # The first Main clip is the project anchor: it may be trimmed/edited,
        # but cannot be moved to an overlay and leave the project without its
        # required starting picture.
        if source_track.get("is_main", False) and target_track is not source_track:
            first_main = min(
                source_track.get("clips", []),
                key=lambda c: self.clip_start_frame(c),
                default=None,
            )
            if first_main is clip:
                return False

        self._push_history()

        duration_frames = self.frame_duration(clip)
        requested_frame = self.frame_from_seconds(
            requested_start
        )
        if clip in source_track.get("clips", []):
            source_track["clips"].remove(clip)

        # The main video lane is a continuous base sequence, not a free-form
        # overlay lane. Reordering/inserting a clip on it always rebuilds the
        # sequence from frame 0 using each clip's exact frame duration. This
        # avoids accumulated gaps and makes the preview/drop boundary stable.
        if source_track.get("is_main", False) and source_track is not target_track:
            self._normalize_main_track(source_track)

        if target_track.get("is_main", False):
            ordered = sorted(
                target_track.get("clips", []),
                key=lambda other: self.clip_start_frame(other),
            )
            # requested_frame is the exact start/end boundary returned by the
            # shared drop resolver when hovering a clip. For empty space, it
            # selects the nearest sequence insertion point to the right.
            insert_index = len(ordered)
            for index, other in enumerate(ordered):
                if self.clip_start_frame(other) >= requested_frame:
                    insert_index = index
                    break
            ordered.insert(insert_index, clip)
            target_track["clips"] = ordered
            self._normalize_main_track(target_track)
            new_start_frame = self.clip_start_frame(clip)
        else:
            # Overlays remain free-form, but collision insertion uses the same
            # frame-domain ripple plan for every drop path.
            original_start_frame = self.frame_from_seconds(clip.get("start", 0.0))
            if (
                not force_insert
                and target_track is source_track
                and abs(requested_frame - original_start_frame) <= 1
            ):
                new_start_frame = original_start_frame
            else:
                self._ripple_insert(target_track, requested_frame, duration_frames, exclude=clip)
                new_start_frame = requested_frame
            new_start_frame = max(0, int(new_start_frame))
            clip["start"] = new_start_frame / self.FPS
            target_track["clips"].append(clip)
            target_track["clips"].sort(key=lambda c: c["start"])

        clip["start"] = new_start_frame / self.FPS

        self.playhead = clip["start"]
        self.selected_clip = clip

        self._active_stack_signature = None
        self._prune_empty_tracks()
        self.rebuild(keep_view=True)
        self.select_clip(clip)
        self.time_changed.emit(self.playhead)
        self._emit_active_clips(self.playhead)
        return True

    def move_clip_to_track(
        self,
        drag_id: int,
        target_track: dict,
        requested_start: float,
    ) -> bool:
        """Compatibility wrapper using the single canonical move/insert path."""
        source_track, clip = self._find_clip_by_drag_id(drag_id)
        if clip is None or source_track is None:
            return False
        return self.move_clip_object(
            clip,
            target_track,
            requested_start,
            force_insert=True,
        )

    def show_track_context_menu(
        self,
        track: dict,
        global_pos,
    ):
        menu = QMenu(self)
        delete = menu.addAction(
            "Clear Main Layer" if track.get("is_main", False) else "Delete Layer"
        )
        hide = menu.addAction(
            "Show Layer" if track.get("hidden", False) else "Hide Layer"
        )
        lock = menu.addAction(
            "Unlock Layer" if track.get("locked", False) else "Lock Layer"
        )
        mute = menu.addAction(
            "Unmute Layer" if track.get("muted", False) else "Mute Layer"
        )
        volume = menu.addAction("Volume…")

        menu.addSeparator()
        add = menu.addAction("Add Empty Video Layer")

        action = menu.exec(global_pos)
        if action is None:
            return

        if action == delete:
            self._push_history()
            if track not in self.tracks:
                return

            if track.get("is_main", False):
                track["clips"].clear()
                self.selected_clip = None
                self.selection_cleared.emit()
            else:
                if self.selected_clip in track.get("clips", []):
                    self.selected_clip = None
                    self.selection_cleared.emit()
                self.tracks.remove(track)

            self._prune_empty_tracks()
            self._active_stack_signature = None
            self.rebuild(keep_view=True)
            self._emit_active_clips(self.playhead)
        elif action == hide:
            self.set_track_hidden(
                track,
                not bool(track.get("hidden", False)),
            )
        elif action == lock:
            self.set_track_locked(
                track,
                not bool(track.get("locked", False)),
            )
        elif action == mute:
            self.set_track_muted(
                track,
                not bool(track.get("muted", False)),
            )
        elif action == volume:
            current = float(track.get("volume", 1.0)) * 100.0
            value, ok = QInputDialog.getDouble(
                self,
                f"{track.get('name', 'Layer')} Volume",
                "Volume (%)",
                current,
                0.0,
                200.0,
                1,
            )
            if ok:
                self.set_track_volume(track, value / 100.0)
        elif action == add:
            self.add_empty_track("V")

    def _active_timeline_layers(self, seconds: float):
        frame = self.frame_from_seconds(seconds)
        active = []

        for row_index, track in enumerate(self.playback_tracks()):
            if track.get("hidden", False):
                continue

            for clip in track.get("clips", []):
                if (
                    self.clip_start_frame(clip)
                    <= frame
                    < self.clip_end_frame(clip)
                ):
                    clip_start = float(clip.get("start", 0.0))
                    clip_duration = float(clip.get("duration", 0.0))
                    source_in = float(clip.get("source_in", 0.0))
                    active.append(
                        {
                            "row": row_index,
                            "stack_order": float(track.get("_stack_order", row_index)),
                            "layer": track.get("name", ""),
                            "base": track.get("base", "V"),
                            "is_main": bool(track.get("is_main", False)),
                            "kind": clip.get("kind", "Video"),
                            "path": str(clip.get("path", "")),
                            "start": clip_start,
                            "duration": clip_duration,
                            "end": clip_start + clip_duration,
                            "source_in": source_in,
                            "local_time": max(0.0, source_in + float(seconds) - clip_start),
                            "frame": frame,
                            "clip_id": id(clip),
                            "visual_index": len(active),
                            "topmost_first": True,
                            "render_backend": self.render_backend,
                            "scale": float(clip.get("scale", 1.0)),
                            "position_x": float(clip.get("position_x", 0.0)),
                            "position_y": float(clip.get("position_y", 0.0)),
                            "position_z": float(clip.get("position_z", 0.0)),
                            "rotation": float(clip.get("rotation", 0.0)),
                            "opacity": float(clip.get("opacity", 1.0)),
                            "chroma_key_enabled": bool(clip.get("chroma_key_enabled", False)),
                            "chroma_key_color": str(clip.get("chroma_key_color", "#00FF00")),
                            "chroma_similarity": float(clip.get("chroma_similarity", 0.15)),
                            "chroma_blend": float(clip.get("chroma_blend", 0.05)),
                            "chroma_opacity": float(clip.get("chroma_opacity", 1.0)),
                            "volume": (
                                0.0
                                if track.get("muted", False) or clip.get("clip_muted", False)
                                else max(0.0, min(
                                    2.0,
                                    float(track.get("volume", 1.0))
                                    * float(clip.get("volume", 1.0)),
                                ))
                            ),
                            "muted": bool(track.get("muted", False) or clip.get("clip_muted", False)),
                        }
                    )

        # Lower stack_order means a visually newer/topmost video layer.
        # Keep this ordering stable so the PlayerPanel compositor can composite
        # without guessing which overlay should appear first.
        active.sort(
            key=lambda item: (
                float(item.get("stack_order", item.get("row", 0))),
                int(item.get("row", 0)),
            )
        )

        # The PlayerPanel receives this list in strict visual order:
        # index 0 = newest/topmost layer, last = lowest layer.
        for visual_index, item in enumerate(active):
            item["visual_index"] = visual_index
            item["z_index"] = -visual_index
            item["topmost_first"] = True

        return active

    def _emit_active_clips(
        self,
        seconds: float,
        push_to_player: bool = True,
    ):
        # IMPORTANT: this is the complete active project stack, not the selected
        # clip. Every visible/active video layer at this frame is forwarded.
        active = self._active_timeline_layers(seconds)

        # Keep the legacy SOURCE -> PROJECT clock mapping aligned with the
        # timeline without reloading or seeking the player.
        if not self._player_is_source_preview():
            self._prime_player_project_clock(seconds)

        # Publish current source-local time continuously. The PlayerPanel can
        # therefore advance every active layer without reloading its sources.
        self.active_clips_changed.emit(active)

        if not push_to_player:
            return

        engine = self._multitrack_engine
        if engine is not None and engine._ready:
            try:
                engine.set_active_layers(active)
                return
            except Exception:
                pass

        panel = getattr(self.window(), "player", None)
        setter = getattr(
            panel,
            "set_timeline_layers",
            None,
        ) if panel else None
        if callable(setter):
            try:
                setter(active, timeline=self)
            except TypeError:
                try:
                    setter(active)
                except Exception:
                    pass
            except Exception:
                pass

    def active_video_layers_at(self, seconds: float):
        return [
            item
            for item in self._active_timeline_layers(seconds)
            if item.get("base") == "V"
        ]

    def active_audio_layers_at(self, seconds: float):
        return [
            item
            for item in self._active_timeline_layers(seconds)
            if item.get("base") == "A"
        ]

    def project_preview_layers(self, seconds: float | None = None):
        value = self.playhead if seconds is None else float(seconds)
        return self._active_timeline_layers(
            self.snap_to_frame(value, self.FPS)
        )

    def _active_video_clip(self, seconds: float):
        frame = self.frame_from_seconds(seconds)
        for track in self.playback_tracks():
            if track.get("base") != "V" or track.get("hidden", False):
                continue
            for clip in sorted(
                track.get("clips", []),
                key=lambda c: self.clip_start_frame(c),
                reverse=True,
            ):
                if (
                    self.clip_start_frame(clip)
                    <= frame
                    < self.clip_end_frame(clip)
                ):
                    return track, clip
        return None, None

    def _set_player_volume_for_track(self, track):
        panel = getattr(self.window(), "player", None)
        if panel is None:
            return

        volume = max(
            0.0,
            min(2.0, float(track.get("volume", 1.0))),
        )
        normalized = 0.0 if track.get("muted", False) else min(1.0, volume)

        candidates = [panel]
        for name in (
            "preview",
            "_preview",
            "video",
            "_video_panel",
        ):
            obj = getattr(panel, name, None)
            if obj is not None:
                candidates.append(obj)

        for obj in candidates:
            for name in (
                "audio_output",
                "_audio_output",
                "audioOutput",
                "_audioOutput",
            ):
                output = getattr(obj, name, None)
                if output is not None and hasattr(output, "setVolume"):
                    try:
                        output.setVolume(normalized)
                        return
                    except Exception:
                        pass

    def _sync_active_clip_to_player(
        self,
        seconds: float,
    ):
        # Project playback is multi-layer by definition. The timeline sends
        # every active clip to the PlayerPanel instead of choosing one source.
        panel = getattr(
            self.window(),
            "player",
            None,
        )
        if panel is None:
            return

        active = self._active_timeline_layers(seconds)
        setter = getattr(
            panel,
            "set_timeline_layers",
            None,
        )

        if callable(setter):
            try:
                setter(active, timeline=self)
            except TypeError:
                try:
                    setter(active)
                except Exception:
                    pass
            except Exception:
                pass

        # Never let the legacy single-source clock own project time.
        self._active_player_clip_key = None
        self._switching_player = False



    # ========================================================
    # Editing actions
    # ========================================================

    def copy_selected(self):
        clip = self.selected_clip
        if clip is None:
            return
        self._clipboard_clip = copy.deepcopy(clip)

    def cut_selected(self):
        self.copy_selected()
        self.delete_selected()

    def duplicate_selected(self):
        clip = self.selected_clip
        track = self._find_selected_track()
        if clip is None or track is None or track.get("locked", False):
            return
        self._push_history()

        duplicate = copy.deepcopy(clip)
        duration = self.frame_duration(duplicate)
        start = self.clip_end_frame(clip) + 1

        # On a primary layer, keep the base lane contiguous where possible.
        if track.get("is_main", False):
            start = self.clip_end_frame(clip)

        start = self._nearest_free_start_frame(
            track,
            start,
            duration,
        )
        duplicate["start"] = start / self.FPS
        track["clips"].append(duplicate)
        track["clips"].sort(key=lambda c: c["start"])
        self.selected_clip = duplicate
        self.playhead = duplicate["start"]
        self.rebuild(keep_view=True)
        self.select_clip(duplicate)

    def toggle_clip_flag(self, key: str):
        clip = self.selected_clip
        track = self._find_selected_track()
        if clip is None or track is None or track.get("locked", False):
            return
        self._push_history()
        clip[key] = not bool(clip.get(key, False))
        self.rebuild(keep_view=True)
        self.select_clip(clip)

    def rotate_selected(self):
        clip = self.selected_clip
        track = self._find_selected_track()
        if clip is None or track is None or track.get("locked", False):
            return
        self._push_history()
        current = float(clip.get("rotation", 0.0))
        clip["rotation"] = (current + 90.0) % 360.0
        self.rebuild(keep_view=True)
        self.select_clip(clip)

    def toggle_clip_mute(self):
        clip = self.selected_clip
        track = self._find_selected_track()
        if clip is None or track is None or track.get("locked", False):
            return
        self._push_history()
        clip["clip_muted"] = not bool(clip.get("clip_muted", False))
        self._emit_active_clips(self.playhead)
        self.rebuild(keep_view=True)
        self.select_clip(clip)

    def copy_selected_attributes(self):
        clip = self.selected_clip
        if clip is None:
            return
        self._attribute_clipboard = {
            key: copy.deepcopy(clip.get(key))
            for key in (
                "scale", "position_x", "position_y", "rotation",
                "opacity", "reverse", "freeze", "mirror_x",
                "clip_muted",
            )
            if key in clip
        }

    def paste_selected_attributes(self):
        clip = self.selected_clip
        track = self._find_selected_track()
        attrs = getattr(self, "_attribute_clipboard", None)
        if clip is None or track is None or track.get("locked", False) or not attrs:
            return
        self._push_history()
        clip.update(copy.deepcopy(attrs))
        self._emit_active_clips(self.playhead)
        self.rebuild(keep_view=True)
        self.select_clip(clip)

    def open_selected_file_location(self):
        clip = self.selected_clip
        if clip is None:
            return
        path = Path(str(clip.get("path", ""))).resolve()
        if not path.exists():
            return
        try:
            subprocess.Popen(
                ["explorer.exe", "/select,", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    def _layer_gap_at_global_pos(self, global_pos):
        """Return the insertion gap currently under a clip-drag pointer, if any."""
        try:
            content = self.content
            point = content.mapFromGlobal(global_pos)
            for widget in getattr(content, "_row_widgets", []):
                if isinstance(widget, LayerInsertionGap) and widget.geometry().contains(point):
                    return widget
        except Exception:
            pass
        return None

    def _clear_clip_drag_preview(self):
        for widget in getattr(self, "_clip_drag_preview_widgets", []):
            try:
                widget.hide()
                widget.deleteLater()
            except RuntimeError:
                pass
        self._clip_drag_preview_widgets = []

    def _resolve_clip_drop_frame(self, target_track, global_pos, requested_frame, exclude_clip=None):
        """Resolve a drop over a clip to its exact start/end frame.

        This prevents clips being placed at arbitrary times inside another clip.
        The pointer's horizontal position chooses the boundary: left half inserts
        before, right half inserts after. Drops into empty timeline space retain
        the requested frame; ripple insertion then closes the next gap exactly.
        """
        if target_track is None or target_track.get("locked", False):
            return max(0, int(requested_frame)), False
        try:
            point = self.content.mapFromGlobal(global_pos)
            widgets = self.content.findChildren(ClipWidget)
        except Exception:
            return max(0, int(requested_frame)), False

        hits = []
        for widget in widgets:
            if not widget.isVisible() or widget.clip is exclude_clip:
                continue
            if widget.track is not target_track or widget.track.get("locked", False):
                continue
            top_left = widget.mapTo(self.content, QPoint(0, 0))
            rect = widget.rect().translated(top_left)
            if rect.contains(point):
                hits.append((rect.width(), widget, rect))
        if not hits:
            return max(0, int(requested_frame)), False

        # Prefer the narrowest hit if widgets happen to overlap visually.
        _width, widget, rect = min(hits, key=lambda item: item[0])
        frame = overlap_insert_boundary(
            self.clip_start_frame(widget.clip),
            self.clip_end_frame(widget.clip),
            point.x() - rect.left(),
            rect.width(),
        )
        return max(0, int(frame)), True

    def _update_clip_drag_preview(self, clip, target_track, requested_frame, global_pos):
        """Render a lightweight live preview of clip placement and ripple shifts."""
        self._clear_clip_drag_preview()
        gap = self._layer_gap_at_global_pos(global_pos)
        source_track = next((t for t in self.tracks if clip in t.get("clips", [])), None)
        if source_track is None:
            return
        content = self.content
        duration = max(1, self.frame_duration(clip))
        insert_frame = max(0, int(requested_frame))
        if gap is not None:
            y = gap.y() + max(0, (gap.height() - 26) // 2)
            preview = QLabel(content)
            preview.setText(f"＋  New {('Audio' if clip.get('kind') == 'Audio' else 'Overlay')} Layer  ·  {Path(str(clip.get('path',''))).name}")
            preview.setGeometry(self.time_to_x(insert_frame / self.FPS), y, max(160, min(320, self.time_to_x((insert_frame + duration) / self.FPS) - self.time_to_x(insert_frame / self.FPS))), 26)
            preview.setStyleSheet("QLabel{color:#E8FCFF;background:#12333A;border:1px dashed #00D8E8;border-radius:4px;font-size:9px;padding:3px;}")
            preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            preview.show(); preview.raise_()
            self._clip_drag_preview_widgets.append(preview)
            return
        if target_track is None or target_track.get("base") != source_track.get("base"):
            return
        affected = [
            other for other in target_track.get("clips", [])
            if other is not clip and (
                self.clip_start_frame(other) >= insert_frame
                or self.clip_end_frame(other) > insert_frame
            )
        ]
        shift = 0
        if affected:
            earliest = min(self.clip_start_frame(other) for other in affected)
            shift = (
                max(duration, insert_frame + duration - earliest)
                if earliest < insert_frame
                else insert_frame + duration - earliest
            )
        area = next((w for w in content.findChildren(TrackArea) if w.track is target_track), None)
        if area is None:
            return
        from .track_layout import clip_height
        row_top = area.y()
        row_h = area.height()
        h = clip_height(self, target_track)
        y = row_top + max(0, (row_h - h) // 2)

        if target_track.get("is_main", False):
            # Preview the same contiguous frame sequence that the commit path
            # will create. Do not use the overlay ripple-offset preview here:
            # its preserved gaps were the source of misleading drop feedback.
            ordered = sorted(
                [other for other in target_track.get("clips", []) if other is not clip],
                key=lambda other: self.clip_start_frame(other),
            )
            insert_index = len(ordered)
            for index, other in enumerate(ordered):
                if self.clip_start_frame(other) >= insert_frame:
                    insert_index = index
                    break
            cursor = 0
            for index, other in enumerate(ordered):
                if index == insert_index:
                    px1 = self.time_to_x(cursor / self.FPS)
                    px2 = self.time_to_x((cursor + duration) / self.FPS)
                    ghost = QLabel(content)
                    ghost.setText("  Insert  ")
                    ghost.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    ghost.setGeometry(px1, y, max(4, px2 - px1), h)
                    ghost.setStyleSheet("QLabel{color:#C5D0D7;background:rgba(65,76,86,150);border:1px dashed #7D8B96;border-radius:4px;font-size:9px;}")
                    ghost.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                    ghost.show(); ghost.raise_()
                    self._clip_drag_preview_widgets.append(ghost)
                    cursor += duration
                old_start = self.clip_start_frame(other)
                new_start = cursor
                if old_start != new_start:
                    px1 = self.time_to_x(new_start / self.FPS)
                    px2 = self.time_to_x((new_start + self.frame_duration(other)) / self.FPS)
                    shadow = QLabel(content)
                    shadow.setText("")
                    shadow.setGeometry(px1, y, max(4, px2 - px1), h)
                    shadow.setStyleSheet("QLabel{color:#C5D0D7;background:rgba(65,76,86,95);border:1px dashed #687782;border-radius:4px;font-size:9px;}")
                    shadow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                    shadow.show(); shadow.raise_()
                    self._clip_drag_preview_widgets.append(shadow)
                cursor += max(1, self.frame_duration(other))
            if insert_index == len(ordered):
                px1 = self.time_to_x(cursor / self.FPS)
                px2 = self.time_to_x((cursor + duration) / self.FPS)
                ghost = QLabel(content)
                ghost.setText("  Insert  ")
                ghost.setAlignment(Qt.AlignmentFlag.AlignCenter)
                ghost.setGeometry(px1, y, max(4, px2 - px1), h)
                ghost.setStyleSheet("QLabel{color:#C5D0D7;background:rgba(65,76,86,150);border:1px dashed #7D8B96;border-radius:4px;font-size:9px;}")
                ghost.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                ghost.show(); ghost.raise_()
                self._clip_drag_preview_widgets.append(ghost)
            return

        x1 = self.time_to_x(insert_frame / self.FPS)
        x2 = self.time_to_x((insert_frame + duration) / self.FPS)
        target_preview = QLabel(content)
        target_preview.setText("  Insert  ")
        target_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        target_preview.setGeometry(x1, y, max(4, x2-x1), h)
        target_preview.setStyleSheet("QLabel{color:#C5D0D7;background:rgba(65,76,86,150);border:1px dashed #7D8B96;border-radius:4px;font-size:9px;}")
        target_preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        target_preview.show(); target_preview.raise_()
        self._clip_drag_preview_widgets.append(target_preview)
        # Show where the clips that will be displaced are expected to land.
        for other in affected[:8]:
            other_start = self.clip_start_frame(other)
            new_start = other_start + shift
            ox1 = self.time_to_x(new_start / self.FPS)
            ox2 = self.time_to_x((new_start + self.frame_duration(other)) / self.FPS)
            displaced = QLabel(content)
            displaced.setText("")
            displaced.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            displaced.setGeometry(ox1, y, max(4, ox2-ox1), h)
            displaced.setStyleSheet("QLabel{color:#C5D0D7;background:rgba(65,76,86,95);border:1px dashed #687782;border-radius:4px;font-size:9px;}")
            displaced.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            displaced.show(); displaced.raise_()
            self._clip_drag_preview_widgets.append(displaced)

    def _update_external_drop_preview(self, path, kind, target_track, requested_frame):
        """Preview a file dropped between clips, including the ripple destinations."""
        self._clear_clip_drag_preview()
        if target_track is None or target_track.get("locked", False):
            return
        if target_track.get("base") != self._track_base_for_kind(kind):
            return
        key = (str(path), str(kind))
        preview_clip = self._external_preview_cache.get(key)
        if preview_clip is None:
            try:
                preview_clip = self._clip_from_media(Path(path).resolve(), kind, 0.0)
            except Exception:
                return
            self._external_preview_cache[key] = preview_clip
        duration = max(1, self.frame_duration(preview_clip))
        insert_frame = max(0, int(requested_frame))
        if target_track.get("is_main", False):
            area = next((w for w in self.content.findChildren(TrackArea) if w.track is target_track), None)
            if area is None:
                return
            from .track_layout import clip_height
            h = clip_height(self, target_track)
            y = area.y() + max(0, (area.height() - h) // 2)
            ordered = sorted(target_track.get("clips", []), key=lambda c: self.clip_start_frame(c))
            index = self._main_sequence_insert_index(target_track, insert_frame)
            cursor = 0
            for i, other in enumerate(ordered):
                if i == index:
                    x1 = self.time_to_x(cursor / self.FPS)
                    x2 = self.time_to_x((cursor + duration) / self.FPS)
                    ghost = QLabel(self.content)
                    ghost.setText("  + Insert into main sequence  ")
                    ghost.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    ghost.setGeometry(x1, y, max(5, x2 - x1), h)
                    ghost.setStyleSheet("QLabel{color:#C5CDD4;background:rgba(70,78,86,125);border:1px dashed #7D8790;border-radius:5px;font-size:9px;padding-left:3px;}")
                    ghost.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                    ghost.show(); ghost.raise_()
                    self._clip_drag_preview_widgets.append(ghost)
                    cursor += duration
                new_start = cursor
                old_start = self.clip_start_frame(other)
                if old_start != new_start:
                    px1 = self.time_to_x(new_start / self.FPS)
                    px2 = self.time_to_x((new_start + self.frame_duration(other)) / self.FPS)
                    shadow = QLabel(self.content)
                    shadow.setGeometry(px1, y, max(5, px2 - px1), h)
                    shadow.setStyleSheet("QLabel{background:rgba(92,101,110,85);border:1px dashed #707B84;border-radius:5px;}")
                    shadow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                    shadow.show(); shadow.raise_()
                    self._clip_drag_preview_widgets.append(shadow)
                cursor += self.frame_duration(other)
            if index == len(ordered):
                x1 = self.time_to_x(cursor / self.FPS)
                x2 = self.time_to_x((cursor + duration) / self.FPS)
                ghost = QLabel(self.content)
                ghost.setText("  + Append to main sequence  ")
                ghost.setAlignment(Qt.AlignmentFlag.AlignCenter)
                ghost.setGeometry(x1, y, max(5, x2 - x1), h)
                ghost.setStyleSheet("QLabel{color:#C5CDD4;background:rgba(70,78,86,125);border:1px dashed #7D8790;border-radius:5px;font-size:9px;padding-left:3px;}")
                ghost.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                ghost.show(); ghost.raise_()
                self._clip_drag_preview_widgets.append(ghost)
            return
        affected = [
            c for c in target_track.get("clips", [])
            if self.clip_start_frame(c) >= insert_frame or self.clip_end_frame(c) > insert_frame
        ]
        shift = 0
        if affected:
            earliest = min(self.clip_start_frame(c) for c in affected)
            shift = (
                max(duration, insert_frame + duration - earliest)
                if earliest < insert_frame
                else insert_frame + duration - earliest
            )
        area = next((w for w in self.content.findChildren(TrackArea) if w.track is target_track), None)
        if area is None:
            return
        from .track_layout import clip_height
        h = clip_height(self, target_track)
        y = area.y() + max(0, (area.height() - h) // 2)
        x1 = self.time_to_x(insert_frame / self.FPS)
        x2 = self.time_to_x((insert_frame + duration) / self.FPS)
        label = QLabel(self.content)
        label.setText(f"  + {Path(str(path)).name}")
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label.setGeometry(x1, y, max(5, x2-x1), h)
        label.setStyleSheet("QLabel{color:#E8FCFF;background:#00A9B522;border:2px dashed #00D8E8;border-radius:5px;font-size:9px;padding-left:4px;}")
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        label.show(); label.raise_()
        self._clip_drag_preview_widgets.append(label)
        for other in affected[:8]:
            old_start = self.clip_start_frame(other)
            new_start = max(old_start + shift, insert_frame + duration)
            ox1 = self.time_to_x(new_start / self.FPS)
            ox2 = self.time_to_x((new_start + self.frame_duration(other)) / self.FPS)
            displaced = QLabel(self.content)
            displaced.setText("  ↳ shifts")
            displaced.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            displaced.setGeometry(ox1, y, max(5, ox2-ox1), h)
            displaced.setStyleSheet("QLabel{color:#DFFBFF;background:#00D8E822;border:1px dashed #4DDDE8;border-radius:5px;font-size:9px;}")
            displaced.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            displaced.show(); displaced.raise_()
            self._clip_drag_preview_widgets.append(displaced)

    def move_clip_to_new_layer(self, clip, gap, requested_frame):
        """Move an existing clip to a newly inserted compatible layer slot."""
        source_track = next((t for t in self.tracks if clip in t.get("clips", [])), None)
        if source_track is None or source_track.get("locked", False):
            return False
        if clip.get("kind") == "Audio" and source_track.get("base") != "A":
            return False
        if source_track.get("is_main", False):
            first_main = min(source_track.get("clips", []), key=lambda c: self.clip_start_frame(c), default=None)
            if first_main is clip:
                return False
        before_tracks = set(id(t) for t in self.tracks)
        gap_index = int(getattr(gap, "display_gap_index", 0))
        before_track = getattr(gap, "before_track", None)
        requested_start = max(0, int(requested_frame)) / self.FPS
        # This call creates the layer at the exact insertion slot. We replace
        # its temporary media object with the original clip object so trims and
        # per-clip properties are retained.
        self.insert_media_as_new_layer(
            str(clip.get("path", "")), str(clip.get("kind", "Video")),
            requested_start, gap_index, before_track,
        )
        new_tracks = [t for t in self.tracks if id(t) not in before_tracks]
        target_track = next((t for t in new_tracks if t.get("base") == source_track.get("base")), None)
        if target_track is None:
            return False
        created = next((c for c in target_track.get("clips", []) if c.get("path") == clip.get("path")), None)
        if created is not None:
            target_track["clips"].remove(created)
        if clip in source_track.get("clips", []):
            source_track["clips"].remove(clip)
        clip["start"] = requested_start
        target_track["clips"].append(clip)
        target_track["clips"].sort(key=lambda c: c.get("start", 0.0))
        self._prune_empty_tracks()
        self._active_stack_signature = None
        self.rebuild(keep_view=True)
        self.select_clip(clip)
        self.time_changed.emit(self.playhead)
        self._emit_active_clips(self.playhead)
        return True

    def track_at_global_pos(self, global_pos, base=None):
        try:
            content = self.content
            point = content.mapFromGlobal(global_pos)
            y = float(point.y())
        except Exception:
            return None

        for track, top in self.track_row_positions():
            if base is not None and track.get("base") != base:
                continue
            if top <= y < top + self.TRACK_HEIGHT:
                return track
        return None

    def track_row_positions(self):
        # Use the exact geometry model rendered by the sidebar and timeline.
        from .track_layout import track_row_positions
        return track_row_positions(self)

    def _find_selected_track(self):
        if self.selected_clip is None:
            return None
        for track in self.tracks:
            if self.selected_clip in track["clips"]:
                return track
        return None

    def trim_selected_left(self):
        """Remove the selected clip's left portion up to the current playhead."""
        clip = self.selected_clip
        track = self._find_selected_track()
        if clip is None or track is None or track.get("locked", False):
            return

        start = self.clip_start_frame(clip)
        end = self.clip_end_frame(clip)
        target = self.frame_from_seconds(self.playhead)
        if target <= start or target >= end:
            return

        # Do not leave the trimmed clip overlapping an earlier clip on the
        # same track if the project already contains overlapping segments.
        for other in track.get("clips", []):
            if other is clip:
                continue
            other_start = self.clip_start_frame(other)
            other_end = self.clip_end_frame(other)
            if other_start < start and other_end > target:
                return

        source_in = self.frame_from_seconds(clip.get("source_in", 0.0))
        raw_source_duration = clip.get("source_duration")
        if is_freely_stretchable_clip(clip):
            raw_source_duration = None  # no intrinsic source length
        source_duration = (
            self.frame_from_seconds(raw_source_duration)
            if raw_source_duration is not None
            else None
        )
        trim_speed = max(0.1, min(8.0, float(clip.get("speed", 1.0))))
        result = left_trim_frames(start, end, target, source_in, source_duration, speed=trim_speed)
        if result is None:
            return
        new_start, new_source_in, new_duration = result

        self._push_history()
        old_clip_start_seconds = start / self.FPS
        clip["start"] = new_start / self.FPS
        clip["source_in"] = new_source_in / self.FPS
        clip["duration"] = new_duration / self.FPS
        try:
            from app.animation import trim_keyframes
            trim_keyframes(clip, old_clip_start_seconds, clip["start"], clip["duration"], fps=self.FPS)
        except Exception:
            pass
        if not is_freely_stretchable_clip(clip):
            clip["speed_source_duration"] = clip["duration"] * trim_speed
        self.rebuild(keep_view=True)
        self.time_changed.emit(self.playhead)
        self._emit_active_clips(self.playhead)

    def trim_selected_right(self):
        """Remove the selected clip's right portion from the playhead onward."""
        clip = self.selected_clip
        track = self._find_selected_track()
        if clip is None or track is None or track.get("locked", False):
            return

        start = self.clip_start_frame(clip)
        end = self.clip_end_frame(clip)
        target = self.frame_from_seconds(self.playhead)
        retained_duration = right_trim_frames(start, end, target)
        if retained_duration is None:
            return
        trim_speed = max(0.1, min(8.0, float(clip.get("speed", 1.0))))
        raw_source_duration = clip.get("source_duration")
        if raw_source_duration is not None and not is_freely_stretchable_clip(clip):
            source_total = self.frame_from_seconds(raw_source_duration)
            source_in_frame = self.frame_from_seconds(clip.get("source_in", 0.0))
            retained_duration = min(retained_duration, max(1, int((source_total-source_in_frame)/trim_speed)))

        # Don't trim through a following clip on the same track.
        for other in track.get("clips", []):
            if other is clip:
                continue
            other_start = self.clip_start_frame(other)
            if start < other_start < end and target > other_start:
                return

        self._push_history()
        old_clip_start_seconds = float(clip.get("start", 0.0))
        clip["duration"] = retained_duration / self.FPS
        try:
            from app.animation import trim_keyframes
            trim_keyframes(clip, old_clip_start_seconds, old_clip_start_seconds, clip["duration"], fps=self.FPS)
        except Exception:
            pass
        if not is_freely_stretchable_clip(clip):
            clip["speed_source_duration"] = clip["duration"] * trim_speed
        self.rebuild(keep_view=True)
        self.time_changed.emit(self.playhead)
        self._emit_active_clips(self.playhead)

    def split_selected(self):
        clip = self.selected_clip
        track = self._find_selected_track()
        if clip is None or track is None:
            return

        if track.get("locked", False):
            return

        start = self.clip_start_frame(
            clip
        )
        end = self.clip_end_frame(
            clip
        )
        split = self.frame_from_seconds(
            self.playhead
        )

        if split <= start or split >= end:
            return

        self._push_history()

        left_frames = split - start
        right_frames = end - split

        original_source_in = float(clip.get("source_in", 0.0))
        left_duration = left_frames / self.FPS
        right_duration = right_frames / self.FPS
        is_video_source = str(clip.get("kind", "")).lower() != "image"
        speed = max(0.5, min(5.0, float(clip.get("speed", 1.0))))
        source_offset = left_duration * speed

        left = dict(clip)
        left["duration"] = left_duration

        right = dict(clip)
        right["start"] = split / self.FPS
        right["duration"] = right_duration
        if clip.get("speed_mode") == "curve" and clip.get("speed_curve"):
            from app.animation import integrate_speed_to, integrate_speed_curve, split_speed_curve
            original_duration = max(1.0 / self.FPS, float(clip.get("duration", 1.0)))
            source_offset = integrate_speed_to(clip["speed_curve"], original_duration, left_duration, speed)
            left_curve, right_curve, _split_speed = split_speed_curve(clip["speed_curve"], original_duration, left_duration, speed)
            left["speed_curve"] = left_curve
            right["speed_curve"] = right_curve
            left["speed_mode"] = right["speed_mode"] = "curve"
            left["speed_source_duration"] = integrate_speed_curve(left_curve, left_duration, speed)
            right["speed_source_duration"] = integrate_speed_curve(right_curve, right_duration, speed)
        else:
            left["speed_source_duration"] = left_duration * speed
            right["speed_source_duration"] = right_duration * speed
        if is_video_source:
            right["source_in"] = original_source_in + source_offset
        else:
            right["source_in"] = original_source_in

        if clip.get("keyframes"):
            try:
                from app.animation import split_keyframes
                defaults = {k: v for k, v in clip.items() if isinstance(v, (int, float))}
                left["keyframes"], right["keyframes"] = split_keyframes(clip.get("keyframes", {}), left_duration, float(clip.get("duration", 0.0)), defaults)
            except Exception:
                pass
        index = track["clips"].index(
            clip
        )
        track["clips"][index:index + 1] = [
            left,
            right,
        ]

        self.selected_clip = right
        self.rebuild()
        self.select_clip(right)
        self.time_changed.emit(self.playhead)
        self._emit_active_clips(self.playhead)

    def delete_selected(self):
        clip = self.selected_clip
        track = self._find_selected_track()
        if clip is None or track is None:
            return

        if track.get("locked", False):
            return

        self._push_history()

        track["clips"].remove(
            clip
        )

        self.selected_clip = None
        self.selection_cleared.emit()
        self._prune_empty_tracks()
        self._active_stack_signature = None
        self.rebuild()
        self.time_changed.emit(self.playhead)
        self._emit_active_clips(self.playhead)

    # ========================================================
    # History
    # ========================================================

    def _snapshot(self):
        return copy.deepcopy(
            self.tracks
        )

    def _push_history(self):
        if self._history_restoring:
            return

        self._history.append(
            self._snapshot()
        )
        if len(self._history) > 50:
            self._history.pop(0)

        self._future.clear()

    def undo(self):
        if not self._history:
            return

        self._future.append(
            self._snapshot()
        )
        state = self._history.pop()

        self._history_restoring = True
        try:
            self.tracks = copy.deepcopy(
                state
            )
            self.selected_clip = None
            self.selection_cleared.emit()
            self.rebuild(
                keep_view=True
            )
        finally:
            self._history_restoring = False
        self._emit_active_clips(self.playhead)

    def redo(self):
        if not self._future:
            return

        self._history.append(
            self._snapshot()
        )
        state = self._future.pop()

        self._history_restoring = True
        try:
            self.tracks = copy.deepcopy(
                state
            )
            self.selected_clip = None
            self.selection_cleared.emit()
            self.rebuild(
                keep_view=True
            )
        finally:
            self._history_restoring = False
        self._emit_active_clips(self.playhead)

    def _set_layer_view_mode(self, mode: str):
        """Show overlay lanes, audio lanes, or both without changing playback."""
        mode = str(mode or "Both").strip().casefold()
        self.overlays_ui_visible = mode in ("both", "overlays")
        self.audio_ui_visible = mode in ("both", "audio")
        # Preserve the user's vertical scroll as much as possible while the
        # shared layer columns rebuild from the same view state.
        self.rebuild(keep_view=True)

    # ========================================================
    # Rebuild / resize
    # ========================================================

    def rebuild(
        self,
        keep_view: bool = True,
    ):
        old_scroll = 0
        old_vertical = 0

        if hasattr(
            self,
            "tracks_scroll",
        ):
            old_scroll = (
                self.tracks_scroll
                .horizontalScrollBar()
                .value()
            )
            old_vertical = (
                self.tracks_scroll
                .verticalScrollBar()
                .value()
            )

        # Whole-project adjustment lanes track the actual project duration but
        # never define that duration themselves (avoids a self-extending loop).
        project_duration = max(1.0 / self.FPS, self.duration())
        for track in self.tracks:
            for clip in track.get("clips", []):
                if clip.get("tool_type") == "Adjustments" and clip.get("scope") == "project":
                    clip["start"] = 0.0
                    clip["duration"] = project_duration
        self._built_top_pad = self.top_layer_drop_height()
        self.content.rebuild()
        self.sidebar_content.rebuild()
        self.edit_gutter_content.rebuild()

        width = self.content_width()

        self.content.setFixedWidth(
            width
        )
        self.ruler.setFixedWidth(
            width
        )

        self.content.updateGeometry()
        self.ruler.updateGeometry()
        self.ruler.update()

        self.sidebar_content.setFixedWidth(
            self.HEADER_WIDTH
        )
        # Vertical geometry (content heights of all three columns) is owned
        # by the scroll coordinator so there is exactly one height policy.
        self.content.setFixedHeight(self.layer_content_height())
        coordinator = getattr(self, "_scroll_coordinator", None)
        if coordinator is not None:
            coordinator.align_ranges()

        if keep_view:
            h = (
                self.tracks_scroll
                .horizontalScrollBar()
            )
            v = (
                self.tracks_scroll
                .verticalScrollBar()
            )

            h.setValue(
                max(
                    0,
                    min(
                        h.maximum(),
                        old_scroll,
                    ),
                )
            )
            v.setValue(
                max(
                    0,
                    min(
                        v.maximum(),
                        old_vertical,
                    ),
                )
            )
            self._sync_layer_scrolls(v.value())

        if (
            not getattr(self, "_vscroll_initialized", False)
            and any(t.get("clips") for t in self.tracks)
        ):
            self._vscroll_initialized = True
            vbar = self.tracks_scroll.verticalScrollBar()
            QTimer.singleShot(
                0, lambda: self._sync_layer_scrolls(vbar.maximum())
            )

        self._on_horizontal_scroll(
            self.tracks_scroll
            .horizontalScrollBar()
            .value()
        )

        QTimer.singleShot(
            0,
            lambda: self._sync_layer_scrolls(
                self.tracks_scroll
                .verticalScrollBar()
                .value()
            ),
        )

        self._move_marker()

    def closeEvent(self, event):
        engine = self._multitrack_engine
        if engine is not None:
            try:
                engine.shutdown()
            except Exception:
                pass
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)

        if not hasattr(
            self,
            "tracks_scroll",
        ):
            return

        if self._initial_scale_pending:
            QTimer.singleShot(
                0,
                self._apply_initial_scale,
            )
            return

        if self.zoom_slider.value() is None:
            return

        # The single-main-lane layout uses the available viewport height for
        # visual centering. Rebuild only the vertical columns here; horizontal
        # timing and zoom are preserved.
        self.reanchor_if_needed()

        old_ppf = max(
            0.0001,
            self.pixels_per_frame,
        )

        scroll = (
            self.tracks_scroll
            .horizontalScrollBar()
        )

        old_x = self.time_to_x(
            self.playhead
        )
        screen_x = (
            old_x - scroll.value()
        )

        if not (
            0 <= screen_x
            <= self._editor_viewport_width()
        ):
            screen_x = (
                self._editor_viewport_width()
                / 2.0
            )

        visible = self.visible_seconds_for_zoom(
            self.zoom_slider.value()
        )
        pps = self._editor_viewport_width() / max(
            0.001,
            visible,
        )

        self.pixels_per_second = pps
        self.pixels_per_frame = (
            pps / self.FPS
        )

        self._update_zoom_label(
            visible
        )

        self.rebuild(
            keep_view=False
        )

        new_x = self.time_to_x(
            self.playhead
        )

        desired = int(
            round(
                new_x - screen_x
            )
        )

        scroll.setValue(
            max(
                0,
                min(
                    scroll.maximum(),
                    desired,
                ),
            )
        )

        self._on_horizontal_scroll(
            scroll.value()
        )
        self._move_marker()
        QTimer.singleShot(
            0,
            self._align_layer_scroll_ranges,
        )
