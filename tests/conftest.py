import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("GTAB_DATA_DIR", str(Path(__file__).parent.parent/".local/tests"))


@pytest.fixture
def melody(tmp_path):
    sr = 44100
    chunks = []
    pitches = [40, 45, 50, 55, 59, 64]
    for midi in pitches:
        t = np.arange(int(sr*.5))/sr
        envelope = np.minimum(1, t/.015)*np.minimum(1, (.5-t)/.02)
        chunks.append(.4*np.sin(2*np.pi*440*2**((midi-69)/12)*t)*envelope)
        chunks.append(np.zeros(int(sr*.15)))
    path = tmp_path/"Гитара №1.wav"
    sf.write(path, np.concatenate(chunks), sr)
    return path, pitches


@pytest.fixture
def video(melody, tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    wav, _ = melody
    video = tmp_path/"Гитара №1.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
        "color=c=black:s=320x180:r=30", "-i", str(wav), "-shortest", "-c:v", "mpeg4",
        "-c:a", "aac", str(video)], check=True)
    return video
