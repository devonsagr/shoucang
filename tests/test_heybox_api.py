from types import SimpleNamespace
from urllib.parse import parse_qs,urlparse
import pytest
from app import adapters,heybox_api,platform_browser,sessions
from test_automatic_collection import local

def address(offset=0,**values):
    from urllib.parse import urlencode
    return 'https://api.xiaoheihe.cn/bbs/web/profile/favours?'+urlencode({'userid':'111','heybox_id':'111','offset':offset,'limit':2,'hkey':'private-fixture-signature','nonce':'private-fixture-nonce',**values})

def response(offset,items,**metadata):
    return SimpleNamespace(url=address(offset),status=200,request=SimpleNamespace(method='GET'),
                           json=lambda:{'status':'ok','result':{'links':items,**metadata}})

def test_only_actual_favourites_endpoint_and_stable_returned_ids_are_read():
    payload={'status':'ok','result':{'links':[{'linkid':'97001','title':'准确标题','description':'列表只有摘要，不能当原文'},{'link':{'linkid':'97002','title':'图片帖子'}}]}}
    parsed=heybox_api.parse(address(),200,payload)
    assert [x['remote_id'] for x in parsed['items']]==['97001','97002']
    assert parsed['items'][0]['title']=='准确标题' and not any('body' in x for x in parsed['items'])
    assert parsed['next_offset']==2 and not parsed['complete']
    assert '111' not in parsed['account_fingerprint'] and 'private-fixture-' not in str(parsed)
    assert heybox_api.parse('https://api.xiaoheihe.cn/bbs/app/feeds',200,payload) is None
    assert heybox_api.parse('https://other.example.org/bbs/web/profile/favours',200,payload) is None

def test_cursor_pages_dedupe_and_explicit_empty_tail():
    feed=heybox_api.Feed()
    feed.response(response(0,[{'linkid':97001},{'linkid':97002}]))
    feed.response(response(0,[{'linkid':97001},{'linkid':97002}]))
    assert len(feed.take())==1
    feed.response(response(2,[{'linkid':97003}]))
    page=feed.take()[0];assert page['short_page'] and not page['complete']
    feed.response(response(3,[]));assert feed.take()[0]['complete']

def test_short_tail_verification_reuses_one_scoped_read_not_guessed_ids(monkeypatch):
    feed=heybox_api.Feed();feed.response(response(0,[{'linkid':97001}]))
    feed.take();calls=[]
    def get(url,**kwargs):
        calls.append((url,kwargs));return SimpleNamespace(url=url,status=200,json=lambda:{'status':'ok','result':{'links':[]}})
    monkeypatch.setattr(adapters,'public_url',lambda _:None)
    feed.verify_short_tail(SimpleNamespace(request=SimpleNamespace(get=get)))
    feed.verify_short_tail(SimpleNamespace(request=SimpleNamespace(get=get)))
    assert len(calls)==1 and parse_qs(urlparse(calls[0][0]).query)['offset']==['1']
    assert calls[0][1]['max_redirects']==0 and 'private-fixture-signature' in calls[0][0]
    assert feed.take()[0]['complete']

def test_malformed_rows_or_pagination_gap_stop_without_silent_loss():
    with pytest.raises(ValueError,match='稳定帖子ID'):heybox_api.parse(address(),200,{'status':'ok','result':{'links':[{'title':'失效条目'}]}})
    feed=heybox_api.Feed();feed.response(response(0,[{'linkid':97001},{'linkid':97002}]))
    feed.take();feed.response(response(4,[{'linkid':97003}]))
    with pytest.raises(ValueError,match='断点'):feed.take()
    with pytest.raises(ValueError):heybox_api.parse(address(),200,{'status':'ok','result':{'links':[],'has_more':True}})

@pytest.mark.parametrize('status',[401,403,429])
def test_platform_denial_is_a_verification_pause_not_a_successful_empty_list(status):
    with pytest.raises(platform_browser.PlatformAccessRequired):heybox_api.parse(address(),status,{})

def test_account_changes_do_not_resume_someone_elses_checkpoint():
    feed=heybox_api.Feed();feed.response(response(0,[{'linkid':97001},{'linkid':97002}]))
    feed.take();next_page=response(2,[]);next_page.url=address(2,userid='222',heybox_id='222')
    feed.response(next_page)
    with pytest.raises(ValueError,match='账号'):feed.take()
    with pytest.raises(ValueError,match='自己的收藏'):heybox_api.parse(address(userid='222'),200,{'status':'ok','result':{'links':[]}})

def test_buffered_page_survives_a_later_denial_without_any_extra_probe(monkeypatch):
    feed=heybox_api.Feed();feed.response(response(0,[{'linkid':97001}],has_more=False))
    feed.response(SimpleNamespace(url=address(1),status=403,request=SimpleNamespace(method='GET')))
    assert feed.take()[0]['items'][0]['remote_id']=='97001'
    context=SimpleNamespace(request=SimpleNamespace(get=lambda *a,**k:pytest.fail('拒绝访问后不能继续探测')))
    with pytest.raises(platform_browser.PlatformAccessRequired):feed.verify_short_tail(context)
    with pytest.raises(platform_browser.PlatformAccessRequired):feed.take()

