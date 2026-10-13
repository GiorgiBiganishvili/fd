
import cv2
import numpy as np
from PySide6.QtMultimedia import QMediaPlayer

from guitar_tab_ai.app.dialogs import NoteDialog
from guitar_tab_ai.app.window import MainWindow
from guitar_tab_ai.core.config import AppConfig
from guitar_tab_ai.core.events import NoteEvent, Position
from guitar_tab_ai.core.project import Project
from guitar_tab_ai.export.formats import export_image, export_pdf
from guitar_tab_ai.guitar.model import GuitarModel
from guitar_tab_ai.ocr.tab_ocr import TabDetector, TabOCR
from guitar_tab_ai.video.analyzer import Frame, FretDetector, StringDetector


def tab_frame(color=(0, 0, 0)):
    image = np.full((220, 600, 3), 255, np.uint8)
    for y in [50, 75, 100, 125, 150, 175]:
        cv2.line(image, (15, y), (580, y), (0, 0, 0), 1)
    cv2.putText(image, "10", (100, 107), cv2.FONT_HERSHEY_SIMPLEX, .65, (255, 255, 255), 5)
    cv2.putText(image, "10", (100, 107), cv2.FONT_HERSHEY_SIMPLEX, .65, color, 2)
    return image


def test_tab_line_detection_and_fret_physics():
    detections = TabDetector().detect(tab_frame())
    assert len(detections) == 1
    assert len(detections[0][-1]) == 6
    grid = FretDetector().grid(0, 12)
    assert len(grid) == 13 and grid[0] == 0 and grid[-1] == 1
    assert grid[1]-grid[0] > grid[-1]-grid[-2]
    rows, confidence = StringDetector().detect(tab_frame(), 6)
    assert len(rows) == 6 and confidence > 0


def test_tesseract_recognizes_grouped_digit_and_static_tab():
    result = TabOCR(AppConfig()).analyze(iter([Frame(0, tab_frame())]))
    assert result.detected
    assert any(e.position == Position(string=3, fret=10) for e in result.evidence)
    assert all(not e.synchronized for e in result.evidence)


def test_highlight_tracking_emits_one_onset_per_highlight():
    frame = tab_frame((0, 0, 220))
    result = TabOCR(AppConfig()).analyze(iter([Frame(0, frame), Frame(.5, frame)]))
    timed = [e for e in result.evidence if e.synchronized]
    assert len(timed) == 1
    assert timed[0].position.fret == 10


def test_gui_edit_move_undo_redo_and_exports(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("GTAB_DATA_DIR", str(tmp_path/"app"))
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    note = NoteEvent(start=.5, end=1, midi=64, string=1, fret=0)
    window.apply_project(Project(notes=[note]))
    window.select_note(note.id)
    window.timeline.seek.emit(.5)
    window.move_note(note.id, 2, 2)
    assert window.project.notes[0].start == 2
    assert window.project.notes[0].midi == 59
    assert window.project.notes[0].manual_override
    window.undo_stack.undo()
    assert window.project.notes[0].start == .5
    window.undo_stack.redo()
    assert window.project.notes[0].start == 2
    dialog = NoteDialog(window.project.notes[0], window.project.guitar)
    dialog.fret.setValue(3)
    dialog.start.setValue(2.2)
    dialog.end.setValue(2.7)
    dialog.validate()
    assert dialog.result_note.midi == 62
    assert dialog.result_note.manual_override
    window.timeline.position(2.1)
    export_image(window.project, tmp_path/"tab.png")
    export_pdf(window.project, tmp_path/"tab.pdf")
    assert (tmp_path/"tab.png").read_bytes().startswith(b'\x89PNG')
    assert (tmp_path/"tab.pdf").read_bytes().startswith(b'%PDF')
    window.copy_note()
    window.paste_note()
    assert len(window.project.notes) == 2
    window.delete_selected()
    assert len(window.project.notes) == 1
    window.undo_stack.setClean()
    window.close()


def test_gui_background_analysis_and_media_playback(qtbot, video, tmp_path, monkeypatch):
    monkeypatch.setenv("GTAB_DATA_DIR", str(tmp_path/"app"))
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.config.ocr_enabled = False
    window.config.video_enabled = False
    window.import_video(video)
    assert window.worker is not None
    # The event loop can still process UI operations while analysis runs.
    window.player.setPlaybackRate(.5)
    qtbot.waitUntil(lambda: window.worker is None, timeout=30000)
    assert len(window.project.notes) == 6
    window.player.play()
    qtbot.waitUntil(lambda: window.player.position() > 100, timeout=10000)
    assert window.player.error() == QMediaPlayer.Error.NoError
    window.player.pause()
    window.undo_stack.setClean()
    window.close()


def test_unassigned_note_dialog_offers_a_pitch_consistent_position(qtbot):
    note = NoteEvent(start=0, end=.5, midi=50)
    dialog = NoteDialog(note, GuitarModel())
    qtbot.addWidget(dialog)
    dialog.validate()
    assert dialog.result_note.midi == 50
    assert GuitarModel().midi_at(Position(string=dialog.result_note.string,
                                        fret=dialog.result_note.fret)) == 50
