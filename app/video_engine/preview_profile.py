"""Adaptive preview profiles for low-end and higher-quality editing.

The default is Performance: a small CPU-friendly composite for older machines.
Profiles only affect disposable previews/proxies; export quality is independent.
"""
from __future__ import annotations

PROFILE_OPTIONS = {
    "Performance": {
        "width": 640, "height": 360, "crf": 27,
        "proxy_width": 640, "proxy_height": 360,
        "proxy_crf": 30, "use_proxies": True,
    },
    "Balanced": {
        "width": 854, "height": 480, "crf": 27,
        "proxy_width": 854, "proxy_height": 480,
        "proxy_crf": 29, "use_proxies": True,
    },
    "Clear": {
        "width": 1280, "height": 720, "crf": 26,
        "proxy_width": 960, "proxy_height": 540,
        "proxy_crf": 28, "use_proxies": False,
    },
}

PREVIEW_PROFILE_NAME = "Performance"
PREVIEW_PROFILE_ID = "composite-performance-360-chroma-safe-v1"
PREVIEW_WIDTH = 640
PREVIEW_HEIGHT = 360
PREVIEW_CRF = 27
PREVIEW_THREADS = 2
PREVIEW_PRESET = "ultrafast"
PREVIEW_AUDIO_BITRATE = "96k"
PROXY_WIDTH = 640
PROXY_HEIGHT = 360
PROXY_CRF = 30
USE_PROXIES = True


def configure_preview_profile(name: str) -> str:
    """Select a known profile and update the runtime settings used by workers."""
    global PREVIEW_PROFILE_NAME, PREVIEW_PROFILE_ID
    global PREVIEW_WIDTH, PREVIEW_HEIGHT, PREVIEW_CRF
    global PROXY_WIDTH, PROXY_HEIGHT, PROXY_CRF, USE_PROXIES

    selected = name if name in PROFILE_OPTIONS else "Performance"
    values = PROFILE_OPTIONS[selected]
    PREVIEW_PROFILE_NAME = selected
    PREVIEW_PROFILE_ID = (
        f"composite-{selected.lower()}-{values['width']}x{values['height']}-chroma-safe-v1"
    )
    PREVIEW_WIDTH = int(values["width"])
    PREVIEW_HEIGHT = int(values["height"])
    PREVIEW_CRF = int(values["crf"])
    PROXY_WIDTH = int(values["proxy_width"])
    PROXY_HEIGHT = int(values["proxy_height"])
    PROXY_CRF = int(values["proxy_crf"])
    USE_PROXIES = bool(values["use_proxies"])

    # The proxy marker includes its profile. Rebuilding a proxy after a quality
    # change cannot accidentally reuse a lower-resolution file as a clear one.
    try:
        from app.media import proxy_paths
        proxy_paths.PROXY_PROFILE_ID = (
            f"proxy-{selected.lower()}-{PROXY_WIDTH}x{PROXY_HEIGHT}-v1"
        )
    except Exception:
        pass
    return selected


# Keep the marker in sync even when no explicit setting has been loaded yet.
configure_preview_profile("Performance")
