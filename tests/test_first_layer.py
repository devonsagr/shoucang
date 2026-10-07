import base64
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app import main,service,store

@pytest.fixture
def local(tmp_path,monkeypatch):
    vault=tmp_path/'test-vault';vault.mkdir()
    (vault/'06_资料与教程').mkdir()
    config={'obsidian_vault':str(vault)}
    monkeypatch.setattr(store,'ROOT',tmp_path);monkeypatch.setattr(store,'DATA',tmp_path/'data')
    monkeypatch.setattr(store,'settings',lambda:config.copy())
    monkeypatch.setattr(service,'worker',lambda:None);monkeypatch.setattr(service,'favorites_worker',lambda:None)
    with TestClient(main.app,headers={'X-Local-Request':'1'}) as client:
        mid=service.add({'url':'https://x.com/fixture/status/123450','title':'合成验收：两种去向','text':'完整原文，结尾不能丢失。','origin':'favorite'},enqueue_collect=False)['id']
        yield client,vault,mid

def save(client,mid,track,note):
    response=client.put(f'/api/materials/{mid}/notes',json={'notes':note,'annotation_track':track,'revision':store.get(mid)['revision']})
    assert response.status_code==200,response.text
    response=client.post(f'/api/materials/{mid}/push-preview',json={'destination':'obsidian','complete_processing':False,'shelf_output':{'stage':track}})
    assert response.status_code==200,response.text
    return response.json()

def confirm(client,p):
    result=client.post(f'/api/pushes/{p["id"]}/confirm',json={'hash':p['hash']})
    assert result.status_code==200,result.text
    return result.json()['layer_id']

def test_two_notes_become_independent_libraries_without_ai(local,monkeypatch):
    client,vault,mid=local
    monkeypatch.setattr(service.httpx,'post',lambda *a,**k:pytest.fail('First save must never call AI'))
    p=save(client,mid,'callable','以后调用实现方法');assert not Path(p['destination']).exists()
    assert '01_调用资料' in p['destination'] and 'human_digest: false' in p['shelf_markdown']
    callable_id=confirm(client,p)
    other=save(client,mid,'digest','想参透这几个判断');digest_id=confirm(client,other)
    assert '02_消化暂存' in other['destination'] and callable_id!=digest_id
    assert store.get(callable_id)['notes']=='以后调用实现方法'
    assert store.get(digest_id)['notes']=='想参透这几个判断'
    assert store.get(mid)['content']['annotations']=={'callable':'以后调用实现方法','digest':'想参透这几个判断'}
    for item_id in (callable_id,digest_id):
        assert store.get(item_id)['summary']=='' and store.get(item_id)['processing']=='pending'
    assert client.get('/api/materials',params={'state':'pending'}).json()['items']==[]
    raw=client.get('/api/materials',params={'state':'source_archive'}).json()
    assert raw['items'][0]['id']==mid and raw['counts']['callable']==raw['counts']['digest']==1
    client.post(f'/api/materials/{callable_id}/status',json={'state':'later'})
    assert store.get(digest_id)['processing']=='pending' and store.get(mid)['processing']=='pending'
    assert client.get('/api/first-layer',params={'track':'callable','state':'later','q':'调用'}).json()['items'][0]['id']==callable_id
    assert '完整原文，结尾不能丢失。' in Path(p['destination']).read_text('utf-8')

def test_same_route_dedupes_and_new_version_preserves_prior_work(local):
    client,vault,mid=local;p=save(client,mid,'callable','调用用途');old=confirm(client,p)
    client.put(f'/api/materials/{old}/notes',json={'notes':'第二步加工，不是原批注','revision':store.get(old)['revision']})
    duplicate=save(client,mid,'callable','调用用途');assert duplicate['duplicate'] and duplicate['id']==p['id']
    assert confirm(client,duplicate)==old
    updated=save(client,mid,'callable','新的调用用途');new=confirm(client,updated)
    assert new!=old and store.get(old)['notes']=='第二步加工，不是原批注' and not store.get(old)['active']
    assert not Path(p['destination']).exists() and Path(updated['destination']).exists()
    assert not Path(p['destination']).parent.exists()
    assert (store.DATA/'outbox'/'obsidian'/p['id']/'shelf.md').exists(),'old snapshot history remains local'
    assert client.get('/api/first-layer',params={'track':'callable'}).json()['items'][0]['id']==new
    assert client.put(f'/api/materials/{old}/notes',json={'notes':'覆盖','revision':store.get(old)['revision']}).status_code==400

def test_snapshot_images_captions_and_comments_survive_raw_purge(local):
    client,vault,mid=local;folder=store.material_folder(mid)
    image=folder/'assets'/'source.png';image.parent.mkdir(parents=True,exist_ok=True)
    image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z0KsAAAAASUVORK5CYII='))
    service.save_content(mid,{'title':'原文和附件','body':'前文\n\n![帖子图片](assets/source.png)\n\n完整结尾','collection':'ready',
        'content':{'source':'合成验收','media':[{'path':'assets/source.png','status':'saved','source_url':'https://example.org/image.png','sha256':store.digest_bytes(image.read_bytes())}],
                   'subtitle_source':'平台字幕','segments':[{'start':0,'end':120,'text':'完整字幕到两分钟'}],
                   'comments_status':'仅保存夹具回复','comments':[{'author':'fixture','body':'回复及图片\n![回复图](assets/source.png)'}]}})
    p=save(client,mid,'digest','消化字幕');layer=confirm(client,p)
    item=store.get(layer);asset=item['content']['media'][0]['path']
    assert client.get(f'/api/materials/{layer}/images/{asset}').status_code==200
    note=Path(p['destination']).read_text('utf-8')
    assert '完整结尾' in note and '完整字幕到两分钟' in note and '回复及图片' in note
    assert '](assets/' in note and 'assets/source.png)' not in note
    assert len(list(Path(p['destination']).parent.glob('assets/*.png')))==1
    client.delete(f'/api/materials/{mid}')
    assert client.get('/api/materials',params={'state':'trash'}).json()['items'][0]['id']==mid
    assert client.post(f'/api/materials/{mid}/purge',json={'revision':store.get(mid)['revision'],'confirmation':'彻底删除'}).status_code==200
    assert client.get(f'/api/materials/{layer}/images/{asset}').status_code==200
    assert store.get(layer)['body'].endswith('完整结尾') and Path(p['destination']).exists()

