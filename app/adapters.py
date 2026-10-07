from __future__ import annotations
import html
import http.cookiejar
import ipaddress
import json
import re
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
import trafilatura
from bs4 import BeautifulSoup
from . import store, sessions, video_pipeline

PLATFORMS = {
    'bilibili': ('B站', ['bilibili.com', 'b23.tv']),
    'youtube': ('YouTube', ['youtube.com', 'youtu.be']),
    'douyin': ('抖音', ['douyin.com', 'iesdouyin.com']),
    'x': ('X', ['x.com', 'twitter.com']),
    'heybox': ('小黑盒', ['xiaoheihe.cn', 'heybox.com', 'heybox.cn']),
    'xiaohongshu': ('小红书', ['xiaohongshu.com', 'xhslink.com']),
}

def platform(url):
    host = (urlparse(url).hostname or '').lower()
    for key, (_, hosts) in PLATFORMS.items():
        if any(host == h or host.endswith('.' + h) for h in hosts):
            return key
    return 'web'

def canonical(url):
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('请提供不带账号密码的 http/https 链接')
    host = parsed.hostname.lower()
    query = parse_qs(parsed.query)
    kind = platform(url)
    if kind == 'youtube':
        vid = query.get('v', [None])[0]
        if host == 'youtu.be':
            vid = parsed.path.strip('/').split('/')[0]
        elif parsed.path.startswith(('/shorts/', '/embed/', '/live/')):
            vid = parsed.path.split('/')[2]
        if vid:
            return f'https://www.youtube.com/watch?v={vid}'
    if kind == 'x':
        match = re.search(r'/status/(\d+)', parsed.path)
        if match:
            return 'https://x.com/i/status/' + match[1]
    if kind == 'douyin':
        vid = query.get('modal_id', query.get('aweme_id', [None]))[0]
        match = re.search(r'/(?:video|share/video)/(\d+)', parsed.path)
        if match: vid = match[1]
        if vid and str(vid).isdigit():
            return 'https://www.douyin.com/video/' + str(vid)
    if kind == 'bilibili':
        match = re.search(r'/(BV[0-9A-Za-z]+|av\d+)', parsed.path)
        if match:
            page = query.get('p', ['1'])[0]
            return f'https://www.bilibili.com/video/{match[1]}' + (f'?p={page}' if page != '1' else '')
    if kind == 'heybox':
        match=re.search(r'/(?:app/(?:bbs|topic)/)?link/(\d+)',parsed.path)
        identifier=match[1] if match else query.get('link_id',[None])[0]
        if identifier and str(identifier).isdigit():
            return 'https://www.xiaoheihe.cn/app/bbs/link/'+str(identifier)
    clean = {k: v for k, v in query.items() if not k.startswith('utm_') and k not in ('spm_id_from', 'share_source', 'si', 'feature')}
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip('/') or '/', '', urlencode(sorted(clean.items()), doseq=True), ''))

def public_url(url):
    canonical(url)
    p = urlparse(url)
    # Desktop proxy clients commonly return RFC 2544 fake-IP addresses for public
    # DNS names. Permit that DNS-only range, never literal private/benchmark URLs.
    try:
        literal = ipaddress.ip_address(p.hostname)
    except ValueError:
        literal = None
    if literal and not literal.is_global:
        raise ValueError('不能抓取本机或内网地址')
    if p.hostname == 'localhost' or p.hostname.endswith(('.local', '.localhost', '.internal')):
        raise ValueError('不能抓取本机或内网地址')
    if p.port not in (None, 80, 443):
        raise ValueError('抓取只允许公共网站的 80/443 端口')
    addresses = socket.getaddrinfo(p.hostname, p.port or 443, type=socket.SOCK_STREAM)
    fake_net = ipaddress.ip_network('198.18.0.0/15')
    if not addresses or any(not (ipaddress.ip_address(a[4][0]).is_global or (not literal and ipaddress.ip_address(a[4][0]) in fake_net)) for a in addresses):
        raise ValueError('不能抓取本机或内网地址')

