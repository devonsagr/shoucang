import sys
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app import main, obsidian, service, store, video_pipeline

@pytest.fixture
def local(tmp_path, monkeypatch):
    config={}
    monkeypatch.setattr(store,'ROOT',tmp_path)
    monkeypatch.setattr(store,'DATA',tmp_path/'data')
    monkeypatch.setattr(store,'settings',lambda:config.copy())
    monkeypatch.setattr(service,'worker',lambda:None)
    monkeypatch.setattr(service,'favorites_worker',lambda:None)
    with TestClient(main.app,headers={'X-Local-Request':'1'}) as client:
        yield client, config

def material(client, suffix='12345678'):
    return client.post('/api/materials',json={'url':'https://x.com/i/status/'+suffix,'text':'原文夹具','title':'测试材料'}).json()['id']

def test_purge_requires_trash_explicit_current_confirmation_and_preserves_others(local):
    client,_=local
    mid=material(client); other=material(client,'12345679')
    folder=store.material_folder(mid); image=folder/'images/a.png'
    image.parent.mkdir(); image.write_bytes(b'fixture image')
    exported=service.preview(mid,'knowledge')
    service.confirm(exported['id'],exported['hash'])
    confirmed_outbox=store.DATA/'outbox/knowledge'/exported['id']
    preview=service.preview(mid,'todo')
    before=store.get(mid)['revision']
    assert client.post(f'/api/materials/{mid}/purge',json={'revision':before,'confirmation':'彻底删除'}).status_code==400
    client.delete(f'/api/materials/{mid}')
    revision=store.get(mid)['revision']
    assert client.post(f'/api/materials/{mid}/purge',json={'revision':revision,'confirmation':'删除'}).status_code==422
    assert client.post(f'/api/materials/{mid}/purge',json={'revision':before,'confirmation':'彻底删除'}).status_code==400
    assert folder.exists()
    response=client.post(f'/api/materials/{mid}/purge',json={'revision':revision,'confirmation':'彻底删除'})
    assert response.status_code==200 and response.json()['purged']
    assert not folder.exists() and store.get(other)['body']=='原文夹具'
    assert confirmed_outbox.exists()
    with store.db() as c:
        for table in ('materials','versions','events','jobs'):
            column='id' if table=='materials' else 'material_id'
            assert not c.execute(f'SELECT 1 FROM {table} WHERE {column}=?',(mid,)).fetchone()
        assert c.execute('SELECT state FROM pushes WHERE id=?',(exported['id'],)).fetchone()[0]=='confirmed'
        assert not c.execute('SELECT 1 FROM pushes WHERE id=?',(preview['id'],)).fetchone()

def test_purge_waits_for_inflight_job_and_rejects_linked_root(local):
    client,_=local; mid=material(client); client.delete(f'/api/materials/{mid}')
    revision=store.get(mid)['revision']
    with store.db() as c:
        c.execute("INSERT INTO jobs(id,material_id,kind,payload,state,created,updated) VALUES ('inflight',?,'collect','{}','running',?,?)",(mid,store.now(),store.now()))
    response=client.post(f'/api/materials/{mid}/purge',json={'revision':revision,'confirmation':'彻底删除'})
    assert response.status_code==400 and '后台任务' in response.text
    assert store.material_folder(mid).exists()

def test_purge_rejects_directory_escape_before_deleting_anything(local, monkeypatch):
    client,_=local;mid=material(client);client.delete(f'/api/materials/{mid}')
    outside=store.ROOT/'protected-folder';outside.mkdir();kept=outside/'keep.md';kept.write_text('保留','utf-8')
    monkeypatch.setattr(store,'material_folder',lambda *a:outside)
    with pytest.raises(ValueError,match='越界'):store.purge(mid,store.get(mid)['revision'],'彻底删除')
    assert kept.read_text('utf-8')=='保留' and store.get(mid)['trashed']

@pytest.mark.parametrize('state,label',[('pending','待处理'),('later','稍后整理'),('done','已完成')])
def test_obsidian_current_state_snapshot_requires_confirmation_and_preserves_state(local,state,label):
    client,config=local; vault=store.ROOT/'fixture-vault'; vault.mkdir();config['obsidian_vault']=str(vault)
    mid=material(client)
    client.post(f'/api/materials/{mid}/status',json={'state':state})
    preview=client.post(f'/api/materials/{mid}/push-preview',json={'destination':'obsidian','complete_processing':False}).json()
    assert f'收藏处理器/X/{label}/' in preview['payload']['obsidian']['note']
    assert not list(vault.iterdir())
    response=client.post('/api/pushes/'+preview['id']+'/confirm',json={'hash':preview['hash']})
    assert response.status_code==200
    assert store.get(mid)['processing']==state
    assert __import__('pathlib').Path(response.json()['path']).read_text('utf-8')==preview['markdown']

def test_normal_completed_push_uses_done_directory_and_current_markdown(local):
    client,config=local; vault=store.ROOT/'fixture-vault';vault.mkdir();config['obsidian_vault']=str(vault)
    mid=material(client)
    preview=service.preview(mid,'obsidian')
    assert '/已完成/' in preview['payload']['obsidian']['note'] and '- 处理状态：已完成' in preview['markdown']
    service.confirm(preview['id'],preview['hash'])
    assert store.get(mid)['processing']=='done'
    assert (store.material_folder(mid)/'material.md').read_text('utf-8')==store.markdown(store.get(mid))

