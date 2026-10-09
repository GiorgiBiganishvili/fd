import subprocess
from pathlib import Path


def _flags():
    return getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def run(cmd, log_path=None):
    p=subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', creationflags=_flags())
    if p.returncode != 0:
        if log_path:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True); Path(log_path).write_text(p.stderr, encoding='utf-8', errors='replace')
        raise RuntimeError((p.stderr[-2400:].strip() or f'FFmpeg error {p.returncode}') + (f'\n\nЛог: {log_path}' if log_path else ''))
    return p


def has_audio(ffprobe, path):
    p=subprocess.run([ffprobe,'-v','error','-select_streams','a:0','-show_entries','stream=index','-of','csv=p=0',str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', creationflags=_flags())
    return p.returncode==0 and bool(p.stdout.strip())


def probe_size(ffprobe,path):
    p=run([ffprobe,'-v','error','-select_streams','v:0','-show_entries','stream=width,height','-of','csv=p=0:s=x',str(path)]); w,h=p.stdout.strip().split('x'); return int(w),int(h)


def filter_path(path):
    s=str(Path(path).resolve()).replace('\\','/'); return s.replace(':','\\:').replace("'","\\'")


def _crop_for_zoom(base_crop, scale):
    x=float(base_crop['x']); y=float(base_crop['y']); w=float(base_crop['w']); h=float(base_crop['h']); scale=max(1.0,float(scale or 1.0)); nw=max(2.0,w/scale); nh=max(2.0,h/scale); cx=x+w/2; cy=y+h/2; nx=cx-nw/2; ny=cy-nh/2
    def even(v): return max(2,int(v)//2*2)
    return even(nx),even(ny),even(nw),even(nh)


def _center_crop(src_w,src_h):
    h=float(src_h); w=h*9/16
    if w>src_w: w=float(src_w); h=w*16/9
    x=(src_w-w)/2; y=(src_h-h)/2
    def even(v): return max(2,int(v)//2*2)
    return {'x':even(x),'y':even(y),'w':even(w),'h':even(h)}


def _color_filter(settings):
    if not settings: return ''
    exposure=float(settings.get('exposure',0)); contrast=float(settings.get('contrast',1)); saturation=float(settings.get('saturation',1)); temp=float(settings.get('temperature',0)); sharpen=float(settings.get('sharpen',0)); chain=[]; brightness=max(-0.25,min(0.25,exposure)); chain.append(f'eq=brightness={brightness:.3f}:contrast={contrast:.3f}:saturation={saturation:.3f}')
    if abs(temp)>0.005:
        r=max(-0.25,min(0.25,temp)); chain.append(f'colorbalance=rs={r:.3f}:bs={-r:.3f}')
    if sharpen>0.01:
        amt=max(0.05,min(0.5,sharpen)); chain.append(f'unsharp=5:5:{amt:.3f}:5:5:0')
    return ','.join(chain)


def _audio_filter(mode):
    mode=str(mode or 'OFF').upper()
    if mode=='OFF': return 'anull'
    if mode=='NORMAL': return 'highpass=f=80,afftdn=nf=-28,acompressor=threshold=0.10:ratio=3:attack=12:release=180,alimiter=limit=0.95'
    return 'highpass=f=70,afftdn=nf=-32,acompressor=threshold=0.14:ratio=2.2:attack=15:release=220,alimiter=limit=0.97'


def build_command(ffmpeg, ffprobe, source, out, montage, ass_path=None, fonts_dir=None, base_crop=None, clean=False, preview=False, log_path=None):
    source=str(source); out=str(out); src_w,src_h=probe_size(ffprobe,source); audio_present=has_audio(ffprobe,source); base_crop=base_crop or _center_crop(src_w,src_h)
    cuts=montage.get('cuts') or [{'src_start':montage['clip_start'],'src_end':montage['clip_end'],'out_start':0.0,'out_end':montage['clip_end']-montage['clip_start']}]; zooms=montage.get('zooms') or [{'start':0.0,'end':montage.get('output_duration',1.0),'scale':1.0}]
    pieces=[]
    for c in cuts:
        co0=float(c.get('out_start',0)); co1=float(c.get('out_end',co0+float(c['src_end'])-float(c['src_start'])))
        for z in zooms:
            a=max(co0,float(z['start'])); b=min(co1,float(z['end']))
            if b-a<=0.025: continue
            src_a=float(c['src_start'])+(a-co0); pieces.append({'src_start':src_a,'src_end':src_a+(b-a),'scale':float(z.get('scale',1.0))})
    if not pieces: pieces=[{'src_start':float(montage['clip_start']),'src_end':float(montage['clip_end']),'scale':1.0}]
    cmd=[ffmpeg,'-hide_banner','-y','-i',source]; extra_inputs=[]; music_index=None; music_path=montage.get('music_path') if not clean else ''
    if music_path:
        music_index=1+len(extra_inputs); extra_inputs.append(('music',str(music_path))); cmd += ['-stream_loop','-1','-i',str(music_path)]
    broll_items=[] if clean else (montage.get('broll') or [])
    for item in broll_items:
        p=str(item.get('path',''))
        if not p or not Path(p).exists(): continue
        ext=Path(p).suffix.lower(); cmd += (['-loop','1','-i',p] if ext in ('.png','.jpg','.jpeg','.webp','.bmp') else ['-stream_loop','-1','-i',p]); extra_inputs.append(('overlay',p))
    indexed_broll=[]; idx_cursor=1+(1 if music_index is not None else 0)
    for item in ([] if clean else (montage.get('broll') or [])):
        p=str(item.get('path',''))
        if not p or not Path(p).exists(): continue
        it=dict(item); it['_input_index']=idx_cursor; indexed_broll.append(it); idx_cursor+=1
    filters=[]; concat_labels=[]; out_w,out_h=(540,960) if preview else (1080,1920)
    for i,p in enumerate(pieces):
        x,y,w,h=_crop_for_zoom(base_crop,p['scale']); filters.append(f"[0:v]trim=start={p['src_start']:.4f}:end={p['src_end']:.4f},setpts=PTS-STARTPTS,crop={w}:{h}:{x}:{y},scale={out_w}:{out_h}:flags=lanczos,setsar=1,format=yuv420p[v{i}]"); concat_labels.append(f'[v{i}]')
        if audio_present:
            filters.append(f"[0:a]atrim=start={p['src_start']:.4f}:end={p['src_end']:.4f},asetpts=PTS-STARTPTS[a{i}]"); concat_labels.append(f'[a{i}]')
    n=len(pieces); filters.append(''.join(concat_labels)+(f'concat=n={n}:v=1:a=1[vcat][acat]' if audio_present else f'concat=n={n}:v=1:a=0[vcat]'))
    vcur='vcat'; color=_color_filter(montage.get('color'))
    if color: filters.append(f'[{vcur}]{color}[vcolor]'); vcur='vcolor'
    for j,it in enumerate(indexed_broll):
        idx=int(it['_input_index']); st=float(it.get('start',0)); en=float(it.get('end',st+2.5)); mode=str(it.get('mode','FULLSCREEN')).upper()
        if mode=='PICTURE IN PICTURE':
            ow=int(out_w*0.42); ox=int(out_w*0.54); oy=int(out_h*0.08); filters.append(f'[{idx}:v]setpts=PTS-STARTPTS+{st:.3f}/TB,scale={ow}:-2:flags=lanczos,setsar=1[ov{j}]'); filters.append(f'[{vcur}][ov{j}]overlay={ox}:{oy}:shortest=1:enable=\'between(t,{st:.3f},{en:.3f})\'[vb{j}]')
        else:
            filters.append(f'[{idx}:v]setpts=PTS-STARTPTS+{st:.3f}/TB,scale={out_w}:{out_h}:force_original_aspect_ratio=increase:flags=lanczos,crop={out_w}:{out_h},setsar=1[ov{j}]'); filters.append(f'[{vcur}][ov{j}]overlay=0:0:shortest=1:enable=\'between(t,{st:.3f},{en:.3f})\'[vb{j}]')
        vcur=f'vb{j}'
    if ass_path and not clean:
        ap=filter_path(ass_path); fd=filter_path(fonts_dir) if fonts_dir else ''; sub=f"subtitles=filename='{ap}'"+(f":fontsdir='{fd}'" if fd else ''); filters.append(f'[{vcur}]{sub}[vsub]'); vcur='vsub'
    acur=None
    if audio_present:
        filters.append(f"[acat]{_audio_filter(montage.get('audio_cleanup'))}[aclean]"); acur='aclean'
        if music_index is not None:
            dur=float(montage.get('output_duration') or sum(p['src_end']-p['src_start'] for p in pieces)); vol=max(0,min(1,float(montage.get('music_volume',0.10)))); fade_out=max(0,dur-1.2); filters.append(f'[{music_index}:a]atrim=start=0:end={dur:.3f},asetpts=PTS-STARTPTS,volume={vol:.3f},afade=t=in:st=0:d=0.8,afade=t=out:st={fade_out:.3f}:d=1.0[music]'); filters.append(f'[music][{acur}]sidechaincompress=threshold=0.035:ratio=8:attack=20:release=280[duck]'); filters.append(f'[{acur}][duck]amix=inputs=2:duration=first:dropout_transition=2[aout]'); acur='aout'
    cmd += ['-filter_complex',';'.join(filters),'-map',f'[{vcur}]']
    if acur: cmd += ['-map',f'[{acur}]']
    cmd += ['-c:v','libx264','-preset','veryfast' if preview else 'medium','-crf','27' if preview else '18','-pix_fmt','yuv420p']
    if acur: cmd += ['-c:a','aac','-b:a','192k']
    cmd += ['-movflags','+faststart',out]; return cmd


def render(ffmpeg, ffprobe, source, out, montage, ass_path=None, fonts_dir=None, base_crop=None, clean=False, preview=False, log_path=None):
    cmd=build_command(ffmpeg,ffprobe,source,out,montage,ass_path,fonts_dir,base_crop,clean,preview,log_path); Path(out).parent.mkdir(parents=True,exist_ok=True)
    if log_path: Path(str(log_path)+'.cmd.txt').write_text(' '.join(cmd),encoding='utf-8')
    run(cmd,log_path=log_path); p=Path(out)
    if not p.exists() or p.stat().st_size<1024: raise RuntimeError('FFmpeg завершился, но итоговый файл не создан корректно.')
    return str(out)
