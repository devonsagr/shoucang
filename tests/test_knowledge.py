import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app import knowledge,main,service,store

@pytest.fixture
def local(tmp_path,monkeypatch):
    vault=tmp_path/'test-vault';vault.mkdir()
    for folder in ('01_索引','06_资料与教程','08_专辑学习积累','.obsidian','04_Vibecoding项目'):(vault/folder).mkdir()
    (vault/'06_资料与教程'/'已有AI理解.md').write_text('# 已有AI理解\n\n已有观点：先验证再使用。','utf-8')
    (vault/'08_专辑学习积累'/'已有音乐理解.md').write_text('# 已有音乐理解\n\n这是另一类知识。','utf-8')
    (vault/'AGENTS.md').write_text('不能作为普通笔记读取','utf-8')
    config={'obsidian_vault':str(vault),'knowledge_targets':['06_资料与教程','08_专辑学习积累']}
    monkeypatch.setattr(store,'ROOT',tmp_path);monkeypatch.setattr(store,'DATA',tmp_path/'data')
    monkeypatch.setattr(store,'settings',lambda:config.copy())
    monkeypatch.setattr(service,'worker',lambda:None);monkeypatch.setattr(service,'favorites_worker',lambda:None)
    with TestClient(main.app,headers={'X-Local-Request':'1'}) as client:yield client,vault,config

def material(client):
    mid=client.post('/api/materials',json={'url':'https://example.org/knowledge-fixture','text':'AI 工作流的新材料，保留原文。','title':'合成验收：联系已有知识'}).json()['id']
    return mid

def associate(client,mid):
    return client.put(f'/api/materials/{mid}/knowledge-context',json={'paths':['06_资料与教程/已有AI理解.md'],'revision':store.get(mid)['revision']})

def preview(client,mid,complete=True):
    folders=client.get(f'/api/materials/{mid}/knowledge-folders').json()
    response=client.post(f'/api/materials/{mid}/push-preview',json={'destination':'obsidian','complete_processing':complete,
        'knowledge_output':{'title':'新的AI实践判断','text':'我的理解：应先小范围验证。\n\n- [ ] 验证建议（尚未执行）','folder':folders[0]['path']}})
    assert response.status_code==200,response.text
    return response.json()

def test_explicit_directory_browse_never_reads_bodies_or_recurses(local,monkeypatch):
    client,vault,_=local
    (vault/'06_资料与教程'/'子目录').mkdir();(vault/'06_资料与教程'/'子目录'/'深层.md').write_text('不能被目录搜索读取','utf-8')
    monkeypatch.setattr(knowledge,'read',lambda *args:pytest.fail('title browsing must not read note bodies'))
    root=client.get('/api/vault/notes').json()
    assert '.obsidian' not in [d['title'] for d in root['directories']] and root['notes']==[]
    data=client.get('/api/vault/notes',params={'folder':'06_资料与教程','query':'AI'}).json()
    assert [n['title'] for n in data['notes']]==['已有AI理解']
    assert [d['title'] for d in data['directories']]==['子目录']

@pytest.mark.parametrize('path',['../secret.md','.obsidian/secret.md','AGENTS.md','HARNESS.md','04_Vibecoding项目/../secret.md','C:/secret.md','06_资料与教程\\secret.md'])
def test_paths_are_scoped_and_metadata_is_not_readable(local,path):
    client,_,_=local
    assert client.get('/api/vault/note',params={'path':path}).status_code==400

