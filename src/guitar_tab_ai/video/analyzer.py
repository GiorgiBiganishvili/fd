"""Sampled OpenCV analysis, calibrated neck geometry and optional hand landmarks."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Protocol

import cv2
import numpy as np

from guitar_tab_ai.audio.extractor import check_cancel
from guitar_tab_ai.core.config import AppConfig
from guitar_tab_ai.core.events import Evidence, Position
from guitar_tab_ai.guitar.model import GuitarModel, fret_fraction


@dataclass
class Frame:
    time: float
    image: np.ndarray


def sample_frames(path: Path, fps: float, cancel: threading.Event, start: float = 0,
                  end: float | None = None) -> Iterator[Frame]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError("OpenCV не может прочитать видео")
    try:
        duration = capture.get(cv2.CAP_PROP_FRAME_COUNT) / max(capture.get(cv2.CAP_PROP_FPS), 1)
        stop = min(duration, end) if end is not None else duration
        time = start
        while time < stop:
            check_cancel(cancel)
            capture.set(cv2.CAP_PROP_POS_MSEC, time*1000)
            ok, image = capture.read()
            if not ok:
                break
            yield Frame(time, image)
            time += 1/fps
    finally:
        capture.release()


class NeckDetector:
    """Conservative line-based proposal. Uncalibrated detections produce no frets."""
    def detect(self, image: np.ndarray) -> tuple[np.ndarray | None, float]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 60, 140)
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, 70,
                                minLineLength=max(50, image.shape[1]//4), maxLineGap=20)
        if lines is None or len(lines) < 3:
            return None, 0
        groups: dict[int, list[np.ndarray]] = {}
        for line in lines[:, 0]:
            angle = np.degrees(np.arctan2(line[3]-line[1], line[2]-line[0])) % 180
            groups.setdefault(int(angle//8), []).append(line)
        group = max(groups.values(), key=len)
        if len(group) < 4:
            return None, 0
        points = np.asarray(group).reshape(-1, 2).astype(np.float32)
        rectangle = cv2.minAreaRect(points)
        _, (width, height), _ = rectangle
        ratio = max(width, height)/max(min(width, height), 1)
        if not 3 < ratio < 25:
            return None, 0
        return cv2.boxPoints(rectangle), min(0.55, len(group)/25)


class StringDetector:
    def detect(self, rectified: np.ndarray, strings: int) -> tuple[list[float], float]:
        gray = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
        strength = np.abs(np.diff(gray.astype(float), axis=0)).mean(axis=1)
        from scipy.signal import find_peaks
        peaks, _ = find_peaks(strength, distance=max(3, len(strength)//(strings*2)),
                             prominence=max(1, float(strength.std())))
        selected = sorted(peaks, key=lambda p: strength[p], reverse=True)[:strings]
        if len(selected) != strings:
            return np.linspace(0.05, 0.95, strings).tolist(), 0.25
        return sorted(float(p/rectified.shape[0]) for p in selected), 0.6


class FretDetector:
    def grid(self, start_fret: int, end_fret: int) -> list[float]:
        """Physical spacing normalized between user-calibrated nut/end boundaries."""
        if end_fret <= start_fret:
            raise ValueError("Конечный лад должен быть выше начального")
        a, b = fret_fraction(start_fret), fret_fraction(end_fret)
        return [(fret_fraction(n)-a)/(b-a) for n in range(start_fret, end_fret+1)]


class HandTracker(Protocol):
    def tips(self, image: np.ndarray, time: float) -> list[tuple[float, float]]: ...


class MediaPipeHandTracker:
    """Tasks API requires an explicitly supplied local hand_landmarker.task model."""
    def __init__(self, model: Path):
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
        self.mp = mp
        options = vision.HandLandmarkerOptions(base_options=python.BaseOptions(model_asset_path=str(model)),
                                               running_mode=vision.RunningMode.VIDEO, num_hands=2)
        self.detector = vision.HandLandmarker.create_from_options(options)

    def tips(self, image: np.ndarray, time: float) -> list[tuple[float, float]]:
        frame = self.mp.Image(image_format=self.mp.ImageFormat.SRGB,
                              data=cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        result = self.detector.detect_for_video(frame, round(time*1000))
        return [(hand[i].x, hand[i].y) for hand in result.hand_landmarks for i in (8, 12, 16, 20)]

    def close(self) -> None:
        self.detector.close()


@dataclass
class HandPositionEstimator:
    history: list[float] = field(default_factory=list)

    def estimate(self, candidates: list[Position]) -> tuple[float | None, float]:
        fretted = [p.fret for p in candidates if p.fret]
        if not fretted:
            return None, 0
        center = float(np.median(fretted))
        self.history = (self.history+[center])[-5:]
        return float(np.median(self.history)), min(0.75, len(fretted)*0.15)


@dataclass
class VideoResult:
    evidence: list[Evidence] = field(default_factory=list)
    visibility: float = 0
    warnings: list[str] = field(default_factory=list)


class VideoAnalyzer:
    def __init__(self, guitar: GuitarModel, config: AppConfig):
        self.guitar, self.config = guitar, config
        self.neck = NeckDetector()
        self.strings = StringDetector()
        self.frets = FretDetector()

    def analyze(self, frames: Iterator[Frame]) -> VideoResult:
        result = VideoResult()
        tracker = None
        if self.config.hand_model:
            if not Path(self.config.hand_model).is_file():
                result.warnings.append("Модель рук не найдена; используется Audio + FingeringSolver")
            else:
                try:
                    tracker = MediaPipeHandTracker(Path(self.config.hand_model))
                except (ImportError, RuntimeError, ValueError) as exc:
                    result.warnings.append(f"MediaPipe недоступен: {exc}")
        if self.config.neck_roi is None:
            result.warnings.append("Гриф не откалиброван. Укажите четыре угла для привязки пальцев к ладам.")
        if tracker is None:
            result.warnings.append("Анализ пальцев не активен: нужен extra hands и локальная модель MediaPipe.")
        grid = self.frets.grid(self.config.neck_start_fret, self.config.neck_end_fret)
        string_rows: list[float] | None = None
        transform = None
        hand_position = HandPositionEstimator()
        try:
            for index, frame in enumerate(frames):
                if self.config.neck_roi is None:
                    if index % 10 == 0:
                        _, confidence = self.neck.detect(frame.image)
                        result.visibility = max(result.visibility, confidence)
                    continue
                h, w = frame.image.shape[:2]
                if transform is None:
                    points = np.asarray(self.config.neck_roi, dtype=np.float32)*[w, h]
                    transform = cv2.getPerspectiveTransform(points.astype(np.float32),
                        np.float32([[0, 0], [999, 0], [999, 199], [0, 199]]))
                    rectangle = cv2.warpPerspective(frame.image, transform, (1000, 200))
                    string_rows, string_confidence = self.strings.detect(rectangle, self.guitar.strings)
                result.visibility = 0.8
                if tracker is None:
                    continue
                points = np.float32([[x*w, y*h] for x, y in tracker.tips(frame.image, frame.time)])
                if not len(points):
                    continue
                normalized = cv2.perspectiveTransform(points.reshape(1, -1, 2), transform)[0]/[999, 199]
                frame_evidence = []
                for x, y in normalized:
                    if not 0 <= x <= 1 or not 0 <= y <= 1:
                        continue
                    string = int(np.argmin(np.abs(np.asarray(string_rows)-y)))+1
                    fret = min(self.config.neck_end_fret,
                               self.config.neck_start_fret + int(np.searchsorted(grid, x)))
                    relative = fret-self.guitar.capo
                    if relative < 0 or relative > self.guitar.frets-self.guitar.capo:
                        continue
                    frame_evidence.append(Evidence(time=frame.time,
                        position=Position(string=string, fret=relative), confidence=0.45*string_confidence,
                        source="video"))
                center, _ = hand_position.estimate([e.position for e in frame_evidence])
                for e in frame_evidence:
                    e.hand_center_fret = center
                result.evidence.extend(frame_evidence)
        finally:
            if tracker:
                tracker.close()
        return result
