"""Owned login state and authorized snapshots; no automatic browser-profile scanning."""
from __future__ import annotations
import ctypes
import json
import math
import os
import queue
import threading
import subprocess
import socket
import time
from pathlib import Path
from urllib.parse import urlparse
from . import store

PAGES = {
    'bilibili': ('https://www.bilibili.com/', 'https://space.bilibili.com/'),
    'youtube': ('https://www.youtube.com/', 'https://www.youtube.com/feed/playlists'),
    'douyin': ('https://www.douyin.com/', 'https://www.douyin.com/user/self?showTab=favorite_collection'),
    'x': ('https://x.com/login', 'https://x.com/i/bookmarks'),
    'heybox': ('https://www.xiaoheihe.cn/app/user/favour/content', 'https://www.xiaoheihe.cn/app/user/favour/content'),
    'xiaohongshu': ('https://www.xiaohongshu.com/', 'https://www.xiaohongshu.com/'),
}

def belongs(kind, domain):
    from .adapters import PLATFORMS
    domain = domain.lstrip('.').lower()
    return any(domain == h or domain.endswith('.' + h) for h in PLATFORMS[kind][1])

def protect(value, decrypt=False):
    if os.name != 'nt':
        raise ValueError('本版本的网页登录态加密需要 Windows DPAPI；不降级为明文存储')
    class Blob(ctypes.Structure):
        _fields_ = [('size', ctypes.c_uint32), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buf = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    api = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not api(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError('无法加密/解密本机登录状态，请使用保存它的 Windows 用户')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)

def path(kind):
    if kind not in PAGES: raise ValueError('未知平台')
    return store.DATA / 'credentials' / (kind + '.dpapi')

def save(kind, state):
    state['cookies'] = [c for c in state.get('cookies', []) if belongs(kind, c.get('domain', ''))]
    state['origins'] = [v for v in state.get('origins', []) if belongs(kind, urlparse(v.get('origin', '')).hostname or '')]
    if not state['cookies']: raise ValueError('没有取得该平台登录状态；请先完成官方网页登录')
    if kind=='heybox' and not any(c.get('name') in ('user_pkey','pkey') and c.get('value') for c in state['cookies']):
        raise ValueError('小黑盒登录尚未完成，未用访客Cookie覆盖已有登录状态')
    if kind=='x' and store.settings().get('x_read_mode','session')!='oauth':
        keys={c['name'] for c in state['cookies'] if c.get('value')}
        if not {'auth_token','ct0'}.issubset(keys): raise ValueError('X 登录还没有完成；请先正常进入书签页，再保存状态')
    target = path(kind); target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_bytes(protect(store.dumps(state).encode('utf-8')))
    temporary.replace(target)

def load(kind):
    target = path(kind)
    return json.loads(protect(target.read_bytes(), True)) if target.exists() else {'cookies': [], 'origins': []}

def import_state(kind,state):
    """Import one authorized platform snapshot; never scan another Chrome profile."""
    if not isinstance(state.get('cookies'),list) or any(not isinstance(c,dict) for c in state['cookies']):raise ValueError('请提供浏览器导出的Cookie列表')
    if state.get('platform',kind)!=kind:raise ValueError('请选择当前平台的登录快照')
    if any(not isinstance(c.get('domain'),str) for c in state['cookies']):raise ValueError('Cookie域名格式无效，未保存')
    cookies=[{k:v for k,v in cookie.items() if k in ('name','value','domain','path','expires','httpOnly','secure','sameSite')}
             for cookie in state['cookies'] if belongs(kind,cookie.get('domain',''))]
    if any(not all(isinstance(c.get(k),str) for k in ('name','value','domain','path')) for c in cookies):raise ValueError('Cookie字段不完整，未保存')
    for cookie in cookies:
        if not cookie['name'] or not cookie['path'].startswith('/'):raise ValueError('Cookie名称或路径无效，未保存')
        if 'expires' in cookie and (not isinstance(cookie['expires'],(int,float)) or not math.isfinite(cookie['expires'])):raise ValueError('Cookie有效期无效，未保存')
        if any(k in cookie and not isinstance(cookie[k],bool) for k in ('httpOnly','secure')):raise ValueError('Cookie安全字段无效，未保存')
        if cookie.get('sameSite','Lax') not in ('Strict','Lax','None'):raise ValueError('Cookie来源策略无效，未保存')
    if kind=='heybox' and not any(c.get('name') in ('user_pkey','pkey') and c.get('value') for c in cookies):
        raise ValueError('当前Chrome未取得小黑盒账号登录信息，未替换已有登录状态')
    values=state.get('origins',[])
    if not isinstance(values,list) or any(not isinstance(v,dict) or not isinstance(v.get('origin'),str) for v in values):raise ValueError('登录来源格式无效，未保存')
    origins=[]
    for value in values:
        if not belongs(kind,urlparse(value['origin']).hostname or ''):continue
        entries=value.get('localStorage',[])
        if not isinstance(entries,list) or any(not isinstance(v,dict) or not all(isinstance(v.get(k),str) for k in ('name','value')) for v in entries):raise ValueError('登录存储格式无效，未保存')
        origins.append({'origin':value['origin'],'localStorage':[{'name':v['name'],'value':v['value']} for v in entries]})
    save(kind,{'cookies':cookies,'origins':origins})
    with store.db() as c:store.event(c,None,'platform_session_imported',{'platform':kind,'source':'authorized_browser_snapshot','cookies':len(cookies)})
    return {'platform':kind,'saved':True,'cookie_count':len(cookies),'verification':'登录快照已保存，下次可直接复用；访问权限在实际读取时核对'}

def status(kind):
    with store.db() as c:
        last = c.execute("SELECT id,state,error,progress FROM jobs WHERE kind='favorites' AND json_extract(payload,'$.platform')=? ORDER BY created DESC LIMIT 1", (kind,)).fetchone()
    last = dict(last) if last else None
    if last: last['progress'] = json.loads(last['progress'])
    return {'platform': kind, 'saved': path(kind).exists(), 'login': LOGIN.get(kind, {'state':'closed'}),
            'last_sync': last, 'favorite_url': store.settings().get('favorite_pages', {}).get(kind, PAGES[kind][1]),
            'x_client_id': store.settings().get('x_client_id','') if kind=='x' else '',
            'read_mode': store.settings().get('x_read_mode','session') if kind=='x' else 'session',
            'verification': '登录状态已保存；收藏权限在实际读取时验证' if path(kind).exists() else '尚未登录'}

def browser_executable():
    roots=[Path(os.environ.get('PROGRAMFILES','C:/Program Files')),Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))]
    for root in roots:
        chrome=root/'Google/Chrome/Application/chrome.exe'
        if chrome.exists():return chrome
    edge=roots[1]/'Microsoft/Edge/Application/msedge.exe'
    return edge if edge.exists() else None

