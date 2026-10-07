import json
from app import platform_browser,service,sessions,store
from test_automatic_collection import local
from test_source_identity import purge

def source(identifier):return 'https://www.xiaoheihe.cn/app/bbs/link/'+str(identifier)

def setup_material(client,identifier,state,**content):
    mid=client.post('/api/materials',json={'url':source(identifier),'text':'已有原文 '+str(identifier),'origin':'favorite'}).json()['id']
    with store.db() as c:
        c.execute("UPDATE materials SET collection=?,notes='我的用途',processing='later',content_json=? WHERE id=?",
                  (state,store.dumps({**store.get(mid)['content'],**content}),mid))
    return mid

def synchronize(monkeypatch,identifiers,repair=False):
    def pages(kind,url,record,progress,cancelled):
        for identifier in identifiers:record({'url':source(identifier),'title':'清单标题'})
        progress['complete']=True;yield progress
    monkeypatch.setattr(platform_browser,'favorites',pages)
    payload={'platform':'heybox','url':'https://www.xiaoheihe.cn/app/user/favour/content','repair_incomplete':repair}
    with store.db() as c:jid=store.enqueue(c,'favorites',payload)
    service.run_job({'id':jid,'kind':'favorites','material_id':None,'payload':store.dumps(payload),'progress':'{}'})
    with store.db() as c:
        progress=json.loads(c.execute('SELECT progress FROM jobs WHERE id=?',(jid,)).fetchone()['progress'])
        queued={r['material_id'] for r in c.execute("SELECT material_id FROM jobs WHERE kind='collect' AND state='queued'")}
    return progress,queued

def test_normal_sync_does_not_retry_old_failures_or_overwrite_annotations(local,monkeypatch):
    client,_=local;mid=setup_material(client,98101,'failed')
    progress,queued=synchronize(monkeypatch,[98101,98102])
    assert mid not in queued and len(queued)==1
    assert progress['new']==1 and progress['duplicates']==1 and progress['only_new_content']
    item=store.get(mid)
    assert item['collection']=='failed' and item['notes']=='我的用途' and item['processing']=='later' and item['body']=='已有原文 98101'

def test_opt_in_repair_uses_only_returned_unfinished_sources_and_preserves_deleted(local,monkeypatch):
    client,_=local
    ids={identifier:setup_material(client,identifier,state) for identifier,state in
         [(98201,'failed'),(98202,'partial'),(98203,'paused'),(98204,'ready'),(98205,'failed'),(98206,'failed'),(98207,'failed'),(98208,'partial')]}
    client.delete('/api/materials/'+ids[98205]);purge(client,ids[98206])
    with store.db() as c:c.execute('UPDATE materials SET content_json=? WHERE id=?',(store.dumps({'media_kind':'video_reference'}),ids[98208]))
    progress,queued=synchronize(monkeypatch,[98201,98202,98203,98204,98205,98206,98208,98209],repair=True)
    assert {ids[98201],ids[98202],ids[98203]}<=queued and len(queued)==4
    assert not any(ids[n] in queued for n in (98204,98205,98206,98207,98208))
    assert progress['repair_queued']==3 and progress['retired']==1 and progress['new']==1 and progress['duplicates']==7
    assert not progress['only_new_content'] and store.get(ids[98205])['trashed']
    for n in (98201,98202,98203,98204,98207,98208):
        item=store.get(ids[n]);assert item['notes']=='我的用途' and item['processing']=='later'
    assert store.get(ids[98207])['collection']=='failed'

def test_resume_keeps_the_original_repair_mode(local):
    client,_=local
    sessions.path('heybox').parent.mkdir(parents=True,exist_ok=True);sessions.path('heybox').write_bytes(b'fixture')
    with store.db() as c:
        old=store.enqueue(c,'favorites',{'platform':'heybox','repair_incomplete':True})
        c.execute("UPDATE jobs SET state='failed',progress=? WHERE id=?",(store.dumps({'complete':False,'seen_urls':[source(98301)]}),old))
    result=client.post('/api/favorites',json={'platform':'heybox','resume_job_id':old,'repair_incomplete':False})
    assert result.status_code==200,result.text
    with store.db() as c:row=c.execute('SELECT payload,progress FROM jobs WHERE id=?',(result.json()['job_id'],)).fetchone()
    assert json.loads(row['payload'])['repair_incomplete'] is True and json.loads(row['progress'])['seen_urls']==[source(98301)]

def test_native_api_resume_repairs_previously_seen_paused_material_only_once(local,monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    import playwright.sync_api
    from test_heybox_api import response
    client,_=local;mid=setup_material(client,98401,'paused')
    class Page:
        def on(self,event,callback):self.response=callback
        def goto(self,*args,**kwargs):self.response(response(0,[{'linkid':98401},{'linkid':98401}],has_more=False))
        def wait_for_timeout(self,ms):pass
        def evaluate(self,_):raise AssertionError('接口末尾之后不应滚动')
    page=Page();context=SimpleNamespace(route=lambda *a:None,new_page=lambda:page)
    browser=SimpleNamespace(new_context=lambda **kw:context,close=lambda:None)
    @contextmanager
    def runtime():yield None
    monkeypatch.setattr(playwright.sync_api,'sync_playwright',runtime)
    monkeypatch.setattr(sessions,'browser',lambda _:browser);monkeypatch.setattr(sessions,'load',lambda _: {})
    monkeypatch.setattr(sessions,'login_browser',lambda pw,kind:(browser,context,page));page.close=lambda:None;page.route=context.route
    monkeypatch.setattr(platform_browser,'blocked',lambda *a,**kw: '')
    sessions.path('heybox').parent.mkdir(parents=True,exist_ok=True);sessions.path('heybox').write_bytes(b'fixture')
    payload={'platform':'heybox','url':'https://www.xiaoheihe.cn/app/user/favour/content','repair_incomplete':True,'resumed_from':'fixture-previous'}
    progress={'complete':False,'seen_urls':[source(98401)]}
    with store.db() as c:jid=store.enqueue(c,'favorites',payload)
    service.run_job({'id':jid,'kind':'favorites','material_id':None,'payload':store.dumps(payload),'progress':store.dumps(progress)})
    with store.db() as c:
        progress=json.loads(c.execute('SELECT progress FROM jobs WHERE id=?',(jid,)).fetchone()['progress'])
        assert c.execute("SELECT count(*) FROM jobs WHERE kind='collect' AND material_id=? AND state='queued'",(mid,)).fetchone()[0]==1
    assert progress['repair_queued']==1 and progress['duplicates']==1 and progress['complete']
    assert store.get(mid)['collection']=='queued' and store.get(mid)['notes']=='我的用途' and store.get(mid)['processing']=='later'
