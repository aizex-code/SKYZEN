"""Pure path helpers for versioned source proxy cache files (no Qt dependency)."""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

# Bump this whenever proxy resolution, codecs, or audio-preservation behavior changes.
PROXY_PROFILE_ID = "proxy360-v4"


def source_identity(path: str | Path) -> str:
    source = Path(path).expanduser().resolve()
    try:
        stat = source.stat()
        payload = f"{source}|{stat.st_size}|{stat.st_mtime_ns}"
    except OSError:
        payload = str(source)
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:32]


def proxy_marker_value(source: str | Path) -> str:
    return f"{source_identity(source)}|{PROXY_PROFILE_ID}"


def proxy_cache_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "Skyzen" / "media_proxies"
    path.mkdir(parents=True, exist_ok=True)
    return path


def proxy_path_for(source: str | Path, root_dir: str | Path | None = None) -> Path:
    """Return only a complete proxy matching the current preview profile."""
    original = Path(source).expanduser().resolve()
    proxy = proxy_cache_dir() / f"{source_identity(original)}.mp4"
    marker = proxy.with_suffix(".ok")
    try:
        if (
            proxy.is_file()
            and proxy.stat().st_size > 0
            and marker.is_file()
            and marker.read_text(encoding="utf-8").strip() == proxy_marker_value(original)
        ):
            return proxy
    except (OSError, UnicodeError):
        pass
    return original
