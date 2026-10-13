import threading
import xml.etree.ElementTree as ET

import numpy as np
import pretty_midi
import pytest
import soundfile as sf

from guitar_tab_ai.audio.extractor import Cancelled, probe_video
from guitar_tab_ai.audio.transcription import BasicPitchTranscriber, SpectralTranscriber
from guitar_tab_ai.core.config import AppConfig
from guitar_tab_ai.core.project import Project
from guitar_tab_ai.export.formats import export_json, export_midi, export_musicxml, export_text
from guitar_tab_ai.storage.project_storage import load_project, save_project
from guitar_tab_ai.workers.pipeline import analyze


def test_spectral_transcribes_known_melody(melody):
    path, expected = melody
    result = SpectralTranscriber().transcribe(path, threading.Event(), lambda *_: None)
    assert [n.midi for n in result.notes] == expected
    assert all(abs(n.start-i*.65) < .12 for i, n in enumerate(result.notes))
    assert all(.3 < n.end-n.start < .8 for n in result.notes)
    assert all(0 < n.confidence.audio < 1 for n in result.notes)


def test_silence_and_cancellation(tmp_path):
    path = tmp_path/"silent.wav"
    sf.write(path, np.zeros(44100), 44100)
    result = SpectralTranscriber().transcribe(path, threading.Event(), lambda *_: None)
    assert result.notes == []
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        SpectralTranscriber().transcribe(path, cancel, lambda *_: None)


def test_basic_pitch_real_inference(melody):
    pytest.importorskip("basic_pitch")
    path, expected = melody
    result = BasicPitchTranscriber().transcribe(path, threading.Event(), lambda *_: None)
    assert result.notes
    assert len({n.midi for n in result.notes} & set(expected)) >= 3
    assert result.backend == "basic-pitch"


def test_end_to_end_video_pipeline_export_and_cache(video, tmp_path, monkeypatch):
    monkeypatch.setenv("GTAB_DATA_DIR", str(tmp_path/"data"))
    progress = []
    project = Project(title="Тест", video_path=str(video), settings=AppConfig(ocr_enabled=False,
                                                                           video_enabled=False))
    result = analyze(project, threading.Event(), lambda fraction, text: progress.append(fraction))
    assert [n.midi for n in result.notes] == [40, 45, 50, 55, 59, 64]
    assert all(n.string and n.fret is not None for n in result.notes)
    assert result.media.fps == pytest.approx(30)
    assert result.waveform and result.media.has_audio
    assert progress[-1] == 1
    project_path = tmp_path/"result.gtabproject"
    save_project(result, project_path)
    assert load_project(project_path) == result
    exports = {"txt": export_text, "json": export_json, "mid": export_midi, "musicxml": export_musicxml}
    for ext, exporter in exports.items():
        target = tmp_path/f"tab.{ext}"
        exporter(result, target)
        assert target.stat().st_size > 20
    midi = pretty_midi.PrettyMIDI(str(tmp_path/"tab.mid"))
    assert [n.pitch for n in midi.instruments[0].notes] == [n.midi for n in result.notes]
    assert 'technical' in (tmp_path/"tab.musicxml").read_text()
    assert ET.parse(tmp_path/"tab.musicxml").getroot().tag == "score-partwise"
    assert "Grid:" in (tmp_path/"tab.txt").read_text("utf-8-sig")
    def forbidden(*args, **kwargs):
        raise AssertionError("cached run must not transcribe audio again")
    monkeypatch.setattr(SpectralTranscriber, "transcribe", forbidden)
    repeated = analyze(project, threading.Event(), lambda *_: None)
    assert [n.midi for n in repeated.notes] == [n.midi for n in result.notes]
    # A selection extracts only the interval and translates timestamps back.
    monkeypatch.undo()
    monkeypatch.setenv("GTAB_DATA_DIR", str(tmp_path/"data"))
    result.notes[0].manual_override = True
    selected = analyze(result, threading.Event(), lambda *_: None, (0, 1.3))
    assert selected.notes[0].id == result.notes[0].id
    assert selected.notes[0].manual_override
    assert any(n.start > 2 for n in selected.notes)


def test_corrupt_video_reports_error(tmp_path):
    path = tmp_path/"bad.mp4"
    path.write_bytes(b"not a movie")
    with pytest.raises(RuntimeError, match="ffprobe"):
        probe_video(path, AppConfig(), threading.Event())
