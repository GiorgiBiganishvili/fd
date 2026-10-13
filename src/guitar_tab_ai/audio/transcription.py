"""Real CPU transcription and optional Basic Pitch adapter behind one protocol."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Protocol

import numpy as np
import soundfile as sf
from scipy.signal import find_peaks, stft

from guitar_tab_ai.audio.extractor import check_cancel
from guitar_tab_ai.core.events import AudioResult, Confidence, NoteEvent, Rhythm

Progress = Callable[[float, str], None]


class AudioTranscriber(Protocol):
    def transcribe(self, path: Path, cancel: threading.Event, progress: Progress) -> AudioResult: ...


def estimate_rhythm(onsets: list[float], duration: float) -> Rhythm:
    """Conservative IOI estimate; preserve original timing and mark uncertainty."""
    gaps = np.diff(sorted(set(round(x, 3) for x in onsets)))
    gaps = gaps[(gaps >= 0.18) & (gaps <= 1.5)]
    if len(gaps) < 4:
        return Rhythm()
    period = float(np.median(gaps))
    while period < 0.4:
        period *= 2
    while period > 1:
        period /= 2
    variability = float(np.std(gaps) / max(np.mean(gaps), 1e-6))
    confidence = max(0, 0.65 - variability)
    if confidence < 0.2:
        return Rhythm()
    return Rhythm(tempo=60 / period, beats=np.arange(min(onsets), duration, period).tolist(),
                  confidence=confidence)


class SpectralTranscriber:
    """STFT peak tracker with harmonic suppression, hysteresis and onset resets.

    Intended for exposed melodies/riffs and simple chords. It is an explicit
    baseline, not an ML model; distortion and backing tracks reduce accuracy.
    """
    def transcribe(self, path: Path, cancel: threading.Event, progress: Progress) -> AudioResult:
        active: dict[int, dict[str, float | list[float]]] = {}
        notes: list[NoteEvent] = []
        total_energy = 0.0
        total_frames = 0
        max_amplitude = 0.0
        last_strength: dict[int, float] = {}
        hop, size = 256, 8192
        with sf.SoundFile(path) as stream:
            sr, duration = stream.samplerate, stream.frames / stream.samplerate
            # Process 20-second chunks with overlap, never load a whole video into RAM.
            chunk_frames = sr * 20
            overlap = size
            for block_start in range(0, stream.frames, chunk_frames):
                check_cancel(cancel)
                read_start = max(0, block_start - overlap)
                stream.seek(read_start)
                y = stream.read(min(chunk_frames + 2 * overlap, stream.frames - read_start),
                                dtype="float32", always_2d=True).mean(axis=1)
                max_amplitude = max(max_amplitude, float(np.max(np.abs(y), initial=0)))
                if len(y) < size:
                    y = np.pad(y, (0, size - len(y)))
                freq, times, complex_spec = stft(y, sr, nperseg=size, noverlap=size-hop,
                                                boundary="zeros", padded=True)
                magnitude = np.abs(complex_spec)
                valid_band = (freq >= 25) & (freq <= 1700)
                for column, relative in enumerate(times):
                    time = read_start / sr + float(relative)
                    if time < block_start / sr or time >= min((block_start+chunk_frames)/sr, duration):
                        continue
                    if column % 128 == 0:
                        check_cancel(cancel)
                    spectrum = magnitude[:, column]
                    peak_value = float(spectrum[valid_band].max(initial=0))
                    detected: dict[int, float] = {}
                    if peak_value >= 0.001:
                        peaks, _ = find_peaks(spectrum, height=max(0.0008, peak_value * 0.16), distance=3)
                        fundamental: list[float] = []
                        for index in sorted(peaks, key=lambda p: freq[p]):
                            hz = float(freq[index])
                            if not 25 <= hz <= 1700:
                                continue
                            # Sub-bin parabolic interpolation improves low-string accuracy.
                            a, b, c = np.log(spectrum[index-1:index+2] + 1e-12)
                            delta = float(0.5 * (a-c) / (a-2*b+c)) if abs(a-2*b+c) > 1e-9 else 0
                            hz += np.clip(delta, -0.5, 0.5) * sr / size
                            if any(abs(hz/base - round(hz/base)) < 0.025 and round(hz/base) >= 2
                                   for base in fundamental):
                                continue
                            midi = int(round(69 + 12*np.log2(hz/440)))
                            if not 28 <= midi <= 100:
                                continue
                            fundamental.append(hz)
                            detected[midi] = max(detected.get(midi, 0), float(spectrum[index]))
                            if len(detected) >= 8:
                                break
                    total_energy += peak_value
                    total_frames += 1
                    for midi in list(active):
                        state = active[midi]
                        amplitude = detected.get(midi, 0)
                        # A strong re-attack of the same pitch starts a new note.
                        reattack = (amplitude > last_strength.get(midi, amplitude)*2.8
                                    and time-float(state["start"]) > 0.12)
                        if (time-float(state["last"]) > 0.055 and midi not in detected) or reattack:
                            self._finish(midi, state, notes)
                            del active[midi]
                    for midi, amplitude in detected.items():
                        if midi not in active:
                            active[midi] = {"start": max(0, time-0.012), "last": time, "strength": []}
                        active[midi]["last"] = time
                        active[midi]["strength"].append(amplitude / max(peak_value, 1e-9))
                    last_strength = detected
                progress(min(0.98, (block_start+chunk_frames)/stream.frames), "Анализ спектра аудио")
            for midi, state in active.items():
                self._finish(midi, state, notes)
        notes.sort(key=lambda n: (n.start, n.midi))
        warnings = ["Спектральный режим: ноты и аппликатура требуют проверки; сложная полифония не гарантируется."]
        if max_amplitude < 0.003:
            warnings.append("Аудио отсутствует или слишком тихое")
        quality = min(1, total_energy / max(total_frames, 1) * 15)
        return AudioResult(notes=notes, backend="spectral", quality=quality,
                           rhythm=estimate_rhythm([n.start for n in notes], duration), warnings=warnings)

    @staticmethod
    def _finish(midi: int, state: dict, notes: list[NoteEvent]) -> None:
        start, end = float(state["start"]), float(state["last"]) + 0.01
        if end-start < 0.07:
            return
        confidence = float(np.clip(0.35 + 0.35*np.mean(state["strength"]), 0, 0.7))
        notes.append(NoteEvent(start=start, end=end, midi=midi,
                               confidence=Confidence(audio=confidence), sources=["audio"]))


class BasicPitchTranscriber:
    """Optional polyphonic model. Imports are lazy and model assets stay local."""
    def transcribe(self, path: Path, cancel: threading.Event, progress: Progress) -> AudioResult:
        try:
            from basic_pitch import FilenameSuffix, build_icassp_2022_model_path
            from basic_pitch.inference import predict
        except ImportError as exc:
            raise RuntimeError("Basic Pitch не установлен. Установите extra ml на Python 3.11 "
                               "или выберите спектральный режим.") from exc
        check_cancel(cancel)
        progress(0.05, "Basic Pitch: загрузка локальной модели")
        # predict loads its input into RAM. Keep it bounded and cancellable between
        # overlapping 30-second chunks, assigning each onset to exactly one chunk.
        import tempfile
        from basic_pitch.inference import Model
        model = Model(str(build_icassp_2022_model_path(FilenameSuffix.onnx)))
        notes = []
        with sf.SoundFile(path) as audio:
            duration = audio.frames / audio.samplerate
            with tempfile.TemporaryDirectory(prefix="gtab-ml-") as folder:
                for chunk_start in np.arange(0, duration, 30):
                    check_cancel(cancel)
                    offset = max(0, chunk_start-1)
                    audio.seek(round(offset*audio.samplerate))
                    samples = audio.read(round(32*audio.samplerate), dtype="float32")
                    chunk = Path(folder)/"chunk.wav"
                    sf.write(chunk, samples, audio.samplerate)
                    _, _, events = predict(str(chunk), model)
                    for begin, finish, midi, amplitude, _ in events:
                        start = float(begin)+offset
                        end = min(duration, float(finish)+offset)
                        if not chunk_start <= start < min(chunk_start+30, duration) or end <= start:
                            continue
                        notes.append(NoteEvent(start=start, end=end, midi=int(midi),
                            velocity=max(1, min(127, round(float(amplitude)*127))),
                            confidence=Confidence(audio=min(0.95, max(0, float(amplitude)))),
                            sources=["audio"]))
                    progress(min(0.98, (chunk_start+30)/duration), "Basic Pitch: анализ аудио")
        progress(1, "Basic Pitch завершён")
        return AudioResult(notes=notes, backend="basic-pitch", quality=0.7 if notes else 0,
                           rhythm=estimate_rhythm([n.start for n in notes], duration),
                           warnings=["Confidence модели не является калиброванной вероятностью."])


def make_transcriber(name: str) -> AudioTranscriber:
    if name == "basic-pitch":
        return BasicPitchTranscriber()
    if name == "spectral":
        return SpectralTranscriber()
    raise ValueError(f"Unknown audio backend: {name}")
