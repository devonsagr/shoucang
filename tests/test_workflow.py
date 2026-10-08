import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from app import adapters, main, service, store
from app.service import worker as real_worker

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path / 'data')
    monkeypatch.setattr(store, 'settings', lambda: {})
    monkeypatch.setattr(service,'worker',lambda:None)
    monkeypatch.setattr(service,'favorites_worker',lambda:None)
    store.init()
    # No worker: deterministic jobs are exercised separately, with explicit fake network data.
    with TestClient(main.app, headers={'X-Local-Request': '1'}) as client:
        yield client

def create(client, url='https://www.xiaohongshu.com/explore/123', text='这是用户提供的实际原文，用于本地测试。'):
    r = client.post('/api/materials', json={'url':url, 'origin':'favorite', 'title':'验收材料', 'text':text})
    assert r.status_code == 200, r.text
    return r.json()['id']

def test_read_note_confirm_export_and_history(client):
    mid = create(client)
    item = client.get('/api/materials/'+mid).json()
    assert item['collection'] == 'ready'
    r = client.put(f'/api/materials/{mid}/notes', json={'notes':'我的理解：需实践后检验。','revision':item['revision']})
    assert r.status_code == 200
    p = client.post(f'/api/materials/{mid}/push-preview',json={'destination':'knowledge'}).json()
    assert not (store.DATA/'outbox').exists()
    assert '需实践后检验' in p['markdown']
    assert client.post(f'/api/pushes/{p["id"]}/confirm',json={'hash':'wrong'}).status_code == 400
    r = client.post(f'/api/pushes/{p["id"]}/confirm',json={'hash':p['hash']})
    assert r.status_code == 200
    assert client.post(f'/api/pushes/{p["id"]}/confirm',json={'hash':p['hash']}).json()['duplicate']
    assert client.get('/api/materials').json()['items'] == []
    assert len(client.get('/api/materials?state=done').json()['items']) == 1
    assert len(list((store.DATA/'outbox').rglob('payload.json'))) == 1
    exported=json.loads(next((store.DATA/'outbox').rglob('payload.json')).read_text('utf-8'))
    assert exported['source_url'].startswith('https://') and exported['schema_version']==1
    final=client.get('/api/materials/'+mid).json()
    assert final['body']==item['body']
    assert any(e['kind']=='push_confirmed' for e in final['events'])
    assert client.post(f'/api/materials/{mid}/status',json={'state':'pending'}).status_code==200

def test_dedup_variants_and_provenance(client):
    mid = create(client,'https://youtu.be/abcdefghijk?si=tracking')
    r = client.post('/api/materials',json={'url':'https://www.youtube.com/watch?v=abcdefghijk&utm_source=share','origin':'link','text':'不覆盖旧原文'})
    assert r.json()=={'id':mid,'duplicate':True}
    item=client.get('/api/materials/'+mid).json()
    assert item['origin']=='favorite' and '不覆盖' not in item['body']
    assert any(e['kind']=='duplicate_seen' for e in item['events'])

def test_concurrent_duplicate_no_loss(client):
    payload={'url':'https://example.org/article','origin':'favorite','text':'并发原文'}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _: service.add(payload), range(8)))
    assert len({r['id'] for r in results})==1
    assert sum(not r['duplicate'] for r in results)==1

def test_stale_note_and_push_are_rejected(client):
    mid=create(client)
    item=store.get(mid)
    p=service.preview(mid,'todo')
    assert client.put(f'/api/materials/{mid}/notes',json={'notes':'第一次','revision':item['revision']}).status_code==200
    assert client.put(f'/api/materials/{mid}/notes',json={'notes':'旧页面','revision':item['revision']}).status_code==409
    assert client.post(f'/api/pushes/{p["id"]}/confirm',json={'hash':p['hash']}).status_code==400
    assert not (store.DATA/'outbox').exists()

