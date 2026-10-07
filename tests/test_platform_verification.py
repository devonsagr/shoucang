import json
import threading
from app import platform_browser,service,store
from test_automatic_collection import local

REAL_WORKER=service.worker

def test_visible_verification_pauses_only_remaining_requests_for_that_platform(local,monkeypatch):
    client,_=local
    mids=[client.post('/api/materials',json={'url':url,'text':'原文仍然保留'}).json()['id'] for url in ['https://www.xiaoheihe.cn/app/bbs/link/970001','https://www.xiaoheihe.cn/app/bbs/link/970002','https://x.com/i/status/970003']]
    with store.db() as c:
        ids=[store.enqueue(c,'collect',{'transcribe':True,'engine':'local'},mid) for mid in mids]
        c.execute("UPDATE materials SET collection='queued'")
    stop=threading.Event();monkeypatch.setattr(service,'STOP',stop)
    def blocked(job):stop.set();raise platform_browser.PlatformAccessRequired('平台要求验证码，请本人完成')
    monkeypatch.setattr(service,'run_job',blocked)
    REAL_WORKER()
    with store.db() as c:states={r['id']:r['state'] for r in c.execute('SELECT id,state FROM jobs')}
    assert states[ids[0]]=='failed' and states[ids[1]]=='paused' and states[ids[2]]=='queued'
    assert store.get(mids[1])['body']=='原文仍然保留' and store.get(mids[1])['collection']=='paused'
    assert store.get(mids[2])['collection']=='queued'
