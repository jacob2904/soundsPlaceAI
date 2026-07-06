"""Prompt construction and response parsing for brain providers.

Kept provider-agnostic so Gemini / OpenAI / Claude share one prompt + one strict
JSON schema, which makes their outputs interchangeable downstream.
"""

from __future__ import annotations

import json
from typing import Any

from cinesfx.models import Scene, SfxCue, SfxKind

SYSTEM_INSTRUCTION = (
    "You are a senior cinematic sound designer. You are given ordered key-frames "
    "from consecutive shots of a single video clip. Your job is to decide which "
    "real, recordable SOUND EFFECTS should be placed to make the clip feel "
    "cinematic and to let the viewer HEAR everything they SEE, in perfect sync. "
    "You NEVER invent music or generate audio; you only describe sound effects to "
    "search for in a licensed library. Prefer specific, on-screen, diegetic sounds "
    "(footsteps, cloth, doors, impacts, water, mechanisms) plus a supporting "
    "ambience bed per location. Be precise about timing."
)


def build_user_prompt(scenes: list[Scene], context: dict[str, Any]) -> str:
    """Return the textual instruction that accompanies the key-frame images.

    Args:
        scenes: Scenes for one clip (timings are clip-relative seconds).
        context: Extra hints (clip name, duration, max cues per scene, style).

    Returns:
        A prompt string requesting a strict JSON array of cues.
    """
    max_cues = int(context.get("max_cues_per_scene", 4))
    clip_name = context.get("clip_name", "clip")
    duration = float(context.get("duration_seconds", 0.0))
    style = context.get("style", "natural, filmic")

    scene_lines = []
    for scene in scenes:
        scene_lines.append(
            f"- scene_index {scene.index}: {scene.start_seconds:.2f}s .. "
            f"{scene.end_seconds:.2f}s ({scene.duration_seconds:.2f}s long)"
        )
    scene_block = "\n".join(scene_lines) if scene_lines else "- (single scene)"

    schema = json.dumps(
        [
            {
                "scene_index": 0,
                "description": "wooden door creaks open",
                "query": "wooden door creak open interior",
                "kind": "spot | ambience | transition",
                "onset_seconds": 0.0,
                "duration_seconds": 0.0,
                "gain_db": 0.0,
                "pan": 0.0,
                "distance": 0.0,
                "diegetic": True,
                "confidence": 0.0,
            }
        ],
        indent=2,
    )

    return (
        f"Clip: '{clip_name}', total duration {duration:.2f}s. Desired style: {style}.\n"
        f"The images provided are key-frames, in order, one or more per scene.\n"
        f"Scenes (timings are seconds relative to the clip start):\n{scene_block}\n\n"
        f"Return ONLY a JSON array (no prose, no markdown fences) of sound-effect "
        f"cues. At most {max_cues} cues per scene. Each element MUST match this "
        f"schema exactly:\n{schema}\n\n"
        "Rules:\n"
        "- onset_seconds is relative to the CLIP start and MUST fall inside the "
        "cue's scene window.\n"
        "- duration_seconds 0 means 'use the asset's natural length'.\n"
        "- pan is -1 (hard left) .. +1 (hard right) based on where the source is "
        "on screen.\n"
        "- distance is 0 (very close) .. 1 (far away).\n"
        "- gain_db is a relative loudness suggestion, roughly -24..+6.\n"
        "- Use 'ambience' kind for continuous location beds; give them the scene "
        "length as duration and a low gain.\n"
        "- Keep queries short and searchable (nouns + material + action)."
    )


def parse_cue_response(text: str) -> list[SfxCue]:
    """Parse a model's text response into a list of validated :class:`SfxCue`.

    The parser is tolerant of surrounding prose or markdown code fences.

    Args:
        text: Raw model output.

    Returns:
        A list of cues (possibly empty). Malformed entries are skipped.
    """
    payload = _extract_json_array(text)
    if payload is None:
        return []

    cues: list[SfxCue] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        description = str(entry.get("description", "")).strip()
        query = str(entry.get("query", description)).strip()
        if not query:
            continue
        cues.append(
            SfxCue(
                description=description or query,
                query=query,
                kind=_coerce_kind(entry.get("kind")),
                onset_seconds=_as_float(entry.get("onset_seconds"), 0.0),
                duration_seconds=_as_float(entry.get("duration_seconds"), 0.0),
                gain_db=_as_float(entry.get("gain_db"), 0.0),
                pan=_clamp(_as_float(entry.get("pan"), 0.0), -1.0, 1.0),
                distance=_clamp(_as_float(entry.get("distance"), 0.0), 0.0, 1.0),
                diegetic=bool(entry.get("diegetic", True)),
                confidence=_clamp(_as_float(entry.get("confidence"), 0.5), 0.0, 1.0),
                scene_index=int(_as_float(entry.get("scene_index"), 0.0)),
            )
        )
    return cues


def _extract_json_array(text: str) -> list[Any] | None:
    """Return the first JSON array found in ``text`` or ``None``."""
    if not text:
        return None
    stripped = text.strip()
    # Remove common markdown fences.
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        newline = stripped.find("\n")
        if newline != -1:
            stripped = stripped[newline + 1 :]
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def _coerce_kind(value: Any) -> SfxKind:
    try:
        return SfxKind(str(value).lower())
    except ValueError:
        return SfxKind.SPOT


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
