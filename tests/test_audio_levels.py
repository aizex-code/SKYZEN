import importlib.util
import math
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

_p = Path(__file__).resolve().parents[1] / "app" / "audio_meter" / "levels.py"
_s = importlib.util.spec_from_file_location("levels", _p)
L = importlib.util.module_from_spec(_s)
_s.loader.exec_module(L)


def amp(_path, _t):
    return 0.5  # -6.02 dBFS source


def clip(**kw):
    base = {"kind": "Audio", "path": "a.wav", "start": 0.0, "duration": 10.0, "volume": 1.0}
    base.update(kw)
    return base


def test_unity_gain_matches_source_level():
    db = L.project_level_db([{"base": "A", "clips": [clip()]}], 1.0, amp)
    assert abs(db - 20 * math.log10(0.5)) < 1e-6


def test_track_and_clip_volume_scale_the_level():
    tr = {"base": "A", "volume": 0.5, "clips": [clip(volume=0.5)]}
    db = L.project_level_db([tr], 1.0, amp)
    assert abs(db - 20 * math.log10(0.5 * 0.5 * 0.5)) < 1e-6


def test_mute_and_silence_outside_clip():
    muted = {"base": "A", "muted": True, "clips": [clip()]}
    assert L.project_level_db([muted], 1.0, amp) == L.MIN_DB
    clip_muted = {"base": "A", "clips": [clip(clip_muted=True)]}
    assert L.project_level_db([clip_muted], 1.0, amp) == L.MIN_DB
    assert L.project_level_db([{"base": "A", "clips": [clip()]}], 11.0, amp) == L.MIN_DB


def test_layers_sum_and_images_are_silent():
    tracks = [
        {"base": "A", "clips": [clip()]},
        {"base": "V", "clips": [clip(kind="Video")]},
        {"base": "V", "clips": [clip(kind="Image")]},
    ]
    db = L.project_level_db(tracks, 1.0, amp)
    assert abs(db - 20 * math.log10(0.5 * math.sqrt(2))) < 1e-6


def test_source_in_offsets_envelope_lookup():
    seen = []
    L.project_level_db([{"base": "A", "clips": [clip(start=2.0, source_in=5.0)]}], 3.0,
                       lambda p, t: seen.append(t) or 0.1)
    assert seen == [6.0]


def test_ffmpeg_envelope_roundtrip():
    ff = shutil.which("ffmpeg")
    if not ff:
        return
    d = tempfile.mkdtemp()
    wav = str(Path(d) / "t.wav")
    subprocess.run([ff, "-v", "quiet", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2", "-af", "volume=4", wav], check=True)
    cache = L.PeakCache(ff)
    cache.amp_at(wav, 0.0)
    for _ in range(100):
        if cache.ready(wav):
            break
        time.sleep(0.05)
    assert cache.ready(wav)
    assert 0.4 < cache.amp_at(wav, 1.0) < 0.6
    assert cache.amp_at(wav, 5.0) == 0.0


def test_meter_segments_follow_level():
    assert L.lit_segments(L.MIN_DB) == 0
    assert L.lit_segments(-20.0) == 3
    assert L.lit_segments(0.0) == 6
