"""Anthropic Claude brain provider (vision-capable)."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from cinesfx.brain.base import BrainError, BrainProvider
from cinesfx.brain.prompts import SYSTEM_INSTRUCTION, build_user_prompt, parse_cue_response
from cinesfx.config import AppConfig
from cinesfx.logging_utils import get_logger
from cinesfx.models import Scene, SfxCue

_log = get_logger("brain.claude")


class ClaudeBrain(BrainProvider):
    """Understands scenes with Anthropic's Claude vision models."""

    name = "claude"

    def __init__(self, settings: dict[str, Any]) -> None:
        super().__init__(settings)
        self._model_name = settings.get("model", "claude-3-5-sonnet-latest")
        self._temperature = float(settings.get("temperature", 0.4))
        self._max_tokens = int(settings.get("max_output_tokens", 4096))
        self._api_key = AppConfig.secret("ANTHROPIC_API_KEY")
        if not self._api_key:
            raise BrainError(
                "ANTHROPIC_API_KEY is not set. Add it to your .env to use the Claude brain."
            )

    def describe_and_plan(
        self, scenes: list[Scene], context: dict[str, Any]
    ) -> list[SfxCue]:
        try:
            import anthropic
        except ImportError as exc:
            raise BrainError(
                "The Claude brain needs 'anthropic'. Install with: pip install anthropic"
            ) from exc

        client = anthropic.Anthropic(api_key=self._api_key)
        prompt = build_user_prompt(scenes, context)

        images = self._collect_images(
            scenes,
            per_scene_limit=context.get("brain_frames_per_scene"),
            max_total=context.get("max_images_per_request"),
        )
        content: list[dict[str, Any]] = []
        for image_path in images:
            block = self._encode_image_block(image_path)
            if block:
                content.append(block)
        content.append({"type": "text", "text": prompt})

        try:
            message = client.messages.create(
                model=self._model_name,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                system=SYSTEM_INSTRUCTION,
                messages=[{"role": "user", "content": content}],
            )
            text = "".join(
                block.text for block in message.content if block.type == "text"
            )
        except Exception as exc:  # noqa: BLE001 - surface a clean error
            raise BrainError(f"Claude request failed: {exc}") from exc

        cues = parse_cue_response(text)
        _log.info("Claude planned %d cue(s)", len(cues))
        return cues

    @staticmethod
    def _encode_image_block(image_path: Path) -> dict[str, Any] | None:
        """Return an Anthropic image content block or ``None`` if unreadable."""
        try:
            raw = image_path.read_bytes()
        except OSError as exc:
            _log.warning("Skipping unreadable key-frame %s: %s", image_path, exc)
            return None
        encoded = base64.b64encode(raw).decode("ascii")
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": encoded,
            },
        }
