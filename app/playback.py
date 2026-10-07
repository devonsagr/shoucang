"""Ephemeral, range-bounded playback relay; no video files or account mutation."""
from __future__ import annotations
import math
import re
import threading
import time
from urllib.parse import urlsplit
import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from . import adapters, store, video_pipeline

MEDIA_DOMAINS = ('douyinvod.com', 'douyin.com', 'iesdouyin.com', 'amemv.com')
CACHE = {}
STREAMS = {}
LOCK = threading.Lock()
CHUNK_LIMIT = 8*1024*1024
SESSION_TTL = 7200

def fallback(reason):
    return {'mode':'embed','source':'抖音原站嵌入播放器',
            'notice':'本次未取得可在页内定位的播放地址；保留原站播放。可正常登录后重试，未绕过平台限制。',
            'reason':reason}

def safe_media_url(url):
    p = urlsplit(url)
    host = (p.hostname or '').lower()
    if (p.scheme != 'https' or p.username or p.password or p.port not in (None,443)
            or not any(host==d or host.endswith('.'+d) for d in MEDIA_DOMAINS)):
        raise ValueError('平台未返回受支持的 HTTPS 播放地址')
    adapters.public_url(url)
    return url

def resolve_address(url):
    """Read response headers and redirects, never consume a media response body."""
    with httpx.Client(timeout=15, follow_redirects=False) as client:
        for _ in range(5):
            safe_media_url(url)
            with client.stream('GET', url, headers={'Range':'bytes=0-0','User-Agent':'Mozilla/5.0',
                    'Referer':'https://www.douyin.com/'}) as response:
                if response.status_code in (401,403,429):
                    raise ValueError('平台拒绝播放或限流，已停止')
                if response.is_redirect:
                    url = str(response.url.join(response.headers['location']))
                    continue
                if response.status_code != 206:
                    raise ValueError('平台未提供可定位的分段视频响应')
                if response.headers.get('content-type','').split(';')[0].lower() not in ('video/mp4','application/octet-stream'):
                    raise ValueError('平台返回的资源不是可用 MP4 视频')
                return url
    raise ValueError('播放地址重定向过多，已停止')

def douyin(item,refresh=False):
    if item['platform']!='douyin': raise ValueError('此播放地址入口仅用于抖音视频')
    canonical=adapters.canonical(item['url'])
    with LOCK:
        cached=CACHE.get(canonical)
        if cached and cached[0]>time.monotonic():
            previous=cached[1]
            if previous['mode']=='embed': return previous  # Short cooldown after a refusal/failure.
            token=previous['url'].rsplit('/',1)[-1]
            entry=STREAMS.get(token)
            if (not refresh and entry and entry['material_id']==item['id']
                    and entry['expires']>time.monotonic()): return previous
        if refresh:
            for token in list(STREAMS):
                if STREAMS[token]['material_id']==item['id']: STREAMS.pop(token,None)
        try:
            info, source=video_pipeline.douyin_metadata(canonical)
            if str(info.get('aweme_id',''))!=canonical.rsplit('/',1)[-1]:
                raise ValueError('平台返回了不同视频的信息，已停止')
            video=info.get('video') or {}
            duration=float(video.get('duration',0))/1000
            if not math.isfinite(duration) or duration<=0:
                raise ValueError('平台未返回有效视频时长')
            addresses=[]
            for key in ('play_addr_h264','play_addr'):
                if key=='play_addr' and video.get('is_h265'): continue
                addresses.extend((video.get(key) or {}).get('url_list') or [])
            for variant in video.get('bit_rate') or []:
                if not variant.get('is_h265') and not variant.get('is_bytevc1'):
                    addresses.extend((variant.get('play_addr') or {}).get('url_list') or [])
            addresses=list(dict.fromkeys(addresses))
            # One validated address; no retry storm or watermark/download URL rewrites.
            address=next((u for u in addresses if isinstance(u,str) and u.startswith('https://')
                          and any((urlsplit(u).hostname or '').endswith('.'+d) or urlsplit(u).hostname==d for d in MEDIA_DOMAINS)),None)
            if not address: raise ValueError('平台没有返回可在线播放的视频地址')
            address=resolve_address(address)
            token=store.uid()
            STREAMS[token]={'material_id':item['id'],'url':address,'expires':time.monotonic()+SESSION_TTL}
            if len(STREAMS)>100:
                old=next(k for k in STREAMS if k!=token);STREAMS.pop(old)
            result={'mode':'stream','url':f'/api/materials/{item["id"]}/playback-stream/{token}',
                    'duration':duration,'width':video.get('width'),
                    'height':video.get('height'),'source':source,'notice':'平台视频在线播放，不保存视频文件；加载后可按字幕定位。'}
            ttl=SESSION_TTL
        except Exception as exc:
            # Signed URLs and credentials must never appear in errors, events or Markdown.
            result=fallback(re.sub(r'https?://\S+','[资源地址]',str(exc))[:160] if isinstance(exc,ValueError) else '平台播放信息请求未成功')
            ttl=30
        CACHE[canonical]=(time.monotonic()+ttl,result)
        # Bound this process-only cache; no signed addresses are persisted.
        if len(CACHE)>100:
            stale=next(k for k in CACHE if k!=canonical);CACHE.pop(stale)
        return result