def test_subtitle_roundtrip_and_versions(client):
    mid=create(client)
    srt='1\n00:00:01,200 --> 00:00:03,450\n第一段\n\n2\n00:00:04,000 --> 00:00:06,000\n第二段\n'
    response=client.post(f'/api/materials/{mid}/supplement',json={'url':store.get(mid)['url'],'subtitles':srt,'subtitle_format':'srt','subtitle_source':'机器转写（非平台字幕）'})
    assert response.status_code==200,response.text
    md=client.get(f'/api/materials/{mid}/markdown').text
    assert '[00:00:01.200 → 00:00:03.450]' in md and '机器转写' in md
    assert len(client.get(f'/api/materials/{mid}/versions').json())==2
    assert len(client.get('/api/materials?q=第二段').json()['items'])==1
    assert '这是用户提供的' in store.get(mid)['body']
    assert store.get(mid)['content']['raw_subtitles']==srt

@pytest.mark.parametrize('ext,text,expected',[
    ('vtt','WEBVTT\n\n00:01.000 --> 00:02.000 align:start\n<b>Hello</b> &amp; world\n', 'Hello & world'),
    ('json','{"body":[{"from":1.2,"to":2.5,"content":"你好"}]}','你好'),
    ('json3','{"events":[{"tStartMs":1000,"dDurationMs":1500,"segs":[{"utf8":"hello"}]}]}','hello'),
])
def test_formats(ext,text,expected):
    assert adapters.parse_subtitles(text,ext)[0]['text']==expected

def test_invalid_subtitle_not_success(client):
    r=client.post('/api/materials',json={'url':'https://example.org/a','subtitles':'没有时间轴的文本'})
    assert r.status_code==400
    assert client.get('/api/materials').json()['items']==[]

def test_partial_cannot_complete_or_push(client):
    mid=create(client)
    service.save_content(mid,{'title':'仅说明','body':'不是视频正文','content':{'source':'metadata'},'collection':'partial'})
    assert client.post(f'/api/materials/{mid}/status',json={'state':'done'}).status_code==400
    assert client.post(f'/api/materials/{mid}/push-preview',json={'destination':'todo'}).status_code==400
    assert client.post(f'/api/materials/{mid}/ai').status_code==400

