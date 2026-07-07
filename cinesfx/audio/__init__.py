"""Audio post-processing (baking gain / pan / fades into SFX before placement)."""

from cinesfx.audio.render import AudioRenderer, build_filter_chain, pan_gains

__all__ = ["AudioRenderer", "build_filter_chain", "pan_gains"]
