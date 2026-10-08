"""Read ordinary official pages using only a project-owned, human-created session."""
from __future__ import annotations
import json
import re
import time
from urllib.parse import urlparse, parse_qs
from . import adapters, sessions, store

LINKS = {
    'bilibili': r'/video/(?:BV[\w]+|av\d+)',
    'youtube': r'(?:/watch\?[^#]*v=|/shorts/|/playlist\?[^#]*list=)',
    'douyin': r'(?:/video/\d+|modal_id=\d+)',
    'x': r'/status/\d+',
    'heybox': r'(?:/app/topic/link|/bbs/app/link|/link/|link_id=)',
    'xiaohongshu': r'/(?:explore|discovery/item)/[0-9a-f]+',
}

class PlatformAccessRequired(ValueError):
    """An actual visible verification or platform access restriction, never auto-solved."""

def content_link(kind, url):
    return adapters.platform(url) == kind and bool(re.search(LINKS[kind], url))

def safe_page(kind, url):
    if adapters.platform(url) != kind: raise ValueError('收藏页必须属于所选平台的官方网站')
    adapters.public_url(url)

def guarded(context,block_media=False):
    # Reject a redirect or page subrequest into the user's LAN. Never evade a challenge.
    def route(request_route):
        try:
            if block_media and request_route.request.resource_type=='media':
                request_route.abort();return
            url = request_route.request.url
            if url.startswith(('http://','https://')): adapters.public_url(url)
            request_route.continue_()
        except Exception: request_route.abort()
    context.route('**/*', route)

def blocked(page,verified_favorite_api=False):
    challenge=page.evaluate('''()=>Array.from(document.querySelectorAll('iframe[src*="captcha"], [role="dialog"]')).some(n=>{
      const r=n.getBoundingClientRect();if(r.width<10||r.height<10||r.bottom<0||r.right<0||r.top>=innerHeight||r.left>=innerWidth)return false;
      for(let p=n;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0)return false}
      return n.tagName==='IFRAME'||/安全验证|请完成验证|人机验证/.test(n.innerText||'')})''')
    if challenge:raise PlatformAccessRequired('平台要求验证码或安全验证，已停止；请在官方窗口本人完成后刷新登录状态，不自动绕过')
    text = page.locator('body').inner_text(timeout=10000)[:25000]
    if not verified_favorite_api and re.search(r'访问过于频繁|操作过于频繁|账号异常|账号被封|验证后继续|请完成安全验证|unusual traffic|Verify you are human|rate limit exceeded', text, re.I) and not page.locator('#page-bbs-link .hb-bbs-link__content').count():
        raise PlatformAccessRequired('平台要求验证、限流或限制了访问，已停止；请在官方登录窗口人工处理后再继续，不自动绕过验证')
    return text

