import zipfile

import pytest

from guitar_tab_ai.core.config import AppConfig
from guitar_tab_ai.core.events import AudioResult, Confidence, Evidence, NoteEvent, Position, group_chords
from guitar_tab_ai.core.project import Project
from guitar_tab_ai.fusion.fusion_engine import FusionEngine
from guitar_tab_ai.guitar.model import GuitarModel
from guitar_tab_ai.storage.database import Preferences
from guitar_tab_ai.storage.project_storage import load_project, save_project


def test_audio_visual_agreement():
    audio = AudioResult(notes=[NoteEvent(start=1, end=1.4, midi=62, confidence=Confidence(audio=.95))])
    video = [Evidence(time=1, position=Position(string=3, fret=7), confidence=.85, source="video")]
    note, = FusionEngine(GuitarModel(), AppConfig()).fuse(audio, video, [])
    assert (note.string, note.fret) == (3, 7)
    assert note.confidence.video == .85
    assert not note.uncertain


def test_conflict_keeps_high_audio_and_marks_uncertainty():
    audio = AudioResult(notes=[NoteEvent(start=1, end=1.4, midi=61, confidence=Confidence(audio=.95))])
    video = [Evidence(time=1, position=Position(string=3, fret=7), confidence=.85, source="video")]
    note, = FusionEngine(GuitarModel(), AppConfig()).fuse(audio, video, [])
    assert note.midi == 61 and note.uncertain
    assert note.confidence.final <= .5


def test_static_ocr_and_finger_contacts_do_not_invent_onsets():
    e = Evidence(time=1, position=Position(string=3, fret=7), confidence=.9, source="ocr", synchronized=False)
    engine = FusionEngine(GuitarModel(), AppConfig())
    assert engine.fuse(AudioResult(), [], [e]) == []
    assert engine.fuse(AudioResult(), [e.model_copy(update={"source": "video", "synchronized": True})], []) == []


def test_chord_evidence_is_not_treated_as_conflict():
    audio = AudioResult(notes=[NoteEvent(start=1, end=2, midi=m, confidence=Confidence(audio=.9))
                              for m in [59, 64]])
    evidence = [Evidence(time=1, position=Position(string=s, fret=0), confidence=.9, source="video")
                for s in [1, 2]]
    result = FusionEngine(GuitarModel(), AppConfig()).fuse(audio, evidence, [])
    assert all(not n.uncertain for n in result)


def test_reanalysis_preserves_manual_and_outside_notes():
    manual = NoteEvent(start=1, end=1.5, midi=64, string=1, fret=0, manual_override=True)
    outside = NoteEvent(start=4, end=4.4, midi=64)
    project = Project(notes=[manual, outside])
    fresh = [NoteEvent(start=1.1, end=1.4, midi=64), NoteEvent(start=2, end=2.3, midi=62)]
    project.replace_interval(0, 3, fresh)
    assert {n.id for n in project.notes} == {manual.id, outside.id, fresh[1].id}


def test_chords_do_not_quantize_arpeggios():
    notes = [NoteEvent(start=t, end=t+.5, midi=64) for t in [0, .02, .15]]
    chords = group_chords(notes)
    assert len(chords) == 1 and len(chords[0].note_ids) == 2


def test_project_atomic_roundtrip_and_relink(tmp_path):
    media = tmp_path/"Видео №1.mp4"
    media.touch()
    project = Project(video_path=str(media), notes=[NoteEvent(start=0, end=.3, midi=64, string=1, fret=0,
                                                            manual_override=True)])
    path = tmp_path/"test.gtabproject"
    save_project(project, path)
    loaded = load_project(path)
    assert loaded == project
    with zipfile.ZipFile(path) as archive:
        assert archive.namelist() == ["project.json"]
        assert b'"video_path": "' in archive.read("project.json")
    moved = tmp_path/"moved"
    moved.mkdir()
    path.rename(moved/path.name)
    media.rename(moved/media.name)
    assert load_project(moved/path.name).video_path == str(moved/media.name)


def test_invalid_project_is_reported(tmp_path):
    path = tmp_path/"bad.gtabproject"
    path.write_bytes(b"not a zip")
    with pytest.raises(ValueError, match="Повреждённый"):
        load_project(path)


def test_preferences(tmp_path):
    db = Preferences(tmp_path/"preferences.sqlite")
    db.set("tuning", [38, 45, 50, 55, 59, 64])
    assert db.get("tuning")[0] == 38
    db.remember(tmp_path/"p.gtabproject")
    assert len(db.recent()) == 1
