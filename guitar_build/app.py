from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import medfilt
from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QFileDialog, QHBoxLayout, QMainWindow,
    QMessageBox, QPushButton, QPlainTextEdit, QProgressBar, QSlider, QSplitter,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
STANDARD_TUNING = (40, 45, 50, 55, 59, 64)  # low -> high
LABELS = {1: "e", 2: "B", 3: "G", 4: "D", 5: "A", 6: "E"}


@dataclass
class NoteEvent:
    start: float
    end: float
    pitch: str
    midi: int
    string: int | None = None
    fret: int | None = None
    confidence: float = 0.0
    manual_override: bool = False


def midi_to_note(midi: int) -> str:
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def ffmpeg_path() -> str:
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidate = Path(bundle) / "ffmpeg.exe"
        if candidate.exists():
            return str(candidate)
    if getattr(sys, "frozen", False):
        candidate = Path(sys.executable).resolve().parent / "ffmpeg.exe"
        if candidate.exists():
            return str(candidate)
    return "ffmpeg.exe" if os.name == "nt" else "ffmpeg"


def extract_audio(video: Path, wav: Path) -> None:
    wav.parent.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.run(
        [ffmpeg_path(), "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(wav)],
        capture_output=True, text=True, creationflags=flags,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-3000:] or "FFmpeg failed")


def transcribe_monophonic(wav_path: Path) -> list[NoteEvent]:
    y, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
    if y.ndim == 2:
        y = np.mean(y, axis=1)
    frame_size, hop = 4096, 512
    if y.size < frame_size:
        return []
    peak = float(np.max(np.abs(y)))
    if peak < 1e-5:
        return []
    y = y / peak
    window = np.hanning(frame_size).astype(np.float32)
    freqs = np.fft.rfftfreq(frame_size, d=1.0 / sr)
    valid_idx = np.flatnonzero((freqs >= 70.0) & (freqs <= 1400.0))
    raw: list[float] = []
    confs: list[float] = []

    for start in range(0, len(y) - frame_size + 1, hop):
        frame = y[start:start + frame_size]
        rms = float(np.sqrt(np.mean(frame * frame)))
        if rms < 0.008:
            raw.append(np.nan); confs.append(0.0); continue
        spectrum = np.abs(np.fft.rfft(frame * window))
        band = spectrum[valid_idx]
        if not band.size or float(np.max(band)) <= 0:
            raw.append(np.nan); confs.append(0.0); continue
        scores = band.copy()
        for harmonic, weight in ((2, 0.55), (3, 0.35), (4, 0.2)):
            src = valid_idx * harmonic
            ok = src < spectrum.size
            harmonic_energy = np.zeros_like(scores)
            harmonic_energy[ok] = spectrum[src[ok]]
            scores += harmonic_energy * weight
        local = int(np.argmax(scores))
        hz = float(freqs[int(valid_idx[local])])
        midi = 69.0 + 12.0 * math.log2(hz / 440.0)
        dominance = float(band[local] / (float(np.median(band)) + 1e-9))
        conf = min(0.90, max(0.20, 0.18 + math.log10(max(1.0, dominance)) * 0.25))
        raw.append(midi); confs.append(conf)

    arr = np.array(raw, dtype=float)
    finite = np.isfinite(arr)
    rounded = np.full(arr.shape, np.nan)
    rounded[finite] = np.rint(arr[finite])
    filled = np.where(finite, rounded, 0.0)
    smoothed = medfilt(filled, kernel_size=3)
    smoothed[~finite] = np.nan
    times = np.arange(len(smoothed), dtype=float) * (hop / sr)

    events: list[NoteEvent] = []
    current: int | None = None
    start_idx: int | None = None
    probs: list[float] = []

    def close(end_idx: int) -> None:
        nonlocal current, start_idx, probs
        if current is None or start_idx is None:
            return
        st = float(times[start_idx])
        et = float(min(len(y) / sr, times[min(end_idx, len(times)-1)] + frame_size / sr))
        if et - st >= 0.055:
            c = float(np.mean(probs)) if probs else 0.35
            events.append(NoteEvent(st, et, midi_to_note(current), current, confidence=c))
        current = None; start_idx = None; probs = []

    for i, value in enumerate(smoothed):
        val = int(value) if np.isfinite(value) else None
        if val != current:
            close(i)
            if val is not None:
                current = val; start_idx = i
        if val is not None:
            probs.append(confs[i])
    close(len(smoothed)-1)
    return events


