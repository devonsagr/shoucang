import json
import pytest
from fastapi.testclient import TestClient
from app import bilingual,main,service,store

@pytest.fixture
def local(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'ROOT',tmp_path);monkeypatch.setattr(store,'DATA',tmp_path/'data')
    monkeypatch.setattr(store,'settings',lambda:{})
    monkeypatch.setattr(service,'worker',lambda:None);monkeypatch.setattr(service,'favorites_worker',lambda:None)
    monkeypatch.setattr(bilingual,'translate_batch',lambda texts,direction,report:['译文 '+t for t in texts])
    with TestClient(main.app,headers={'X-Local-Request':'1'}) as c:yield c

def material(local):
    mid=local.post('/api/materials',json={'url':'https://x.com/i/status/2345678901','text':'Keep the original.\n\nThis is useful.','title':'翻译验收夹具'}).json()['id']
    item=store.get(mid);content={**item['content'],'comments':[{'author':'reader','body':'A useful reply.','url':item['url']}],'comments_status':'只存档一条回复'}
    with store.db() as c:c.execute('UPDATE materials SET content_json=?,notes=?,summary=?,processing=? WHERE id=?',(store.dumps(content),'我的理解','我的摘要','later',mid))
    return mid

def run(mid,jid):
    with store.db() as c:job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
    service.run_job(job)
    with store.db() as c:c.execute("UPDATE jobs SET state='done' WHERE id=?",(jid,))

def test_selected_translation_is_deduplicated_and_keeps_original_understanding_and_status(local):
    mid=material(local);before=store.get(mid)
    first=local.post(f'/api/materials/{mid}/bilingual').json()
    assert local.post(f'/api/materials/{mid}/bilingual').json()['job_id']==first['job_id']
    run(mid,first['job_id']);after=store.get(mid)
    for key in ('body','notes','summary','processing','collection','title','updated'):assert after[key]==before[key]
    assert after['content']['comments']==before['content']['comments']
    ready=local.get(f'/api/materials/{mid}').json()
    assert ready['reader_translation']['units']['comment:0:0']['text']=='译文 A useful reply.'
    assert ready['reader_translation']['units']['body:1']['source']==bilingual.SOURCE
    assert local.post(f'/api/materials/{mid}/bilingual').json()['cached'] is True
    assert '双语阅读译文' in ready['markdown'] and '回复 1 的译文' in ready['markdown'] and before['body'] in ready['markdown']

def test_new_notes_during_translation_are_kept(local,monkeypatch):
    mid=material(local)
    def engine(texts,direction,report):
        with store.db() as c:c.execute('UPDATE materials SET notes=?,revision=revision+1 WHERE id=?',('阅读过程中新的理解',mid))
        return ['译文' for _ in texts]
    monkeypatch.setattr(bilingual,'translate_batch',engine)
    jid=local.post(f'/api/materials/{mid}/bilingual').json()['job_id'];run(mid,jid)
    assert store.get(mid)['notes']=='阅读过程中新的理解'

def test_original_change_during_translation_cannot_publish_stale_units(local,monkeypatch):
    mid=material(local)
    def engine(texts,direction,report):
        with store.db() as c:c.execute('UPDATE materials SET body=?,revision=revision+1 WHERE id=?',('Changed original',mid))
        return ['旧译文' for _ in texts]
    monkeypatch.setattr(bilingual,'translate_batch',engine)
    jid=local.post(f'/api/materials/{mid}/bilingual').json()['job_id']
    with pytest.raises(ValueError,match='原文或回复已变化'):run(mid,jid)
    assert not bilingual.current(store.get(mid)) and store.get(mid)['body']=='Changed original'
    with store.db() as c:assert c.execute("SELECT count(*) FROM events WHERE kind='bilingual_stale' AND material_id=?",(mid,)).fetchone()[0]==1

def test_trash_and_inflight_collection_do_not_start_translation(local):
    mid=material(local)
    with store.db() as c:store.enqueue(c,'collect',{},mid)
    assert local.post(f'/api/materials/{mid}/bilingual').status_code==400
    local.delete(f'/api/materials/{mid}')
    assert local.post(f'/api/materials/{mid}/bilingual').status_code==400

def test_image_paragraph_ids_and_long_input_are_not_lost():
    source='Before.\n\n![image](images/a.png)\n\nAfter.\n![second](images/b.png)\n\nLast.'
    assert bilingual.paragraphs(source)==['Before.','After.','Last.']
    text=('A long sentence. '*100)+'https://example.org/source?a=1&b=2'
    parts=bilingual.split_text(text)
    assert ''.join(t for t,_ in parts)==text
    assert all(len(t)<=500 for t,protected in parts if not protected)
    assert parts[-1]==('https://example.org/source?a=1&b=2',True)

def test_platform_cue_translation_is_preferred_and_its_time_source_is_kept(monkeypatch):
    item={'body':'','content':{'language':'en','segments':[{'start':10,'end':12,'text':'Hello'}],
        'subtitle_tracks':[{'language':'zh-Hans','source':'平台自动翻译字幕','segments':[{'start':10,'end':12,'text':'你好'}]}]}}
    monkeypatch.setattr(bilingual,'translate_batch',lambda *args:pytest.fail('platform track must be used'))
    result=bilingual.translate(item)['units']['caption:0']
    assert result['text']=='你好' and result['source']=='平台自动翻译字幕' and result['start']==10 and result['end']==12

def test_cancelled_local_translation_preserves_source(monkeypatch):
    item={'body':'Read this.','content':{}}
    with pytest.raises(ValueError,match='停止'):bilingual.translate(item,cancelled=lambda:True)

def test_unsupported_language_is_not_marked_fully_translated(monkeypatch):
    monkeypatch.setattr(bilingual,'translate_batch',lambda texts,*args:['译文' for _ in texts])
    result=bilingual.translate({'body':'English description','content':{'language':'fr','segments':[{'start':0,'end':1,'text':'Bonjour'}]}})
    assert not result['complete'] and result['unsupported_captions']==1 and 'caption:0' not in result['units']

def test_target_tokens_decode_spaces_without_changing_urls_or_underscores(monkeypatch):
    class Tokenizer:
        def encode(self,text,out_type):return [text]
        def decode(self,tokens):return ''.join(tokens)
    class Result:
        hypotheses=[['A', '\u2581useful', '\u2581source_id.']]
    class Translator:
        def translate_batch(self,inputs,**options):return [Result() for _ in inputs]
    monkeypatch.setattr(bilingual,'runtime',lambda *args:(Translator(),Tokenizer(),''))
    text='一个有用的来源。 https://example.org/source_id?a=1&b=2'
    result=bilingual.translate_batch([text],'zh_en',lambda _:None)[0]
    assert result=='A useful source_id. https://example.org/source_id?a=1&b=2'
    assert '\u2581' not in result

def test_reply_containing_only_account_handle_does_not_invent_translation():
    item={'body':'Read this.','content':{'comments':[{'body':'@hiiipowers 🏡'},{'body':'A useful reply. @source_id'}]}}
    output=bilingual.units(item)
    assert [u['id'] for u in output]==['body:0','comment:1:0']
    parts=bilingual.split_text('A useful reply. @source_id https://example.org/source_id')
    assert ''.join(t for t,_ in parts)=='A useful reply. @source_id https://example.org/source_id'
    assert ('@source_id',True) in parts
