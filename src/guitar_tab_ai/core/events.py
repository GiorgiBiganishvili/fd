"""Versioned, validated data contracts shared by analyzers, storage and UI."""
from __future__ import annotations

from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid", allow_inf_nan=False)


class Technique(StrEnum):
    HAMMER_ON = "hammer_on"
    PULL_OFF = "pull_off"
    SLIDE_UP = "slide_up"
    SLIDE_DOWN = "slide_down"
    BEND = "bend"
    BEND_RELEASE = "bend_release"
    VIBRATO = "vibrato"
    PALM_MUTE = "palm_mute"
    DEAD_NOTE = "dead_note"
    HARMONIC = "harmonic"
    ARTIFICIAL_HARMONIC = "artificial_harmonic"
    TAP = "tap"
    LET_RING = "let_ring"


class Confidence(Record):
    audio: float = Field(0, ge=0, le=1)
    video: float = Field(0, ge=0, le=1)
    ocr: float = Field(0, ge=0, le=1)
    fingering: float = Field(0, ge=0, le=1)
    final: float = Field(0, ge=0, le=1)


class Position(Record):
    string: int = Field(ge=1, le=8)
    fret: int = Field(ge=0, le=36)


class NoteEvent(Record):
    id: str = Field(default_factory=lambda: str(uuid4()))
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)
    midi: int = Field(ge=0, le=127)
    string: int | None = Field(None, ge=1, le=8)
    fret: int | None = Field(None, ge=0, le=36)
    finger: int | None = Field(None, ge=0, le=4)
    technique: Technique | None = None
    velocity: int = Field(80, ge=1, le=127)
    confidence: Confidence = Field(default_factory=Confidence)
    sources: list[str] = Field(default_factory=list)
    alternatives: list[Position] = Field(default_factory=list)
    manual_override: bool = False
    uncertain: bool = True

    @model_validator(mode="after")
    def valid_interval(self) -> NoteEvent:
        if self.end <= self.start:
            raise ValueError("Note end must be after start")
        if (self.string is None) != (self.fret is None):
            raise ValueError("String and fret must both be present or absent")
        return self

    @property
    def pitch(self) -> str:
        names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
        return f"{names[self.midi % 12]}{self.midi // 12 - 1}"


class ChordEvent(Record):
    start: float
    end: float
    note_ids: list[str]
    name: str | None = None
    direction: str | None = None


class SuppressedEvent(Record):
    """A user's deletion/move of an automatic onset, retained across reanalysis."""
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)
    midi: int = Field(ge=0, le=127)


class Rhythm(Record):
    tempo: float | None = Field(None, gt=0, allow_inf_nan=False)
    beats: list[float] = Field(default_factory=list)
    time_signature: tuple[int, int] = (4, 4)
    confidence: float = Field(0, ge=0, le=1)


class Evidence(Record):
    """An observation at a timestamp, never a claim that a finger sounded."""
    time: float = Field(ge=0, allow_inf_nan=False)
    position: Position
    confidence: float = Field(ge=0, le=1)
    source: str
    synchronized: bool = True
    hand_center_fret: float | None = None


class AudioResult(Record):
    notes: list[NoteEvent] = Field(default_factory=list)
    rhythm: Rhythm = Field(default_factory=Rhythm)
    quality: float = Field(0, ge=0, le=1)
    backend: str = ""
    warnings: list[str] = Field(default_factory=list)


def group_chords(notes: list[NoteEvent], tolerance: float = 0.035) -> list[ChordEvent]:
    """Group near-simultaneous onsets without quantizing fingerstyle arpeggios."""
    groups: list[list[NoteEvent]] = []
    for note in sorted(notes, key=lambda n: (n.start, n.midi)):
        if groups and note.start - groups[-1][0].start <= tolerance:
            groups[-1].append(note)
        else:
            groups.append([note])
    return [ChordEvent(start=g[0].start, end=min(n.end for n in g), note_ids=[n.id for n in g])
            for g in groups if len(g) > 1]
