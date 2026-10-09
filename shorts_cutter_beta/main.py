import sys, os, json, threading, traceback
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QObject, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QComboBox,
    QMessageBox, QProgressBar, QCheckBox, QTabWidget, QGroupBox, QFormLayout,
    QSpinBox, QDoubleSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QInputDialog
)

from transcription import transcribe_media
from semantic_engine import build_content_map, find_candidates
from editing import build_montage, build_keep_segments, build_zoom_plan, remap_words_to_output, default_color
from captions import segment_words, write_ass, write_srt, parse_srt_vtt, parse_ass, align_plain_text_to_words, font_family_from_file
from render_engine import render
from project_store import create_project, save_json, copy_asset

APP='Shorts Cutter 0.3 Beta'
VERSION='0.3.0-beta'


def appdata():
    p=Path(os.getenv('LOCALAPPDATA',Path.home()))/'ShortsCutter'; p.mkdir(parents=True,exist_ok=True); return p


def tool(name):
    base=Path(getattr(sys,'_MEIPASS',Path(__file__).parent)); p=base/'tools'/name; return str(p) if p.exists() else name


def fmt(t):
    t=max(0,int(float(t or 0))); return f'{t//60:02d}:{t%60:02d}'


def has_video(path):
    import subprocess
    fp=tool('ffprobe.exe')
    p=subprocess.run([fp,'-v','error','-select_streams','v:0','-show_entries','stream=index','-of','csv=p=0',str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return p.returncode==0 and bool(p.stdout.strip())


class Signals(QObject):
    progress=Signal(int,str); analysis_done=Signal(object,object,object,object); fail=Signal(str); render_done=Signal(str,str); render_fail=Signal(str)


class Window(QWidget):
    def __init__(self):
        super().__init__(); self.setWindowTitle(APP); self.resize(1320,900)
        self.file=''; self.ref_photo=''; self.words_original=[]; self.words=[]; self.cands=[]; self.content_map={}; self.target_scan=None; self.current_candidate=None; self.montage=None; self.caption_blocks=[]; self.imported_caption_blocks=None; self.project_dir=None; self.music_path=''; self.custom_font=''
        self.signals=Signals(); self.signals.progress.connect(self.on_progress); self.signals.analysis_done.connect(self.on_analysis_done); self.signals.fail.connect(self.on_fail); self.signals.render_done.connect(self.on_render_done); self.signals.render_fail.connect(self.on_render_fail)
        self._build_ui()

    def _build_ui(self):
        root=QVBoxLayout(self); hdr=QHBoxLayout(); title=QLabel('SHORTS CUTTER 0.3'); title.setStyleSheet('font-size:28px;font-weight:800'); hdr.addWidget(title); hdr.addStretch(1); hdr.addWidget(QLabel('Одна мысль → целостный Short → базовый монтаж')); root.addLayout(hdr)
        self.tabs=QTabWidget(); root.addWidget(self.tabs,1); self._analysis_tab(); self._transcript_tab(); self._montage_tab(); self._captions_tab(); self.pb=QProgressBar(); root.addWidget(self.pb); self.status=QLabel('Готов'); root.addWidget(self.status)
        self.setStyleSheet('QWidget{background:#16151b;color:#eee;font-size:13px} QLineEdit,QPlainTextEdit,QListWidget,QComboBox,QTableWidget,QSpinBox,QDoubleSpinBox{background:#23212a;border:1px solid #444;padding:5px} QPushButton{background:#6d4aff;border:0;padding:9px 13px;border-radius:6px;font-weight:600} QPushButton:disabled{background:#444;color:#999} QGroupBox{border:1px solid #3b3943;margin-top:8px;padding-top:8px;font-weight:700} QTabBar::tab{background:#211f27;padding:9px 18px;margin-right:2px} QTabBar::tab:selected{background:#6d4aff}')

    def _analysis_tab(self):
        tab=QWidget(); lay=QVBoxLayout(tab); box=QGroupBox('Исходник'); form=QFormLayout(box)
        row=QHBoxLayout(); self.path=QLineEdit(); self.path.setReadOnly(True); b=QPushButton('Выбрать видео / аудио'); b.clicked.connect(self.pick_source); row.addWidget(self.path,1); row.addWidget(b); form.addRow('Файл:',row)
        row=QHBoxLayout(); self.face_path=QLineEdit(); self.face_path.setReadOnly(True); fb=QPushButton('Выбрать мою фотографию'); fb.clicked.connect(self.pick_face); row.addWidget(self.face_path,1); row.addWidget(fb); form.addRow('Главный человек:',row)
        self.only_me=QCheckBox('Только я: искать мои реплики и кадрировать Short вокруг выбранного лица'); self.only_me.setChecked(True); form.addRow('',self.only_me)
        opts=QHBoxLayout(); self.model=QComboBox(); self.model.addItems(['small','medium','base']); opts.addWidget(QLabel('Whisper')); opts.addWidget(self.model); self.key=QLineEdit(); self.key.setEchoMode(QLineEdit.Password); self.key.setPlaceholderText('необязательно — без ключа работает fallback'); opts.addWidget(QLabel('OpenAI API key')); opts.addWidget(self.key,1); form.addRow('',opts); lay.addWidget(box)
        self.analyze_btn=QPushButton('АНАЛИЗИРОВАТЬ ВЫПУСК'); self.analyze_btn.clicked.connect(self.analyze); lay.addWidget(self.analyze_btn)
        mid=QHBoxLayout(); self.cand_list=QListWidget(); self.cand_list.currentItemChanged.connect(self.show_candidate); mid.addWidget(self.cand_list,1); right=QVBoxLayout(); self.cand_detail=QPlainTextEdit(); self.cand_detail.setReadOnly(True); right.addWidget(self.cand_detail,1); self.build_btn=QPushButton('СОБРАТЬ БАЗОВЫЙ МОНТАЖ'); self.build_btn.clicked.connect(self.build_base_montage); self.build_btn.setEnabled(False); right.addWidget(self.build_btn); rw=QWidget(); rw.setLayout(right); mid.addWidget(rw,2); lay.addLayout(mid,1); self.tabs.addTab(tab,'1. Анализ')

    def _transcript_tab(self):
        tab=QWidget(); lay=QVBoxLayout(tab); lab=QLabel('Исправь текст как обычный документ. «Применить» привяжет исправленный текст к таймкодам.'); lab.setWordWrap(True); lay.addWidget(lab); self.transcript=QPlainTextEdit(); lay.addWidget(self.transcript,1); row=QHBoxLayout(); a=QPushButton('Применить правки к таймкодам'); a.clicked.connect(self.apply_transcript); row.addWidget(a); r=QPushButton('Вернуть оригинал Whisper'); r.clicked.connect(self.reset_transcript); row.addWidget(r); row.addStretch(1); lay.addLayout(row); self.tabs.addTab(tab,'2. Транскрипт')

    def _montage_tab(self):
        tab=QWidget(); lay=QVBoxLayout(tab); box=QGroupBox('Базовый монтаж'); form=QFormLayout(box)
        self.edit_preset=QComboBox(); self.edit_preset.addItems(['CALM','STANDARD SHORT','DYNAMIC']); self.edit_preset.setCurrentText('STANDARD SHORT'); form.addRow('Монтажный preset:',self.edit_preset)
        self.pacing=QComboBox(); self.pacing.addItems(['NATURAL','BALANCED','TIGHT']); self.pacing.setCurrentText('BALANCED'); form.addRow('Плотность речи:',self.pacing)
        self.zoom=QComboBox(); self.zoom.addItems(['OFF','LOW','NORMAL','HIGH']); self.zoom.setCurrentText('LOW'); form.addRow('Auto zoom:',self.zoom)
        self.hook=QLineEdit(); self.hook.setPlaceholderText('Пусто = без contextual title'); form.addRow('Hook / контекст:',self.hook)
        self.audio_cleanup=QComboBox(); self.audio_cleanup.addItems(['OFF','LIGHT','NORMAL']); self.audio_cleanup.setCurrentText('LIGHT'); form.addRow('Очистка голоса:',self.audio_cleanup)
        self.color_preset=QComboBox(); self.color_preset.addItems(['Neutral','Clean','Warm','Cool','Contrast','Soft']); form.addRow('Цвет:',self.color_preset)
        cr=QHBoxLayout(); self.exposure=QDoubleSpinBox(); self.exposure.setRange(-0.25,0.25); self.exposure.setSingleStep(0.02); self.contrast=QDoubleSpinBox(); self.contrast.setRange(0.7,1.4); self.contrast.setValue(1.0); self.saturation=QDoubleSpinBox(); self.saturation.setRange(0.5,1.5); self.saturation.setValue(1.0); self.temperature=QDoubleSpinBox(); self.temperature.setRange(-0.25,0.25); self.sharpen=QDoubleSpinBox(); self.sharpen.setRange(0,0.5)
        for n,w in [('Exp',self.exposure),('Contrast',self.contrast),('Sat',self.saturation),('Temp',self.temperature),('Sharp',self.sharpen)]: cr.addWidget(QLabel(n)); cr.addWidget(w)
        form.addRow('Тонкая настройка:',cr); lay.addWidget(box)
        media=QHBoxLayout(); add=QPushButton('Добавить B-roll / перебивку'); add.clicked.connect(self.add_broll); media.addWidget(add); rm=QPushButton('Удалить перебивку'); rm.clicked.connect(self.remove_broll); media.addWidget(rm); mu=QPushButton('Выбрать музыку'); mu.clicked.connect(self.pick_music); media.addWidget(mu); cm=QPushButton('Убрать музыку'); cm.clicked.connect(self.clear_music); media.addWidget(cm); media.addStretch(1); lay.addLayout(media)
        self.broll_list=QListWidget(); self.broll_list.setMaximumHeight(90); lay.addWidget(self.broll_list); self.timeline=QTableWidget(0,4); self.timeline.setHorizontalHeaderLabels(['Тип','Начало','Конец','Деталь']); self.timeline.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch); lay.addWidget(self.timeline,1)
        row=QHBoxLayout(); rb=QPushButton('Пересобрать монтаж'); rb.clicked.connect(self.rebuild_montage); row.addWidget(rb); pv=QPushButton('PREVIEW'); pv.clicked.connect(self.preview); row.addWidget(pv); ef=QPushButton('EXPORT FINISHED'); ef.clicked.connect(lambda:self.export_short(False)); row.addWidget(ef); ec=QPushButton('EXPORT CLEAN'); ec.clicked.connect(lambda:self.export_short(True)); row.addWidget(ec); ea=QPushButton('EXPORT ASSETS'); ea.clicked.connect(self.export_assets); row.addWidget(ea); lay.addLayout(row); self.tabs.addTab(tab,'3. Монтаж')

    def _captions_tab(self):
        tab=QWidget(); lay=QVBoxLayout(tab); form=QFormLayout(); self.caption_mode=QComboBox(); self.caption_mode.addItems(['PHRASES','WORD BY WORD','SENTENCES']); form.addRow('Режим:',self.caption_mode)
        fr=QHBoxLayout(); self.font_path=QLineEdit(); self.font_path.setReadOnly(True); f=QPushButton('Загрузить TTF / OTF'); f.clicked.connect(self.pick_font); fr.addWidget(self.font_path,1); fr.addWidget(f); form.addRow('Шрифт:',fr)
        self.font_size=QSpinBox(); self.font_size.setRange(28,120); self.font_size.setValue(64); form.addRow('Размер:',self.font_size)
        colors=QHBoxLayout(); self.text_color=QLineEdit('#FFFFFF'); self.highlight_color=QLineEdit('#C9B7FF'); self.stroke_color=QLineEdit('#000000'); colors.addWidget(QLabel('Text')); colors.addWidget(self.text_color); colors.addWidget(QLabel('Highlight')); colors.addWidget(self.highlight_color); colors.addWidget(QLabel('Stroke')); colors.addWidget(self.stroke_color); form.addRow('Цвета:',colors)
        self.stroke=QDoubleSpinBox(); self.stroke.setRange(0,8); self.stroke.setValue(3); form.addRow('Контур:',self.stroke); self.sub_anim=QComboBox(); self.sub_anim.addItems(['NONE','POP','FADE','SCALE','WORD HIGHLIGHT']); self.sub_anim.setCurrentText('WORD HIGHLIGHT'); form.addRow('Анимация:',self.sub_anim); self.sub_bg=QCheckBox('Подложка под текст'); form.addRow('',self.sub_bg); self.margin_v=QSpinBox(); self.margin_v.setRange(80,700); self.margin_v.setValue(250); form.addRow('Safe zone снизу:',self.margin_v); lay.addLayout(form)
        row=QHBoxLayout(); imp=QPushButton('Импорт SRT / VTT / ASS / TXT'); imp.clicked.connect(self.import_subtitles); row.addWidget(imp); gen=QPushButton('Сгенерировать из транскрипции'); gen.clicked.connect(self.regenerate_captions); row.addWidget(gen); row.addStretch(1); lay.addLayout(row)
        self.caption_table=QTableWidget(0,3); self.caption_table.setHorizontalHeaderLabels(['Начало','Конец','Текст']); self.caption_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch); lay.addWidget(self.caption_table,1); self.tabs.addTab(tab,'4. Субтитры')

    def pick_source(self):
        f,_=QFileDialog.getOpenFileName(self,'Выберите выпуск','', 'Media (*.mp4 *.mkv *.mov *.avi *.webm *.mp3 *.wav *.m4a *.flac *.ogg);;Все файлы (*.*)')
        if f: self.file=f; self.path.setText(f); self.target_scan=None; self.project_dir=None

    def pick_face(self):
        f,_=QFileDialog.getOpenFileName(self,'Выберите фотографию себя','', 'Images (*.jpg *.jpeg *.png *.webp *.bmp);;Все файлы (*.*)')
        if f: self.ref_photo=f; self.face_path.setText(f); self.target_scan=None

    def analyze(self):
        if not self.file: QMessageBox.warning(self,'Нет файла','Сначала выбери выпуск.'); return
        if self.only_me.isChecked() and has_video(self.file) and not self.ref_photo: QMessageBox.warning(self,'Нужна фотография','Для режима «Только я» выбери фотографию лица.'); return
        s={'file':self.file,'ref':self.ref_photo,'only_me':self.only_me.isChecked(),'model':self.model.currentText(),'key':self.key.text().strip()}; self.analyze_btn.setEnabled(False); self.build_btn.setEnabled(False); self.cand_list.clear(); self.cand_detail.clear(); self.pb.setValue(1); threading.Thread(target=self._analysis_worker,args=(s,),daemon=True).start()

    def _analysis_worker(self,s):
        try:
            result=transcribe_media(s['file'],s['model'],appdata()/'models',lambda p,msg:self.signals.progress.emit(int(p*45),msg)); words=result['words']; scan=None; target=False
            if s['only_me'] and s['ref'] and has_video(s['file']):
                self.signals.progress.emit(48,'Ищу тебя в видео…'); from face_focus import TargetFaceAnalyzer, mark_target_words; scan=TargetFaceAnalyzer().scan(s['file'],s['ref'],sample_fps=2.5,progress=lambda p:self.signals.progress.emit(48+int(p*20),f'Поиск лица: {int(p*100)}%'))
                if scan.get('coverage',0)<0.06: raise RuntimeError('По выбранной фотографии я почти не нахожу тебя в видео. Нужна более чёткая фотография лица.')
                words=mark_target_words(words,scan); target=True
            self.signals.progress.emit(70,'Строю карту выпуска…'); cmap=build_content_map(words,s['key'],target) if s['key'] else {'summary':'Локальный режим','themes':[],'chapters':[]}; self.signals.progress.emit(82,'Ищу целостные Shorts…'); cands,cmap=find_candidates(words,s['key'],cmap,maxn=15,target_mode=target); self.signals.progress.emit(100,'Готово'); self.signals.analysis_done.emit(words,cands,scan,cmap)
        except Exception as e: self._log_exception('analysis',e); self.signals.fail.emit(str(e))

    def on_analysis_done(self,words,cands,scan,cmap):
        self.words_original=[dict(w) for w in words]; self.words=[dict(w) for w in words]; self.cands=cands; self.target_scan=scan; self.content_map=cmap; self.transcript.setPlainText(' '.join(w.get('text','') for w in words)); self.cand_list.clear()
        for c in cands:
            status='CTX' if c.get('status')=='PASS_WITH_CONTEXT_TITLE' else 'PASS'; me=f" Я:{float(c.get('target_ratio',1))*100:.0f}%" if scan else ''; it=QListWidgetItem(f"{c.get('score',0):>3}/100 {status}{me}  {fmt(c.get('start'))}–{fmt(c.get('end'))}  {c.get('title','')}"); it.setData(Qt.UserRole,c); self.cand_list.addItem(it)
        self.analyze_btn.setEnabled(True); self.build_btn.setEnabled(bool(cands)); self.status.setText(f'Найдено кандидатов: {len(cands)}');
        if self.cand_list.count(): self.cand_list.setCurrentRow(0)

    def show_candidate(self,item,*_):
        if not item:return
        c=item.data(Qt.UserRole); self.current_candidate=c; scores=c.get('scores') or {}; lines=[c.get('title',''),'',f"{fmt(c.get('start'))} → {fmt(c.get('end'))}",f"Overall: {c.get('score',0)}/100",f"Status: {c.get('status','PASS')}",f"Context dependency: {c.get('context_dependency_score',0)}/100",'', 'CENTRAL IDEA:',c.get('central_idea',''),'', 'Что должен унести зритель:',c.get('viewer_takeaway',''),'', 'Почему выбран:',c.get('reason','')]
        if scores: lines += ['', 'Scores: '+', '.join(f'{k}={v}' for k,v in scores.items())]
        lines += ['', 'Текст:',c.get('text','')]; self.cand_detail.setPlainText('\n'.join(lines)); titles=c.get('suggested_titles') or []; self.hook.setText(titles[0] if c.get('status')=='PASS_WITH_CONTEXT_TITLE' and titles else '')

    def apply_transcript(self):
        if not self.words:return
        self.words=align_plain_text_to_words(self.transcript.toPlainText(),self.words); QMessageBox.information(self,'Готово','Правки текста применены к таймкодам.');
        if self.montage:self.regenerate_captions()

    def reset_transcript(self):
        if self.words_original:self.words=[dict(w) for w in self.words_original]; self.transcript.setPlainText(' '.join(w.get('text','') for w in self.words))

    def _apply_transcript_silent(self):
        if self.words and self.transcript.toPlainText().strip(): self.words=align_plain_text_to_words(self.transcript.toPlainText(),self.words)

    def build_base_montage(self):
        if not self.current_candidate: QMessageBox.warning(self,'Нет Short','Выбери кандидат.'); return
        self._apply_transcript_silent(); self.project_dir=create_project(appdata()/'projects',self.file,self.current_candidate); self.rebuild_montage(); save_json(self.project_dir/'transcript_original.json',self.words_original); save_json(self.project_dir/'transcript_edited.json',self.words); save_json(self.project_dir/'candidate.json',self.current_candidate); save_json(self.project_dir/'content_map.json',self.content_map); self.tabs.setCurrentIndex(2); QMessageBox.information(self,'Монтаж собран','Базовый монтаж создан. Его можно править перед экспортом.')

    def rebuild_montage(self):
        if not self.current_candidate:return
        self._apply_transcript_silent(); self.montage=build_montage(self.current_candidate,self.words,self.edit_preset.currentText(),self.zoom.currentText()); self.montage['pacing']=self.pacing.currentText(); self.montage['cuts']=build_keep_segments(self.words,float(self.current_candidate['start']),float(self.current_candidate['end']),self.pacing.currentText()); self.montage['output_duration']=self.montage['cuts'][-1]['out_end'] if self.montage['cuts'] else float(self.current_candidate['end'])-float(self.current_candidate['start']); self.montage['zooms']=build_zoom_plan(self.montage['output_duration'],self.zoom.currentText()); self.montage['hook_text']=self.hook.text().strip(); self.montage['hook_duration']=3.5 if self.montage['hook_text'] else 0; self.montage['audio_cleanup']=self.audio_cleanup.currentText(); self._apply_color(); self.montage['music_path']=self.music_path; self.montage['music_volume']=0.10; self.montage['broll']=[self.broll_list.item(i).data(Qt.UserRole) for i in range(self.broll_list.count())]
        if self.imported_caption_blocks is not None: self.caption_blocks=[dict(b) for b in self.imported_caption_blocks]; self._fill_caption_table(self.caption_blocks)
        else: self.regenerate_captions()
        self.update_timeline(); self.save_project_state(); self.status.setText(f"Монтаж: {self.montage['output_duration']:.1f} сек")

    def _apply_color(self):
        if not self.montage:return
        base=default_color(self.color_preset.currentText()); self.montage['color']={'exposure':float(self.exposure.value()) if abs(self.exposure.value())>.001 else base['exposure'],'contrast':float(self.contrast.value()) if abs(self.contrast.value()-1)>.001 else base['contrast'],'saturation':float(self.saturation.value()) if abs(self.saturation.value()-1)>.001 else base['saturation'],'temperature':float(self.temperature.value()) if abs(self.temperature.value())>.001 else base['temperature'],'sharpen':float(self.sharpen.value()) if self.sharpen.value()>0 else base['sharpen']}; self.montage['color_preset']=self.color_preset.currentText()

    def regenerate_captions(self):
        if not self.montage:return
        remapped=remap_words_to_output(self.words,self.montage['cuts']); self.caption_blocks=segment_words(remapped,0,self.montage['output_duration'],self.caption_mode.currentText(),4); self.imported_caption_blocks=None; self._fill_caption_table(self.caption_blocks)

    def _fill_caption_table(self,blocks):
        self.caption_table.setRowCount(len(blocks))
        for r,b in enumerate(blocks): self.caption_table.setItem(r,0,QTableWidgetItem(f"{float(b['start']):.3f}")); self.caption_table.setItem(r,1,QTableWidgetItem(f"{float(b['end']):.3f}")); self.caption_table.setItem(r,2,QTableWidgetItem(str(b.get('text',''))))

    def _read_caption_table(self):
        out=[]
        for r in range(self.caption_table.rowCount()):
            try:
                st=float(self.caption_table.item(r,0).text()); en=float(self.caption_table.item(r,1).text()); tx=self.caption_table.item(r,2).text().strip()
                if tx and en>st:out.append({'start':st,'end':en,'text':tx,'words':[]})
            except Exception:pass
        return out

    def pick_font(self):
        f,_=QFileDialog.getOpenFileName(self,'Выбери шрифт','', 'Fonts (*.ttf *.otf)')
        if f:self.custom_font=f; self.font_path.setText(f)

    def import_subtitles(self):
        f,_=QFileDialog.getOpenFileName(self,'Импорт субтитров','', 'Subtitles (*.srt *.vtt *.ass *.ssa *.txt)')
        if not f:return
        ext=Path(f).suffix.lower()
        if ext in ('.srt','.vtt'):blocks=parse_srt_vtt(f)
        elif ext in ('.ass','.ssa'):blocks=parse_ass(f)
        else:
            self.transcript.setPlainText(Path(f).read_text(encoding='utf-8-sig',errors='replace')); self.apply_transcript(); self.regenerate_captions(); return
        if not blocks: QMessageBox.warning(self,'Не удалось','Не удалось прочитать таймкоды из файла.'); return
        self.imported_caption_blocks=blocks; self.caption_blocks=blocks; self._fill_caption_table(blocks)

    def add_broll(self):
        if not self.montage: QMessageBox.warning(self,'Сначала монтаж','Сначала собери базовый монтаж.'); return
        f,_=QFileDialog.getOpenFileName(self,'B-roll / перебивка','', 'Media (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.mov *.mkv *.webm)')
        if not f:return
        dur=float(self.montage.get('output_duration',30)); st,ok=QInputDialog.getDouble(self,'Начало перебивки','Секунда внутри Short:',0,0,max(0,dur-.2),2)
        if not ok:return
        en,ok=QInputDialog.getDouble(self,'Конец перебивки','Секунда внутри Short:',min(dur,st+2.5),st+.1,dur,2)
        if not ok:return
        mode,ok=QInputDialog.getItem(self,'Режим','Как показать:',['FULLSCREEN','PICTURE IN PICTURE'],0,False)
        if not ok:return
        data={'path':f,'start':st,'end':en,'mode':mode}; it=QListWidgetItem(f"{st:.1f}–{en:.1f} {mode}  {Path(f).name}"); it.setData(Qt.UserRole,data); self.broll_list.addItem(it); self.rebuild_montage()

    def remove_broll(self):
        r=self.broll_list.currentRow();
        if r>=0:self.broll_list.takeItem(r); self.rebuild_montage()

    def pick_music(self):
        f,_=QFileDialog.getOpenFileName(self,'Фоновая музыка','', 'Audio (*.mp3 *.wav *.m4a *.flac *.aac *.ogg)')
        if f:self.music_path=f; self.status.setText('Музыка: '+Path(f).name); self.rebuild_montage()

    def clear_music(self): self.music_path=''; self.rebuild_montage()

    def update_timeline(self):
        if not self.montage:return
        rows=[]
        for c in self.montage.get('cuts',[]):rows.append(('VIDEO',c['out_start'],c['out_end'],f"source {c['src_start']:.2f}–{c['src_end']:.2f}"))
        for z in self.montage.get('zooms',[]):rows.append(('ZOOM',z['start'],z['end'],f"{z['scale']*100:.0f}%"))
        if self.montage.get('hook_text'):rows.append(('HOOK',0,self.montage.get('hook_duration',3.5),self.montage['hook_text']))
        for b in self.montage.get('broll',[]):rows.append(('B-ROLL',b['start'],b['end'],Path(b['path']).name))
        rows.sort(key=lambda x:(x[1],x[0])); self.timeline.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,v in enumerate((row[0],f'{row[1]:.2f}',f'{row[2]:.2f}',row[3])):self.timeline.setItem(r,c,QTableWidgetItem(str(v)))

    def _subtitle_style(self):
        font_path=self.custom_font
        if self.project_dir and font_path:
            try:font_path=copy_asset(font_path,self.project_dir,'fonts')
            except Exception:pass
        return {'font_path':font_path,'font_family':font_family_from_file(font_path) if font_path else 'Arial','font_size':self.font_size.value(),'text_color':self.text_color.text().strip(),'highlight_color':self.highlight_color.text().strip(),'stroke_color':self.stroke_color.text().strip(),'stroke_width':self.stroke.value(),'shadow':1,'background':self.sub_bg.isChecked(),'background_color':'#000000','margin_v':self.margin_v.value(),'alignment':2,'animation':self.sub_anim.currentText()}

    def _prepare_ass(self):
        if not self.project_dir:return None,None
        blocks=self._read_caption_table(); self.caption_blocks=blocks; ass=self.project_dir/'captions.ass'; write_ass(ass,blocks,self._subtitle_style(),self.hook.text().strip(),3.5,1080,1920); return str(ass),str(self.project_dir/'assets'/'fonts')

    def _base_crop(self):
        if self.only_me.isChecked() and self.target_scan and self.current_candidate:
            from face_focus import estimate_crop
            return estimate_crop(self.target_scan,float(self.current_candidate['start']),float(self.current_candidate['end']))
        return None

    def preview(self):
        if not self.montage: QMessageBox.warning(self,'Нет монтажа','Сначала собери базовый монтаж.'); return
        self.rebuild_montage(); ass,fonts=self._prepare_ass(); self._start_render(self.project_dir/'proxy'/'preview.mp4',False,True,ass,fonts,'preview')

    def export_short(self,clean=False):
        if not self.montage: QMessageBox.warning(self,'Нет монтажа','Сначала собери базовый монтаж.'); return
        self.rebuild_montage(); out,_=QFileDialog.getSaveFileName(self,'Сохранить Short','short_clean.mp4' if clean else 'short_finished.mp4','MP4 (*.mp4)')
        if not out:return
        if not out.lower().endswith('.mp4'):out+='.mp4'
        ass,fonts=(None,None) if clean else self._prepare_ass(); self._start_render(Path(out),clean,False,ass,fonts,'clean' if clean else 'finished')

    def _start_render(self,out,clean,preview,ass,fonts,kind):
        self.pb.setValue(3); self.status.setText('Рендер…'); montage=json.loads(json.dumps(self.montage,ensure_ascii=False)); montage['hook_text']=self.hook.text().strip(); montage['audio_cleanup']=self.audio_cleanup.currentText(); self._apply_color(); montage['color']=dict(self.montage['color']); montage['music_path']=self.music_path if not clean else ''; montage['broll']=[self.broll_list.item(i).data(Qt.UserRole) for i in range(self.broll_list.count())] if not clean else []; base=self._base_crop(); log=appdata()/'logs'/f'last_{kind}_ffmpeg.log'
        def work():
            try:render(tool('ffmpeg.exe'),tool('ffprobe.exe'),self.file,str(out),montage,ass,fonts,base,clean,preview,str(log)); self.signals.render_done.emit(str(out),kind)
            except Exception as e:self._log_exception(kind,e); self.signals.render_fail.emit(str(e))
        threading.Thread(target=work,daemon=True).start()

    def on_render_done(self,out,kind):
        self.pb.setValue(100); self.status.setText('Готово: '+out)
        if kind=='preview':QDesktopServices.openUrl(QUrl.fromLocalFile(out))
        else:QMessageBox.information(self,'Готово','Файл сохранён:\n'+out)

    def on_render_fail(self,e):self.status.setText('Ошибка рендера'); QMessageBox.critical(self,'Ошибка рендера',e)

    def export_assets(self):
        if not self.montage or not self.project_dir:return
        folder=QFileDialog.getExistingDirectory(self,'Куда экспортировать assets?')
        if not folder:return
        folder=Path(folder); blocks=self._read_caption_table(); write_srt(folder/'short.srt',blocks); write_ass(folder/'short.ass',blocks,self._subtitle_style(),self.hook.text().strip(),3.5); (folder/'transcript.txt').write_text(self.transcript.toPlainText(),encoding='utf-8'); (folder/'hook.txt').write_text(self.hook.text().strip(),encoding='utf-8'); save_json(folder/'edit.json',self.montage); QMessageBox.information(self,'Готово','Экспортированы SRT, ASS, transcript.txt, hook.txt и edit.json.')

    def save_project_state(self):
        if not self.project_dir or not self.montage:return
        self.montage['hook_text']=self.hook.text().strip(); self.montage['caption_style']=self._subtitle_style(); self.montage['caption_blocks']=self._read_caption_table(); self.montage['broll']=[self.broll_list.item(i).data(Qt.UserRole) for i in range(self.broll_list.count())]; self.montage['music_path']=self.music_path; save_json(self.project_dir/'project.json',{'version':VERSION,'source_video':self.file,'reference_photo':self.ref_photo,'candidate':self.current_candidate,'montage':self.montage}); save_json(self.project_dir/'transcript_edited.json',self.words); save_json(self.project_dir/'cuts.json',self.montage.get('cuts',[])); save_json(self.project_dir/'zooms.json',self.montage.get('zooms',[])); save_json(self.project_dir/'captions.json',self.montage.get('caption_blocks',[])); save_json(self.project_dir/'overlays.json',self.montage.get('broll',[])); save_json(self.project_dir/'color.json',self.montage.get('color',{})); save_json(self.project_dir/'audio.json',{'cleanup':self.audio_cleanup.currentText(),'music':self.music_path})

    def on_progress(self,v,s):self.pb.setValue(v); self.status.setText(s)
    def on_fail(self,e):self.analyze_btn.setEnabled(True); self.status.setText('Ошибка'); QMessageBox.critical(self,'Ошибка',e)
    def _log_exception(self,stage,e):
        p=appdata()/'logs'/f'{stage}_python.log'; p.parent.mkdir(exist_ok=True); p.write_text(traceback.format_exc()+'\n'+str(e),encoding='utf-8',errors='replace')


def main():
    app=QApplication(sys.argv); w=Window(); w.show(); return app.exec()

if __name__=='__main__':
    raise SystemExit(main())
