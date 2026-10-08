import json
from app import service,store
from test_automatic_collection import local

def test_all_active_work_is_counted_beyond_the_legacy_200_rows(local):
    client,_=local
    mid=service.add({'url':'https://example.org/task-fixture','text':'合成正文'},enqueue_collect=False)['id']
    with store.db() as c:
        for i in range(240):store.enqueue(c,'sync',{'platform':'heybox','url':'https://example.org/list','private':'must-not-leak'})
        jid=store.enqueue(c,'collect',{},mid)
        c.execute("UPDATE jobs SET state='running',progress=? WHERE id=?",(store.dumps({'stage':'transcribing','seconds':60,'duration':600,'message':'转写到1分钟'}),jid))
        store.enqueue(c,'overview',{},mid);store.enqueue(c,'bilingual',{},mid)
    r=client.get('/api/tasks').json()
    assert r['counts']['running']==1 and r['counts']['queued']==242 and len(r['active'])==40
    assert r['active'][0]['label']=='转写字幕' and r['active'][0]['title']=='https://example.org/task-fixture'
    assert 'must-not-leak' not in json.dumps(r) and 'payload' not in r['active'][0]
    assert len(client.get('/api/jobs').json())==200
    assert {g['kind'] for g in r['groups']}=={'sync','collect','overview','bilingual'}

def test_successful_retry_resolves_attention_but_preserves_history(local):
    client,_=local
    mid=service.add({'url':'https://example.org/retry-fixture','text':'原文'},enqueue_collect=False)['id']
    with store.db() as c:
        old=store.enqueue(c,'images',{},mid);c.execute("UPDATE jobs SET state='failed',error='图片传输失败' WHERE id=?",(old,))
        newer=store.enqueue(c,'images',{},mid);c.execute("UPDATE jobs SET state='done',error='' WHERE id=?",(newer,))
        stopped=store.enqueue(c,'favorites',{'platform':'x'});c.execute("UPDATE jobs SET state='failed',error='用户停止读取；可继续' WHERE id=?",(stopped,))
    result=client.get('/api/tasks').json()
    assert result['counts']['attention']==0
    assert {r['id'] for r in result['recent']}=={old,newer,stopped}
    assert next(r for r in result['recent'] if r['id']==stopped)['status_label']=='已停止'

def test_platform_filter_and_closed_dialog_cannot_change_global_activity(local):
    client,_=local
    with store.db() as c:
        a=store.enqueue(c,'favorites',{'platform':'heybox'});c.execute("UPDATE jobs SET state='running' WHERE id=?",(a,))
        b=store.enqueue(c,'bilingual',{'platform':'bilibili'});c.execute("UPDATE jobs SET state='paused',error='需本人验证' WHERE id=?",(b,))
    before=client.get('/api/tasks').json();client.get('/api/materials?platform=x');after=client.get('/api/tasks').json()
    assert before['counts']==after['counts']=={'running':1,'queued':0,'attention':1}
    assert after['active'][0]['id']==a and after['attention'][0]['id']==b
    assert client.get('/api/tasks?limit=0').status_code==400

def test_finished_favorite_batch_does_not_claim_the_list_is_complete(local):
    client,_=local
    with store.db() as c:
        jid=store.enqueue(c,'favorites',{'platform':'x'});c.execute("UPDATE jobs SET state='done',progress=? WHERE id=?",(store.dumps({'complete':False}),jid))
    assert '未确认末尾' in client.get('/api/tasks').json()['recent'][0]['status_label']
