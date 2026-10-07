import base64
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app import main,obsidian,service,store,vault_files

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z0KsAAAAASUVORK5CYII=')

@pytest.fixture
def local(tmp_path,monkeypatch):
    vault=tmp_path/'test-vault';vault.mkdir();(vault/'06_资料与教程').mkdir()
    config={'obsidian_vault':str(vault)}
    monkeypatch.setattr(store,'ROOT',tmp_path);monkeypatch.setattr(store,'DATA',tmp_path/'data')
    monkeypatch.setattr(store,'settings',lambda:config.copy())
    monkeypatch.setattr(service,'worker',lambda:None);monkeypatch.setattr(service,'favorites_worker',lambda:None)
    with TestClient(main.app,headers={'X-Local-Request':'1'}) as client:yield client,vault,config

def material(suffix='123450'):
    mid=service.add({'url':'https://x.com/fixture/status/'+suffix,'title':'合成材料：图文字幕','text':'原始正文','origin':'favorite'},enqueue_collect=False)['id']
    folder=store.material_folder(mid);image=folder/'images'/'fixture.png';image.parent.mkdir();image.write_bytes(PNG)
    service.save_content(mid,{'title':'合成材料：图文字幕','body':'完整开头\n\n![原图](images/fixture.png)\n\n完整结尾','collection':'ready',
      'content':{'source':'合成测试','media':[{'status':'saved','path':'images/fixture.png','sha256':store.digest_bytes(PNG),'source_url':'https://example.org/fixture.png'}],
                 'segments':[{'start':0,'end':61,'text':'完整最后一句字幕'}],'subtitle_source':'平台字幕',
                 'comments':[{'author':'fixture','body':'回复图片\n![回复](images/fixture.png)'}],'comments_status':'仅测试回复'}})
    return mid

def first(client,mid,track='callable'):
    r=client.put(f'/api/materials/{mid}/notes',json={'notes':'保留方法，以后调用；还有一个待考虑的问题','annotation_track':track,'revision':store.get(mid)['revision']});assert r.status_code==200,r.text
    p=service.preview(mid,'obsidian',False,shelf_output={'stage':track,'overview':''})
    result=service.confirm(p['id'],p['hash']);return p,result['layer_id']

def second(mid,authorship='reference',complete=False):
    return service.preview(mid,'obsidian',complete,knowledge_output={'title':'分配后的材料','text':'调用场景：验证工具实现方法。','folder':'06_资料与教程','authorship':authorship})

def export(c,pid):return dict(c.execute('SELECT * FROM vault_exports WHERE id=?',(pid,)).fetchone())

def test_first_layer_is_a_single_owned_document_and_image_bundle(local):
    client,vault,_=local;mid=material();p,layer=first(client,mid)
    root=Path(p['destination']).parent
    assert root.name.endswith('--'+p['id']) and root.joinpath('index.md').is_file()
    assert len(list(root.glob('assets/*.png')))==1
    assert not (vault/'收藏处理器').exists(),'first save must not create a duplicate source archive in the Vault'
    text=(root/'index.md').read_text('utf-8')
    assert '完整结尾' in text and '完整最后一句字幕' in text and '回复图片' in text
    assert '](assets/' in text and '../../' not in text
    with store.db() as c:assert export(c,p['id'])['owner_id']==layer

def test_raw_then_first_then_second_moves_documents_and_images_together(local):
    client,vault,_=local;mid=material()
    raw=service.preview(mid,'obsidian',False);service.confirm(raw['id'],raw['hash']);raw_root=Path(raw['destination']).parent
    assert raw_root.exists()
    p,layer=first(client,mid);first_root=Path(p['destination']).parent
    assert not raw_root.exists() and first_root.exists()
    q=second(layer);target=Path(q['destination']);assert not target.exists() and first_root.exists(),'preview must not move files'
    assert '/材料/可调用资料/' in q['payload']['knowledge_output']['note']
    service.confirm(q['id'],q['hash'])
    assert not first_root.exists() and target.is_file()
    source=Path(q['source_destination']);assert source.parent==target.parent and source.name=='来源与批注.md'
    assert '完整结尾' in source.read_text('utf-8') and '完整最后一句字幕' in source.read_text('utf-8')
    assert len(list(target.parent.glob('assets/*.png')))==1
    assert 'type: material' in target.read_text('utf-8') and 'human_digest: false' in target.read_text('utf-8')
    item=store.get(layer);assert item['first_layer']['path']==str(target) and item['content']['first_layer_context']['path']==str(source)
    assert service.confirm(p['id'],p['hash'])['path']==str(target),'repeat confirmation reports the actual current location'
    assert service.confirm(q['id'],q['hash'])['duplicate']
    assert store.get(mid)['body'].endswith('完整结尾') and store.get(layer)['processing']=='pending'