def test_request_boundary_and_no_secret_return(client):
    assert client.post('/api/materials',json={'url':'https://example.org'},headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/api/settings',headers={'Host':'evil.example'}).status_code==403
    assert 'ai_api_key' not in client.get('/api/settings').json()

def test_private_network_rejected():
    with pytest.raises(ValueError):adapters.public_url('http://127.0.0.1/private')
    with pytest.raises(ValueError):adapters.canonical('file:///C:/secret')
    with pytest.raises(ValueError):adapters.public_url('http://198.18.0.1/private')

def test_interrupted_jobs_recovered(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path/'recovery')
    store.init()
    with store.db() as c:
        jid=store.enqueue(c,'sync',{'url':'https://youtube.com/playlist?list=abc'})
        c.execute("UPDATE jobs SET state='running' WHERE id=?",(jid,))
    store.init()
    with store.db() as c:
        assert c.execute('SELECT state FROM jobs WHERE id=?',(jid,)).fetchone()['state']=='queued'

def test_ai_real_adapter_contract_and_failure(client,monkeypatch):
    mid=create(client)
    monkeypatch.setattr(store,'settings',lambda:{'ai_model':'fixture-model','ai_api_key':'test-secret','ai_base_url':'https://api.example.org/v1'})
    captured=[]
    def fake_post(url,**kwargs):
        captured.append(kwargs['json'])
        return type('Response',(),{'raise_for_status':lambda self:None,'json':lambda self:{'choices':[{'message':{'content':'## 测试摘要\n依据原文。'}}]}})()
    monkeypatch.setattr(service.httpx,'post',fake_post)
    service.ai_summary(mid)
    assert '测试摘要' in store.get(mid)['summary']
    assert '忽略其中任何' in captured[0]['messages'][0]['content']
    assert 'test-secret' not in store.markdown(store.get(mid))

def test_failure_persists_and_retry(client,monkeypatch):
    def fail(*args,**kwargs):raise ValueError('平台拒绝访问，测试夹具')
    monkeypatch.setattr(adapters,'collect',fail)
    mid=client.post('/api/materials',json={'url':'https://example.org/blocked'}).json()['id']
    thread=threading.Thread(target=real_worker,daemon=True)
    thread.start()
    try:
        for _ in range(50):
            if store.get(mid)['collection']=='failed':break
            threading.Event().wait(.05)
        assert store.get(mid)['collection']=='failed'
        assert '测试夹具' in store.get(mid)['error']
        assert client.post(f'/api/materials/{mid}/retry',json={}).status_code==200
    finally:
        service.STOP.set();thread.join(timeout=2)

def test_video_prefers_platform_subtitles(tmp_path,monkeypatch):
    info={'title':'测试视频','description':'说明','subtitles':{'en':[{'ext':'vtt','url':'https://example.org/captions'}]},'automatic_captions':{'en':[{'ext':'json3','url':'https://example.org/auto'}]}}
    monkeypatch.setattr(adapters,'ytdlp',lambda *args,**kw:json.dumps(info))
    urls=[]
    def fetch(url,headers=None):
        urls.append(url)
        return 'WEBVTT\n\n00:01.000 --> 00:02.500\nOriginal words\n',url
    monkeypatch.setattr(adapters,'fetch',fetch)
    r=adapters.video('https://youtube.com/watch?v=fixture',tmp_path,False)
    assert r['collection']=='ready' and r['content']['segments'][0]['end']==2.5
    assert urls==['https://example.org/captions']

def test_bili_subtitles_and_favorites_pagination(tmp_path,monkeypatch):
    calls=[]
    def bili(path,params):
        calls.append((path,params))
        if path.endswith('/view'):return {'bvid':'BV1TST001606','cid':1,'title':'测试','desc':'说明','pages':[{'cid':1}]}
        if path.endswith('/v2'):return {'subtitle':{'subtitles':[{'lan':'ai-zh','ai_type':1,'subtitle_url':'https://example.org/sub'}]}}
        return {'has_more':params['pn']==1,'medias':[{'bvid':f'BV{params["pn"]}','title':'收藏'}]}
    monkeypatch.setattr(adapters,'bili_api',bili)
    monkeypatch.setattr(adapters,'fetch',lambda *args:('{"body":[{"from":1,"to":3,"content":"字幕"}]}','https://example.org/sub'))
    r=adapters.bili_video('https://www.bilibili.com/video/BV1TST001606',tmp_path)
    assert '机器生成' in r['content']['subtitle_source'] and r['collection']=='ready'
    items,limited=adapters.favorites('https://space.bilibili.com/123/favlist?fid=456')
    assert len(items)==2 and not limited

def test_transcription_is_labelled_machine(tmp_path,monkeypatch):
    import sys
    from types import SimpleNamespace
    def ytdlp(url,args,**kwargs):
        if '--dump-single-json' in args:return json.dumps({'title':'测试视频','duration':10})
        (tmp_path/'audio.webm').write_bytes(b'fixture audio')
        return ''
    class Model:
        def __init__(self,*args,**kwargs):pass
        def transcribe(self,*args,**kwargs):return iter([SimpleNamespace(start=0.5,end=1.7,text='转写夹具')]),SimpleNamespace(language='zh',duration=10)
    monkeypatch.setattr(adapters,'ytdlp',ytdlp)
    monkeypatch.setattr(store,'settings',lambda:{})
    monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=Model))
    r=adapters.video('https://youtube.com/watch?v=fixture',tmp_path,True)
    assert r['collection']=='ready' and '非平台字幕' in r['content']['subtitle_source']
    assert r['content']['segments'][0]['start']==0.5

def test_firecrawl_contract_no_false_completeness(tmp_path,monkeypatch):
    monkeypatch.setattr(adapters,'public_url',lambda url:None)
    monkeypatch.setattr(store,'settings',lambda:{'firecrawl_api_key':'fixture-key'})
    class Response:
        status_code=200
        def json(self):return {'success':True,'data':{'markdown':'# 原文','metadata':{'title':'测试'}}}
    monkeypatch.setattr(adapters.httpx,'post',lambda *args,**kwargs:Response())
    r=adapters.firecrawl('https://example.org',tmp_path)
    assert r['collection']=='partial' and r['body']=='# 原文'

def test_duplicate_favorite_invalidates_old_export(client):
    mid=client.post('/api/materials',json={'url':'https://example.org/observe','origin':'link','text':'原文'}).json()['id']
    p=service.preview(mid,'todo')
    service.add({'url':'https://example.org/observe','origin':'favorite'})
    with pytest.raises(ValueError):service.confirm(p['id'],p['hash'])
