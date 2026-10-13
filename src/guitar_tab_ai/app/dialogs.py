"""Explicit note edits and four-corner manual neck calibration."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QLabel, QMessageBox, QSpinBox, QVBoxLayout)

from guitar_tab_ai.core.events import NoteEvent, Position, Technique
from guitar_tab_ai.guitar.model import GuitarModel


class NoteDialog(QDialog):
    def __init__(self, note: NoteEvent, guitar: GuitarModel, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Редактировать ноту")
        self.note, self.guitar, self.result_note = note, guitar, None
        layout = QFormLayout(self)
        self.start = QDoubleSpinBox()
        self.end = QDoubleSpinBox()
        for widget in (self.start, self.end):
            widget.setRange(0, 86400)
            widget.setDecimals(3)
        self.start.setValue(note.start)
        self.end.setValue(note.end)
        self.string = QSpinBox()
        self.string.setRange(1, guitar.strings)
        initial = (Position(string=note.string, fret=note.fret) if note.string is not None
                   else next(iter(guitar.candidates(note.midi)), None))
        self.string.setValue(initial.string if initial else 1)
        self.fret = QSpinBox()
        self.fret.setRange(0, guitar.frets-guitar.capo)
        self.fret.setValue(initial.fret if initial else 0)
        self.pitch = QSpinBox()
        self.pitch.setRange(0, 127)
        self.pitch.setValue(note.midi)
        self.finger = QSpinBox()
        self.finger.setRange(0, 4)
        self.finger.setValue(note.finger or 0)
        self.technique = QComboBox()
        self.technique.addItem("Без обозначения", None)
        for t in Technique:
            self.technique.addItem(t.value, t.value)
        if note.technique:
            self.technique.setCurrentIndex(self.technique.findData(note.technique.value))
        self.alternatives = QComboBox()
        for p in guitar.candidates(note.midi):
            self.alternatives.addItem(f"Струна {p.string}, лад {p.fret}", p)
        self.alternatives.activated.connect(self.choose_position)
        for label, widget in [("Начало, с", self.start), ("Конец, с", self.end), ("Струна", self.string),
                              ("Лад (от капо)", self.fret), ("MIDI pitch", self.pitch),
                              ("Палец (0 = не указан)", self.finger), ("Техника (вручную)", self.technique),
                              ("Альтернативы", self.alternatives)]:
            layout.addRow(label, widget)
        self.string.valueChanged.connect(self.update_pitch)
        self.fret.valueChanged.connect(self.update_pitch)
        self.pitch.valueChanged.connect(self.update_positions)
        label = QLabel(f"Исходная уверенность: audio {note.confidence.audio:.0%}, "
                       f"video {note.confidence.video:.0%}, OCR {note.confidence.ocr:.0%}\n"
                       "Ручное исправление сохраняется при повторном анализе.")
        label.setWordWrap(True)
        layout.addRow(label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def choose_position(self, index):
        p = self.alternatives.itemData(index)
        if p:
            self.string.blockSignals(True)
            self.string.setValue(p.string)
            self.string.blockSignals(False)
            self.fret.setValue(p.fret)
            self.update_pitch()

    def update_pitch(self):
        self.pitch.blockSignals(True)
        self.pitch.setValue(self.guitar.midi_at(Position(string=self.string.value(), fret=self.fret.value())))
        self.pitch.blockSignals(False)

    def update_positions(self):
        self.alternatives.clear()
        for p in self.guitar.candidates(self.pitch.value()):
            self.alternatives.addItem(f"Струна {p.string}, лад {p.fret}", p)
        if self.alternatives.count():
            self.choose_position(0)

    def validate(self):
        try:
            values = self.note.model_dump()
            position = Position(string=self.string.value(), fret=self.fret.value())
            if self.pitch.value() != self.guitar.midi_at(position):
                raise ValueError("Выбранная нота не соответствует струне и ладу")
            confidence = self.note.confidence.model_copy(deep=True)
            values.update(start=self.start.value(), end=self.end.value(), string=position.string,
                          fret=position.fret, midi=self.pitch.value(), manual_override=True, uncertain=False,
                          finger=self.finger.value() or None, technique=self.technique.currentData(),
                          confidence=confidence, sources=sorted(set(self.note.sources+["manual"])))
            self.result_note = NoteEvent.model_validate(values)
        except ValueError as exc:
            QMessageBox.warning(self, "Проверьте ноту", str(exc))
            return
        self.accept()


class CalibrationImage(QLabel):
    def __init__(self, image: QPixmap):
        super().__init__()
        self.original = image
        self.points: list[tuple[float, float]] = []
        self.setFixedSize(image.size())
        self.setPixmap(image)

    def mousePressEvent(self, event):
        if len(self.points) == 4:
            self.points.clear()
        self.points.append((event.position().x()/self.width(), event.position().y()/self.height()))
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QColor("#ffb545"))
        for i, (x, y) in enumerate(self.points):
            painter.drawEllipse(int(x*self.width())-5, int(y*self.height())-5, 10, 10)
            painter.drawText(int(x*self.width())+8, int(y*self.height()), str(i+1))


class CalibrationDialog(QDialog):
    def __init__(self, image: QPixmap, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Указать гриф вручную")
        layout = QVBoxLayout(self)
        instructions = QLabel("Нажмите по порядку: 1 начало у высокой струны, 2 конец у высокой струны, "
                              "3 конец у низкой струны, 4 начало у низкой струны.\n"
                              "Границы должны проходить по выбранным ладам. Следующий клик сбрасывает точки.\n"
                              "Калибровка рассчитана на неподвижную камеру.")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        self.image = CalibrationImage(image.scaled(900, 500, Qt.AspectRatioMode.KeepAspectRatio))
        layout.addWidget(self.image)
        form = QFormLayout()
        self.start_fret, self.end_fret = QSpinBox(), QSpinBox()
        self.start_fret.setRange(0, 23)
        self.end_fret.setRange(1, 24)
        self.end_fret.setValue(12)
        form.addRow("Начальный физический лад (0 = порожек)", self.start_fret)
        form.addRow("Конечный физический лад", self.end_fret)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def validate(self):
        if len(self.image.points) != 4 or self.end_fret.value() <= self.start_fret.value():
            QMessageBox.warning(self, "Калибровка", "Укажите четыре угла и корректные лады")
            return
        import cv2
        import numpy as np
        contour = np.asarray(self.image.points, dtype=np.float32)
        if not cv2.isContourConvex(contour) or abs(cv2.contourArea(contour)) < 0.001:
            QMessageBox.warning(self, "Калибровка", "Четыре угла должны образовать выпуклый четырёхугольник")
            return
        self.accept()
