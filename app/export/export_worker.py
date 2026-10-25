"""Non-blocking FFmpeg export worker with live progress and optional thumbnail."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.video_engine.ffmpeg_backend import build_frame_command, build_project_command, find_binary


class ExportWorker(QThread):
    progress = Signal(int, str, str)  # percent, stage/status, elapsed text
    succeeded = Signal(str, str)      # video path, thumbnail path or empty
    failed = Signal(str)

    def __init__(self, snapshot: dict, root_dir: str, output_path: str,
                 width: int, height: int, fps: int, options: dict,
                 thumbnail_mode: str = "None", thumbnail_source: str = "",
                 thumbnail_time: float = 0.0, parent=None):
        super().__init__(parent)
        self.snapshot = dict(snapshot)
        self.root_dir = str(root_dir)
        self.output_path = str(output_path)
        self.width = int(width)
        self.height = int(height)
        self.fps = max(1, min(60, int(fps)))
        self.options = dict(options)
        self.thumbnail_mode = str(thumbnail_mode)
        self.thumbnail_source = str(thumbnail_source or "")
        self.thumbnail_time = max(0.0, float(thumbnail_time))
        self._process = None

    @staticmethod
    def _elapsed(seconds: float) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"

    @staticmethod
    def _parse_clock(value: str) -> float:
        try:
            hours, minutes, seconds = value.strip().split(":")
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        except (ValueError, AttributeError):
            return 0.0

    def run(self):
        ffmpeg = find_binary(self.root_dir, "ffmpeg.exe") or find_binary(self.root_dir, "ffmpeg")
        ffprobe = find_binary(self.root_dir, "ffprobe.exe") or find_binary(self.root_dir, "ffprobe")
        if not ffmpeg:
            self.failed.emit("FFmpeg was not found. Install it or place it in the project's ffmpeg folder.")
            return
        self.snapshot["fps"] = self.fps
        duration = max(1.0 / self.fps, float(self.snapshot.get("duration", 0.0)))
        try:
            command = build_project_command(
                ffmpeg, ffprobe, self.snapshot, self.output_path,
                width=self.width, height=self.height, codec_options=self.options,
            )
        except Exception as exc:
            self.failed.emit(f"Could not prepare export: {type(exc).__name__}: {exc}")
            return

        # FFmpeg's machine-readable progress stream is separate from diagnostics.
        command[-1:-1] = ["-progress", "pipe:1", "-stats_period", "0.25", "-nostats"]
        Path(self.output_path).parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        self.progress.emit(0, "Starting encoder…", "00:00:00")
        try:
            with tempfile.TemporaryFile() as error_file:
                self._process = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=error_file, text=True, encoding="utf-8", errors="replace",
                    bufsize=1, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                out_time = 0.0
                while True:
                    line = self._process.stdout.readline() if self._process.stdout else ""
                    if not line and self._process.poll() is not None:
                        break
                    if not line:
                        continue
                    key, sep, value = line.strip().partition("=")
                    if not sep:
                        continue
                    if key == "out_time":
                        out_time = self._parse_clock(value)
                        percent = max(0, min(99, int(out_time / duration * 100)))
                        elapsed = self._elapsed(time.monotonic() - started)
                        self.progress.emit(percent, "Exporting video…", elapsed)
                    elif key == "progress" and value == "end":
                        self.progress.emit(99, "Finishing video…", self._elapsed(time.monotonic() - started))
                return_code = self._process.wait()
                error_file.seek(0)
                diagnostic = error_file.read().decode("utf-8", errors="replace").strip()
        except OSError as exc:
            self.failed.emit(f"Could not start FFmpeg: {exc}")
            return
        except Exception as exc:
            self.failed.emit(f"Unexpected export error: {type(exc).__name__}: {exc}")
            return
        finally:
            self._process = None

        out = Path(self.output_path)
        if return_code != 0 or not out.is_file() or out.stat().st_size <= 0:
            try:
                out.unlink(missing_ok=True)
            except OSError:
                pass
            self.failed.emit(diagnostic[-5000:] or f"FFmpeg exited with code {return_code} without producing a video.")
            return

        thumbnail_path = ""
        try:
            if self.thumbnail_mode == "Custom image" and self.thumbnail_source:
                source = Path(self.thumbnail_source)
                if source.is_file():
                    thumbnail_path = str(out.with_name(out.stem + "_thumbnail" + source.suffix.lower()))
                    shutil.copy2(source, thumbnail_path)
            elif self.thumbnail_mode == "Current project frame":
                thumbnail_path = str(out.with_name(out.stem + "_thumbnail.jpg"))
                self.progress.emit(99, "Creating project-frame thumbnail…", self._elapsed(time.monotonic() - started))
                # If the playhead is in a gap, render the nearest visible clip
                # instead of silently producing a black/empty thumbnail.
                thumbnail_time = self.thumbnail_time
                visual = list(self.snapshot.get("visual", []))
                if visual and not any(float(c.get("start", 0.0)) <= thumbnail_time < float(c.get("end", 0.0)) for c in visual):
                    nearest = min(visual, key=lambda c: min(abs(thumbnail_time - float(c.get("start", 0.0))), abs(thumbnail_time - float(c.get("end", 0.0)))))
                    start = float(nearest.get("start", 0.0))
                    end = max(start, float(nearest.get("end", start)))
                    thumbnail_time = max(start, min(thumbnail_time, max(start, end - 1.0 / max(1, self.fps))))
                thumb_command = build_frame_command(ffmpeg, self.snapshot, thumbnail_time, thumbnail_path)
                thumb_result = subprocess.run(
                    thumb_command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if thumb_result.returncode != 0 or not Path(thumbnail_path).is_file():
                    thumbnail_path = ""
        except Exception:
            thumbnail_path = ""

        self.progress.emit(100, "Export complete", self._elapsed(time.monotonic() - started))
        self.succeeded.emit(self.output_path, thumbnail_path)
