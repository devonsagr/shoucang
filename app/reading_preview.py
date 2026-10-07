"""Local extractive reading aid, excluded from processing, export and AI prompts."""
from collections import Counter
from functools import lru_cache
import re

def plain(text):
    text=re.sub(r'!\[[^\]]*\]\([^)]*\)','',text or '')
    text=re.sub(r'\[([^\]]+)\]\([^)]*\)',r'\1',text)
    return re.sub(r'(?m)^\s*[#>*-]+\s*','',text).strip()

def tokens(text):
    words=re.findall(r'[A-Za-z][A-Za-z0-9_+-]{2,}',text.lower())
    for word in re.findall(r'[\u4e00-\u9fff]+',text):words.extend(word[i:i+2] for i in range(len(word)-1))
    return [t for t in words if t not in {'这个','那个','我们','你们','一个','可以','就是','the','and','for','with','this','that','have'}]

@lru_cache(maxsize=256)
def extract(text):
    if len(text)<120:return None
    sentences=[s.strip() for s in re.split(r'(?<=[。！？!?])\s*|\n+|(?<=[.])\s+(?=[A-Z])',text) if 15<=len(s.strip())<=400][:400]
    if len(sentences)<3:return None
    frequency=Counter(t for s in sentences for t in set(tokens(s)))
    ranked=sorted(range(len(sentences)),key=lambda i:sum(min(frequency[t],8) for t in tokens(sentences[i]))/max(len(tokens(sentences[i])),1)**.5,reverse=True)
    selected=[]
    for i in ranked:
        if any(sentences[i]==sentences[j] for j in selected):continue
        if sum(len(sentences[j]) for j in selected)+len(sentences[i])>380:continue
        selected.append(i)
        if len(selected)==2:break
    return '\n'.join(sentences[i] for i in sorted(selected)) or None

def make(item):
    content=item.get('content',{})
    if content.get('media_kind')=='video_reference':return None
    if content.get('segments') and item.get('platform') in ('bilibili','youtube','douyin'):
        text='\n'.join(s['text'] for s in content['segments'])[:24000];source='字幕摘录'
    else:text=plain(item.get('body',''))[:24000];source='原文摘录'
    result=extract(text)
    return {'text':result,'method':'extractive','source':source,'reading_only':True,'model_used':False} if result else None

def excerpt(item):
    preview=make(item)
    if preview:return preview['text'].replace('\n',' ')[:240]
    content=item.get('content',{})
    if content.get('media_kind')=='video_reference':return '原视频链接与封面已保留，尚未转写'
    text=plain(item.get('body',''))
    if not text and content.get('gallery_count'):text=f"图片帖 · {content['gallery_count']} 张图片"
    if not text and content.get('segments'):text=content['segments'][0]['text']
    return text[:240]
