"""Desktop workstation: playback, TAB editing, project lifecycle and analysis."""
from __future__ import annotations

import logging
from pathlib import Path

import cv2
from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QImage, QKeySequence, QPixmap, QUndoCommand, QUndoStack
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSlider,
                               QScrollArea, QSpinBox, QSplitter, QVBoxLayout, QWidget)

from guitar_tab_ai.app.dialogs import CalibrationDialog, NoteDialog
from guitar_tab_ai.app.timeline import TabTimeline
from guitar_tab_ai.core.config import AppConfig, data_directory
from guitar_tab_ai.core.events import NoteEvent, Position, SuppressedEvent, group_chords
from guitar_tab_ai.core.project import Project
from guitar_tab_ai.export.formats import EXPORTERS
from guitar_tab_ai.guitar.model import GuitarModel, TUNINGS, pitch_to_midi
from guitar_tab_ai.storage.database import Preferences
from guitar_tab_ai.storage.project_storage import load_project, save_project
from guitar_tab_ai.tab.generator import ascii_tab
from guitar_tab_ai.workers.analysis_worker import AnalysisWorker

log = logging.getLogger(__name__)


class ProjectCommand(QUndoCommand):
    def __init__(self, window: MainWindow, before: Project, after: Project, text: str):
        super().__init__(text)
        self.window = window
        self.before, self.after = before.model_copy(deep=True), after.model_copy(deep=True)

    def undo(self):
        self.window.apply_project(self.before.model_copy(deep=True))

    def redo(self):
        self.window.apply_project(self.after.model_copy(deep=True))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Guitar Tab AI")
        self.resize(1280, 900)
        self.setAcceptDrops(True)
        self.root = data_directory()
        self.preferences = Preferences(self.root/"preferences.sqlite")
        self.config = AppConfig.load(self.root/"config.yaml")
        self.project = Project(settings=self.config.model_copy(deep=True))
        self.project_path: Path | None = None
        self.selected_id: str | None = None
        self.clipboard_note: NoteEvent | None = None
        self.worker: AnalysisWorker | None = None
        self.close_pending = False
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(50)
        self.undo_stack.cleanChanged.connect(self.update_title)
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.video = QVideoWidget()
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self.playback_position)
        self.player.durationChanged.connect(lambda duration: self.seek_slider.setRange(0, duration))
        self.player.errorOccurred.connect(lambda error, message: self.statusBar().showMessage(message))
        self.build_ui()
        self.build_actions()
        self.apply_project(self.project)
        self.undo_stack.setClean()

    def build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        top = QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(self.video)
        side = QWidget()
        side_layout = QVBoxLayout(side)
        form = QFormLayout()
        self.tuning = QComboBox()
        self.tuning.addItems(list(TUNINGS)+["Custom"])
        self.custom_tuning = QLineEdit("E2 A2 D3 G3 B3 E4")
        self.custom_tuning.setToolTip("От низкой струны к высокой, 6–8 нот")
        self.capo = QSpinBox()
        self.capo.setRange(0, 12)
        self.frets = QSpinBox()
        self.frets.setRange(12, 36)
        self.frets.setValue(24)
        self.backend = QComboBox()
        self.backend.addItem("Автоматически (Basic Pitch)", "auto")
        self.backend.addItem("Спектральный (CPU)", "spectral")
        self.backend.addItem("Basic Pitch (ML extra)", "basic-pitch")
        self.transcription_profile = QComboBox()
        self.transcription_profile.addItem("Гитара: аккорды и арпеджио", "polyphonic")
        self.transcription_profile.addItem("Мелодия: одна нота за раз", "melody")
        self.audio_threshold = QDoubleSpinBox()
        self.audio_threshold.setRange(0.1, 0.95)
        self.audio_threshold.setSingleStep(0.05)
        self.audio_threshold.setToolTip("Выше — меньше слабых срабатываний; тихие ноты могут пропасть")
        self.preset = QComboBox()
        self.preset.addItems(["Fast", "Balanced", "Maximum accuracy"])
        self.preset.setCurrentText("Balanced")
        self.ocr_enabled = QCheckBox("Читать TAB на видео")
        self.ocr_enabled.setChecked(self.config.ocr_enabled)
        self.video_enabled = QCheckBox("Анализировать гриф/руки")
        self.video_enabled.setChecked(self.config.video_enabled)
        self.hand_model = QLineEdit(self.config.hand_model or "")
        self.hand_model.setPlaceholderText("hand_landmarker.task (необязательно)")
        self.hand_model.setToolTip("Локальная модель MediaPipe; ничего не скачивается автоматически")
        for name, widget in [("Строй", self.tuning), ("Custom tuning", self.custom_tuning), ("Капо", self.capo),
                             ("Ладов", self.frets), ("Аудио", self.backend), ("Режим", self.preset),
                             ("Партия", self.transcription_profile), ("Порог нот", self.audio_threshold),
                             ("Модель рук", self.hand_model)]:
            form.addRow(name, widget)
        form.addRow(self.ocr_enabled)
        form.addRow(self.video_enabled)
        side_layout.addLayout(form)
        self.analyze_button = QPushButton("Анализировать видео")
        self.analyze_button.clicked.connect(lambda: self.start_analysis(False))
        self.calibrate_button = QPushButton("Указать гриф вручную")
        self.calibrate_button.clicked.connect(self.calibrate)
        self.review_button = QPushButton("Проверить сомнительную ноту")
        self.review_button.clicked.connect(self.review_uncertain)
        for button in (self.analyze_button, self.calibrate_button, self.review_button):
            side_layout.addWidget(button)
        self.summary = QLabel("Загрузите видео с гитарой")
        self.summary.setWordWrap(True)
        side_layout.addWidget(self.summary)
        self.warnings = QPlainTextEdit()
        self.warnings.setReadOnly(True)
        self.warnings.setMaximumHeight(150)
        side_layout.addWidget(self.warnings)
        side_scroll = QScrollArea()
        side_scroll.setWidgetResizable(True)
        side_scroll.setWidget(side)
        side_scroll.setMinimumWidth(330)
        top.addWidget(side_scroll)
        top.setStretchFactor(0, 3)
        top.setStretchFactor(1, 1)
        top.setMinimumHeight(260)
        layout.addWidget(top, 3)
        controls = QHBoxLayout()
        for label, callback in [("Загрузить видео", self.open_video), ("▶ / ⏸", self.toggle_play),
                                ("■", self.player.stop), ("◀ кадр", lambda: self.step_frame(-1)),
                                ("кадр ▶", lambda: self.step_frame(1))]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.sliderMoved.connect(self.player.setPosition)
        controls.addWidget(self.seek_slider, 1)
        self.clock = QLabel("00:00.000")
        controls.addWidget(self.clock)
        self.speed = QComboBox()
        self.speed.addItems(["0.25x", "0.5x", "0.75x", "1x", "1.25x", "1.5x"])
        self.speed.setCurrentText("1x")
        self.speed.currentTextChanged.connect(lambda text: self.player.setPlaybackRate(float(text[:-1])))
        controls.addWidget(self.speed)
        volume = QSlider(Qt.Orientation.Horizontal)
        volume.setRange(0, 100)
        volume.setValue(80)
        volume.setMaximumWidth(100)
        volume.valueChanged.connect(lambda value: self.audio_output.setVolume(value/100))
        self.audio_output.setVolume(0.8)
        controls.addWidget(volume)
        layout.addLayout(controls)
        selection = QHBoxLayout()
        self.range_a, self.range_b = QDoubleSpinBox(), QDoubleSpinBox()
        for widget in (self.range_a, self.range_b):
            widget.setRange(0, 86400)
            widget.setDecimals(3)
            widget.setSuffix(" с")
        self.range_b.setValue(10)
        selection.addWidget(QLabel("Участок A–B"))
        selection.addWidget(self.range_a)
        selection.addWidget(self.range_b)
        for label, widget in [("A = сейчас", self.range_a), ("B = сейчас", self.range_b)]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, target=widget: target.setValue(self.player.position()/1000))
            selection.addWidget(button)
        self.loop = QCheckBox("Повтор A–B")
        selection.addWidget(self.loop)
        self.reanalyze_button = QPushButton("Анализировать участок заново")
        self.reanalyze_button.clicked.connect(lambda: self.start_analysis(True))
        selection.addWidget(self.reanalyze_button)
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(60, 800)
        self.zoom.setValue(180)
        self.zoom.setMaximumWidth(130)
        self.zoom.valueChanged.connect(self.zoom_changed)
        selection.addWidget(QLabel("Масштаб"))
        selection.addWidget(self.zoom)
        layout.addLayout(selection)
        self.timeline = TabTimeline()
        self.timeline.seek.connect(lambda seconds: self.player.setPosition(round(seconds*1000)))
        self.timeline.note_selected.connect(self.select_note)
        self.timeline.edit_requested.connect(self.edit_note)
        self.timeline.note_moved.connect(self.move_note)
        layout.addWidget(self.timeline, 2)
        note_tools = QHBoxLayout()
        self.edit_buttons = []
        for label, callback in [("Добавить ноту", self.add_note), ("Изменить", self.edit_selected),
                                ("Удалить", self.delete_selected), ("Copy TAB", self.copy_tab),
                                ("Сохранить проект", self.save), ("Экспорт", self.export)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            note_tools.addWidget(button)
            self.edit_buttons.append(button)
        self.note_info = QLabel("Клик по ноте → переход; двойной клик → редактор")
        note_tools.addWidget(self.note_info, 1)
        layout.addLayout(note_tools)
        progress_layout = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.cancel_button = QPushButton("Отменить анализ")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_analysis)
        progress_layout.addWidget(self.progress, 1)
        progress_layout.addWidget(self.cancel_button)
        layout.addLayout(progress_layout)
        self.setCentralWidget(root)

    def action(self, menu, text, callback, shortcut=None):
        action = QAction(text, self)
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(shortcut)
        menu.addAction(action)
        return action

    def build_actions(self):
        files = self.menuBar().addMenu("Файл")
        self.action(files, "Загрузить видео", self.open_video, QKeySequence.StandardKey.Open)
        self.action(files, "Открыть проект", self.open_project, "Ctrl+Shift+O")
        self.action(files, "Сохранить", self.save, QKeySequence.StandardKey.Save)
        self.action(files, "Сохранить как…", lambda: self.save(True), "Ctrl+Shift+S")
        recent = files.addMenu("Недавние проекты")
        for path in self.preferences.recent():
            self.action(recent, Path(path).name, lambda checked=False, p=path: self.open_project_path(Path(p)))
        self.action(files, "Перепривязать видео", self.relink)
        self.action(files, "Экспорт TAB", self.export)
        self.action(files, "Выход", self.close)
        edit = self.menuBar().addMenu("Правка")
        self.undo_action = self.undo_stack.createUndoAction(self, "Отменить")
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        edit.addAction(self.undo_action)
        self.redo_action = self.undo_stack.createRedoAction(self, "Повторить")
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        edit.addAction(self.redo_action)
        self.action(edit, "Добавить ноту", self.add_note, "Ctrl+N")
        self.action(edit, "Редактировать ноту", self.edit_selected, "Ctrl+E")
        self.action(edit, "Удалить ноту", self.delete_selected, "Delete")
        self.action(edit, "Копировать ноту", self.copy_note, "Ctrl+C")
        self.action(edit, "Вставить ноту", self.paste_note, "Ctrl+V")
        self.action(edit, "Copy TAB", self.copy_tab, "Ctrl+Shift+C")
        view = self.menuBar().addMenu("Воспроизведение")
        for text, key, callback in [("Play / Pause", "Space", self.toggle_play),
                                    ("Назад 1 с", "Left", lambda: self.seek_delta(-1)),
                                    ("Вперёд 1 с", "Right", lambda: self.seek_delta(1)),
                                    ("Назад 10 с", "Shift+Left", lambda: self.seek_delta(-10)),
                                    ("Вперёд 10 с", "Shift+Right", lambda: self.seek_delta(10))]:
            self.action(view, text, callback, key)

    def update_title(self, *args):
        mark = "" if self.undo_stack.isClean() else " *"
        self.setWindowTitle(f"{self.project.title}{mark} — Guitar Tab AI")

    def apply_project(self, project: Project):
        self.project = project
        source = QUrl.fromLocalFile(project.video_path) if project.video_path else QUrl()
        if self.player.source() != source:
            self.player.setSource(source)
        self.sync_controls()
        self.timeline.set_project(project)
        self.timeline.position(self.player.position()/1000)
        summary = project.analysis_summary
        tempo = f"{project.rhythm.tempo:.1f} BPM (оценка)" if project.rhythm.tempo else "не определён"
        tracking = "оценка по калибровке" if summary.get("video_tracking_active") else "НЕ АКТИВНО"
        self.summary.setText(f"Строй: {project.guitar.tuning_name}; капо: {project.guitar.capo}\n"
                             f"Темп: {tempo}\nНоты: {len(project.notes)}; с ?: {sum(n.uncertain for n in project.notes)}\n"
                             f"TAB на видео: {'да' if summary.get('tab_overlay') else 'не подтверждена'}\n"
                             f"Определение ладов по пальцам: {tracking}\n"
                             f"Режим: {summary.get('mode', 'не анализировалось')}")
        self.warnings.setPlainText('\n'.join(project.warnings))
        if self.selected_id in self.timeline.items_by_id:
            self.timeline.items_by_id[self.selected_id].setSelected(True)
        self.update_title()

    def unsaved_ok(self):
        if self.undo_stack.isClean():
            return True
        answer = QMessageBox.question(self, "Несохранённые изменения", "Сохранить изменения проекта?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return True

    def busy(self):
        return self.worker is not None

    def open_video(self):
        if self.busy():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Загрузить видео", "", "Видео (*.mp4 *.mov *.mkv *.avi *.webm)")
        if path:
            self.import_video(Path(path))

    def import_video(self, path: Path):
        if self.busy() or not self.unsaved_ok():
            return
        from guitar_tab_ai.audio.extractor import SUPPORTED_VIDEO
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_VIDEO:
            QMessageBox.warning(self, "Видео", "Неподдерживаемый или отсутствующий файл")
            return
        self.project_path = None
        self.selected_id = None
        self.undo_stack.clear()
        project = Project(title=path.stem, video_path=str(path.resolve()), settings=self.config.model_copy(deep=True))
        self.apply_project(project)
        self.sync_controls()
        self.player.setSource(QUrl.fromLocalFile(project.video_path))
        self.start_analysis(False)

    def open_project(self):
        if self.busy():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Открыть проект", "", "Guitar TAB (*.gtabproject)")
        if path:
            self.open_project_path(Path(path))

    def open_project_path(self, path: Path):
        if self.busy() or not self.unsaved_ok():
            return
        try:
            project = load_project(path)
            self.project_path = path
            self.selected_id = None
            self.undo_stack.clear()
            self.apply_project(project)
            self.sync_controls()
            self.player.setSource(QUrl.fromLocalFile(project.video_path))
            self.preferences.remember(path)
            if not Path(project.video_path).is_file():
                QMessageBox.information(self, "Видео перемещено", "TAB загружена. Выберите Файл → Перепривязать видео.")
        except (OSError, ValueError, KeyError) as exc:
            self.error(str(exc))

    def sync_controls(self):
        g, c = self.project.guitar, self.project.settings
        self.tuning.setCurrentText(g.tuning_name if g.tuning_name in TUNINGS else "Custom")
        names = [("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")[n%12]+str(n//12-1)
                 for n in g.open_strings]
        self.custom_tuning.setText(' '.join(names))
        self.capo.setValue(g.capo)
        self.frets.setValue(g.frets)
        self.backend.setCurrentIndex(max(0, self.backend.findData(c.audio_backend)))
        self.transcription_profile.setCurrentIndex(max(0, self.transcription_profile.findData(c.transcription_profile)))
        self.audio_threshold.setValue(c.minimum_audio_confidence)
        self.hand_model.setText(c.hand_model or "")
        self.ocr_enabled.setChecked(c.ocr_enabled)
        self.video_enabled.setChecked(c.video_enabled)

    def save(self, save_as=False):
        if self.busy():
            return False
        path = self.project_path
        if path is None or save_as:
            name, _ = QFileDialog.getSaveFileName(self, "Сохранить проект", self.project.title+".gtabproject",
                                                 "Guitar TAB (*.gtabproject)")
            if not name:
                return False
            path = Path(name)
            if path.suffix.lower() != ".gtabproject":
                path = path.with_suffix(".gtabproject")
        try:
            save_project(self.project, path)
            self.project_path = path
            self.preferences.remember(path)
            self.undo_stack.setClean()
            self.statusBar().showMessage(f"Проект сохранён: {path.name}")
            return True
        except (OSError, ValueError) as exc:
            self.error(str(exc))
            return False

    def relink(self):
        if self.busy():
            return
        name, _ = QFileDialog.getOpenFileName(self, "Новое расположение видео", "", "Видео (*.mp4 *.mov *.mkv *.avi *.webm)")
        if name:
            after = self.project.model_copy(deep=True)
            after.video_path = str(Path(name).resolve())
            self.commit(after, "Перепривязать видео")
            self.player.setSource(QUrl.fromLocalFile(after.video_path))

    def export(self):
        if self.busy():
            return
        name, _ = QFileDialog.getSaveFileName(self, "Экспорт TAB", self.project.title+".txt",
            "ASCII TAB (*.txt);;JSON (*.json);;MIDI (*.mid);;MusicXML (*.musicxml);;PNG (*.png);;PDF (*.pdf)")
        if not name:
            return
        path = Path(name)
        exporter = EXPORTERS.get(path.suffix.lower().lstrip('.'))
        if exporter is None:
            self.error("Укажите расширение: txt, json, mid, musicxml, png или pdf")
            return
        try:
            exporter(self.project, path)
            self.statusBar().showMessage(f"Экспортирован {path.name}")
        except (OSError, ValueError, RuntimeError) as exc:
            self.error(str(exc))

    def copy_tab(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(ascii_tab(self.project.notes, self.project.guitar))
        self.statusBar().showMessage("TAB скопирована")

    def commit(self, after: Project, text: str):
        after.chords = group_chords(after.notes)
        self.undo_stack.push(ProjectCommand(self, self.project, after, text))

    def select_note(self, note_id):
        self.selected_id = note_id
        note = next((n for n in self.project.notes if n.id == note_id), None)
        if note:
            self.note_info.setText(f"{note.pitch} · {note.start:.3f} с · "
                                   f"confidence {note.confidence.final:.0%}")

    def edit_selected(self):
        if self.selected_id:
            self.edit_note(self.selected_id)

    def edit_note(self, note_id):
        if self.busy():
            return
        note = next((n for n in self.project.notes if n.id == note_id), None)
        if note is None:
            return
        dialog = NoteDialog(note, self.project.guitar, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            after = self.project.model_copy(deep=True)
            if not note.manual_override:
                after.suppressed.append(SuppressedEvent(start=note.start, end=note.end, midi=note.midi))
            after.notes = [dialog.result_note if n.id == note_id else n for n in after.notes]
            self.commit(after, "Изменить ноту")

    def add_note(self):
        if self.busy():
            return
        start = self.player.position()/1000
        midi = self.project.guitar.midi_at(Position(string=1, fret=0))
        note = NoteEvent(start=start, end=start+0.25, midi=midi, string=1, fret=0)
        dialog = NoteDialog(note, self.project.guitar, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            after = self.project.model_copy(deep=True)
            after.notes.append(dialog.result_note)
            after.notes.sort(key=lambda n: (n.start, n.midi))
            self.commit(after, "Добавить ноту")

    def delete_selected(self):
        if self.busy() or not self.selected_id:
            return
        after = self.project.model_copy(deep=True)
        for n in after.notes:
            if n.id == self.selected_id:
                after.suppressed.append(SuppressedEvent(start=n.start, end=n.end, midi=n.midi))
        after.notes = [n for n in after.notes if n.id != self.selected_id]
        self.commit(after, "Удалить ноту")

    def move_note(self, note_id, start, string):
        if self.busy():
            return
        after = self.project.model_copy(deep=True)
        for i, n in enumerate(after.notes):
            if n.id == note_id:
                if not n.manual_override:
                    after.suppressed.append(SuppressedEvent(start=n.start, end=n.end, midi=n.midi))
                p = Position(string=string, fret=n.fret or 0)
                values = n.model_dump()
                values.update(start=start, end=start+(n.end-n.start), string=string, fret=p.fret,
                              midi=after.guitar.midi_at(p, n.technique), manual_override=True, uncertain=False,
                              sources=sorted(set(n.sources+["manual"])))
                after.notes[i] = NoteEvent.model_validate(values)
        after.notes.sort(key=lambda n: (n.start, n.midi))
        self.commit(after, "Переместить ноту")

    def copy_note(self):
        self.clipboard_note = next((n.model_copy(deep=True) for n in self.project.notes
                                    if n.id == self.selected_id), None)

    def paste_note(self):
        if self.busy() or self.clipboard_note is None:
            return
        from uuid import uuid4
        start = self.player.position()/1000
        n = self.clipboard_note
        values = n.model_dump()
        values.update(id=str(uuid4()), start=start, end=start+n.end-n.start, manual_override=True)
        after = self.project.model_copy(deep=True)
        after.notes.append(NoteEvent.model_validate(values))
        self.commit(after, "Вставить ноту")

    def review_uncertain(self):
        notes = sorted((n for n in self.project.notes if n.uncertain and not n.manual_override), key=lambda n: n.start)
        if not notes:
            self.statusBar().showMessage("Нот, ожидающих проверки, нет")
            return
        current_index = next((i for i, n in enumerate(notes) if n.id == self.selected_id), -1)
        note = notes[(current_index+1) % len(notes)]
        self.select_note(note.id)
        self.player.setPosition(round(note.start*1000))
        self.timeline.centerOn(self.timeline.origin+note.start*self.timeline.scale, 160)
        self.edit_note(note.id)
        corrected = next((n for n in self.project.notes if n.id == note.id), None)
        if corrected and corrected.manual_override and any(n.uncertain and not n.manual_override
                                                           for n in self.project.notes):
            QTimer.singleShot(0, self.review_uncertain)

    def settings_from_controls(self):
        config = self.project.settings.model_copy(deep=True)
        config.audio_backend = self.backend.currentData()
        config.transcription_profile = self.transcription_profile.currentData()
        config.minimum_audio_confidence = self.audio_threshold.value()
        config.frame_sampling_rate = {"Fast": 2, "Balanced": 5, "Maximum accuracy": 12}[self.preset.currentText()]
        config.beam_width = {"Fast": 32, "Balanced": 96, "Maximum accuracy": 256}[self.preset.currentText()]
        config.ocr_enabled = self.ocr_enabled.isChecked()
        config.video_enabled = self.video_enabled.isChecked()
        config.hand_model = self.hand_model.text().strip() or None
        name = self.tuning.currentText()
        if name == "Custom":
            guitar = GuitarModel(tuning_name="Custom", open_strings=tuple(
                pitch_to_midi(x) for x in self.custom_tuning.text().split()),
                capo=self.capo.value(), frets=self.frets.value())
        else:
            guitar = GuitarModel.preset(name, self.capo.value(), self.frets.value())
        return config, guitar

    def start_analysis(self, selection=False):
        if self.busy():
            return
        if not self.project.video_path:
            self.open_video()
            return
        try:
            config, guitar = self.settings_from_controls()
            pending = self.project.model_copy(deep=True)
            pending.settings, pending.guitar = config, guitar
            for n in pending.notes:
                if n.manual_override and n.string is not None:
                    n.midi = guitar.midi_at(Position(string=n.string, fret=n.fret), n.technique)
            config.save(self.root/"config.yaml")
            self.config = config
            interval = (self.range_a.value(), self.range_b.value()) if selection else None
            if interval and interval[1] <= interval[0]:
                raise ValueError("Конец участка должен быть после начала")
        except (OSError, ValueError) as exc:
            self.error(str(exc))
            return
        self.worker = AnalysisWorker(pending, interval)
        self.worker.progress.connect(self.analysis_progress)
        self.worker.completed.connect(self.analysis_completed)
        self.worker.failed.connect(self.error)
        self.worker.cancelled.connect(lambda: self.statusBar().showMessage("Анализ отменён; проект сохранён"))
        self.worker.finished.connect(self.analysis_finished)
        self.set_busy(True)
        self.progress.setValue(0)
        self.worker.start()

    def set_busy(self, value):
        self.timeline.busy = value
        self.timeline.setInteractive(not value)
        for widget in self.edit_buttons + [self.analyze_button, self.reanalyze_button, self.calibrate_button,
            self.review_button, self.tuning, self.custom_tuning, self.capo, self.frets, self.backend,
            self.preset, self.hand_model, self.ocr_enabled, self.video_enabled,
            self.transcription_profile, self.audio_threshold]:
            widget.setEnabled(not value)
        self.menuBar().setEnabled(not value)
        self.cancel_button.setEnabled(value)

    def analysis_progress(self, value, message):
        self.progress.setValue(value)
        self.statusBar().showMessage(message)

    def analysis_completed(self, project):
        self.commit(project, "Анализ видео")
        if project.media:
            self.range_b.setValue(min(project.media.duration, max(10, self.range_b.value())))
        self.statusBar().showMessage(f"Анализ завершён: {len(project.notes)} нот. Проверьте аппликатуру.")

    def analysis_finished(self):
        worker = self.worker
        self.worker = None
        self.set_busy(False)
        if worker:
            worker.deleteLater()
        if self.close_pending:
            self.close_pending = False
            QTimer.singleShot(0, self.close)

    def cancel_analysis(self):
        if self.worker:
            self.worker.cancel()
            self.statusBar().showMessage("Остановка после текущего шага модели…")

    def error(self, message):
        log.error("User-visible error: %s", message)
        QMessageBox.warning(self, "Не удалось выполнить действие", message)

    def playback_position(self, milliseconds):
        seconds = milliseconds/1000
        self.seek_slider.blockSignals(True)
        self.seek_slider.setValue(milliseconds)
        self.seek_slider.blockSignals(False)
        self.clock.setText(f"{int(seconds)//60:02}:{seconds%60:06.3f}")
        self.timeline.position(seconds)
        if (self.loop.isChecked() and self.range_b.value() > self.range_a.value()
                and seconds >= self.range_b.value()
                and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState):
            self.player.setPosition(round(self.range_a.value()*1000))

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def seek_delta(self, seconds):
        self.player.setPosition(max(0, self.player.position()+round(seconds*1000)))

    def step_frame(self, direction):
        self.player.pause()
        self.seek_delta(direction/(self.project.media.fps if self.project.media else 30))

    def zoom_changed(self, value):
        self.timeline.scale = value
        self.timeline.set_project(self.project)
        self.timeline.position(self.player.position()/1000)

    def calibrate(self):
        if self.busy() or not self.project.video_path:
            return
        capture = cv2.VideoCapture(self.project.video_path)
        try:
            capture.set(cv2.CAP_PROP_POS_MSEC, self.player.position())
            ok, frame = capture.read()
        finally:
            capture.release()
        if not ok:
            self.error("Не удалось прочитать текущий кадр")
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy()
        dialog = CalibrationDialog(QPixmap.fromImage(image), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            after = self.project.model_copy(deep=True)
            after.settings.neck_roi = dialog.image.points
            after.settings.neck_start_fret = dialog.start_fret.value()
            after.settings.neck_end_fret = dialog.end_fret.value()
            self.commit(after, "Калибровка грифа")
            self.statusBar().showMessage("Калибровка сохранена. Для анализа пальцев нужна модель рук.")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.busy():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            if paths[0].suffix == ".gtabproject":
                self.open_project_path(paths[0])
            else:
                self.import_video(paths[0])
            event.acceptProposedAction()

    def closeEvent(self, event):
        if self.busy():
            self.close_pending = True
            self.cancel_analysis()
            event.ignore()
            return
        if not self.unsaved_ok():
            event.ignore()
            return
        self.player.stop()
        event.accept()
