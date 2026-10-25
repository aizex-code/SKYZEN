from __future__ import annotations

from pathlib import Path
import json
from datetime import datetime

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMainWindow,
)

from app.left_panel.main import LeftPanel
from app.media.thumbnail_service import ThumbnailService
from app.media.proxy_service import ProxyService
from app.player_panel.main import PlayerPanel
from app.timeline_panel.main import TimelinePanel
from app.export.export_dialog import ExportDialog
from app.video_engine import preview_profile
from app.inspector_panel.main import InspectorPanel
from app.ui.theme import STYLE
from app.ui.editor_layout import build_editor_layout
from app.main_window.settings_dialog import EditorSettingsDialog


_UNSERIALIZABLE = object()

class EditorMainWindow(QMainWindow):
    # Emitted after save completes in closeEvent so the project window can
    # reliably show itself again. Qt signals survive C++ vtable dispatch;
    # Python monkey-patching of closeEvent does not.
    editor_closed = Signal()

    def __init__(self, root_dir: str | Path):
        super().__init__()

        self.root_dir = Path(root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.project_state_path = self.root_dir / "project_state.json"
        self.settings = QSettings("Skyzen", "Editor")
        # One-time migration: enable fast compressed preview copies by default
        # for existing installs, while respecting the user's choice thereafter.
        if not self.settings.value("media/proxy_default_migrated_v4", False, type=bool):
            self.settings.setValue("media/create_proxies", True)
            self.settings.setValue("media/proxy_default_migrated_v4", True)
        self.proxy_enabled = self.settings.value("media/create_proxies", True, type=bool)
        self.preview_quality = str(self.settings.value("preview/quality", "Performance"))
        self.zoom_wheel_step = self.settings.value("timeline/zoom_wheel_step", 150, type=int)
        self.horizontal_pan_multiplier = self.settings.value("timeline/horizontal_pan_multiplier", 7, type=int)
        self.vertical_scroll_multiplier = self.settings.value("timeline/vertical_scroll_multiplier", 1, type=int)
        if self.preview_quality not in preview_profile.PROFILE_OPTIONS:
            self.preview_quality = "Performance"
        preview_profile.configure_preview_profile(self.preview_quality)
        self.proxy_service = ProxyService(self.root_dir, self)
        self.setWindowTitle("Skyzen — Editor")
        self.resize(1280, 760)
        self.setMinimumSize(960, 600)
        self.setStyleSheet(STYLE)

        # One shared background thumbnail queue serves both the media bin and
        # timeline. This avoids duplicate FFmpeg jobs and GUI-thread blocking.
        self.thumbnail_service = ThumbnailService(self.root_dir, self)
        self.left = LeftPanel(
            root_dir=self.root_dir,
            thumbnail_service=self.thumbnail_service,
        )
        self.player = PlayerPanel(root_dir=self.root_dir)
        self.timeline = TimelinePanel(
            root_dir=self.root_dir,
            thumbnail_service=self.thumbnail_service,
        )
        self.inspector = InspectorPanel(self.timeline)
        self.timeline.zoom_wheel_step = max(40, min(350, int(self.zoom_wheel_step)))
        self.timeline.horizontal_pan_multiplier = max(2, min(14, int(self.horizontal_pan_multiplier)))
        self.timeline.vertical_scroll_multiplier = max(1, min(3, int(self.vertical_scroll_multiplier)))
        self.left.media_imported.connect(self._on_media_imported)

        self.build()
        # Defer state restore until after the first event-loop pass so that all
        # child widgets (timeline scroll areas, left panel list view, etc.) have
        # finished their own initialisation and are safe to call rebuild() on.
        QTimer.singleShot(0, self._load_project_state)
        self.proxy_service.completed.connect(self._on_proxy_completed)
        self.proxy_service.progress_text.connect(self._on_proxy_progress)
        self._install_shortcuts()
        # Existing timeline/bin media should also get proxies after the UI is
        # ready; otherwise only newly imported files benefit from fast preview.
        QTimer.singleShot(0, self._build_proxies_for_current_bin)

        # Frequent autosave reduces loss if the editor closes unexpectedly.
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(10_000)  # 10 s
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start()

    def _read_saved_state(self):
        """Read the best available state snapshot, including backup/legacy files."""
        candidates = (self.project_state_path, self.project_state_path.with_name("project_state.json.bak"))
        errors = []
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(payload, dict) and (isinstance(payload.get("tracks"), list) or isinstance(payload.get("imported_media"), list)):
                    return payload, candidate
                errors.append(f"{candidate.name}: unsupported state format")
            except Exception as exc:
                errors.append(f"{candidate.name}: {exc}")
        metadata_path = self.root_dir / "project.json"
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                embedded = metadata.get("project_state") or metadata.get("state")
                if isinstance(embedded, dict):
                    return embedded, metadata_path
                if isinstance(metadata.get("tracks"), list):
                    return metadata, metadata_path
            except Exception as exc:
                errors.append(f"project.json: {exc}")
        if errors:
            raise ValueError("Could not read saved project state: " + "; ".join(errors))
        return None, None

    def _load_project_state(self):
        """Restore imported media and timeline elements from this project."""
        try:
            payload, source = self._read_saved_state()
            if payload is None:
                self.status_label.setText("New project · 30 FPS")
                return
            imported = []
            for item in payload.get("imported_media", []):
                if not isinstance(item, dict):
                    continue
                raw_path = str(item.get("path", "")).strip()
                if raw_path:
                    imported.append((Path(raw_path).expanduser(), str(item.get("kind") or "Media")))
            self.left.imported_items = imported
            self.left.items = list(imported)
            self.left.browser_source = "yours"
            self.left.rebuild()

            tracks = payload.get("tracks", [])
            if not isinstance(tracks, list):
                tracks = []
            restored_tracks = []
            for track in tracks:
                if not isinstance(track, dict):
                    continue
                clean_track = dict(track)
                clips = clean_track.get("clips", [])
                clean_track["clips"] = [dict(c) for c in clips if isinstance(c, dict)] if isinstance(clips, list) else []
                restored_tracks.append(clean_track)
            self.timeline.tracks = restored_tracks
            self.timeline.selected_clip = None
            self.status_label.setText("Restoring project…")
            QTimer.singleShot(80, self._rebuild_timeline_after_restore)
        except Exception as exc:
            self.status_label.setText(f"Restore warning: {exc}")

    def _rebuild_timeline_after_restore(self):
        """Recreate timeline widgets after Qt has completed initial layout."""
        try:
            self.timeline.rebuild()
            self.timeline.selected_clip = None
            if hasattr(self.timeline, "_emit_active_clips"):
                self.timeline._emit_active_clips(getattr(self.timeline, "playhead", 0.0))
            self.status_label.setText("Project restored · 30 FPS")
            self.save_project_state()
        except Exception as exc:
            self.status_label.setText(f"Restore rebuild error: {exc}")

    @staticmethod
    def _json_safe(value):
        """Convert state to JSON-safe data, omitting transient Qt objects."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if str(key).startswith("_qt_"):
                    continue
                safe = EditorMainWindow._json_safe(item)
                if safe is not _UNSERIALIZABLE:
                    result[str(key)] = safe
            return result
        if isinstance(value, (list, tuple)):
            result = []
            for item in value:
                safe = EditorMainWindow._json_safe(item)
                if safe is not _UNSERIALIZABLE:
                    result.append(safe)
            return result
        return _UNSERIALIZABLE

    def save_project_state(self):
        """Atomically persist the full media-bin and editable timeline model."""
        try:
            imported = []
            for path, kind in getattr(self.left, "imported_items", []):
                try:
                    normalized = str(Path(path).expanduser().resolve())
                except Exception:
                    normalized = str(path)
                imported.append({"path": normalized, "kind": str(kind)})
            tracks = self._json_safe(getattr(self.timeline, "tracks", []))
            if tracks is _UNSERIALIZABLE or not isinstance(tracks, list):
                raise TypeError("timeline state could not be serialized")
            now = datetime.now().isoformat(timespec="seconds")
            payload = {"schema_version": 2, "name": self.root_dir.name, "modified": now,
                       "imported_media": imported, "tracks": tracks,
                       "playhead": float(getattr(self.timeline, "playhead", 0.0) or 0.0)}
            serialized = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)
            if self.project_state_path.is_file():
                try:
                    self.project_state_path.with_name("project_state.json.bak").write_text(
                        self.project_state_path.read_text(encoding="utf-8"), encoding="utf-8")
                except OSError:
                    pass
            temp_path = self.project_state_path.with_suffix(".json.tmp")
            temp_path.write_text(serialized, encoding="utf-8")
            temp_path.replace(self.project_state_path)
            metadata_path = self.root_dir / "project.json"
            metadata = {}
            if metadata_path.exists():
                try:
                    loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        metadata = loaded
                except Exception:
                    pass
            metadata.update({"name": self.root_dir.name, "modified": now, "version": 2})
            metadata_temp = metadata_path.with_suffix(".json.tmp")
            metadata_temp.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
            metadata_temp.replace(metadata_path)
            if hasattr(self, "saved_label"):
                self.saved_label.setText("●  Auto saved: " + datetime.now().strftime("%H:%M:%S"))
        except Exception as exc:
            if hasattr(self, "status_label"):
                self.status_label.setText(f"Project save failed: {exc}")


    def _autosave(self):
        """Periodic autosave — silently persists the current state every 60 s."""
        self.save_project_state()

    def closeEvent(self, event):
        # Stop the autosave timer before the final save so it cannot fire again
        # after the window starts tearing down.
        if hasattr(self, "_autosave_timer"):
            self._autosave_timer.stop()
        self.save_project_state()

        # Shut down background services before the window is destroyed.
        try:
            self.proxy_service.shutdown()
        except Exception:
            pass
        engine = getattr(self.player, "_multitrack_engine", None)
        if engine is not None:
            try:
                engine.shutdown()
            except Exception:
                pass

        super().closeEvent(event)
        if event.isAccepted():
            self.editor_closed.emit()

    def build(self):
        build_editor_layout(self)

    def open_export_dialog(self):
        dialog = ExportDialog(self.timeline, self.root_dir, self)
        dialog.exec()

    def open_settings_dialog(self):
        """Edit common performance and timeline controls without code changes."""
        dialog = EditorSettingsDialog(self, {
            "quality": self.preview_quality,
            "proxies": self.proxy_enabled,
            "zoom_step": self.timeline.zoom_wheel_step,
            "pan_speed": self.timeline.horizontal_pan_multiplier,
            "layer_scroll": self.timeline.vertical_scroll_multiplier,
        })
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.settings.setValue("timeline/zoom_wheel_step", values["zoom_step"])
        self.settings.setValue("timeline/horizontal_pan_multiplier", values["pan_speed"])
        self.settings.setValue("timeline/vertical_scroll_multiplier", values["layer_scroll"])
        self.timeline.zoom_wheel_step = values["zoom_step"]
        self.timeline.horizontal_pan_multiplier = values["pan_speed"]
        self.timeline.vertical_scroll_multiplier = values["layer_scroll"]
        self._set_proxy_enabled(values["proxies"])
        if values["quality"] != self.preview_quality:
            self._set_preview_quality(values["quality"])

    def _install_shortcuts(self):
        """Keyboard shortcuts are active while the timeline has focus."""
        self.timeline.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        definitions = (
            ("Delete", self.timeline.delete_selected),
            ("Ctrl+K", self.timeline.split_selected),
            ("Ctrl+Z", self.timeline.undo),
            ("Ctrl+Y", self.timeline.redo),
            ("Ctrl+Shift+Z", self.timeline.redo),
            ("Space", self.player.toggle_play),
        )
        self._timeline_shortcuts = []
        for sequence, callback in definitions:
            shortcut = QShortcut(QKeySequence(sequence), self.timeline)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self._timeline_shortcuts.append(shortcut)

    def _set_preview_quality(self, quality_name: str):
        """Switch preview quality without changing project/export dimensions."""
        quality_name = preview_profile.configure_preview_profile(quality_name)
        self.preview_quality = quality_name
        self.settings.setValue("preview/quality", quality_name)
        if hasattr(self, "preview_quality_actions"):
            action = self.preview_quality_actions.get(quality_name)
            if action is not None:
                action.setChecked(True)

        engine = getattr(self.player, "_multitrack_engine", None)
        if engine is not None:
            try:
                engine.refresh_sources()
            except Exception:
                pass

        if preview_profile.USE_PROXIES and self.proxy_enabled:
            # Profile-specific marker values force incompatible old proxies to
            # be rebuilt. This remains a one-worker queue to protect low-end CPUs.
            self._build_proxies_for_current_bin()
            self.status_label.setText(f"Preview quality: {quality_name} · preparing media")
        elif quality_name == "Clear":
            self.status_label.setText("Clear preview: original media · CPU intensive")
            self.status_label.setToolTip(
                "Clear mode avoids 360p proxies and uses the original source media. "
                "On older CPUs, switch back to Performance or Balanced during playback."
            )
        else:
            self.status_label.setText(f"Preview quality: {quality_name}")

    def _set_proxy_enabled(self, enabled: bool):
        self.proxy_enabled = bool(enabled)
        self.settings.setValue("media/create_proxies", self.proxy_enabled)
        if self.proxy_enabled:
            self.status_label.setText("Fast proxies enabled for new imports")
            self.status_label.setToolTip(
                "Imported videos are copied to a smaller, faster-to-decode proxy in the background. Originals are preserved."
            )
        else:
            self.status_label.setText("Basic editing · 30 FPS")
            self.status_label.setToolTip("Proxy generation is disabled; original media is used.")

    def _on_media_imported(self, path: str):
        if self.proxy_enabled and preview_profile.USE_PROXIES:
            self.proxy_service.request(path)

    def _build_proxies_for_current_bin(self):
        if not preview_profile.USE_PROXIES:
            return
        sources = {}
        for path, kind in list(getattr(self.left, "items", [])):
            if str(kind).lower() == "video":
                sources[str(Path(path).expanduser().resolve())] = path
        for track in getattr(self.timeline, "playback_tracks", lambda: [])():
            if str(track.get("base", "V")) != "V":
                continue
            for clip in track.get("clips", []):
                if str(clip.get("kind", "Video")).lower() == "video":
                    path = clip.get("path", "")
                    if path:
                        sources[str(Path(path).expanduser().resolve())] = path
        if not sources:
            return
        for path in sources.values():
            self.proxy_service.request(path)
        self.status_label.setText(f"Preparing fast previews for {len(sources)} video(s)…")

    def _on_proxy_progress(self, message: str):
        self.status_label.setText(str(message)[:52])
        if hasattr(self, "proxy_progress"):
            self.proxy_progress.show()

    def _on_proxy_completed(self, source: str, output: str, success: bool, message: str):
        engine = getattr(self.player, "_multitrack_engine", None)
        if success:
            self.status_label.setText(f"Proxy ready: {Path(source).name[:26]}")
            if hasattr(self, "proxy_progress") and not self.proxy_service._queue:
                self.proxy_progress.hide()
            if engine is not None:
                refresh = getattr(engine, "refresh_sources", None)
                if callable(refresh):
                    refresh()
        else:
            self.status_label.setText(f"Proxy failed: {Path(source).name[:22]}")
            self.status_label.setToolTip(str(message))
            if hasattr(self, "proxy_progress") and not self.proxy_service._queue:
                self.proxy_progress.hide()

    def _on_tool_add_requested(self, tool_type: str, preset_id: str):
        """Route typed toolbar presets into the shared timeline layer model."""
        try:
            clip = self.timeline.add_tool_asset_at_playhead(tool_type, preset_id)
            if clip is not None:
                self.status_label.setText(f"Added {tool_type}: {clip.get('display_name', preset_id)}")
        except Exception as exc:
            try:
                self.timeline._log_drop_failure("tool preset add", exc)
            except Exception:
                pass
            self.status_label.setText(f"Couldn't add {tool_type.lower()} preset")

    def _on_media_add_requested(
        self,
        path: str,
        kind: str,
    ):
        """
        Bridge between LeftPanel and TimelinePanel.

        The LeftPanel is intentionally not changed.
        Import still puts media in the browser.
        The media-card '+' adds that media to the timeline.
        """
        try:
            media_path = Path(path).expanduser().resolve()
        except (OSError, RuntimeError, TypeError):
            return

        if not media_path.is_file():
            return

        normalized_kind = (
            str(kind).strip().title()
            if kind
            else "Video"
        )

        # Current timeline API.
        add_method = getattr(
            self.timeline,
            "add_media_at_playhead",
            None,
        )
        if callable(add_method):
            add_method(
                str(media_path),
                normalized_kind,
            )
            return

        # Compatibility fallback for an older timeline build.
        fallback = getattr(
            self.timeline,
            "add_as_new_track",
            None,
        )
        if callable(fallback):
            playhead = float(
                getattr(
                    self.timeline,
                    "playhead",
                    0.0,
                )
            )
            fallback(
                str(media_path),
                normalized_kind,
                playhead,
            )

    # NOTE: closeEvent is defined earlier in this class (search for editor_closed).
    # Do not add a second closeEvent here — Python silently replaces the first.
