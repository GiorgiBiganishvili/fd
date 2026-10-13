"""Shared fret and technique notation for the editor and printable TAB."""
from guitar_tab_ai.core.events import NoteEvent, Technique

SYMBOLS = {"hammer_on": "h", "pull_off": "p", "slide_up": "/", "slide_down": "\\",
           "bend": "b", "bend_release": "r", "vibrato": "~", "palm_mute": "PM",
           "dead_note": "x", "artificial_harmonic": "AH", "tap": "t", "let_ring": "LR"}


def fret_label(note: NoteEvent) -> str:
    if note.fret is None:
        return "*"
    if note.technique == Technique.HARMONIC:
        return f"<{note.fret}>"
    return str(note.fret)+SYMBOLS.get(note.technique, "")