def test_empty_category_structure_creates_no_materials_and_protects_existing_files(local):
    client,config=local;vault=store.ROOT/'fixture-vault';vault.mkdir();config['obsidian_vault']=str(vault)
    kept=vault/'existing.md';kept.write_text('人工内容','utf-8')
    response=client.post('/api/obsidian/structure',json={})
    assert response.status_code==200 and response.json()['materials_written']==0
    assert response.json()['directories']==28
    assert (vault/'收藏处理器/B站/待处理').is_dir() and (vault/'收藏处理器/X/稍后整理').is_dir()
    assert kept.read_text('utf-8')=='人工内容' and not list((vault/'收藏处理器').rglob('*.md'))

@pytest.mark.parametrize('decoded,expected,should_pass',[(10,600,False),(599,600,True),(15,600,False),(620,600,False)])
def test_transcription_checks_decoded_full_audio_not_last_speech(tmp_path,monkeypatch,decoded,expected,should_pass):
    monkeypatch.setattr(store,'DATA',tmp_path/'data')
    monkeypatch.setattr(store,'settings',lambda:{'whisper_model':'turbo'})
    monkeypatch.setattr(video_pipeline,'whisper_runtime',lambda:('cpu','int8'))
    consumed=[]
    def segments():
        consumed.append(True)
        yield SimpleNamespace(start=0,end=9,text='前面说话，后面可能是静音')
    class Model:
        def __init__(self,*a,**k):pass
        def transcribe(self,*a,**k):
            return segments(),SimpleNamespace(language='zh',duration=decoded,duration_after_vad=9)
    monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=Model))
    content={}
    if should_pass:
        result=video_pipeline.transcribe(tmp_path/'fixture.wav',expected,content,tmp_path)
        assert result['transcription']['decoded_duration']==decoded
        assert content['audio_validation']['duration_matches'] and consumed
    else:
        with pytest.raises(ValueError,match='音频时长与视频不一致'):
            video_pipeline.transcribe(tmp_path/'fixture.wav',expected,content,tmp_path)
        video_pipeline.transcription_failure(content,ValueError('片段音频'))
        assert not content['audio_validation']['duration_matches'] and content['transcript_state']=='failed'
        assert not consumed and not content.get('segments')

def test_sparse_transcription_rechecks_without_vad_but_never_claims_full_success(tmp_path,monkeypatch):
    from app import adapters
    monkeypatch.setattr(store,'DATA',tmp_path/'data')
    monkeypatch.setattr(store,'settings',lambda:{'whisper_model':'turbo'})
    monkeypatch.setattr(video_pipeline,'whisper_runtime',lambda:('cpu','int8'))
    calls=[]
    class Model:
        def __init__(self,*a,**k):pass
        def transcribe(self,*a,**k):
            calls.append(k['vad_filter'])
            end=7 if k['vad_filter'] else 100
            return iter([SimpleNamespace(start=6,end=end,text='仅供测试的稀疏识别结果')]),SimpleNamespace(language='en',duration=600,duration_after_vad=1)
    monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=Model))
    def extractor(url,args,**kwargs):
        if '--dump-single-json' in args:return '{"title":"稀疏语音夹具","duration":600}'
        (tmp_path/'audio.webm').write_bytes(b'fixture')
        return ''
    monkeypatch.setattr(adapters,'ytdlp',extractor)
    result=adapters.video('https://youtube.com/watch?v=fixture',tmp_path,True)
    assert calls==[True,False]
    assert result['collection']=='partial' and result['content']['transcript_state']=='uncertain'
    assert store.transcript_status('youtube','partial',result['content'])=='uncertain'
    assert result['content']['segments'][0]['end']==100 and '不能确认全片' in result['content']['warning']
    assert not (tmp_path/'audio.webm').exists()


def test_later_suspends_an_uncollected_item_without_notes_ai_or_export(local):
    client,_=local
    mid=client.post('/api/materials',json={'url':'https://x.com/i/status/12345681'}).json()['id']
    before=store.get(mid)
    assert before['collection']=='queued' and before['notes']==''
    result=client.post(f'/api/materials/{mid}/status',json={'state':'later','revision':before['revision']})
    assert result.status_code==200
    after=store.get(mid)
    for key in ('body','notes','summary','collection','url','origin'):assert after[key]==before[key]
    assert after['processing']=='later'
    assert client.get('/api/materials',params={'state':'pending'}).json()['items']==[]
    listing=client.get('/api/materials',params={'state':'later'}).json()
    assert listing['items'][0]['id']==mid and listing['counts']['later']==1
    markdown=client.get(f'/api/materials/{mid}/markdown').text
    assert '稍后整理' in markdown and '已读' not in markdown
    with store.db() as c:
        assert c.execute('SELECT count(*) FROM pushes WHERE material_id=?',(mid,)).fetchone()[0]==0
        assert c.execute("SELECT count(*) FROM jobs WHERE material_id=? AND kind='ai'",(mid,)).fetchone()[0]==0
    assert client.post(f'/api/materials/{mid}/status',json={'state':'pending','revision':after['revision']}).status_code==200
    assert client.get('/api/materials',params={'state':'pending'}).json()['items'][0]['id']==mid