def positions_for_midi(midi: int, max_fret: int = 24) -> list[tuple[int, int]]:
    out = []
    for string in range(1, 7):
        open_midi = STANDARD_TUNING[6-string]
        fret = midi - open_midi
        if 0 <= fret <= max_fret:
            out.append((string, fret))
    return out


def choose_fingering(events: list[NoteEvent]) -> list[NoteEvent]:
    if not events:
        return []
    candidates = [positions_for_midi(e.midi) for e in events]
    if any(not c for c in candidates):
        return events
    dp: list[dict[tuple[int,int], tuple[float, tuple[int,int] | None]]] = []
    dp.append({p: ((-0.25 if p[1] == 0 else 0.0) + p[1]*0.02, None) for p in candidates[0]})
    for i in range(1, len(events)):
        layer = {}
        for p in candidates[i]:
            best_cost, best_prev = float("inf"), None
            for q, (cost, _) in dp[i-1].items():
                score = cost + abs(p[1]-q[1]) + abs(p[0]-q[0])*0.65 + p[1]*0.02 + (-0.25 if p[1] == 0 else 0)
                if score < best_cost:
                    best_cost, best_prev = score, q
            layer[p] = (best_cost, best_prev)
        dp.append(layer)
    last = min(dp[-1], key=lambda p: dp[-1][p][0])
    path = [last]
    for i in range(len(events)-1, 0, -1):
        prev = dp[i][path[-1]][1]
        assert prev is not None
        path.append(prev)
    path.reverse()
    for e, (s, f) in zip(events, path):
        if not e.manual_override:
            e.string, e.fret = s, f
    return events


def generate_tab(events: list[NoteEvent], width: int = 100) -> str:
    rows = {s: list("-" * width) for s in range(1, 7)}
    if events:
        end = max(e.end for e in events) or 1.0
        for e in events:
            if e.string is None or e.fret is None:
                continue
            token = str(e.fret)
            col = min(width-len(token), max(0, int((e.start/end)*(width-len(token)))))
            for j, ch in enumerate(token):
                rows[e.string][col+j] = ch
    return "\n".join(f"{LABELS[s]}|{''.join(rows[s])}|" for s in range(1, 7))


class AnalysisThread(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, video: Path):
        super().__init__(); self.video = video

    def run(self):
        try:
            cache = Path(tempfile.gettempdir()) / "GuitarTabAI" / self.video.stem
            wav = cache / "audio.wav"
            extract_audio(self.video, wav)
            self.done.emit(choose_fingering(transcribe_monophonic(wav)))
        except Exception as exc:
            self.failed.emit(str(exc))


