"""Compare original source content, independent of notes, AI output and capture paths."""
import re
from urllib.parse import urlparse,urlencode,parse_qsl,urlunparse
from . import store

def fingerprint(value):
    content=value.get('content',{})
    body=content.get('original_body') or value.get('body','')
    saved={m.get('path'):m.get('source_url','') for m in content.get('media',[]) if m.get('path')}
    images=[]
    def image(match):
        source=saved.get(match[2],match[2]);p=urlparse(source)
        query=[(k,v) for k,v in parse_qsl(p.query) if k.lower() not in ('token','sig','signature','expires','policy','auth_key','ts','key-pair-id')]
        images.append(urlunparse((p.scheme,p.netloc,p.path,'',urlencode(sorted(query)),'')))
        return ''
    text=re.sub(r'!\[([^\]]*)\]\(([^\s)]+)\)',image,body)
    segments=[{'start':s['start'],'end':s['end'],'text':s['text']} for s in content.get('segments',[])]
    return store.digest(store.dumps({'title':value.get('title',''),'text':re.sub(r'\s+',' ',text).strip(),'images':images,'segments':segments}))
