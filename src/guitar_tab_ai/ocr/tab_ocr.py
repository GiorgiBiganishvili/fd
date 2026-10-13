"""Six/eight-line TAB detection, digit grouping and conservative highlight timing."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterator, Protocol

import cv2
import numpy as np
import pytesseract

from guitar_tab_ai.core.config import AppConfig
from guitar_tab_ai.core.events import Evidence, Position, Technique
from guitar_tab_ai.guitar.model import NATURAL_HARMONICS
from guitar_tab_ai.video.analyzer import Frame


class OCRBackend(Protocol):
    def digits(self, image: np.ndarray) -> list[tuple[str, float, tuple[int, int, int, int]]]: ...


class TesseractBackend:
    def digits(self, image: np.ndarray) -> list[tuple[str, float, tuple[int, int, int, int]]]:
        data = pytesseract.image_to_data(image, config="--psm 11 -c 'tessedit_char_whitelist=0123456789<>'",
                                         output_type=pytesseract.Output.DICT, timeout=12)
        return [(text.strip(), max(0, min(1, float(data['conf'][i])/100)),
                 (data['left'][i], data['top'][i], data['width'][i], data['height'][i]))
                for i, text in enumerate(data['text']) if re.fullmatch(r"\d+|<\d+>", text.strip())]


class TabDetector:
    def detect(self, image: np.ndarray, strings: int = 6) -> list[tuple[int, int, int, int, list[int]]]:
        """Locate uniformly spaced horizontal staves; false proposals remain low confidence."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)[1]
        lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (max(30, image.shape[1]//8), 1)))
        rows = np.where(np.count_nonzero(lines, axis=1) > image.shape[1]*0.22)[0]
        centers = []
        for row in rows:
            if not centers or row-centers[-1] > 3:
                centers.append(int(row))
        results = []
        for beginning in range(len(centers)-strings+1):
            group = centers[beginning:beginning+strings]
            gaps = np.diff(group)
            if gaps.min() < 7 or np.std(gaps) > max(2, np.mean(gaps)*0.12):
                continue
            margin = round(float(np.mean(gaps))*0.8)
            top, bottom = max(0, group[0]-margin), min(image.shape[0], group[-1]+margin)
            results.append((0, top, image.shape[1], bottom-top, [r-top for r in group]))
        return results


@dataclass
class OCRResult:
    evidence: list[Evidence] = field(default_factory=list)
    detected: bool = False
    warnings: list[str] = field(default_factory=list)
    symbols: int = 0


class TabOCR:
    def __init__(self, config: AppConfig, strings: int = 6, max_fret: int = 24,
                 backend: OCRBackend | None = None):
        self.config, self.strings, self.max_fret = config, strings, max_fret
        self.detector = TabDetector()
        self.backend = backend or TesseractBackend()

    def analyze(self, frames: Iterator[Frame]) -> OCRResult:
        result = OCRResult()
        previous_active: set[tuple[int, int, int]] = set()
        pytesseract.pytesseract.tesseract_cmd = self.config.tesseract
        try:
            for frame in frames:
                image = frame.image
                if self.config.ocr_roi:
                    x, y, w, h = self.config.ocr_roi
                    height, width = image.shape[:2]
                    image = image[int(y*height):int((y+h)*height), int(x*width):int((x+w)*width)]
                proposals = self.detector.detect(image, self.strings)
                active: set[tuple[int, int, int]] = set()
                for x, y, w, h, rows in proposals:
                    result.detected = True
                    roi = image[y:y+h, x:x+w]
                    upscaled = cv2.resize(roi, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
                    gray = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY)
                    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)[1]
                    # Erase only long stave lines; preserve digit strokes.
                    inverse = 255-binary
                    lines = cv2.morphologyEx(inverse, cv2.MORPH_OPEN,
                                             cv2.getStructuringElement(cv2.MORPH_RECT, (90, 1)))
                    cleaned = cv2.bitwise_or(binary, lines)
                    for text, confidence, (left, top, width, height) in self.backend.digits(cleaned):
                        harmonic = bool(re.fullmatch(r"<\d+>", text))
                        if not harmonic and not text.isdigit():
                            continue
                        fret = int(text.strip("<>"))
                        if harmonic and fret not in NATURAL_HARMONICS:
                            continue
                        if fret > self.max_fret or confidence < 0.35:
                            continue
                        center = (top+height/2)/3
                        string = int(np.argmin(np.abs(np.asarray(rows)-center)))+1
                        if abs(rows[string-1]-center) > max(5, (rows[1]-rows[0])*0.48):
                            continue
                        result.symbols += 1
                        color = upscaled[max(0, top-2):top+height+2, max(0, left-2):left+width+2]
                        hsv = cv2.cvtColor(color, cv2.COLOR_BGR2HSV)
                        highlighted = np.count_nonzero((hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 70)) > 10
                        key = (string, fret, round(left/30))
                        if highlighted:
                            active.add(key)
                            if key in previous_active:
                                continue
                        result.evidence.append(Evidence(time=frame.time, position=Position(string=string,
                            fret=fret), confidence=min(0.9, confidence), source="ocr",
                            technique=Technique.HARMONIC if harmonic else None,
                            synchronized=highlighted))
                previous_active = active
        except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError, RuntimeError) as exc:
            result.warnings.append(f"OCR недоступен: {exc}. Используется аудио.")
        if result.detected and not any(e.synchronized for e in result.evidence):
            result.warnings.append("TAB найдена, но временная привязка не подтверждена: статичные цифры "
                                   "не используются как синхронизированные ноты.")
        return result
