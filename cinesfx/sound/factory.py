"""Factory that instantiates the configured sound provider."""

from __future__ import annotations

from cinesfx.config import AppConfig
from cinesfx.sound.base import SoundProvider, SoundProviderError

# Platforms with no public developer API. Audiio and Musicbed are enterprise /
# bespoke only, so they share one parameterised REST provider that partners can
# point at their credentials; without them it raises a clear, actionable error.
_PARTNER_ENV = {
    "audiio": ("AUDIIO_API_BASE", "AUDIIO_API_TOKEN"),
    "musicbed": ("MUSICBED_API_BASE", "MUSICBED_API_TOKEN"),
}


def create_sound_provider(config: AppConfig) -> SoundProvider:
    """Return the sound provider selected in ``config``.

    Args:
        config: The loaded application configuration.

    Returns:
        A ready-to-use :class:`SoundProvider`.

    Raises:
        SoundProviderError: If the selected provider is unknown or unusable.
    """
    choice = config.sound_provider
    settings = config.sound_settings()
    cache_dir = config.cache_dir()

    if choice == "epidemic":
        from cinesfx.sound.epidemic import EpidemicSoundProvider

        return EpidemicSoundProvider(settings, cache_dir)
    if choice == "freesound":
        from cinesfx.sound.freesound import FreesoundProvider

        return FreesoundProvider(settings, cache_dir)
    if choice == "artlist":
        from cinesfx.sound.artlist import ArtlistProvider

        return ArtlistProvider(settings, cache_dir)
    if choice == "splice":
        from cinesfx.sound.splice import SpliceProvider

        return SpliceProvider(settings, cache_dir)
    if choice == "soundly":
        from cinesfx.sound.soundly import SoundlyProvider

        return SoundlyProvider(settings, cache_dir)
    if choice == "local":
        from cinesfx.sound.local import LocalFolderProvider

        return LocalFolderProvider(settings, cache_dir)
    if choice in _PARTNER_ENV:
        from cinesfx.sound.partner import PartnerRestProvider

        base_env, token_env = _PARTNER_ENV[choice]
        return PartnerRestProvider(choice, base_env, token_env, settings, cache_dir)

    raise SoundProviderError(f"Unknown sound provider '{choice}'.")
