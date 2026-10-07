"""Archive raster images, retaining Markdown order and original source URLs."""
from __future__ import annotations
import re
from pathlib import Path
from urllib.parse import urljoin, unquote

import httpx
from . import adapters, store

IMAGE = re.compile(r'!\[([^\]\n]*)\]\(([^\s)]+)(?:\s+"[^"]*")?\)')

def raster_type(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'): return 'png'
    if data.startswith(b'\xff\xd8\xff'): return 'jpg'
    if data[:6] in (b'GIF87a', b'GIF89a'): return 'gif'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP': return 'webp'
    if len(data) > 12 and data[4:8] == b'ftyp' and data[8:12] in (b'avif', b'avis'): return 'avif'
    raise ValueError('图片响应不是支持的栅格格式（PNG/JPEG/GIF/WebP/AVIF）')

def download(url):
    # No platform cookies are sent to image hosts, including redirect destinations.
    with httpx.Client(timeout=25, follow_redirects=False, headers={'User-Agent':'Mozilla/5.0'}) as client:
        for _ in range(6):
            adapters.public_url(url)
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
    previous = content.get('media', [])
    existing = {a['path']:a for a in previous if a.get('status') == 'saved' and a.get('path')}
    content['media'] = list(existing.values())
    cache = {}
    def replace(match):
        alt, original = match.groups()
        if original in existing: return match.group(0)
        source = urljoin(base_url, original.strip('<>'))
        if source in cache: return f'![{alt}]({cache[source]})'
        entry = {'source_url': source, 'alt': alt, 'status': 'failed'}
        content['media'].append(entry)
        try:
            if len(content['media']) > 40: raise ValueError('本次图片超过 40 张上限')
            data, ext = download(source)
            asset = folder / 'images' / (store.digest(source)[:24] + '.' + ext)
            asset.parent.mkdir(parents=True, exist_ok=True)
            asset.write_bytes(data)
            relative = asset.relative_to(store.material_folder(mid)).as_posix()
            entry.update(status='saved', path=relative, sha256=store.digest_bytes(data), bytes=len(data))
            # Paths are relative to material.md; API rewrites only these validated paths.
            cache[source] = relative
            return f'![{alt}]({relative})'
        except Exception as exc:
            entry['error'] = type(exc).__name__ + '：图片未存档'
            return f'[图片未存档：{alt or "图片"}]({source})'
    content.setdefault('original_body', result['body'])
    result['body'] = IMAGE.sub(replace, result['body'])
    for comment in content.get('comments', []):
        comment['body'] = IMAGE.sub(replace, comment.get('body', ''))
    if any(a['status'] != 'saved' for a in content['media']):
        content['warning'] = (content.get('warning', '') + ' 部分图片未能存档，请查看图片来源记录。').strip()
        result['collection'] = 'partial'
    return result
