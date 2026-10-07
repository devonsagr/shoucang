import json
from pathlib import Path
import pytest
from app import knowledge,service,store
from test_knowledge import local,material

def annotate(client,mid,text):
    response=client.put(f'/api/materials/{mid}/notes',json={'revision':store.get(mid)['revision'],'notes':text})
    assert response.status_code==200

def submit(client,mid,second=False):
    return client.post(f'/api/materials/{mid}/ai',json={'from_annotation':True,'second_pass':second,'revision':store.get(mid)['revision']})

def run_model(client,mid,monkeypatch,text):
    response=submit(client,mid,second=bool(store.get(mid)['summary']));assert response.status_code==200,response.text
    with store.db() as c:job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(response.json()['job_id'],)).fetchone())
    calls=[]
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'choices':[{'message':{'content':text}}]}
    monkeypatch.setattr(service.httpx,'post',lambda *args,**kwargs:(calls.append(kwargs['json']) or Response()))
    service.run_job(job)
    with store.db() as c:c.execute("UPDATE jobs SET state='done' WHERE id=?",(job['id'],))
    return calls

def review(client,mid):
    item=client.get('/api/materials/'+mid).json()
    result=client.post(f'/api/materials/{mid}/ai-review',json={'revision':item['revision'],'summary_hash':item['ai_review']['summary_hash']})
    assert result.status_code==200

def test_annotation_result_review_second_pass_and_final_confirm(local,monkeypatch):
    client,vault,config=local;mid=material(client)
    config.update(ai_model='synthetic-model',ai_api_key='fixture-key')
    annotate(client,mid,'我想做工具，帮我保留可操作方法和限制。')
    first=run_model(client,mid,monkeypatch,'第一遍合成结果：先验证方法和限制。')
    assert '用户批注' in first[0]['messages'][1]['content'] and '保留可操作方法' in first[0]['messages'][1]['content']
    assert '本次内容整理的重点' in first[0]['messages'][0]['content']
    item=store.get(mid);assert item['processing']=='review' and not knowledge.review(item)['reviewed']
    listing=client.get('/api/materials?state=review').json();assert listing['items'][0]['id']==mid
    assert listing['counts']['review']==1 and listing['counts']['pending']==listing['counts']['done']==0
    paths=client.get(f'/api/materials/{mid}/processing-paths').json()
    pool=Path(paths['local_review']);assert pool.read_text('utf-8').count('第一遍合成结果')==1
    assert Path(paths['local_source']).exists() and Path(paths['vault_review_folder'])==vault/'收藏处理器'/'01_AI待查看'
    assert not (vault/'收藏处理器').exists(),'generation must not automatically write the real or fixture Vault'
    assert submit(client,mid,second=True).status_code==400
    review(client,mid);annotate(client,mid,'审查意见：保留限制，并与第一遍内容对照。')
    assert '尚未用于上述结果' in pool.read_text('utf-8')
    second=run_model(client,mid,monkeypatch,'第二遍合成结果：根据审查意见补充限制。')
    assert '第一遍合成结果' in second[0]['messages'][1]['content'] and '审查意见' in second[0]['messages'][1]['content']
    item=store.get(mid);assert item['content']['ai_workflow']['pass']==2 and not knowledge.review(item)['reviewed']
    p=client.post(f'/api/materials/{mid}/push-preview',json={'destination':'obsidian','complete_processing':False,'shelf_output':{'stage':'ai_review'}}).json()
    assert Path(p['destination']).parent==vault/'收藏处理器'/'01_AI待查看'
    assert '审查意见' in p['shelf_markdown'] and '第二遍合成结果' in p['shelf_markdown']
    assert client.post(f'/api/pushes/{p["id"]}/confirm',json={'hash':p['hash']}).status_code==200
    assert store.get(mid)['processing']=='review'
    review(client,mid)
    p2=client.post(f'/api/materials/{mid}/push-preview',json={'destination':'obsidian','knowledge_output':{'folder':'06_资料与教程','title':'审查后的知识','text':'我选择留下的方法与限制'}}).json()
    assert client.post(f'/api/pushes/{p2["id"]}/confirm',json={'hash':p2['hash']}).status_code==200
    assert store.get(mid)['processing']=='done' and not Path(p['destination']).exists() and pool.exists()
    assert Path(p2['destination']).exists() and (store.DATA/'outbox'/'obsidian'/p['id']/'shelf.md').exists()

def test_blank_annotation_and_missing_model_never_fake_a_job(local):
    client,_,config=local;mid=material(client)
    config.update(ai_model='fixture',ai_api_key='fixture')
    assert submit(client,mid).status_code==400
    annotate(client,mid,'这条先留备注')
    config.pop('ai_api_key')
    assert submit(client,mid).status_code==400
    assert store.get(mid)['notes']=='这条先留备注' and store.get(mid)['processing']=='pending'
    with store.db() as c:assert not c.execute("SELECT 1 FROM jobs WHERE kind='ai'").fetchone()

def test_changed_queued_annotation_never_calls_model(local,monkeypatch):
    client,_,config=local;mid=material(client);config.update(ai_model='fixture',ai_api_key='fixture')
    annotate(client,mid,'旧批注');result=submit(client,mid)
    with store.db() as c:job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(result.json()['job_id'],)).fetchone())
    annotate(client,mid,'新批注')
    monkeypatch.setattr(service.httpx,'post',lambda *args,**kwargs:pytest.fail('must not send a stale annotation'))
    with pytest.raises(ValueError,match='排队后'):service.run_job(job)
    assert not store.get(mid)['summary'] and not (store.DATA/'review').exists()

def test_changed_annotation_during_generation_keeps_old_result_in_history(local,monkeypatch):
    client,_,config=local;mid=material(client);config.update(ai_model='fixture',ai_api_key='fixture')
    annotate(client,mid,'原批注');result=submit(client,mid)
    with store.db() as c:job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(result.json()['job_id'],)).fetchone())
    class Response:
        def raise_for_status(self):pass
        def json(self):
            annotate(client,mid,'生成中改了批注')
            return {'choices':[{'message':{'content':'旧批注生成的结果'}}]}
    monkeypatch.setattr(service.httpx,'post',lambda *args,**kwargs:Response())
    with pytest.raises(ValueError,match='生成期间'):service.run_job(job)
    assert not store.get(mid)['summary'] and store.get(mid)['notes']=='生成中改了批注'
    with store.db() as c:assert c.execute("SELECT 1 FROM events WHERE material_id=? AND kind='ai_stale_result'",(mid,)).fetchone()

def test_purge_removes_exclusive_review_projection(local,monkeypatch):
    client,_,config=local;mid=material(client);config.update(ai_model='fixture',ai_api_key='fixture')
    annotate(client,mid,'仅为彻底删除验收的批注');run_model(client,mid,monkeypatch,'删除夹具结果')
    pool=store.DATA/'review'/(mid+'.md');assert pool.exists()
    client.delete('/api/materials/'+mid)
    result=store.purge(mid,store.get(mid)['revision'],'彻底删除')
    assert result['purged'] and not pool.exists()