def bounded_range(value):
    if not value: return f'bytes=0-{CHUNK_LIMIT-1}'
    match=re.fullmatch(r'bytes=(\d*)-(\d*)',value)
    if not match or not any(match.groups()): raise HTTPException(416,'只支持单个有效字节范围')
    left,right=match.groups()
    if not left:
        length=int(right)
        if length<=0: raise HTTPException(416,'字节范围无效')
        return 'bytes=-'+str(min(length,CHUNK_LIMIT))
    start=int(left)
    end=min(int(right),start+CHUNK_LIMIT-1) if right else start+CHUNK_LIMIT-1
    if start>2**53 or end<start: raise HTTPException(416,'字节范围无效')
    return f'bytes={start}-{end}'

def stream(item,token,range_header):
    entry=STREAMS.get(token)
    if not entry or entry['material_id']!=item['id'] or entry['expires']<=time.monotonic():
        raise HTTPException(404,'播放会话已过期，请重新打开视频')
    selected_range=bounded_range(range_header)
    client=httpx.Client(timeout=httpx.Timeout(45,connect=15),follow_redirects=False)
    upstream=None
    def close():
        if upstream is not None: upstream.close()
        client.close()
    try:
        address=entry['url']
        for _ in range(5):
            safe_media_url(address)
            upstream=client.send(client.build_request('GET',address,headers={
                'Range':selected_range,'User-Agent':'Mozilla/5.0','Referer':'https://www.douyin.com/',
                'Accept-Encoding':'identity'}),stream=True)
            if upstream.status_code in (401,403,429):
                STREAMS.pop(token,None)
                with LOCK:
                    CACHE[adapters.canonical(item['url'])]=(time.monotonic()+30,fallback('平台拒绝播放或限流；已停止，请在原站正常查看'))
                raise HTTPException(502,'平台拒绝播放或限流；已停止，请在原站正常查看')
            if upstream.is_redirect:
                address=str(upstream.url.join(upstream.headers['location']));upstream.close();continue
            break
        else: raise HTTPException(502,'平台播放重定向过多')
        if upstream.status_code==416: raise HTTPException(416,'播放范围不可用')
        content_type=upstream.headers.get('content-type','').split(';')[0].lower()
        content_range=upstream.headers.get('content-range','')
        if upstream.status_code!=206 or content_type not in ('video/mp4','application/octet-stream'):
            raise HTTPException(502,'平台没有提供可定位的视频分段，已停止')
        parsed=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',content_range)
        if not parsed: raise HTTPException(502,'平台视频范围信息不完整')
        start,end,total=map(int,parsed.groups())
        length=end-start+1
        if length<=0 or length>CHUNK_LIMIT or end>=total:
            raise HTTPException(502,'平台返回的视频分段超出约定范围')
        requested_start,requested_end=selected_range[6:].split('-')
        expected_start=int(requested_start) if requested_start else max(0,total-int(requested_end))
        expected_end=min(int(requested_end),total-1) if requested_start else total-1
        declared_length=upstream.headers.get('content-length')
        if ((start,end)!=(expected_start,expected_end) or
                declared_length is not None and (not declared_length.isdigit() or int(declared_length)!=length)):
            raise HTTPException(502,'平台返回的视频分段与请求不一致')
        headers={'Content-Range':content_range,'Content-Length':str(length),'Accept-Ranges':'bytes',
                 'Cache-Control':'no-store'}
        def chunks():
            sent=0
            try:
                for chunk in upstream.iter_raw(65536):
                    if sent+len(chunk)>length: raise ValueError('平台分段长度不一致')
                    sent+=len(chunk);yield chunk
                if sent!=length: raise ValueError('平台分段长度不一致')
            finally: close()
        return StreamingResponse(chunks(),status_code=206,media_type='video/mp4',headers=headers,
                                 background=BackgroundTask(close))
    except HTTPException:
        close();raise
    except Exception:
        close();raise HTTPException(502,'平台视频流暂不可用，请使用原站播放') from None