def browser(pw, headed=False):
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(store.DATA / 'browsers')
    executable=browser_executable()
    args = {'headless': not headed}
    if executable: args['executable_path'] = str(executable)
    return pw.chromium.launch(**args)

def login_browser(pw,kind):
    """A normal visible Chrome window in this project's own profile, for human sign-in."""
    executable=browser_executable()
    if not executable:
        b=browser(pw,True);context=b.new_context(storage_state=load(kind))
        return b,context,context.new_page()
    profile=store.DATA/'login-profiles'/kind;profile.mkdir(parents=True,exist_ok=True)
    control=profile/'browser-control.json'
    if control.exists():
        import httpx
        try:
            previous=json.loads(control.read_text('utf-8'))
            endpoint=f'http://127.0.0.1:{int(previous["port"])}'
            version=httpx.get(endpoint+'/json/version',timeout=2,trust_env=False).json()
            if version.get('webSocketDebuggerUrl','').endswith(previous['browser_path']):
                b=pw.chromium.connect_over_cdp(endpoint);context=b.contexts[0]
                page=next((p for p in context.pages if belongs(kind,urlparse(p.url).hostname or '')),None)
                return b,context,page or context.new_page()
        except Exception:pass
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    process=subprocess.Popen([str(executable),f'--user-data-dir={profile}',f'--remote-debugging-port={port}',
                              '--remote-debugging-address=127.0.0.1','--no-first-run','--no-default-browser-check',PAGES[kind][0]],
                             stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            with socket.create_connection(('127.0.0.1',port),timeout=.2):break
        except OSError:
            if process.poll() is not None:raise ValueError('Chrome 登录窗口没有启动；请关闭此工具此前的同平台登录窗口后重试')
            time.sleep(.1)
    else:
        process.terminate();raise ValueError('Chrome 登录窗口启动超时')
    b=pw.chromium.connect_over_cdp(f'http://127.0.0.1:{port}')
    import httpx
    version=httpx.get(f'http://127.0.0.1:{port}/json/version',timeout=5,trust_env=False).json()
    control.write_text(store.dumps({'port':port,'browser_path':urlparse(version['webSocketDebuggerUrl']).path}),'utf-8')
    context=b.contexts[0]
    return b,context,context.pages[0] if context.pages else context.new_page()

COMMANDS = queue.Queue()
LOGIN = {}
LOCK = threading.Lock()
THREAD = None
URLS = {}

def command(kind, action):
    global THREAD
    path(kind)
    with LOCK:
        if THREAD is None or not THREAD.is_alive():
            THREAD = threading.Thread(target=login_worker, daemon=True, name='official-login')
            THREAD.start()
        if action == 'open':
            if LOGIN.get(kind, {}).get('state') in ('opening', 'open', 'saving'):
                return status(kind)
            if kind=='x' and store.settings().get('x_read_mode','session')=='oauth':
                from . import xofficial
                URLS[kind]=xofficial.authorize()
            LOGIN[kind] = {'state':'opening', 'message':'正在打开该平台的官方登录窗口'}
        elif action == 'save':
            if kind=='x' and store.settings().get('x_read_mode','session')=='oauth': raise ValueError('当前选择官方 OAuth，授权后自动保存')
            if LOGIN.get(kind, {}).get('state') != 'open': raise ValueError('请先打开登录窗口')
            LOGIN[kind] = {'state':'saving', 'message':'正在保存这个平台的本机登录状态'}
        elif action == 'forget':
            path(kind).unlink(missing_ok=True)
            cfg = store.settings(); cfg.setdefault('favorite_pages', {}).pop(kind, None)
            store.save_settings(cfg)
        COMMANDS.put((kind, action))
    return status(kind)

def login_worker():
    from playwright.sync_api import sync_playwright
    opened = {}
    with sync_playwright() as pw:
        while True:
            try: kind, action = COMMANDS.get(timeout=.25)
            except queue.Empty:
                for kind, (_, context, page) in list(opened.items()):
                    try: page.wait_for_timeout(50)
                    except Exception:
                        opened.pop(kind, None)
                        LOGIN[kind] = {'state':'closed', 'message':'登录窗口已关闭；已保存的登录状态仍保留'}
                continue
            try:
                if action == 'open':
                    b,context,page = login_browser(pw,kind)
                    opened[kind] = (b, context, page)
                    target=URLS.get(kind,store.settings().get('favorite_pages',{}).get(kind,PAGES[kind][1] if path(kind).exists() else PAGES[kind][0]))
                    page.goto(target, wait_until='domcontentloaded', timeout=60000)
                    LOGIN[kind] = {'state':'open', 'message':'已打开原有Chrome资料目录；已登录可直接使用，过期时本人登录后保存'}
                elif action == 'save':
                    b, context, page = opened[kind]
                    save(kind, context.storage_state())
                    current = page.url
                    if belongs(kind, urlparse(current).hostname or ''):
                        favorite = current if any(part in current for part in ('favour','favorite','collect','bookmark','playlist','/user/profile/')) else PAGES[kind][1]
                        cfg = store.settings(); cfg.setdefault('favorite_pages', {})[kind] = favorite
                        store.save_settings(cfg)
                    b.close(); opened.pop(kind, None)
                    LOGIN[kind] = {'state':'saved', 'message':'已加密保存在本机；请确认下方地址是自己的收藏页，再开始导入'}
                    with store.db() as c: store.event(c, None, 'platform_session_saved', {'platform':kind})
                elif action in ('close', 'forget'):
                    if kind in opened: opened.pop(kind)[0].close()
                    LOGIN[kind] = {'state':'closed', 'message':'登录窗口已关闭'}
            except Exception as exc:
                LOGIN[kind] = {'state':'open' if kind in opened else 'error', 'message':str(exc) if isinstance(exc,ValueError) else f'登录窗口操作失败（{type(exc).__name__}）；请在原窗口核对后重试'}

def cookie_values(kind):
    return {c['name']:c['value'] for c in load(kind).get('cookies',[])}
