"""User-selectable FFmpeg export profiles and output dimensions."""
from __future__ import annotations

PROFILES = {
    "H.264 (MP4)": {
        "id": "h264", "extension": ".mp4",
        "video_args": lambda quality, preset="medium": ["-c:v", "libx264", "-preset", preset, "-crf", str(int(quality)), "-pix_fmt", "yuv420p", "-movflags", "+faststart"],
        "audio_args": ["-c:a", "aac", "-b:a", "192k"],
        "quality_range": (16, 30), "quality_default": 20,
    },
    "HEVC / H.265 (MP4)": {
        "id": "hevc", "extension": ".mp4",
        "video_args": lambda quality, preset="medium": ["-c:v", "libx265", "-preset", preset, "-crf", str(int(quality)), "-pix_fmt", "yuv420p", "-tag:v", "hvc1", "-movflags", "+faststart"],
        "audio_args": ["-c:a", "aac", "-b:a", "192k"],
        "quality_range": (18, 32), "quality_default": 24,
    },
    "ProRes 422 (MOV)": {
        "id": "prores", "extension": ".mov",
        "video_args": lambda quality, preset="medium": ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"],
        "audio_args": ["-c:a", "pcm_s16le"],
        "quality_range": (0, 0), "quality_default": 0,
    },
    "VP9 (WebM)": {
        "id": "vp9", "extension": ".webm",
        "video_args": lambda quality, preset="medium": ["-c:v", "libvpx-vp9", "-deadline", "good", "-cpu-used", "4" if preset == "medium" else ("6" if preset == "fast" else "2"), "-crf", str(int(quality)), "-b:v", "0", "-pix_fmt", "yuv420p"],
        "audio_args": ["-c:a", "libopus", "-b:a", "160k"],
        "quality_range": (24, 40), "quality_default": 31,
    },
}

# Dimensions are even-numbered for broad H.264/H.265 compatibility.
RESOLUTIONS = {
    "240p (Low)": (426, 240),
    "480p (SD)": (854, 480),
    "720p (HD)": (1280, 720),
    "1080p (Full HD)": (1920, 1080),
    "1440p (1.4K / QHD)": (2560, 1440),
    "2K (2048 × 1080)": (2048, 1080),
    "4K UHD (3840 × 2160)": (3840, 2160),
}


def export_options(profile_name: str, quality: int, speed: str = "balanced") -> dict:
    profile = PROFILES[profile_name]
    preset = {"fast": "ultrafast", "balanced": "medium", "quality": "slow"}.get(str(speed), "medium")
    return {
        "profile_id": profile["id"], "extension": profile["extension"],
        "video_args": profile["video_args"](quality, preset),
        "audio_args": list(profile["audio_args"]), "metadata": False,
    }
