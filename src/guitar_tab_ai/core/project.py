from __future__ import annotations

from uuid import uuid4

from pydantic import Field

from guitar_tab_ai.core.config import AppConfig
from guitar_tab_ai.core.events import ChordEvent, Evidence, NoteEvent, Record, Rhythm, SuppressedEvent
from guitar_tab_ai.guitar.model import GuitarModel


class MediaInfo(Record):
    duration: float = Field(gt=0, allow_inf_nan=False)
    fps: float = Field(gt=0, allow_inf_nan=False)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    has_audio: bool


class Project(Record):
    schema_version: int = 1
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str = "Новый проект"
    video_path: str = ""
    media: MediaInfo | None = None
    guitar: GuitarModel = Field(default_factory=GuitarModel)
    settings: AppConfig = Field(default_factory=AppConfig)
    notes: list[NoteEvent] = Field(default_factory=list)
    suppressed: list[SuppressedEvent] = Field(default_factory=list)
    observations: list[Evidence] = Field(default_factory=list)
    chords: list[ChordEvent] = Field(default_factory=list)
    rhythm: Rhythm = Field(default_factory=Rhythm)
    waveform: list[float] = Field(default_factory=list)
    analysis_summary: dict[str, str | float | int | bool] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    def replace_interval(self, start: float, end: float, notes: list[NoteEvent]) -> None:
        """Preserve explicit edits and notes outside the selection on reanalysis."""
        manual = [n for n in self.notes if n.manual_override and n.start < end and n.end > start]
        retained = [n for n in self.notes if n.manual_override or not (n.start < end and n.end > start)]
        fresh = [n for n in notes if not any(
            n.start < m.end and n.end > m.start and (n.midi == m.midi or n.string == m.string)
            for m in manual) and (n.manual_override or not any(
                n.midi == s.midi and abs(n.start-s.start) < 0.15 for s in self.suppressed))]
        self.notes = sorted(retained + fresh, key=lambda n: (n.start, n.midi))
