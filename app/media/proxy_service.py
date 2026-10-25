"""Optional background proxy generation for imported source media.

A proxy is created once per original file and reused by every timeline clip
that references that source. Originals are never modified.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot, QTimer

from app.video_engine.ffmpeg_backend import find_binary
from app.video_engine import preview_profile


from app.media.proxy_paths import proxy_cache_dir, proxy_path_for, source_identity, proxy_marker_value




class ProxyWorker(QThread):
    completed = Signal(str, str, bool, str)
    progress_text = Signal(str)

    def __init__(self, source: str, root_dir: str | Path, parent=None):
        super().__init__(parent)
        self.source = str(Path(source).expanduser().resolve())
        self.root_dir = str(Path(root_dir).resolve())
        self.cancel_requested = False

    def cancel(self):
        self.cancel_requested = True

    def run(self):
        source = Path(self.source)
        output = proxy_cache_dir() / f"{source_identity(source)}.mp4"
        marker = output.with_suffix(".ok")
        partial = output.with_name(output.stem + ".partial.mp4")
        try:
            marker_matches = (
                marker.is_file()
                and marker.read_text(encoding="utf-8", errors="ignore").strip()
                == proxy_marker_value(source)
            )
            if output.is_file() and output.stat().st_size > 0 and marker_matches:
                self.completed.emit(self.source, str(output), True, "Already cached")
                return
        except OSError:
            pass
        ffmpeg = find_binary(self.root_dir, "ffmpeg.exe") or find_binary(self.root_dir, "ffmpeg")
        if not ffmpeg:
            self.completed.emit(self.source, str(output), False, "FFmpeg was not found")
            return
        try:
            partial.unlink(missing_ok=True)
            marker.unlink(missing_ok=True)
        except OSError:
            pass

        # Proxies are low-cost editing copies sized to the selected preview
        # profile. Originals are never modified; profile-specific markers ensure
        # a smaller proxy is never silently reused for a higher-quality profile.
        proxy_width = int(preview_profile.PROXY_WIDTH)
        proxy_height = int(preview_profile.PROXY_HEIGHT)
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", self.source,
            "-map", "0:v:0", "-map", "0:a?",
            "-vf", f"scale=w='min({proxy_width},iw)':h='min({proxy_height},ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", str(preview_profile.PROXY_CRF),
            "-threads", "2", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k",
            "-movflags", "+faststart",
            str(partial),
        ]
        self.progress_text.emit(f"Building proxy: {source.name}")
        process = None
        try:
            process = subprocess.Popen(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            while process.poll() is None:
                if self.cancel_requested:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    partial.unlink(missing_ok=True)
                    self.completed.emit(self.source, str(output), False, "Cancelled")
                    return
                time.sleep(0.1)
            diagnostic_bytes = process.stderr.read() if process.stderr else b""
            diagnostic = diagnostic_bytes.decode("utf-8", errors="replace").strip()
            if process.returncode != 0 or not partial.is_file() or partial.stat().st_size == 0:
                partial.unlink(missing_ok=True)
                self.completed.emit(
                    self.source, str(output), False,
                    diagnostic[-2000:] or "FFmpeg proxy failed",
                )
                return
            partial.replace(output)
            marker.write_text(proxy_marker_value(source), encoding="utf-8")
            self.completed.emit(self.source, str(output), True, "")
        except OSError as exc:
            if process is not None and process.poll() is None:
                process.terminate()
            partial.unlink(missing_ok=True)
            self.completed.emit(self.source, str(output), False, str(exc))


class ProxyService(QObject):
    """Single-worker proxy queue; avoids saturating the CPU on multi-file import."""
    completed = Signal(str, str, bool, str)
    progress_text = Signal(str)

    def __init__(self, root_dir: str | Path, parent=None):
        super().__init__(parent)
        self.root_dir = Path(root_dir).resolve()
        self._workers: dict[str, ProxyWorker] = {}
        self._queue: list[Path] = []
        self._active_worker: ProxyWorker | None = None
        self._closing = False

    def request(self, path: str | Path):
        source = Path(path).expanduser().resolve()
        if self._closing or not source.is_file() or source.suffix.lower() not in {
            ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".wmv"
        }:
            return
        key = str(source).lower()
        if key in self._workers or any(str(item).lower() == key for item in self._queue):
            return
        self._queue.append(source)
        self._start_next()

    def _start_next(self):
        if self._closing or (self._active_worker is not None and self._active_worker.isRunning()):
            return
        self._active_worker = None
        if not self._queue:
            return
        source = self._queue.pop(0)
        key = str(source).lower()
        worker = ProxyWorker(str(source), self.root_dir, self)
        self._workers[key] = worker
        self._active_worker = worker
        worker.completed.connect(self._on_worker_completed)
        worker.progress_text.connect(self.progress_text.emit)
        worker.finished.connect(self._on_worker_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    @Slot()
    def _on_worker_finished(self):
        QTimer.singleShot(0, self._start_next)

    @Slot(str, str, bool, str)
    def _on_worker_completed(self, source, output, ok, message):
        key = str(Path(source).resolve()).lower()
        self._workers.pop(key, None)
        self.completed.emit(source, output, ok, message)

    def shutdown(self):
        self._closing = True
        self._queue.clear()
        worker = self._active_worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            worker.wait(5000)
