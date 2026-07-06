"""Factory that instantiates the configured brain provider."""

from __future__ import annotations

from cinesfx.brain.base import BrainError, BrainProvider
from cinesfx.config import AppConfig


def create_brain(config: AppConfig) -> BrainProvider:
    """Return the brain provider selected in ``config``.

    Providers are imported lazily so that a user only needs the SDK for the brain
    they actually use.

    Args:
        config: The loaded application configuration.

    Returns:
        A ready-to-use :class:`BrainProvider`.

    Raises:
        BrainError: If the selected brain is unknown or cannot be constructed.
    """
    settings = config.brain_settings()
    choice = config.brain

    if choice == "gemini":
        from cinesfx.brain.gemini import GeminiBrain

        return GeminiBrain(settings)
    if choice == "openai":
        from cinesfx.brain.openai_provider import OpenAIBrain

        return OpenAIBrain(settings)
    if choice == "claude":
        from cinesfx.brain.claude import ClaudeBrain

        return ClaudeBrain(settings)

    raise BrainError(f"Unknown brain provider '{choice}'.")
