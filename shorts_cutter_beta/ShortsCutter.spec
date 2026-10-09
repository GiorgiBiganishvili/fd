from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs
from pathlib import Path
root=Path(SPECPATH)
hidden=[]; datas=[]; binaries=[]
for pkg in ['faster_whisper','ctranslate2','av','tokenizers','huggingface_hub','openai','PySide6','cv2','numpy']:
    try: hidden += collect_submodules(pkg)
    except Exception: pass
for pkg in ['faster_whisper','cv2']:
    try: datas += collect_data_files(pkg)
    except Exception: pass
for pkg in ['ctranslate2','av','cv2']:
    try: binaries += collect_dynamic_libs(pkg)
    except Exception: pass
for name in ['ffmpeg.exe','ffprobe.exe']:
    p=root/'tools'/name
    if p.exists(): binaries.append((str(p),'tools'))
for name in ['face_detection_yunet_2023mar_int8.onnx','face_recognition_sface_2021dec_int8.onnx']:
    p=root/'models'/name
    if p.exists(): datas.append((str(p),'models'))
a=Analysis([str(root/'main.py')],pathex=[str(root)],binaries=binaries,datas=datas,hiddenimports=hidden,hookspath=[],runtime_hooks=[],excludes=[],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='ShortsCutter',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='ShortsCutter')
