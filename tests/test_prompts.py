"""Tests for prompt building and (crucially) response parsing."""

from cinesfx.brain.prompts import build_user_prompt, parse_cue_response
from cinesfx.models import Keyframe, Scene, SfxKind
from pathlib import Path


def _scene() -> Scene:
    return Scene(
        index=0,
        start_seconds=0.0,
        end_seconds=5.0,
        keyframes=(Keyframe(Path("/tmp/x.jpg"), 2.5),),
    )


def test_build_user_prompt_mentions_schema_and_scene():
    prompt = build_user_prompt([_scene()], {"clip_name": "hero", "duration_seconds": 5.0})
    assert "scene_index" in prompt
    assert "hero" in prompt
    assert "JSON array" in prompt


def test_parse_plain_json_array():
    text = """[
      {"scene_index": 0, "description": "door creak", "query": "wooden door creak",
       "kind": "spot", "onset_seconds": 1.2, "duration_seconds": 0, "gain_db": -3,
       "pan": 0.5, "distance": 0.2, "diegetic": true, "confidence": 0.9}
    ]"""
    cues = parse_cue_response(text)
    assert len(cues) == 1
    cue = cues[0]
    assert cue.query == "wooden door creak"
    assert cue.kind is SfxKind.SPOT
    assert cue.pan == 0.5


def test_parse_tolerates_markdown_fences_and_prose():
    text = "Here you go:\n```json\n[{\"query\": \"whoosh\", \"description\": \"whoosh\"}]\n```"
    cues = parse_cue_response(text)
    assert len(cues) == 1
    assert cues[0].query == "whoosh"


def test_parse_clamps_out_of_range_values():
    text = '[{"query": "boom", "pan": 5, "distance": -2, "confidence": 9}]'
    cue = parse_cue_response(text)[0]
    assert cue.pan == 1.0
    assert cue.distance == 0.0
    assert cue.confidence == 1.0


def test_parse_falls_back_to_description_as_query():
    text = '[{"description": "distant thunder"}, {"query": "click"}]'
    cues = parse_cue_response(text)
    assert len(cues) == 2
    assert cues[0].query == "distant thunder"
    assert cues[1].query == "click"


def test_parse_skips_entries_with_neither_query_nor_description():
    text = '[{"gain_db": -3}, {"query": "click"}]'
    cues = parse_cue_response(text)
    assert len(cues) == 1
    assert cues[0].query == "click"


def test_parse_returns_empty_on_garbage():
    assert parse_cue_response("not json at all") == []
    assert parse_cue_response("") == []
