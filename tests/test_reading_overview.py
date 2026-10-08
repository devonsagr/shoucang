import json
from types import SimpleNamespace
import pytest
from app import overview,service,store
from test_automatic_collection import local

TEXT='这份合成文章介绍怎样用任务队列保存收集进度，以及如何区分列表读取和正文处理。\n\n关闭窗口不会停止持久化队列，重新打开后可以查看任务进度。\n\n所有材料保留原文，个人批注是后续整理的依据。顶栏任务面板可以同时显示来自不同平台的收集和转写状态，失败后也不会丢失历史记录。'

def create(client):return service.add({'url':'https://example.org/overview-fixture','title':'队列工作原理 · 合成材料','text':TEXT},enqueue_collect=False)['id']
def job(jid):
    with store.db() as c:return dict(c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
def model(config):config.update(ai_base_url='http://127.0.0.1:11434/v1',ai_model='synthetic-model',ai_api_key='')
def fake_model(monkeypatch,callback=None):
    calls=[]
    class Client:
        def __init__(self,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kw):
            calls.append((url,kw))
            if callback:callback(len(calls))
            return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'choices':[{'message':{'content':'这份合成材料解释了持久化队列如何让收藏读取和正文处理分开运行，窗口关闭后任务仍可追溯。'}}]})
    monkeypatch.setattr(overview.httpx,'Client',Client)
    return calls

def test_default_reading_and_missing_model_do_not_make_any_model_request(local,monkeypatch):
    client,_=local;mid=create(client)
    monkeypatch.setattr(overview.httpx,'Client',lambda **kw:pytest.fail('没有主动配置不得调用模型'))
    result=client.get('/api/materials/'+mid).json()
    assert result['reading_preview']['model_used'] is False and result['reading_overview'] is None
    assert client.post('/api/materials/'+mid+'/overview',json={}).status_code==400
    with store.db() as c:assert c.execute("SELECT count(*) FROM jobs WHERE kind='overview'").fetchone()[0]==0

def test_overview_is_deduplicated_reading_only_and_never_changes_processing_inputs(local,monkeypatch):
    client,config=local;model(config);mid=create(client)
    with store.db() as c:c.execute("UPDATE materials SET notes='PRIVATE-NOTE',summary='PRIVATE-PROCESSED',processing='later',content_json=? WHERE id=?",(store.dumps({'comments':[{'body':'COMMENT-NOT-INPUT'}],'knowledge_context':{'notes':[{'path':'合成测试/关联.md','title':'合成关联','text':'KNOWLEDGE-NOT-INPUT'}]}}),mid))
    before=store.get(mid);calls=fake_model(monkeypatch)
    first=client.post('/api/materials/'+mid+'/overview',json={}).json();same=client.post('/api/materials/'+mid+'/overview',json={}).json()
    assert same['job_id']==first['job_id'] and same['duplicate']
    service.run_job(job(first['job_id']))
    assert store.get(mid)==before and overview.current(before)['reading_only']
    request=json.dumps(calls[0][1],ensure_ascii=False)
    assert 'PRIVATE-NOTE' not in request and 'PRIVATE-PROCESSED' not in request and 'COMMENT-NOT-INPUT' not in request and 'KNOWLEDGE-NOT-INPUT' not in request
    assert not calls[0][1]['headers'] and len(calls)==1
    assert client.post('/api/materials/'+mid+'/overview',json={}).json()['cached']
    export=client.post('/api/materials/'+mid+'/push-preview',json={'destination':'markdown','complete_processing':True}).json()
    assert 'reading_overview' not in str(export) and '这份合成材料解释了持久化队列' not in str(export)

def test_source_change_during_generation_cannot_commit_the_old_overview(local,monkeypatch):
    client,config=local;model(config);mid=create(client)
    def change(_):
        with store.db() as c:c.execute("UPDATE materials SET body='另一份原文' WHERE id=?",(mid,))
    fake_model(monkeypatch,change);queued=client.post('/api/materials/'+mid+'/overview',json={}).json()
    with pytest.raises(ValueError,match='变化'):service.run_job(job(queued['job_id']))
    assert overview.current(store.get(mid)) is None

def test_changed_engine_is_rejected_before_any_text_is_sent(local,monkeypatch):
    client,config=local;model(config);mid=create(client)
    queued=client.post('/api/materials/'+mid+'/overview',json={}).json();config['ai_model']='different-model'
    monkeypatch.setattr(overview.httpx,'Client',lambda **kw:pytest.fail('配置已改变，不得发起请求'))
    with pytest.raises(ValueError,match='设置已变化'):service.run_job(job(queued['job_id']))

