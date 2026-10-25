"""Timeline preview controller.

The editable timeline is authoritative. FFmpeg creates a cached low-resolution
composite for synchronized project playback; Qt plays that single file so all
video layers and mixed audio share one playback clock. Paused frames are rendered
separately, and final export remains separate.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QMediaPlayer

from .project_snapshot import build_snapshot, project_fingerprint
from .render_worker import RenderWorker
from . import preview_profile


class ProjectPreviewController(QObject):
    """Compatibility adapter used by PlayerPanel and TimelinePanel."""

    def __init__(self, timeline, panel, master_media):
        super().__init__(panel)
        self.timeline = timeline
        self.panel = panel
        self.player = master_media
        self._view = getattr(panel, "timeline_composite", getattr(panel, "video", None))
        self._ready = True
        self._playing = False
        self._render_playback_active = False
        self._snapshot = build_snapshot(timeline, use_proxies=preview_profile.USE_PROXIES)
        self._fingerprint = project_fingerprint(timeline)
        self._signature = self._snapshot["signature"]
        self._rendered_signature = ""
        self._rendered_path = ""
        self._worker = None
        self._worker_mode = ""
        self._token = 0
        self._desired_frame_time = max(0.0, float(getattr(timeline, "playhead", 0.0)))
        self._pending_project_render = False
        self._proxy_refresh_pending = False
        self._pending_play = False
        self._pending_seek = None
        self._closed = False
        self._cache_dir = Path(tempfile.gettempdir()) / "Skyzen" / "preview_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._prune_cache()
        self._last_frame_number = -1
        self._last_frame_signature = ""
        # One playback owner only: the rendered project composite is played by
        # this controller's QMediaPlayer. The older per-clip QVideoSink engine
        # remains in the package for reference, but is deliberately not started
        # or attached here; two competing clocks/decoder paths made playback flaky.
        self._live_engine = None

        self._frame_debounce = QTimer(self)
        self._frame_debounce.setSingleShot(True)
        self._frame_debounce.setInterval(110)
        self._frame_debounce.timeout.connect(self._start_latest_frame)

        # Prebuild the composite after edits settle, off the UI thread, so Play
        # can usually reuse a ready preview instead of waiting to render it.
        self._project_prefetch_timer = QTimer(self)
        self._project_prefetch_timer.setSingleShot(True)
        self._project_prefetch_timer.setInterval(450)
        self._project_prefetch_timer.timeout.connect(self._start_project_render)

        try:
            self.player.positionChanged.connect(self._on_position_changed)
            self.player.playbackStateChanged.connect(self._on_playback_state_changed)
            self.player.mediaStatusChanged.connect(self._on_media_status_changed)
        except Exception:
            pass

    @property
    def project_time(self):
        # Source position is not project position when a clip has a source
        # in-point. The live engine owns the timeline clock in project mode.
        if getattr(self, "_render_playback_active", False) and self._playing:
            try:
                return max(0.0, float(self.player.position()) / 1000.0)
            except Exception:
                pass
        return max(0.0, float(getattr(self.timeline, "playhead", 0.0)))

    def set_active_layers(self, _active):
        """Timeline compatibility slot; rebuild snapshots only after real edits."""
        if self._closed:
            return
        try:
            fingerprint = project_fingerprint(self.timeline)
        except Exception as exc:
            self._log(f"Could not fingerprint project timeline: {exc}")
            return

        old_signature = self._signature
        if fingerprint != self._fingerprint:
            try:
                latest = build_snapshot(self.timeline, use_proxies=preview_profile.USE_PROXIES)
            except Exception as exc:
                self._log(f"Could not read project timeline: {exc}")
                return
            self._fingerprint = fingerprint
            self._snapshot = latest
            self._signature = latest["signature"]
            self._desired_frame_time = max(0.0, float(getattr(self.timeline, "playhead", 0.0)))

            if self._signature != old_signature:
                # Cancel obsolete full-project composites so a slow render cannot
                # block feedback for the newest inspector adjustment.
                worker = self._worker
                if (
                    worker is not None and worker.isRunning()
                    and getattr(worker, "snapshot", {}).get("signature") != self._signature
                ):
                    # Cancel stale still-frame renders too. Otherwise a slow
                    # frame for the previous slider value can occupy the only
                    # render slot and make the newest adjustment feel delayed.
                    worker.cancel()

                if not latest["clips"]:
                    self.pause()
                    self._render_playback_active = False
                    self._rendered_signature = ""
                    self._rendered_path = ""
                    self._pending_play = False
                    self._pending_project_render = False
                    self._frame_debounce.stop()
                    try:
                        self.player.stop()
                        self.player.setSource(QUrl())
                    except Exception:
                        pass
                    self._show_empty()
                    return

                was_playing = bool(self._playing or self._pending_play)
                old_composite_is_available = bool(
                    self._rendered_path and Path(self._rendered_path).is_file()
                )
                self._pending_project_render = False

                if was_playing and old_composite_is_available:
                    # Keep the current composite playing smoothly while the new
                    # graded/adjusted version renders in the background. The
                    # playhead continues to advance; the updated composite swaps
                    # in at the latest project time when ready.
                    self._pending_play = True
                    self._render_playback_active = True
                    self._frame_debounce.stop()
                elif was_playing:
                    # Play was requested but no usable composite exists yet.
                    # Preserve the request and prioritize the project render.
                    self._pending_play = True
                    self._render_playback_active = False
                    self._rendered_signature = ""
                    self._rendered_path = ""
                    self._frame_debounce.stop()
                else:
                    self._render_playback_active = False
                    self._rendered_signature = ""
                    self._rendered_path = ""
                    self._pending_play = False
                    self._frame_debounce.start()

                self._project_prefetch_timer.start()
                return
            # Empty track creation/removal may change the fingerprint without
            # changing the rendered project; no re-render is required.

        self._desired_frame_time = max(0.0, float(getattr(self.timeline, "playhead", 0.0)))
        if not self._playing:
            frame_number = round(self._desired_frame_time * int(self._snapshot["fps"]))
            if frame_number != self._last_frame_number or self._last_frame_signature != self._signature:
                self._frame_debounce.start()

    def refresh_sources(self):
        """Refresh preview source paths after optional import proxies finish."""
        if self._closed:
            return
        if self._worker is not None and self._worker.isRunning():
            self._proxy_refresh_pending = True
            return
        try:
            latest = build_snapshot(self.timeline, use_proxies=preview_profile.USE_PROXIES)
        except Exception as exc:
            self._log(f"Could not refresh proxy sources: {exc}")
            return
        if latest.get("signature") == self._signature:
            return
        if self._playing:
            self.pause()
        worker = self._worker
        if (
            worker is not None and worker.isRunning()
            and getattr(worker, "snapshot", {}).get("signature") != latest.get("signature")
        ):
            worker.cancel()
        self._snapshot = latest
        self._signature = latest["signature"]
        self._fingerprint = project_fingerprint(self.timeline)
        self._rendered_signature = ""
        self._rendered_path = ""
        self._pending_play = False
        self._pending_project_render = False
        self._last_frame_number = -1
        if self._snapshot["clips"]:
            self._frame_debounce.start()
            self._project_prefetch_timer.start()
        else:
            self._project_prefetch_timer.stop()
            self._show_empty()

    def _prune_cache(self, max_bytes=1024 * 1024 * 1024):
        """Keep preview artifacts bounded so repeated edits cannot fill the disk."""
        try:
            files = [
                path for path in self._cache_dir.iterdir()
                if path.is_file() and path.suffix.lower() in (".mp4", ".png")
            ]
            total = sum(path.stat().st_size for path in files)
            for path in sorted(files, key=lambda item: item.stat().st_mtime):
                if total <= max_bytes:
                    break
                size = path.stat().st_size
                # Never remove the preview currently bound to the player.
                if str(path) == self._rendered_path:
                    continue
                path.unlink(missing_ok=True)
                if path.suffix.lower() == ".mp4":
                    path.with_suffix(".ok").unlink(missing_ok=True)
                total -= size
        except (OSError, PermissionError):
            pass

    def _cache_project_path(self, signature):
        return self._cache_dir / f"project-{preview_profile.PREVIEW_PROFILE_ID}-{signature}.mp4"

    def _cache_frame_path(self, signature, seconds):
        frame = round(max(0.0, seconds) * int(self._snapshot["fps"]))
        return self._cache_dir / f"frame-{preview_profile.PREVIEW_PROFILE_ID}-{signature}-{frame}.png"

    def _start_latest_frame(self):
        if self._closed or self._playing or not self._snapshot["clips"]:
            return
        if self._worker is not None and self._worker.isRunning():
            # Keep only the latest scrub position; the completed worker will
            # schedule this frame rather than launching many FFmpeg processes.
            return
        seconds = max(0.0, float(self._desired_frame_time))
        frame_number = round(seconds * int(self._snapshot["fps"]))
        path = self._cache_frame_path(self._signature, seconds)
        if path.is_file() and path.stat().st_size > 0:
            cached_pixmap = QPixmap(str(path))
            if not cached_pixmap.isNull():
                self._show_still(str(path), frame_number)
                return
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        # Keep the last good frame visible while the replacement frame renders.
        # Switching to a full-screen loading message for every slider tick made
        # interactive adjustments impossible to judge. Only show the placeholder
        # when there is no usable preview yet.
        try:
            current = self.panel.surface.currentWidget()
        except Exception:
            current = None
        if current is self.panel.message and self._last_frame_signature == "":
            self.panel.message.setText("Preparing preview frame…")
        self._start_worker("frame", str(path), seconds)

    def _start_project_render(self):
        if self._closed:
            return
        if not self._snapshot["clips"]:
            self._show_empty()
            return
        # Do not inspect/delete a cache output while FFmpeg may still be
        # writing it. If this exact project is already rendering, let that
        # worker finish; otherwise queue a project render behind a frame job.
        if self._worker is not None and self._worker.isRunning():
            worker_snapshot = getattr(self._worker, "snapshot", {})
            if self._worker_mode == "project" and worker_snapshot.get("signature") == self._signature:
                return
            self._pending_project_render = True
            return

        self._prune_cache()
        cached = self._cache_project_path(self._signature)
        marker = cached.with_suffix(".ok")
        if cached.is_file() and cached.stat().st_size > 0 and marker.is_file():
            self._rendered_signature = self._signature
            self._rendered_path = str(cached)
            self._activate_project_preview(autoplay=self._pending_play)
            return
        if cached.exists() and not marker.exists():
            try:
                cached.unlink(missing_ok=True)
            except OSError:
                pass
        self._pending_project_render = False
        self._start_worker("project", str(cached), self._desired_frame_time)

    def _start_worker(self, mode, output, seconds):
        if self._worker is not None and self._worker.isRunning():
            return
        self._token += 1
        worker = RenderWorker(
            self._token, mode, self._snapshot, output,
            str(getattr(self.timeline, "root_dir", Path.cwd())),
            seconds, self,
        )
        self._worker = worker
        self._worker_mode = mode
        worker.succeeded.connect(self._on_render_succeeded)
        worker.failed.connect(self._on_render_failed)
        worker.finished.connect(self._on_worker_finished)
        worker.start()

    def _on_render_succeeded(self, token, mode, signature, path, seconds):
        if self._closed or int(token) != self._token or signature != self._signature:
            return
        if mode == "frame":
            rendered_frame = round(float(seconds) * int(self._snapshot["fps"]))
            desired_frame = round(self._desired_frame_time * int(self._snapshot["fps"]))
            if rendered_frame == desired_frame:
                self._show_still(path, rendered_frame)
        elif mode == "project":
            try:
                self.panel.processing_bar.hide()
            except Exception:
                pass
            try:
                Path(path).with_suffix(".ok").write_text(signature, encoding="utf-8")
            except OSError as exc:
                self._log(f"Could not mark preview cache complete: {exc}")
            self._rendered_signature = signature
            self._rendered_path = path
            self._activate_project_preview(autoplay=self._pending_play)

    def _on_render_failed(self, token, mode, signature, diagnostic, seconds):
        if self._closed or int(token) != self._token or signature != self._signature:
            return
        self._log(f"{mode} preview render failed: {diagnostic}")
        self.panel.multitrack_error = str(diagnostic)
        if mode == "project":
            try:
                self.panel.processing_bar.hide()
            except Exception:
                pass
        if mode == "frame":
            # Don't leave a black preview with no explanation, and don't retry
            # the same failed frame continuously.
            self._last_frame_number = round(float(seconds) * int(self._snapshot["fps"]))
            self.panel.message.setText(
                "Could not render this preview frame.\n"
                "Check FFmpeg and the source media.\n\n"
                + str(diagnostic)[-500:]
            )
            self.panel.surface.setCurrentWidget(self.panel.message)
        elif mode == "project":
            self._pending_play = False
            self._playing = False
            self._render_playback_active = False
            self.panel.play_button.setText("▶")
            self.panel.message.setText(
                "Could not build project preview.\n"
                "Check FFmpeg and the media files.\n\n"
                + str(diagnostic)[-700:]
            )
            self.panel.surface.setCurrentWidget(self.panel.message)
        elif signature == self._signature:
            self.panel.message.setText("Frame preview unavailable. Check FFmpeg and the selected media.")
            self.panel.message.setToolTip(str(diagnostic))
            self.panel.surface.setCurrentWidget(self.panel.message)

    def _on_worker_finished(self):
        worker = self._worker
        self._worker = None
        self._worker_mode = ""
        if worker is not None:
            worker.deleteLater()
        if self._closed:
            return
        if self._proxy_refresh_pending:
            self._proxy_refresh_pending = False
            self.refresh_sources()
            return
        if self._pending_project_render:
            self._pending_project_render = False
            self._start_project_render()
        elif not self._playing and self._snapshot["clips"]:
            wanted = round(self._desired_frame_time * int(self._snapshot["fps"]))
            if wanted != self._last_frame_number or self._last_frame_signature != self._signature:
                self._frame_debounce.start()

    def _show_still(self, path, frame_number):
        if self._closed or self._playing:
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        label = getattr(self.panel, "timeline_still", None)
        if label is None:
            return
        label.set_source_pixmap(pixmap)
        self.panel.surface.setCurrentWidget(label)
        self._last_frame_number = int(frame_number)
        self._last_frame_signature = self._signature
        self.panel.timeline_time = self._desired_frame_time
        try:
            self.panel.update_timeline_time()
        except Exception:
            pass

    def _show_empty(self):
        self.panel.message.setText("Drop media to start editing")
        self.panel.surface.setCurrentWidget(self.panel.message)

    def play(self):
        """Play one synchronized FFmpeg composite for stable video and audio."""
        if self._closed:
            return
        self.refresh_sources()
        if not self._snapshot["clips"]:
            return
        end_time = float(self._snapshot.get("duration", 0.0))
        frame_duration = 1.0 / max(1, int(self._snapshot.get("fps", 30)))
        if end_time > 0 and self._desired_frame_time >= end_time - frame_duration:
            self._desired_frame_time = 0.0
            try:
                self.timeline.set_playhead(0.0, emit=False, ensure_visible=True)
            except Exception:
                pass

        self._frame_debounce.stop()
        self._project_prefetch_timer.stop()
        # Independent live decoders drift and compete for CPU/audio devices on
        # modest machines. Render a low-resolution composite off the UI thread,
        # then play exactly one MP4 so picture and mixed audio share one clock.
        self._render_playback_active = True
        self._pending_play = True
        self._playing = False
        # Keep the last good frame visible while a composite is prepared.
        # Do not replace the preview with a loading message or progress strip.
        self.panel.play_button.setText("▶")
        self.panel.timeline_time = self._desired_frame_time
        self.panel.update_timeline_time()
        self._start_project_render()

    def _activate_project_preview(self, autoplay=False):
        if not self._rendered_path or not Path(self._rendered_path).is_file():
            return

        # Reuse the loaded composite whenever possible. Re-setting the same
        # source on every Play click causes black frames and needless decoder
        # resets on several Qt multimedia backends.
        try:
            current_source = self.player.source().toLocalFile()
            status = self.player.mediaStatus()
        except Exception:
            current_source = ""
            status = None

        self._render_playback_active = True
        self.panel.surface.setCurrentWidget(self.panel.video)
        if current_source == self._rendered_path and status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            self._pending_seek = None
            self.player.setPosition(max(0, int(round(self._desired_frame_time * 1000.0))))
            if autoplay:
                self.player.play()
                self._playing = True
                self.panel.play_button.setText("Ⅱ")
            else:
                self.player.pause()
                self._playing = False
                self.panel.play_button.setText("▶")
            self._pending_play = False
            return

        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(self._rendered_path))
        self._pending_seek = int(round(self._desired_frame_time * 1000.0))
        self._pending_play = bool(autoplay)
        self._playing = False
        QTimer.singleShot(0, self._try_activate_loaded_source)

    def _try_activate_loaded_source(self):
        if self._pending_seek is None:
            return
        try:
            status = self.player.mediaStatus()
            loaded = status in (
                QMediaPlayer.MediaStatus.LoadedMedia,
                QMediaPlayer.MediaStatus.BufferedMedia,
            )
        except Exception:
            loaded = True
        if not loaded:
            return
        seek = self._pending_seek
        self._pending_seek = None
        self.player.setPosition(max(0, int(seek)))
        if self._pending_play:
            self._pending_play = False
            self.player.play()
            self._playing = True
            self.panel.play_button.setText("Ⅱ")
        else:
            self.player.pause()
            self._playing = False
            self.panel.play_button.setText("▶")

    def _on_media_status_changed(self, status):
        try:
            if status in (
                QMediaPlayer.MediaStatus.LoadedMedia,
                QMediaPlayer.MediaStatus.BufferedMedia,
            ):
                self._try_activate_loaded_source()
        except Exception:
            pass

    def pause(self):
        if self._closed:
            return
        was_playing = bool(self._playing)
        had_valid_composite = (
            self._render_playback_active
            and self._rendered_signature == self._signature
            and bool(self._rendered_path)
            and Path(self._rendered_path).is_file()
        )
        self._pending_play = False
        self._pending_seek = None
        try:
            self.panel.processing_bar.hide()
        except Exception:
            pass
        try:
            if self._render_playback_active and was_playing:
                self._desired_frame_time = max(0.0, self.player.position() / 1000.0)
                self.panel.timeline_time = self._desired_frame_time
                try:
                    self.timeline.set_playhead(
                        self._desired_frame_time, emit=False, ensure_visible=True
                    )
                except Exception:
                    pass
        except Exception as exc:
            self._log(f"Could not stop playback cleanly: {exc}")
        try:
            self.player.pause()
        except Exception:
            pass
        self._playing = False
        self.panel.play_button.setText("▶")
        self.panel.update_timeline_time()

        # Keep the current composite frame frozen when pausing a valid project
        # preview. Rendering a second still here used to compete with the next
        # Play request and could replace the player surface unexpectedly.
        if had_valid_composite:
            self.panel.surface.setCurrentWidget(self.panel.video)
        elif self._snapshot["clips"]:
            self._frame_debounce.start()
        else:
            self._show_empty()

    def toggle_play(self):
        if self._playing or self._pending_play:
            self.pause()
        else:
            self.play()

    def seek(self, project_time: float, resume=None):
        target = max(0.0, float(project_time))
        fps = int(self._snapshot["fps"])
        self._desired_frame_time = round(target * fps) / fps
        was_playing = self._playing if resume is None else bool(resume)
        self.panel.timeline_time = self._desired_frame_time

        if was_playing:
            if self._render_playback_active and self._rendered_signature == self._signature:
                try:
                    current_source = self.player.source().toLocalFile()
                    loaded = self.player.mediaStatus() in (
                        QMediaPlayer.MediaStatus.LoadedMedia,
                        QMediaPlayer.MediaStatus.BufferedMedia,
                    )
                    if current_source == self._rendered_path and loaded:
                        self.player.setPosition(max(0, int(round(self._desired_frame_time * 1000.0))))
                        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                            self.player.play()
                        self._playing = True
                        self.panel.surface.setCurrentWidget(self.panel.video)
                        self.panel.play_button.setText("Ⅱ")
                        self.panel.update_timeline_time()
                        return
                    # Media is still loading; retain the newest seek and let the
                    # loaded-media callback apply it before playback resumes.
                    self._pending_seek = max(0, int(round(self._desired_frame_time * 1000.0)))
                    self._pending_play = True
                    self._playing = False
                    return
                except Exception as exc:
                    self._log(f"Could not seek composite playback: {exc}")
            self._pending_play = True
            self._playing = False
            self._start_project_render()
            return

        self.pause()
        self._desired_frame_time = round(target * fps) / fps
        self.panel.timeline_time = self._desired_frame_time
        self._frame_debounce.start()
        self.panel.update_timeline_time()

    def _on_position_changed(self, position_ms):
        if self._closed or not bool(getattr(self.panel, "timeline_mode", False)):
            return
        if not self._render_playback_active or not self._playing:
            return
        seconds = max(0.0, float(position_ms) / 1000.0)
        self._desired_frame_time = seconds
        self.panel.timeline_time = seconds
        try:
            self.timeline.set_playhead(seconds, emit=False, ensure_visible=True)
        except Exception:
            pass
        try:
            self.panel.update_timeline_time()
        except Exception:
            pass

    def _on_playback_state_changed(self, state):
        if self._closed:
            return
        if bool(getattr(self.panel, "timeline_mode", False)):
            if self._render_playback_active:
                is_playing = state == QMediaPlayer.PlaybackState.PlayingState
                if is_playing:
                    self._playing = True
                    self._pending_play = False
                    self.panel.play_button.setText("Ⅱ")
                elif not self._pending_play:
                    self._playing = False
                    self.panel.play_button.setText("▶")
                return
            # Project playback has one owner: the composite QMediaPlayer above.
            return
        # Outside timeline mode this player belongs to the media-bin source preview.
        return

    # Compatibility methods retained for the existing PlayerPanel API.
    def _sync_layers(self, _active, play=False):
        if play:
            self.play()
        elif self._snapshot["clips"]:
            self._frame_debounce.start()

    def _restore_legacy_audio(self):
        # The same single player owns the composite's audio; there is no second
        # player/audio output to restore.
        return None

    def clear_project(self):
        self.pause()
        self._frame_debounce.stop()
        self._token += 1  # Ignore any render result started for the old project.
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
        self._pending_project_render = False
        self._pending_play = False
        try:
            self.player.stop()
            self.player.setSource(QUrl())
        except Exception:
            pass
        self._snapshot = {"clips": [], "visual": [], "audio": [], "fps": 30, "duration": 0.0, "signature": ""}
        self._fingerprint = ""
        self._signature = ""
        self._rendered_signature = ""
        self._rendered_path = ""
        self._render_playback_active = False
        self._last_frame_number = -1
        self._last_frame_signature = ""
        self._show_empty()

    def _log(self, message):
        try:
            log_path = Path(getattr(self.timeline, "root_dir", Path.cwd())) / "skyzen-crash.log"
            with log_path.open("a", encoding="utf-8") as log:
                from datetime import datetime
                log.write(f"[{datetime.now().isoformat(timespec='seconds')}] VIDEO ENGINE: {message}\n")
        except Exception:
            pass
        try:
            print(f"[Skyzen video engine] {message}")
        except Exception:
            pass

    def shutdown(self):
        self._closed = True
        self._frame_debounce.stop()
        self._project_prefetch_timer.stop()
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
        try:
            self.player.stop()
        except Exception:
            pass