def fetch(url, headers=None):
    # Validate redirects individually rather than allowing a public URL to enter localhost.
    with httpx.Client(timeout=35, follow_redirects=False, headers={'User-Agent': 'Mozilla/5.0', **(headers or {})}) as client:
        for _ in range(8):
            public_url(url)
            with client.stream('GET', url) as response:
                if response.is_redirect:
                    url = str(response.url.join(response.headers['location']))
                    continue
                response.raise_for_status()
                result = bytearray()
                for chunk in response.iter_bytes():
                    result.extend(chunk)
                    if len(result) > 12_000_000:
                        raise ValueError('页面或字幕超过 12MB 限制')
                return bytes(result).decode('utf-8', errors='replace'), url
    raise ValueError('重定向次数过多')

def seconds(value):
    parts = value.replace(',', '.').split(':')
    return sum(float(n) * 60 ** i for i, n in enumerate(reversed(parts)))

def parse_subtitles(text, ext):
    segments = []
    if ext in ('json', 'json3'):
        value = json.loads(text)
        if 'body' in value:
            segments = [{'start': s['from'], 'end': s['to'], 'text': s['content']} for s in value['body']]
        else:
            for e in value.get('events', []):
                words = ''.join(s.get('utf8', '') for s in e.get('segs', []))
                if words.strip():
                    segments.append({'start': e['tStartMs'] / 1000, 'end': (e['tStartMs'] + e.get('dDurationMs', 0)) / 1000, 'text': words.strip()})
    else:
        pattern = r'(?m)^\s*((?:\d+:)?\d{2}:\d{2}[.,]\d+)\s*-->\s*((?:\d+:)?\d{2}:\d{2}[.,]\d+)[^\n]*\n(.*?)(?=\n\s*\n|\Z)'
        for m in re.finditer(pattern, text, re.S):
            words = html.unescape(re.sub(r'<[^>]+>', '', m[3])).strip()
            if words:
                segments.append({'start': seconds(m[1]), 'end': seconds(m[2]), 'text': words})
    valid = []
    for s in segments:
        s = {'start': float(s['start']), 'end': float(s['end']), 'text': str(s['text']).strip()}
        if s['start'] < 0 or s['end'] < s['start']:
            raise ValueError('字幕时间轴无效')
        if s['text'] and (not valid or s != valid[-1]):
            valid.append(s)
    if not valid:
        raise ValueError('没有解析到带时间轴的字幕；支持 SRT、VTT、B站 JSON、YouTube JSON3')
    return valid

def cookie_args(kind):
    filename = store.settings().get('cookies', {}).get(kind)
    if filename:
        path = (store.ROOT / filename).resolve()
        if not path.is_relative_to(store.ROOT):
            raise ValueError('Cookie 文件必须放在本项目目录内')
        if kind == 'x' and path.suffix == '.json':
            value = json.loads(path.read_text('utf-8'))
            converted = path.with_suffix('.ytdlp.txt')
            lines = ['# Netscape HTTP Cookie File']
            for key in ('auth_token','ct0'):
                secret = str(value.get(key,''))
                if not secret or any(ch in secret for ch in '\r\n\t'):
                    raise ValueError('X Cookie 内容无效')
                lines.append('.x.com\tTRUE\t/\tTRUE\t0\t'+key+'\t'+secret)
            converted.write_text('\n'.join(lines)+'\n','utf-8')
            path = converted
        return ['--cookies', str(path)]
    return []

