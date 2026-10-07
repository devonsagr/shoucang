"""Agent-Reach's current twitter-cli backend, confined to our explicit X session.

Only use its Python reader, never its CLI authentication/browser-cookie discovery.
All request pacing, cancellation, snapshots and stop-on-block behavior are ours.
"""
from __future__ import annotations
import random
import hashlib
import re
import threading
import time
from urllib.parse import unquote,urlparse
from . import store,sessions,xbookmarks,x_browser,adapters

HTTP_LOCK=threading.Lock()
READER=None
READER_KEY=''

class ReadTransport:
    def __init__(self,raw,cancelled):self.raw=raw;self.cancelled=cancelled
    def post(self,*args,**kwargs):raise ValueError('X 收藏通道不执行写请求')
    def get(self,url,**kwargs):
        if urlparse(url).hostname not in ('x.com','twitter.com','abs.twimg.com','raw.githubusercontent.com'):
            raise ValueError('X 读取器拒绝向未知网站发送请求')
        with HTTP_LOCK:
            if self.cancelled() or xbookmarks.blocked_reason():raise ValueError('X 读取已停止；已保存结果保留')
            with xbookmarks.REQUEST_LOCK:
                delay=xbookmarks.reserve_delay()
            if delay:time.sleep(delay)
            if self.cancelled() or xbookmarks.blocked_reason():raise ValueError('X 读取已停止；已保存结果保留')
            result=self.raw.get(url,**kwargs)
            if result.status_code in (401,403,429):
                message=f'X 返回 HTTP {result.status_code}，已停止全部 X 读取；原文保留，请人工检查账号后再继续。'
                xbookmarks.block(message);raise ValueError(message)
            if '/i/api/' in urlparse(url).path:
                try:errors=result.json().get('errors',[])
                except Exception:errors=[]
                if any(e.get('code') in (32,64,88,89,326) for e in errors):
                    xbookmarks.block('X 会话受限、过期或触发限流，已停止全部 X 读取；请人工检查后再继续。')
                    raise ValueError(xbookmarks.blocked_reason())
            return result

def client(cancelled=lambda:False):
    # Importing this module does not call twitter_cli.auth or browser_cookie3.
    import twitter_cli.client as upstream
    global READER,READER_KEY
    cookies=sessions.cookie_values('x');xbookmarks.read_cookies()
    header='; '.join(name+'='+value for name,value in cookies.items() if not any(c in name+value for c in '\r\n;'))
    key=hashlib.sha256(header.encode()).hexdigest()
    if READER is not None and key==READER_KEY:
        upstream._cffi_session.cancelled=cancelled
        return READER
    raw=upstream._get_cffi_session()
    if isinstance(raw,ReadTransport):raw=raw.raw
    upstream._cffi_session=ReadTransport(raw,cancelled)
    class Reader(upstream.TwitterClient):
        @staticmethod
        def _ct_cache_path():return str(store.DATA/'x-cli/transaction_cache.json')
        def _api_request(self,url,method='GET',body=None):
            if method!='GET':raise ValueError('X 收藏通道不执行写请求')
            return super()._api_request(url,method,body)
    READER=Reader(cookies['auth_token'],cookies['ct0'],rate_limit_config={'requestDelay':0,'maxRetries':0,'maxCount':20},cookie_string=header)
    READER_KEY=key
    return READER

