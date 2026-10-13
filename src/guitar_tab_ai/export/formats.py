"""Portable exports with faithful event times and guitar position metadata."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pretty_midi

from guitar_tab_ai.core.project import Project
from guitar_tab_ai.tab.generator import ascii_tab


def export_text(project: Project, path: Path) -> None:
    path.write_text(ascii_tab(project.notes, project.guitar), encoding="utf-8-sig")


def export_json(project: Project, path: Path) -> None:
    path.write_text(json.dumps(project.model_dump(mode="json"), ensure_ascii=False, indent=2), "utf-8")


def export_midi(project: Project, path: Path) -> None:
    midi = pretty_midi.PrettyMIDI(initial_tempo=project.rhythm.tempo or 120)
    instrument = pretty_midi.Instrument(program=24, name="Guitar")
    instrument.notes = [pretty_midi.Note(n.velocity, n.midi, n.start, n.end) for n in project.notes]
    midi.instruments.append(instrument)
    midi.write(str(path))


def export_musicxml(project: Project, path: Path) -> None:
    """Timewise-unquantized TAB in independent string voices with rests/backups.

    A neutral 120 BPM grid encodes exact seconds if tempo is unknown; it is not
    reported as detected tempo. Advanced technique engraving is not claimed.
    """
    divisions = 960
    if any(n.string is None for n in project.notes):
        raise ValueError("MusicXML: назначьте струну и лад всем нотам перед экспортом")
    tempo = project.rhythm.tempo or 120
    scale = divisions * tempo / 60
    root = ET.Element("score-partwise", version="4.0")
    work = ET.SubElement(root, "work")
    ET.SubElement(work, "work-title").text = project.title
    parts = ET.SubElement(root, "part-list")
    score_part = ET.SubElement(parts, "score-part", id="P1")
    ET.SubElement(score_part, "part-name").text = "Guitar TAB"
    part = ET.SubElement(root, "part", id="P1")
    measure = ET.SubElement(part, "measure", number="1", implicit="yes")
    attributes = ET.SubElement(measure, "attributes")
    ET.SubElement(attributes, "divisions").text = str(divisions)
    clef = ET.SubElement(attributes, "clef")
    ET.SubElement(clef, "sign").text = "TAB"
    ET.SubElement(clef, "line").text = "5"
    staff = ET.SubElement(attributes, "staff-details")
    ET.SubElement(staff, "staff-lines").text = str(project.guitar.strings)
    for index, midi in enumerate(project.guitar.open_strings, 1):
        tuning = ET.SubElement(staff, "staff-tuning", line=str(index))
        step, alter = _pitch(midi)
        ET.SubElement(tuning, "tuning-step").text = step
        if alter:
            ET.SubElement(tuning, "tuning-alter").text = "1"
        ET.SubElement(tuning, "tuning-octave").text = str(midi//12-1)
    ET.SubElement(staff, "capo").text = str(project.guitar.capo)
    direction = ET.SubElement(measure, "direction")
    ET.SubElement(direction, "sound", tempo=str(tempo))
    total = max((round(n.end*scale) for n in project.notes), default=1)
    for string in range(1, project.guitar.strings+1):
        cursor = 0
        for n in sorted((n for n in project.notes if n.string == string), key=lambda n: n.start):
            start = round(n.start*scale)
            if start < cursor:
                raise ValueError("MusicXML: перекрывающиеся ноты на одной струне; исправьте TAB")
            if start > cursor:
                _rest(measure, start-cursor, string)
            note = ET.SubElement(measure, "note")
            pitch = ET.SubElement(note, "pitch")
            step, alter = _pitch(n.midi)
            ET.SubElement(pitch, "step").text = step
            if alter:
                ET.SubElement(pitch, "alter").text = "1"
            ET.SubElement(pitch, "octave").text = str(n.midi//12-1)
            length = max(1, round(n.end*scale)-start)
            ET.SubElement(note, "duration").text = str(length)
            ET.SubElement(note, "voice").text = str(string)
            technical = ET.SubElement(ET.SubElement(note, "notations"), "technical")
            ET.SubElement(technical, "string").text = str(string)
            ET.SubElement(technical, "fret").text = str(n.fret)
            cursor = start+length
        if cursor < total:
            _rest(measure, total-cursor, string)
        if string < project.guitar.strings:
            ET.SubElement(ET.SubElement(measure, "backup"), "duration").text = str(total)
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _pitch(midi: int) -> tuple[str, int]:
    return (("C", 0), ("C", 1), ("D", 0), ("D", 1), ("E", 0), ("F", 0),
            ("F", 1), ("G", 0), ("G", 1), ("A", 0), ("A", 1), ("B", 0))[midi % 12]


def _rest(measure: ET.Element, duration: int, voice: int) -> None:
    rest = ET.SubElement(measure, "note")
    ET.SubElement(rest, "rest")
    ET.SubElement(rest, "duration").text = str(duration)
    ET.SubElement(rest, "voice").text = str(voice)


def export_image(project: Project, path: Path) -> None:
    from PySide6.QtGui import QColor, QFont, QImage, QPainter
    lines = ascii_tab(project.notes, project.guitar).splitlines()
    image = QImage(max(900, max(map(len, lines))*11+60), len(lines)*24+60, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setPen(QColor("black"))
    painter.setFont(QFont("Consolas", 12))
    for i, line in enumerate(lines):
        painter.drawText(30, 40+i*24, line)
    painter.end()
    if not image.save(str(path), "PNG"):
        raise OSError("Не удалось сохранить PNG")


def export_pdf(project: Project, path: Path) -> None:
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPainter, QPdfWriter
    writer = QPdfWriter(str(path))
    writer.setResolution(96)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)
    painter = QPainter(writer)
    painter.setFont(QFont("Courier New", 9))
    y = 20
    for line in ascii_tab(project.notes, project.guitar, cells_per_line=24).splitlines():
        if y+18 > writer.height():
            writer.newPage()
            y = 20
        painter.drawText(0, y, line)
        y += 18
    painter.end()


EXPORTERS = {"txt": export_text, "json": export_json, "mid": export_midi,
             "musicxml": export_musicxml, "png": export_image, "pdf": export_pdf}
