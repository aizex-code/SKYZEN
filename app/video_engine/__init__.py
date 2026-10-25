"""Skyzen project-preview video engine.

The UI and timeline never create a decoder per overlay. FFmpeg builds a single
composited preview stream, which the existing PlayerPanel QMediaPlayer plays.
"""
