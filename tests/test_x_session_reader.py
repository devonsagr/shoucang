import json
from types import SimpleNamespace
import pytest
from app import store,sessions,x_cli,x_browser,xbookmarks,service
from test_library_revision import local,material

def tweet(text='原文 https://t.co/photo 后文',**extra):
    return {'rest_id':'12345678','legacy':{'full_text':text,'extended_entities':{'media':[
        {'type':'photo','url':'https://t.co/photo','media_url_https':'https://pbs.twimg.com/a.jpg'},
        {'type':'video','media_url_https':'https://pbs.twimg.com/cover.jpg'}]}},
        'core':{'user_results':{'result':{'core':{'screen_name':'fixture'}}}},**extra}

def test_saved_bookmark_text_photo_order_and_video_link_only():
    result=x_browser.record(tweet())
    assert result['body'].index('原文')<result['body'].index('![帖子图片]')<result['body'].index('后文')
    assert 'cover.jpg' not in result['body'] and result['content']['has_video']
    assert '![' not in result['title'] and 't.co/photo' not in result['title']
    assert result['collection']=='ready' and result['content']['comments_status']=='尚未读取回复'
    value=tweet();value['legacy']['truncated']=True
    assert x_browser.record(value)['collection']=='partial'
    value['note_tweet']={'note_tweet_results':{'result':{'text':'完整长文'}}}
    assert x_browser.record(value)['body'].startswith('完整长文')
    assert x_browser.record(value)['content']['original_text_complete']

def test_article_summary_is_not_full_article(monkeypatch):
    import twitter_cli.parser
    value=tweet(article={'article_results':{'result':{'title':'文章'}}})
    monkeypatch.setattr(twitter_cli.parser,'parse_tweet_result',lambda _:SimpleNamespace(article_text='',article_title='文章'))
    assert x_browser.record(value)['collection']=='partial'
    monkeypatch.setattr(twitter_cli.parser,'parse_tweet_result',lambda _:SimpleNamespace(article_text='实际文章全文',article_title='文章'))
    result=x_browser.record(value)
    assert result['collection']=='ready' and '实际文章全文' in result['body']

@pytest.mark.parametrize('repair',[False,True])
def test_browser_resume_only_revisits_seen_sources_in_explicit_repair_mode(local,monkeypatch,repair):
    from contextlib import contextmanager
    import playwright.sync_api
    class Page:
        url='https://x.com/i/bookmarks'
        def goto(self,*a,**kw):pass
        def wait_for_timeout(self,ms):pass
        def title(self):return '书签夹具'
        def locator(self,_):return SimpleNamespace(inner_text=lambda **kw:'书签')
        def close(self):pass
    @contextmanager
    def runtime():yield None
    def reader(pw,received,cancelled):
        received.append(('/Bookmarks',{}))
        return SimpleNamespace(close=lambda:None),Page(),[],[]
    monkeypatch.setattr(playwright.sync_api,'sync_playwright',runtime)
    monkeypatch.setattr(x_browser,'reader',reader);monkeypatch.setattr(x_browser,'guard',lambda *a:None)
    monkeypatch.setattr(x_browser,'tweets',lambda _:[tweet(),tweet()])
    monkeypatch.setattr(x_browser,'nodes',lambda _:[{'instructions':[],'type':'TimelineTerminateTimeline','direction':'Bottom'}])
    progress={'seen_urls':[x_browser.record(tweet())['url']],'repair_incomplete':repair};entries=[]
    list(x_browser.favorites(entries.append,progress,lambda:False))
    assert len(entries)==int(repair) and progress['complete']

def test_transport_never_writes_and_auth_limit_stops_without_retry(local,monkeypatch):
    client,_=local;mid=material(client,'https://x.com/i/status/12345678',text='')
    calls=[]
    raw=SimpleNamespace(get=lambda url,**kw:(calls.append(url) or SimpleNamespace(status_code=200,json=lambda:{'errors':[{'code':88}]})))
    transport=x_cli.ReadTransport(raw,lambda:False)
    monkeypatch.setattr(xbookmarks,'reserve_delay',lambda:0)
    with pytest.raises(ValueError,match='写请求'):transport.post('https://x.com/i/api/write')
    with pytest.raises(ValueError,match='未知网站'):transport.get('https://unknown.example/i/api/Bookmarks')
    with pytest.raises(ValueError,match='限流'):transport.get('https://x.com/i/api/Bookmarks')
    with pytest.raises(ValueError,match='停止'):transport.get('https://x.com/i/api/Bookmarks')
    assert len(calls)==1 and store.get(mid)['collection']=='paused'

def test_pacing_survives_a_new_reader_process(local,monkeypatch):
    monkeypatch.setattr(xbookmarks,'NEXT_REQUEST',0)
    monkeypatch.setattr(xbookmarks.time,'monotonic',lambda:100)
    monkeypatch.setattr(xbookmarks.time,'time',lambda:1000)
    monkeypatch.setattr(xbookmarks.random,'uniform',lambda *_:10)
    assert xbookmarks.reserve_delay()==0
    monkeypatch.setattr(xbookmarks,'NEXT_REQUEST',0)
    assert xbookmarks.reserve_delay()==10

def test_reader_reuses_only_explicit_project_session(local,monkeypatch):
    import twitter_cli.client as upstream
    calls=[]
    monkeypatch.setattr(x_cli,'READER',None)
    monkeypatch.setattr(x_cli,'READER_KEY','')
    monkeypatch.setattr(sessions,'cookie_values',lambda _:dict(auth_token='fixture',ct0='fixture'))
    monkeypatch.setattr(xbookmarks,'read_cookies',lambda:dict(auth_token='fixture',ct0='fixture'))
    monkeypatch.setattr(upstream,'_get_cffi_session',lambda:SimpleNamespace())
    monkeypatch.setattr(upstream,'_cffi_session',None)
    monkeypatch.setattr(upstream.TwitterClient,'__init__',lambda self,*args,**kwargs:calls.append(kwargs))
    first=x_cli.client();second=x_cli.client()
    assert first is second and len(calls)==1
    assert calls[0]['rate_limit_config']['maxRetries']==0
    assert 'fixture' in calls[0]['cookie_string']
    assert first._ct_cache_path().startswith(str(store.DATA))

def test_background_enrichment_keeps_finished_material_out_of_pending(local):
    client,_=local;mid=material(client,'https://x.com/i/status/12345678')
    with store.db() as c:c.execute("UPDATE materials SET processing='done',notes='已读后的理解' WHERE id=?",(mid,))
    service.save_content(mid,{'title':'原文与部分回复','body':'保存的原文','content':{},'collection':'ready'},preserve_processing=True)
    item=store.get(mid)
    assert item['processing']=='done' and item['notes']=='已读后的理解'
    assert not client.get('/api/materials?platform=x&state=pending').json()['items']
