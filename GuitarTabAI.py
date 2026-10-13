import sys,os,math,subprocess,tempfile,json
from pathlib import Path
import numpy as np, soundfile as sf
from PySide6.QtCore import Qt,QThread,Signal,QUrl
from PySide6.QtMultimedia import QMediaPlayer,QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import *
NAMES=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']; OPEN=[40,45,50,55,59,64]
def note(m): return f'{NAMES[m%12]}{m//12-1}'
def ffmpeg():
 b=getattr(sys,'_MEIPASS',None)
 if b and (Path(b)/'ffmpeg.exe').exists(): return str(Path(b)/'ffmpeg.exe')
 return 'ffmpeg.exe'
def extract(v):
 d=Path(tempfile.gettempdir())/'GuitarTabAI'; d.mkdir(exist_ok=True); w=d/'audio.wav'
 p=subprocess.run([ffmpeg(),'-y','-i',str(v),'-vn','-ac','1','-ar','44100','-c:a','pcm_s16le',str(w)],capture_output=True,text=True,creationflags=(subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0))
 if p.returncode: raise RuntimeError(p.stderr[-1500:])
 return w
def transcribe(w):
 y,sr=sf.read(str(w),dtype='float32'); y=np.mean(y,axis=1) if getattr(y,'ndim',1)==2 else y
 if len(y)<4096:return []
 y=y/(np.max(np.abs(y))+1e-9); frame=4096; hop=1024; win=np.hanning(frame); fr=np.fft.rfftfreq(frame,1/sr); mask=(fr>=70)&(fr<=1400); ids=np.flatnonzero(mask); raw=[]
 for s in range(0,len(y)-frame,hop):
  x=y[s:s+frame]
  if np.sqrt(np.mean(x*x))<.01: raw.append(None); continue
  sp=np.abs(np.fft.rfft(x*win)); k=ids[np.argmax(sp[mask])]; hz=fr[k]; m=round(69+12*math.log2(hz/440)); raw.append(m)
 out=[]; cur=None; st=0
 for i,m in enumerate(raw+[None]):
  if m!=cur:
   if cur is not None and (i-st)*hop/sr>.06:
    c=[]
    for j,o in enumerate(OPEN):
     f=cur-o
     if 0<=f<=24:c.append((6-j,f))
    string,fret=min(c,key=lambda x:x[1]) if c else (None,None); out.append({'start':st*hop/sr,'end':i*hop/sr,'midi':cur,'pitch':note(cur),'string':string,'fret':fret})
   cur=m; st=i
 return out
def tab(ns,cols=90):
 if not ns:return ''
 end=max(n['end'] for n in ns) or 1; rows={s:['-']*cols for s in range(1,7)}; names={1:'e',2:'B',3:'G',4:'D',5:'A',6:'E'}
 for n in ns:
  if not n['string']:continue
  t=str(n['fret']); x=min(cols-len(t),int(n['start']/end*(cols-1)))
  for i,ch in enumerate(t): rows[n['string']][x+i]=ch
 return '\n'.join(f"{names[s]}|{''.join(rows[s])}|" for s in range(1,7))
class Worker(QThread):
 done=Signal(object); fail=Signal(str)
 def __init__(self,v):super().__init__();self.v=v
 def run(self):
  try:self.done.emit(transcribe(extract(self.v)))
  except Exception as e:self.fail.emit(str(e))
