import json
from pathlib import Path
import pytest
from app import store
from app import vault_files
from test_vault_file_lifecycle import local,material,first,export

def request(client,action,ids,**kwargs):
    return client.post('/api/materials/batch-actions',json={'action':action,'items':[{'id':mid,'revision':store.get(mid)['revision']} for mid in ids],**kwargs})

def test_batch_trash_and_restore_preserve_originals_and_other_items(local):
    client,_,_=local
    ids=[material(str(410000+i)) for i in range(3)];before=[store.get(mid) for mid in ids]
    result=request(client,'trash',ids[:2]).json();assert result['succeeded']==2 and result['failed']==0
    assert [bool(store.get(mid)['trashed']) for mid in ids]==[True,True,False]
    result=request(client,'restore',ids[:2]).json();assert result['succeeded']==2
    for mid,old in zip(ids,before):
        item=store.get(mid);assert (item['body'],item['notes'],item['content'],item['processing'])==(old['body'],old['notes'],old['content'],old['processing'])
        assert store.material_folder(mid).joinpath('images/fixture.png').is_file()
    with store.db() as c:
        events=[json.loads(r[0]) for r in c.execute("SELECT detail FROM events WHERE kind='material_batch_completed'")]
    assert [e['action'] for e in events]==['trash','restore'] and all(len(e['results'])==2 for e in events)

def test_batch_stale_revision_and_missing_id_fail_only_their_items(local):
    client,_,_=local;a,b=material('420001'),material('420002');stale=store.get(a)['revision']
    client.put(f'/api/materials/{a}/notes',json={'notes':'新批注必须保留','revision':stale})
    body={'action':'trash','items':[{'id':a,'revision':stale},{'id':'missing','revision':1},{'id':b,'revision':store.get(b)['revision']}]}
    r=client.post('/api/materials/batch-actions',json=body).json()
    assert r['succeeded']==1 and r['failed']==2
    assert '已改变' in r['results'][0]['error'] and '不存在' in r['results'][1]['error']
    assert store.get(a)['notes']=='新批注必须保留' and not store.get(a)['trashed'] and store.get(b)['trashed']

def test_batch_purge_requires_one_explicit_confirmation_and_cleans_owned_images(local):
    client,vault,_=local;a,b=material('430001'),material('430002');p,layer=first(client,a)
    request(client,'trash',[layer,b]);owned=Path(p['destination'])
    r=request(client,'purge',[layer,b]);assert r.status_code==400
    assert store.get(layer)['trashed'] and store.get(b)['trashed']
    r=request(client,'purge',[layer,b],confirmation='彻底删除').json();assert r['succeeded']==2 and r['failed']==0
    for mid in [layer,b]:
        with pytest.raises(ValueError):store.get(mid)
    assert store.get(a)['body'] and store.material_folder(a).joinpath('images/fixture.png').is_file()
    assert not owned.exists() and not (store.DATA/'outbox/obsidian'/p['id']).exists()
    with store.db() as c:assert export(c,p['id'])['state']=='purged'
    assert not list((vault/'收藏材料库').rglob('*.png'))

def test_batch_modified_vault_file_stays_intact_while_other_record_completes(local):
    client,_,_=local
    a,b=material('440001'),material('440002');p,layer=first(client,a);note=Path(p['destination'])
    note.write_text('人工改写必须保留','utf-8')
    r=request(client,'trash',[layer,b]).json();assert r['succeeded']==1 and r['failed']==1
    assert '已被修改' in r['results'][0]['error']
    assert not store.get(layer)['trashed'] and store.get(b)['trashed'] and note.read_text('utf-8')=='人工改写必须保留'

def test_post_commit_archive_failure_reports_saved_state_with_warning(local,monkeypatch):
    client,_,_=local;mid=material('441001')
    monkeypatch.setattr(store,'archive',lambda mid:(_ for _ in ()).throw(OSError('simulated unavailable archive')))
    r=request(client,'trash',[mid]).json()
    assert r['succeeded']==1 and r['failed']==0 and r['warnings']==1 and store.get(mid)['trashed']
    assert '状态已保存' in r['results'][0]['warning']

def test_post_commit_purge_cleanup_failure_retains_recovery_journal(local,monkeypatch):
    client,_,_=local;mid=material('441002');request(client,'trash',[mid])
    original=vault_files._remove_journal
    monkeypatch.setattr(vault_files,'_remove_journal',lambda root:(_ for _ in ()).throw(OSError('simulated locked cleanup')))
    r=request(client,'purge',[mid],confirmation='彻底删除').json()
    assert r['succeeded']==1 and r['failed']==0 and r['warnings']==1
    with pytest.raises(ValueError):store.get(mid)
    assert list((store.DATA/'vault_operations').iterdir()),'committed cleanup retains its recovery evidence'
    monkeypatch.setattr(vault_files,'_remove_journal',original);vault_files.recover()
    assert not list((store.DATA/'vault_operations').iterdir())

@pytest.mark.parametrize('change',[lambda b:b['items'].append(b['items'][0]),lambda b:b['items'][0].update(id='../escape'),lambda b:b['items'][0].update(revision=0),lambda b:b.update(action='unknown'),lambda b:b.update(items=[]),lambda b:b.update(items=b['items']*101)])
def test_invalid_batch_has_no_side_effects(local,change):
    client,_,_=local;mid=material('450001');before=store.get(mid)
    body={'action':'trash','items':[{'id':mid,'revision':before['revision']}]};change(body)
    assert client.post('/api/materials/batch-actions',json=body).status_code in (400,422)
    assert store.get(mid)==before