def test_second_step_manual_and_reference_need_no_model_or_ai_review(local):
    client,vault,mid=local;first=save(client,mid,'digest','只是问题，不能冒充理解');layer=confirm(client,first)
    with store.db() as c:c.execute('UPDATE first_layers SET summary=? WHERE id=?',('未审查的AI结果',layer))
    request={'destination':'obsidian','complete_processing':True,'knowledge_output':{'folder':'06_资料与教程','title':'本人加工的知识','text':'这是我的判断','authorship':'manual'}}
    p=client.post(f'/api/materials/{layer}/push-preview',json=request);assert p.status_code==200,p.text
    assert not Path(p.json()['destination']).exists()
    confirm(client,p.json())
    assert store.get(layer)['processing']=='done' and store.get(mid)['processing']=='pending'
    text=Path(p.json()['destination']).read_text('utf-8')
    assert 'authorship: manual' in text and '第一层批注材料' in text
    request['knowledge_output']['authorship']='edited'
    assert client.post(f'/api/materials/{layer}/push-preview',json=request).status_code==400
    request['knowledge_output']['authorship']='reference'
    assert client.post(f'/api/materials/{layer}/push-preview',json=request).status_code==200

def test_conflicts_changes_and_rescrape_cannot_drop_annotations(local):
    client,vault,mid=local;p=save(client,mid,'callable','保留调用批注')
    target=Path(p['destination']);target.parent.mkdir(parents=True);target.write_text('人工内容','utf-8')
    assert client.post(f'/api/pushes/{p["id"]}/confirm',json={'hash':p['hash']}).status_code==400
    assert target.read_text('utf-8')=='人工内容'
    assert client.get('/api/first-layer',params={'track':'callable'}).json()['items']==[]
    service.save_content(mid,{'title':'刷新后','body':'新原文','collection':'ready','content':{'source':'合成刷新'}},preserve_processing=True)
    assert store.get(mid)['content']['annotations']['callable']=='保留调用批注'
    assert client.post(f'/api/pushes/{p["id"]}/confirm',json={'hash':p['hash']}).status_code==400

def test_ai_workflow_belongs_to_annotated_record_and_preserves_source(local,monkeypatch):
    client,vault,mid=local;p=save(client,mid,'digest','请围绕这个问题整理');layer=confirm(client,p)
    monkeypatch.setattr(store,'settings',lambda:{'obsidian_vault':str(vault),'ai_model':'synthetic-model','ai_api_key':'fixture-only'})
    calls=[]
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'choices':[{'message':{'content':'合成AI结果：仅验收独立处理状态'}}]}
    monkeypatch.setattr(service.httpx,'post',lambda *a,**k:(calls.append(k['json']) or Response()))
    response=client.post(f'/api/materials/{layer}/ai',json={'from_annotation':True,'revision':store.get(layer)['revision']})
    assert response.status_code==200,response.text
    with store.db() as c:job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(response.json()['job_id'],)).fetchone())
    service.run_job(job)
    assert '请围绕这个问题整理' in calls[0]['messages'][1]['content']
    assert store.get(layer)['processing']=='review' and store.get(mid)['summary']==''
    assert client.get('/api/first-layer',params={'track':'digest','state':'review'}).json()['items'][0]['id']==layer
    item=client.get('/api/materials/'+layer).json()
    assert client.post(f'/api/materials/{layer}/ai-review',json={'revision':item['revision'],'summary_hash':item['ai_review']['summary_hash']}).status_code==200
    assert Path(p['destination']).read_text('utf-8')==p['shelf_markdown'],'AI must not rewrite a confirmed first-layer note'


def test_disconnected_vault_keeps_visible_paths_but_never_creates_files(local):
    client,vault,mid=local;vault.rename(vault.parent/'temporarily-unmounted')
    paths=client.get('/api/first-layer/folders');assert paths.status_code==200
    assert paths.json()['callable']['path']==str(vault/'收藏材料库'/'01_调用资料')
    assert paths.json()['callable']['available'] is False and paths.json()['callable']['error']
    local_paths=client.get(f'/api/materials/{mid}/processing-paths').json()
    assert local_paths['vault_available'] is False and local_paths['formal_folders']==[]
    assert Path(local_paths['local_source']).is_file()
    assert client.put(f'/api/materials/{mid}/notes',json={'notes':'离线时的批注','revision':store.get(mid)['revision']}).status_code==200
    assert client.post(f'/api/materials/{mid}/push-preview',json={'destination':'obsidian','complete_processing':False,'shelf_output':{'stage':'callable'}}).status_code==400
    assert not vault.exists() and store.get(mid)['notes']=='离线时的批注'
    assert client.get('/api/first-layer',params={'track':'callable'}).json()['items']==[]
