"""X official OAuth2 PKCE / bookmarks. No website scripting or password collection."""
from __future__ import annotations
import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode
import httpx
from . import store, sessions

PENDING = {}
REDIRECT = 'http://127.0.0.1:8766/oauth/x/callback'

def authorize():
    client_id=store.settings().get('x_client_id','')
    if not client_id: raise ValueError('X 官方授权需要开发者应用 Client ID；在「导入收藏 → X」填写后再连接。未配置时可以导入收藏清单，不默认使用网站脚本')
    state=secrets.token_urlsafe(32); verifier=secrets.token_urlsafe(48)
    PENDING[state]={'verifier':verifier,'created':time.time(),'client_id':client_id}
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    return 'https://x.com/i/oauth2/authorize?'+urlencode({'response_type':'code','client_id':client_id,
        'redirect_uri':REDIRECT,'scope':'tweet.read users.read bookmark.read offline.access',
        'state':state,'code_challenge':challenge,'code_challenge_method':'S256'})

def save_token(value):
    if not value.get('access_token'): raise ValueError('X 官方授权没有返回有效访问令牌')
    value['expires_at']=time.time()+value.get('expires_in',7200)
    value['cookies']=[]; value['origins']=[]
    path=sessions.path('x'); path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp'); temporary.write_bytes(sessions.protect(store.dumps(value).encode('utf-8')))
    temporary.replace(path)

def callback(code, state, error=''):
    pending=PENDING.pop(state,None)
    if not pending or time.time()-pending['created']>1800: raise ValueError('X 授权状态失效或不匹配，请重新打开官方授权窗口')
    if error: raise ValueError('X 授权未完成；没有保存登录状态')
    r=httpx.post('https://api.x.com/2/oauth2/token',data={'grant_type':'authorization_code','client_id':pending['client_id'],
                 'code':code,'redirect_uri':REDIRECT,'code_verifier':pending['verifier']},timeout=30)
    if r.status_code!=200: raise ValueError(f'X 官方令牌接口返回 HTTP {r.status_code}，请核对 Client ID、回调地址与应用权限')
    token=r.json(); token['client_id']=pending['client_id']; save_token(token)
    sessions.LOGIN['x']={'state':'saved','message':'X 官方授权已保存；收藏读取使用官方 API，不使用网页脚本'}
    with store.db() as c: store.event(c,None,'platform_session_saved',{'platform':'x','method':'official_oauth_pkce'})

def configured():
    return bool(sessions.load('x').get('access_token'))

def request(path, params=None):
    token=sessions.load('x')
    if not token.get('access_token'): raise ValueError('请先完成 X 官方授权；Cookie 登录不能代替官方 API 授权')
    if token.get('expires_at',0)<time.time()+60:
        if not token.get('refresh_token'): raise ValueError('X 授权已过期，请重新连接')
        r=httpx.post('https://api.x.com/2/oauth2/token',data={'grant_type':'refresh_token','refresh_token':token['refresh_token'],
            'client_id':token['client_id']},timeout=30)
        if r.status_code!=200: raise ValueError('X 官方授权刷新失败，请重新连接；不会循环重试')
        updated=r.json(); updated['client_id']=token['client_id']; updated.setdefault('refresh_token',token['refresh_token'])
        save_token(updated); token=updated
    r=httpx.get('https://api.x.com/2/'+path,params=params,headers={'Authorization':'Bearer '+token['access_token']},timeout=30)
    if r.status_code==429: raise ValueError('X 官方 API 限流，已停止；已导入材料保留，可稍后继续')
    if r.status_code in (401,403): raise ValueError('X 官方 API 拒绝访问；请核对授权、应用权限与 API 额度，已停止')
    if r.status_code!=200: raise ValueError(f'X 官方 API 返回 HTTP {r.status_code}；没有冒充成功')
    return r.json()

PARAMS={'tweet.fields':'created_at,author_id,attachments,note_tweet,referenced_tweets',
        'expansions':'attachments.media_keys,author_id', 'media.fields':'url,alt_text,type', 'user.fields':'username,name'}

def records(value):
    media={m['media_key']:m for m in value.get('includes',{}).get('media',[])}
    users={u['id']:u for u in value.get('includes',{}).get('users',[])}
    for post in value.get('data') or []:
        text=(post.get('note_tweet') or {}).get('text') or post.get('text','')
        for key in post.get('attachments',{}).get('media_keys',[]):
            m=media.get(key,{})
            if m.get('type')=='photo' and m.get('url'):
                alt=(m.get('alt_text') or '帖子图片').replace('[','').replace(']','').replace('\n',' ')
                text+='\n\n!['+alt+']('+m['url']+')'
        author='@'+users.get(post.get('author_id'),{}).get('username','未返回作者')
        yield {'url':'https://x.com/i/status/'+post['id'],'title':author+'：'+text[:80],'body':text,'collection':'ready',
               'content':{'source':'X 官方 API v2 原帖 / note_tweet 与图片','author':author,'created_at':post.get('created_at',''),
                          'comments':[], 'comments_status':'本次官方书签/帖子接口不返回评论；未获取评论，不代表没有评论。',
                          'warning':'保留该帖文字与 API 返回的图片；引用和完整线程未展开，视频仅保留原链接。'}}

def detail(url):
    import re
    match=re.search(r'/status/(\d+)',url)
    if not match: raise ValueError('需要具体 X 帖子链接')
    value=request('tweets/'+match[1],PARAMS)
    value['data']=[value.get('data',{})]
    return next(records(value))

def favorites(record, progress, cancelled):
    user=request('users/me').get('data') or {}
    if not user.get('id'): raise ValueError('X 官方接口未返回当前账号')
    if progress.get('account_id') and progress['account_id']!=user['id']: raise ValueError('X 账号已变化，请开始新的导入')
    progress['account_id']=user['id']
    cursor=progress.get('next_cursor')
    for _ in range(100):
        if cancelled(): raise ValueError('用户停止读取；已保存的收藏保留')
        params={**PARAMS,'max_results':100}
        if cursor: params['pagination_token']=cursor
        value=request('users/'+user['id']+'/bookmarks',params)
        for entry in records(value): record(entry)
        cursor=value.get('meta',{}).get('next_token')
        progress.update(next_cursor=cursor,complete=not cursor,message='X 官方书签页已入库，图文与图片排队存档')
        yield progress
        if not cursor:return
        time.sleep(5)
    raise ValueError('已达到单次 100 页上限；未完成的收藏可继续读取')
