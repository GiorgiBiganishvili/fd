import sys, os, json, subprocess, threading
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QTextEdit, QComboBox,
    QMessageBox, QProgressBar, QCheckBox
)

APP = 'Shorts Cutter Beta'


def appdata():
    p = Path(os.getenv('LOCALAPPDATA', Path.home())) / 'ShortsCutter'
    p.mkdir(parents=True, exist_ok=True)
    return p


def tool(name):
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
    p = base / 'tools' / name
    return str(p) if p.exists() else name


def fmt(t):
    t = max(0, int(t))
    return f'{t // 60:02d}:{t % 60:02d}'


def probe_duration(path):
    fp = tool('ffprobe.exe')
    cmd = [fp, '-v', 'error', '-show_entries', 'format=duration', '-of',
           'default=noprint_wrappers=1:nokey=1', path]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, encoding='utf-8', errors='replace',
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if p.returncode != 0:
        raise RuntimeError('FFprobe не смог прочитать файл:\n' + p.stderr[-1200:])
    try:
        return float(p.stdout.strip())
    except Exception:
        raise RuntimeError('FFprobe вернул некорректную длительность файла.')


def has_video_stream(path):
    fp = tool('ffprobe.exe')
    cmd = [fp, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
           'stream=index', '-of', 'csv=p=0', path]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, encoding='utf-8', errors='replace',
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return p.returncode == 0 and bool(p.stdout.strip())


def _ratio(words, start, end):
    try:
        from face_focus import target_ratio
        return target_ratio(words, start, end)
    except Exception:
        return 0.0


