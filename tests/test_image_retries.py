import base64
import json
import pytest
from app import assets,service,sessions,store
from test_automatic_collection import local

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')

def material(client,identifier,state='partial',source_page=False):
    url='https://www.xiaoheihe.cn/app/bbs/link/'+str(identifier)
    mid=client.post('/api/materials',json={'url':url,'text':'前文。后文。','origin':'favorite'}).json()['id']
    image=url if source_page else 'https://cdn.example.org/diagram.png'
    content={'original_text_complete':True,'media':[{'status':'failed','source_url':image,'alt':'图解'}]}
    with store.db() as c:
        c.execute("UPDATE materials SET body=?,content_json=?,collection=?,notes='本人批注',summary='此前整理',processing='done' WHERE id=?",
                  ('前文\n\n[图片未存档：图解]('+image+')\n\n后文',store.dumps(content),state,mid))
    return mid

def test_failed_marker_can_be_scripted_back_to_an_image_in_the_same_position(local,monkeypatch):
    client,_=local;mid=material(client,99501);item=store.get(mid);calls=[]
    item['content']['comments']=[{'body':'回复前\n\n[图片未存档：图解](https://cdn.example.org/diagram.png)\n\n回复后'}]
    def download(url):calls.append(url);return PNG,'png'
    monkeypatch.setattr(assets,'download',download)
    result=assets.localize({'title':item['title'],'body':item['body'],'content':item['content'],'collection':'ready'},store.material_folder(mid)/'retry-fixture',mid,item['url'])
    assert calls==['https://cdn.example.org/diagram.png'] and len(result['content']['media'])==1
    assert result['collection']=='ready' and '图片未存档' not in result['body']
    assert result['body'].index('前文')<result['body'].index('![')<result['body'].index('后文')
    assert result['content']['comments'][0]['body'].index('回复前')<result['content']['comments'][0]['body'].index('![')<result['content']['comments'][0]['body'].index('回复后')

def test_retry_only_missing_images_preserves_notes_summary_and_status_without_collecting(local,monkeypatch):
    client,_=local;mid=material(client,99502)
    monkeypatch.setattr(assets,'download',lambda _:(PNG,'png'))
    monkeypatch.setattr(service.adapters,'collect',lambda *a:(_ for _ in ()).throw(AssertionError('已有原文，不应重抓网站')))
    r=client.post('/api/materials/'+mid+'/retry',json={}).json();assert r['kind']=='images'
    with store.db() as c:job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(r['job_id'],)).fetchone())
    service.run_job(job)
    item=store.get(mid)
    assert item['collection']=='ready' and item['notes']=='本人批注' and item['summary']=='此前整理' and item['processing']=='done'
    assert not any(a['status']!='saved' for a in item['content']['media'])

def test_legacy_empty_src_requires_source_hydration_instead_of_downloading_html_again(local):
    client,_=local;mid=material(client,99503,source_page=True)
    assert client.post('/api/materials/'+mid+'/retry',json={}).json()['kind']=='collect'

def test_missing_cached_file_recovers_from_recorded_original_image_url(local,monkeypatch):
    client,_=local;mid=material(client,99504)
    with store.db() as c:
        content={'media':[{'status':'saved','path':'old/images/diagram.png','source_url':'https://cdn.example.org/diagram.png'}]}
        c.execute("UPDATE materials SET collection='ready',body=?,content_json=? WHERE id=?",('前文\n\n![图解](old/images/diagram.png)\n\n后文',store.dumps(content),mid))
    calls=[];monkeypatch.setattr(assets,'download',lambda url:(calls.append(url) or PNG,'png'))
    r=client.post('/api/materials/'+mid+'/retry',json={}).json()
    with store.db() as c:job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(r['job_id'],)).fetchone())
    service.run_job(job)
    assert calls==['https://cdn.example.org/diagram.png']
    assert store.get(mid)['collection']=='ready' and 'old/images' not in store.get(mid)['body']

