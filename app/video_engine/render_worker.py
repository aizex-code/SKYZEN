"""Qt worker wrapper for non-blocking FFmpeg preview renders."""
from __future__ import annotations

import subprocess
import tempfile
import threading
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .ffmpeg_backend import (
    build_frame_command,
    build_project_command,
    find_binary,
)


class RenderWorker(QThread):
    """Build and run one FFmpeg command away from the UI thread."""

    succeeded = Signal(int, str, str, str, float)  # token, mode, signature, path, seconds
    failed = Signal(int, str, str, str, float)     # token, mode, signature, diagnostic, seconds

    def __init__(
        self, token: int, mode: str, snapshot: dict, output: str,
        root_dir: str, seconds: float = 0.0, parent=None,
    ):
        super().__init__(parent)
        self.token = int(token)
        self.mode = str(mode)
        self.snapshot = snapshot
        self.output = str(output)
        self.root_dir = str(root_dir)
        self.seconds = float(seconds)
        self._cancel = threading.Event()
        self._process = None

    def cancel(self):
        self._cancel.set()
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def run(self):
        signature = str(self.snapshot.get("signature", ""))
        ffmpeg = find_binary(self.root_dir, "ffmpeg.exe") or find_binary(self.root_dir, "ffmpeg")
        if not ffmpeg:
            self.failed.emit(self.token, self.mode, signature, "FFmpeg was not found. Install FFmpeg or place it in the project's ffmpeg folder.", self.seconds)
            return
        ffprobe = find_binary(self.root_dir, "ffprobe.exe") or find_binary(self.root_dir, "ffprobe")

        try:
            if self.mode == "frame":
                command = build_frame_command(
                    ffmpeg, self.snapshot, self.seconds, self.output
                )
            elif self.mode == "project":
                command = build_project_command(
                    ffmpeg, ffprobe, self.snapshot, self.output
                )
            else:
                self.failed.emit(self.token, self.mode, signature, f"Unknown render mode: {self.mode}", self.seconds)
                return
        except Exception as exc:
            self.failed.emit(self.token, self.mode, signature, f"Could not prepare FFmpeg render: {exc}", self.seconds)
            return

        Path(self.output).parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryFile() as error_file:
                self._process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=error_file,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                while self._process.poll() is None:
                    if self._cancel.is_set():
                        try:
                            self._process.terminate()
                        except OSError:
                            pass
                        try:
                            self._process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            self._process.kill()
                            self._process.wait()
                        try:
                            Path(self.output).unlink(missing_ok=True)
                        except OSError:
                            pass
                        self.failed.emit(self.token, self.mode, signature, "Preview render cancelled.", self.seconds)
                        return
                    time.sleep(0.05)

                error_file.seek(0)
                diagnostic = error_file.read().decode("utf-8", errors="replace").strip()
                return_code = self._process.returncode
        except OSError as exc:
            self.failed.emit(self.token, self.mode, signature, f"Could not start FFmpeg: {exc}", self.seconds)
            return
        except Exception as exc:
            self.failed.emit(
                self.token, self.mode, signature,
                f"Unexpected preview worker error: {type(exc).__name__}: {exc}",
                self.seconds,
            )
            return
        finally:
            self._process = None

        output_path = Path(self.output)
        if return_code == 0 and output_path.is_file() and output_path.stat().st_size > 0:
            self.succeeded.emit(self.token, self.mode, signature, self.output, self.seconds)
        else:
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass
            self.failed.emit(
                self.token, self.mode, signature,
                diagnostic[-5000:] or f"FFmpeg exited with code {return_code} without producing a preview.",
                self.seconds,
            )