def favorites(record_entry,progress,cancelled):
    reader=client(cancelled)
    twid=unquote(sessions.cookie_values('x').get('twid','')).strip('"')
    account=re.fullmatch(r'u=(\d+)',twid)
    if not account:raise ValueError('无法核对 X 当前账号；未使用其他账号继续旧收藏任务')
    account_id=account[1]
    if progress.get('account_id') and progress['account_id']!=account_id:raise ValueError('X 账号已变化，不能续读另一账号的书签')
    from twitter_cli.graphql import FEATURES
    folder=store.DATA/'x-captures'/store.uid();folder.mkdir(parents=True,exist_ok=True)
    cursor=progress.get('next_cursor');seen_cursors=set()
    while True:
        if cancelled():raise ValueError('用户停止 X 读取；已保存结果保留，可继续')
        variables={'count':20,'includePromotedContent':False,'requestContext':'launch'}
        if cursor:variables['cursor']=cursor
        value=reader._graphql_get('Bookmarks',variables,FEATURES)
        timeline=value.get('data',{}).get('bookmark_timeline_v2') or value.get('data',{}).get('bookmark_timeline')
        if not timeline:raise ValueError('X 未返回可辨认的私人书签列表；没有把未知响应当成空收藏')
        entries=list(x_browser.tweets(timeline))
        n=progress.get('pages',0)+1
        (folder/f'page-{n}.json').write_text(store.dumps(value),'utf-8')
        for tweet in entries:
            entry=x_browser.record(tweet)
            entry['content']['source']='X 私人书签原文（twitter-cli 登录会话读取，非付费开发者 API）'
            record_entry(entry)
        next_cursor=next((node.get('value') for node in x_browser.nodes(timeline) if node.get('cursorType')=='Bottom'),None)
        terminal=any(node.get('type')=='TimelineTerminateTimeline' for node in x_browser.nodes(timeline))
        complete=terminal or not next_cursor
        # A successful empty timeline at an unchanged cursor is the platform's terminal page.
        if next_cursor==cursor and not entries:complete=True
        if next_cursor in seen_cursors and not complete:raise ValueError('X 返回重复游标但仍有帖子，停止以防遗漏或循环；已保存原文')
        progress.update(account_id=account_id,next_cursor=next_cursor,pages=n,backend='twitter-cli',complete=complete,
                        message='书签原文逐页保存；每次请求间隔 8–12 秒，图片和首次加载的部分回复随后处理')
        yield progress
        if complete:return
        seen_cursors.add(next_cursor);cursor=next_cursor

def detail(url,seed=None):
    reader=client();tid=adapters.canonical(url).rsplit('/',1)[-1]
    from twitter_cli.graphql import FEATURES
    try:
        data=reader._graphql_get('TweetDetail',{'focalTweetId':tid,'with_rux_injections':False,
            'includePromotedContent':False,'withCommunity':False,'withQuickPromoteEligibilityTweetFields':False,
            'withBirdwatchNotes':True,'withVoice':True,'withV2Timeline':True},FEATURES,
            field_toggles={'withArticleRichContentState':True,'withArticlePlainText':False})
        results=list(x_browser.tweets(data))
        target=next((t for t in results if str(t.get('rest_id'))==tid),None)
        if not target:raise ValueError('X 详情没有目标帖，原文保留；不会使用推荐帖子替代')
        result=x_browser.record(target);comments=[]
        for tweet in results:
            legacy=tweet.get('legacy',{})
            if str(tweet.get('rest_id'))==tid or str(legacy.get('conversation_id_str'))!=tid:continue
            reply=x_browser.record(tweet)
            comments.append({'body':reply['body'],'author':reply['content']['author'],'url':reply['url'],'created':legacy.get('created_at','')})
            if len(comments)>=20:break
        result['content'].update(source='X 已登录帖子详情（twitter-cli，非付费开发者 API）',comments=comments,
            comments_status=f'平台首次返回的可见回复，取得 {len(comments)} 条；未继续展开，不是全部评论。',
            warning='评论是首次返回的可见部分。'+(' X Article 尚未取得全文。' if result['content']['article'] and not result['content']['article_complete'] else '')+(' 视频仅留原链接。' if result['content']['has_video'] else ''))
        result['collection']='partial' if not result['content']['original_text_complete'] else 'ready'
        result['content']['original_response']=data
        return result
    except Exception as exc:
        if seed:
            seed['content']['comments_status']='回复读取失败；未把失败当成没有评论。'
            seed['content']['warning']='详情读取未完成；已保留书签原文。'+xbookmarks.error_message(exc)
            return seed
        raise
