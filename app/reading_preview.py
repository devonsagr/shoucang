"""Local extractive reading aid, excluded from processing, export and AI prompts."""
from functools import lru_cache
import re

def plain(text):
    text=re.sub(r'!\[[^\]]*\]\([^)]*\)','',text or '')
    text=re.sub(r'\[([^\]]+)\]\([^)]*\)',r'\1',text)
    return re.sub(r'(?m)^\s*[#>*-]+\s*','',text).strip()

FRAGMENT=re.compile(r'^(?:也将|同时也|此外|其中|与此同时|该作|该游戏|这款|其(?:中|将|在)|而且|以及|also\b|it\b|they\b)',re.I)
NOISE=re.compile(r'^(?:点赞|收藏|关注|评论|举报|分享|返回顶部|展开全文|加载更多|登录后查看|相关阅读|相关推荐)(?:[\s\d:：·|]*)$')

def opening(block):
    if len(block)<=360:return block
    sentences=re.findall(r'.+?[。！？!?](?:\s|$)|.+$',block)
    chosen=[]
    for sentence in sentences:
        if sum(map(len,chosen))+len(sentence)>360:break
        chosen.append(sentence)
    return ''.join(chosen).strip() or None

@lru_cache(maxsize=1024)
def extract(text):
    if len(text)<120:return None
    # Keep the first substantive paragraph and its adjacent context together.
    # Repeated dates/platform names must not replace the subject with two scattered lines.
    blocks=[b.strip() for b in re.split(r'\n\s*\n',text) if b.strip()]
    if len(blocks)==1:blocks=[b.strip() for b in text.splitlines() if b.strip()]
    blocks=[b for b in blocks if len(b)>=12 and not NOISE.fullmatch(b)]
    first=next((i for i,b in enumerate(blocks) if not FRAGMENT.search(b) and opening(b)),None)
    if first is None:return None
    selected=[opening(blocks[first])]
    for block in blocks[first+1:first+3]:
        piece=opening(block)
        if not piece or piece in selected or sum(map(len,selected))+len(piece)>480:break
        selected.append(piece)
    return '\n'.join(selected)

def make(item):
    content=item.get('content',{})
    if content.get('media_kind')=='video_reference':return None
    if content.get('segments') and item.get('platform') in ('bilibili','youtube','douyin'):
        text='\n'.join(s['text'] for s in content['segments'])[:24000];source='字幕导读'
    else:text=plain(item.get('body',''))[:24000];source='原文导读'
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
