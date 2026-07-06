"""Google Gemini brain provider (vision-capable)."""

from __future__ import annotations

from typing import Any

from cinesfx.brain.base import BrainError, BrainProvider
from cinesfx.brain.prompts import SYSTEM_INSTRUCTION, build_user_prompt, parse_cue_response
from cinesfx.config import AppConfig
from cinesfx.logging_utils import get_logger
from cinesfx.models import Scene, SfxCue

_log = get_logger("brain.gemini")


class GeminiBrain(BrainProvider):
    """Understands scenes with Google's Gemini models via google-generativeai."""

    name = "gemini"

    def __init__(self, settings: dict[str, Any]) -> None:
        super().__init__(settings)
        self._model_name = settings.get("model", "gemini-2.5-flash")
        self._temperature = float(settings.get("temperature", 0.4))
        self._max_tokens = int(settings.get("max_output_tokens", 4096))
        self._api_key = AppConfig.secret("GEMINI_API_KEY")
        if not self._api_key:
            raise BrainError(
                "GEMINI_API_KEY is not set. Add it to your .env to use the Gemini brain."
            )

    def describe_and_plan(
        self, scenes: list[Scene], context: dict[str, Any]
    ) -> list[SfxCue]:
        try:
            import google.generativeai as genai
            from PIL import Image
        except ImportError as exc:
            raise BrainError(
                "The Gemini brain needs 'google-generativeai' and 'Pillow'. "
                "Install with: pip install google-generativeai Pillow"
            ) from exc

        genai.configure(api_key=self._api_key)
        model = genai.GenerativeModel(
            model_name=self._model_name,
            system_instruction=SYSTEM_INSTRUCTION,
        )

        prompt = build_user_prompt(scenes, context)
        parts: list[Any] = [prompt]
        for image_path in self._collect_images(scenes):
            try:
                parts.append(Image.open(image_path))
            except OSError as exc:  # skip unreadable frame, keep going
                _log.warning("Skipping unreadable key-frame %s: %s", image_path, exc)

        try:
            response = model.generate_content(
                parts,
                generation_config={
                    "temperature": self._temperature,
                    "max_output_tokens": self._max_tokens,
                },
            )
            text = response.text or ""
        except Exception as exc:  # noqa: BLE001 - surface a clean error
            raise BrainError(f"Gemini request failed: {exc}") from exc

        cues = parse_cue_response(text)
        _log.info("Gemini planned %d cue(s)", len(cues))
        return cues
