"""Confidence-aware fusion; unsynchronized OCR never invents note timing."""
from __future__ import annotations

from guitar_tab_ai.core.config import AppConfig
from guitar_tab_ai.core.events import AudioResult, Confidence, Evidence, NoteEvent, Technique
from guitar_tab_ai.core.timeline import TemporalIndex
from guitar_tab_ai.guitar.fingering_solver import FingeringSolver
from guitar_tab_ai.guitar.model import GuitarModel


class FusionEngine:
    def __init__(self, guitar: GuitarModel, config: AppConfig):
        self.guitar, self.config = guitar, config

    def fuse(self, audio: AudioResult, video: list[Evidence], ocr: list[Evidence],
             manual: list[NoteEvent] | None = None) -> list[NoteEvent]:
        evidence = [e for e in video+ocr if e.synchronized]
        index = TemporalIndex(evidence, lambda e: e.time)
        audio_index = TemporalIndex(audio.notes, lambda n: n.start)
        notes = [n.model_copy(deep=True) for n in audio.notes]
        for n in notes:
            nearby = index.around(n.start)
            harmonics = [e for e in nearby if e.technique == Technique.HARMONIC
                         and e.confidence >= 0.7 and abs(e.time-n.start) < 0.15
                         and self.guitar.midi_at(e.position, e.technique) == n.midi]
            if harmonics:
                # A matching pitch alone cannot distinguish a 12th-fret touch
                # from a stopped octave. Require explicit technique evidence.
                n.technique = Technique.HARMONIC
            chord_notes = audio_index.around(n.start)
            compatible: list[Evidence] = []
            for e in nearby:
                pitch = self.guitar.midi_at(e.position, e.technique)
                if pitch == n.midi:
                    compatible.append(e)
                    n.sources = sorted(set(n.sources+[e.source]))
                elif (e.confidence > 0.7 and n.confidence.audio < 0.45
                      and e.confidence * (self.config.weights.ocr if e.source == "ocr"
                                         else self.config.weights.video)
                      > n.confidence.audio*self.config.weights.audio
                      and not any(abs(other.start-n.start) < 0.15 and other.midi == pitch
                                  for other in chord_notes)):
                    n.midi = pitch
                    if e.technique is not None:
                        n.technique = e.technique
                    compatible.append(e)
                    n.sources = sorted(set(n.sources+[e.source]))
                elif e.confidence > 0.6 and not any(
                        abs(other.start-n.start) < 0.15 and other.midi == pitch for other in chord_notes):
                    n.uncertain = True
            n.confidence.video = max((e.confidence for e in compatible if e.source == "video"), default=0)
            n.confidence.ocr = max((e.confidence for e in compatible if e.source == "ocr"), default=0)
        # Time-linked highlight observations may form notes when audio is absent.
        # Plain finger contacts cannot: a visible finger does not prove a sound.
        for e in sorted(ocr, key=lambda e: e.time):
            if not e.synchronized or e.confidence < 0.7:
                continue
            pitch = self.guitar.midi_at(e.position, e.technique)
            if any(abs(n.start-e.time) < 0.15 and n.midi == pitch for n in notes):
                continue
            notes.append(NoteEvent(start=e.time, end=e.time+0.2, midi=pitch,
                                   technique=e.technique,
                                   confidence=Confidence(ocr=e.confidence), sources=["ocr"]))
        for m in manual or []:
            notes = [n for n in notes if not (n.start < m.end and n.end > m.start
                                              and (n.midi == m.midi or n.string == m.string))]
            notes.append(m.model_copy(deep=True))
        solved = FingeringSolver(self.guitar, self.config).solve(notes, evidence)
        solved_index = TemporalIndex(solved, lambda n: n.start)
        for n in solved:
            conflicting = [e for e in index.around(n.start) if e.confidence > 0.6
                           and self.guitar.midi_at(e.position, e.technique) != n.midi
                           and not any(abs(other.start-n.start) < 0.15
                                       and other.midi == self.guitar.midi_at(e.position, e.technique)
                                       for other in solved_index.around(n.start))]
            if conflicting:
                n.uncertain = True
                n.confidence.final = min(n.confidence.final, 0.5)
        return solved
