import json
import sqlite3
from app import adapters,service,store
from test_automatic_collection import local

def create(client,url='https://x.com/fixture/status/730001'):
    return client.post('/api/materials',json={'url':url,'text':'保留的原文夹具。完整内容来自原作者。'}).json()['id']

def purge(client,mid):
    client.delete('/api/materials/'+mid)
    r=client.post('/api/materials/'+mid+'/purge',json={'revision':store.get(mid)['revision'],'confirmation':'彻底删除'})
    assert r.status_code==200,r.text

def test_permanent_deletion_is_not_a_new_favorite_next_time(local):
    client,_=local;mid=create(client);purge(client,mid)
    result=service.add({'url':'https://twitter.com/another/status/730001?utm_source=share','origin':'favorite'},source='new sync')
    assert result.get('retired') and result['duplicate'],'purged sources must not silently come back as new favorites'
    with store.db() as c:
        assert not c.execute('SELECT 1 FROM materials WHERE id=?',(mid,)).fetchone()
        assert c.execute('SELECT COUNT(*) FROM materials').fetchone()[0]==0

def test_heybox_link_aliases_have_one_stable_identity(local):
    client,_=local;url='https://www.xiaoheihe.cn/app/topic/link/9000000000000000020?share=1'
    mid=create(client,url);before=store.get(mid)
    # Historical keys from before the new platform normalization remain recognizable.
    with store.db() as c:c.execute('UPDATE materials SET canonical=? WHERE id=?',(url,mid))
    again=service.add({'url':'https://www.xiaoheihe.cn/app/bbs/link/9000000000000000020','origin':'favorite'})
    assert again['duplicate'] and again['id']==mid and store.get(mid)['body']==before['body']
    assert adapters.canonical(url)==adapters.canonical('https://heybox.com/share?link_id=9000000000000000020')
    purge(client,mid)
    assert service.add({'url':url,'origin':'favorite'})['retired']

def test_saved_deletion_fingerprint_has_no_original_text_or_link(local):
    client,_=local;mid=create(client);purge(client,mid)
    with store.db() as c:rows=[dict(r) for r in c.execute('SELECT * FROM retired_sources')]
    assert len(rows)==1 and rows[0]['material_id']==mid and rows[0]['platform']=='x'
    assert 'https://' not in json.dumps(rows) and '原文夹具' not in json.dumps(rows)
    assert len(rows[0]['identity'])==64

def test_historical_purge_can_recover_identity_from_owned_backup(local):
    client,_=local;mid=create(client)
    backup=store.DATA/'backups/prior.sqlite3';backup.parent.mkdir()
    with sqlite3.connect(store.DATA/'library.sqlite3') as source,sqlite3.connect(backup) as target:source.backup(target)
    purge(client,mid)
    with store.db() as c:
        c.execute('DELETE FROM retired_sources')
        c.execute("UPDATE events SET detail=? WHERE kind='material_purged'",(store.dumps({'id':mid}),))
    result=store.recover_deleted_identities()
    assert result['recovered']==1 and not result['unresolved']
    assert service.add({'url':'https://x.com/i/status/730001','origin':'favorite'})['retired']

def test_manual_recollection_requires_explicit_opt_in(local):
    client,_=local;mid=create(client);purge(client,mid)
    body={'url':'https://x.com/i/status/730001','text':'明确重新收集的原文'}
    assert client.post('/api/materials',json=body).json()['retired']
    r=client.post('/api/materials',json={**body,'recollect_deleted':True}).json()
    assert not r['duplicate'] and r['id']!=mid and store.get(r['id'])['body']=='明确重新收集的原文'

def test_changed_complete_source_updates_in_place_preserving_annotation_and_status(local):
    client,_=local
    seed={'url':'https://x.com/i/status/730007','origin':'favorite','title':'标题','body':'第一版的作者原文。','collection':'ready','content':{'source':'test favorite response','original_text_complete':True}}
    mid=service.add(seed,enqueue_collect=False)['id']
    with store.db() as c:c.execute("UPDATE materials SET notes='我的用途批注',processing='done' WHERE id=?",(mid,))
    old=store.get(mid)
    assert service.add(seed)['duplicate'] and store.get(mid)['revision']==old['revision']
    changed=service.add({**seed,'body':'作者新增一段，并删去了旧文字。'})
    item=store.get(mid)
    assert changed['updated'] and changed['id']==mid and item['body'].startswith('作者新增')
    assert item['notes']=='我的用途批注' and item['processing']=='done'
    with store.db() as c:assert c.execute('SELECT COUNT(*) FROM versions WHERE material_id=?',(mid,)).fetchone()[0]==2

def test_partial_list_preview_cannot_replace_stored_full_text(local):
    client,_=local;mid=create(client,'https://x.com/i/status/730009');before=store.get(mid)
    r=service.add({'url':before['url'],'origin':'favorite','body':'只是一小段…','title':'预览','collection':'partial','content':{'original_text_complete':False}})
    assert r['duplicate'] and not r.get('updated') and store.get(mid)['body']==before['body']