def test_digest_and_manual_knowledge_are_not_mislabeled_as_the_same_kind(local):
    client,_,_=local;mid=material();p,layer=first(client,mid,'digest')
    with store.db() as c:c.execute("UPDATE first_layers SET summary='模拟AI建议',content_json=json_set(content_json,'$.ai_review',json(?)) WHERE id=?",(store.dumps({'summary_hash':store.digest('模拟AI建议')}),layer))
    q=second(layer,'edited');assert '/材料/待消化/' in q['payload']['knowledge_output']['note']
    assert 'type: material' in q['knowledge_markdown'] and 'human_digest: false' in q['knowledge_markdown']
    manual=second(layer,'manual');assert '/材料/' not in manual['payload']['knowledge_output']['note']
    assert 'type: knowledge' in manual['knowledge_markdown']

def test_trash_restore_and_purge_clean_only_the_deleted_records_bundle(local):
    client,vault,_=local;mid=material();p,layer=first(client,mid);other=material('123451');other_p,other_layer=first(client,other)
    original=Path(p['destination']);root=original.parent;image=next(root.glob('assets/*.png'));image_bytes=image.read_bytes()
    keep=vault/'人工笔记.md';keep.write_text('本人内容','utf-8')
    assert client.delete(f'/api/materials/{layer}').status_code==200
    assert not root.exists() and keep.read_text('utf-8')=='本人内容'
    with store.db() as c:r=export(c,p['id'])
    trash_note=vault/r['note'];assert r['state']=='trash' and trash_note.exists()
    assert len(list(trash_note.parent.glob('assets/*.png')))==1
    assert client.post(f'/api/materials/{layer}/restore').status_code==200
    assert original.exists() and image.read_bytes()==image_bytes and not trash_note.exists()
    assert client.delete(f'/api/materials/{layer}').status_code==200
    deleted=client.post(f'/api/materials/{layer}/purge',json={'revision':store.get(layer)['revision'],'confirmation':'彻底删除'})
    assert deleted.status_code==200 and deleted.json()['vault_bundles_deleted']==1
    assert not original.exists() and not trash_note.exists()
    assert Path(other_p['destination']).is_file() and store.get(other_layer)['notes']
    with store.db() as c:assert export(c,p['id'])['state']=='purged'
    assert not (store.DATA/'outbox'/'obsidian'/p['id']).exists(),'purge must clean its dedicated local frozen image cache too'
    assert (store.DATA/'outbox'/'obsidian'/other_p['id']).exists()
    remaining=client.get('/api/materials',params={'state':'pending'}).json()['items']
    assert mid not in [r['id'] for r in remaining],'purging a derived record must not silently requeue an already routed source'
    assert mid in [r['id'] for r in client.get('/api/materials',params={'state':'source_archive'}).json()['items']]

def test_modified_file_blocks_move_before_any_original_is_removed(local):
    client,_,_=local;mid=material();p,layer=first(client,mid);old=Path(p['destination']);old.write_text('人工改写，必须保留','utf-8')
    q=second(layer);before=store.get(layer)
    with pytest.raises(ValueError,match='已被修改'):service.confirm(q['id'],q['hash'])
    assert old.read_text('utf-8')=='人工改写，必须保留' and not Path(q['destination']).exists()
    assert not (store.DATA/'outbox'/'obsidian'/q['id']).exists()
    assert store.get(layer)['revision']==before['revision']
    assert client.delete(f'/api/materials/{layer}').status_code==400 and not store.get(layer)['trashed']

