import asyncio
import json
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app import adapters, main, service, sessions, store, video_pipeline, xbookmarks, platform_browser

@pytest.fixture
def local(tmp_path,monkeypatch):
    config={}
    monkeypatch.setattr(store,'ROOT',tmp_path)
    monkeypatch.setattr(store,'DATA',tmp_path/'data')
    monkeypatch.setattr(store,'settings',lambda:config.copy())
    monkeypatch.setattr(store,'save_settings',lambda value:(config.clear(),config.update(value)))
    monkeypatch.setattr(service,'worker',lambda:None)
    monkeypatch.setattr(service,'favorites_worker',lambda:None)
    monkeypatch.setattr(adapters,'public_url',lambda u:None)
    monkeypatch.setattr(xbookmarks,'BLOCKED',__import__('threading').Event())
    monkeypatch.setattr(xbookmarks,'BLOCK_REASON','')
    with TestClient(main.app,headers={'X-Local-Request':'1'}) as client:yield client,config

def material(client,url,text='原文夹具'):
    return client.post('/api/materials',json={'url':url,'text':text}).json()['id']

def test_platform_counts_trash_restore_and_invalidated_push(local):
    client,_=local
    mid=material(client,'https://x.com/i/status/12345678')
    material(client,'https://www.douyin.com/video/12345678')
    material(client,'https://www.douyin.com/video/12345679')
    item=store.get(mid)
    assert client.put(f'/api/materials/{mid}/notes',json={'notes':'我的理解夹具','revision':item['revision']}).status_code==200
    preview=client.post(f'/api/materials/{mid}/push-preview',json={'destination':'knowledge'}).json()
    assert client.get('/api/materials?platform=x').json()['counts']['all']==1
    assert client.get('/api/materials?platform=douyin').json()['counts']['all']==2
    assert client.delete(f'/api/materials/{mid}').status_code==200
    data=client.get('/api/materials?platform=x').json()
    assert not data['items'] and data['counts']['trash']==1 and data['counts']['all']==0
    assert client.post('/api/pushes/'+preview['id']+'/confirm',json={'hash':preview['hash']}).status_code==400
    assert client.post(f'/api/materials/{mid}/retry',json={}).status_code==400
    assert client.get('/api/materials?platform=x&state=trash').json()['items'][0]['id']==mid
    assert client.post(f'/api/materials/{mid}/restore',json={}).status_code==200
    item=store.get(mid)
    assert item['body']=='原文夹具' and item['notes']=='我的理解夹具' and not item['trashed']
    with store.db() as c:
        assert {r[0] for r in c.execute('SELECT kind FROM events WHERE material_id=?',(mid,))}>={'material_trashed','material_restored','notes_saved'}
    assert not (store.DATA/'outbox').exists()

def test_read_later_is_unfinished_platform_scoped_and_reversible(local):
    client,_=local
    mid=material(client,'https://x.com/i/status/12345678')
    other=material(client,'https://www.douyin.com/video/12345678')
    before=store.get(mid)
    preview=client.post(f'/api/materials/{mid}/push-preview',json={'destination':'knowledge'}).json()
    assert client.post(f'/api/materials/{mid}/status',json={'state':'later','revision':before['revision']}).status_code==200
    item=store.get(mid)
    assert item['processing']=='later' and item['body']==before['body'] and item['revision']==before['revision']+1
    assert not client.get('/api/materials?platform=x&state=pending').json()['items']
    data=client.get('/api/materials?platform=x&state=later').json()
    assert [r['id'] for r in data['items']]==[mid] and data['counts']['all']==1 and data['counts']['later']==1
    assert client.get('/api/materials?platform=douyin&state=pending').json()['items'][0]['id']==other
    assert '稍后整理（暂存，尚未处理完成）' in client.get(f'/api/materials/{mid}/markdown').text
    assert client.post('/api/pushes/'+preview['id']+'/confirm',json={'hash':preview['hash']}).status_code==400
    assert not (store.DATA/'outbox').exists()
    assert (store.material_folder(mid)/'material.md').read_text('utf-8')==store.markdown(item)
    client.delete(f'/api/materials/{mid}')
    client.post(f'/api/materials/{mid}/restore',json={})
    assert store.get(mid)['processing']=='later'
    client.post(f'/api/materials/{mid}/status',json={'state':'pending'})
    assert client.get('/api/materials?platform=x&state=pending').json()['items'][0]['id']==mid