def bili_api(path, params):
    cookie = http.cookiejar.MozillaCookieJar()
    args = cookie_args('bilibili')
    if args:
        cookie.load(args[1], ignore_discard=True)
    if sessions.path('bilibili').exists():
        # httpx's cookie mapping is only sent to this fixed official API host.
        cookie = sessions.cookie_values('bilibili')
    r = httpx.get('https://api.bilibili.com' + path, params=params, cookies=cookie, timeout=30,
                  headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.bilibili.com/'})
    r.raise_for_status()
    data = r.json()
    if data.get('code') != 0:
        raise ValueError(f'B站返回 {data.get("code")}：{data.get("message", "请检查登录或权限")}')
    return data['data']

def subtitle_language(language):
    return str(language or '').lower().removeprefix('ai-').split('-')[0]


def youtube_subtitle_candidates(info):
    candidates = []
    for key, source in [('subtitles', '平台提供的字幕（人工或来源未声明）'),
                        ('automatic_captions', '平台自动字幕（机器生成）')]:
        for language, tracks in (info.get(key) or {}).items():
            if language == 'live_chat': continue
            for track in tracks:
                if track.get('ext') not in ('json3', 'json', 'vtt', 'srt'): continue
                translated = bool(parse_qs(urlparse(track.get('url', '')).query).get('tlang'))
                candidates.append({'language':language, 'url':track.get('url'), 'format':track['ext'],
                                   'source':'平台自动翻译字幕（机器生成）' if translated else source})
    return candidates


def bili_subtitle_candidates(tracks):
    return [{'language':t.get('lan', '未指定'),
             'url':'https:'+t['subtitle_url'] if t.get('subtitle_url', '').startswith('//') else t.get('subtitle_url'),
             'format':'json', 'source':'B站自动字幕（机器生成）' if t.get('ai_type') or t.get('lan', '').startswith('ai-') else 'B站平台字幕'}
            for t in tracks if t.get('subtitle_url')]


def secondary_subtitles(content, candidates, folder, headers=None):
    primary = subtitle_language(content.get('language'))
    candidates = [t for t in candidates if subtitle_language(t['language']) not in ('', primary)]
    preference = ['en', 'zh'] if primary == 'zh' else ['zh', 'en']
    candidates.sort(key=lambda t: (preference.index(subtitle_language(t['language'])) if subtitle_language(t['language']) in preference else 99,
                                  '机器生成' in t['source'], {'json3':0,'json':1,'vtt':2,'srt':3}[t['format']]))
    if not candidates:
        return {'subtitle_tracks':[], 'bilingual_notice':'平台未返回另一语言字幕；没有生成或虚构译文。'}
    # Try a bounded number of native tracks; never download media or invoke ASR here.
    failed = 0
    for candidate in candidates[:6]:
        try:
            raw, _ = fetch(candidate['url'], headers)
            segments = parse_subtitles(raw, candidate['format'])
            filename = 'secondary-subtitles.' + candidate['format']
            (folder / filename).write_text(raw, 'utf-8')
            return {'subtitle_tracks':[{'language':candidate['language'], 'source':candidate['source'],
                                        'format':candidate['format'], 'raw_file':filename, 'segments':segments}],
                    'bilingual_notice':''}
        except Exception:
            failed += 1
    return {'subtitle_tracks':[], 'bilingual_notice':f'另一语言字幕读取失败（尝试 {failed} 条轨道）；原字幕仍保留，可稍后重试。'}


def fetch_secondary_subtitles(item, folder):
    url = item['content'].get('resolved_url') or item['url']
    if item['platform'] == 'bilibili':
        if urlparse(url).hostname == 'b23.tv': _, url = fetch(url)
        match = re.search(r'/(BV[0-9A-Za-z]+|av\d+)', urlparse(url).path)
        if not match: raise ValueError('缺少可识别的 B站视频地址')
        info = bili_api('/x/web-interface/view', {'bvid':match[1]} if match[1].startswith('BV') else {'aid':match[1][2:]})
        pages = info.get('pages') or [{'cid':info['cid']}]
        part = int(parse_qs(urlparse(url).query).get('p', [item['content'].get('part', {}).get('index', 1)])[0])
        if part < 1 or part > len(pages): raise ValueError('分 P 序号不存在')
        player = bili_api('/x/player/v2', {'bvid':info['bvid'], 'cid':pages[part-1]['cid']})
        candidates = bili_subtitle_candidates(player.get('subtitle', {}).get('subtitles', []))
        headers = None
    elif item['platform'] == 'youtube':
        info = json.loads(ytdlp(url, ['--dump-single-json', '--skip-download', '--no-playlist']))
        candidates = youtube_subtitle_candidates(info)
        headers = info.get('http_headers')
    else:
        raise ValueError('第二语言字幕目前支持 B站和 YouTube 的平台轨道')
    return secondary_subtitles(item['content'], candidates, folder, headers)


def bili_video(url, folder, transcribe=True):
    video_pipeline.stage('subtitles', '正在检查 B站平台字幕')
    if urlparse(url).hostname == 'b23.tv':
        _, url = fetch(url)
    match = re.search(r'/(BV[0-9A-Za-z]+|av\d+)', urlparse(url).path)
    if not match:
        raise ValueError('目前 B站自动采集支持视频 BV/av 链接；文章和动态请粘贴原文')
    key = {'bvid': match[1]} if match[1].startswith('BV') else {'aid': match[1][2:]}
    info = bili_api('/x/web-interface/view', key)
    (folder / 'original-metadata.json').write_text(store.dumps(info), 'utf-8')
    pages = info.get('pages') or [{'cid': info['cid']}]
    page = int(parse_qs(urlparse(url).query).get('p', ['1'])[0])
    if page < 1 or page > len(pages):
        raise ValueError('分 P 序号不存在')
    content = {'source': 'B站视频接口', 'subtitle_source': '未取得字幕', 'segments': [], 'resolved_url':url,
               'duration':pages[page-1].get('duration') or info.get('duration')}
    result = {'title': info['title'], 'body': info.get('desc', ''), 'content': content, 'collection': 'partial'}
    if info.get('pic'):
        result['body'] += '\n\n![视频封面（不代表视频画面内容）](' + info['pic'] + ')'
    content['comments'] = []
    try:
        replies = bili_api('/x/v2/reply', {'type':1, 'oid':info.get('aid',''), 'pn':1, 'ps':20, 'sort':2})
        seen = set()
        for reply in [*(replies.get('hots') or []), *(replies.get('replies') or [])]:
            rid = str(reply.get('rpid', ''))
            if not rid or rid in seen or len(content['comments']) >= 20: continue
            seen.add(rid)
            text = reply.get('content',{}).get('message','')
            for picture in reply.get('content',{}).get('pictures',[]):
                if picture.get('img_src'): text += '\n\n![评论图片](' + picture['img_src'] + ')'
            content['comments'].append({'author':reply.get('member',{}).get('uname','未署名'),
                'body':text, 'created':str(reply.get('ctime','')), 'url':url+'#reply'+rid})
        content['comments_status'] = f'B站平台返回的热门/首页评论，最多 20 条；已取得 {len(content["comments"])} 条，不是全部评论。'
    except Exception:
        content['comments_status'] = 'B站评论读取失败或无权限；没有把失败视为无评论。'
    if len(pages) > 1:
        result['title'] += f' · P{page} ' + pages[page-1].get('part','')
        content['part'] = {'index':page,'total':len(pages)}
        if 'p=' not in url:
            result['additional_parts'] = [f'https://www.bilibili.com/video/{info["bvid"]}?p={n}' for n in range(2,len(pages)+1)]
    try:
        player = bili_api('/x/player/v2', {'bvid': info['bvid'], 'cid': pages[page - 1]['cid']})
        tracks = player.get('subtitle', {}).get('subtitles', [])
        tracks.sort(key=lambda x: (x.get('ai_type', 0) != 0, not x.get('lan', '').startswith('zh')))
        for track in tracks:
            link = track.get('subtitle_url', '')
            if not link:
                continue
            raw, _ = fetch('https:' + link if link.startswith('//') else link)
            segments = parse_subtitles(raw, 'json')
            (folder / 'original-subtitles.json').write_text(raw, 'utf-8')
            content.update(segments=segments, language=track.get('lan', '未指定'),
                           subtitle_source='B站自动字幕（机器生成）' if track.get('ai_type') or track.get('lan', '').startswith('ai-') else 'B站平台字幕')
            content.update(secondary_subtitles(content, bili_subtitle_candidates(tracks), folder))
            result['collection'] = 'ready'
            return result
        reason = '平台未返回可用字幕，可能需要登录，也可能视频本身无字幕'
    except Exception as exc:
        reason = '字幕请求失败：' + re.sub(r'https?://\S+', '[资源链接]', str(exc))[:200]
    try:
        data = bili_api('/x/player/playurl', {'bvid':info['bvid'], 'cid':pages[page-1]['cid'], 'fnval':16, 'qn':16})
        audio = (data.get('dash') or {}).get('audio') or data.get('durl') or []
        if not audio: raise ValueError('B站没有返回可用音频；请在官方窗口登录后重试')
        links=[]
        for track in sorted(audio,key=lambda a:a.get('bandwidth',0)):
            links.extend([track.get('baseUrl') or track.get('base_url') or track.get('url'),
                          *(track.get('backupUrl') or track.get('backup_url') or [])])
        link=next((v for v in links if v and urlparse(v).port in (None,80,443)),None)
        if not link: raise ValueError('平台音频地址缺失')
        video_pipeline.direct_audio(link, pages[page-1].get('duration') or info.get('duration'), content, folder,
                                    {'Referer':url, 'User-Agent':'Mozilla/5.0'})
        result['collection']='partial' if content.get('transcript_state')=='uncertain' else 'ready'
        return result
    except Exception as exc:
        video_pipeline.transcription_failure(content,exc)
        reason += '；自动音频转写失败：' + re.sub(r'https?://\S+', '[资源链接]', str(exc))[:400]
    content['warning'] = reason + '。尚未获得视频正文，不标成成功；登录后可重新自动采集。'
    return result

def ytdlp(url, extra, timeout=150):
    public_url(url)
    if platform(url) not in ('bilibili', 'youtube', 'douyin', 'x', 'xiaohongshu'):
        raise ValueError('该平台未接入视频提取器')
    kind = platform(url)
    temporary = None
    cookies = cookie_args(kind) if not sessions.path(kind).exists() else []
    if sessions.path(kind).exists():
        tmp = store.ROOT/'tmp'; tmp.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix='session-',dir=tmp)
        path = Path(temporary.name)/'cookies.txt'
        lines = ['# Netscape HTTP Cookie File']
        for cookie in sessions.load(kind)['cookies']:
            value = str(cookie['value'])
            if any(c in value for c in '\r\n\t'): continue
            lines.append('\t'.join([cookie['domain'],'TRUE' if cookie['domain'].startswith('.') else 'FALSE',
                                   cookie.get('path','/'),'TRUE' if cookie.get('secure') else 'FALSE',
                                   str(max(0,int(cookie.get('expires',0)))),cookie['name'],value]))
        path.write_text('\n'.join(lines)+'\n','utf-8'); cookies=['--cookies',str(path)]
    cmd = [sys.executable, '-m', 'yt_dlp', '--ignore-config', '--no-cache-dir', '--no-warnings',
           '--socket-timeout', '20', '--retries', '1', '--extractor-retries', '1',
           '--js-runtimes', 'node', *cookies, *extra, '--', url]
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    finally:
        if temporary: temporary.cleanup()
    if run.returncode:
        error = run.stderr[-1400:]
        # Never persist signed resource URLs or cookies from diagnostics.
        error = re.sub(r'https?://\S+', '[资源链接]', error)
        raise ValueError(error or '平台提取失败')
    return run.stdout