def test_restore_conflict_and_changed_configuration_do_not_lose_trash(local):
    client,vault,config=local;mid=material();p,layer=first(client,mid);original=Path(p['destination'])
    client.delete(f'/api/materials/{layer}')
    original.parent.mkdir(parents=True);original.write_text('新人工文件','utf-8')
    assert client.post(f'/api/materials/{layer}/restore').status_code==400
    assert original.read_text('utf-8')=='新人工文件' and store.get(layer)['trashed']
    original.unlink();config['obsidian_vault']=str(vault/'missing-drive')
    assert client.post(f'/api/materials/{layer}/purge',json={'revision':store.get(layer)['revision'],'confirmation':'彻底删除'}).status_code==400
    assert not (vault/'missing-drive').exists() and store.get(layer)['trashed']

def test_transaction_failure_and_interrupted_operation_restore_original_bytes(local):
    _,vault,_=local;old=vault/'收藏材料库/01_调用资料/fixture/index.md';old.parent.mkdir(parents=True);old.write_bytes(b'original')
    old_rel=old.relative_to(vault).as_posix();new_rel='06_资料与教程/材料/可调用资料/fixture/index.md'
    with pytest.raises(RuntimeError):
        with vault_files.Change() as change,store.db() as c:
            change.apply(c,str(vault),{new_rel:b'new'},{old_rel:store.digest_bytes(b'original')})
            raise RuntimeError('simulated DB failure')
    assert old.read_bytes()==b'original' and not (vault/new_rel).exists()
    # Simulate process loss after file writes but before the database transaction commits.
    abandoned=vault_files.Change()
    with pytest.raises(RuntimeError):
        with store.db() as c:
            abandoned.apply(c,str(vault),{new_rel:b'new'},{old_rel:store.digest_bytes(b'original')})
            raise RuntimeError('simulated interruption')
    assert not old.exists() and (vault/new_rel).exists()
    vault_files.recover();assert old.read_bytes()==b'original' and not (vault/new_rel).exists()
    assert not list((store.DATA/'vault_operations').iterdir())

def test_committed_interrupted_cleanup_retains_new_bundle(local):
    _,vault,_=local;old=vault/'收藏材料库/01_调用资料/fixture/index.md';old.parent.mkdir(parents=True);old.write_bytes(b'original')
    old_rel=old.relative_to(vault).as_posix();new_rel='06_资料与教程/材料/可调用资料/fixture/index.md'
    abandoned=vault_files.Change()
    with store.db() as c:abandoned.apply(c,str(vault),{new_rel:b'new'},{old_rel:store.digest_bytes(b'original')})
    vault_files.recover();assert (vault/new_rel).read_bytes()==b'new' and not old.parent.exists()

@pytest.mark.parametrize('relative',['../outside.md','.obsidian/settings.json','C:/secret.md','资料\\secret.md'])
def test_owned_path_checks_reject_escape_and_metadata(local,relative):
    _,vault,_=local
    with pytest.raises(ValueError):vault_files.checked(str(vault),relative)

def test_prompt_is_read_only_and_uses_current_config_without_accessing_vault(local,monkeypatch):
    client,_,config=local;config['obsidian_vault']='Z:\\离线小库';config['ai_api_key']='never-return-this'
    monkeypatch.setattr(obsidian,'configuration',lambda:pytest.fail('copying instructions must not inspect the Vault'))
    p=client.get('/api/first-layer/organization-prompt');assert p.status_code==200
    assert p.json()['writes_performed'] is False and 'Z:\\离线小库' in p.json()['text']
    assert 'never-return-this' not in p.text and '直接把它们写进我的观点笔记' in p.json()['text']

def test_explicit_fine_topic_target_does_not_require_a_preset_tool_or_root(local):
    client,vault,_=local;mid=material();p,layer=first(client,mid)
    folder='我的研究/声音与表达/案例';(vault/folder).mkdir(parents=True)
    q=service.preview(layer,'obsidian',False,knowledge_output={'folder':folder,'title':'按主题归位','text':'## AI概览\n\n案例用途，待核查。','authorship':'reference'})
    assert q['payload']['knowledge_output']['note'].startswith(folder+'/材料/可调用资料/')
    service.confirm(q['id'],q['hash']);assert Path(q['destination']).is_file() and not Path(p['destination']).exists()

