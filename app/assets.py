"""Archive raster images, retaining Markdown order and original source URLs."""
from __future__ import annotations
import re
from contextlib import ExitStack
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import urljoin, unquote

import httpx
from . import adapters, store

IMAGE = re.compile(r'!\[([^\]\n]*)\]\(([^\s)]+)(?:\s+"[^"]*")?\)')
FAILED_IMAGE = re.compile(r'\[图片未存档：([^\]\n]*)\]\(([^\s)]+)\)')
IMAGE_CLIENT=ContextVar("image_client",default=None)
MAX_IMAGES = 200
MAX_CAPTURE_BYTES = 128_000_000

def needs_retry(item):
    media=item['content'].get('media',[])
    if item['content'].get('missing_image_count') or any(m.get('status')!='saved' for m in media):return True
    for m in media:
        if m.get('path'):
            path=(store.material_folder(item['id'])/m['path']).resolve()
            if not path.is_relative_to(store.material_folder(item['id']).resolve()) or not path.is_file():return True
    return False

def needs_source(item):
    # Legacy empty src values were wrongly resolved to the HTML source page.
    from .adapters import canonical
    base=item['content'].get('resolved_url',item['url'])
    return bool(item['content'].get('missing_image_count')) or any(
        m.get('status')!='saved' and canonical(m.get('source_url',''))==canonical(base)
        for m in item['content'].get('media',[]))

def raster_type(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'): return 'png'
    if data.startswith(b'\xff\xd8\xff'): return 'jpg'
    if data[:6] in (b'GIF87a', b'GIF89a'): return 'gif'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP': return 'webp'
    if len(data) > 12 and data[4:8] == b'ftyp' and data[8:12] in (b'avif', b'avis'): return 'avif'
    raise ValueError('图片响应不是支持的栅格格式（PNG/JPEG/GIF/WebP/AVIF）')

def download(url):
    # No platform cookies are sent to image hosts, including redirect destinations.
    with ExitStack() as stack:
        client=IMAGE_CLIENT.get() or stack.enter_context(httpx.Client(timeout=25,follow_redirects=False,headers={'User-Agent':'Mozilla/5.0'}))
        for _ in range(6):
            adapters.public_url(url)
            client.cookies.clear()
            with client.stream('GET', url) as response:
                if response.is_redirect:
                    url = str(response.url.join(response.headers['location']))
                    continue
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 8_000_000: raise ValueError('单张图片超过 8MB')
                value = bytes(data)
                return value, raster_type(value)
    raise ValueError('图片重定向过多')

def image_path(mid, relative):
    if mid.startswith('l1_'):
        from .first_layer import media_root
        root=media_root(mid).resolve()
    else:root = store.material_folder(mid).resolve()
    path = (root / unquote(relative)).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('材料图片不存在或路径无效')
    raster_type(path.read_bytes()[:32])
    return path

def localize(result, folder, mid, base_url):
    content = result['content']
    if 'original_text_complete' not in content and result['collection']=='ready':content['original_text_complete']=True
    previous = content.get('media', [])
    root=store.material_folder(mid).resolve()
    existing = {a['path']:a for a in previous if a.get('status') == 'saved' and a.get('path')
                and (root/a['path']).resolve().is_relative_to(root) and (root/a['path']).is_file()}
    original_sources={a['path']:a['source_url'] for a in previous if a.get('path') and a.get('source_url')}
    retryable={a.get('source_url') for a in previous if a.get('status')!='saved'}
    def restore_failed(text):
        return FAILED_IMAGE.sub(lambda m:f'![{m[1]}]({m[2]})' if m[2] in retryable else m[0],text)
    result['body']=restore_failed(result['body'])
    for comment in content.get('comments',[]):comment['body']=restore_failed(comment.get('body',''))
    content['media'] = list(existing.values())
    cache = {a['source_url']:a['path'] for a in existing.values() if a.get('source_url')}
    failed={};stored_bytes=sum(a.get('bytes',0) for a in existing.values())
    def replace(match):
        nonlocal stored_bytes
        alt, original = match.groups()
        if original in existing: return match.group(0)
        source = original_sources.get(original) or urljoin(base_url, original.strip('<>'))
        if source in cache: return f'![{alt}]({cache[source]})'
        if source in failed:return f'[图片未存档：{alt or "图片"}]({source})'
        entry = {'source_url': source, 'alt': alt, 'status': 'failed'}
        content['media'].append(entry)
        try:
            if len(content['media']) > MAX_IMAGES: raise ValueError('本次图片超过 200 张上限')
            data, ext = download(source)
            if stored_bytes+len(data)>MAX_CAPTURE_BYTES:raise ValueError('本条图片总量超过 128MB')
            asset = folder / 'images' / (store.digest(source)[:24] + '.' + ext)
            asset.parent.mkdir(parents=True, exist_ok=True)
            asset.write_bytes(data)
            relative = asset.relative_to(store.material_folder(mid)).as_posix()
            entry.update(status='saved', path=relative, sha256=store.digest_bytes(data), bytes=len(data))
            stored_bytes+=len(data)
            # Paths are relative to material.md; API rewrites only these validated paths.
            cache[source] = relative
            return f'![{alt}]({relative})'
        except Exception as exc:
            if isinstance(exc,httpx.HTTPStatusError):reason=f'图片服务器返回 {exc.response.status_code}'
            elif isinstance(exc,httpx.TimeoutException):reason='图片下载超时'
            elif isinstance(exc,ValueError):reason=str(exc) if str(exc).startswith(('本次图片','本条图片','单张图片','图片响应')) else '图片地址或文件格式不可用'
            else:reason='图片下载或本机保存失败'
            entry['error']=reason;failed[source]=entry
            return f'[图片未存档：{alt or "图片"}]({source})'
    content.setdefault('original_body', result['body'])
    with httpx.Client(timeout=25,follow_redirects=False,headers={'User-Agent':'Mozilla/5.0'}) as client:
        token=IMAGE_CLIENT.set(client)
        try:
            result['body']=IMAGE.sub(replace,result['body'])
            for comment in content.get('comments',[]):comment['body']=IMAGE.sub(replace,comment.get('body',''))
        finally:IMAGE_CLIENT.reset(token)
    if any(a['status'] != 'saved' for a in content['media']):
        content['warning'] = (content.get('warning', '') + ' 部分图片未能存档，请查看图片来源记录。').strip()
        result['collection'] = 'partial'
    elif not content.get('missing_image_count'):
        content['warning']=content.get('warning','').replace('部分图片未能存档，请查看图片来源记录。','').strip()
    return result
