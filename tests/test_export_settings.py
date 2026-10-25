from app.export.codec_profiles import PROFILES, RESOLUTIONS, export_options


def test_export_resolutions_cover_requested_sizes_and_4k_is_uhd():
    assert RESOLUTIONS["240p (Low)"] == (426, 240)
    assert RESOLUTIONS["480p (SD)"] == (854, 480)
    assert RESOLUTIONS["720p (HD)"] == (1280, 720)
    assert RESOLUTIONS["1080p (Full HD)"] == (1920, 1080)
    assert RESOLUTIONS["1440p (1.4K / QHD)"] == (2560, 1440)
    assert RESOLUTIONS["2K (2048 × 1080)"] == (2048, 1080)
    assert RESOLUTIONS["4K UHD (3840 × 2160)"] == (3840, 2160)
    assert all(width % 2 == height % 2 == 0 for width, height in RESOLUTIONS.values())


def test_export_profiles_provide_codec_and_audio_args():
    for name, profile in PROFILES.items():
        options = export_options(name, profile["quality_default"])
        assert options["profile_id"] == profile["id"]
        assert options["extension"] == profile["extension"]
        assert options["video_args"]
        assert options["audio_args"]


def test_export_speed_presets_are_applied_for_h264():
    fast = export_options("H.264 (MP4)", 20, "fast")
    balanced = export_options("H.264 (MP4)", 20, "balanced")
    quality = export_options("H.264 (MP4)", 20, "quality")
    assert fast["video_args"][fast["video_args"].index("-preset") + 1] == "ultrafast"
    assert balanced["video_args"][balanced["video_args"].index("-preset") + 1] == "medium"
    assert quality["video_args"][quality["video_args"].index("-preset") + 1] == "slow"
