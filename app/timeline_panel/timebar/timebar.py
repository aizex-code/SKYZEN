from __future__ import annotations

import math
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import QWidget

from ..core import COLORS


class TimeRuler(QWidget):
    """
    Clean physical-ruler style time axis.

    The important rule is that ticks are generated from exact 30-FPS frame
    positions, but we only draw the amount of detail that is useful at the
    current zoom. This prevents the old full-height "||||||||" appearance.
    """

    NICE_TIME_STEPS = (
        1.0, 5.0, 10.0, 15.0, 30.0, 60.0, 120.0,
        300.0, 600.0, 900.0, 1800.0, 3600.0,
    )

    def __init__(self, timeline: "TimelinePanel", parent=None):
        super().__init__(parent)
        self.timeline = timeline
        self.setFixedHeight(timeline.RULER_HEIGHT)
        self.setMouseTracking(True)
        self._preview_dragging = False
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    @staticmethod
    def _major_label(seconds: float) -> str:
        total = max(0, int(round(seconds)))
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    @classmethod
    def _nice_major_step(cls, pixels_per_second: float) -> float:
        pps = max(0.001, float(pixels_per_second))
        # Aim for roughly 85-125 px between labeled major marks.
        target_seconds = 100.0 / pps
        for step in cls.NICE_TIME_STEPS:
            if step * pps >= 82.0:
                return step
        return cls.NICE_TIME_STEPS[-1]

    def _minor_step(self, major_step: float, pixels_per_second: float) -> float:
        """
        Choose a ruler-like subdivision that remains visually separated.
        For example:
            30 s major -> 15 s medium -> 5 s minor
            10 s major -> 5 s medium  -> 1 s minor
        """
        pps = max(0.001, float(pixels_per_second))
        candidates = (
            major_step / 10.0,
            major_step / 5.0,
            major_step / 4.0,
            major_step / 2.0,
        )

        for step in candidates:
            if step <= 0:
                continue
            frames = max(1, int(round(step * self._fps())))
            actual = frames / float(self._fps())
            if actual * pps >= 10.0:
                return actual

        return max(1.0 / self._fps(), major_step / 2.0)

    def _fps(self) -> int:
        return int(self.timeline.FPS)

    def _set_playhead_from_x(self, x: float):
        self.timeline.set_playhead(
            self.timeline.x_to_time(x)
        )

    def _preview_marker_screen_x(self) -> float:
        if not self.timeline._concat_preview_axis or self.timeline.preview_time is None:
            return -99999.0
        try:
            scroll_x = self.timeline.tracks_scroll.horizontalScrollBar().value()
        except Exception:
            scroll_x = 0
        return self.timeline.time_to_x(self.timeline.preview_time) - scroll_x

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            x = float(event.position().x())
            if abs(x - self._preview_marker_screen_x()) <= 10.0:
                self._preview_dragging = True
                self.timeline.set_preview_marker(self.timeline.x_to_time(x))
                event.accept()
                return
            self.timeline.select_clip(None)
            self._set_playhead_from_x(x)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._preview_dragging and (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.timeline.set_preview_marker(
                self.timeline.x_to_time(float(event.position().x()))
            )
            event.accept()
            return
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._set_playhead_from_x(float(event.position().x()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._preview_dragging:
            self._preview_dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if self.timeline._scroll_timeline_wheel(event):
            return
        event.ignore()

    def _draw_tick(self, painter, x: int, height: int, tick_height: int, tone: str):
        if x < -2 or x > self.width() + 2:
            return
        painter.setPen(QPen(QColor(tone), 1))
        y0 = max(2, height - tick_height)
        painter.drawLine(x, y0, x, height - 1)

    def _draw_label(self, painter, x: int, text: str, y: int, width: int,
                    last_right: int | None, tone: str):
        # Prevent labels from touching/overlapping each other.
        left = x + 4
        right = left + width
        if last_right is not None and left < last_right + 8:
            return last_right
        painter.setPen(QPen(QColor(tone), 1))
        painter.drawText(
            QRectF(left, y, width, 12),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            text,
        )
        return right

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.fillRect(self.rect(), QColor("#171719"))

        ppf = max(0.0001, self.timeline.pixels_per_frame)
        pps = max(0.001, self.timeline.pixels_per_second)
        fps = int(self.timeline.FPS)
        max_frame = max(0, self.timeline.ruler_duration_frames())
        rect = event.rect()
        height = self.height()

        # A true physical-ruler look: ticks rise from the bottom only.
        # Full-height frame stripes are deliberately gone.
        visible_seconds = max(
            0.5,
            float(self.timeline.current_visible_seconds()),
        )

        # At very close zoom, switch to exact frame divisions.
        if ppf >= 5.5 or visible_seconds <= 6.0:
            # 1 second major marks, 5-frame medium marks, 1-frame minor marks.
            second_start = max(
                0,
                int(math.floor((rect.left() - 50) / pps)) - 1,
            )
            second_end = min(
                max_frame // fps + 1,
                int(math.ceil((rect.right() + 50) / pps)) + 1,
            )

            # Minor frame ticks; only draw as many as are actually distinguishable.
            frame_tick = 1
            if ppf < 9.0:
                frame_tick = 2
            if ppf < 6.5:
                frame_tick = 5

            first_frame = max(
                0,
                int(math.floor((rect.left() - 20) / ppf)) - 2,
            )
            last_frame = min(
                max_frame,
                int(math.ceil((rect.right() + 20) / ppf)) + 2,
            )

            # Minor/medium frame ticks.
            for frame in range(first_frame, last_frame + 1, frame_tick):
                x = int(round(frame * ppf))
                if frame % fps == 0:
                    continue
                if frame % 5 == 0:
                    self._draw_tick(
                        painter, x, height, 10, "#555C65"
                    )
                else:
                    self._draw_tick(
                        painter, x, height, 6, "#3C434B"
                    )

            font = QFont("Segoe UI")
            font.setPointSize(8)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)

            last_right = None
            # Second marks / labels.
            for second in range(second_start, second_end + 1):
                frame = second * fps
                if frame > max_frame:
                    break
                x = int(round(frame * ppf))
                self._draw_tick(
                    painter, x, height, 20, "#737B84"
                )
                last_right = self._draw_label(
                    painter,
                    x,
                    self._major_label(float(second)),
                    1,
                    64,
                    last_right,
                    COLORS["text"],
                )

            # Frame-number labels only when there is room for them.
            if ppf >= 12.0:
                label_every = 5 if ppf < 22.0 else 1
                label_last_right = None
                first = max(0, first_frame - (first_frame % label_every))
                for frame in range(first, last_frame + 1, label_every):
                    if frame % fps == 0 or frame > max_frame:
                        continue
                    x = int(round(frame * ppf))
                    label = f"{frame % fps}f"
                    label_last_right = self._draw_label(
                        painter,
                        x,
                        label,
                        18,
                        28,
                        label_last_right,
                        "#AEB7C1",
                    )

        else:
            # Wide views: choose clean "ruler" major/medium/minor intervals.
            major_step = self._nice_major_step(pps)
            medium_step = major_step / 2.0
            minor_step = self._minor_step(major_step, pps)

            major_frames = max(1, int(round(major_step * fps)))
            medium_frames = max(1, int(round(medium_step * fps)))
            minor_frames = max(1, int(round(minor_step * fps)))

            first_frame = max(
                0,
                int(math.floor((rect.left() - 60) / ppf)) - 2,
            )
            last_frame = min(
                max_frame,
                int(math.ceil((rect.right() + 60) / ppf)) + 2,
            )

            # Minor ticks first, excluding medium/major positions.
            start_minor = first_frame - (first_frame % minor_frames)
            for frame in range(
                start_minor,
                last_frame + 1,
                minor_frames,
            ):
                if frame % major_frames == 0 or frame % medium_frames == 0:
                    continue
                x = int(round(frame * ppf))
                self._draw_tick(
                    painter, x, height, 6, "#3A4149"
                )

            # Medium ticks.
            start_medium = first_frame - (first_frame % medium_frames)
            for frame in range(
                start_medium,
                last_frame + 1,
                medium_frames,
            ):
                if frame % major_frames == 0:
                    continue
                x = int(round(frame * ppf))
                self._draw_tick(
                    painter, x, height, 11, "#555D66"
                )

            # Major ticks + labels.
            font = QFont("Segoe UI")
            font.setPointSize(8)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)

            last_right = None
            first_major = first_frame - (first_frame % major_frames)
            for frame in range(
                first_major,
                last_frame + 1,
                major_frames,
            ):
                if frame > max_frame:
                    break
                x = int(round(frame * ppf))
                self._draw_tick(
                    painter, x, height, 20, "#737B84"
                )
                last_right = self._draw_label(
                    painter,
                    x,
                    self._major_label(
                        frame / float(fps)
                    ),
                    1,
                    72,
                    last_right,
                    COLORS["text"],
                )

        # Thin baseline, like a real ruler edge.
        painter.setPen(QPen(QColor("#343941"), 1))
        painter.drawLine(
            0,
            height - 1,
            self.width(),
            height - 1,
        )

        painter.end()