def test_long_source_includes_the_tail_and_then_combines_all_parts(local,monkeypatch):
    client,config=local;model(config);mid=create(client)
    body=('原文事实。'*4000)+'全文最后的独立事实，不得遗漏。'
    with store.db() as c:c.execute('UPDATE materials SET body=? WHERE id=?',(body,mid))
    calls=fake_model(monkeypatch);queued=client.post('/api/materials/'+mid+'/overview',json={}).json();service.run_job(job(queued['job_id']))
    assert len(calls)==3 and '全文最后的独立事实' in calls[1][1]['json']['messages'][1]['content']
    assert '各段概要' in calls[2][1]['json']['messages'][1]['content']

def test_purge_removes_overview_and_old_source_does_not_reuse_it(local,monkeypatch):
    client,config=local;model(config);mid=create(client);fake_model(monkeypatch)
    queued=client.post('/api/materials/'+mid+'/overview',json={}).json();service.run_job(job(queued['job_id']))
    client.delete('/api/materials/'+mid)
    assert client.post('/api/materials/'+mid+'/purge',json={'revision':store.get(mid)['revision'],'confirmation':'彻底删除'}).status_code==200
    with store.db() as c:assert not c.execute('SELECT 1 FROM reading_overviews WHERE material_id=?',(mid,)).fetchone()


def test_remote_engine_requires_explicit_key_and_cached_result_becomes_stale(local,monkeypatch):
    client,config=local;mid=create(client)
    config.update(ai_base_url='https://model.example.org/v1',ai_model='synthetic-model',ai_api_key='')
    assert client.post('/api/materials/'+mid+'/overview',json={}).status_code==400
    config['ai_api_key']='synthetic-not-a-real-key';calls=fake_model(monkeypatch)
    queued=client.post('/api/materials/'+mid+'/overview',json={}).json();service.run_job(job(queued['job_id']))
    assert calls[0][1]['headers']=={'Authorization':'Bearer synthetic-not-a-real-key'}
    assert overview.current(store.get(mid))['source']=='AI概要'
    with store.db() as c:c.execute('UPDATE materials SET body=? WHERE id=?',('修改后的原文',mid))
    assert client.get('/api/materials/'+mid).json()['reading_overview'] is None

def test_malformed_empty_model_response_has_a_readable_error(local,monkeypatch):
    client,config=local;model(config);mid=create(client)
    class Empty:
        def __init__(self,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*a,**kw):return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'choices':[]})
    monkeypatch.setattr(overview.httpx,'Client',Empty)
    queued=client.post('/api/materials/'+mid+'/overview',json={}).json()
    with pytest.raises(ValueError,match='格式无效'):service.run_job(job(queued['job_id']))
    assert overview.current(store.get(mid)) is None

def test_config_change_during_response_cannot_save_or_send_again(local,monkeypatch):
    client,config=local;model(config);mid=create(client)
    calls=fake_model(monkeypatch,lambda _:config.update(ai_base_url='https://other.example.org/v1'))
    queued=client.post('/api/materials/'+mid+'/overview',json={}).json()
    with pytest.raises(ValueError,match='设置已变化'):service.run_job(job(queued['job_id']))
    assert len(calls)==1 and overview.current(store.get(mid)) is None

def test_title_only_and_oversize_sources_do_not_fake_a_complete_overview(local):
    client,config=local;model(config);mid=create(client)
    with store.db() as c:c.execute("UPDATE materials SET body='' WHERE id=?",(mid,))
    assert client.post('/api/materials/'+mid+'/overview',json={}).status_code==400
    with store.db() as c:c.execute('UPDATE materials SET body=? WHERE id=?',('合成文本'*50000,mid))
    result=client.post('/api/materials/'+mid+'/overview',json={})
    assert result.status_code==400 and '未截断原文' in result.json()['detail']


@pytest.mark.parametrize('error,message',[(overview.httpx.ConnectError('synthetic'),'未连上概要模型'),(overview.httpx.ReadTimeout('synthetic'),'响应超时')])
def test_unreachable_model_is_reported_without_losing_material(local,monkeypatch,error,message):
    client,config=local;model(config);mid=create(client);before=store.get(mid)
    def fail(_):raise error
    fake_model(monkeypatch,fail)
    queued=client.post('/api/materials/'+mid+'/overview',json={}).json()
    with pytest.raises(ValueError,match=message):service.run_job(job(queued['job_id']))
    assert store.get(mid)==before and overview.current(before) is None
