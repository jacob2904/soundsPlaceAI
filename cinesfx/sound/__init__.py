"""Pluggable sound-effect platform providers."""

from cinesfx.sound.base import SoundProvider
from cinesfx.sound.factory import create_sound_provider

__all__ = ["SoundProvider", "create_sound_provider"]