def test_new_topic_directory_is_only_created_after_exact_path_confirmation(local):
    client,vault,_=local;mid=material();p,layer=first(client,mid)
    folder='我的研究/工具调用/失败案例'
    q=service.preview(layer,'obsidian',False,knowledge_output={'folder':folder,'title':'新主题材料','text':'AI概览：供以后调用，待核查。','authorship':'reference'})
    assert not (vault/folder).exists() and Path(p['destination']).exists()
    service.confirm(q['id'],q['hash']);assert Path(q['destination']).exists() and not Path(p['destination']).exists()

def test_legacy_flat_note_and_cross_folder_images_are_adopted_and_moved(local):
    from urllib.parse import quote
    from app import knowledge
    client,vault,_=local;mid=material()
    client.put(f'/api/materials/{mid}/notes',json={'notes':'旧版本批注','annotation_track':'callable','revision':store.get(mid)['revision']})
    p=service.preview(mid,'obsidian',False,shelf_output={'stage':'callable','overview':''});payload=p['payload']
    payload.pop('managed_bundle');payload.pop('relocation');payload['obsidian']=obsidian.target(store.get(mid),p['id'])
    out=payload['shelf_output'];out['note']=out['folder']+'/旧版材料--'+p['id']+'.md';out['path']=str(vault/out['note']);out['source_note']=payload['obsidian']['note']
    archive=payload['obsidian']['note'].rsplit('/',1)[0]
    for asset in payload['assets']:
        out['markdown']=out['markdown'].replace(']('+asset['target']+')',']('+quote('../../'+archive+'/'+asset['target'],safe='/')+')')
    out['markdown']+='\n## 原始存档\n\n'+knowledge.link(payload['obsidian']['note'])+'\n'
    frozen=store.dumps(payload);sha=store.digest(frozen)
    with store.db() as c:c.execute('UPDATE pushes SET payload=?,hash=? WHERE id=?',(frozen,sha,p['id']))
    layer=service.confirm(p['id'],sha)['layer_id'];old=Path(out['path']);archive_root=Path(payload['obsidian']['path']).parent
    assert old.exists() and archive_root.exists()
    q=second(layer);service.confirm(q['id'],q['hash'])
    assert not old.exists() and not archive_root.exists()
    text=Path(q['source_destination']).read_text('utf-8');assert '旧版本批注' in text and '](assets/' in text and '../../' not in text
    assert len(list(Path(q['destination']).parent.glob('assets/*.png')))==1

def test_local_purge_staging_is_rolled_back_on_database_failure(local):
    _,_,_=local;folder=store.DATA/'materials'/'x'/'fixture';folder.mkdir(parents=True);(folder/'image.png').write_bytes(PNG)
    with pytest.raises(RuntimeError):
        with vault_files.Change() as change,store.db() as c:
            change.stash_local(c,[folder]);assert not folder.exists();raise RuntimeError('simulated DB failure')
    assert (folder/'image.png').read_bytes()==PNG
    abandoned=vault_files.Change()
    with pytest.raises(RuntimeError):
        with store.db() as c:
            abandoned.stash_local(c,[folder]);raise RuntimeError('simulated interruption')
    vault_files.recover();assert (folder/'image.png').read_bytes()==PNG

def test_shared_ownership_blocks_move_and_trash(local):
    client,vault,_=local;mid=material();p,layer=first(client,mid)
    with store.db() as c:
        r=export(c,p['id']);c.execute('INSERT INTO vault_exports(id,owner_id,vault,note,files_json,updated) VALUES (?,?,?,?,?,?)',
          ('shared-fixture','another-record',r['vault'],r['note'],r['files_json'],store.now()))
    q=second(layer)
    with pytest.raises(ValueError,match='另一条材料'):service.confirm(q['id'],q['hash'])
    assert client.delete(f'/api/materials/{layer}').status_code==400 and Path(p['destination']).exists()
