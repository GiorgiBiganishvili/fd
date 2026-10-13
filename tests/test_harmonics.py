import xml.etree.ElementTree as ET

import pretty_midi
import pytest
import cv2
import numpy as np

from guitar_tab_ai.app.dialogs import NoteDialog
from guitar_tab_ai.core.config import AppConfig
from guitar_tab_ai.core.events import AudioResult, Confidence, Evidence, NoteEvent, Position, Technique
from guitar_tab_ai.core.project import Project
from guitar_tab_ai.export.formats import export_midi, export_musicxml, export_text
from guitar_tab_ai.fusion.fusion_engine import FusionEngine
from guitar_tab_ai.guitar.model import GuitarModel
from guitar_tab_ai.ocr.tab_ocr import TabOCR
from guitar_tab_ai.storage.project_storage import load_project, save_project
from guitar_tab_ai.tab.notation import fret_label
from guitar_tab_ai.video.analyzer import Frame


@pytest.mark.parametrize("node,interval", [(5, 24), (7, 19), (12, 12), (19, 19), (24, 24)])
def test_natural_harmonic_pitch_and_capo(node, interval):
    guitar = GuitarModel(frets=36, capo=2)
    touch = Position(string=1, fret=node)
    pitch = guitar.midi_at(touch, Technique.HARMONIC)
    assert pitch == 64+2+interval
    assert touch in guitar.candidates(pitch, Technique.HARMONIC)
    assert all(guitar.midi_at(p, Technique.HARMONIC) == pitch
               for p in guitar.candidates(pitch, Technique.HARMONIC))


def test_harmonic_touch_is_not_an_ordinary_fret():
    guitar = GuitarModel()
    assert guitar.midi_at(Position(string=1, fret=5)) == 69
    assert guitar.midi_at(Position(string=1, fret=12), Technique.HARMONIC) == 76
    assert guitar.midi_at(Position(string=1, fret=5), Technique.HARMONIC) == 88
    with pytest.raises(ValueError, match="флажолет"):
        guitar.midi_at(Position(string=1, fret=6), Technique.HARMONIC)


def test_explicit_harmonic_evidence_preserves_touch_node():
    # E4 also has several ordinary fretted positions. A confirmed low-E
    # 5th-node touch must not be turned into an ordinary open high E.
    audio = AudioResult(notes=[NoteEvent(start=1, end=2, midi=64,
                                        confidence=Confidence(audio=.95))])
    evidence = Evidence(time=1, position=Position(string=6, fret=5), confidence=.9,
                        source="ocr", technique=Technique.HARMONIC)
    result, = FusionEngine(GuitarModel(), AppConfig()).fuse(audio, [], [evidence])
    assert (result.string, result.fret, result.midi) == (6, 5, 64)
    assert result.technique == Technique.HARMONIC
    assert fret_label(result) == "<5>"
    assert all(p.fret in {5, 7, 12, 19, 24} for p in result.alternatives)


def test_visible_twelfth_fret_alone_does_not_prove_harmonic():
    audio = AudioResult(notes=[NoteEvent(start=1, end=2, midi=76,
                                        confidence=Confidence(audio=.95))])
    finger = Evidence(time=1, position=Position(string=1, fret=12), confidence=.9, source="video")
    result, = FusionEngine(GuitarModel(), AppConfig()).fuse(audio, [finger], [])
    assert (result.string, result.fret) == (1, 12)
    assert result.technique is None


def test_conflicting_audio_does_not_get_relabelled_as_twelfth_harmonic():
    audio = AudioResult(notes=[NoteEvent(start=1, end=2, midi=69,
                                        confidence=Confidence(audio=.95))])
    harmonic = Evidence(time=1, position=Position(string=1, fret=12), confidence=.9,
                        source="video", technique=Technique.HARMONIC)
    result, = FusionEngine(GuitarModel(), AppConfig()).fuse(audio, [harmonic], [])
    assert result.midi == 69 and result.technique is None and result.uncertain


def test_harmonic_edit_export_and_project_roundtrip(qtbot, tmp_path):
    guitar = GuitarModel()
    note = NoteEvent(start=1, end=2, midi=76, string=1, fret=12)
    dialog = NoteDialog(note, guitar)
    qtbot.addWidget(dialog)
    dialog.technique.setCurrentIndex(dialog.technique.findData(Technique.HARMONIC.value))
    dialog.validate()
    harmonic = dialog.result_note
    assert harmonic.midi == 76 and harmonic.technique == Technique.HARMONIC
    assert fret_label(harmonic) == "<12>"
    # Changing a natural harmonic's touch position updates the sounding pitch,
    # not the ordinary-fretted pitch.
    dialog.fret.setValue(5)
    dialog.validate()
    assert dialog.result_note.midi == 88
    project = Project(notes=[harmonic])
    path = tmp_path/"harmonic.gtabproject"
    save_project(project, path)
    assert load_project(path).notes[0] == harmonic
    export_text(project, tmp_path/"tab.txt")
    assert "<12>" in (tmp_path/"tab.txt").read_text("utf-8-sig")
    export_musicxml(project, tmp_path/"tab.musicxml")
    xml = ET.parse(tmp_path/"tab.musicxml")
    assert xml.find('.//harmonic/natural') is not None
    assert xml.find('.//harmonic/sounding-pitch') is not None
    assert xml.findtext('.//technical/fret') == '12'
    assert xml.findtext('.//notehead') == 'diamond'
    export_midi(project, tmp_path/"tab.mid")
    assert pretty_midi.PrettyMIDI(str(tmp_path/"tab.mid")).instruments[0].notes[0].pitch == 76


def test_real_ocr_reads_highlighted_harmonic_brackets():
    image = np.full((220, 600, 3), 255, np.uint8)
    for y in [50, 75, 100, 125, 150, 175]:
        cv2.line(image, (15, y), (580, y), (0, 0, 0), 1)
    cv2.putText(image, "<12>", (100, 57), cv2.FONT_HERSHEY_SIMPLEX, .7, (255, 255, 255), 6)
    cv2.putText(image, "<12>", (100, 57), cv2.FONT_HERSHEY_SIMPLEX, .7, (0, 0, 220), 2)
    observations = TabOCR(AppConfig()).analyze(iter([Frame(1, image), Frame(1.5, image)]))
    timed = [e for e in observations.evidence if e.synchronized]
    assert len(timed) == 1
    assert timed[0].position == Position(string=1, fret=12)
    assert timed[0].technique == Technique.HARMONIC
    note, = FusionEngine(GuitarModel(), AppConfig()).fuse(AudioResult(), [], timed)
    assert note.midi == 76 and fret_label(note) == "<12>"
