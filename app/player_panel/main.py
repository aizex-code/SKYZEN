from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from app.player_panel.preview_frame import PreviewFrameLabel
from app.player_panel.live_composite import LiveCompositeView

from PySide6.QtWidgets import (
    QFrame,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QProgressBar,
    QVBoxLayout,
    QWidget,
    QDialog,
)


class _HiddenProcessingIndicator:
    """No-op compatibility object for controller show()/hide() calls."""
    def show(self):
        return None

    def hide(self):
        return None


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".wmv"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}

class FullscreenPlayer(QDialog):
    """Separate top-level fullscreen preview. Main editor hierarchy is untouched."""

    def __init__(self, owner: "PlayerPanel"):
        super().__init__(None)
        self.owner = owner
        self.setWindowTitle("Skyzen — Fullscreen Preview")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setStyleSheet("""
            QDialog { background:#000000; color:#EEEEEE; }
            QPushButton {
                background:#2D2D2D; color:#EEEEEE;
                border:1px solid #2B3440; border-radius:5px;
                padding:0 12px; min-height:30px;
            }
            QPushButton:hover { border-color:#00D8E8; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.video = QVideoWidget()
        self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.video.setStyleSheet("background:#000000;")
        root.addWidget(self.video, 1)

        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setStyleSheet("background:#202020;")
        self.image.hide()
        self._image_source_pixmap = QPixmap()
        self._was_playing = False
        self._timeline_mode = False
        root.addWidget(self.image, 1)

        bottom = QFrame()
        bottom.setStyleSheet("QFrame{background:#252525; border-top:1px solid #3A3A3A;}")
        row = QHBoxLayout(bottom)
        row.setContentsMargins(12, 7, 12, 7)

        label = QLabel("Skyzen Preview")
        label.setStyleSheet("color:#00D8E8;")
        row.addWidget(label)
        row.addStretch()

        exit_button = QPushButton("Exit Fullscreen  •  Esc")
        exit_button.clicked.connect(self.close)
        row.addWidget(exit_button)

        root.addWidget(bottom, 0)

    def start(self):
        owner = self.owner
        self._timeline_mode = bool(owner.timeline_mode)
        engine = getattr(owner, "_multitrack_engine", None)
        self._was_playing = (
            owner.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            or bool(getattr(engine, "_playing", False))
            or bool(getattr(engine, "_pending_play", False))
        )

        if self._timeline_mode:
            # Fullscreen follows the project composite, never the selected source
            # clip. Opening fullscreen must not implicitly start playback.
            source_path = owner.player.source().toLocalFile()
            if source_path and Path(source_path).is_file():
                self.image.hide()
                self.video.show()
                owner.player.setVideoOutput(self.video)
                owner.player.play() if self._was_playing else owner.player.pause()
            else:
                self.video.hide()
                self.image.show()
                still = getattr(owner.timeline_still, "_source_pixmap", QPixmap())
                if not still.isNull():
                    self._set_pixmap(still)
                else:
                    self.image.setText("Preview is being prepared")
        elif owner.current_kind == "Video" and owner.current_path:
            self.image.hide()
            self.video.show()
            owner.player.setVideoOutput(self.video)
            owner.player.play() if self._was_playing else owner.player.pause()
        elif owner.current_kind == "Image" and owner.current_path:
            self.video.hide()
            self.image.show()
            self._set_image(owner.current_path)
        else:
            self.video.hide()
            self.image.show()
            self.image.setText("No preview")

        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def _set_image(self, path):
        pix = QPixmap(str(path))
        if not pix.isNull():
            self._set_pixmap(pix)

    def _set_pixmap(self, pixmap):
        self._image_source_pixmap = QPixmap(pixmap)
        self.image.setPixmap(
            self._image_source_pixmap.scaled(
                max(1, self.width() - 20),
                max(1, self.height() - 85),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event):
        if not self._image_source_pixmap.isNull():
            self._set_pixmap(self._image_source_pixmap)
        elif not self._timeline_mode and self.owner.current_kind == "Image" and self.owner.current_path:
            self._set_image(self.owner.current_path)
        super().resizeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        owner = self.owner
        if self._timeline_mode or owner.current_kind == "Video":
            owner.player.setVideoOutput(owner.video)
            if self._was_playing:
                owner.player.play()
            else:
                owner.player.pause()
            if self._timeline_mode:
                engine = getattr(owner, "_multitrack_engine", None)
                if bool(getattr(engine, "_render_playback_active", False)):
                    owner.surface.setCurrentWidget(owner.video)
                else:
                    owner.surface.setCurrentWidget(owner.timeline_still)
            else:
                owner.surface.setCurrentWidget(owner.video)
        self.video.deleteLater()
        super().closeEvent(event)



from app.audio_meter import PeakCache, project_level_db, MIN_DB
from app.audio_meter.widget import LevelMeter


class PlayerPanel(QFrame):
    def __init__(self, root_dir: Path, parent=None):
        super().__init__(parent)
        self.root_dir = root_dir
        self.current_path: Path | None = None
        self.current_kind = ""
        self.timeline_duration = 0.0
        self.timeline_time = 0.0
        self.timeline_mode = False
        self._source_released_for_timeline = False
        self.timeline_layers = []
        self._timeline = None
        self._multitrack_engine = None
        self.multitrack_error = ""

        self.setObjectName("Panel")

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 5, 6, 3)
        root.setSpacing(3)

        self.surface = QStackedWidget()
        self.surface.setStyleSheet(
            "QStackedWidget{background:#202020; border:1px solid #3A3A3A;}"
        )

        self.message = QLabel("Preview")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setStyleSheet("color:#929292; background:#202020;")
        self.surface.addWidget(self.message)

        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setStyleSheet("background:#202020;")
        self.surface.addWidget(self.image)

        # Paused project frames are rendered by FFmpeg in the background and
        # shown here. This avoids opening native decoders just to scrub/edit.
        self.timeline_still = PreviewFrameLabel()
        self.surface.addWidget(self.timeline_still)

        # Realtime timeline playback composites QVideoSink frames into one
        # canvas; the source-media preview keeps its separate QVideoWidget.
        self.timeline_composite = LiveCompositeView()
        self.surface.addWidget(self.timeline_composite)

        self.video = QVideoWidget()
        self.video.setStyleSheet("background:#202020;")
        self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.surface.addWidget(self.video)

        root.addWidget(self.surface, 1)

        # Preview preparation runs in the background; keep the player layout clean.
        self.processing_bar = _HiddenProcessingIndicator()

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(5)

        # CapCut-style order: compact vertical dB meter immediately BEFORE timecode.
        self.level_meter = LevelMeter()
        controls.addWidget(self.level_meter, 0, Qt.AlignmentFlag.AlignVCenter)

        self.time_label = QLabel("00:00:32:12 / 00:01:45:26")
        self.time_label.setMinimumWidth(155)
        self.time_label.setStyleSheet("color:#00D8E8; font-size:11px; font-variant-numeric:tabular-nums;")
        controls.addWidget(self.time_label)

        controls.addStretch()

        self.play_button = QToolButton()
        self.play_button.setText("▶")
        self.play_button.setToolTip("Play / Pause")
        self.play_button.setFixedSize(30, 27)
        self.play_button.clicked.connect(self.toggle_play)
        controls.addWidget(self.play_button)
        controls.addStretch()  # keeps Play/Pause centred like CapCut

        self.ratio_box = QComboBox()
        self.ratio_box.addItems(["Fit", "16:9", "9:16", "1:1", "4:3"])
        self.ratio_box.setCurrentText("Fit")
        self.ratio_box.setFixedSize(72, 27)
        self.ratio_box.setToolTip("Preview framing ratio; does not change project/export resolution")
        self.ratio_box.currentTextChanged.connect(self._set_preview_ratio)
        controls.addWidget(self.ratio_box)

        self.full_button = QToolButton()
        self.full_button.setText("⛶")
        self.full_button.setToolTip("Fullscreen preview")
        self.full_button.setFixedSize(30, 27)
        self.full_button.clicked.connect(self.toggle_fullscreen)
        controls.addWidget(self.full_button)

        root.addLayout(controls)

        self.audio = QAudioOutput()
        self.audio.setVolume(1.0)

        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self._source_position)
        self.player.durationChanged.connect(self._source_duration)
        self.player.playbackStateChanged.connect(self._state_changed)
        self.player.errorOccurred.connect(self._error)

        self._peak_cache = None
        self._meter_timer = QTimer(self)
        self._meter_timer.setInterval(33)
        self._meter_timer.timeout.connect(self._update_level_meter)
        self._meter_timer.start()

    def _peaks(self):
        if self._peak_cache is None:
            try:
                from app.timeline_panel.core import ffmpeg_path
                self._peak_cache = PeakCache(ffmpeg_path(self.root_dir))
            except Exception:
                self._peak_cache = PeakCache(None)
        return self._peak_cache

    def _update_level_meter(self):
        """Drive the dB meter from the project (or the source preview)."""
        engine = self._multitrack_engine
        if self.timeline_mode and engine is not None and getattr(engine, "_ready", False):
            playing = bool(getattr(engine, "_playing", False) or getattr(engine, "_pending_play", False))
        else:
            playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        db = MIN_DB
        self._meter_tick = getattr(self, "_meter_tick", 0) + 1
        if self._meter_tick % 30 == 1:
            # Pre-decode envelopes so the meter is live the moment Play starts.
            try:
                timeline = self._timeline or getattr(self.window(), "timeline", None)
                for track in (timeline.playback_tracks() if timeline else []):
                    for clip in track.get("clips", []):
                        if str(clip.get("kind", "")).lower() in ("video", "audio"):
                            source_time = max(0.0, float(clip.get("source_in", 0.0)))
                            self._peaks().amp_at(str(clip.get("path", "")), source_time)
            except Exception:
                pass
        if playing:
            try:
                timeline = self._timeline or getattr(self.window(), "timeline", None)
                cache = self._peaks()
                if (self.timeline_mode or self.timeline_layers) and timeline is not None:
                    db = project_level_db(
                        timeline.playback_tracks(), float(timeline.playhead), cache.amp_at
                    )
                elif self.current_path is not None and self.current_kind in ("Video", "Audio"):
                    gain = float(self.audio.volume())
                    amp = cache.amp_at(str(self.current_path), self.player.position() / 1000.0)
                    db = project_level_db(
                        [{"base": "V", "clips": [{
                            "kind": self.current_kind, "path": str(self.current_path),
                            "start": 0.0, "duration": 1e9, "volume": gain,
                        }]}],
                        self.player.position() / 1000.0,
                        lambda _p, _t, a=amp: a,
                    )
            except Exception:
                db = MIN_DB
        self.level_meter.set_level(db)

    def ensure_multitrack_engine(self, timeline=None):
        """Create the compositor on demand; never during application startup."""
        if timeline is not None:
            self._timeline = timeline
        if self._multitrack_engine is not None:
            return self._multitrack_engine
        timeline = self._timeline or getattr(self.window(), "timeline", None)
        if timeline is None:
            return None
        try:
            from .multitrack_engine import (
                MultitrackPlaybackEngine,
                QT_MULTITRACK_AVAILABLE,
            )
            if not QT_MULTITRACK_AVAILABLE:
                self.multitrack_error = "Qt multitrack video support is unavailable."
                return None
            engine = MultitrackPlaybackEngine(timeline, self, self.player)
            if not getattr(engine, "_ready", False):
                try:
                    engine.shutdown()
                except Exception:
                    pass
                self.multitrack_error = "Could not attach the multitrack preview surface."
                return None
            self._multitrack_engine = engine
            timeline._multitrack_engine = engine
            return engine
        except Exception as exc:
            self.multitrack_error = f"Multitrack preview unavailable: {exc}"
            try:
                print(self.multitrack_error)
            except Exception:
                pass
            return None

    def _release_source_preview_for_timeline(self):
        """Release the source-preview decoder before entering project playback.

        The source preview and timeline compositor must never hold active media
        sources simultaneously. Releasing the source once per transition avoids
        competing native decoders when the user starts adding overlays.
        """
        if getattr(self, "_source_released_for_timeline", False):
            return
        try:
            self.player.stop()
            self.player.setSource(QUrl())
        except Exception as exc:
            self.multitrack_error = f"Could not release source preview: {exc}"
        self._source_released_for_timeline = True

    def set_timeline_layers(self, active, timeline=None):
        """Receive the active timeline stack without replacing the project output."""
        if timeline is not None:
            self._timeline = timeline
        self.timeline_layers = [dict(item) for item in (active or [])]

        # Enter timeline mode even when the playhead is over a gap. Do not let
        # a timeline update switch the stacked widget back to the source player.
        self._release_source_preview_for_timeline()
        self.timeline_mode = True
        if self._timeline is not None:
            try:
                self.timeline_time = float(self._timeline.playhead)
                self.timeline_duration = float(self._timeline.project_end_seconds())
            except Exception:
                pass

        engine = self.ensure_multitrack_engine(self._timeline)
        if engine is None:
            self.message.setText(
                self.multitrack_error or "Timeline preview is unavailable."
            )
            self.surface.setCurrentWidget(self.message)
            self.update_timeline_time()
            return

        try:
            engine.set_active_layers(self.timeline_layers)
            live = getattr(engine, "_live_engine", None)
            if getattr(engine, "_playing", False):
                # Rendered composite playback uses the single native video output.
                # Keep the old live-engine surface choice only for compatibility.
                target = self.video if getattr(engine, "_render_playback_active", False) or (live is not None and live.direct_mode) else self.timeline_composite
                self.surface.setCurrentWidget(target)
            elif not self._timeline or not getattr(self._timeline, "tracks", None):
                self.message.setText("Drop media to start editing")
                self.surface.setCurrentWidget(self.message)
            else:
                # The controller owns paused-frame rendering and will replace
                # this placeholder when the current playhead frame is ready.
                self.surface.setCurrentWidget(self.timeline_still)
            self.multitrack_error = ""
        except Exception as exc:
            self.multitrack_error = f"Could not update timeline preview: {exc}"
            self.message.setText(self.multitrack_error)
            self.surface.setCurrentWidget(self.message)

        self.update_timeline_time()

    def _timeline_engine(self):
        engine = self._multitrack_engine
        if engine is None:
            engine = self.ensure_multitrack_engine()
        return engine if engine is not None and getattr(engine, "_ready", False) else None

    def show_asset(self, path: str, kind: str):
        p = Path(path).resolve()
        if not p.is_file():
            return

        # Switching back to browser/source preview must stop project playback
        # and remove any overlay layers left by the timeline compositor.
        engine = self._multitrack_engine
        if engine is not None:
            try:
                engine.clear_project()
            except Exception:
                try:
                    engine.pause()
                except Exception:
                    pass
        self.timeline_layers = []

        self.current_path = p
        self.current_kind = kind
        self.timeline_mode = False
        self._source_released_for_timeline = False

        if kind == "Image":
            self.player.stop()
            pix = QPixmap(str(p))
            if pix.isNull():
                self.message.setText(f"Unable to load:\n{p.name}")
                self.surface.setCurrentWidget(self.message)
                return
            self.image.setPixmap(
                pix.scaled(
                    self.surface.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.surface.setCurrentWidget(self.image)
            self.play_button.setText("▶")
            self.time_label.setText("00:00:00:00 / 00:00:00:00")
            return

        if kind in {"Video", "Audio"}:
            self.surface.setCurrentWidget(
                self.video if kind == "Video" else self.message
            )
            if kind == "Audio":
                self.message.setText(f"♫\n\n{p.name}\nAudio preview")
            self.player.stop()
            self.player.setSource(QUrl.fromLocalFile(str(p)))
            self.player.setPosition(0)
            # Selecting/importing media must never start playback implicitly.
            # Only the Play/Pause control (or Space shortcut) may start it.
            self.play_button.setText("▶")
            return

        self.message.setText(p.name)
        self.surface.setCurrentWidget(self.message)

    def show_timeline_clip(self, path: str, start: float, duration: float, kind: str):
        """Select a timeline clip without starting a competing source preview.

        Timeline selection is not a Play command. The compositor must remain
        visible and the project playhead—not the selected clip's start—defines
        which clips are rendered in the preview.
        """
        p = Path(path)
        if not p.is_file():
            return

        self.current_path = p
        self.current_kind = kind
        self._release_source_preview_for_timeline()
        self.timeline_mode = True

        timeline = self._timeline or getattr(self.window(), "timeline", None)
        if timeline is not None:
            self._timeline = timeline
            try:
                self.timeline_time = max(0.0, float(timeline.playhead))
                self.timeline_duration = max(0.0, float(timeline.project_end_seconds()))
            except Exception:
                self.timeline_time = max(0.0, float(start))
                self.timeline_duration = max(0.0, float(duration))

        # Never run the legacy one-source player when selecting a project clip.
        # Doing so used to replace the composite preview with the selected clip
        # and briefly play its audio on top of the multitrack engine.
        try:
            self.player.pause()
        except Exception:
            pass

        engine = self.ensure_multitrack_engine(timeline)
        if engine is None:
            detail = self.multitrack_error or "Multitrack preview is unavailable."
            self.message.setText(detail)
            self.surface.setCurrentWidget(self.message)
            self.update_timeline_time()
            return

        try:
            active = timeline._active_timeline_layers(self.timeline_time)
            self.timeline_layers = [dict(item) for item in active]
            live = getattr(engine, "_live_engine", None)
            was_playing = bool(getattr(engine, "_playing", False) or getattr(engine, "_pending_play", False))
            engine.seek(self.timeline_time, resume=was_playing)
            if was_playing:
                target = self.video if getattr(engine, "_render_playback_active", False) or (live is not None and live.direct_mode) else self.timeline_composite
                self.surface.setCurrentWidget(target)
            else:
                # Paused frame rendering belongs to the controller. Never
                # expose an empty composite canvas while a frame is pending.
                self.surface.setCurrentWidget(self.timeline_still)
        except Exception as exc:
            self.multitrack_error = f"Could not preview timeline: {exc}"
            self.message.setText(self.multitrack_error)
            self.surface.setCurrentWidget(self.message)

        self.update_timeline_time()

    def _pause_first_frame(self):
        if self.timeline_mode:
            self.player.pause()

    def toggle_play(self):
        if self.current_kind == "Image" and not self.timeline_mode and not self.timeline_layers:
            return

        if self.timeline_mode or self.timeline_layers:
            engine = self._timeline_engine()
            if engine is not None:
                engine.toggle_play()
                return
            if self.multitrack_error:
                self.message.setText(self.multitrack_error)
                self.surface.setCurrentWidget(self.message)
            return

        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _set_preview_ratio(self, ratio: str):
        """Set preview presentation mode only; never mutate project resolution."""
        self._preview_ratio = str(ratio or "Fit")
        # Qt's native video surface supports fit vs stretch. Fixed ratios remain
        # a framing preference for the preview surface and are consumed by the
        # canvas layout when it is resized; do not touch render/export settings.
        try:
            if self._preview_ratio == "Fit":
                self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
            else:
                self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
            self.surface.setProperty("skyzen_preview_ratio", self._preview_ratio)
            self.surface.updateGeometry()
            self.surface.update()
        except (AttributeError, RuntimeError):
            pass

    def toggle_fullscreen(self):
        existing = getattr(self, "_fullscreen_window", None)
        if existing is not None and existing.isVisible():
            existing.close()
            return

        if not self.current_path:
            return

        self._fullscreen_window = FullscreenPlayer(self)
        self._fullscreen_window.finished.connect(
            lambda _result: setattr(self, "_fullscreen_window", None)
        )
        self._fullscreen_window.start()


    def seek_timeline(self, seconds: float):
        self.timeline_time = max(0.0, float(seconds))
        if self.timeline_mode or self.timeline_layers:
            engine = self._timeline_engine()
            if engine is not None:
                try:
                    engine.seek(self.timeline_time, resume=bool(engine._playing or getattr(engine, "_pending_play", False)))
                except Exception as exc:
                    self.multitrack_error = f"Timeline seek failed: {exc}"
            self.update_timeline_time()
            return

        if self.current_kind == "Video" and self.current_path and self.player.source().isLocalFile():
            self.player.setPosition(max(0, int(self.timeline_time * 1000)))
        self.update_timeline_time()

    def update_timeline_time(self):
        self.time_label.setText(
            f"{self.format_time(self.timeline_time)} / "
            f"{self.format_time(self.timeline_duration)}"
        )

    def _source_position(self, position_ms: int):
        if not self.timeline_mode:
            total = max(0, self.player.duration())
            self.time_label.setText(
                f"{self.format_time(position_ms / 1000)} / "
                f"{self.format_time(total / 1000)}"
            )

    def _source_duration(self, duration_ms: int):
        if not self.timeline_mode:
            self.time_label.setText(
                f"{self.format_time(self.player.position() / 1000)} / "
                f"{self.format_time(duration_ms / 1000)}"
            )

    def _state_changed(self, state):
        engine = self._multitrack_engine
        if self.timeline_mode and engine is not None and getattr(engine, "_ready", False):
            playing = bool(getattr(engine, "_playing", False))
        else:
            playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setText("❚❚" if playing else "▶")

    def _error(self, _error):
        if self.current_path:
            self.message.setText(
                f"Player could not open:\n{self.current_path.name}"
            )
            self.surface.setCurrentWidget(self.message)

    @staticmethod
    def format_time(seconds: float) -> str:
        frames = int(round(max(0.0, float(seconds)) * 30))
        fps = 30
        h, rem = divmod(frames, fps * 3600)
        m, rem = divmod(rem, fps * 60)
        s, f = divmod(rem, fps)
        return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"

    def resizeEvent(self, event):
        if self.current_path and self.current_kind == "Image":
            pix = QPixmap(str(self.current_path))
            if not pix.isNull():
                self.image.setPixmap(
                    pix.scaled(
                        self.surface.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        super().resizeEvent(event)
