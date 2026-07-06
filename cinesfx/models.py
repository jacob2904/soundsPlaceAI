"""Typed data model shared by every agent in the pipeline.

These dataclasses are the *contracts* between agents. Keeping them free of any
Resolve / network / SDK imports means each agent can be unit-tested in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class SfxKind(str, Enum):
    """High-level category of a placed sound, used for gain/track defaults."""

    SPOT = "spot"          # a discrete, on-screen event (footstep, door, impact)
    AMBIENCE = "ambience"  # a continuous bed (room tone, wind, city)
    TRANSITION = "transition"  # whooshes / risers spanning a cut


@dataclass(frozen=True)
class ClipSelection:
    """A single timeline clip the user asked us to sound-design.

    Attributes:
        item_id: Resolve unique id of the timeline item (for safe re-lookup).
        name: Human-readable clip name (for logs/UI).
        source_path: Absolute path to the source media file on disk.
        timeline_start_frame: Absolute start frame on the timeline.
        timeline_end_frame: Absolute end frame on the timeline (exclusive).
        source_start_seconds: In-point within the source file, in seconds.
        source_end_seconds: Out-point within the source file, in seconds.
        fps: Timeline frame rate (frames per second).
    """

    item_id: str
    name: str
    source_path: str
    timeline_start_frame: int
    timeline_end_frame: int
    source_start_seconds: float
    source_end_seconds: float
    fps: float

    @property
    def duration_seconds(self) -> float:
        """Return the on-screen duration of the clip in seconds."""
        return max(0.0, self.source_end_seconds - self.source_start_seconds)


@dataclass(frozen=True)
class Keyframe:
    """One extracted still used to describe a shot to the brain.

    Attributes:
        image_path: Path to the (small, downscaled) JPEG on disk.
        clip_seconds: Timestamp of the frame, relative to the clip start.
    """

    image_path: Path
    clip_seconds: float


@dataclass(frozen=True)
class Scene:
    """A detected shot within a selected clip.

    ``start_seconds`` / ``end_seconds`` are relative to the *clip* start, so a cue's
    onset can be added directly to the clip's timeline position.
    """

    index: int
    start_seconds: float
    end_seconds: float
    keyframes: tuple[Keyframe, ...]

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)


@dataclass
class SfxCue:
    """A single sound the brain wants placed, described abstractly.

    Timing is *clip-relative* (seconds from the clip's first frame). The
    PlacementAgent converts this to an absolute timeline record frame.

    Attributes:
        description: What the sound is (e.g. "wooden door creaks open").
        query: A search string tuned for a sound library.
        kind: SPOT / AMBIENCE / TRANSITION.
        onset_seconds: When it should start, relative to the clip.
        duration_seconds: How long it should sound (0 = use asset length).
        gain_db: Relative loudness the brain wants, in dB (0 = nominal).
        pan: Stereo position, -1 (hard left) .. +1 (hard right).
        distance: Perceived distance, 0 (close) .. 1 (far).
        diegetic: True if the sound exists in the scene's world.
        confidence: Brain's confidence, 0..1.
        scene_index: Which scene this cue belongs to.
    """

    description: str
    query: str
    kind: SfxKind = SfxKind.SPOT
    onset_seconds: float = 0.0
    duration_seconds: float = 0.0
    gain_db: float = 0.0
    pan: float = 0.0
    distance: float = 0.0
    diegetic: bool = True
    confidence: float = 0.5
    scene_index: int = 0


@dataclass(frozen=True)
class SoundAsset:
    """A concrete, licensable sound-effect returned by a SoundProvider."""

    provider: str
    asset_id: str
    title: str
    duration_seconds: float
    preview_url: Optional[str] = None
    download_url: Optional[str] = None
    local_path: Optional[Path] = None
    attribution: Optional[str] = None
    license_name: Optional[str] = None


@dataclass
class PlannedPlacement:
    """A fully-resolved instruction ready to be written to the timeline."""

    clip: ClipSelection
    cue: SfxCue
    asset: SoundAsset
    audio_file: Path
    record_frame: int          # absolute timeline frame to drop the SFX at
    track_lane: int            # 0-based lane index within the SFX track group
    gain_db: float             # final gain after spatialisation + headroom
    pan: float                 # final pan after spatialisation clamp
    fade_in_frames: int
    fade_out_frames: int


@dataclass
class PlacementPlan:
    """The complete set of placements plus a few reporting helpers."""

    placements: list[PlannedPlacement] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(self, placement: PlannedPlacement) -> None:
        self.placements.append(placement)

    @property
    def count(self) -> int:
        return len(self.placements)
