"""Cancellable FFmpeg import with disk cache and bounded waveform memory."""
from __future__ import annotations

import hashlib
import json
import subprocess
import threading
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf

from guitar_tab_ai.core.config import AppConfig
from guitar_tab_ai.core.project import MediaInfo

SUPPORTED_VIDEO = {".mp4", ".mov", ".mkv", ".avi", ".webm"}


class Cancelled(RuntimeError):
    pass


def check_cancel(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise Cancelled("Анализ отменён")


def run_process(args: list[str], cancel: threading.Event, timeout: float = 600) -> str:
    """Poll communicate rather than filling pipes or freezing cancellation."""
    import time
    started = time.monotonic()
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          encoding="utf-8", errors="replace", **kwargs) as process:
        try:
            while True:
                check_cancel(cancel)
                if time.monotonic() - started > timeout:
                    raise TimeoutError("Превышено время ожидания FFmpeg")
                try:
                    output, error = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                raise RuntimeError(f"Ошибка {Path(args[0]).name}: {error[-2000:]}")
            return output
        except BaseException:
            process.kill()
            process.communicate()
            raise


def probe_video(path: Path, config: AppConfig, cancel: threading.Event) -> MediaInfo:
    if path.suffix.lower() not in SUPPORTED_VIDEO or not path.is_file():
        raise ValueError("Выберите существующий MP4, MOV, MKV, AVI или WEBM")
    data = json.loads(run_process([config.ffprobe, "-v", "error", "-show_streams", "-show_format",
                                   "-of", "json", str(path)], cancel, 30))
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if video is None:
        raise ValueError("В файле нет видеопотока")
    fps = float(Fraction(video.get("avg_frame_rate", "0/1")))
    if not fps:
        fps = float(Fraction(video.get("r_frame_rate", "0/1")))
    duration = float(data.get("format", {}).get("duration", video.get("duration", 0)))
    return MediaInfo(duration=duration, fps=fps, width=video["width"], height=video["height"],
                     has_audio=any(s["codec_type"] == "audio" for s in data["streams"]))


def cache_key(path: Path, cancel: threading.Event | None = None) -> str:
    """Content identity prevents stale analysis after same-name media replacement."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            if cancel is not None:
                check_cancel(cancel)
            digest.update(chunk)
    return digest.hexdigest()


def extract_audio(path: Path, destination: Path, config: AppConfig, cancel: threading.Event,
                  start: float = 0, end: float | None = None) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        with sf.SoundFile(destination) as audio:
            if audio.frames and audio.samplerate == 44100:
                return destination
    partial = destination.with_suffix(".partial.wav")
    args = [config.ffmpeg, "-nostdin", "-v", "error", "-y", "-ss", str(start), "-i", str(path)]
    if end is not None:
        args += ["-t", str(end - start)]
    args += ["-map", "0:a:0", "-vn", "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(partial)]
    try:
        run_process(args, cancel)
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)
    return destination


def waveform(path: Path, bins: int = 1200) -> list[float]:
    with sf.SoundFile(path) as stream:
        block = max(1, int(np.ceil(stream.frames / bins)))
        peaks = []
        while stream.tell() < stream.frames:
            values = stream.read(block, dtype="float32", always_2d=True)
            peaks.append(float(np.max(np.abs(values))))
    return peaks
