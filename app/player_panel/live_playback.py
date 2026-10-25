"""Realtime timeline playback.

A single ordinary main-track clip uses Qt's native QMediaPlayer/QVideoWidget
path. Overlapping video layers use the shared QVideoSink compositor. Paused
scrubbing and final export are owned by separate video-engine modules.
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Qt
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink


class LiveMultitrackEngine(QObject):
    time_changed = Signal(float)
    finished = Signal()
    diagnostic = Signal(str)
    _frame_ready = Signal(int, object)

    def __init__(self, panel, parent=None):
        super().__init__(parent or panel)
        self.panel = panel
        self.view = panel.timeline_composite
        self.snapshot: dict = {}
        self._players: dict[int, dict] = {}
        self._playing = False
        self._closed = False
        self._anchor_wall = 0.0
        self._anchor_time = 0.0
        self._current_time = 0.0
        self._last_ui_emit = 0.0
        self._direct_mode = False
        self._direct_clip = None
        self._direct_path = ""
        self._direct_output_attached = False
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._frame_ready.connect(
            self._apply_video_frame, Qt.ConnectionType.QueuedConnection
        )
        # Direct single-clip playback may receive setSource before Qt has
        # finished loading; reapply the source in-point when the backend is ready.
        self.panel.player.mediaStatusChanged.connect(self._on_direct_media_status)

    @property
    def is_playing(self):
        return self._playing

    @property
    def direct_mode(self):
        return self._direct_mode

    def start(self, snapshot: dict, seconds: float = 0.0):
        if self._closed:
            return
        self._release_players()
        if self._direct_mode:
            try:
                self.panel.player.pause()
            except Exception:
                pass
        self.snapshot = snapshot
        self._anchor_time = max(0.0, float(seconds))
        self._current_time = self._anchor_time
        self._anchor_wall = time.monotonic()
        self._last_ui_emit = 0.0
        self._playing = True
        self._sync_active(self._current_time, force=True)
        self._timer.start()
        self.view.update()
        self.time_changed.emit(self._current_time)

    def seek(self, seconds: float):
        if not self._playing:
            return
        self._anchor_time = max(0.0, float(seconds))
        self._current_time = self._anchor_time
        self._anchor_wall = time.monotonic()
        self._sync_active(self._current_time, force=True)
        self.time_changed.emit(self._current_time)

    def stop(self, clear_view: bool = False):
        self._timer.stop()
        self._playing = False
        self._release_players()
        if self._direct_mode:
            try:
                self.panel.player.pause()
            except Exception:
                pass
        if clear_view:
            self._stop_direct(clear_source=True)
            self.view.clear()

    def shutdown(self):
        self._closed = True
        self.stop(clear_view=True)

    def _tick(self):
        if not self._playing or self._closed:
            return
        now = time.monotonic()
        seconds = self._anchor_time + max(0.0, now - self._anchor_wall)
        duration = max(0.0, float(self.snapshot.get("duration", 0.0)))
        if duration > 0 and seconds >= duration:
            self._current_time = duration
            self.stop(clear_view=False)
            self.time_changed.emit(duration)
            self.finished.emit()
            return

        self._current_time = seconds
        self._sync_active(seconds)
        if not self._direct_mode:
            self.view.update()
        if now - self._last_ui_emit >= 1.0 / 24.0:
            self._last_ui_emit = now
            self.time_changed.emit(seconds)

    @staticmethod
    def _active(clip: dict, seconds: float) -> bool:
        return float(clip.get("start", 0.0)) <= seconds < float(clip.get("end", 0.0))

    @staticmethod
    def _can_use_native_player(visual: list[dict]) -> bool:
        """Use native playback only for one untransformed main-track video."""
        if len(visual) != 1:
            return False
        clip = visual[0]
        if str(clip.get("kind", "Video")).lower() != "video":
            return False
        if clip.get("base") != "V" or not clip.get("is_main", False):
            return False
        # Native playback bypasses the compositor; clips with retiming or
        # animated properties must use the timeline decoder path instead.
        try:
            if abs(float(clip.get("speed", 1.0)) - 1.0) > 1e-6 or clip.get("speed_mode") == "curve" or clip.get("keyframes"):
                return False
            return (
                abs(float(clip.get("scale", 1.0)) - 1.0) < 0.001
                and abs(float(clip.get("opacity", 1.0)) - 1.0) < 0.001
                and abs(float(clip.get("position_x", 0.0))) < 0.001
                and abs(float(clip.get("position_y", 0.0))) < 0.001
                and abs(float(clip.get("rotation", 0.0))) < 0.001
            )
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _local_speed(clip: dict, seconds: float) -> float:
        local = max(0.0, min(float(clip.get("duration", 0.0)), float(seconds) - float(clip.get("start", 0.0))))
        speed = max(0.5, min(5.0, float(clip.get("speed", 1.0))))
        if str(clip.get("speed_mode", "constant")) == "curve" and clip.get("speed_curve"):
            try:
                from app.animation import evaluate_speed_curve
                return max(0.5, min(5.0, evaluate_speed_curve(clip["speed_curve"], clip.get("duration", 1.0), local, speed)))
            except Exception:
                return speed
        return speed

    @staticmethod
    def _expected_source_ms(clip: dict, seconds: float) -> int:
        local = max(0.0, min(float(clip.get("duration", 0.0)), float(seconds) - float(clip.get("start", 0.0))))
        source_offset = local * max(0.5, min(5.0, float(clip.get("speed", 1.0))))
        if str(clip.get("speed_mode", "constant")) == "curve" and clip.get("speed_curve"):
            try:
                from app.animation import integrate_speed_to
                source_offset = integrate_speed_to(clip["speed_curve"], clip.get("duration", 1.0), local, clip.get("speed", 1.0))
            except Exception:
                pass
        source_seconds = max(0.0, float(clip.get("source_in", 0.0)) + source_offset)
        return int(round(source_seconds * 1000.0))

    def _sync_active(self, seconds: float, force: bool = False):
        visual = [
            clip for clip in self.snapshot.get("visual", [])
            if self._active(clip, seconds)
        ]
        audio = [
            clip for clip in self.snapshot.get("audio", [])
            if self._active(clip, seconds)
            and float(clip.get("volume", 0.0)) > 0.0
        ]

        native_clip = visual[0] if self._can_use_native_player(visual) else None
        wanted: dict[int, dict] = {id(clip): clip for clip in audio}

        if native_clip is not None:
            self._activate_native_clip(native_clip, seconds, force=force)
            # The native QVideoWidget is faster and uses Qt's normal audio path.
            self.view.set_layers([])
            if self.panel.surface.currentWidget() is not self.panel.video:
                self.panel.surface.setCurrentWidget(self.panel.video)
        else:
            if self._direct_mode:
                self._stop_direct(clear_source=True)
            for clip in visual:
                if str(clip.get("kind", "Video")).lower() != "image":
                    wanted[id(clip)] = clip
            self.view.set_layers(visual)
            if self.panel.surface.currentWidget() is not self.view:
                self.panel.surface.setCurrentWidget(self.view)

        for key in list(self._players):
            if key not in wanted:
                self._release_one(key)

        for key, clip in wanted.items():
            state = self._players.get(key)
            if state is None:
                self._create_player(key, clip, seconds)
                continue
            # Do not continuously seek decoders to a wall-clock estimate.
            # That feedback loop caused repeated decoder flushes and audible
            # stutter on slower PCs. Seek only on an explicit timeline seek.
            if state.get("ready"):
                try:
                    desired_rate = self._local_speed(clip, seconds)
                    if abs(float(state.get("rate", 1.0)) - desired_rate) > 0.03:
                        state["player"].setPlaybackRate(desired_rate)
                        state["rate"] = desired_rate
                    if force:
                        state["player"].setPosition(self._expected_source_ms(clip, seconds))
                    if self._playing and state["player"].playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                        state["player"].play()
                except RuntimeError:
                    pass

    def _activate_native_clip(self, clip: dict, seconds: float, force: bool = False):
        path = str(clip.get("path", ""))
        if not Path(path).is_file():
            self.diagnostic.emit(f"Missing media during playback: {path}")
            return

        player = self.panel.player
        source = ""
        try:
            if player.source().isLocalFile():
                source = player.source().toLocalFile()
        except Exception:
            pass

        changed = (not self._direct_mode) or source != path or self._direct_path != path
        self._direct_mode = True
        self._direct_clip = clip
        self._direct_path = path

        try:
            if changed or not self._direct_output_attached:
                player.setVideoOutput(self.panel.video)
                self._direct_output_attached = True

            wanted_volume = max(0.0, min(1.0, float(clip.get("volume", 1.0))))
            try:
                if abs(float(self.panel.audio.volume()) - wanted_volume) > 0.001:
                    self.panel.audio.setVolume(wanted_volume)
            except Exception:
                self.panel.audio.setVolume(wanted_volume)

            try:
                player.setPlaybackRate(1.0)
            except Exception:
                pass
            if changed:
                player.stop()
                player.setSource(QUrl.fromLocalFile(path))
                player.setPosition(self._expected_source_ms(clip, seconds))
            elif force:
                player.setPosition(self._expected_source_ms(clip, seconds))
            if self._playing and player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                player.play()
        except Exception as exc:
            self.diagnostic.emit(f"Native video playback failed for {Path(path).name}: {exc}")

    def _on_direct_media_status(self, status):
        if not self._direct_mode or self._direct_clip is None or self._closed:
            return
        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            try:
                self.panel.player.setPosition(
                    self._expected_source_ms(self._direct_clip, self._current_time)
                )
                if self._playing and self.panel.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                    self.panel.player.play()
            except Exception as exc:
                self.diagnostic.emit(f"Could not start source clip: {exc}")
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.diagnostic.emit(
                f"Qt Multimedia could not decode: {self._direct_clip.get('path', '')}"
            )

    def _stop_direct(self, clear_source: bool):
        self._direct_mode = False
        self._direct_clip = None
        self._direct_path = ""
        self._direct_output_attached = False
        try:
            self.panel.player.pause()
            if clear_source:
                self.panel.player.stop()
                self.panel.player.setSource(QUrl())
            self.panel.audio.setVolume(1.0)
        except Exception:
            pass

    def _create_player(self, key: int, clip: dict, seconds: float):
        path = str(clip.get("path", ""))
        if not Path(path).is_file():
            self.diagnostic.emit(f"Missing media during playback: {path}")
            return

        player = QMediaPlayer(self)
        is_dedicated_audio = clip.get("base") == "A"
        is_main_video = clip.get("base") == "V" and bool(clip.get("is_main", False))
        requested_volume = max(0.0, min(1.0, float(clip.get("volume", 0.0))))
        # Overlay video sound is muted by default; only the main video's audio
        # and explicitly placed audio tracks are mixed during composite preview.
        volume = requested_volume if (is_dedicated_audio or is_main_video) else 0.0
        audio_output = None
        if volume > 0.0:
            audio_output = QAudioOutput(player)
            audio_output.setVolume(volume)
            player.setAudioOutput(audio_output)

        state = {
            "player": player,
            "audio": audio_output,
            "sink": None,
            "ready": False,
            "clip": clip,
            "rate": 1.0,
        }
        if clip.get("base") == "V" and str(clip.get("kind", "Video")).lower() != "image":
            sink = QVideoSink(player)
            state["sink"] = sink
            player.setVideoSink(sink)
            sink.videoFrameChanged.connect(
                lambda frame, clip_key=key: self._frame_ready.emit(clip_key, frame)
            )

        player.mediaStatusChanged.connect(
            lambda status, clip_key=key: self._on_media_status(clip_key, status)
        )
        player.errorOccurred.connect(
            lambda error, text, clip_key=key: self.diagnostic.emit(
                f"Media decoder error for {Path(path).name}: {text or error}"
            )
        )
        self._players[key] = state
        try:
            initial_rate = self._local_speed(clip, seconds)
            player.setPlaybackRate(initial_rate)
            state["rate"] = initial_rate
        except Exception:
            pass
        player.setSource(QUrl.fromLocalFile(path))
        if player.mediaStatus() in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            self._on_media_status(key, player.mediaStatus())

    def _on_media_status(self, key: int, status):
        state = self._players.get(key)
        if state is None or self._closed:
            return
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            state["ready"] = True
            state["player"].setPosition(
                self._expected_source_ms(state["clip"], self._current_time)
            )
            if self._playing:
                state["player"].play()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.diagnostic.emit(
                f"Qt Multimedia could not decode: {state['clip'].get('path', '')}"
            )

    def _apply_video_frame(self, key: int, frame):
        if self._closed or key not in self._players:
            return
        try:
            image = frame.toImage()
            if image.isNull():
                return
            # Bound per-frame copy and paint cost for 4K/large source videos.
            if image.width() > 1280 or image.height() > 720:
                image = image.scaled(
                    1280, 720,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            self.view.set_frame(key, image)
        except Exception as exc:
            self.diagnostic.emit(f"Could not compose video frame: {exc}")

    def _release_one(self, key: int):
        state = self._players.pop(key, None)
        if not state:
            return
        player = state.get("player")
        if player is not None:
            try:
                player.stop()
            except Exception:
                pass
            try:
                player.setSource(QUrl())
            except Exception:
                pass
            try:
                player.deleteLater()
            except Exception:
                pass

    def _release_players(self):
        for key in list(self._players):
            self._release_one(key)
