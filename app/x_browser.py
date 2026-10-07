"""Read X pages in the project's own saved session; keep actual bookmark responses.

No profile discovery, password entry, write operations or challenge bypass.
The website supplies its own current request parameters instead of stale query IDs.
"""
from __future__ import annotations
import json
import html
import random
import re
import time
from urllib.parse import urlparse
from . import adapters, sessions, store, xbookmarks

def nodes(value):
    if isinstance(value,dict):
        yield value
        for child in value.values():yield from nodes(child)
    elif isinstance(value,list):
        for child in value:yield from nodes(child)

def tweets(payload):
    seen=set()
    for node in nodes(payload):
        result=(node.get('tweet_results') or {}).get('result')
        if not isinstance(result,dict):continue
        result=result.get('tweet',result)
        tid=str(result.get('rest_id') or result.get('legacy',{}).get('id_str') or '')
        if tid and tid not in seen and result.get('legacy'):
            seen.add(tid);yield result

def record(tweet):
    legacy=tweet.get('legacy',{})
    note=tweet.get('note_tweet',{}).get('note_tweet_results',{}).get('result',{})
    user=tweet.get('core',{}).get('user_results',{}).get('result',{})
    author='@'+(user.get('core',{}).get('screen_name') or user.get('legacy',{}).get('screen_name') or '未署名')
    text=html.unescape(note.get('text') or legacy.get('full_text') or legacy.get('text') or '')
    headline=text
    for media in legacy.get('extended_entities',{}).get('media',[]):
        if media.get('url'):headline=headline.replace(media['url'],'')
    headline=re.sub(r'\s+',' ',headline).strip()
    entities=note.get('entity_set') or legacy.get('entities') or {}
    for link in entities.get('urls',[]):
        if link.get('url') and link.get('expanded_url'):text=text.replace(link['url'],link['expanded_url'])
    pictures=[];video=False
    for media in legacy.get('extended_entities',{}).get('media',[]):
        video|=media.get('type') in ('video','animated_gif')
        if media.get('type')!='photo' or not media.get('media_url_https'):continue
        alt=(media.get('ext_alt_text') or '帖子图片').replace('[','').replace(']','').replace('\n',' ')
        image=f'![{alt}]({media["media_url_https"]})'
        if media.get('url') and media['url'] in text:text=text.replace(media['url'],image,1)
        else:pictures.append(image)
    body=text
    if pictures:body+='\n\n'+'\n\n'.join(pictures)
    quoted=tweet.get('quoted_status_result',{}).get('result');quote_complete=True
    if quoted:
        quote=record({k:v for k,v in quoted.get('tweet',quoted).items() if k!='quoted_status_result'})
        quote_complete=quote['content']['original_text_complete']
        body+='\n\n### 引用帖子\n\n'+quote['content']['author']+'\n\n'+quote['body']+'\n\n来源：'+quote['url']
    tid=str(tweet.get('rest_id') or legacy.get('id_str'))
    article=tweet.get('article',{}).get('article_results',{}).get('result')
    article_complete=False
    if article:
        from twitter_cli.parser import parse_tweet_result
        parsed=parse_tweet_result(tweet)
        if parsed and parsed.article_text:
            body+='\n\n## '+(parsed.article_title or 'X Article')+'\n\n'+parsed.article_text
            article_complete=True
    text_complete=quote_complete and not (legacy.get('truncated') and not note.get('text')) and not (article and not article_complete)
    warning='原文来自自己的书签列表；评论尚未读取。'
    if legacy.get('truncated') and not note.get('text'):warning+=' 平台返回了截断帖文，尚未取得完整原文。'
    if article and not article_complete:warning+=' 附带 X Article，尚未验证完整文章正文，不能把帖文摘要当成全文。'
    if not quote_complete:warning+=' 引用材料尚未取得完整原文。'
    if video:warning+=' 视频只保留原帖链接。'
    return {'url':f'https://x.com/i/status/{tid}','title':author+'：'+(headline[:80] or '收藏图片'),'body':body,
            'content':{'source':'X 已登录网页实际返回的书签原文','author':author,'created_at':legacy.get('created_at',''),
                       'comments':[],'comments_status':'尚未读取回复','has_video':video,'article':bool(article),
                       'article_complete':article_complete,'original_text_complete':text_complete,
                       'warning':warning},'collection':'ready' if text_complete else 'partial'}

def reader(pw,received,cancelled=lambda:False):
    browser,context,_=sessions.login_browser(pw,'x')
    page=context.new_page()
    errors=[]
    paths=[]
    def route(r):
        request=r.request;url=request.url;path=urlparse(url).path
        if '/i/api/' in path and len(paths)<100:paths.append(request.method+' '+path)
        if request.method not in ('GET','HEAD','OPTIONS'):
            r.abort();return
        try:
            if url.startswith(('http://','https://')):adapters.public_url(url)
            if '/i/api/' in path:
                if cancelled() or xbookmarks.blocked_reason():raise ValueError('X 读取已停止')
                with xbookmarks.REQUEST_LOCK:
                    delay=xbookmarks.reserve_delay()
                if delay:time.sleep(delay)
                if cancelled() or xbookmarks.blocked_reason():raise ValueError('X 读取已停止')
            r.continue_()
        except Exception:r.abort()
    page.route('**/*',route)
    def response(r):
        path=urlparse(r.url).path
        if '/i/api/' not in path:return
        if r.status in (401,403,429):
            error=f'X 返回 HTTP {r.status}，已停止读取；已保存原文保留，请人工检查账号后再继续。'
            xbookmarks.block(error);errors.append(error);return
        if '/Bookmarks' not in path and '/TweetDetail' not in path:return
        try:
            value=r.json()
            if value.get('errors'):
                errors.append('X 网页返回了读取错误，未把错误响应当成空书签');return
            received.append((path,value))
        except Exception:errors.append('X 返回的收藏数据无法解析，未标成成功')
    page.on('response',response)
    return browser,page,errors,paths

