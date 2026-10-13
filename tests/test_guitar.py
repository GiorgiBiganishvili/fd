import pytest

from guitar_tab_ai.core.config import AppConfig
from guitar_tab_ai.core.events import Confidence, Evidence, NoteEvent, Position
from guitar_tab_ai.guitar.fingering_solver import FingeringSolver, PlayabilityValidator
from guitar_tab_ai.guitar.model import GuitarModel, TUNINGS, fret_fraction, pitch_to_midi


@pytest.mark.parametrize("pitch,midi", [("E2", 40), ("B3", 59), ("E4", 64), ("Db4", 61), ("C-1", 0)])
def test_pitch_conversion(pitch, midi):
    assert pitch_to_midi(pitch) == midi


@pytest.mark.parametrize("pitch", ["H2", "E", "C11", "Db-9"])
def test_bad_pitch(pitch):
    with pytest.raises(ValueError):
        pitch_to_midi(pitch)


def test_standard_b3_and_capo_candidates():
    g = GuitarModel()
    assert {(p.string, p.fret) for p in g.candidates(59)} == {(2, 0), (3, 4), (4, 9), (5, 14), (6, 19)}
    assert Position(string=1, fret=0) in g.candidates(64)
    capo = GuitarModel(capo=2)
    assert capo.midi_at(Position(string=1, fret=0)) == 66
    assert Position(string=1, fret=22) in capo.candidates(88)
    assert not capo.candidates(39)


@pytest.mark.parametrize("name", list(TUNINGS))
def test_all_tunings_round_trip(name):
    g = GuitarModel.preset(name)
    for s in range(1, g.strings+1):
        for f in (0, 7, 12, 24):
            p = Position(string=s, fret=f)
            assert p in g.candidates(g.midi_at(p))


def test_geometry_and_ergonomics():
    assert fret_fraction(12) == pytest.approx(.5)
    assert fret_fraction(24) == pytest.approx(.75)
    s = FingeringSolver(GuitarModel(), AppConfig())
    p = Position(string=3, fret=7)
    assert s.transition_cost(p, Position(string=3, fret=8)) < s.transition_cost(p, Position(string=6, fret=19))


def test_global_fingering_and_evidence():
    notes = [NoteEvent(start=i*.2, end=i*.2+.15, midi=m, confidence=Confidence(audio=.9))
             for i, m in enumerate([62, 64, 66, 64, 62])]
    evidence = [Evidence(time=n.start, position=Position(string=3, fret=n.midi-55),
                         confidence=.9, source="video") for n in notes]
    solved = FingeringSolver(GuitarModel(), AppConfig()).solve(notes, evidence)
    assert [n.string for n in solved] == [3]*5
    assert [n.fret for n in solved] == [7, 9, 11, 9, 7]
    assert all(len(n.alternatives) > 1 for n in solved)


def test_polyphony_keeps_distinct_sustaining_strings():
    notes = [NoteEvent(start=0, end=1, midi=m, confidence=Confidence(audio=.9)) for m in [40, 47, 52, 55, 59, 64]]
    result = FingeringSolver(GuitarModel(), AppConfig()).solve(notes)
    assert len({n.string for n in result}) == 6
    assert not PlayabilityValidator().validate(result)


def test_impossible_polyphony_is_not_silently_dropped():
    notes = [NoteEvent(start=0, end=1, midi=64) for _ in range(7)]
    result = FingeringSolver(GuitarModel(), AppConfig()).solve(notes)
    assert len(result) == 7
    assert any(n.string is None and n.uncertain for n in result)