def test_relation_preserves_original_status_and_user_understanding_on_refresh(local):
    client,_,_=local;mid=material(client)
    client.put(f'/api/materials/{mid}/notes',json={'notes':'我的新理解','revision':store.get(mid)['revision']})
    client.post(f'/api/materials/{mid}/status',json={'state':'later'})
    before=store.get(mid);response=associate(client,mid);assert response.status_code==200
    after=store.get(mid)
    for key in ('body','notes','summary','collection','processing','updated'):assert after[key]==before[key]
    assert '[[06_资料与教程/已有AI理解|已有AI理解]]' in store.markdown(after)
    service.save_content(mid,{'title':after['title'],'body':after['body'],'content':{'source':'重新采集夹具'},'collection':'ready'},preserve_processing=True)
    assert store.get(mid)['content']['knowledge_context']==after['content']['knowledge_context']
    assert client.put(f'/api/materials/{mid}/knowledge-context',json={'paths':[],'revision':before['revision']}).status_code==400

def test_edit_knowledge_then_preview_confirm_is_a_real_additive_vault_flow(local):
    client,vault,_=local;mid=material(client);associate(client,mid)
    old=(vault/'06_资料与教程'/'已有AI理解.md').read_bytes();before=store.get(mid)
    p=preview(client,mid,complete=False)
    target=Path(p['destination']);source=Path(p['source_destination'])
    assert '06_资料与教程' in str(target) and source.parent==target.parent
    assert not target.exists() and not source.exists() and not (store.DATA/'outbox').exists()
    assert '我的理解：应先小范围验证' in p['knowledge_markdown']
    assert '[[06_资料与教程/已有AI理解|已有AI理解]]' in p['knowledge_markdown']
    assert p['payload']['knowledge_output']['source_note'].removesuffix('.md') in p['knowledge_markdown']
    assert client.post(f'/api/pushes/{p["id"]}/confirm',json={'hash':'wrong'}).status_code==400
    result=client.post(f'/api/pushes/{p["id"]}/confirm',json={'hash':p['hash']});assert result.status_code==200,result.text
    assert target.read_text('utf-8')==p['knowledge_markdown']
    assert source.read_text('utf-8')==p['markdown']
    assert len(list(source.parent.glob('*.md')))==2
    assert store.get(mid)['body']==before['body'] and store.get(mid)['processing']=='pending'
    assert (vault/'06_资料与教程'/'已有AI理解.md').read_bytes()==old
    assert client.post(f'/api/pushes/{p["id"]}/confirm',json={'hash':p['hash']}).json()['duplicate']
    assert len(list((vault/'06_资料与教程').glob('材料/可调用资料/新的AI实践判断--*/index.md')))==1
    package=store.DATA/'outbox'/'obsidian'/p['id']
    assert (package/'knowledge.md').read_text('utf-8')==p['knowledge_markdown']

def test_conflicts_or_changed_reference_stop_before_any_export(local):
    client,vault,_=local;mid=material(client);associate(client,mid);p=preview(client,mid)
    file=Path(p['destination']);file.parent.mkdir(parents=True,exist_ok=True);file.write_text('用户改写的知识笔记','utf-8')
    assert client.post(f'/api/pushes/{p["id"]}/confirm',json={'hash':p['hash']}).status_code==400
    assert file.read_text('utf-8')=='用户改写的知识笔记' and not (store.DATA/'outbox').exists()
    file.unlink();(vault/'06_资料与教程'/'已有AI理解.md').write_text('用户更新了关联知识','utf-8')
    assert client.post(f'/api/pushes/{p["id"]}/confirm',json={'hash':p['hash']}).status_code==400
    assert not file.exists() and not (store.DATA/'outbox').exists() and store.get(mid)['processing']=='pending'

