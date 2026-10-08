import sys, os, json, subprocess, tempfile, threading, math
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QTextEdit, QComboBox, QMessageBox, QProgressBar

APP='Shorts Cutter Beta'

def appdata():
    p=Path(os.getenv('LOCALAPPDATA', Path.home()))/'ShortsCutter'; p.mkdir(parents=True,exist_ok=True); return p

def tool(name):
    base=Path(getattr(sys,'_MEIPASS',Path(__file__).parent)); p=base/'tools'/name
    return str(p) if p.exists() else name

def fmt(t):
    t=max(0,int(t)); return f'{t//60:02d}:{t%60:02d}'

def heuristic_candidates(words, maxn=12):
    if not words: return []
    out=[]; step=55.0; dur=55.0; end=words[-1]['end']; s=0.0; i=1
    while s<end and len(out)<maxn:
        e=min(end,s+dur); seg=[w for w in words if w['start']>=s and w['end']<=e]
        text=' '.join(w['text'] for w in seg).strip()
        if len(text)>80:
            score=min(88,55+len(text)//45)
            out.append({'id':i,'start':s,'end':e,'score':score,'title':text[:70]+'…','reason':'Автоматический кандидат по плотности речи.','text':text})
            i+=1
        s+=step
    return out

def llm_candidates(words, api_key, maxn=15):
    if not api_key: return heuristic_candidates(words,maxn)
    try:
        from openai import OpenAI
        client=OpenAI(api_key=api_key)
        transcript=' '.join(f"[{w['id']}] {w['text']}" for w in words)
        if len(transcript)>90000: transcript=transcript[:90000]
        prompt='''Ты отбираешь сильные Shorts из русскоязычного психологического подкаста. Верни только JSON-массив до 15 объектов. Для каждого: start_word_id, end_word_id, score 0-100, title, reason. Ищи самостоятельную законченную мысль, сильный hook, противоречие, уязвимость, инсайт. Не начинай и не заканчивай посреди мысли. Длина примерно 20-90 секунд. Не дублируй идеи. Транскрипт ниже:\n'''+transcript
        r=client.responses.create(model='gpt-5-mini',input=prompt)
        raw=r.output_text.strip()
        a=raw.find('['); b=raw.rfind(']')
        data=json.loads(raw[a:b+1])
        byid={w['id']:w for w in words}; out=[]
        for i,x in enumerate(data[:maxn],1):
            sw=int(x['start_word_id']); ew=int(x['end_word_id'])
            if sw not in byid or ew not in byid or ew<=sw: continue
            seg=[w for w in words if sw<=w['id']<=ew]
            out.append({'id':i,'start':byid[sw]['start'],'end':byid[ew]['end'],'score':int(x.get('score',70)),'title':str(x.get('title','Кандидат')),'reason':str(x.get('reason','')),'text':' '.join(w['text'] for w in seg)})
        return out or heuristic_candidates(words,maxn)
    except Exception:
        return heuristic_candidates(words,maxn)

class Signals(QObject):
    progress=Signal(int,str); done=Signal(object,object); fail=Signal(str)

class Window(QWidget):
    def __init__(self):
        super().__init__(); self.setWindowTitle(APP); self.resize(1000,720)
        self.file=''; self.words=[]; self.cands=[]; self.sig=Signals(); self.sig.progress.connect(self.onprog); self.sig.done.connect(self.ondone); self.sig.fail.connect(self.onfail)
        root=QVBoxLayout(self)
        title=QLabel('SHORTS CUTTER'); title.setStyleSheet('font-size:28px;font-weight:700'); root.addWidget(title)
        row=QHBoxLayout(); self.path=QLineEdit(); self.path.setReadOnly(True); b=QPushButton('Выбрать видео / аудио'); b.clicked.connect(self.pick); row.addWidget(self.path,1); row.addWidget(b); root.addLayout(row)
        row2=QHBoxLayout(); row2.addWidget(QLabel('Whisper:')); self.model=QComboBox(); self.model.addItems(['small','medium','base']); row2.addWidget(self.model); row2.addWidget(QLabel('OpenAI API key:')); self.key=QLineEdit(); self.key.setEchoMode(QLineEdit.Password); row2.addWidget(self.key,1); root.addLayout(row2)
        self.run=QPushButton('Анализировать'); self.run.clicked.connect(self.analyze); root.addWidget(self.run)
        self.pb=QProgressBar(); root.addWidget(self.pb); self.status=QLabel('Готов'); root.addWidget(self.status)
        mid=QHBoxLayout(); self.list=QListWidget(); self.list.currentItemChanged.connect(self.show_candidate); mid.addWidget(self.list,1); self.text=QTextEdit(); self.text.setReadOnly(True); mid.addWidget(self.text,2); root.addLayout(mid,1)
        erow=QHBoxLayout(); self.export=QPushButton('Экспортировать выбранный 9:16'); self.export.clicked.connect(self.export_clip); erow.addWidget(self.export); root.addLayout(erow)
        self.setStyleSheet('QWidget{background:#16151b;color:#eee;font-size:14px} QLineEdit,QTextEdit,QListWidget,QComboBox{background:#23212a;border:1px solid #444;padding:6px} QPushButton{background:#6d4aff;border:0;padding:10px 14px;border-radius:6px} QPushButton:disabled{background:#444}')
    def pick(self):
        f,_=QFileDialog.getOpenFileName(self,'Выберите выпуск','','Media (*.mp4 *.mkv *.mov *.avi *.webm *.mp3 *.wav *.m4a *.flac *.ogg);;Все файлы (*.*)')
        if f: self.file=f; self.path.setText(f)
    def analyze(self):
        if not self.file: QMessageBox.warning(self,'Нет файла','Сначала выбери файл.'); return
        self.run.setEnabled(False); self.list.clear(); self.text.clear(); self.pb.setValue(1)
        threading.Thread(target=self.worker,daemon=True).start()
    def worker(self):
        try:
            self.sig.progress.emit(5,'Загрузка Whisper…')
            from faster_whisper import WhisperModel
            cache=appdata()/'models'; cache.mkdir(exist_ok=True)
            model_name=self.model.currentText(); m=None
            try: m=WhisperModel(model_name,device='cuda',compute_type='float16',download_root=str(cache))
            except Exception: m=WhisperModel(model_name,device='cpu',compute_type='int8',download_root=str(cache))
            self.sig.progress.emit(15,'Транскрипция…')
            try:
                segs,info=m.transcribe(self.file,language='ru',word_timestamps=True,vad_filter=True)
                words=[]; idx=0
                for seg in segs:
                    for w in (seg.words or []):
                        words.append({'id':idx,'text':w.word.strip(),'start':float(w.start),'end':float(w.end)}); idx+=1
            except Exception:
                m=WhisperModel(model_name,device='cpu',compute_type='int8',download_root=str(cache))
                segs,info=m.transcribe(self.file,language='ru',word_timestamps=True,vad_filter=True)
                words=[]; idx=0
                for seg in segs:
                    for w in (seg.words or []): words.append({'id':idx,'text':w.word.strip(),'start':float(w.start),'end':float(w.end)}); idx+=1
            self.sig.progress.emit(75,'Поиск сильных фрагментов…')
            cands=llm_candidates(words,self.key.text().strip())
            job=appdata()/'last_job'; job.mkdir(exist_ok=True)
            (job/'transcript.json').write_text(json.dumps(words,ensure_ascii=False,indent=2),encoding='utf-8')
            (job/'candidates.json').write_text(json.dumps(cands,ensure_ascii=False,indent=2),encoding='utf-8')
            self.sig.progress.emit(100,'Готово')
            self.sig.done.emit(words,cands)
        except Exception as e: self.sig.fail.emit(str(e))
    def onprog(self,v,s): self.pb.setValue(v); self.status.setText(s)
    def ondone(self,words,cands):
        self.words=words; self.cands=cands; self.run.setEnabled(True)
        for c in sorted(cands,key=lambda x:x['score'],reverse=True):
            it=QListWidgetItem(f"{c['score']:>3}/100  {fmt(c['start'])}–{fmt(c['end'])}  {c['title']}"); it.setData(Qt.UserRole,c); self.list.addItem(it)
        if self.list.count(): self.list.setCurrentRow(0)
    def onfail(self,e): self.run.setEnabled(True); self.status.setText('Ошибка'); QMessageBox.critical(self,'Ошибка',e)
    def show_candidate(self,item,*_):
        if not item: return
        c=item.data(Qt.UserRole); self.text.setPlainText(f"{c['title']}\n\n{fmt(c['start'])} → {fmt(c['end'])}\nОценка: {c['score']}/100\n\nПочему выбран:\n{c['reason']}\n\nТекст:\n{c['text']}")
    def export_clip(self):
        item=self.list.currentItem()
        if not item: return
        c=item.data(Qt.UserRole); out,_=QFileDialog.getSaveFileName(self,'Сохранить Short','short.mp4','MP4 (*.mp4)')
        if not out: return
        self.status.setText('Экспорт…'); self.export.setEnabled(False)
        def work():
            try:
                ff=tool('ffmpeg.exe'); dur=max(0.1,c['end']-c['start'])
                vf="crop='if(gt(iw/ih,9/16),ih*9/16,iw)':'if(gt(iw/ih,9/16),ih,iw*16/9)',scale=1080:1920:flags=lanczos,hqdn3d=1.2:1.2:6:6,unsharp=5:5:0.35:5:5:0"
                cmd=[ff,'-y','-ss',str(c['start']),'-i',self.file,'-t',str(dur),'-vf',vf,'-c:v','libx264','-preset','medium','-crf','18','-c:a','aac','-b:a','192k',out]
                subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                self.sig.progress.emit(100,'Экспорт готов: '+out)
            except Exception as e: self.sig.fail.emit('Экспорт: '+str(e))
            finally: self.export.setEnabled(True)
        threading.Thread(target=work,daemon=True).start()

def main():
    app=QApplication(sys.argv); w=Window(); w.show(); return app.exec()
if __name__=='__main__': raise SystemExit(main())
