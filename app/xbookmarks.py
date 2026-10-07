"""Read-only X session adapter. No login/password, posting or bookmark mutations."""
from __future__ import annotations
import asyncio
import http.cookiejar
import json
import re
import random
import time
import threading
from . import store, sessions

REQUEST_LOCK=threading.Lock()
NEXT_REQUEST=0.0
BLOCKED=threading.Event()
BLOCK_REASON=''

def reserve_delay():
    """Caller holds REQUEST_LOCK. Keep the same low read pace across restarts."""
    global NEXT_REQUEST
    wall=time.time(); mono=time.monotonic()
    path=store.DATA/'x-read-next.json'
    try: deadline=json.loads(path.read_text('utf-8')).get('not_before',0)
    except (OSError,ValueError): deadline=0
    delay=max(0,NEXT_REQUEST-mono,deadline-wall)
    interval=random.uniform(8,12)
    NEXT_REQUEST=mono+delay+interval
    store.DATA.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(store.dumps({'not_before':wall+delay+interval}),'utf-8')
    temporary.replace(path)
    return delay

def clear_block():
    global BLOCK_REASON
    BLOCK_REASON=''; BLOCKED.clear()
    (store.DATA/'x-read-block.json').unlink(missing_ok=True)

def block(reason):
    global BLOCK_REASON
    BLOCK_REASON=reason; BLOCKED.set()
    store.DATA.mkdir(parents=True,exist_ok=True)
    (store.DATA/'x-read-block.json').write_text(store.dumps({'reason':reason,'created':store.now()}),'utf-8')
    with store.db() as c:
        c.execute("UPDATE jobs SET state='paused',error=?,updated=? WHERE state='queued' AND (material_id IN (SELECT id FROM materials WHERE platform='x') OR (kind='favorites' AND json_extract(payload,'$.platform')='x'))",(reason,store.now()))
        c.execute("UPDATE materials SET collection='paused',error=? WHERE platform='x' AND collection='queued'",(reason,))
        store.event(c,None,'x_read_stopped',{'reason':reason,'automatic_retry':False})

def blocked_reason():
    path=store.DATA/'x-read-block.json'
    if BLOCKED.is_set(): return BLOCK_REASON
    if path.exists(): return json.loads(path.read_text('utf-8'))['reason']
    return ''

async def check_response(response):
    if response.status_code in (401,403,429):
        reason=f'X 返回 HTTP {response.status_code}，已停止全部 X 读取并保留原文；请正常登录检查账号，再手动继续。'
        block(reason)
        raise ValueError(reason)

async def pace(request):
    """One shared read pace across favorite and detail workers; never auto-retry a block."""
    if request.method!='GET': raise ValueError('X 收藏通道只允许读取请求')
    if blocked_reason(): raise ValueError(blocked_reason())
    with REQUEST_LOCK:
        delay=reserve_delay()
    if delay: await asyncio.sleep(delay)
    if blocked_reason(): raise ValueError(blocked_reason())

def read_cookies():
    if sessions.path('x').exists():
        value = sessions.cookie_values('x')
        if not value.get('auth_token') or not value.get('ct0'): raise ValueError('X 登录尚未完成或已过期；请在官方窗口重新登录')
        return {k:value[k] for k in ('auth_token','ct0')}
    configured = store.settings().get('cookies', {}).get('x')
    if not configured:
        raise ValueError('请在「导入收藏 → X」打开登录窗口，完成登录并保存状态；账号名不能访问私人书签')
    path = (store.ROOT / configured).resolve()
    if not path.is_relative_to(store.ROOT): raise ValueError('登录信息必须保存在本项目内')
    if path.suffix == '.json':
        value = json.loads(path.read_text('utf-8'))
    else:
        jar = http.cookiejar.MozillaCookieJar(str(path))
        try: jar.load(ignore_discard=True, ignore_expires=True)
        except Exception: raise ValueError('X Cookie 文件无效，请重新导出 JSON 或 Netscape 格式') from None
        value = {c.name: c.value for c in jar if c.domain.lstrip('.') in ('x.com', 'twitter.com')}
    if not value.get('auth_token') or not value.get('ct0'):
        raise ValueError('X Cookie 缺少 auth_token 或 ct0，请重新导出当前登录的网站 Cookie')
    return {k: value[k] for k in ('auth_token', 'ct0')}

