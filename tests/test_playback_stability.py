"""Regression guards for native single-clip playback and audio stability."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(path):
    return (ROOT / path).read_text(encoding="utf-8")


class PlaybackStabilityTests(unittest.TestCase):
    def test_single_main_video_has_native_playback_path(self):
        text = source("app/player_panel/live_playback.py")
        self.assertIn("def _can_use_native_player", text)
        self.assertIn("self.panel.player", text)
        self.assertIn("self.panel.video", text)
        self.assertIn("self._activate_native_clip", text)

    def test_live_engine_does_not_seek_to_wall_clock_every_tick(self):
        text = source("app/player_panel/live_playback.py")
        self.assertIn("Do not continuously seek decoders to a wall-clock estimate", text)
        self.assertIn("if force:", text)
        self.assertNotIn("abs(actual - expected)", text)

    def test_overlay_video_audio_is_muted_in_composite_mode(self):
        text = source("app/player_panel/live_playback.py")
        self.assertIn("is_main_video = clip.get(\"base\") == \"V\" and bool(clip.get(\"is_main\", False))", text)
        self.assertIn("Overlay video sound is muted by default", text)

    def test_timeline_layer_updates_do_not_switch_to_source_video_widget(self):
        text = source("app/player_panel/main.py")
        start = text.index("    def set_timeline_layers(self, active, timeline=None):")
        end = text.index("    def _timeline_engine(self):", start)
        method = text[start:end]
        self.assertNotIn("self.surface.setCurrentWidget(self.video)", method)
        self.assertIn("live.direct_mode", method)
        self.assertIn("self.timeline_composite", method)

    def test_video_frames_are_delivered_to_gui_thread(self):
        text = source("app/player_panel/live_playback.py")
        self.assertIn("Qt.ConnectionType.QueuedConnection", text)
        self.assertIn("image.scaled(", text)
        self.assertIn("FastTransformation", text)

    def test_rendered_project_player_owns_project_clock(self):
        text = source("app/video_engine/controller.py")
        self.assertIn("Play one synchronized FFmpeg composite", text)
        self.assertIn("self._render_playback_active", text)
        self.assertIn("self.panel.video", text)

    def test_timeline_playback_uses_one_composite_media_player(self):
        text = source("app/video_engine/controller.py")
        self.assertIn("def play(self):", text)
        self.assertIn("self._start_project_render()", text)
        self.assertIn("Play one synchronized FFmpeg composite", text)
        self.assertIn("self._render_playback_active", text)

    def test_project_player_position_drives_timeline_clock(self):
        text = source("app/video_engine/controller.py")
        start = text.index("    def _on_position_changed(self, position_ms):")
        end = text.index("    def _on_playback_state_changed", start)
        method = text[start:end]
        self.assertIn("float(position_ms) / 1000.0", method)
        self.assertIn("self.timeline.set_playhead", method)

    def test_player_state_does_not_depend_on_inactive_live_engine(self):
        text = source("app/video_engine/controller.py")
        start = text.index("    def _on_playback_state_changed(self, state):")
        end = text.index("    # Compatibility methods retained", start)
        method = text[start:end]
        self.assertIn("if self._render_playback_active:", method)
        self.assertIn("state == QMediaPlayer.PlaybackState.PlayingState", method)


    def test_ffmpeg_layers_are_shifted_to_project_timeline_time(self):
        text = source("app/video_engine/ffmpeg_backend.py")
        self.assertIn("setpts=PTS-STARTPTS+{_fmt(start)}/TB", text)
        self.assertIn("enable='gte(t,", text)

    def test_fullscreen_preserves_play_state_instead_of_autoplaying(self):
        text = source("app/player_panel/main.py")
        start = text.index("    def start(self):", text.index("class FullscreenPlayer"))
        end = text.index("    def _set_image(self, path):", start)
        method = text[start:end]
        self.assertIn("self._was_playing", method)
        self.assertIn("owner.player.play() if self._was_playing else owner.player.pause()", method)
        self.assertIn("if self._timeline_mode:", method)

    def test_source_asset_selection_does_not_autoplay(self):
        text = source("app/player_panel/main.py")
        start = text.index("    def show_asset(self, path: str, kind: str):")
        end = text.index("    def show_timeline_clip", start)
        method = text[start:end]
        self.assertIn("self.player.setSource(QUrl.fromLocalFile(str(p)))", method)
        self.assertIn("Selecting/importing media must never start playback implicitly", method)
        self.assertNotIn("self.player.play()", method)


    def test_project_controller_has_one_active_playback_engine(self):
        text = source("app/video_engine/controller.py")
        self.assertIn("self._live_engine = None", text)
        self.assertIn("One playback owner only", text)
        self.assertNotIn("LiveMultitrackEngine(panel, self)", text)

    def test_pause_keeps_valid_composite_frame_without_scheduling_still_render(self):
        text = source("app/video_engine/controller.py")
        start = text.index("    def pause(self):")
        end = text.index("    def toggle_play(self):", start)
        method = text[start:end]
        self.assertIn("had_valid_composite", method)
        self.assertIn("self.panel.surface.setCurrentWidget(self.panel.video)", method)
        self.assertIn("elif self._snapshot[\"clips\"]:", method)

    def test_ui_layout_is_separated_from_window_controller(self):
        self.assertTrue((ROOT / "app/ui/editor_layout.py").is_file())
        layout = source("app/ui/editor_layout.py")
        window = source("app/main_window/main.py")
        self.assertIn("def build_editor_layout(window):", layout)
        self.assertIn("build_editor_layout(self)", window)


if __name__ == "__main__":
    unittest.main()