def test_later_survives_collection_and_does_not_claim_complete(local):
    client,_=local
    mid=material(client,'https://www.bilibili.com/video/BVabc123',text='')
    client.post(f'/api/materials/{mid}/status',json={'state':'later'})
    service.save_content(mid,{'title':'仍需核实的视频','body':'简介','collection':'partial','content':{'warning':'未取得字幕'}})
    assert store.get(mid)['processing']=='later'
    assert client.post(f'/api/materials/{mid}/status',json={'state':'done'}).status_code==400
    assert client.post(f'/api/materials/{mid}/status',json={'state':'pending','revision':1}).status_code==409
    with store.db() as c:
        details=[json.loads(r[0]) for r in c.execute("SELECT detail FROM events WHERE material_id=? AND kind='processing_changed'",(mid,))]
    assert details==[{'from':'pending','state':'later'}]

def test_platform_directory_migration_preserves_originals_images_and_history(local):
    client,_=local
    mid=material(client,'https://x.com/i/status/12345678')
    organized=store.material_folder(mid)
    assert organized==store.DATA/'materials'/'x'/mid
    image=organized/'capture-fixture'/'images'/'a.png'
    image.parent.mkdir(parents=True); image.write_bytes(b'archived image fixture')
    original_hash=store.digest_bytes((organized/'material.md').read_bytes())
    revision=store.get(mid)['revision']
    legacy=store.DATA/'materials'/mid
    organized.rename(legacy)
    store.organize_material_files()
    assert not legacy.exists() and image.read_bytes()==b'archived image fixture'
    assert store.digest_bytes((organized/'material.md').read_bytes())==original_hash
    store.organize_material_files()
    assert (organized/f'revision-{revision}.md').exists()
    with pytest.raises(ValueError): store.material_folder('../outside','x')

def test_trash_cancels_jobs_and_inflight_save_cannot_restore(local):
    client,_=local
    mid=material(client,'https://www.bilibili.com/video/BVabc123',text='')
    client.delete(f'/api/materials/{mid}')
    with store.db() as c:assert c.execute('SELECT state FROM jobs WHERE material_id=?',(mid,)).fetchone()[0]=='cancelled'
    service.save_content(mid,{'title':'途中取得的内容','body':'完整原文','content':{},'collection':'ready'})
    assert store.get(mid)['trashed'] and store.get(mid)['collection']=='paused'
    assert not client.get('/api/materials?platform=bilibili').json()['items']

def test_pasted_incomplete_link_retries_only_that_item(local):
    client,_=local
    url='https://www.douyin.com/video/12345678';mid=material(client,url,text='')
    with store.db() as c:
        c.execute("UPDATE materials SET collection='paused' WHERE id=?",(mid,))
        c.execute("UPDATE jobs SET state='paused' WHERE material_id=?",(mid,))
    # Observing the same reference in a collection must not restart a paused batch.
    assert service.add({'url':url,'origin':'favorite'})['duplicate']
    with store.db() as c:assert c.execute("SELECT count(*) FROM jobs WHERE state='queued'").fetchone()[0]==0
    result=client.post('/api/materials',json={'url':url}).json()
    assert result['id']==mid and result['retried'] and store.get(mid)['collection']=='queued'
    with store.db() as c:
        assert c.execute("SELECT count(*) FROM jobs WHERE state='paused'").fetchone()[0]==1
        assert c.execute("SELECT count(*) FROM jobs WHERE state='queued'").fetchone()[0]==1

def test_missing_failed_and_machine_states_are_distinct(local):
    client,_=local
    mid=material(client,'https://www.bilibili.com/video/BVabc123',text='')
    assert client.get(f'/api/materials/{mid}').json()['transcript_state']=='queued'
    content={};video_pipeline.transcription_failure(content,ValueError('媒体无法下载'))
    service.save_content(mid,{'title':'视频夹具','body':'说明不是字幕','content':content,'collection':'partial'})
    assert client.get(f'/api/materials/{mid}').json()['transcript_state']=='failed'
    assert client.get('/api/materials?platform=bilibili&capture=failed').json()['items'][0]['id']==mid
    video_pipeline.transcription_failure(content,video_pipeline.NoSpeech('未识别出可用语音'))
    assert store.transcript_status('bilibili','partial',content)=='no_speech'
    content.update(segments=[{'start':0,'end':4,'text':'真实语音记录夹具'}],transcription={'model':'turbo'})
    service.save_content(mid,{'title':'视频夹具','body':'视频说明','content':content,'collection':'ready'})
    item=client.get('/api/materials?platform=bilibili&capture=transcribed').json()['items'][0]
    assert item['transcript_state']=='machine' and item['transcription_model']=='turbo'

