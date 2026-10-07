import json
from pathlib import Path
import pytest
from app import main,service,store
from test_knowledge import local,material

def shelf(client,mid,stage,overview=''):
    response=client.post(f'/api/materials/{mid}/push-preview',json={'destination':'obsidian','complete_processing':False,
        'shelf_output':{'stage':stage,'overview':overview}})
    assert response.status_code==200,response.text
    return response.json()

def confirm(client,p):
    response=client.post(f'/api/pushes/{p["id"]}/confirm',json={'hash':p['hash']})
    assert response.status_code==200,response.text
    return response.json()

def test_ai_and_annotation_wait_in_first_layer_then_review_allows_formal_knowledge(local):
    client,vault,_=local;mid=material(client)
    item=store.get(mid)
    client.put(f'/api/materials/{mid}/notes',json={'notes':'灵感：以后做工具可以用上','annotation_kind':'inspiration','revision':item['revision']})
    with store.db() as c:c.execute('UPDATE materials SET summary=? WHERE id=?',('合成AI整理结果，未人工查看',mid))
    p=shelf(client,mid,'ai_review');assert '\\01_AI待查看\\' in p['destination'] and '\\科技AI\\' not in p['destination']
    confirm(client,p);assert Path(p['destination']).exists() and store.get(mid)['processing']=='pending'
    annotation=shelf(client,mid,'annotation');assert '\\03_我的批注\\科技AI\\' in annotation['destination'];confirm(client,annotation)
    assert '灵感' in Path(annotation['destination']).read_text('utf-8')
    output={'destination':'obsidian','knowledge_output':{'title':'正式知识','text':'经我查看后形成的理解','folder':'06_资料与教程'}}
    assert client.post(f'/api/materials/{mid}/push-preview',json=output).status_code==400
    detail=client.get('/api/materials/'+mid).json();assert not detail['ai_review']['reviewed']
    reviewed=client.post(f'/api/materials/{mid}/ai-review',json={'revision':detail['revision'],'summary_hash':detail['ai_review']['summary_hash']})
    assert reviewed.status_code==200
    formal=client.post(f'/api/materials/{mid}/push-preview',json=output);assert formal.status_code==200,formal.text
    confirm(client,formal.json());assert store.get(mid)['processing']=='done'
    assert not Path(p['destination']).exists() and not Path(annotation['destination']).exists()
    assert Path(formal.json()['destination']).exists()
    assert len(client.get('/api/materials/'+mid).json()['vault_receipts'])==3
    with store.db() as c:c.execute('UPDATE materials SET summary=? WHERE id=?',('新的AI结果',mid))
    assert not client.get('/api/materials/'+mid).json()['ai_review']['reviewed']

def test_reference_is_queryable_not_a_claim_of_human_digest_and_can_return_to_pending(local):
    client,vault,_=local;mid=material(client)
    p=shelf(client,mid,'reference','AI代理工作流的资料，以后配置工具时调用')
    assert '\\02_资料索引\\科技AI\\' in p['destination']
    assert client.get('/api/reference-index?q=代理').json()['items']==[]
    confirm(client,p)
    current=store.get(mid);assert current['processing']=='pending' and current['content']['reading_intent']=='reference'
    index=client.get('/api/reference-index?q=代理').json()['items'];assert len(index)==1 and index[0]['material_id']==mid
    assert index[0]['overview']=='AI代理工作流的资料，以后配置工具时调用'
    assert not client.get('/api/materials?state=pending').json()['items']
    listed=client.get('/api/materials?state=reference').json()
    assert listed['counts']['all']==1 and listed['counts']['reference']==1 and listed['counts']['pending']==0
    assert 'human_digest: false' in Path(p['destination']).read_text('utf-8')
    assert client.post(f'/api/materials/{mid}/return-to-reading',json={'revision':current['revision']}).status_code==200
    assert len(client.get('/api/materials?state=pending').json()['items'])==1
    assert client.get('/api/materials?state=reference').json()['counts']['reference']==0
    assert Path(p['destination']).exists()

def test_first_layer_never_marks_done_and_cannot_fake_missing_ai_or_annotations(local):
    client,_,_=local;mid=material(client)
    for stage in ('ai_review','annotation','reference'):
        assert client.post(f'/api/materials/{mid}/push-preview',json={'destination':'obsidian','complete_processing':False,'shelf_output':{'stage':stage}}).status_code==400
    assert client.post(f'/api/materials/{mid}/push-preview',json={'destination':'obsidian','shelf_output':{'stage':'reference','overview':'概览'}}).status_code==400
    with store.db() as c:c.execute('UPDATE materials SET summary=? WHERE id=?',('AI结果',mid))
    detail=client.get('/api/materials/'+mid).json()
    assert client.post(f'/api/materials/{mid}/ai-review',json={'revision':detail['revision'],'summary_hash':'old'}).status_code==400

def test_next_day_import_only_queues_new_content_preserves_old_missing_and_trashed(local,monkeypatch):
    client,_,_=local
    entries=[{'url':'https://x.com/i/status/'+str(1000000000+i),'title':'导入夹具 '+str(i),'body':'第'+str(i)+'条原文',
        'collection':'ready','content':{'source':'合成收藏清单','original_text_complete':True}} for i in range(5)]
    pages=[]
    def reader(kind,url,record,progress,cancelled):
        for page in pages:
            for entry in page:record(entry)
            progress['pages']=progress.get('pages',0)+1;progress['complete']=False;yield progress
        progress['complete']=True;yield progress
    monkeypatch.setattr(service.platform_browser,'favorites',reader)
    def run():
        with store.db() as c:jid=store.enqueue(c,'favorites',{'platform':'x','url':'https://x.com/i/bookmarks'})
        with store.db() as c:job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
        service.run_job(job)
        with store.db() as c:c.execute("UPDATE jobs SET state='done' WHERE id=?",(jid,))
        return jid
    pages[:]=[entries[:4]];run()
    with store.db() as c:old=c.execute('SELECT id,canonical FROM materials ORDER BY canonical').fetchall()
    # Finish one, annotate another, retain a remote-unfavorited third and soft-delete a fourth.
    for index,row in enumerate(old):
        with store.db() as c:
            c.execute('UPDATE materials SET notes=?,summary=?,processing=? WHERE id=?',('我的批注 '+str(index),'旧AI整理','done' if index==0 else 'later',row['id']))
            c.execute("UPDATE jobs SET state='done' WHERE material_id=?",(row['id'],))
    client.delete('/api/materials/'+old[3]['id'])
    before={row['id']:store.get(row['id']) for row in old}
    pages[:]=[[entries[4],entries[0]],[entries[3],entries[1]]];jid=run()
    for mid,saved in before.items():
        after=store.get(mid)
        for field in ('body','notes','summary','processing','trashed','created','updated'):assert after[field]==saved[field],field
    with store.db() as c:
        assert c.execute('SELECT count(*) FROM materials').fetchone()[0]==5
        assert c.execute("SELECT count(*) FROM jobs WHERE kind='collect' AND state='queued'").fetchone()[0]==1
        progress=json.loads(c.execute('SELECT progress FROM jobs WHERE id=?',(jid,)).fetchone()[0])
    assert progress['new']==1 and progress['duplicates']==3 and progress['complete']
    assert progress['mode']=='reconcile' and progress['only_new_content'] and progress['preserves_old_materials']
    assert progress['pages']==2
