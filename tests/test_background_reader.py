from types import SimpleNamespace
import pytest
from app import platform_browser,sessions,store
from test_automatic_collection import local
REAL_READER=sessions.background_reader


def test_background_window_is_created_once_reused_and_never_focuses_the_main_browser(local,monkeypatch):
    folder=store.DATA/'login-profiles'/'heybox';folder.mkdir(parents=True)
    (folder/'browser-control.json').write_text('{}','utf-8')
    pages=[];calls=[]
    class Expect:
        def __enter__(self):return self
        def __exit__(self,*args):self.value=pages[-1]
    class Session:
        def send(self,method,params):
            calls.append((method,params))
            if method=='Target.createTarget':
                pages.append(SimpleNamespace(identifier='reader-1',url='about:blank'));return {'targetId':'reader-1'}
            if method=='Browser.getWindowForTarget':return {'windowId':11}
        def detach(self):pass
    context=SimpleNamespace(pages=pages,expect_page=lambda:Expect())
    browser=SimpleNamespace(new_browser_cdp_session=lambda:Session())
    monkeypatch.setattr(sessions,'target_id',lambda context,page:page.identifier)
    one=REAL_READER(browser,context,'heybox');two=REAL_READER(browser,context,'heybox')
    assert one is two and one._cangye_background
    created=[params for method,params in calls if method=='Target.createTarget']
    assert len(created)==1 and created[0]['windowState']=='minimized' and created[0]['focus'] is False and created[0]['background'] is True
    assert all(params['windowId']==11 for method,params in calls if method=='Browser.setWindowBounds')

@pytest.mark.parametrize('challenge',[False,True])
def test_background_cleanup_keeps_the_exact_challenge_but_releases_normal_source_pages(local,monkeypatch,challenge):
    actions=[];url='https://www.xiaoheihe.cn/app/bbs/link/996600'
    page=SimpleNamespace(url=url,_cangye_background=True,close=lambda:pytest.fail('后台页应复用'),unroute=lambda *a:actions.append('unroute'),goto=lambda *a,**kw:actions.append('blank'))
    context=SimpleNamespace(new_page=lambda:page)
    browser=SimpleNamespace(close=lambda:actions.append('disconnect'))
    monkeypatch.setattr(sessions,'browser_executable',lambda:'fixture.exe')
    monkeypatch.setattr(sessions,'login_browser',lambda *a,**kw:(browser,context,None))
    if challenge:
        with pytest.raises(platform_browser.PlatformAccessRequired):
            with sessions.capture_session(None,'heybox'):raise platform_browser.PlatformAccessRequired('本人验证')
        assert actions==['unroute','disconnect'] and sessions.URLS['heybox']==url
    else:
        with sessions.capture_session(None,'heybox'):pass
        assert actions==['blank','unroute','disconnect']

def test_favorites_and_detail_captures_cannot_share_the_reader_at_the_same_time(local,monkeypatch):
    import threading
    first_entered=threading.Event();second_attempted=threading.Event();second_entered=threading.Event();release=threading.Event();errors=[]
    page=SimpleNamespace(url='about:blank',_cangye_background=True,unroute=lambda *a:None)
    page.goto=lambda url,**kw:setattr(page,'url',url)
    context=SimpleNamespace(new_page=lambda:page)
    browser=SimpleNamespace(close=lambda:None)
    monkeypatch.setattr(sessions,'browser_executable',lambda:'fixture.exe')
    monkeypatch.setattr(sessions,'login_browser',lambda *a,**kw:(browser,context,None))
    def detail():
        try:
            with sessions.capture_session(None,'heybox') as (_,owned):
                owned.goto('https://www.xiaoheihe.cn/app/bbs/link/996601');first_entered.set()
                assert release.wait(5)
                assert owned.url.endswith('/996601')
        except BaseException as exc:errors.append(exc)
    def favorites():
        try:
            second_attempted.set()
            with sessions.capture_session(None,'heybox') as (_,owned):
                assert owned.url=='about:blank';second_entered.set()
        except BaseException as exc:errors.append(exc)
    one=threading.Thread(target=detail);two=threading.Thread(target=favorites);one.start()
    try:
        assert first_entered.wait(5);two.start();assert second_attempted.wait(5)
        assert not second_entered.wait(.1), 'favorites must not navigate or clean the active detail page'
    finally:
        release.set();one.join(5)
        if two.ident:two.join(5)
    assert not errors and second_entered.is_set() and not one.is_alive() and not two.is_alive()

def test_reader_metadata_does_not_reseed_stale_cookies_and_new_import_is_applied(local,monkeypatch):
    import json
    folder=store.DATA/'login-profiles'/'heybox';folder.mkdir(parents=True)
    control=folder/'browser-control.json';state={'port':9333,'browser_path':'/devtools/browser/fixture-one'}
    control.write_text(json.dumps(state),'utf-8')
    with store.db() as c:store.event(c,None,'platform_session_imported',{'platform':'heybox','source':'chrome_extension'})
    added=[];snapshot={'cookies':[{'value':'old-synthetic-cookie'}]}
    current={'cookie':None}
    def apply(cookies):added.append(cookies[0]['value']);current['cookie']=cookies[0]['value']
    context=SimpleNamespace(add_cookies=apply)
    monkeypatch.setattr(sessions,'load',lambda kind:snapshot)
    sessions.seed_imported(context,'heybox');current['cookie']='platform-refreshed-cookie'
    state.update(reader_target='reader-one',reader_window=77);control.write_text(json.dumps(state),'utf-8')
    sessions.seed_imported(context,'heybox')
    assert added==['old-synthetic-cookie'] and current['cookie']=='platform-refreshed-cookie'
    snapshot['cookies'][0]['value']='new-synthetic-cookie'
    with store.db() as c:store.event(c,None,'platform_session_imported',{'platform':'heybox','source':'chrome_extension'})
    sessions.seed_imported(context,'heybox');sessions.seed_imported(context,'heybox')
    assert added==['old-synthetic-cookie','new-synthetic-cookie']
    state.update(port=9334,browser_path='/devtools/browser/fixture-two');control.write_text(json.dumps(state),'utf-8')
    sessions.seed_imported(context,'heybox');assert len(added)==3
    with store.db() as c:store.event(c,None,'platform_session_saved',{'platform':'heybox'})
    sessions.seed_imported(context,'heybox');assert len(added)==3