def manual(payload):
    body = payload.get('text', '').strip()
    subs = payload.get('subtitles', '').strip()
    if not body and not subs:
        raise ValueError('请粘贴原文或带时间轴的字幕')
    content = {'source': '用户提供的原文（未核验平台完整性）', 'original_text': payload.get('text', ''), 'warning': '这是用户提供的存档，完整性由提供者核对。'}
    if subs:
        content.update(segments=parse_subtitles(subs, payload.get('subtitle_format', 'vtt')),
                       raw_subtitles=payload.get('subtitles', ''), subtitle_format=payload.get('subtitle_format', 'vtt'),
                       subtitle_source='用户导入：' + payload.get('subtitle_source', '来源未声明'), language=payload.get('language', '未指定'))
    return {'title': payload.get('title') or payload['url'], 'body': body, 'content': content, 'collection': 'ready'}

def firecrawl(url, folder):
    public_url(url)
    cfg = store.settings()
    base = cfg.get('firecrawl_base_url', 'https://api.firecrawl.dev').rstrip('/')
    if not cfg.get('firecrawl_api_key'):
        raise ValueError('请先在 config.json 配置 firecrawl_api_key；默认不会把链接发送给 Firecrawl')
    r = httpx.post(base + '/v2/scrape', timeout=90,
                   headers={'Authorization': 'Bearer ' + cfg['firecrawl_api_key']},
                   json={'url': url, 'formats': ['markdown', 'rawHtml'], 'onlyMainContent': True})
    if r.status_code != 200:
        raise ValueError(f'Firecrawl 返回 HTTP {r.status_code}')
    result = r.json()
    data = result.get('data') or {}
    if not result.get('success') or not data.get('markdown', '').strip():
        raise ValueError('Firecrawl 没有返回有效正文')
    (folder / 'firecrawl.json').write_text(store.dumps(data), 'utf-8')
    return {'title': (data.get('metadata') or {}).get('title') or url, 'body': data['markdown'], 'collection': 'partial',
            'content': {'source': 'Firecrawl /v2/scrape', 'warning': '外部网页提取结果待核对；不代表已取得受限平台全文或视频字幕。核对后可补充原文存档。'}}

