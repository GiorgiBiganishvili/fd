import json
import shutil
from pathlib import Path
from datetime import datetime


def slug(s):
    s=''.join(ch if ch.isalnum() or ch in '-_ ' else '_' for ch in str(s))
    s='_'.join(s.strip().split())
    return s[:70] or 'Short_Project'


def create_project(root, source_path, candidate=None):
    root=Path(root); root.mkdir(parents=True,exist_ok=True)
    stem=slug(Path(source_path).stem); ts=datetime.now().strftime('%Y%m%d_%H%M%S'); p=root/f'{stem}_{ts}'
    (p/'assets'/'fonts').mkdir(parents=True,exist_ok=True); (p/'assets'/'broll').mkdir(parents=True,exist_ok=True); (p/'assets'/'music').mkdir(parents=True,exist_ok=True); (p/'proxy').mkdir(exist_ok=True); (p/'exports').mkdir(exist_ok=True)
    save_json(p/'project.json',{'version':'0.3.0-beta','source_video':str(source_path),'candidate':candidate or {},'created_at':datetime.now().isoformat(timespec='seconds')})
    return p


def save_json(path,obj):
    Path(path).parent.mkdir(parents=True,exist_ok=True); Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')


def load_json(path,default=None):
    try: return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception: return default


def copy_asset(src,project_dir,subfolder):
    if not src: return ''
    src=Path(src); dest=Path(project_dir)/'assets'/subfolder/src.name; dest.parent.mkdir(parents=True,exist_ok=True)
    if src.resolve()!=dest.resolve(): shutil.copy2(src,dest)
    return str(dest)
