"""Audio level model for the player's dB meter (no Qt dependency).

Level = the project mix at the playhead, computed with the same gain chain the
render snapshot uses:  track volume x clip volume, 0 when the track or the clip
is muted.  Source loudness comes from a per-file peak envelope decoded once by
ffmpeg in a background thread (30 values / second).
"""
from __future__ import annotations

import math
import subprocess
import sys
import threading
from array import array
from pathlib import Path

MIN_DB = -60.0
ENV_RATE = 30            # envelope values per second
_SAMPLE_RATE = 8000
_WINDOW = _SAMPLE_RATE // ENV_RATE


# dBFS threshold at which each meter segment (bottom -> top) lights up.
SEGMENT_DB = (-54.0, -42.0, -30.0, -18.0, -8.0, -2.0)


def lit_segments(db: float) -> int:
    """How many meter segments are on for a level in dBFS."""
    return sum(1 for threshold in SEGMENT_DB if db >= threshold)


def gain_to_db(amplitude: float) -> float:
    if amplitude <= 1e-6:
        return MIN_DB
    return max(MIN_DB, 20.0 * math.log10(amplitude))


def clip_gain(track: dict, clip: dict) -> float:
    if track.get("muted", False) or clip.get("clip_muted", False):
        return 0.0
    return max(0.0, min(2.0, float(track.get("volume", 1.0)) * float(clip.get("volume", 1.0))))


def project_level_db(tracks, t: float, amp_at) -> float:
    """dB of the summed mix at timeline time ``t`` (seconds).

    ``amp_at(path, source_seconds)`` returns the 0..1 peak of the source at that
    moment (0 when unknown / silent).
    """
    power = 0.0
    for track in tracks:
        if track.get("base") not in ("V", "A"):
            continue
        for clip in track.get("clips", []):
            if str(clip.get("kind", "")).lower() not in ("video", "audio"):
                continue
            start = float(clip.get("start", 0.0))
            if not (start <= t < start + float(clip.get("duration", 0.0))):
                continue
            gain = clip_gain(track, clip)
            if gain <= 0.0:
                continue
            src = float(clip.get("source_in", 0.0)) + (t - start)
            level = amp_at(str(clip.get("path", "")), src) * gain
            power += level * level
    return gain_to_db(math.sqrt(power))


class PeakCache:
    """Lazy background decode of per-file peak envelopes."""

    def __init__(self, ffmpeg: str | None):
        self.ffmpeg = str(ffmpeg) if ffmpeg else None
        self._env: dict[str, array] = {}
        self._pending: set[str] = set()
        self._lock = threading.Lock()

    def amp_at(self, path: str, seconds: float) -> float:
        env = self._env.get(path)
        if env is None:
            self._request(path)
            return 0.0
        i = int(max(0.0, seconds) * ENV_RATE)
        return env[i] if 0 <= i < len(env) else 0.0

    def ready(self, path: str) -> bool:
        return path in self._env

    def _request(self, path: str):
        if not self.ffmpeg:
            return
        with self._lock:
            if path in self._pending or path in self._env:
                return
            self._pending.add(path)
        threading.Thread(target=self._decode, args=(path,), daemon=True).start()

    def _decode(self, path: str):
        env = array("f")
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
            proc = subprocess.Popen(
                [self.ffmpeg, "-v", "quiet", "-i", path, "-vn", "-ac", "1",
                 "-ar", str(_SAMPLE_RATE), "-f", "s16le", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, creationflags=flags,
            )
            window_bytes = _WINDOW * 2
            carry = b""
            while True:
                chunk = proc.stdout.read(window_bytes * 64)
                if not chunk:
                    break
                carry += chunk
                usable = len(carry) - (len(carry) % window_bytes)
                block, carry = carry[:usable], carry[usable:]
                samples = array("h")
                samples.frombytes(block)
                for i in range(0, len(samples), _WINDOW):
                    peak = max(map(abs, samples[i:i + _WINDOW]))
                    env.append(min(1.0, peak / 32768.0))
            proc.wait(timeout=5)
        except Exception:
            pass
        with self._lock:
            self._env[path] = env
            self._pending.discard(path)