def collect(url, folder: Path, transcribe=True, engine='local'):
    if engine == 'firecrawl':
        return firecrawl(url, folder)
    kind = platform(url)
    if kind == 'bilibili':
        return bili_video(url, folder, True)
    if kind == 'douyin':
        return video_pipeline.douyin(url, folder)
    if kind in ('heybox', 'xiaohongshu'):
        from .platform_browser import text_material
        return text_material(url, folder)
    if kind == 'x':
        # Official oEmbed retains the original post text, but not threads or quoted/media content.
        try:
            raw, _ = fetch('https://publish.twitter.com/oembed?' + urlencode({'url': url, 'omit_script': 'true'}))
            data = json.loads(raw)
            soup = BeautifulSoup(data['html'], 'html.parser')
            post = soup.select_one('blockquote p')
            if post and post.get_text().strip():
                (folder / 'original-oembed.json').write_text(raw, 'utf-8')
                return {'title': post.get_text(' ', strip=True)[:90], 'body': post.get_text('\n', strip=True), 'collection': 'partial',
                        'content': {'source': 'X 官方 oEmbed', 'warning': '只获取当前帖文字，未验证长文截断、引用、图片、视频与线程。请核对并补充原文。'}}
        except (ValueError, KeyError, httpx.HTTPError, OSError):
            pass
        raise ValueError('X 官方公开嵌入接口未返回帖子；请使用统一入口完成官方 OAuth 授权后重试，不默认用网页脚本读取账号')
    if kind == 'youtube':
        return video(url, folder, True)
    raw, resolved = fetch(url)
    (folder / 'original.html').write_text(raw, 'utf-8')
    body = trafilatura.extract(raw, url=resolved, output_format='markdown', include_links=True, include_images=True, include_tables=True, include_comments=False)
    metadata = trafilatura.extract_metadata(raw)
    if not body or len(body.strip()) < 120:
        raise ValueError('未取得足够的正文，可能需要登录或页面依赖脚本；请粘贴原文')
    comment_doc = trafilatura.bare_extraction(raw, url=resolved, include_comments=True)
    comments = getattr(comment_doc, 'comments', None) or ''
    return {'title': metadata.title if metadata and metadata.title else url, 'body': body, 'collection': 'ready',
            'content': {'source': '公开网页正文提取；原始 HTML 已保留', 'resolved_url': resolved,
                        'comments':[{'body':comments[:50000], 'author':'静态网页评论区（作者未验证）', 'url':resolved}] if comments else [],
                        'comments_status':'只提取 HTML 中可辨认的静态评论区；动态加载评论未获取，不能视为完整评论。',
                        'warning': '网页提取可能漏掉动态内容，请对照原链接核查。'}}

