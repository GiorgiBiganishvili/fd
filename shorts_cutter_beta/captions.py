import re
from pathlib import Path

PUNCT_END = ('.', '!', '?', '…')


def _clean(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def segment_words(words, start, end, mode='PHRASES', max_words=4):
    seg = [w for w in words if w.get('include', True) and float(w['end']) >= start and float(w['start']) <= end]
    if not seg:
        return []
    mode = str(mode or 'PHRASES').upper()
    if mode == 'WORD BY WORD':
        return [{'start': max(start,float(w['start']))-start, 'end': min(end,float(w['end']))-start,
                 'text': _clean(w.get('text')), 'words':[w]} for w in seg if _clean(w.get('text'))]
    blocks, cur = [], []
    last_end = None
    for w in seg:
        txt = _clean(w.get('text'))
        if not txt:
            continue
        gap = 0.0 if last_end is None else max(0.0, float(w['start']) - last_end)
        should_break = False
        if cur:
            if mode == 'SENTENCES':
                should_break = gap > 0.85 or str(cur[-1].get('text','')).rstrip().endswith(PUNCT_END)
            else:
                should_break = (len(cur) >= max_words or gap > 0.58 or (len(cur) >= 2 and str(cur[-1].get('text','')).rstrip().endswith(PUNCT_END)))
        if should_break:
            blocks.append(_block(cur, start, end)); cur = []
        cur.append(w); last_end = float(w['end'])
    if cur:
        blocks.append(_block(cur, start, end))
    merged = []
    for b in blocks:
        if merged and len(b['words']) == 1 and len(merged[-1]['words']) < max_words and b['start'] - merged[-1]['end'] < 0.45:
            prev = merged.pop(); merged.append(_block(prev['words'] + b['words'], start, end))
        else:
            merged.append(b)
    return merged


def _block(words, clip_start, clip_end):
    return {'start': max(0.0, float(words[0]['start']) - clip_start), 'end': max(0.02, min(clip_end, float(words[-1]['end'])) - clip_start), 'text': ' '.join(_clean(w.get('text')) for w in words).strip(), 'words': words}


def _ass_time(t):
    t=max(0.0,float(t)); h=int(t//3600); t-=h*3600; m=int(t//60); t-=m*60; s=int(t); cs=int(round((t-s)*100))
    if cs>=100: s+=1; cs-=100
    return f'{h}:{m:02d}:{s:02d}.{cs:02d}'


def _srt_time(t):
    t=max(0.0,float(t)); h=int(t//3600); t-=h*3600; m=int(t//60); t-=m*60; s=int(t); ms=int(round((t-s)*1000))
    if ms>=1000: s+=1; ms-=1000
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def _ass_color(hex_color, alpha=0):
    c=(hex_color or '#FFFFFF').lstrip('#')
    if len(c)!=6: c='FFFFFF'
    r,g,b=c[:2],c[2:4],c[4:6]; a=max(0,min(255,int(alpha)))
    return f'&H{a:02X}{b}{g}{r}'


def _escape_ass_text(text):
    return str(text).replace('\\','\\\\').replace('{','\\{').replace('}','\\}').replace('\n','\\N')


def font_family_from_file(font_path):
    if not font_path: return 'Arial'
    try:
        from fontTools.ttLib import TTFont
        f=TTFont(str(font_path),lazy=True)
        for nid in (16,1):
            for n in f['name'].names:
                if n.nameID==nid:
                    try: return n.toUnicode().strip()
                    except Exception: pass
    except Exception: pass
    return Path(font_path).stem


def write_ass(path, blocks, style=None, hook_text='', hook_duration=3.5, width=1080, height=1920):
    style=dict(style or {}); font=style.get('font_family') or font_family_from_file(style.get('font_path')); size=int(style.get('font_size',64))
    primary=_ass_color(style.get('text_color','#FFFFFF')); secondary=_ass_color(style.get('highlight_color','#C9B7FF')); outline=_ass_color(style.get('stroke_color','#000000'))
    back=_ass_color(style.get('background_color','#000000'),160 if style.get('background',False) else 255); outline_w=float(style.get('stroke_width',3.0)); shadow=float(style.get('shadow',1.0)); margin_v=int(style.get('margin_v',250)); align=int(style.get('alignment',2)); anim=str(style.get('animation','NONE')).upper()
    header=f'''[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nScaledBorderAndShadow: yes\nWrapStyle: 2\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Caption,{font},{size},{primary},{secondary},{outline},{back},-1,0,0,0,100,100,0,0,{3 if style.get('background',False) else 1},{outline_w},{shadow},{align},70,70,{margin_v},1\nStyle: Hook,{font},{int(size*0.82)},{primary},{secondary},{outline},{back},-1,0,0,0,100,100,0,0,1,{outline_w},{shadow},8,80,80,180,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'''
    lines=[header]
    if hook_text:
        lines.append(f'Dialogue: 2,{_ass_time(0)},{_ass_time(hook_duration)},Hook,,0,0,0,,{{\\fad(120,180)}}{_escape_ass_text(hook_text)}\n')
    for b in blocks:
        txt=_escape_ass_text(b.get('text','')); tag=''
        if anim=='FADE': tag='{\\fad(100,100)}'
        elif anim=='SCALE': tag='{\\fscx92\\fscy92\\t(0,160,\\fscx100\\fscy100)}'
        elif anim=='POP': tag='{\\fscx88\\fscy88\\t(0,120,\\fscx104\\fscy104)\\t(120,220,\\fscx100\\fscy100)}'
        elif anim=='WORD HIGHLIGHT' and b.get('words'):
            parts=[]
            for w in b['words']:
                dur=max(1,int(round((float(w['end'])-float(w['start']))*100))); parts.append(f'{{\\kf{dur}}}{_escape_ass_text(w.get("text",""))}')
            txt=' '.join(parts)
        lines.append(f"Dialogue: 1,{_ass_time(b['start'])},{_ass_time(b['end'])},Caption,,0,0,0,,{tag}{txt}\n")
    Path(path).write_text(''.join(lines),encoding='utf-8-sig'); return str(path)


def write_srt(path, blocks):
    out=[]
    for i,b in enumerate(blocks,1): out += [str(i),f"{_srt_time(b['start'])} --> {_srt_time(b['end'])}",b.get('text',''),'']
    Path(path).write_text('\n'.join(out),encoding='utf-8'); return str(path)


def parse_srt_vtt(path):
    text=Path(path).read_text(encoding='utf-8-sig',errors='replace').replace('\r\n','\n')
    pat=re.compile(r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})[^\n]*\n(.*?)(?=\n\s*\n|\Z)',re.S); blocks=[]
    for m in pat.finditer(text):
        def ts(h,mi,s,ms): return int(h)*3600+int(mi)*60+int(s)+int(ms)/1000.0
        blocks.append({'start':ts(*m.group(1,2,3,4)),'end':ts(*m.group(5,6,7,8)),'text':_clean(re.sub('<[^>]+>','',m.group(9))),'words':[]})
    return blocks


def parse_ass(path):
    blocks=[]
    for line in Path(path).read_text(encoding='utf-8-sig',errors='replace').splitlines():
        if not line.startswith('Dialogue:'): continue
        parts=line.split(',',9)
        if len(parts)<10: continue
        def pt(s): h,m,sec=s.split(':'); return int(h)*3600+int(m)*60+float(sec)
        txt=re.sub(r'\{[^}]*\}','',parts[9]).replace('\\N',' '); blocks.append({'start':pt(parts[1]),'end':pt(parts[2]),'text':_clean(txt),'words':[]})
    return blocks


def align_plain_text_to_words(text, words):
    tokens=re.findall(r'\S+',str(text or ''))
    if not tokens or not words: return words
    base=[dict(w) for w in words]
    if len(tokens)==len(base):
        for w,t in zip(base,tokens): w['text']=t
        return base
    start=float(base[0]['start']); end=float(base[-1]['end']); total=max(0.01,end-start); new=[]
    for i,tok in enumerate(tokens):
        a=start+total*i/len(tokens); b=start+total*(i+1)/len(tokens); new.append({'id':i,'text':tok,'original_text':tok,'start':a,'end':b,'include':True})
    return new