def test_verified_api_does_not_mistake_post_words_for_warning_or_ignore_visible_challenge():
    class Page:
        challenge=False
        def evaluate(self,_):return self.challenge
        def locator(self,_):return SimpleNamespace(inner_text=lambda **k:'收藏里的文章讲到了 rate limit exceeded',count=lambda:0)
    page=Page()
    assert '文章' in platform_browser.blocked(page,verified_favorite_api=True)
    page.challenge=True
    with pytest.raises(platform_browser.PlatformAccessRequired):platform_browser.blocked(page,verified_favorite_api=True)

def test_browser_adapter_consumes_favourite_api_and_resume_skips_known_ids_not_page_links(local,monkeypatch):
    from contextlib import contextmanager
    import playwright.sync_api
    class Page:
        def on(self,event,callback):self.response=callback
        def goto(self,*args,**kwargs):self.response(response(0,[{'linkid':97001,'title':'准确标题一'},{'linkid':97002,'title':'准确标题二'}]))
        def wait_for_timeout(self,ms):
            if ms==6000:self.response(response(2,[{'linkid':97003,'title':'准确标题三'}],has_more=False))
        def evaluate(self,script):assert 'window.scrollBy' in script
        def locator(self,selector):raise AssertionError('API有效时不能枚举网页推荐链接：'+selector)
    page=Page()
    context=SimpleNamespace(route=lambda *a:None,new_page=lambda:page)
    closed=[];browser=SimpleNamespace(new_context=lambda **kw:context,close=lambda:closed.append(True))
    @contextmanager
    def runtime():yield None
    monkeypatch.setattr(playwright.sync_api,'sync_playwright',runtime)
    monkeypatch.setattr(sessions,'browser',lambda _:browser);monkeypatch.setattr(sessions,'load',lambda _: {})
    monkeypatch.setattr(sessions,'login_browser',lambda pw,kind:(browser,context,page));page.close=lambda:None;page.route=context.route;page.unroute=lambda *a:None
    monkeypatch.setattr(platform_browser,'blocked',lambda *a,**kw: '')
    sessions.path('heybox').parent.mkdir(parents=True,exist_ok=True);sessions.path('heybox').write_bytes(b'fixture')
    progress={'seen_urls':['https://www.xiaoheihe.cn/app/bbs/link/97001']};entries=[]
    list(platform_browser.favorites('heybox','https://www.xiaoheihe.cn/app/user/favour',entries.append,progress))
    assert [v['remote_id'] for v in entries]==['97002','97003']
    assert progress['complete'] and progress['checkpoint']=={'offset':3} and progress['pages']==2
    assert progress['transport']=='heybox_favorites_api' and 'private-fixture-' not in str(progress) and closed

@pytest.mark.parametrize('fault',['denied','visible_challenge','denied_during_wait','next_page_then_challenge'])
def test_browser_keeps_valid_page_before_verification_and_does_not_claim_the_end(local,monkeypatch,fault):
    from contextlib import contextmanager
    import playwright.sync_api
    class Page:
        challenge=False
        def on(self,event,callback):self.response=callback
        def deny(self):self.response(SimpleNamespace(url=address(1),status=403,request=SimpleNamespace(method='GET')))
        def goto(self,*args,**kwargs):
            self.response(response(0,[{'linkid':97001}],**({} if fault in ('denied_during_wait','next_page_then_challenge') else {'has_more':False})))
            if fault=='denied':self.deny()
        def wait_for_timeout(self,ms):
            if ms==6000 and fault=='denied_during_wait':self.deny()
            if ms==6000 and fault=='next_page_then_challenge':
                self.response(response(1,[{'linkid':97002}],has_more=False));self.challenge=True
        def evaluate(self,_):pytest.fail('遇到验证不能继续滚动触发下一页')
    page=Page();closed=[]
    context=SimpleNamespace(route=lambda *a:None,new_page=lambda:page,
        request=SimpleNamespace(get=lambda *a,**kw:pytest.fail('遇到拒绝不能发起末页探测')))
    browser=SimpleNamespace(new_context=lambda **kw:context,close=lambda:closed.append(True))
    @contextmanager
    def runtime():yield None
    def blocked(*args,**kwargs):
        if fault=='visible_challenge' or page.challenge:raise platform_browser.PlatformAccessRequired('平台要求安全验证')
        return ''
    monkeypatch.setattr(playwright.sync_api,'sync_playwright',runtime)
    monkeypatch.setattr(sessions,'browser',lambda _:browser);monkeypatch.setattr(sessions,'load',lambda _: {})
    monkeypatch.setattr(sessions,'login_browser',lambda pw,kind:(browser,context,page));page.close=lambda:None;page.route=context.route;page.unroute=lambda *a:None
    monkeypatch.setattr(platform_browser,'blocked',blocked)
    sessions.path('heybox').parent.mkdir(parents=True,exist_ok=True);sessions.path('heybox').write_bytes(b'fixture')
    entries=[];progress={}
    with pytest.raises(platform_browser.PlatformAccessRequired):
        list(platform_browser.favorites('heybox','https://www.xiaoheihe.cn/app/user/favour',entries.append,progress))
    assert [e['remote_id'] for e in entries]==(['97001','97002'] if fault=='next_page_then_challenge' else ['97001'])
    assert not progress['complete'] and progress['checkpoint']=={'offset':2 if page.challenge else 1} and closed