def video(url, folder, transcribe):
    video_pipeline.stage('subtitles','正在获取平台字幕，优先人工字幕，其次平台自动字幕')
    extra = ['--dump-single-json', '--skip-download', '--no-playlist']
    if platform(url) == 'youtube': extra += ['--write-comments', '--extractor-args', 'youtube:max_comments=20']
    info = json.loads(ytdlp(url, extra))
    if info.get('entries'):
        entries = info['entries']
        if len(entries) != 1:
            raise ValueError('多分 P 视频请提供带 ?p= 的单集链接，避免遗漏其他分集')
        info = entries[0]
    (folder / 'metadata.json').write_text(store.dumps({k: info.get(k) for k in ('id', 'title', 'description', 'uploader', 'webpage_url', 'duration')}), 'utf-8')
    content = {'source': '平台视频元数据', 'segments': [], 'subtitle_source': '未取得字幕', 'duration':info.get('duration'),
               'resolved_url':info.get('webpage_url') or url}
    if info.get('thumbnail'):
        info['description'] = (info.get('description') or '') + '\n\n![视频封面（不代表视频画面内容）](' + info['thumbnail'] + ')'
    content['comments'] = [{'author':c.get('author') or '未署名', 'body':c.get('text') or '',
        'created':str(c.get('timestamp','')), 'url':url+('&' if '?' in url else '?')+'lc='+str(c.get('id',''))}
        for c in (info.get('comments') or [])[:20]]
    content['comments_status'] = f'平台提取器返回的部分评论，最多 20 条；已取得 {len(content["comments"])} 条。未返回评论可能是关闭、权限或提取限制，不能视为没有评论。'
    failures = []
    languages = store.settings().get('subtitle_languages', ['zh-Hans', 'zh-CN', 'zh', 'en'])
    for key, source in [('subtitles', '平台提供的字幕（人工或来源未声明）'), ('automatic_captions', '平台自动字幕（机器生成）')]:
        tracks = info.get(key) or {}
        langs = sorted((k for k in tracks if k != 'live_chat'), key=lambda k: next((i for i, p in enumerate(languages) if k.startswith(p)), 99))
        for lang in langs:
            choices = sorted(tracks[lang], key=lambda t: {'json3': 0, 'json': 1, 'vtt': 2, 'srt': 3}.get(t.get('ext'), 99))
            for track in choices:
                ext = track.get('ext', '')
                if ext not in ('json3', 'json', 'vtt', 'srt'):
                    continue
                try:
                    raw, _ = fetch(track['url'], info.get('http_headers'))
                    segments = parse_subtitles(raw, ext)
                    (folder / f'original-subtitles.{ext}').write_text(raw, 'utf-8')
                    content.update(segments=segments, subtitle_source=('平台自动字幕（机器生成）' if lang.startswith('ai-') else source), language=lang)
                    if parse_qs(urlparse(track['url']).query).get('tlang'):
                        content['subtitle_source'] = '平台自动翻译字幕（机器生成）'
                    content.update(secondary_subtitles(content, youtube_subtitle_candidates(info), folder, info.get('http_headers')))
                    return {'title': info['title'], 'body': info.get('description') or '', 'content': content, 'collection': 'ready'}
                except Exception as exc:
                    failures.append(type(exc).__name__)
    if transcribe:
        try:
            if not info.get('duration') or info['duration'] > 7200:
                raise ValueError('本版本机转写只接受时长明确且不超过 2 小时的视频')
            ytdlp(url, ['--no-playlist', '-f', 'bestaudio/best', '--max-filesize', '300M',
                        '-o', str(folder / 'audio.%(ext)s')], timeout=600)
            audio = [p for p in folder.glob('audio.*') if p.suffix not in ('.part', '.ytdl')]
            if not audio:
                raise ValueError('未获得完整音频')
            video_pipeline.transcribe(audio[0], info['duration'], content, folder)
            return {'title': info['title'], 'body': info.get('description') or '', 'content': content,
                    'collection': 'partial' if content.get('transcript_state')=='uncertain' else 'ready'}
        except ImportError as exc:
            video_pipeline.transcription_failure(content,exc)
            failures.append('本机转写组件不可用；请在任务记录查看组件错误')
        except Exception as exc:
            video_pipeline.transcription_failure(content,exc)
            failures.append(str(exc)[:300])
        finally:
            for temporary in folder.glob('audio.*'): temporary.unlink(missing_ok=True)
    content['warning'] = '已尝试自动字幕与本机转写，尚未取得视频正文，不能标成成功。登录后可重新自动采集。' + ('；' + '；'.join(failures[-3:]) if failures else '')
    return {'title': info['title'], 'body': info.get('description') or '', 'content': content, 'collection': 'partial'}

