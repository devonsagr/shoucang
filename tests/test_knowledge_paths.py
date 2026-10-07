from pathlib import Path
import pytest
from app import obsidian,store
from test_automatic_collection import local

def source(client):
    mid=client.post('/api/materials',json={'url':'https://example.org/path-fixture','text':'合成材料正文','title':'路径验收'}).json()['id']
    client.put(f'/api/materials/{mid}/notes',json={'notes':'以后写作时引用','revision':store.get(mid)['revision']})
    return mid

def first(client,mid):
    response=client.post(f'/api/materials/{mid}/push-preview',json={'destination':'obsidian','complete_processing':False,'shelf_output':{'stage':'callable'}})
    assert response.status_code==200,response.text
    return response.json()

def confirm(client,p):
    return client.post(f'/api/pushes/{p["id"]}/confirm',json={'hash':p['hash']})

def test_default_local_markdown_library_needs_no_personal_vault(local):
    client,cfg=local
    default=Path(client.get('/api/settings').json()['obsidian_vault'])
    assert default==store.DATA/'knowledge-base' and default.is_dir()
    p=first(client,source(client))
    assert confirm(client,p).status_code==200
    assert Path(p['destination']).is_file() and not cfg.get('obsidian_vault')

def test_custom_paths_preview_confirm_migrate_bundle_and_restore_old_trash(local,tmp_path):
    client,_=local;vault=tmp_path/'md-library';vault.mkdir()
    custom={**obsidian.DEFAULT_PATHS,'archive':'收集/原文','callable':'批注/资料','digest':'批注/细读','trash':'回收/材料','materials':'素材'}
    assert client.put('/api/obsidian',json={'vault':str(vault),'paths':custom,'targets':['主题/AI']}).status_code==200
    mid=source(client);p=first(client,mid);old=Path(p['destination'])
    assert old.is_relative_to(vault/'批注/资料') and not old.exists()
    saved=confirm(client,p).json();assert old.is_file()
    layer=saved['layer_id'];current=store.get(layer)
    assert client.delete(f'/api/materials/{layer}').status_code==200
    assert not old.exists() and list((vault/'回收/材料').rglob('index.md'))
    # Restoring uses the recorded location, even after the trash preference changes.
    custom['trash']='另一个回收站'
    assert client.put('/api/obsidian',json={'vault':str(vault),'paths':custom}).status_code==200
    assert client.post(f'/api/materials/{layer}/restore',json={'revision':store.get(layer)['revision']}).status_code==200
    assert old.is_file() and not list((vault/'回收/材料').rglob('index.md'))
    custom['callable']='一级/调用资料'
    assert client.put('/api/obsidian',json={'vault':str(vault),'paths':custom}).status_code==200
    assert old.is_file()  # Preferences alone never move existing documents.
    p2=first(client,mid);assert p2.get('duplicate') is not True
    assert confirm(client,p2).status_code==200
    assert not old.exists() and Path(p2['destination']).is_relative_to(vault/'一级/调用资料')

def test_changed_directory_invalidates_frozen_preview(local):
    client,_=local;p=first(client,source(client))
    assert client.put('/api/obsidian',json={'vault':obsidian.root(),'paths':{'callable':'新的资料'}}).status_code==200
    result=confirm(client,p)
    assert result.status_code==400 and '重新' in result.json()['detail']
    assert not Path(p['destination']).exists()

def test_preview_created_before_path_settings_cannot_ignore_new_destination(local):
    client,_=local;p=first(client,source(client));payload=p['payload']
    payload.pop('knowledge_paths');payload['obsidian'].pop('config_paths',None);payload['shelf_output'].pop('config_paths')
    encoded=store.dumps(payload);legacy_hash=store.digest(encoded)
    with store.db() as c:c.execute('UPDATE pushes SET payload=?,hash=? WHERE id=?',(encoded,legacy_hash,p['id']))
    assert client.put('/api/obsidian',json={'vault':obsidian.root(),'paths':{'callable':'新的资料'}}).status_code==200
    result=client.post(f'/api/pushes/{p["id"]}/confirm',json={'hash':legacy_hash})
    assert result.status_code==400 and '重新' in result.json()['detail']
    assert not Path(p['destination']).exists()

@pytest.mark.parametrize('path',['../escape','C:/outside','.obsidian/data','foo//bar','foo/../bar','foo/'])
def test_directory_escape_or_metadata_is_rejected_without_configuration_change(local,path):
    client,_=local;before=client.get('/api/settings').json()
    result=client.put('/api/obsidian',json={'vault':obsidian.root(),'paths':{'callable':path}})
    assert result.status_code==400
    assert client.get('/api/settings').json()==before

def test_distinct_stages_and_explicit_target_list_are_required(local):
    client,_=local
    assert client.put('/api/obsidian',json={'vault':obsidian.root(),'paths':{'digest':obsidian.paths()['callable']}}).status_code==400
    assert client.put('/api/obsidian',json={'vault':obsidian.root(),'targets':['.obsidian']} ).status_code==400

def test_organization_prompt_uses_configured_paths_and_excludes_screening_preview(local):
    client,_=local
    client.put('/api/obsidian',json={'vault':obsidian.root(),'paths':{'callable':'一级/资料','digest':'一级/细读','materials':'参考材料'}})
    prompt=client.get('/api/first-layer/organization-prompt').json()['text']
    assert '一级/资料' in prompt and '一级/细读' in prompt and '参考材料' in prompt
    assert '不使用该速览作依据' in prompt and '{{' not in prompt and 'G:\\' not in prompt
