from pathlib import Path


def transcribe_media(path, model_name='small', cache_dir=None, progress=None):
    from faster_whisper import WhisperModel
    cache_dir = Path(cache_dir or (Path.home() / '.shortscutter_models'))
    cache_dir.mkdir(parents=True, exist_ok=True)

    def load(device, compute):
        return WhisperModel(model_name, device=device, compute_type=compute, download_root=str(cache_dir))

    if progress:
        progress(0.03, 'Загрузка Whisper…')
    try:
        model = load('cuda', 'float16')
        device = 'CUDA'
    except Exception:
        model = load('cpu', 'int8')
        device = 'CPU'

    def run(m):
        segs, info = m.transcribe(
            str(path), language='ru', word_timestamps=True, vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=350),
        )
        words = []
        idx = 0
        for seg in segs:
            for w in (seg.words or []):
                text = (w.word or '').strip()
                if not text:
                    continue
                words.append({
                    'id': idx,
                    'text': text,
                    'original_text': text,
                    'start': float(w.start),
                    'end': float(w.end),
                    'include': True,
                })
                idx += 1
        return words, info

    try:
        if progress:
            progress(0.10, f'Транскрипция ({device})…')
        words, info = run(model)
    except Exception:
        if device == 'CPU':
            raise
        if progress:
            progress(0.12, 'CUDA недоступна, переключаюсь на CPU…')
        model = load('cpu', 'int8')
        device = 'CPU'
        words, info = run(model)

    return {
        'words': words,
        'language': getattr(info, 'language', 'ru'),
        'duration': float(getattr(info, 'duration', words[-1]['end'] if words else 0.0) or 0.0),
        'device': device,
        'model': model_name,
    }