class NoteTable(QTableWidget):
    seek_requested = Signal(float)
    notes_changed = Signal(object)
    HEADERS = ["Start", "End", "Pitch", "MIDI", "String", "Fret", "Confidence"]

    def __init__(self):
        super().__init__(0, len(self.HEADERS))
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.notes: list[NoteEvent] = []
        self.itemSelectionChanged.connect(self._selection)
        self.itemChanged.connect(self._changed)

    def set_notes(self, notes: list[NoteEvent]):
        self.blockSignals(True)
        self.notes = [NoteEvent(**asdict(n)) for n in notes]
        self.setRowCount(len(notes))
        for r, n in enumerate(self.notes):
            vals = [f"{n.start:.3f}", f"{n.end:.3f}", n.pitch, str(n.midi), str(n.string or ""), str(n.fret if n.fret is not None else ""), f"{n.confidence:.2f}"]
            for c, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if c in (2, 3, 6):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.setItem(r, c, item)
        self.blockSignals(False)

    def _selection(self):
        rows = self.selectionModel().selectedRows()
        if rows:
            self.seek_requested.emit(self.notes[rows[0].row()].start)

    def _changed(self, item: QTableWidgetItem):
        r, c = item.row(), item.column()
        if not (0 <= r < len(self.notes)):
            return
        n = self.notes[r]
        try:
            if c == 0: n.start = float(item.text())
            elif c == 1: n.end = float(item.text())
            elif c == 4: n.string = int(item.text()) if item.text().strip() else None
            elif c == 5: n.fret = int(item.text()) if item.text().strip() else None
            else: return
            if n.end < n.start: raise ValueError
            n.manual_override = True
            self.notes_changed.emit([NoteEvent(**asdict(x)) for x in self.notes])
        except Exception:
            self.set_notes(self.notes)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Guitar Tab AI")
        self.resize(1200, 800)
        self.video_path: Path | None = None
        self.notes: list[NoteEvent] = []
        self.thread: AnalysisThread | None = None
        self.duration = 0

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        video = QVideoWidget(); self.player.setVideoOutput(video)

        self.tab = QPlainTextEdit(); self.tab.setReadOnly(True); self.tab.setPlaceholderText("TAB появится после анализа")
        self.note_table = NoteTable(); self.note_table.seek_requested.connect(self.seek_seconds); self.note_table.notes_changed.connect(self.notes_edited)
        tabs = QTabWidget(); tabs.addTab(self.tab, "TAB"); tabs.addTab(self.note_table, "Ноты")

        self.progress = QProgressBar(); self.progress.setVisible(False)
        self.timeline = QSlider(Qt.Orientation.Horizontal); self.timeline.setRange(0, 1000)
        self.timeline.sliderMoved.connect(self.timeline_seek)
        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(lambda d: setattr(self, "duration", max(0, d)))

        buttons = []
        for label, handler in [
            ("Загрузить видео", self.open_video), ("Анализировать", self.analyze),
            ("Play / Pause", self.play_pause), ("Сохранить проект", self.save_project),
            ("Открыть проект", self.load_project), ("Экспорт TAB", self.export_tab),
        ]:
            b = QPushButton(label); b.clicked.connect(handler); buttons.append(b)
        bar = QHBoxLayout(); [bar.addWidget(b) for b in buttons]
        top = QWidget(); top.setLayout(bar)
        split = QSplitter(Qt.Orientation.Vertical); split.addWidget(video); split.addWidget(tabs)
        root = QVBoxLayout(); root.addWidget(top); root.addWidget(self.progress); root.addWidget(split); root.addWidget(self.timeline)
        host = QWidget(); host.setLayout(root); self.setCentralWidget(host)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls: self.set_video(Path(urls[0].toLocalFile()))

    def open_video(self):
        f, _ = QFileDialog.getOpenFileName(self, "Видео", filter="Video (*.mp4 *.mov *.mkv *.avi *.webm)")
        if f: self.set_video(Path(f))

    def set_video(self, path: Path):
        self.video_path = path
        self.player.setSource(QUrl.fromLocalFile(str(path)))

    def play_pause(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState: self.player.pause()
        else: self.player.play()

    def analyze(self):
        if not self.video_path:
            QMessageBox.information(self, "Guitar Tab AI", "Сначала загрузите видео.")
            return
        self.progress.setRange(0, 0); self.progress.setVisible(True)
        self.thread = AnalysisThread(self.video_path)
        self.thread.done.connect(self.analysis_done); self.thread.failed.connect(self.analysis_failed); self.thread.start()

    def analysis_done(self, notes):
        self.notes = notes; self.refresh(); self.progress.setVisible(False)

    def analysis_failed(self, message: str):
        self.progress.setVisible(False); QMessageBox.critical(self, "Ошибка анализа", message)

    def refresh(self):
        self.tab.setPlainText(generate_tab(self.notes)); self.note_table.set_notes(self.notes)

    def notes_edited(self, notes):
        self.notes = notes; self.tab.setPlainText(generate_tab(self.notes))

    def seek_seconds(self, seconds: float): self.player.setPosition(int(seconds * 1000))

    def position_changed(self, position: int):
        if self.duration and not self.timeline.isSliderDown():
            self.timeline.setValue(int(position / self.duration * 1000))

    def timeline_seek(self, value: int):
        if self.duration: self.player.setPosition(int(value / 1000 * self.duration))

    def save_project(self):
        if not self.video_path: return
        f, _ = QFileDialog.getSaveFileName(self, "Сохранить", filter="Guitar Tab Project (*.gtabproject)")
        if not f: return
        data = {"version": 1, "source_video": str(self.video_path), "notes": [asdict(n) for n in self.notes]}
        with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.json", json.dumps(data, ensure_ascii=False, indent=2))

    def load_project(self):
        f, _ = QFileDialog.getOpenFileName(self, "Открыть", filter="Guitar Tab Project (*.gtabproject)")
        if not f: return
        with zipfile.ZipFile(f, "r") as zf:
            data = json.loads(zf.read("project.json").decode("utf-8"))
        self.video_path = Path(data["source_video"]); self.notes = [NoteEvent(**n) for n in data.get("notes", [])]
        self.player.setSource(QUrl.fromLocalFile(str(self.video_path))); self.refresh()

    def export_tab(self):
        if not self.notes: return
        f, _ = QFileDialog.getSaveFileName(self, "Экспорт TAB", filter="Text (*.txt)")
        if f: Path(f).write_text(generate_tab(self.notes), encoding="utf-8")


def main():
    app = QApplication(sys.argv)
    w = MainWindow(); w.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
