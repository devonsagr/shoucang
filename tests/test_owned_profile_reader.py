from types import SimpleNamespace
import pytest
from app import sessions,store
from test_automatic_collection import local

def test_heybox_capture_reuses_owned_context_without_cloning_cookies_or_closing_the_login_tab(local,monkeypatch):
    closed=[]
    landing=SimpleNamespace(close=lambda:pytest.fail('不能关闭本人登录标签'))
    page=SimpleNamespace(close=lambda:closed.append('reader'))
    context=SimpleNamespace(new_page=lambda:page)
    browser=SimpleNamespace(close=lambda:closed.append('connection'),new_context=lambda **kw:pytest.fail('不能克隆到新浏览器上下文'))
    monkeypatch.setattr(sessions,'browser',lambda _:pytest.fail('不能启动新的后台无头浏览器'))
    monkeypatch.setattr(sessions,'login_browser',lambda pw,kind:(browser,context,landing))
    with sessions.capture_session(None,'heybox') as (actual,reader):
        assert actual is context and reader is page
    assert closed==['reader','connection']

def test_active_human_login_is_not_interrupted_by_background_capture(local,monkeypatch):
    sessions.LOGIN['heybox']={'state':'open'}
    monkeypatch.setattr(sessions,'login_browser',lambda *a:pytest.fail('本人验证中不能自动读取'))
    with pytest.raises(ValueError,match='完成验证'):
        with sessions.capture_session(None,'heybox'):pass

def test_visible_heybox_verification_keeps_the_actual_reader_tab_for_human_resolution(local,monkeypatch):
    from app.platform_browser import PlatformAccessRequired
    cleanup=[]
    page=SimpleNamespace(close=lambda:pytest.fail('不能关闭真正触发验证码的页面'),unroute=lambda pattern:cleanup.append(pattern))
    context=SimpleNamespace(new_page=lambda:page)
    browser=SimpleNamespace(close=lambda:cleanup.append('disconnect'))
    monkeypatch.setattr(sessions,'login_browser',lambda *a:(browser,context,None))
    with pytest.raises(PlatformAccessRequired):
        with sessions.capture_session(None,'heybox'):raise PlatformAccessRequired('本人验证')
    assert cleanup==['**/*','disconnect']

def test_other_reader_failures_close_only_the_owned_tab(local,monkeypatch):
    cleanup=[]
    page=SimpleNamespace(close=lambda:cleanup.append('reader'))
    browser=SimpleNamespace(close=lambda:cleanup.append('disconnect'))
    monkeypatch.setattr(sessions,'login_browser',lambda *a:(browser,SimpleNamespace(new_page=lambda:page),None))
    with pytest.raises(ValueError,match='页面结构变化'):
        with sessions.capture_session(None,'heybox'):raise ValueError('页面结构变化')
    assert cleanup==['reader','disconnect']

@pytest.mark.parametrize('fault',['unroute','disconnect','both'])
def test_cleanup_failure_never_hides_platform_verification_or_its_pause_signal(local,monkeypatch,fault):
    from app.platform_browser import PlatformAccessRequired
    cleanup=[]
    def clear():
        cleanup.append('unroute')
        if fault in ('unroute','both'):raise RuntimeError('连接已关闭')
    def disconnect():
        cleanup.append('disconnect')
        if fault in ('disconnect','both'):raise RuntimeError('连接已关闭')
    page=SimpleNamespace(close=lambda:pytest.fail('验证码标签必须保留'),unroute=lambda *a:clear())
    monkeypatch.setattr(sessions,'login_browser',lambda *a:(SimpleNamespace(close=disconnect),SimpleNamespace(new_page=lambda:page),None))
    original=PlatformAccessRequired('平台要求本人验证')
    with pytest.raises(PlatformAccessRequired) as error:
        with sessions.capture_session(None,'heybox'):raise original
    assert error.value is original and cleanup==['unroute','disconnect']

def test_owned_login_reconnects_to_the_latest_platform_tab(local,monkeypatch):
    import httpx
    profile=store.DATA/'login-profiles'/'heybox';profile.mkdir(parents=True)
    (profile/'browser-control.json').write_text(store.dumps({'port':43210,'browser_path':'/devtools/browser/fixture'}),'utf-8')
    landing=SimpleNamespace(url='https://www.xiaoheihe.cn/app/user/favour/content')
    challenged=SimpleNamespace(url='https://www.xiaoheihe.cn/app/bbs/link/997001')
    context=SimpleNamespace(pages=[landing,challenged])
    browser=SimpleNamespace(contexts=[context])
    runtime=SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=lambda endpoint:browser))
    monkeypatch.setattr(sessions,'browser_executable',lambda:profile/'fixture.exe')
    monkeypatch.setattr(httpx,'get',lambda *a,**kw:SimpleNamespace(json=lambda:{'webSocketDebuggerUrl':'ws://127.0.0.1:43210/devtools/browser/fixture'}))
    actual,actual_context,page=sessions.login_browser(runtime,'heybox')
    assert actual is browser and actual_context is context and page is challenged

def test_verification_window_does_not_refresh_same_source_or_save_visible_challenge(local,monkeypatch):
    from contextlib import contextmanager
    import playwright.sync_api
    from app import platform_browser
    class WorkerStopped(BaseException):pass
    actions=iter([('heybox','open'),('heybox','save')])
    def command(**kwargs):
        try:return next(actions)
        except StopIteration:raise WorkerStopped()
    @contextmanager
    def runtime():yield None
    url='https://www.xiaoheihe.cn/app/bbs/link/997001'
    page=SimpleNamespace(url=url,goto=lambda *a,**kw:pytest.fail('不能刷新已经停在验证页的同一原文'))
    browser=SimpleNamespace(close=lambda:pytest.fail('验证码未完成不能关闭窗口'))
    context=SimpleNamespace(storage_state=lambda:pytest.fail('可见验证不能保存为已通过'))
    def blocked(page):raise platform_browser.PlatformAccessRequired('请完成本人验证')
    monkeypatch.setattr(sessions,'COMMANDS',SimpleNamespace(get=command))
    monkeypatch.setattr(sessions,'URLS',{'heybox':url})
    monkeypatch.setattr(sessions,'login_browser',lambda *a:(browser,context,page))
    monkeypatch.setattr(platform_browser,'blocked',blocked)
    monkeypatch.setattr(playwright.sync_api,'sync_playwright',runtime)
    with pytest.raises(WorkerStopped):sessions.login_worker()
    assert sessions.LOGIN['heybox']['state']=='open' and '本人验证' in sessions.LOGIN['heybox']['message']

def test_verify_window_url_stays_on_the_selected_public_platform(local,monkeypatch):
    client,_=local;calls=[]
    monkeypatch.setattr(sessions,'URLS',{})
    monkeypatch.setattr(sessions,'command',lambda kind,action:(calls.append((kind,action)) or {'opened':True}))
    url='https://www.xiaoheihe.cn/app/bbs/link/997001'
    assert client.post('/api/accounts/heybox/login',json={'action':'open','url':url}).status_code==200
    assert sessions.URLS['heybox']==url
    assert client.post('/api/accounts/heybox/login',json={'action':'open','url':'https://x.com/i/bookmarks'}).status_code==400
    assert client.post('/api/accounts/heybox/login',json={'action':'save','url':url}).status_code==400
    assert len(calls)==1