def test_x_session_is_default_and_does_not_need_paid_client(local,monkeypatch):
    client,config=local
    sessions.path('x').parent.mkdir(parents=True,exist_ok=True);sessions.path('x').write_bytes(b'fixture')
    monkeypatch.setattr(sessions,'load',lambda kind:{'cookies':[{'name':'auth_token','value':'fixture'},{'name':'ct0','value':'fixture'}]})
    response=client.post('/api/favorites',json={'platform':'x'})
    assert response.status_code==200 and not config.get('x_client_id')
    assert sessions.status('x')['read_mode']=='session'

def test_x_seed_is_saved_atomically_before_detail_can_fail(local,monkeypatch):
    client,_=local
    seed={'url':'https://x.com/i/status/12345678','title':'收藏夹具','body':'原文\n![图](https://pbs.twimg.com/photo.jpg)',
          'content':{'source':'X 书签列表','warning':'详情尚未读取'},'collection':'partial'}
    def pages(kind,url,record,progress,cancelled):
        record(seed);yield progress
        raise ValueError('分页失败夹具')
    monkeypatch.setattr(platform_browser,'favorites',pages)
    with store.db() as c:jid=store.enqueue(c,'favorites',{'platform':'x','url':'https://x.com/i/bookmarks'})
    with pytest.raises(ValueError):service.run_job({'id':jid,'kind':'favorites','material_id':None,'payload':json.dumps({'platform':'x','url':'https://x.com/i/bookmarks'}),'progress':'{}'})
    with store.db() as c:
        row=c.execute('SELECT body FROM materials').fetchone()
        payload=json.loads(c.execute("SELECT payload FROM jobs WHERE kind='collect'").fetchone()[0])
    assert row['body']==seed['body'] and payload['x_seed']['body']==seed['body']

def test_x_all_workers_share_pace_and_only_read(local,monkeypatch):
    delays=[]
    monkeypatch.setattr(xbookmarks,'NEXT_REQUEST',0)
    monkeypatch.setattr(xbookmarks.time,'monotonic',lambda:100)
    monkeypatch.setattr(xbookmarks.time,'time',lambda:1000)
    monkeypatch.setattr(xbookmarks.random,'uniform',lambda low,high:10)
    async def sleep(delay):delays.append(delay)
    monkeypatch.setattr(xbookmarks.asyncio,'sleep',sleep)
    asyncio.run(xbookmarks.pace(SimpleNamespace(method='GET')))
    asyncio.run(xbookmarks.pace(SimpleNamespace(method='GET')))
    assert delays==[10]
    with pytest.raises(ValueError,match='只允许读取'):asyncio.run(xbookmarks.pace(SimpleNamespace(method='POST')))

def test_x_rate_limit_pauses_other_jobs_and_survives_restart(local):
    client,_=local
    mid=material(client,'https://x.com/i/status/12345678',text='')
    with pytest.raises(ValueError,match='HTTP 429'):asyncio.run(xbookmarks.check_response(SimpleNamespace(status_code=429)))
    assert store.get(mid)['collection']=='paused'
    xbookmarks.BLOCKED.clear()
    with pytest.raises(ValueError,match='HTTP 429'):asyncio.run(xbookmarks.pace(SimpleNamespace(method='GET')))
    store.init()
    with store.db() as c:assert c.execute('SELECT state FROM jobs WHERE material_id=?',(mid,)).fetchone()[0]=='paused'
    xbookmarks.clear_block()
    assert not xbookmarks.blocked_reason()

def test_job_history_surfaces_recent_progress_before_newer_waiting_jobs(local):
    client,_=local
    old=material(client,'https://x.com/i/status/12345678',text='')
    material(client,'https://x.com/i/status/12345679',text='')
    with store.db() as c:
        c.execute("UPDATE jobs SET created='2026-01-02',updated='2026-01-02'")
        c.execute("UPDATE jobs SET created='2026-01-01',updated='2026-01-03',state='running' WHERE material_id=?",(old,))
    jobs=client.get('/api/jobs').json()
    assert jobs[0]['material_id']==old and jobs[0]['state']=='running'
