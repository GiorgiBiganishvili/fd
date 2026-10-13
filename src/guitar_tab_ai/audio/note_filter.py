"""Conservative candidate selection before guitar fingering assignment.

Raw model candidates remain in the audio cache. Filtering never edits manual
notes or claims to separate a guitar from a mixed recording.
"""
from __future__ import annotations

from guitar_tab_ai.core.config import AppConfig
from guitar_tab_ai.core.events import NoteEvent, Technique
from guitar_tab_ai.guitar.model import GuitarModel


def filter_notes(notes: list[NoteEvent], guitar: GuitarModel, config: AppConfig) -> list[NoteEvent]:
    candidates = sorted((n.model_copy(deep=True) for n in notes
                         if (guitar.candidates(n.midi, n.technique)
                             or guitar.candidates(n.midi, Technique.HARMONIC))
                         and n.end-n.start >= 0.10
                         and n.confidence.audio >= config.minimum_audio_confidence),
                        key=lambda n: (n.start, -n.confidence.audio, n.midi))
    # Overlapping detections of one pitch are one sustained event, rather than
    # a chord that the solver has to scatter across multiple strings.
    by_pitch: dict[int, NoteEvent] = {}
    merged: list[NoteEvent] = []
    for note in candidates:
        previous = by_pitch.get(note.midi)
        if previous and note.start < previous.end-0.025:
            previous.end = max(previous.end, note.end)
            previous.confidence.audio = max(previous.confidence.audio, note.confidence.audio)
        else:
            merged.append(note)
            by_pitch[note.midi] = note
    if config.transcription_profile != "melody":
        return sorted(merged, key=lambda n: (n.start, n.midi))
    # Explicit monophonic mode: keep the strongest concurrent event; a new
    # attack can replace a decaying tail, but not a stronger sustained note.
    result: list[NoteEvent] = []
    for note in sorted(merged, key=lambda n: (n.start, -n.confidence.audio)):
        if result and note.start < result[-1].end:
            previous = result[-1]
            if note.confidence.audio < previous.confidence.audio*0.85:
                continue
            if note.start-previous.start < 0.10:
                if note.confidence.audio > previous.confidence.audio:
                    result[-1] = note
                continue
            previous.end = note.start
        result.append(note)
    return result