def heuristic_candidates(words, maxn=12, target_mode=False):
    if not words:
        return []
    out = []
    step = 35.0 if target_mode else 55.0
    dur = 55.0
    end = words[-1]['end']
    s = 0.0
    i = 1
    while s < end and len(out) < maxn:
        e = min(end, s + dur)
        seg = [w for w in words if w['start'] >= s and w['end'] <= e]
        text = ' '.join(w['text'] for w in seg).strip()
        tr = _ratio(words, s, e) if target_mode else 1.0
        if len(text) > 80 and (not target_mode or tr >= 0.42):
            score = min(88, 55 + len(text) // 45)
            if target_mode:
                score = int(min(95, score + tr * 10))
            out.append({
                'id': i, 'start': s, 'end': e, 'score': score,
                'title': text[:70] + '…',
                'reason': 'Автоматический кандидат по плотности речи.' +
                          (f' Доля речи выбранного человека: {tr:.0%}.' if target_mode else ''),
                'text': text, 'target_ratio': tr,
            })
            i += 1
        s += step
    return out


def llm_candidates(words, api_key, maxn=15, target_mode=False):
    if not api_key:
        return heuristic_candidates(words, maxn, target_mode)
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        if target_mode:
            transcript = ' '.join(
                f"[{w['id']}][{'ME' if w.get('target_speaker') else 'OTHER'}:{float(w.get('target_score',0)):.2f}] {w['text']}"
                for w in words
            )
            target_rule = (
                'КРИТИЧЕСКИ ВАЖНО: ME означает слова выбранного по фотографии человека. '
                'Выбирай только такие диапазоны, где почти весь основной монолог принадлежит ME. '
                'Не выбирай чужой монолог. Короткая реплика собеседника допустима только если без нее '
                'невозможно понять ответ, но приоритет — исключительно речь ME. '
            )
        else:
            transcript = ' '.join(f"[{w['id']}] {w['text']}" for w in words)
            target_rule = ''
        if len(transcript) > 110000:
            transcript = transcript[:110000]
        prompt = (
            'Ты отбираешь сильные Shorts из русскоязычного психологического подкаста. '
            'Верни только JSON-массив до 15 объектов. Для каждого: start_word_id, end_word_id, '
            'score 0-100, title, reason. Ищи самостоятельную законченную мысль, сильный hook, '
            'противоречие, уязвимость, инсайт. Не начинай и не заканчивай посреди мысли. '
            'Длина примерно 20-90 секунд. Не дублируй идеи. ' + target_rule +
            '\nТранскрипт ниже:\n' + transcript
        )
        r = client.responses.create(model='gpt-5-mini', input=prompt)
        raw = r.output_text.strip()
        a, b = raw.find('['), raw.rfind(']')
        data = json.loads(raw[a:b + 1])
        byid = {w['id']: w for w in words}
        out = []
        for x in data[:maxn * 2]:
            sw, ew = int(x['start_word_id']), int(x['end_word_id'])
            if sw not in byid or ew not in byid or ew <= sw:
                continue
            start, end = byid[sw]['start'], byid[ew]['end']
            tr = _ratio(words, start, end) if target_mode else 1.0
            if target_mode and tr < 0.42:
                continue
            seg = [w for w in words if sw <= w['id'] <= ew]
            out.append({
                'id': len(out) + 1,
                'start': start,
                'end': end,
                'score': int(x.get('score', 70)),
                'title': str(x.get('title', 'Кандидат')),
                'reason': str(x.get('reason', '')) +
                          (f' Доля речи выбранного человека: {tr:.0%}.' if target_mode else ''),
                'text': ' '.join(w['text'] for w in seg),
                'target_ratio': tr,
            })
            if len(out) >= maxn:
                break
        return out or heuristic_candidates(words, maxn, target_mode)
    except Exception:
        return heuristic_candidates(words, maxn, target_mode)


class Signals(QObject):
    progress = Signal(int, str)
    done = Signal(object, object, object)
    fail = Signal(str)
    export_done = Signal(str)
    export_failed = Signal(str)


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP)
        self.resize(1080, 760)
        self.file = ''
        self.ref_photo = ''
        self.words = []
        self.cands = []
        self.target_scan = None
        self.sig = Signals()
        self.sig.progress.connect(self.onprog)
        self.sig.done.connect(self.ondone)
        self.sig.fail.connect(self.onfail)
        self.sig.export_done.connect(self.on_export_done)
        self.sig.export_failed.connect(self.on_export_failed)

        root = QVBoxLayout(self)
        title = QLabel('SHORTS CUTTER')
        title.setStyleSheet('font-size:28px;font-weight:700')
        root.addWidget(title)

        row = QHBoxLayout()
        self.path = QLineEdit(); self.path.setReadOnly(True)
        b = QPushButton('Выбрать видео / аудио'); b.clicked.connect(self.pick)
        row.addWidget(self.path, 1); row.addWidget(b); root.addLayout(row)

        face_row = QHBoxLayout()
        face_row.addWidget(QLabel('Главный человек:'))
        self.face_path = QLineEdit(); self.face_path.setReadOnly(True)
        self.face_path.setPlaceholderText('Не выбран — будет обычный центрированный crop')
        fb = QPushButton('Выбрать мою фотографию'); fb.clicked.connect(self.pick_face)
        face_row.addWidget(self.face_path, 1); face_row.addWidget(fb)
        root.addLayout(face_row)

        self.only_me = QCheckBox('Только я: искать мои слова и при экспорте кадрировать только меня')
        self.only_me.setChecked(True)
        root.addWidget(self.only_me)

        row2 = QHBoxLayout(); row2.addWidget(QLabel('Whisper:'))
        self.model = QComboBox(); self.model.addItems(['small', 'medium', 'base']); row2.addWidget(self.model)
        row2.addWidget(QLabel('OpenAI API key:'))
        self.key = QLineEdit(); self.key.setEchoMode(QLineEdit.Password); row2.addWidget(self.key, 1)
        root.addLayout(row2)

        self.run = QPushButton('Анализировать'); self.run.clicked.connect(self.analyze); root.addWidget(self.run)
        self.pb = QProgressBar(); root.addWidget(self.pb)
        self.status = QLabel('Готов'); root.addWidget(self.status)

        mid = QHBoxLayout()
        self.list = QListWidget(); self.list.currentItemChanged.connect(self.show_candidate); mid.addWidget(self.list, 1)
        self.text = QTextEdit(); self.text.setReadOnly(True); mid.addWidget(self.text, 2); root.addLayout(mid, 1)

        erow = QHBoxLayout()
        self.export = QPushButton('Экспортировать выбранный 9:16')
        self.export.clicked.connect(self.export_clip); erow.addWidget(self.export); root.addLayout(erow)

        self.setStyleSheet(
            'QWidget{background:#16151b;color:#eee;font-size:14px} '
            'QLineEdit,QTextEdit,QListWidget,QComboBox{background:#23212a;border:1px solid #444;padding:6px} '
            'QPushButton{background:#6d4aff;border:0;padding:10px 14px;border-radius:6px} '
            'QPushButton:disabled{background:#444}'
        )

    def pick(self):
        f, _ = QFileDialog.getOpenFileName(self, 'Выберите выпуск', '',
            'Media (*.mp4 *.mkv *.mov *.avi *.webm *.mp3 *.wav *.m4a *.flac *.ogg);;Все файлы (*.*)')
        if f:
            self.file = f; self.path.setText(f); self.target_scan = None

    def pick_face(self):
        f, _ = QFileDialog.getOpenFileName(self, 'Выберите фотографию себя', '',
            'Images (*.jpg *.jpeg *.png *.webp *.bmp);;Все файлы (*.*)')
        if f:
            self.ref_photo = f; self.face_path.setText(f); self.target_scan = None

    def analyze(self):
        if not self.file:
            QMessageBox.warning(self, 'Нет файла', 'Сначала выбери файл.'); return
        if self.only_me.isChecked() and has_video_stream(self.file) and not self.ref_photo:
            QMessageBox.warning(self, 'Нужна фотография', 'Для режима «Только я» выбери фотографию, по которой приложение найдёт тебя в видео.')
            return
        self.run.setEnabled(False); self.list.clear(); self.text.clear(); self.pb.setValue(1)
        threading.Thread(target=self.worker, daemon=True).start()

    def worker(self):
        try:
            self.sig.progress.emit(5, 'Загрузка Whisper…')
            from faster_whisper import WhisperModel
            cache = appdata() / 'models'; cache.mkdir(exist_ok=True)
            model_name = self.model.currentText()
            try:
                m = WhisperModel(model_name, device='cuda', compute_type='float16', download_root=str(cache))
            except Exception:
                m = WhisperModel(model_name, device='cpu', compute_type='int8', download_root=str(cache))

            self.sig.progress.emit(12, 'Транскрипция…')
            try:
                segs, _ = m.transcribe(self.file, language='ru', word_timestamps=True, vad_filter=True)
                words, idx = [], 0
                for seg in segs:
                    for w in (seg.words or []):
                        words.append({'id': idx, 'text': w.word.strip(), 'start': float(w.start), 'end': float(w.end)}); idx += 1
            except Exception:
                m = WhisperModel(model_name, device='cpu', compute_type='int8', download_root=str(cache))
                segs, _ = m.transcribe(self.file, language='ru', word_timestamps=True, vad_filter=True)
                words, idx = [], 0
                for seg in segs:
                    for w in (seg.words or []):
                        words.append({'id': idx, 'text': w.word.strip(), 'start': float(w.start), 'end': float(w.end)}); idx += 1

            target_mode = bool(self.only_me.isChecked() and self.ref_photo and has_video_stream(self.file))
            scan = None
            if target_mode:
                self.sig.progress.emit(55, 'Ищу тебя в видео и определяю, где говоришь именно ты…')
                from face_focus import TargetFaceAnalyzer, mark_target_words
                analyzer = TargetFaceAnalyzer()
                scan = analyzer.scan(self.file, self.ref_photo, sample_fps=2.5,
                    progress=lambda p: self.sig.progress.emit(55 + int(p * 20), f'Поиск лица: {int(p*100)}%'))
                if scan.get('coverage', 0.0) < 0.08:
                    raise RuntimeError('По выбранной фотографии я почти не нахожу тебя в видео. Выбери более чёткое фото лица анфас.')
                words = mark_target_words(words, scan)

            self.sig.progress.emit(78, 'Поиск сильных фрагментов…')
            cands = llm_candidates(words, self.key.text().strip(), target_mode=target_mode)
            job = appdata() / 'last_job'; job.mkdir(exist_ok=True)
            (job / 'transcript.json').write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding='utf-8')
            (job / 'candidates.json').write_text(json.dumps(cands, ensure_ascii=False, indent=2), encoding='utf-8')
            if scan:
                (job / 'target_face_scan.json').write_text(json.dumps(scan, ensure_ascii=False), encoding='utf-8')
            self.sig.progress.emit(100, 'Готово')
            self.sig.done.emit(words, cands, scan)
        except Exception as e:
            self.sig.fail.emit(str(e))

    def onprog(self, v, s):
        self.pb.setValue(v); self.status.setText(s)

    def ondone(self, words, cands, scan):
        self.words, self.cands, self.target_scan = words, cands, scan
        self.run.setEnabled(True)
        for c in sorted(cands, key=lambda x: x['score'], reverse=True):
            me = f"  Я:{float(c.get('target_ratio',1))*100:.0f}%" if scan else ''
            it = QListWidgetItem(f"{c['score']:>3}/100{me}  {fmt(c['start'])}–{fmt(c['end'])}  {c['title']}")
            it.setData(Qt.UserRole, c); self.list.addItem(it)
        if self.list.count(): self.list.setCurrentRow(0)

    def onfail(self, e):
        self.run.setEnabled(True); self.status.setText('Ошибка'); QMessageBox.critical(self, 'Ошибка', e)

    def show_candidate(self, item, *_):
        if not item: return
        c = item.data(Qt.UserRole)
        me = f"\nРечь выбранного человека: {float(c.get('target_ratio',1))*100:.0f}%" if self.target_scan else ''
        self.text.setPlainText(
            f"{c['title']}\n\n{fmt(c['start'])} → {fmt(c['end'])}\nОценка: {c['score']}/100{me}"
            f"\n\nПочему выбран:\n{c['reason']}\n\nТекст:\n{c['text']}"
        )

    def export_clip(self):
        item = self.list.currentItem()
        if not item: return
        if not has_video_stream(self.file):
            QMessageBox.warning(self, 'Нет видео', 'Этот файл не содержит видеодорожку. Для MP3/WAV можно анализировать текст, но экспорт 9:16 требует видео.'); return
        c = item.data(Qt.UserRole)
        out, _ = QFileDialog.getSaveFileName(self, 'Сохранить Short', 'short.mp4', 'MP4 (*.mp4)')
        if not out: return
        if not out.lower().endswith('.mp4'): out += '.mp4'
        self.status.setText('Экспорт…'); self.export.setEnabled(False); self.pb.setValue(5)

        def work():
            try:
                ff = tool('ffmpeg.exe')
                src_dur = probe_duration(self.file)
                start = max(0.0, min(float(c['start']), max(0.0, src_dur - 0.05)))
                requested = max(0.1, float(c['end']) - float(c['start']))
                dur = max(0.05, min(requested, max(0.05, src_dur - start)))

                if self.only_me.isChecked() and self.ref_photo:
                    from face_focus import estimate_crop, TargetFaceAnalyzer
                    scan = self.target_scan
                    if scan is None:
                        self.sig.progress.emit(15, 'Ищу выбранное лицо в этом фрагменте…')
                        scan = TargetFaceAnalyzer().scan(self.file, self.ref_photo, start=start, end=start+dur, sample_fps=2.5)
                    crop = estimate_crop(scan, start, start + dur)
                    vf = f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']},scale=1080:1920:flags=lanczos,format=yuv420p"
                else:
                    vf = 'scale=w=1080:h=1920:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:1920,format=yuv420p'

                cmd = [ff, '-hide_banner', '-y', '-ss', f'{start:.3f}', '-i', self.file,
                       '-t', f'{dur:.3f}', '-map', '0:v:0', '-map', '0:a:0?', '-vf', vf,
                       '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
                       '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', out]
                p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding='utf-8', errors='replace',
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if p.returncode != 0:
                    logdir = appdata() / 'logs'; logdir.mkdir(exist_ok=True)
                    logpath = logdir / 'last_export_ffmpeg.log'; logpath.write_text(p.stderr, encoding='utf-8', errors='replace')
                    tail = p.stderr[-1800:].strip() or f'FFmpeg завершился с кодом {p.returncode}'
                    raise RuntimeError(f'{tail}\n\nПолный лог: {logpath}')
                op = Path(out)
                if not op.exists() or op.stat().st_size < 1024:
                    raise RuntimeError('FFmpeg завершился без ошибки, но итоговый MP4 не был создан корректно.')
                self.sig.export_done.emit(out)
            except Exception as e:
                self.sig.export_failed.emit(str(e))
        threading.Thread(target=work, daemon=True).start()

    def on_export_done(self, out):
        self.export.setEnabled(True); self.pb.setValue(100); self.status.setText('Экспорт готов: ' + out)
        QMessageBox.information(self, 'Готово', 'Short сохранён:\n' + out)

    def on_export_failed(self, error):
        self.export.setEnabled(True); self.status.setText('Ошибка экспорта'); QMessageBox.critical(self, 'Ошибка экспорта', error)


def main():
    app = QApplication(sys.argv); w = Window(); w.show(); return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
