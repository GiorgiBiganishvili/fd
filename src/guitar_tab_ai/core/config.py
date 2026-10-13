"""User configuration and application paths; never store credentials."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import Field

from guitar_tab_ai.core.events import Record


def data_directory() -> Path:
    override = os.environ.get("GTAB_DATA_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "GuitarTabAI"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "guitar-tab-ai"


class FusionWeights(Record):
    audio: float = Field(1.0, ge=0)
    video: float = Field(1.4, ge=0)
    ocr: float = Field(1.8, ge=0)
    hand_position: float = Field(0.35, ge=0)
    fret_distance: float = Field(0.22, ge=0)
    string_distance: float = Field(0.12, ge=0)
    stretch: float = Field(0.65, ge=0)
    open_string: float = Field(0.08, ge=0)


class AppConfig(Record):
    audio_backend: str = "auto"
    transcription_profile: str = "polyphonic"
    minimum_audio_confidence: float = Field(0.45, ge=0, le=1)
    frame_sampling_rate: float = Field(5, gt=0, le=30)
    confidence_threshold: float = Field(0.65, ge=0, le=1)
    beam_width: int = Field(96, ge=8, le=512)
    max_analysis_seconds: float = Field(1800, gt=0)
    ocr_enabled: bool = True
    video_enabled: bool = True
    weights: FusionWeights = Field(default_factory=FusionWeights)
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    tesseract: str = "tesseract"
    hand_model: str | None = None
    # ROI order: nut-high, bridge-high, bridge-low, nut-low; normalized coordinates.
    neck_roi: list[tuple[float, float]] | None = None
    neck_start_fret: int = Field(0, ge=0, le=24)
    neck_end_fret: int = Field(12, ge=1, le=36)
    ocr_roi: tuple[float, float, float, float] | None = None

    @classmethod
    def load(cls, path: Path) -> AppConfig:
        return cls.model_validate(yaml.safe_load(path.read_text("utf-8")) or {}) if path.exists() else cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(self.model_dump(mode="json"), allow_unicode=True), "utf-8")
