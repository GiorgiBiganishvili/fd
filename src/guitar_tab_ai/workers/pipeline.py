"""UI-independent orchestration, cancellation and reusable content-addressed cache."""
from __future__ import annotations

import threading
from pathlib import Path

from guitar_tab_ai.audio.extractor import cache_key, check_cancel, extract_audio, probe_video, waveform
from guitar_tab_ai.audio.note_filter import filter_notes
from guitar_tab_ai.audio.transcription import Progress, make_transcriber, resolve_backend
from guitar_tab_ai.core.config import data_directory
from guitar_tab_ai.core.events import AudioResult, group_chords
from guitar_tab_ai.core.project import Project
from guitar_tab_ai.fusion.fusion_engine import FusionEngine
from guitar_tab_ai.guitar.fingering_solver import PlayabilityValidator
from guitar_tab_ai.ocr.tab_ocr import OCRResult, TabOCR
from guitar_tab_ai.video.analyzer import VideoAnalyzer, VideoResult, sample_frames


def analyze(project: Project, cancel: threading.Event, progress: Progress,
            selection: tuple[float, float] | None = None) -> Project:
    """Return a new project only after success, preserving the open editor on failure."""
    result = project.model_copy(deep=True)
    config, path = result.settings, Path(result.video_path)
    progress(0.01, "Проверка видео")
    result.media = probe_video(path, config, cancel)
    start, end = selection or (0, result.media.duration)
    if not 0 <= start < end <= result.media.duration+0.001:
        raise ValueError("Неверный интервал анализа")
    if end-start > config.max_analysis_seconds:
        raise ValueError(f"За один проход поддерживается {config.max_analysis_seconds/60:g} минут. "
                         "Выберите более короткий участок.")
    check_cancel(cancel)
    progress(0.04, "Подготовка кэша")
    cache = data_directory()/"cache"/cache_key(path, cancel)
    cache.mkdir(parents=True, exist_ok=True)
    audio = AudioResult(warnings=["В видео нет аудио; нужны синхронизированные OCR-подсказки."])
    if result.media.has_audio:
        progress(0.08, "Извлечение аудио FFmpeg")
        wav = extract_audio(path, cache/f"audio-{start:.6f}-{end:.6f}.wav", config, cancel, start, end)
        if selection is None:
            result.waveform = waveform(wav)
        backend = resolve_backend(config.audio_backend)
        low = min(result.guitar.open_strings)+result.guitar.capo
        high = max(result.guitar.open_strings)+result.guitar.frets
        audio_cache = cache/f"notes-v2-{backend}-{low}-{high}-{start:.6f}-{end:.6f}.json"
        if audio_cache.exists():
            audio = AudioResult.model_validate_json(audio_cache.read_text("utf-8"))
        else:
            audio = make_transcriber(backend, low, high).transcribe(wav, cancel,
                lambda fraction, message: progress(0.12+0.48*fraction, message))
            temporary = audio_cache.with_suffix(".tmp")
            temporary.write_text(audio.model_dump_json(), "utf-8")
            temporary.replace(audio_cache)
        for note in audio.notes:
            values = note.model_dump()
            values.update(start=note.start+start, end=min(end, note.end+start))
            note.__dict__.update(type(note).model_validate(values).__dict__)
        audio.rhythm.beats = [t+start for t in audio.rhythm.beats]
    raw_count = len(audio.notes)
    audio.notes = filter_notes(audio.notes, result.guitar, config)
    filtered_count = raw_count-len(audio.notes)
    if filtered_count:
        audio.warnings.append(f"Отфильтровано кандидатов: {filtered_count} (слабые, короткие, "
                              "дублирующиеся или вне строя).")
    audio.warnings.append("Запись с вокалом, басом и ударными может давать чужие ноты. "
                          "Для точной TAB используйте отдельную дорожку гитары.")
    check_cancel(cancel)
    progress(0.62, "Распознавание грифа и рук")
    video = VideoResult()
    if config.video_enabled:
        video = VideoAnalyzer(result.guitar, config).analyze(
            sample_frames(path, config.frame_sampling_rate, cancel, start, end))
    progress(0.77, "Поиск и чтение TAB")
    ocr = OCRResult()
    if config.ocr_enabled:
        # OCR costs more per frame; reuse coarse timestamps at <= 2 FPS.
        ocr = TabOCR(config, result.guitar.strings, result.guitar.frets-result.guitar.capo).analyze(
            sample_frames(path, min(2, config.frame_sampling_rate), cancel, start, end))
    check_cancel(cancel)
    progress(0.92, "Объединение источников и выбор аппликатуры")
    manual = [n for n in result.notes if n.manual_override and n.start < end and n.end > start]
    notes = FusionEngine(result.guitar, config).fuse(audio, video.evidence, ocr.evidence, manual)
    result.replace_interval(start, end, notes)
    result.observations = [e for e in result.observations if not start <= e.time < end]
    result.observations.extend(video.evidence+ocr.evidence)
    result.chords = group_chords(result.notes)
    if selection is None:
        result.rhythm = audio.rhythm
    result.warnings = audio.warnings+video.warnings+ocr.warnings
    result.warnings += PlayabilityValidator().validate(result.notes)
    timed_ocr = any(e.synchronized for e in ocr.evidence)
    if timed_ocr:
        mode = "Hybrid" if audio.notes or video.evidence else "TAB OCR"
    elif audio.notes:
        mode = "Audio + Video" if video.evidence else "Audio priority"
    else:
        mode = "Нет подтверждённых событий"
    result.analysis_summary = {
        "backend": audio.backend, "notes": len(result.notes), "filtered_candidates": filtered_count,
        "low_confidence": sum(n.uncertain for n in result.notes), "tab_overlay": ocr.detected,
        "ocr_symbols": ocr.symbols, "video_visibility": video.visibility,
        "audio_quality": audio.quality,
        "mode": mode,
    }
    progress(1, "Готово — проверьте ноты со знаком ?")
    return result