class Win(QMainWindow):
 def __init__(self):
  super().__init__();self.setWindowTitle('Guitar Tab AI');self.resize(1150,780);self.v=None;self.ns=[];self.dur=0
  self.p=QMediaPlayer();self.a=QAudioOutput();self.p.setAudioOutput(self.a);vid=QVideoWidget();self.p.setVideoOutput(vid)
  self.txt=QPlainTextEdit();self.txt.setReadOnly(True);self.tbl=QTableWidget(0,5);self.tbl.setHorizontalHeaderLabels(['start','pitch','MIDI','string','fret']);self.tbl.itemChanged.connect(self.edit)
  tabs=QTabWidget();tabs.addTab(self.txt,'TAB');tabs.addTab(self.tbl,'Ноты');sp=QSplitter(Qt.Vertical);sp.addWidget(vid);sp.addWidget(tabs)
  self.pr=QProgressBar();self.pr.hide();self.sl=QSlider(Qt.Horizontal);self.sl.setRange(0,1000);self.sl.sliderMoved.connect(lambda x:self.p.setPosition(int(x/1000*self.dur)) if self.dur else None);self.p.durationChanged.connect(lambda d:setattr(self,'dur',d));self.p.positionChanged.connect(lambda x:self.sl.setValue(int(x/self.dur*1000)) if self.dur and not self.sl.isSliderDown() else None)
  bar=QHBoxLayout()
  for t,f in [('Загрузить видео',self.open),('Анализировать',self.analyze),('Play / Pause',self.play),('Сохранить проект',self.save),('Открыть проект',self.load),('Экспорт TAB',self.export)]: b=QPushButton(t);b.clicked.connect(f);bar.addWidget(b)
  top=QWidget();top.setLayout(bar);lay=QVBoxLayout();lay.addWidget(top);lay.addWidget(self.pr);lay.addWidget(sp);lay.addWidget(self.sl);w=QWidget();w.setLayout(lay);self.setCentralWidget(w)
 def open(self):
  f,_=QFileDialog.getOpenFileName(self,'Видео',filter='Video (*.mp4 *.mov *.mkv *.avi *.webm)')
  if f:self.v=Path(f);self.p.setSource(QUrl.fromLocalFile(f))
 def play(self): self.p.pause() if self.p.playbackState()==QMediaPlayer.PlayingState else self.p.play()
 def analyze(self):
  if not self.v:return
  self.pr.setRange(0,0);self.pr.show();self.w=Worker(self.v);self.w.done.connect(self.done);self.w.fail.connect(self.fail);self.w.start()
 def done(self,x):self.ns=x;self.pr.hide();self.refresh()
 def fail(self,e):self.pr.hide();QMessageBox.critical(self,'Ошибка',e)
 def refresh(self):
  self.txt.setPlainText(tab(self.ns));self.tbl.blockSignals(True);self.tbl.setRowCount(len(self.ns))
  for r,n in enumerate(self.ns):
   for c,k in enumerate(['start','pitch','midi','string','fret']):self.tbl.setItem(r,c,QTableWidgetItem('' if n[k] is None else str(n[k])))
  self.tbl.blockSignals(False)
 def edit(self,it):
  r=it.row()
  try:self.ns[r]['start']=float(self.tbl.item(r,0).text());self.ns[r]['pitch']=self.tbl.item(r,1).text();self.ns[r]['midi']=int(self.tbl.item(r,2).text());self.ns[r]['string']=int(self.tbl.item(r,3).text());self.ns[r]['fret']=int(self.tbl.item(r,4).text());self.txt.setPlainText(tab(self.ns))
  except:pass
 def save(self):
  if not self.v:return
  f,_=QFileDialog.getSaveFileName(self,'Сохранить',filter='Project (*.gtabproject)')
  if f:Path(f).write_text(json.dumps({'video':str(self.v),'notes':self.ns},ensure_ascii=False),encoding='utf8')
 def load(self):
  f,_=QFileDialog.getOpenFileName(self,'Открыть',filter='Project (*.gtabproject)')
  if f:
   d=json.loads(Path(f).read_text(encoding='utf8'));self.v=Path(d['video']);self.ns=d['notes'];self.p.setSource(QUrl.fromLocalFile(str(self.v)));self.refresh()
 def export(self):
  if not self.ns:return
  f,_=QFileDialog.getSaveFileName(self,'Экспорт',filter='Text (*.txt)')
  if f:Path(f).write_text(tab(self.ns),encoding='utf8')
if __name__=='__main__':
 app=QApplication(sys.argv);w=Win();w.show();sys.exit(app.exec())