def client():
    from twikit import Client
    session = Client('en-US', timeout=30)
    session.http.event_hooks.setdefault('request',[]).append(pace)
    session.http.event_hooks.setdefault('response',[]).append(check_response)
    for name, value in read_cookies().items():
        session.http.cookies.set(name, value, domain='.x.com', path='/')
    return session

def account_info(user):
    return {'id': str(user.id), 'username': user.screen_name, 'name': user.name}

async def checked_account():
    session = client()
    try:
        info = account_info(await session.user())
        config = store.settings()
        config['x_account'] = info
        store.save_settings(config)
        return info
    finally:
        await session.http.aclose()

def error_message(exc):
    name = type(exc).__name__
    if name in ('TooManyRequests',): return 'X 限流，已保存的条目仍在；请稍后继续同步。'
    if name in ('Unauthorized', 'Forbidden', 'AccountSuspended', 'AccountLocked'):
        return 'X 登录已过期或账号受限，请在浏览器正常登录后重新导出单平台 Cookie。'
    return f'X 读取失败（{name}）；平台接口可能变化。没有把失败当成空收藏或成功。'

def photo_markdown(tweet):
    text = tweet.full_text or tweet.text or ''
    for entity in tweet.urls or []:
        if entity.get('url') and entity.get('expanded_url'):
            text = text.replace(entity['url'], entity['expanded_url'])
    pictures = []
    video = False
    for media in tweet.media or []:
        media = media if isinstance(media, dict) else media._data
        kind = media.get('type')
        link = media.get('media_url_https') or media.get('media_url')
        if link and kind == 'photo':
            alt = media.get('ext_alt_text') or ('视频封面（不代表视频画面内容）' if kind != 'photo' else '帖子图片')
            picture = f'![{alt.replace("]", "").replace("[", "").replace(chr(10), " ")}]({link})'
            anchor = media.get('url')
            if anchor and anchor in text:
                text = text.replace(anchor, picture, 1)
            else:
                pictures.append(picture)
        video |= kind in ('video', 'animated_gif')
    return text + ('\n\n' + '\n\n'.join(pictures) if pictures else ''), video

def post_record(tweet):
    body, video = photo_markdown(tweet)
    user = tweet.user
    return {'id': str(tweet.id), 'author': '@' + user.screen_name if user else '未署名',
            'created': tweet.created_at, 'body': body, 'video': video,
            'url': f'https://x.com/i/status/{tweet.id}'}

def seed_record(tweet):
    value = post_record(tweet)
    return {'url': value['url'], 'title': value['author'] + '：' + (tweet.full_text or tweet.text)[:80],
            'body': value['body'], 'content': {'source': 'X 登录会话书签列表（Twikit，非付费开发者 API）',
                'author': value['author'], 'created_at': value['created'], 'comments': [],
                'comments_status': '尚未读取回复', 'warning': '已保留书签列表返回原文；帖子详情尚未验证。'},
            'collection': 'partial'}

