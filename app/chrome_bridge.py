"""One platform, one short-lived local Chrome handoff; no credential logging."""
import re
import secrets
import threading
import time
from . import sessions

TTL=600
PENDING={}
LOCK=threading.Lock()
EXTENSION=re.compile(r'^chrome-extension://[a-p]{32}$')

def extension_origin(value):return bool(value and EXTENSION.fullmatch(value))

def issue(kind,port):
    if kind not in sessions.PAGES:raise ValueError('未知平台')
    token=secrets.token_urlsafe(24)
    with LOCK:
        expired=[key for key,value in PENDING.items() if value['expires']<=time.monotonic()]
        for key in expired:PENDING.pop(key,None)
        if len(PENDING)>=32:raise ValueError('待连接请求较多，请稍后再试')
        PENDING[token]={'platform':kind,'expires':time.monotonic()+TTL}
    return {'code':f'cangye:{port}:{token}','expires_in':TTL,'platform':kind}

def accept(token,kind,state):
    with LOCK:
        pending=PENDING.get(token)
        if not pending or pending['expires']<=time.monotonic():
            PENDING.pop(token,None);raise ValueError('连接码已过期或使用过，请回网站重新生成')
        if pending['platform']!=kind:raise ValueError('平台与连接码不一致，请选择网站中相同的平台')
        result=sessions.import_state(kind,state,source='chrome_extension')
        PENDING.pop(token,None)
    return result
