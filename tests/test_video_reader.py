import pytest
from fastapi.testclient import TestClient
from app import adapters, main, service, store


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'ROOT', tmp_path)
    monkeypatch.setattr(store, 'DATA', tmp_path/'data')
    monkeypatch.setattr(store, 'settings', lambda: {})
    monkeypatch.setattr(service, 'worker', lambda: None)
    monkeypatch.setattr(service, 'favorites_worker', lambda: None)
    with TestClient(main.app, headers={'X-Local-Request':'1'}) as client:
        yield client


def material(client):
    return client.post('/api/materials', json={'url':'https://www.youtube.com/watch?v=TST00001606',
        'title':'字幕夹具', 'text':'保留视频说明', 'subtitles':'WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n原字幕\n',
        'language':'zh', 'subtitle_source':'平台字幕'}).json()['id']


def test_source_distinguishes_native_automatic_translation():
    info={'subtitles':{'en':[{'ext':'json3','url':'https://example.org/native'}]},
          'automatic_captions':{'zh-Hans':[{'ext':'json3','url':'https://example.org/auto?tlang=zh-Hans'}]}}
    tracks=adapters.youtube_subtitle_candidates(info)
    assert '自动翻译' not in tracks[0]['source']
    assert '自动翻译' in tracks[1]['source']


def test_secondary_track_excludes_same_language_and_preserves_timeline(tmp_path, monkeypatch):
    calls=[]
    def fetch(url, headers):
        calls.append(url)
        return 'WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHello\n\n00:00:05.000 --> 00:00:09.000\nWorld\n',url
    monkeypatch.setattr(adapters,'fetch',fetch)
    candidates=[{'language':'zh-Hans','source':'平台字幕','format':'vtt','url':'same'},
                {'language':'en','source':'平台字幕','format':'vtt','url':'other'}]
    result=adapters.secondary_subtitles({'language':'ai-zh'},candidates,tmp_path)
    assert calls==['other']
    assert result['subtitle_tracks'][0]['segments'][-1]['end']==9
    assert (tmp_path/'secondary-subtitles.vtt').read_text('utf-8').endswith('World\n')


def test_missing_secondary_is_not_fabricated(tmp_path):
    result=adapters.secondary_subtitles({'language':'en'},[],tmp_path)
    assert not result['subtitle_tracks'] and '未返回' in result['bilingual_notice']


@pytest.mark.parametrize('processing',['pending','later','done'])
def test_secondary_job_keeps_primary_notes_summary_and_processing(local, monkeypatch, processing):
    mid=material(local)
    with store.db() as c:
        c.execute('UPDATE materials SET notes=?,summary=?,processing=? WHERE id=?',('自己的理解','已有摘要',processing,mid))
    before=store.get(mid)
    track={'language':'en','source':'平台自动字幕（机器生成）','segments':[{'start':1,'end':3,'text':'Original speech'},{'start':500,'end':502,'text':'Later speech'}]}
    monkeypatch.setattr(adapters,'fetch_secondary_subtitles',lambda *a:{'subtitle_tracks':[track],'bilingual_notice':''})
    response=local.post(f'/api/materials/{mid}/subtitle-tracks')
    assert response.status_code==200
    with store.db() as c:job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(response.json()['job_id'],)).fetchone())
    service.run_job(job)
    after=store.get(mid)
    for key in ('notes','summary','processing','collection','body'):assert after[key]==before[key]
    assert after['content']['segments']==before['content']['segments']
    assert after['revision']==before['revision']+1
    markdown=local.get(f'/api/materials/{mid}/markdown').text
    assert '第二语言字幕 · en' in markdown and '00:08:20.000 → 00:08:22.000' in markdown and '原字幕' in markdown


def test_stale_secondary_result_cannot_overwrite_a_user_note(local, monkeypatch):
    mid=material(local)
    def fetch(item,folder):
        with store.db() as c:c.execute('UPDATE materials SET notes=?,revision=revision+1 WHERE id=?',('刚写下的理解',mid))
        return {'subtitle_tracks':[{'language':'en','source':'平台字幕','segments':[]}], 'bilingual_notice':''}
    monkeypatch.setattr(adapters,'fetch_secondary_subtitles',fetch)
    with pytest.raises(ValueError,match='变化'):service.save_secondary_subtitles(mid,store.material_folder(mid))
    assert store.get(mid)['notes']=='刚写下的理解' and not store.get(mid)['content'].get('subtitle_tracks')
    with store.db() as c:assert c.execute("SELECT 1 FROM events WHERE material_id=? AND kind='subtitle_tracks_stale'",(mid,)).fetchone()


def test_failed_refresh_keeps_already_saved_secondary(local, monkeypatch):
    mid=material(local)
    saved={'language':'en','source':'平台字幕','segments':[{'start':1,'end':3,'text':'saved'}]}
    monkeypatch.setattr(adapters,'fetch_secondary_subtitles',lambda *a:{'subtitle_tracks':[saved]})
    service.save_secondary_subtitles(mid,store.material_folder(mid))
    monkeypatch.setattr(adapters,'fetch_secondary_subtitles',lambda *a:{'subtitle_tracks':[],'bilingual_notice':'另一语言字幕读取失败'})
    service.save_secondary_subtitles(mid,store.material_folder(mid))
    assert store.get(mid)['content']['subtitle_tracks']==[saved]


def test_embed_policy_is_scoped_and_secondary_refuses_trash(local):
    policy=local.get('/api/materials').headers['Content-Security-Policy']
    assert 'https://player.bilibili.com' in policy and 'https://open.douyin.com' in policy
    assert "connect-src 'self'" in policy and 'unsafe-inline' not in policy
    mid=material(local);local.delete(f'/api/materials/{mid}')
    assert local.post(f'/api/materials/{mid}/subtitle-tracks').status_code==400


def test_secondary_failure_is_visible_without_changing_primary_collection(local):
    mid=material(local)
    before=store.get(mid)
    job=local.post(f'/api/materials/{mid}/subtitle-tracks').json()['job_id']
    with store.db() as c:c.execute("UPDATE jobs SET state='failed',error='字幕请求受限' WHERE id=?",(job,))
    response=local.get(f'/api/materials/{mid}').json()
    assert response['subtitle_job']['state']=='failed' and response['subtitle_job']['error']=='字幕请求受限'
    assert response['collection']==before['collection'] and response['revision']==before['revision']