async def detail(url, seed=None, comment_limit=20):
    match = re.search(r'/status/(\d+)', url)
    if not match: raise ValueError('X 自动读取需要具体帖子链接')
    session = client()
    try:
        tweet = await session.get_tweet_by_id(match[1])
        record = post_record(tweet)
        if not record['body'].strip(): raise ValueError('帖子没有可读取的正文或图片')
        body = record['body']
        context = []
        seen_context = {record['id']}
        for part in [*(tweet.reply_to or []), *(tweet.thread or [])]:
            if str(part.id) in seen_context: continue
            seen_context.add(str(part.id))
            r = post_record(part)
            context.append(r)
        if tweet.quote:
            r = post_record(tweet.quote)
            body += '\n\n### 引用的帖子\n\n' + r['author'] + '\n\n' + r['body'] + '\n\n来源：' + r['url']
        for r in context:
            body += '\n\n### 平台返回的线程上下文\n\n' + r['author'] + '\n\n' + r['body'] + '\n\n来源：' + r['url']
        comments, seen = [], {record['id'], *(r['id'] for r in context)}
        page = tweet.replies
        pages = 0
        cursors = set()
        warning = ''
        try:
            while page is not None and pages < 5 and len(comments) < comment_limit:
                pages += 1
                # Include visible nested replies, with IDs preventing duplicate context.
                for reply in page:
                    for part in [reply, *(reply.replies or [])]:
                        if str(part.id) in seen or len(comments) >= comment_limit: continue
                        seen.add(str(part.id)); comments.append(post_record(part))
                cursor = getattr(page, 'next_cursor', None)
                if not cursor or cursor in cursors or len(comments) >= comment_limit: break
                cursors.add(cursor)
                page = await page.next()
        except Exception as exc:
            warning = error_message(exc)
        status = f'X 帖子详情可见回复，最多 {comment_limit} 条；已取得 {len(comments)} 条。不是全部评论，平台排序、隐藏及删除会影响结果。'
        if warning: status += ' 后续回复读取中断：' + warning
        content = {'source':'X 已登录帖子详情（Twikit）', 'author': record['author'],
                   'created_at': record['created'], 'comments': comments, 'comments_status': status,
                   'thread_status':'只保留平台返回的引用与线程上下文，未保证完整线程',
                   'warning':'评论为部分采集；线程只包含平台返回的上下文。'}
        video = record['video'] or any(r['video'] for r in context) or bool(tweet.quote and post_record(tweet.quote)['video'])
        content['has_video'] = video
        article = bool(getattr(tweet, '_data', {}).get('article'))
        content['article'] = article
        if article: content['warning'] += ' 帖子附带的 X Article 未验证全文，不能把帖子文字当成完整文章。'
        if video: content['warning'] += ' 视频仅保留原帖链接；按图文平台的处理范围，不下载或嵌入视频。'
        return {'title': record['author'] + '：' + (tweet.full_text or tweet.text)[:80],
                'body': body, 'content': content, 'collection': 'partial' if article else 'ready'}
    except Exception as exc:
        if seed:
            seed['content']['warning'] = error_message(exc) + ' 书签列表返回的原文已保留，详情不完整。'
            return seed
        raise ValueError(error_message(exc)) from None
    finally:
        await session.http.aclose()

async def bookmark_pages(cursor=None, folder_id=None):
    session = client()
    try:
        account = account_info(await session.user())
        seen_cursors = set()
        while True:
            page = await session.get_bookmarks(count=20, cursor=cursor, folder_id=folder_id)
            entries = [seed_record(tweet) for tweet in page]
            next_cursor = getattr(page, 'next_cursor', None)
            yield account, entries, next_cursor
            if not next_cursor: break
            if next_cursor in seen_cursors:
                raise ValueError('X 返回重复分页游标；已保留已取得的书签，停止以防循环。')
            seen_cursors.add(next_cursor); cursor = next_cursor
            # Every HTTP request, including details, shares the 8–12 second pace above.
    except Exception as exc:
        if isinstance(exc, ValueError): raise
        raise ValueError(error_message(exc)) from None
    finally:
        await session.http.aclose()

def favorites(record,progress,cancelled):
    """A synchronous generator keeps each committed page before requesting another."""
    loop=asyncio.new_event_loop()
    iterator=bookmark_pages(progress.get('next_cursor'))
    try:
        while True:
            if cancelled():raise ValueError('已停止 X 收藏读取；已保存内容保留，可继续')
            try:account,entries,cursor=loop.run_until_complete(anext(iterator))
            except StopAsyncIteration:return
            if progress.get('account_id') and progress['account_id']!=account['id']:
                raise ValueError('X 账号已变化，不能继续另一账号的收藏任务')
            progress.update(account_id=account['id'],account=account)
            for entry in entries:record(entry)
            progress.update(next_cursor=cursor,pages=progress.get('pages',0)+1,complete=not cursor,
                message='X 书签原文已保存；每次读取间隔 8–12 秒，图片与部分评论分别排队')
            yield progress
            if progress['complete']:return
    finally:
        loop.run_until_complete(iterator.aclose());loop.close()