def favorites(kind, url, record, progress, cancelled=lambda:False):
    """Persist each visible page before scrolling. A stalled list is never 'complete'."""
    from playwright.sync_api import sync_playwright
    safe_page(kind, url)
    if not sessions.path(kind).exists(): raise ValueError('请先连接或保存这个平台的Chrome登录状态')
    if kind=='x':
        if store.settings().get('x_read_mode','session')=='oauth':
            from . import xofficial
            yield from xofficial.favorites(record,progress,cancelled)
        else:
            backend=store.settings().get('x_read_backend','twitter-cli')
            if backend=='twitter-cli':
                from . import x_cli
                yield from x_cli.favorites(record,progress,cancelled)
            elif backend=='browser':
                from . import x_browser
                yield from x_browser.favorites(record,progress,cancelled)
            else:
                from . import xbookmarks
                yield from xbookmarks.favorites(record,progress,cancelled)
        return
    if kind == 'bilibili':
        yield from bili_favorites(record, progress, cancelled)
        return
    if kind=='heybox':
        yield from heybox_favorites(url,record,progress,cancelled)
        return
    with sync_playwright() as pw:
        b = sessions.browser(pw)
        try:
            context = b.new_context(storage_state=sessions.load(kind)); guarded(context)
            page = context.new_page()
            ends = []; returned = []
            unavailable = set(progress.get('unavailable_ids', []))
            def response(r):
                # Only favorite list responses can supply completion evidence.
                if kind == 'douyin' and urlparse(r.url).path != '/aweme/v1/web/aweme/listcollection/': return
                if not re.search(r'bookmark|favorite|favourite|favour|collect|saved', r.url, re.I): return
                if r.status in (401,403,429): ends.append('blocked'); return
                try:
                    data = r.json()
                    if kind == 'douyin':
                        if data.get('status_code', 0) != 0: ends.append('blocked'); return
                        for item in data.get('aweme_list') or []:
                            identifier = str(item.get('aweme_id', ''))
                            if identifier.isdigit(): returned.append({'url':'https://www.douyin.com/video/'+identifier, 'title':item.get('desc', '')})
                        for identifier in set(map(str, (data.get('disabled_item_ids') or [])+(data.get('invalid_item_id_list') or []))):
                            if identifier.isdigit():
                                unavailable.add(identifier)
                                returned.append({'url':'https://www.douyin.com/video/'+identifier, 'title':'平台标为失效或不可访问的收藏', 'unavailable':True})
                    def walk(value):
                        if isinstance(value, dict):
                            if value.get('has_more') is False or value.get('has_more') == 0:
                                if any(isinstance(value.get(k), list) for k in ('items','notes','aweme_list','list','medias')):
                                    ends.append('end')
                            for v in value.values(): walk(v)
                        elif isinstance(value, list):
                            for v in value: walk(v)
                    walk(data)
                except Exception: pass
            page.on('response', response)
            page.goto(url, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_timeout(2500)
            # A profile is not a favorites page until its visible favorites tab is selected.
            if kind in ('douyin', 'xiaohongshu'):
                tab = page.get_by_text('收藏', exact=True)
                if tab.count() != 1:
                    raise ValueError('无法唯一确认当前页面的收藏标签；停止读取，避免把发布内容或推荐流当成收藏。请在官方窗口打开自己的收藏页后重试')
                tab.click(timeout=10000); page.wait_for_timeout(2000)
                selected=tab.evaluate('(n)=>[n,n.parentElement,n.parentElement?.parentElement].filter(Boolean).some(x=>x.getAttribute("aria-selected")==="true"||/active|selected|chosen/i.test(x.className||""))')
                if not selected:
                    raise ValueError('尚未验证收藏标签被选中；未把其他帖子当成收藏导入。平台页面结构需重新适配')
            # Only scan the actual content list, excluding navigation and recommendation sidebars.
            selectors={'youtube':'ytd-two-column-browse-results-renderer, ytd-playlist-video-list-renderer',
                       'douyin':'[data-e2e="user-post-list"], [data-e2e="user-favorite-list"], .user-video-list',
                       'xiaohongshu':'.feeds-container', 'heybox':'.favour-list, .favorite-list, main'}
            lists=page.locator(selectors[kind])
            if not lists.count():
                raise ValueError('没有辨认出收藏内容列表，停止读取；不会从整个网页的推荐内容中导入假收藏')
            listing=lists.first
            seen = set(progress.get('seen_urls', [])); observed=set(); stale = 0; scroll_moving = False
            # A DOM resume begins at the top: previously imported cards are still scroll progress.
            # The safety budget grows by one batch so a previous cap doesn't trap every continuation.
            page_budget=max(180,int(progress.get('pages',0))+180)
            for number in range(page_budget):
                if cancelled(): raise ValueError('用户停止读取；已导入的材料保留，可继续去重读取')
                text = blocked(page)
                if 'blocked' in ends: raise ValueError('收藏接口拒绝访问或限流；已停止，已导入内容保留')
                entries = listing.locator('a[href]').evaluate_all('(nodes) => nodes.map(n=>({url:n.href,title:n.innerText||n.getAttribute("aria-label")||""}))')
                entries = returned[:] + entries; returned.clear()
                fresh = 0
                for entry in entries:
                    if not content_link(kind, entry['url']): continue
                    key = adapters.canonical(entry['url'])
                    first_observation=key not in observed
                    if first_observation:observed.add(key);fresh+=1
                    if not first_observation or key in seen and not progress.get('repair_incomplete'):continue
                    # YouTube's saved lists are expanded; raw playlist links aren't videos.
                    if kind == 'youtube' and '/playlist?' in entry['url']:
                        videos, limited = adapters.favorites(entry['url'])
                        for video in videos: record(video)
                        if limited: raise ValueError('播放列表超过单批 500 条；已保存前 500 条，本次未完整读取')
                    else: record(entry)
                    seen.add(key)
                progress.update(seen_urls=sorted(seen), pages=number+1, complete=False,
                                unavailable_ids=sorted(unavailable), unavailable=len(unavailable),
                                message='收藏链接已逐页保存；视频将自动提取字幕或本机转写')
                yield progress
                explicit = bool(re.search(r'没有更多了|没有更多内容|已加载全部|已到底|No more (?:posts|items|results)', text, re.I))
                if (explicit or 'end' in ends) and fresh==0 and number>0:
                    progress.update(complete=True, message='平台返回了列表末尾；已登记本次可访问条目'+(f'，另有 {len(unavailable)} 条失效或不可访问的收藏已保留链接与失败状态' if unavailable else ''))
                    yield progress
                    return
                stale = stale+1 if fresh == 0 and not scroll_moving else 0
                if stale >= 4:
                    raise ValueError('页面连续四次没有返回新的收藏，未验证到列表末尾；可能未登录、列表为空或页面结构变化。已保存读取结果，可重新登录后继续，不标成全部成功')
                page.evaluate('window.scrollBy(0, Math.max(innerHeight * .8, 500))')
                # Scroll the visible list container as well (Douyin/XHS use nested scrolling).
                scroll_moving = bool(listing.evaluate('(root)=>{const scroll=n=>{const before=n.scrollTop;n.scrollTop+=Math.max(n.clientHeight*.8,500);return n.scrollTop>before+1&&n.scrollTop+n.clientHeight<n.scrollHeight-2};for(let parent=root;parent;parent=parent.parentElement){const s=getComputedStyle(parent);if(["auto","scroll"].includes(s.overflowY)&&parent.scrollHeight>parent.clientHeight+100&&parent.clientHeight>200)return scroll(parent)}for(const n of root.querySelectorAll("main,section,div")){const s=getComputedStyle(n);if(["auto","scroll"].includes(s.overflowY)&&n.scrollHeight>n.clientHeight+100&&n.clientHeight>200)return scroll(n)}return false}'))
                page.wait_for_timeout(5000)
            raise ValueError('已达到本次收藏页读取的安全上限；已保存内容，仍未到达末尾，可继续读取')
        finally: b.close()

def heybox_favorites(url,record,progress,cancelled):
    """Consume normal website pagination responses, not a range of guessed IDs."""
    from playwright.sync_api import sync_playwright
    from .heybox_api import Feed,PATH
    with sync_playwright() as pw:
        with sessions.capture_session(pw,'heybox') as (context,page):
            guarded(page,block_media=True)
            feed=Feed();page.on('response',feed.response)
            page.goto(url,wait_until='domcontentloaded',timeout=60000);page.wait_for_timeout(2500)
            seen=set(progress.get('seen_urls',[]));observed=set();stalled=0;api_pages=0;fallback=False
            budget=max(180,int(progress.get('pages',0))+180)
            for _ in range(budget):
                if cancelled():raise ValueError('用户停止读取；已登记收藏保留')
                pages=feed.take()
                if feed.account:
                    previous=progress.get('account_fingerprint')
                    if previous and previous!=feed.account:raise ValueError('账号与上次断点不同，请开始新一轮核对')
                    progress['account_fingerprint']=feed.account
                for value in pages:
                    for entry in value['items']:
                        key=adapters.canonical(entry['url'])
                        if key in observed:continue
                        observed.add(key)
                        if key not in seen or progress.get('repair_incomplete'):record(entry)
                        seen.add(key)
                    api_pages+=1
                    progress.update(seen_urls=sorted(seen),pages=api_pages,complete=False,
                                    checkpoint={'offset':value['next_offset']},transport='heybox_favorites_api',
                                    endpoint=PATH,message='按收藏接口逐页登记，仅为新来源排队正文')
                    yield progress
                feed.raise_error()
                blocked(page,verified_favorite_api=bool(feed.account))
                if pages and pages[-1]['complete']:
                    progress.update(complete=True,message='收藏接口明确返回末尾，已登记本次可访问条目')
                    yield progress
                    return
                if pages and pages[-1]['short_page']:
                    # A short page alone is not proof; check the one returned next offset.
                    page.wait_for_timeout(6000)
                    if feed.error or feed.pages:continue
                    blocked(page,verified_favorite_api=bool(feed.account))
                    feed.verify_short_tail(context)
                    continue
                if pages:stalled=0
                else:stalled+=1
                if not feed.observed and stalled>=2:
                    # Compatibility is confined to the actual favourites container.
                    # Broad main-page/recommendation harvesting is never a fallback.
                    listing=page.locator('.favour-list, .favorite-list')
                    if not listing.count():raise ValueError('未取得小黑盒收藏接口响应；请刷新登录或等待接口适配，不从整页推荐中导入')
                    fallback=True
                    entries=listing.first.locator('a[href]').evaluate_all('(ns)=>ns.map(n=>({url:n.href,title:n.getAttribute("aria-label")||n.innerText||""}))')
                    fresh=0
                    for entry in entries:
                        if not content_link('heybox',entry['url']):continue
                        key=adapters.canonical(entry['url'])
                        if key in observed:continue
                        observed.add(key);fresh+=1
                        if key not in seen or progress.get('repair_incomplete'):record(entry)
                        seen.add(key)
                    progress.update(seen_urls=sorted(seen),complete=False,transport='heybox_compatibility_page',
                                    message='当前未取得收藏接口，仅登记专用收藏容器；未确认全部读取完成')
                    yield progress
                    if fresh:stalled=0
                if stalled>=4:raise ValueError('收藏接口未继续返回下一页，当前进度已保存，未宣称读完全部收藏')
                # Trigger the page's own signed next-page request; do not forge nonce or credentials.
                page.evaluate('window.scrollBy(0, Math.max(innerHeight * .8, 500))')
                if fallback or not pages:
                    page.locator('body').evaluate('(root)=>{for(const n of root.querySelectorAll("main,section,div")){const s=getComputedStyle(n);if(["auto","scroll"].includes(s.overflowY)&&n.scrollHeight>n.clientHeight+100&&n.clientHeight>200){n.scrollTop+=Math.max(n.clientHeight*.8,500);return}}}')
                page.wait_for_timeout(6000)
            raise ValueError('本批收藏接口分页达到上限，已保存断点；未确认全部读取完成')

def bili_folders():
    nav=adapters.bili_api('/x/web-interface/nav',{})
    if not nav.get('isLogin'):raise ValueError('B站登录已过期，请沿用当前Chrome账号重新连接')
    account=str(nav['mid'])
    data=adapters.bili_api('/x/v3/fav/folder/created/list-all',{'up_mid':account})
    folders=[{'id':str(value['id']),'title':str(value.get('title','未命名收藏夹')),'count':int(value.get('media_count',0))} for value in data.get('list') or []]
    return account,folders

def bili_favorites(record, progress, cancelled):
    account,folders=bili_folders()
    if progress.get('account_id') and progress['account_id'] != account:
        raise ValueError('账号已变化，不能继续另一个账号的收藏任务；请开始一次新的导入')
    progress['account_id'] = account
    selected=progress.get('folder_ids')
    previous=progress.get('selected_folders')
    if previous:
        frozen=[str(folder['id']) for folder in previous]
        if selected is not None and set(selected)!=set(frozen):raise ValueError('续读的收藏夹范围已变化，请开始一次新的导入')
        selected=frozen
    if selected is not None:
        by_id={folder['id']:folder for folder in folders}
        if not selected or set(selected)-set(by_id):raise ValueError('所选收藏夹不存在或已不可访问，请重新选择')
        # Checkpoint indices refer to this frozen order, not the next API listing order.
        folders=[by_id[identifier] for identifier in selected]
    progress['selected_folders']=[{'id':f['id'],'title':f['title']} for f in folders]
    checkpoint = progress.get('checkpoint', {})
    start_folder = checkpoint.get('folder', 0)
    for index, folder in enumerate(folders):
        if index < start_folder: continue
        page = checkpoint.get('page', 1) if index == start_folder else 1
        while True:
            if cancelled(): raise ValueError('用户停止读取；已导入材料保留')
            data = adapters.bili_api('/x/v3/fav/resource/list', {'media_id':folder['id'], 'pn':page, 'ps':20, 'platform':'web'})
            for entry in data.get('medias') or []:
                if not entry.get('bvid'): raise ValueError('收藏中存在已失效或未支持的条目；已登记的材料保留，本次未完整完成')
                record({'url':'https://www.bilibili.com/video/'+entry['bvid'],'title':entry.get('title',''),'favorite_folder':{'id':folder['id'],'title':folder['title']}})
            checkpoint = {'folder':index, 'page':page+1} if data.get('has_more') else {'folder':index+1, 'page':1}
            progress.update(checkpoint=checkpoint, complete=False, message='正在读取收藏夹：'+folder.get('title',''))
            yield progress
            if not data.get('has_more'): break
            page += 1; time.sleep(5)
        time.sleep(3)
    progress.update(complete=True, message=f'已读完账号可访问的 {len(folders)} 个收藏夹')
    yield progress

def text_material(url, folder):
    from playwright.sync_api import sync_playwright
    kind = adapters.platform(url); safe_page(kind, url)
    with sync_playwright() as pw:
        with sessions.capture_session(pw,kind) as (context,page):
            guarded(page,block_media=True)
            page.goto(url, wait_until='domcontentloaded', timeout=60000)
            if kind=='heybox':
                from . import heybox
                try:page.wait_for_function(r'''()=>{const nodes=document.querySelectorAll('#page-bbs-link .post__content,#page-bbs-link .image-text__content,.article-content,.bbs-content,.post-content,.link-content');return [...nodes].some(n=>{const t=(n.innerText||'').trim();return n.querySelector('img,video')||t.length>=8&&!/^(?:正在加载|加载中|loading)[.。…\s]*$/i.test(t)})||!!document.querySelector('#page-bbs-link .hb-bbs-video,#page-bbs-link .header-image__container img')}''',timeout=12000,polling=100)
                except Exception:
                    blocked(page)
                    raise ValueError('未取得小黑盒正文；页面加载或访问未完成，标题不算成功') from None
                blocked(page)
                from .video_pipeline import PROGRESS
                heybox.hydrate_images(page,blocked,PROGRESS.get())
                blocked(page)
                raw=page.content();(folder/'original.html').write_text(raw,'utf-8')
                return heybox.parse(raw,page.url,page.title().split(' - ')[0])
            page.wait_for_timeout(2500);blocked(page)
            selectors = {
                'xiaohongshu':['#detail-desc', '.note-content', '.content .desc'],
                'heybox':['.article-content', '.bbs-content', '.post-content', 'article', '.link-content'],
                'x':['article [data-testid="tweetText"]'],
            }
            node = None
            for selector in selectors[kind]:
                candidates = page.locator(selector)
                if candidates.count(): node = candidates.first; break
            if node is None: raise ValueError('没有辨认出帖子正文；可能需要登录或页面结构变化，未把导航/登录页面保存为正文')
            # Walk actual DOM in order so interleaved images stay in corresponding positions.
            body = node.evaluate('''(root)=>{let out="";function walk(n){if(n.nodeType===3){out+=n.textContent;return}if(n.nodeType!==1)return;if(["SCRIPT","STYLE","VIDEO","SOURCE","IFRAME"].includes(n.tagName))return;if(n.tagName==="IMG"){const u=n.currentSrc||n.src;if(u.startsWith("http"))out+="\\n\\n![帖子图片]("+u+")\\n\\n";return}if(n.tagName==="BR")out+="\\n";for(const c of n.childNodes)walk(c);if(["P","DIV","LI","H1","H2","H3"].includes(n.tagName))out+="\\n"}walk(root);return out.trim()}''')
            if len(body.strip()) < 20: raise ValueError('未取得足够的正文，不能标为成功')
            # XHS's image carousel is adjacent to text, not a child of the description.
            if kind == 'xiaohongshu':
                pictures = page.locator('.note-slider img, .swiper-slide img').evaluate_all('(ns)=>ns.map(n=>n.currentSrc||n.src)')
                for image in dict.fromkeys(pictures):
                    if image.startswith('http') and image not in body: body += '\n\n![帖子图片]('+image+')'
            title = page.title().split(' - ')[0]
            comments = []
            for comment in page.locator('.comment-item, .comment-container .parent-comment').all()[:20]:
                text = comment.inner_text()
                if text.strip(): comments.append({'author':'网页显示的评论（见原文）','body':text,'url':url})
            (folder/'original.html').write_text(page.content(), 'utf-8')
            partial = bool(re.search(r'展开全文|登录后查看全文|阅读全文', body))
            return {'title':title, 'body':body, 'collection':'partial' if partial else 'ready',
                    'content':{'source':'官方网页可辨认的帖子正文与图片（本机浏览器）','resolved_url':page.url,
                               'original_text_complete':not partial,
                               'comments':comments, 'comments_status':f'只读取页面当前已加载的前 {len(comments)} 条可辨认评论，未读取全部评论。',
                               'warning':'只保存实际可见的图文；视频留在原链接。展开/隐藏内容和评论范围请对照原页核查。'}}

def douyin_info(url):
    """Read metadata/media actually returned to the official page, without signature generation."""
    from playwright.sync_api import sync_playwright
    wanted=adapters.canonical(url).rsplit('/',1)[-1]
    captured=[]; denied=[]
    with sync_playwright() as pw:
        b=sessions.browser(pw)
        try:
            context=b.new_context(storage_state=sessions.load('douyin')); guarded(context)
            page=context.new_page()
            def response(r):
                if 'douyin.com' not in (urlparse(r.url).hostname or ''): return
                if not re.search(r'aweme|detail|video',r.url): return
                if r.status in (401,403,429): denied.append(r.status); return
                try:
                    data=r.json()
                    def walk(value):
                        if isinstance(value,dict):
                            if str(value.get('aweme_id',''))==wanted and isinstance(value.get('video'),dict):
                                captured.append(value); return
                            for v in value.values(): walk(v)
                        elif isinstance(value,list):
                            for v in value: walk(v)
                    walk(data)
                except Exception: pass
            page.on('response',response)
            page.goto(adapters.canonical(url),wait_until='domcontentloaded',timeout=60000)
            for _ in range(6):
                page.wait_for_timeout(1500)
                blocked(page)
                if denied: raise ValueError('抖音视频接口拒绝访问或限流；已停止，请在官方窗口正常登录后重试')
                if captured: return captured[0]
            # Ordinary browser media properties are usable when platform JSON is unavailable.
            media=page.locator('video')
            if media.count():
                data=media.first.evaluate('(v)=>({url:v.currentSrc,duration:v.duration,cover:v.poster})')
                if data.get('url','').startswith('http') and isinstance(data.get('duration'),(int,float)):
                    description=page.locator('[data-e2e="video-desc"]').first
                    return {'aweme_id':wanted,'desc':description.inner_text() if description.count() else page.title(),
                            'video':{'duration':data['duration']*1000,'play_addr':{'url_list':[data['url']]},
                                     'cover':{'url_list':[data['cover']] if data.get('cover') else []}}}
            raise ValueError('抖音官方页面没有返回可用媒体；可能需要登录或该视频受限。没有把分享页缺少数据说成视频已删除；请保存抖音登录状态后重试')
        finally: b.close()