def favorites(url):
    kind = platform(url)
    if kind not in ('bilibili', 'youtube'):
        raise ValueError('目前仅 B站收藏夹与 YouTube 播放列表支持自动枚举；其他平台请导入收藏链接清单')
    p = urlparse(url)
    q = parse_qs(p.query)
    if kind == 'youtube' and not q.get('list'):
        raise ValueError('请提供含 list= 的 YouTube 播放列表链接')
    if kind == 'bilibili' and not (q.get('fid') or '/favlist' in p.path):
        raise ValueError('请提供 B站收藏夹链接（含 fid=）')
    if kind == 'bilibili':
        fid = q.get('fid', [None])[0]
        if not fid:
            raise ValueError('请从 B站收藏夹地址复制含 fid= 的完整链接')
        values = []
        for page in range(1, 26):
            data = bili_api('/x/v3/fav/resource/list', {'media_id': fid, 'pn': page, 'ps': 20, 'platform': 'web'})
            for entry in data.get('medias') or []:
                bvid = entry.get('bvid')
                if not bvid:
                    raise ValueError('收藏夹含无视频链接的条目，请使用原文导入补充')
                values.append({'url': 'https://www.bilibili.com/video/' + bvid, 'title': entry.get('title', '')})
            if not data.get('has_more'):
                return values, False
        return values, True
    result = json.loads(ytdlp(url, ['--flat-playlist', '--dump-single-json', '--skip-download', '--playlist-end', '501'], timeout=300))
    entries = result.get('entries') or []
    values = []
    for entry in entries:
        if not entry:
            raise ValueError('列表含不可读取条目；请核查权限后重试')
        link = entry.get('webpage_url') or entry.get('url')
        if not link or not link.startswith('http'):
            if kind == 'youtube' and entry.get('id'):
                link = 'https://www.youtube.com/watch?v=' + entry['id']
            else:
                raise ValueError('收藏条目缺少可访问链接')
        values.append({'url': link, 'title': entry.get('title', '')})
    if not values:
        raise ValueError('未读取到任何收藏；可能是空列表、未登录或权限受限')
    return values[:500], len(values) > 500
