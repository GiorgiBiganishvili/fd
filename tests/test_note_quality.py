import threading

import numpy as np
import soundfile as sf

from guitar_tab_ai.app.timeline import TabTimeline
from guitar_tab_ai.audio.note_filter import filter_notes
from guitar_tab_ai.audio.transcription import SpectralTranscriber
from guitar_tab_ai.core.config import AppConfig
from guitar_tab_ai.core.events import Confidence, NoteEvent
from guitar_tab_ai.core.project import Project
from guitar_tab_ai.guitar.model import GuitarModel


def note(midi, start=0, end=.5, confidence=.8):
    return NoteEvent(midi=midi, start=start, end=end, confidence=Confidence(audio=confidence))


def test_noise_and_guitar_harmonics_do_not_fill_tab(tmp_path):
    sr = 44100
    t = np.arange(sr)/sr
    # Plucked low E with harmonics, followed by a loud broadband noise burst.
    hz = 440*2**((40-69)/12)
    pluck = sum(.3/k*np.sin(2*np.pi*hz*k*t) for k in range(1, 7))*np.exp(-3*t)
    noise = np.random.default_rng(42).normal(0, .12, sr)
    path = tmp_path/"harmonics-noise.wav"
    sf.write(path, np.concatenate([pluck, np.zeros(sr//4), noise]), sr)
    result = SpectralTranscriber(40, 88).transcribe(path, threading.Event(), lambda *_: None)
    assert result.notes
    assert {n.midi for n in result.notes} == {40}
    assert all(n.start < 1 for n in result.notes)


def test_filter_removes_weak_out_of_range_short_and_duplicate_candidates():
    candidates = [note(40), note(40, .2, .8), note(20), note(100),
                  note(55, confidence=.2), note(57, end=.04), note(64)]
    filtered = filter_notes(candidates, GuitarModel(), AppConfig())
    assert [n.midi for n in filtered] == [40, 64]
    assert filtered[0].end == .8
    assert candidates[0].end == .5  # raw cache candidates remain untouched


def test_chords_preserved_and_monophonic_mode_prevents_polyphony():
    candidates = [note(40), note(47, confidence=.55), note(52, confidence=.7),
                  note(64, .25, .7, .9)]
    guitar = GuitarModel()
    assert len(filter_notes(candidates, guitar, AppConfig())) == 4
    melody = filter_notes(candidates, guitar, AppConfig(transcription_profile="melody"))
    assert [n.midi for n in melody] == [40, 64]
    assert melody[0].end == melody[1].start


def test_dense_tab_fret_labels_do_not_overlap(qtbot):
    timeline = TabTimeline()
    qtbot.addWidget(timeline)
    notes = [NoteEvent(midi=64, string=1, fret=0, start=i*.03, end=i*.03+.5)
             for i in range(30)]
    project = Project(notes=notes+[note(100)])
    timeline.set_project(project)
    items = [timeline.items_by_id[n.id] for n in notes]
    assert len(items) == 30
    for a, b in zip(items, items[1:]):
        assert a.sceneBoundingRect().right() <= b.sceneBoundingRect().left()
    assert project.notes[-1].id not in timeline.items_by_id
    timeline.scale = 800
    timeline.set_project(project)
    assert timeline.items_by_id[notes[0].id].rect().width() >= 20
