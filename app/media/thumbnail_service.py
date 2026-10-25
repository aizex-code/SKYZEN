"""Asynchronous, shared video-thumbnail generation for Skyzen.

FFmpeg is never run on the GUI thread. The service is shared by the media bin
and timeline so the same source file is decoded only once per cache key.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap


def _ffmpeg_path(root_dir: Path) -> Path | None:
    candidates = []
    for base in (root_dir, *root_dir.parents):
        candidates.extend((
            base / "ffmpeg" / "ffmpeg.exe",
            base / "ffmpeg.exe",
            base / "bin" / "ffmpeg.exe",
        ))
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            pass
    found = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    return Path(found).resolve() if found else None


def _cache_path(root_dir: Path, source: Path) -> Path:
    try:
        stat = source.stat()
        identity = f"{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    except OSError:
        identity = str(source)
    digest = hashlib.sha1(identity.encode("utf-8", errors="replace")).hexdigest()[:12]
    cache_dir = root_dir / "cache" / "thumbnails"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{source.stem}_{digest}.jpg"


class _ThumbnailSignals(QObject):
    finished = Signal(str, str)


class _ThumbnailJob(QRunnable):
    def __init__(self, source: Path, cache: Path, ffmpeg: Path | None):
        super().__init__()
        self.source = source
        self.cache = cache
        self.ffmpeg = ffmpeg
        self.signals = _ThumbnailSignals()

    def run(self):
        result_path = ""
        if self.cache.is_file():
            result_path = str(self.cache)
        elif self.ffmpeg is not None and self.source.is_file():
            try:
                completed = subprocess.run(
                    [
                        str(self.ffmpeg),
                        "-hide_banner", "-loglevel", "error", "-y",
                        "-ss", "0.25", "-i", str(self.source),
                        "-frames:v", "1", "-vf", "scale=480:270:force_original_aspect_ratio=decrease",
                        str(self.cache),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=18,
                    check=False,
                )
                if completed.returncode == 0 and self.cache.is_file():
                    result_path = str(self.cache)
            except (OSError, subprocess.SubprocessError):
                result_path = ""
        self.signals.finished.emit(str(self.source.resolve()), result_path)


class ThumbnailService(QObject):
    """Returns cached/placeholder pixmaps immediately and emits completed ones."""

    thumbnail_ready = Signal(str, QPixmap)

    def __init__(self, root_dir: str | Path, parent=None):
        super().__init__(parent)
        self.root_dir = Path(root_dir).resolve()
        self._cache: dict[str, QPixmap] = {}
        self._pending: dict[str, _ThumbnailJob] = {}
        self._failed: set[str] = set()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)

    @staticmethod
    def _key(path: str | Path) -> str:
        try:
            return str(Path(path).resolve())
        except (OSError, RuntimeError):
            return str(path)

    @staticmethod
    def _placeholder() -> QPixmap:
        pix = QPixmap(480, 270)
        pix.fill(QColor("#111720"))
        painter = QPainter(pix)
        painter.setPen(QColor("#394553"))
        painter.drawRect(0, 0, pix.width() - 1, pix.height() - 1)
        painter.setPen(QColor("#8A96A6"))
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "VIDEO")
        painter.end()
        return pix

    def request(self, path: str | Path) -> QPixmap:
        """Return immediately; a missing thumbnail is generated in a worker."""
        source = Path(path)
        key = self._key(source)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        cache = _cache_path(self.root_dir, source)
        if cache.is_file():
            pix = QPixmap(str(cache))
            if not pix.isNull():
                self._cache[key] = pix
                return pix

        if key not in self._pending and key not in self._failed:
            job = _ThumbnailJob(source, cache, _ffmpeg_path(self.root_dir))
            job.signals.finished.connect(self._job_finished)
            self._pending[key] = job
            self._pool.start(job)

        return self._placeholder()

    def _job_finished(self, source_key: str, cache_path: str):
        self._pending.pop(source_key, None)
        pix = QPixmap(cache_path) if cache_path else QPixmap()
        if pix.isNull():
            self._failed.add(source_key)
            return
        self._cache[source_key] = pix
        self.thumbnail_ready.emit(source_key, pix)
