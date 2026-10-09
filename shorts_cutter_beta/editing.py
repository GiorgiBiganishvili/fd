from typing import List, Dict


def build_keep_segments(words: List[Dict], start: float, end: float, pacing='BALANCED'):
    seg=[w for w in words if w.get('include',True) and float(w['end'])>=start and float(w['start'])<=end]
    if not seg: return _annotate_output_time([{'src_start':start,'src_end':end}])
    pacing=str(pacing or 'BALANCED').upper()
    if pacing=='NATURAL': threshold,keep_gap=2.2,0.95
    elif pacing=='TIGHT': threshold,keep_gap=0.9,0.34
    else: threshold,keep_gap=1.35,0.56
    cuts=[]; prev=max(start,float(seg[0]['start']))
    for a,b in zip(seg,seg[1:]):
        gap=float(b['start'])-float(a['end'])
        if gap>=threshold:
            left=max(prev,float(a['end'])+keep_gap*0.5); right=min(end,float(b['start'])-keep_gap*0.5)
            if left-prev>0.10: cuts.append({'src_start':prev,'src_end':left})
            prev=max(prev,right)
    if end-prev>0.10: cuts.append({'src_start':prev,'src_end':end})
    if not cuts: cuts=[{'src_start':start,'src_end':end}]
    return _annotate_output_time(cuts)


def _annotate_output_time(segments):
    out=[]; t=0.0
    for s in segments:
        dur=max(0.0,float(s['src_end'])-float(s['src_start']))
        if dur<=0.02: continue
        x=dict(s); x['out_start']=t; x['out_end']=t+dur; x['duration']=dur; out.append(x); t+=dur
    return out


def build_zoom_plan(duration,intensity='LOW'):
    intensity=str(intensity or 'LOW').upper()
    if intensity=='OFF': return [{'start':0.0,'end':duration,'scale':1.0}]
    if intensity=='HIGH': interval,levels=4.2,[1.0,1.12,1.0,1.18]
    elif intensity=='NORMAL': interval,levels=5.5,[1.0,1.10,1.0,1.15]
    else: interval,levels=7.0,[1.0,1.08,1.0,1.12]
    out=[]; t=0.0; i=0
    while t<duration-1e-6:
        e=min(duration,t+interval); out.append({'start':t,'end':e,'scale':levels[i%len(levels)]}); t=e; i+=1
    return out or [{'start':0.0,'end':duration,'scale':1.0}]


def default_color(preset='Neutral'):
    p=str(preset or 'Neutral').lower(); base={'exposure':0.0,'contrast':1.0,'saturation':1.0,'temperature':0.0,'sharpen':0.0}
    if p=='clean': base.update({'exposure':0.03,'contrast':1.05,'saturation':1.03,'sharpen':0.18})
    elif p=='warm': base.update({'temperature':0.08,'contrast':1.03,'saturation':1.04})
    elif p=='cool': base.update({'temperature':-0.07,'contrast':1.03,'saturation':0.98})
    elif p=='contrast': base.update({'contrast':1.12,'saturation':1.02,'sharpen':0.12})
    elif p=='soft': base.update({'contrast':0.95,'saturation':0.98,'sharpen':0.0})
    return base


def build_montage(candidate,words,preset='STANDARD SHORT',zoom='LOW'):
    preset=str(preset or 'STANDARD SHORT').upper()
    if preset=='CALM': pacing='NATURAL'; zoom_int='LOW'
    elif preset=='DYNAMIC': pacing='TIGHT'; zoom_int='HIGH'
    else: pacing='BALANCED'; zoom_int=zoom or 'NORMAL'
    start=float(candidate['start']); end=float(candidate['end']); cuts=build_keep_segments(words,start,end,pacing); duration=cuts[-1]['out_end'] if cuts else end-start; zooms=build_zoom_plan(duration,zoom_int)
    title=''
    if candidate.get('status')=='PASS_WITH_CONTEXT_TITLE':
        titles=candidate.get('suggested_titles') or []; title=titles[0] if titles else candidate.get('title','')
    return {'candidate':candidate,'clip_start':start,'clip_end':end,'output_duration':duration,'pacing':pacing,'cuts':cuts,'zooms':zooms,'hook_text':title,'hook_duration':3.5 if title else 0.0,'subtitle_mode':'PHRASES','subtitle_style':{'font_path':'','font_family':'Arial','font_size':64,'text_color':'#FFFFFF','highlight_color':'#C9B7FF','stroke_color':'#000000','stroke_width':3.0,'shadow':1.0,'background':False,'background_color':'#000000','margin_v':250,'alignment':2,'animation':'WORD HIGHLIGHT'},'audio_cleanup':'LIGHT','color_preset':'Neutral','color':default_color('Neutral'),'music_path':'','music_volume':0.10,'broll':[]}


def remap_words_to_output(words,cuts):
    out=[]
    for w in words:
        if not w.get('include',True): continue
        ws=float(w['start']); we=float(w['end'])
        for c in cuts:
            cs=float(c['src_start']); ce=float(c['src_end'])
            if we<cs or ws>ce: continue
            a=max(ws,cs); b=min(we,ce)
            if b<=a: continue
            nw=dict(w); nw['source_start']=ws; nw['source_end']=we; nw['start']=float(c.get('out_start',0.0))+(a-cs); nw['end']=float(c.get('out_start',0.0))+(b-cs); out.append(nw); break
    for i,w in enumerate(out): w['id']=i
    return out
