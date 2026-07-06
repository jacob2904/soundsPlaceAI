"""OpenAI brain provider (vision-capable chat models)."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from cinesfx.brain.base import BrainError, BrainProvider
from cinesfx.brain.prompts import SYSTEM_INSTRUCTION, build_user_prompt, parse_cue_response
from cinesfx.config import AppConfig
from cinesfx.logging_utils import get_logger
from cinesfx.models import Scene, SfxCue

_log = get_logger("brain.openai")


class OpenAIBrain(BrainProvider):
    """Understands scenes with OpenAI vision-capable chat models."""

    name = "openai"

    def __init__(self, settings: dict[str, Any]) -> None:
        super().__init__(settings)
        self._model_name = settings.get("model", "gpt-4o")
        self._temperature = float(settings.get("temperature", 0.4))
        self._max_tokens = int(settings.get("max_output_tokens", 4096))
        self._api_key = AppConfig.secret("OPENAI_API_KEY")
        if not self._api_key:
            raise BrainError(
                "OPENAI_API_KEY is not set. Add it to your .env to use the OpenAI brain."
            )

    def describe_and_plan(
        self, scenes: list[Scene], context: dict[str, Any]
    ) -> list[SfxCue]:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise BrainError(
                "The OpenAI brain needs 'openai'. Install with: pip install openai"
            ) from exc

        client = OpenAI(api_key=self._api_key)
        prompt = build_user_prompt(scenes, context)

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image_path in self._collect_images(scenes):
            data_url = self._encode_image(image_path)
            if data_url:
                content.append(
                    {"type": "image_url", "image_url": {"url": data_url}}
                )

        try:
            response = client.chat.completions.create(
                model=self._model_name,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                messages=[
                    {"role": "system", "content": SYSTEM_INSTRUCTION},
                    {"role": "user", "content": content},
                ],
            )
            text = response.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001 - surface a clean error
            raise BrainError(f"OpenAI request failed: {exc}") from exc

        cues = parse_cue_response(text)
        _log.info("OpenAI planned %d cue(s)", len(cues))
        return cues

    @staticmethod
    def _encode_image(image_path: Path) -> str | None:
        """Return a base64 data URL for ``image_path`` or ``None`` if unreadable."""
        try:
            raw = image_path.read_bytes()
        except OSError as exc:
            _log.warning("Skipping unreadable key-frame %s: %s", image_path, exc)
            return None
        encoded = base64.b64encode(raw).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"
