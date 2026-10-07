import json
from app import assets,service,store
from test_automatic_collection import local

def image_job(client):
    mid=client.post('/api/materials',json={'url':'https://example.org/image-race','title':'旧标题','text':'V1 原文。\n\n![图片](https://cdn.example.org/v1.jpg)'}).json()['id']
    with store.db() as c:
        job=dict(c.execute("SELECT * FROM jobs WHERE material_id=? AND kind='images'",(mid,)).fetchone())
        c.execute("UPDATE jobs SET state='running' WHERE id=?",(job['id'],))
    return mid,job

def test_old_image_result_cannot_overwrite_new_favorite_source_and_requeues_current(local,monkeypatch):
    client,_=local;mid,job=image_job(client)
    def delayed(result,*args):
        newer={'url':'https://example.org/image-race','origin':'favorite','title':'新标题',
               'body':'V2 完整原文。\n\n![图片](https://cdn.example.org/v2.jpg)',
               'collection':'ready','content':{'source':'合成清单完整正文','original_text_complete':True}}
        assert service.add(newer,enqueue_collect=False)['updated']
        return result
    monkeypatch.setattr(assets,'localize',delayed)
    service.run_job(job)
    latest=store.get(mid)
    assert latest['title']=='新标题' and 'V2 完整原文' in latest['body'] and 'v1.jpg' not in latest['body']
    with store.db() as c:
        pending=c.execute("SELECT id FROM jobs WHERE material_id=? AND kind='images' AND state='queued'",(mid,)).fetchall()
        assert len(pending)==1 and pending[0]['id']!=job['id']
        assert c.execute("SELECT count(*) FROM events WHERE material_id=? AND kind='images_stale'",(mid,)).fetchone()[0]==1

def test_image_only_caching_preserves_existing_summary_and_notes(local,monkeypatch):
    client,_=local;mid,job=image_job(client)
    with store.db() as c:c.execute("UPDATE materials SET summary='已审查的旧整理',notes='本人用途批注' WHERE id=?",(mid,))
    monkeypatch.setattr(assets,'localize',lambda result,*args:result)
    service.run_job(job)
    assert store.get(mid)['summary']=='已审查的旧整理' and store.get(mid)['notes']=='本人用途批注'

def test_late_image_result_does_not_write_into_trashed_material(local,monkeypatch):
    client,_=local;mid,job=image_job(client)
    def delayed(result,*args):
        store.trash(mid);return {**result,'body':'迟到的图片结果'}
    monkeypatch.setattr(assets,'localize',delayed);service.run_job(job)
    item=store.get(mid)
    assert item['trashed'] and 'V1 原文' in item['body'] and '迟到' not in item['body']
    with store.db() as c:assert c.execute("SELECT count(*) FROM jobs WHERE material_id=? AND kind='images' AND state='queued'",(mid,)).fetchone()[0]==0
