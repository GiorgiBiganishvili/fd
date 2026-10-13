from guitar_tab_ai.core.events import NoteEvent, SuppressedEvent
from guitar_tab_ai.core.project import Project


def test_deleted_note_does_not_return_on_reanalysis():
    deleted = SuppressedEvent(start=1, end=1.4, midi=64)
    project = Project(suppressed=[deleted])
    notes = [NoteEvent(start=1.03, end=1.4, midi=64), NoteEvent(start=2, end=2.4, midi=64)]
    project.replace_interval(0, 3, notes)
    assert len(project.notes) == 1 and project.notes[0].start == 2


def test_manual_note_at_suppressed_onset_is_kept():
    project = Project(suppressed=[SuppressedEvent(start=1, end=1.4, midi=64)])
    manual = NoteEvent(start=1, end=1.4, midi=64, manual_override=True)
    project.replace_interval(0, 3, [manual])
    assert project.notes[0].id == manual.id
