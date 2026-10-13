"""Guitar geometry. String 1 is the highest string; frets are relative to capo."""
from __future__ import annotations

import re

from pydantic import Field, model_validator

from guitar_tab_ai.core.events import Position, Record, Technique

# Touch nodes measured relative to the sounding nut/capo. The node number is
# not the interval: touching 5 gives the fourth partial, 24 semitones higher.
NATURAL_HARMONICS = {5: 24, 7: 19, 12: 12, 19: 19, 24: 24}

TUNINGS: dict[str, tuple[int, ...]] = {
    "Standard": (40, 45, 50, 55, 59, 64),
    "Drop D": (38, 45, 50, 55, 59, 64),
    "D Standard": (38, 43, 48, 53, 57, 62),
    "Drop C": (36, 43, 48, 53, 57, 62),
    "Open D": (38, 45, 50, 54, 57, 62),
    "Open G": (38, 43, 50, 55, 59, 62),
    "7 Standard": (35, 40, 45, 50, 55, 59, 64),
    "8 Standard": (30, 35, 40, 45, 50, 55, 59, 64),
}


def pitch_to_midi(pitch: str) -> int:
    match = re.fullmatch(r"([A-Ga-g])([#b]?)(-?\d+)", pitch.strip())
    if not match:
        raise ValueError(f"Invalid pitch: {pitch}")
    letter, accidental, octave = match.groups()
    semitone = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[letter.upper()]
    midi = (int(octave) + 1) * 12 + semitone + {"": 0, "#": 1, "b": -1}[accidental]
    if not 0 <= midi <= 127:
        raise ValueError("Pitch outside MIDI range")
    return midi


class GuitarModel(Record):
    tuning_name: str = "Standard"
    open_strings: tuple[int, ...] = TUNINGS["Standard"]  # low to high
    frets: int = Field(24, ge=1, le=36)
    capo: int = Field(0, ge=0, le=12)

    @model_validator(mode="after")
    def validate_guitar(self) -> GuitarModel:
        if not 6 <= len(self.open_strings) <= 8:
            raise ValueError("Only 6, 7 or 8 strings are supported")
        if self.capo > self.frets:
            raise ValueError("Capo is beyond the last fret")
        if any(not 0 <= n <= 127 for n in self.open_strings):
            raise ValueError("Invalid open-string MIDI pitch")
        return self

    @property
    def strings(self) -> int:
        return len(self.open_strings)

    def midi_at(self, position: Position, technique: Technique | None = None) -> int:
        if position.string > self.strings or position.fret > self.frets - self.capo:
            raise ValueError("Position is outside this guitar")
        interval = position.fret
        if technique == Technique.HARMONIC:
            if position.fret not in NATURAL_HARMONICS:
                raise ValueError("Натуральный флажолет: поддерживаются узлы 5, 7, 12, 19 и 24 от капо")
            interval = NATURAL_HARMONICS[position.fret]
        return self.open_strings[-position.string] + self.capo + interval

    def candidates(self, midi: int, technique: Technique | None = None) -> list[Position]:
        if technique == Technique.HARMONIC:
            return [Position(string=s, fret=fret)
                    for s in range(1, self.strings+1)
                    for fret, interval in NATURAL_HARMONICS.items()
                    if fret <= self.frets-self.capo
                    and self.open_strings[-s]+self.capo+interval == midi]
        return [Position(string=s, fret=midi - self.open_strings[-s] - self.capo)
                for s in range(1, self.strings + 1)
                if 0 <= midi - self.open_strings[-s] - self.capo <= self.frets - self.capo]

    @classmethod
    def preset(cls, name: str, capo: int = 0, frets: int = 24) -> GuitarModel:
        return cls(tuning_name=name, open_strings=TUNINGS[name], capo=capo, frets=frets)


def fret_fraction(fret: float) -> float:
    return 1 - 2 ** (-fret / 12)