def test_ai_only_reads_selected_notes_after_explicit_knowledge_flag(local,monkeypatch):
    client,vault,config=local;mid=material(client);associate(client,mid)
    config.update(ai_model='model-fixture',ai_api_key='secret-fixture')
    note=vault/'06_资料与教程'/'已有AI理解.md';note.write_text('已有知识证据 '*2000,'utf-8');associate(client,mid)
    response=client.post(f'/api/materials/{mid}/ai',json={'include_knowledge':True});assert response.status_code==200
    with store.db() as c:job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(response.json()['job_id'],)).fetchone())
    payload=json.loads(job['payload']);assert len(payload['knowledge_notes'])==1
    assert payload['knowledge_notes'][0]['excerpt'] and len(payload['knowledge_notes'][0]['text'])==6000
    calls=[]
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'choices':[{'message':{'content':'合成模型结果：新材料补充已有观点，建议尚未执行。'}}]}
    monkeypatch.setattr(service.httpx,'post',lambda *args,**kwargs:(calls.append(kwargs['json']) or Response()))
    service.run_job(job)
    joined=store.dumps(calls)
    assert '已有知识证据' in joined and '已有音乐理解' not in joined
    assert '相互矛盾' in calls[0]['messages'][0]['content']
    assert 'secret-fixture' not in joined and '结合 1 篇' in store.get(mid)['summary']
    assert store.get(mid)['processing']=='pending' and not (vault/'知识库').exists()

def test_no_context_and_non_knowledge_targets_cannot_fake_integration(local):
    client,_,config=local;mid=material(client)
    config.update(ai_model='fixture',ai_api_key='fixture')
    assert client.post(f'/api/materials/{mid}/ai',json={'include_knowledge':True}).status_code==400
    for folder in ('系统/行动','04_Vibecoding项目','../escaped'):
        assert client.post(f'/api/materials/{mid}/push-preview',json={'destination':'obsidian',
            'knowledge_output':{'title':'知识','text':'实际正文','folder':folder}}).status_code==400
    assert client.post(f'/api/materials/{mid}/push-preview',json={'destination':'todo',
        'knowledge_output':{'title':'知识','text':'实际正文','folder':'06_资料与教程'}}).status_code==400

def test_unusual_note_names_keep_a_valid_exact_reference(local):
    assert knowledge.link('06_资料与教程/AI#1.md','AI#1')=='[AI#1](06_%E8%B5%84%E6%96%99%E4%B8%8E%E6%95%99%E7%A8%8B/AI%231.md)'

def test_original_archive_conflict_is_checked_before_creating_result_or_outbox(local):
    client,_,_=local;mid=material(client);associate(client,mid);p=preview(client,mid)
    source=Path(p['source_destination']);source.parent.mkdir(parents=True);source.write_text('云端人工修改的存档','utf-8')
    result=client.post(f'/api/pushes/{p["id"]}/confirm',json={'hash':p['hash']})
    assert result.status_code==400 and not Path(p['destination']).exists() and not (store.DATA/'outbox').exists()
    assert source.read_text('utf-8')=='云端人工修改的存档'

def test_ai_result_is_kept_out_of_current_summary_when_selected_note_changes(local,monkeypatch):
    client,vault,config=local;mid=material(client);associate(client,mid)
    config.update(ai_model='fixture',ai_api_key='fixture')
    snapshot=knowledge.context(store.get(mid))
    class Response:
        def raise_for_status(self):pass
        def json(self):
            (vault/'06_资料与教程'/'已有AI理解.md').write_text('AI生成时用户更新笔记','utf-8')
            return {'choices':[{'message':{'content':'旧知识版本的AI结果'}}]}
    monkeypatch.setattr(service.httpx,'post',lambda *args,**kwargs:Response())
    with pytest.raises(ValueError,match='生成期间'):service.ai_summary(mid,snapshot)
    assert not store.get(mid)['summary']
    with store.db() as c:assert c.execute("SELECT count(*) FROM events WHERE material_id=? AND kind='ai_stale_result'",(mid,)).fetchone()[0]==1

def test_stale_vault_configuration_does_not_prevent_clearing_local_links(local):
    client,vault,config=local;mid=material(client);associate(client,mid)
    config['obsidian_vault']=str(vault/'missing')
    response=client.put(f'/api/materials/{mid}/knowledge-context',json={'paths':[],'revision':store.get(mid)['revision']})
    assert response.status_code==200 and store.get(mid)['content']['knowledge_context']['notes']==[]
