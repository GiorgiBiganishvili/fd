"""Editable time-scaled TAB scene and waveform, driven by media position."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView

from guitar_tab_ai.core.events import NoteEvent
from guitar_tab_ai.core.project import Project


class NoteItem(QGraphicsRectItem):
    def __init__(self, note: NoteEvent, timeline: TabTimeline):
        super().__init__(0, -10, max(24, (note.end-note.start)*timeline.scale), 23)
        self.note, self.timeline = note, timeline
        self.setPos(timeline.origin+note.start*timeline.scale, 45+(note.string or 0)*32)
        self.base_color = QColor("#bc8431" if note.uncertain else "#377b8f")
        self.setBrush(self.base_color)
        self.setPen(QPen(QColor("#e1ebef"), 0.5))
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setToolTip(f"{note.pitch} · {note.start:.3f}–{note.end:.3f} с\n"
                        f"Confidence: {note.confidence.final:.0%}\nДвойной клик: редактировать")
        self.initial = self.pos()

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        painter.setPen(QColor("white"))
        text = str(self.note.fret) if self.note.fret is not None else "*"
        if self.note.uncertain:
            text += "?"
        if self.note.manual_override:
            text += "✓"
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)

    def mousePressEvent(self, event):
        self.initial = self.pos()
        self.timeline.note_selected.emit(self.note.id)
        self.timeline.seek.emit(self.note.start)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.timeline.edit_requested.emit(self.note.id)
        event.accept()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        delta = self.pos()-self.initial
        if abs(delta.x()) > 3 or abs(delta.y()) > 8:
            start = max(0, (self.pos().x()-self.timeline.origin)/self.timeline.scale)
            string = max(1, min(self.timeline.strings, round((self.pos().y()-45)/32)))
            self.setPos(self.initial)
            self.timeline.note_moved.emit(self.note.id, start, string)


class TabTimeline(QGraphicsView):
    seek = Signal(float)
    note_selected = Signal(str)
    edit_requested = Signal(str)
    note_moved = Signal(str, float, int)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMinimumHeight(300)
        self.setBackgroundBrush(QColor("#16202d"))
        self.origin, self.scale, self.strings = 65, 110, 6
        self.items_by_id: dict[str, NoteItem] = {}
        self.playhead = None
        self.duration = 1
        self.busy = False

    def set_project(self, project: Project):
        self.scene().clear()
        self.items_by_id.clear()
        self.strings = project.guitar.strings
        self.duration = max(project.media.duration if project.media else 1,
                            max((n.end for n in project.notes), default=1))
        width = self.origin + self.duration*self.scale+50
        for s in range(1, self.strings+1):
            y = 45+s*32
            self.scene().addLine(self.origin, y, width, y, QPen(QColor("#536273")))
            label = self.scene().addText(f"{s}")
            label.setDefaultTextColor(QColor("#c5d1df"))
            label.setPos(20, y-14)
        tick_interval = max(1, round(100/self.scale))
        for t in range(0, int(self.duration)+1, tick_interval):
            x = self.origin+t*self.scale
            label = self.scene().addText(f"{t//60:02}:{t%60:02}")
            label.setDefaultTextColor(QColor("#8d9bae"))
            label.setPos(x, 4)
            self.scene().addLine(x, 32, x, 45+self.strings*32, QPen(QColor("#263749")))
        for note in project.notes:
            item = NoteItem(note, self)
            self.scene().addItem(item)
            self.items_by_id[note.id] = item
        base = 75+self.strings*32
        if project.waveform:
            path = QPainterPath()
            for i, peak in enumerate(project.waveform):
                x = self.origin+i/len(project.waveform)*self.duration*self.scale
                path.moveTo(x, base-peak*24)
                path.lineTo(x, base+peak*24)
            self.scene().addPath(path, QPen(QColor("#557584")))
        self.playhead = self.scene().addLine(self.origin, 0, self.origin, base+30,
                                             QPen(QColor("#68d5bc"), 2))
        self.playhead.setZValue(10)
        self.scene().setSceneRect(0, 0, width, base+40)

    def position(self, seconds: float):
        if self.playhead is None:
            return
        self.playhead.setX(seconds*self.scale)
        for item in self.items_by_id.values():
            active = item.note.start <= seconds < item.note.end
            item.setBrush(QColor("#41a58c") if active else item.base_color)
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        x = self.origin+seconds*self.scale
        if x > visible.right()-30 or x < visible.left():
            self.centerOn(x+self.viewport().width()/4, visible.center().y())

    def mousePressEvent(self, event):
        if self.busy:
            return
        item = self.itemAt(event.position().toPoint())
        if not isinstance(item, NoteItem):
            point = self.mapToScene(event.position().toPoint())
            self.seek.emit(max(0, min(self.duration, (point.x()-self.origin)/self.scale)))
        super().mousePressEvent(event)
