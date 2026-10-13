"""Readable ASCII TAB with an explicit seconds grid and aligned chord columns."""
from __future__ import annotations

from guitar_tab_ai.core.events import NoteEvent
from guitar_tab_ai.guitar.model import GuitarModel
from guitar_tab_ai.tab.notation import fret_label


def ascii_tab(notes: list[NoteEvent], guitar: GuitarModel, seconds_per_cell: float = 0.125,
              cells_per_line: int = 32) -> str:
    if seconds_per_cell <= 0:
        raise ValueError("Seconds per cell must be positive")
    output = [f"Tuning: {guitar.tuning_name} | Capo: {guitar.capo}",
              f"Grid: {seconds_per_cell:g} s per column; ? = uncertain; * = unassigned", ""]
    if not notes:
        return "\n".join(output+["Нет распознанных нот."])
    last_cell = max(int(n.start/seconds_per_cell + 0.5) for n in notes)
    cells: dict[tuple[int, int], list[str]] = {}
    for n in notes:
        cell = int(n.start/seconds_per_cell + 0.5)
        if n.string is None:
            output.append(f"* {n.start:.3f}s {n.pitch}: no playable position")
            continue
        text = fret_label(n) + ("?" if n.uncertain else "")
        cells.setdefault((n.string, cell), []).append(text)
    for beginning in range(0, last_cell+1, cells_per_line):
        width = min(cells_per_line, last_cell-beginning+1)
        sizes = [max(3, *(len('/'.join(cells.get((s, c), [])))+1
                         for s in range(1, guitar.strings+1)))
                 for c in range(beginning, beginning+width)]
        output.append(f"[{beginning*seconds_per_cell:08.3f}s]")
        for s in range(1, guitar.strings+1):
            label = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")[
                guitar.open_strings[-s] % 12]
            line = ''.join('/'.join(cells.get((s, c), [])).ljust(size, '-')
                           for c, size in zip(range(beginning, beginning+width), sizes))
            output.append(f"{label:>2}|{line}|")
        output.append("")
    return '\n'.join(output)