@pytest.mark.parametrize('source_changed',[False,True])
def test_requeued_cache_repair_keeps_completeness_only_when_the_original_source_is_unchanged(local,monkeypatch,source_changed):
    client,_=local;mid=material(client,99510)
    with store.db() as c:
        content={'media':[{'status':'saved','path':'old/images/diagram.png','source_url':'https://cdn.example.org/diagram.png'}]}
        c.execute("UPDATE materials SET collection='ready',body=?,content_json=? WHERE id=?",('完整旧正文\n\n![图解](old/images/diagram.png)',store.dumps(content),mid))
    first=client.post('/api/materials/'+mid+'/retry',json={}).json()
    with store.db() as c:
        c.execute("UPDATE jobs SET state='running' WHERE id=?",(first['job_id'],))
        job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(first['job_id'],)).fetchone())
    assert json.loads(job['payload'])['source_complete'] is True
    calls=[]
    def download(url):
        calls.append(url)
        if len(calls)==1:
            item=store.get(mid)
            assert client.put('/api/materials/'+mid+'/notes',json={'notes':'刚补的新批注','annotation_track':'callable','annotation_kind':'inspiration','revision':item['revision']}).status_code==200
            if source_changed:
                with store.db() as c:
                    content={**store.get(mid)['content'],'original_text_complete':False,'media':[{'status':'failed','source_url':'https://cdn.example.org/new.png'}]}
                    c.execute('UPDATE materials SET body=?,content_json=?,revision=revision+1 WHERE id=?',('新的部分原文\n\n![新图](https://cdn.example.org/new.png)',store.dumps(content),mid))
        return PNG,'png'
    monkeypatch.setattr(assets,'download',download)
    service.run_job(job)
    with store.db() as c:requeued=dict(c.execute("SELECT * FROM jobs WHERE material_id=? AND kind='images' AND state='queued' AND id<>?",(mid,first['job_id'])).fetchone())
    assert json.loads(requeued['payload'])['source_complete'] is (not source_changed)
    service.run_job(requeued)
    item=store.get(mid)
    assert item['collection']==('partial' if source_changed else 'ready') and item['notes']=='刚补的新批注'
    assert item['summary']=='此前整理' and item['processing']=='done'
    assert item['content']['annotations']['callable']=='刚补的新批注' and item['content']['annotation_kind']=='inspiration'
    assert all(m['status']=='saved' for m in item['content']['media'])

def test_many_distinct_article_images_are_saved_instead_of_failing_after_the_fortieth(local,monkeypatch):
    client,_=local;mid=material(client,99505)
    monkeypatch.setattr(assets,'download',lambda _:(PNG,'png'))
    body='\n\n'.join(f'![图{i}](https://cdn.example.org/{i}.png)' for i in range(58))
    r=assets.localize({'title':'长图文夹具','body':body,'content':{},'collection':'ready'},store.material_folder(mid)/'long-fixture',mid,'https://example.org/article')
    assert r['collection']=='ready' and len(r['content']['media'])==58
    assert all(m['status']=='saved' for m in r['content']['media'])

def test_platform_verification_blocks_source_retries_until_latest_login_is_saved_but_not_image_cache(local):
    client,_=local;source=material(client,99506,source_page=True);cache=material(client,99507)
    with store.db() as c:store.event(c,None,'platform_capture_paused',{'platform':'heybox','reason':'安全验证'})
    assert sessions.status('heybox')['access_required']
    r=client.post('/api/materials/batch-actions',json={'action':'retry','items':[{'id':mid,'revision':store.get(mid)['revision']} for mid in (source,cache)]}).json()
    assert r['failed']==1 and r['results'][1]['kind']=='images' and '本人验证' in r['results'][0]['error']
    with store.db() as c:
        assert not c.execute("SELECT 1 FROM jobs WHERE material_id=? AND kind='collect'",(source,)).fetchone()
        store.event(c,None,'platform_session_saved',{'platform':'heybox'})
    assert not sessions.status('heybox')['access_required']
    assert client.post('/api/materials/'+source+'/retry',json={}).json()['kind']=='collect'

def test_a_late_collect_job_cannot_bypass_the_platform_pause(local,monkeypatch):
    import pytest
    from app.platform_browser import PlatformAccessRequired
    client,_=local;mid=material(client,99508,source_page=True)
    with store.db() as c:
        jid=store.enqueue(c,'collect',{},mid)
        job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
        store.event(c,None,'platform_capture_paused',{'platform':'heybox'})
    monkeypatch.setattr(service,'collect_job',lambda *a:(_ for _ in ()).throw(AssertionError('暂停后不得发起网站请求')))
    with pytest.raises(PlatformAccessRequired):service.run_job(job)

@pytest.mark.parametrize('complete',[None,False])
def test_unknown_or_folded_source_never_becomes_ready_just_because_images_are_cached(local,monkeypatch,complete):
    client,_=local;mid=material(client,99509)
    with store.db() as c:
        content=store.get(mid)['content']
        if complete is None:content.pop('original_text_complete')
        else:content['original_text_complete']=False
        c.execute('UPDATE materials SET content_json=? WHERE id=?',(store.dumps(content),mid))
    assert client.post('/api/materials/'+mid+'/retry',json={}).json()['kind']=='collect'
    with store.db() as c:
        jid=store.enqueue(c,'images',{},mid)
        job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
    monkeypatch.setattr(assets,'download',lambda _:(PNG,'png'))
    service.run_job(job)
    assert store.get(mid)['collection']=='partial'