def guard(page,errors):
    if errors:raise ValueError(errors[0])
    if xbookmarks.blocked_reason():raise ValueError(xbookmarks.blocked_reason())
    text=page.locator('body').inner_text(timeout=15000)[:25000]
    if re.search(r'Verify you are human|验证后继续|请完成安全验证|账号已锁定|account (?:is )?locked|unusual activity',text,re.I):
        xbookmarks.block('X 要求账号验证，已停止；请在普通 Chrome 窗口人工处理后再继续')
        raise ValueError(xbookmarks.blocked_reason())

def favorites(record_entry,progress,cancelled):
    from playwright.sync_api import sync_playwright
    received=[];seen=set(progress.get('seen_urls',[]));stale=0
    folder=store.DATA/'x-captures'/store.uid();folder.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser,page,errors,paths=reader(pw,received,cancelled)
        try:
            page.goto('https://x.com/i/bookmarks',wait_until='domcontentloaded',timeout=120000)
            for cycle in range(max(1000,int(progress.get('pages',0))+1000)):
                if cancelled():raise ValueError('用户停止 X 读取；已保存内容保留，可继续')
                page.wait_for_timeout(3000)
                (folder/'read-diagnostic.json').write_text(store.dumps({'request_paths':paths,'page_url':page.url,
                    'page_title':page.title(),'page_text':page.locator('body').inner_text(timeout=5000)[:2500]}),'utf-8')
                guard(page,errors)
                payloads=[value for path,value in received if '/Bookmarks' in path];received.clear()
                for value in payloads:
                    results=list(tweets(value))
                    if not any('instructions' in node for node in nodes(value)):
                        raise ValueError('无法识别 X 书签列表结构；没有导入推荐流或把未知响应标成成功')
                    for tweet in results:
                        entry=record(tweet)
                        if entry['url'] in seen:continue
                        record_entry(entry);seen.add(entry['url'])
                    n=progress.get('pages',0)+1
                    (folder/f'page-{n}.json').write_text(store.dumps(value),'utf-8')
                    cursor=next((node.get('value') for node in nodes(value) if node.get('cursorType')=='Bottom'),None)
                    terminal=any(node.get('type')=='TimelineTerminateTimeline' and node.get('direction') in ('Bottom','Both') for node in nodes(value))
                    progress.update(pages=n,seen_urls=sorted(seen),next_cursor=cursor,backend='browser',
                                    complete=terminal or not results,
                                    message='使用保存的 Chrome 登录会话读取自己的书签；图文原文先保存，图片与部分评论分别排队')
                    yield progress
                    if progress['complete']:return
                stale=0 if payloads else stale+1
                if stale>=8:
                    (folder/'read-diagnostic.json').write_text(store.dumps({'request_paths':paths,'page_text':page.locator('body').inner_text()[:2500]}),'utf-8')
                    raise ValueError('X 页面没有继续返回书签，尚未验证末尾；已保存结果保留，可继续读取')
                page.evaluate('window.scrollTo(0,document.body.scrollHeight)')
                page.wait_for_timeout(random.uniform(8000,12000))
            raise ValueError('已达到本次低速读取上限；已保存结果保留，尚未确认末尾，可继续')
        finally:
            page.close();browser.close()

def detail(url,seed=None):
    from playwright.sync_api import sync_playwright
    tid=url.rstrip('/').split('/')[-1].split('?')[0]
    received=[]
    try:
        with sync_playwright() as pw:
            browser,page,errors,paths=reader(pw,received)
            try:
                page.goto(url,wait_until='domcontentloaded',timeout=120000)
                for _ in range(12):
                    page.wait_for_timeout(2000);guard(page,errors)
                    values=[value for path,value in received if '/TweetDetail' in path]
                    if values:break
                else:raise ValueError('X 没有返回可解析的帖子详情，已保留书签原文')
                all_tweets=[tweet for value in values for tweet in tweets(value)]
                target=next((tweet for tweet in all_tweets if str(tweet.get('rest_id'))==tid),None)
                if not target:raise ValueError('X 返回的详情没有目标帖子；未用推荐帖替代原文')
                result=record(target);comments=[]
                for tweet in all_tweets:
                    legacy=tweet.get('legacy',{})
                    if str(tweet.get('rest_id'))==tid or str(legacy.get('conversation_id_str'))!=tid:continue
                    reply=record(tweet)
                    comments.append({'id':tweet.get('rest_id'),'body':reply['body'],'author':reply['content']['author'],'url':reply['url'],'created':legacy.get('created_at','')})
                    if len(comments)>=20:break
                result['content'].update(source='X 已登录网页实际返回的帖子详情',comments=comments,
                    comments_status=f'首次加载的可见回复，已保存 {len(comments)} 条；未展开更多，不是全部评论。',
                    warning='评论仅为首次加载的可见部分。'+(' X Article 正文未验证完整。' if result['content']['article'] else '')+(' 视频只保留原帖链接。' if result['content']['has_video'] else ''))
                result['collection']='partial' if result['content']['article'] else 'ready'
                return result
            finally:
                page.close();browser.close()
    except Exception as exc:
        if seed:
            seed['content']['warning']='详情未完成：'+str(exc)[:300]+'；书签列表返回的原文保留。'
            return seed
        raise
