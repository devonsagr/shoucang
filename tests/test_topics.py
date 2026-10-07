import json
import pytest
from fastapi.testclient import TestClient
from app import main, service, store, topics

@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'ROOT', tmp_path)
    monkeypatch.setattr(store, 'DATA', tmp_path/'data')
    monkeypatch.setattr(store, 'settings', lambda: {})
    monkeypatch.setattr(service, 'worker', lambda: None)
    monkeypatch.setattr(service, 'favorites_worker', lambda: None)
    with TestClient(main.app, headers={'X-Local-Request': '1'}) as client:
        yield client

def add(client, number, text, origin='favorite', platform='x'):
    url = f'https://x.com/i/status/{number}' if platform=='x' else f'https://example.com/{number}'
    response = client.post('/api/materials', json={'url': url, 'title': text[:100], 'text': text, 'origin': origin})
    assert response.status_code==200
    return response.json()['id']

@pytest.mark.parametrize('text,expected', [
    ('OpenAI 发布大模型，编程助手与 GPU 测评', 'tech'),
    ('Mr. Morale & The Big Steppers studio sessions 🎹', 'music'),
    ('Kendrick Lamar 专辑的创作过程', 'music'),
    ('电影导演与演员的幕后采访', 'entertainment'),
    ('Elden Ring 游戏攻略', 'games'),
    ('Kanye West on the Israel - Palestine conflict', 'society'),
    ('用 Obsidian 整理读书笔记与学习方法', 'life'),
    ('没想到今天会这样 🤔', 'uncategorized'),
    ('mail fair repair stairs said', 'uncategorized'),
])
def test_local_classifier_distinguishes_topics_and_unknown(text, expected):
    result=topics.classify('', text)
    assert result['topic']==expected and result['detail']['method']=='local_rules'

def test_urls_authors_image_placeholders_and_comments_are_not_topic_evidence():
    result=topics.classify('@Music：看这个', 'https://example.com/ai/album ![AI图片](images/a.png)',
                           {'comments':[{'body':'人工智能专辑游戏'}]})
    assert result['topic']=='uncategorized'
    assert topics.classify('', 'AI music')['topic']=='tech'  # stronger explicit concept
    assert topics.classify('', 'AI Kendrick')['topic']=='uncategorized'  # equal strong signals
    assert topics.classify('', '', {'segments':[{'text':'普通开场'},{'text':'这是人工智能模型的演示'}]})['topic']=='tech'

def test_topic_filter_counts_follow_platform_status_origin_and_search(local):
    music=add(local, 801, 'Drake album recording')
    add(local, 802, 'OpenAI 编程演示')
    later=add(local, 803, 'Kendrick album', origin='link')
    add(local, 804, 'Kendrick album', platform='web')
    local.post(f'/api/materials/{later}/status', json={'state':'later'})
    data=local.get('/api/materials?state=pending&platform=x&topic=music').json()
    assert [m['id'] for m in data['items']]==[music]
    assert data['counts']=={'pending':1,'later':1,'review':0,'done':0,'reference':0,'all':2,'trash':0,'source_archive':0,'callable':0,'digest':0}
    counts={t['id']:t['count'] for t in data['topics']}
    assert counts['music']==1 and counts['tech']==1  # topic shelf excludes its own filter
    favorite=local.get('/api/materials?state=all&platform=x&topic=music&origin=favorite&q=Drake').json()
    assert favorite['counts']['all']==1 and sum(t['count'] for t in favorite['topics'])==1
    assert local.get('/api/materials?topic=unknown').status_code==400

def test_manual_choice_preserves_content_and_survives_recollection(local):
    mid=add(local, 811, 'Drake album')
    assert local.put(f'/api/materials/{mid}/notes', json={'notes':'我自己的理解','revision':store.get(mid)['revision']}).status_code==200
    local.post(f'/api/materials/{mid}/status', json={'state':'later'})
    before=store.get(mid)
    assert before['notes']=='我自己的理解'
    response=local.post(f'/api/materials/{mid}/topic', json={'topic':'entertainment','revision':before['revision']})
    assert response.status_code==200
    after=store.get(mid)
    for field in ('body','content','notes','summary','collection','processing','updated'):
        assert after[field]==before[field]
    assert after['topic']=='entertainment' and after['topic_source']=='manual'
    service.save_content(mid, {'title':'OpenAI 新模型', 'body':'人工智能', 'collection':'ready','content':{'source':'重采测试'}})
    assert store.get(mid)['topic']=='entertainment'
    current=store.get(mid)
    reset=local.post(f'/api/materials/{mid}/topic', json={'topic':'auto','revision':current['revision']}).json()
    assert reset['topic']=='tech' and reset['topic_source']=='automatic'
    with store.db() as c:
        events=[json.loads(r[0]) for r in c.execute("SELECT detail FROM events WHERE material_id=? AND kind='topic_assigned'",(mid,))]
    assert events[-2]['source']=='manual' and events[-1]['to']=='tech'

def test_old_material_migration_is_idempotent_and_only_changes_topic_metadata(local):
    mid=add(local, 821, '音乐专辑')
    with store.db() as c:
        c.execute("UPDATE materials SET topic_source='unclassified',topic_detail='{}',processing='done',notes='保留',summary='摘要' WHERE id=?",(mid,))
    before=store.get(mid)
    assert service.organize_topics()==1
    after=store.get(mid)
    for field in ('body','content','notes','summary','processing','collection','updated','trashed'):
        assert before[field]==after[field]
    assert after['revision']==before['revision']+1 and after['topic']=='music'
    assert '内容主题：音乐' in (store.material_folder(mid)/'material.md').read_text('utf-8')
    assert service.organize_topics()==0
    assert store.get(mid)['revision']==after['revision']

def test_stale_or_trashed_material_cannot_be_recategorized(local):
    mid=add(local, 831, 'AI 编程')
    before=store.get(mid)
    good={'topic':'music','revision':before['revision']}
    assert local.post(f'/api/materials/{mid}/topic',json=good).status_code==200
    assert local.post(f'/api/materials/{mid}/topic',json=good).status_code==400
    local.delete(f'/api/materials/{mid}')
    assert local.post(f'/api/materials/{mid}/topic',json={**good,'revision':store.get(mid)['revision']}).status_code==400
    assert store.get(mid)['topic']=='music'

def test_export_preview_names_absolute_local_target_and_creates_no_task(local):
    mid=add(local, 841, '音乐专辑')
    preview=local.post(f'/api/materials/{mid}/push-preview',json={'destination':'todo'}).json()
    assert preview['destination']==str(store.DATA/'outbox/todo'/preview['id'])
    assert '没有连接外部服务' in preview['notice']
    assert preview['payload']['topic']=='music'
    assert not (store.DATA/'outbox').exists()
    assert store.get(mid)['processing']=='pending'
    with store.db() as c:
        assert not c.execute("SELECT 1 FROM jobs WHERE kind='todo'").fetchone()
