"""Skyzen timeline connector; imported by the main application."""
from .core import TimelinePanel
from .timebar import timemarker as _timemarker

_timemarker.apply(TimelinePanel)

__all__ = ["TimelinePanel"]
