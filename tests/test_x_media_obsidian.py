import asyncio
import base64
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from twikit.tweet import Tweet
from twikit.utils import Result
from app import adapters, assets, main, obsidian, service, store, xbookmarks

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')

@pytest.fixture
def context(tmp_path, monkeypatch):
    # Explicitly exercise the opt-in legacy compatibility adapter; production defaults to official OAuth.
    config = {'x_legacy_read_enabled':True}
    monkeypatch.setattr(store, 'ROOT', tmp_path)
    monkeypatch.setattr(store, 'DATA', tmp_path/'data')
    monkeypatch.setattr(store, 'settings', lambda:config.copy())
    monkeypatch.setattr(store, 'save_settings', lambda value: (config.clear(), config.update(value)))
    monkeypatch.setattr(service, 'worker', lambda:None)
    monkeypatch.setattr(service, 'favorites_worker', lambda:None)
    with TestClient(main.app, headers={'X-Local-Request':'1'}) as client:
        yield client, config

def item_with_image(client, monkeypatch):
    mid = client.post('/api/materials',json={'url':'https://example.org/rich','text':'原文','origin':'favorite'}).json()['id']
    folder = store.material_folder(mid)/'capture-fixture'
    monkeypatch.setattr(assets, 'download', lambda url:(PNG,'png'))
    result = {'title':'图片验收材料','body':'前段\n\n![图解](https://example.org/photo.png)\n\n后段',
              'collection':'ready','content':{'source':'测试原文','comments_status':'部分评论，非全部',
              'comments':[{'author':'测试作者','body':'这是一条回复','url':'https://example.org/comment'}]}}
    service.save_content(mid,assets.localize(result,folder,mid,'https://example.org/rich'))
    return store.get(mid)

def test_web_image_position_and_relative_resolution(context, monkeypatch):
    client, _ = context
    raw = '<html><head><title>图文</title></head><body><article><p>'+'第一段正文。'*35+'</p><img src="/diagram.png" alt="图解"><p>'+'第二段正文。'*35+'</p></article></body></html>'
    monkeypatch.setattr(adapters,'fetch',lambda *args:(raw,'https://example.org/article'))
    folder = store.material_folder('web-fixture','web')/'capture-test'
    folder.mkdir(parents=True)
    result = adapters.collect('https://example.org/article',folder)
    requested = []
    monkeypatch.setattr(assets,'download',lambda url:(requested.append(url) or PNG,'png'))
    result = assets.localize(result,folder,'web-fixture','https://example.org/article')
    assert requested == ['https://example.org/diagram.png']
    assert result['body'].index('第一段') < result['body'].index('![') < result['body'].index('第二段')
    assert result['content']['media'][0]['status']=='saved'

def test_local_images_comments_and_portable_bundle(context, monkeypatch):
    client, _ = context
    item = item_with_image(client,monkeypatch)
    image = item['content']['media'][0]
    response = client.get(f'/api/materials/{item["id"]}/images/{image["path"]}')
    assert response.status_code==200 and response.content==PNG
    listed = client.get('/api/materials?state=all').json()['items'][0]
    assert listed['thumbnail'] == image['path']
    assert client.get(f'/api/materials/{item["id"]}/images/../../../config.json').status_code in (400,404)
    preview = service.preview(item['id'],'knowledge')
    assert '部分评论，非全部' in preview['markdown'] and '这是一条回复' in preview['markdown']
    assert '](assets/' in preview['markdown'] and not (store.DATA/'outbox').exists()
    confirmed = service.confirm(preview['id'],preview['hash'])
    from pathlib import Path
    folder=Path(confirmed['path'])
    assert len(list((folder/'assets').glob('*.png')))==1
    assert (folder/'material.md').read_text('utf-8')==preview['markdown']

def test_list_thumbnail_uses_archived_image_only(context, monkeypatch):
    client, _ = context
    item = item_with_image(client, monkeypatch)
    archived = item['content']['media'][0]
    item['content']['media'].insert(0, {'status':'failed','source_url':'https://example.org/unavailable.png'})
    service.save_content(item['id'], {'title':item['title'],'body':item['body'],
                                      'content':item['content'],'collection':'partial'})
    listed = client.get('/api/materials?state=all').json()['items'][0]
    assert listed['thumbnail'] == archived['path']
    assert client.get(f'/api/materials/{item["id"]}/images/{listed["thumbnail"]}').content == PNG
    empty = client.post('/api/materials',json={'url':'https://example.org/plain','text':'只有文字'}).json()
    listed = {r['id']:r for r in client.get('/api/materials?state=all').json()['items']}
    assert listed[empty['id']]['thumbnail'] is None

def test_manual_markdown_images_are_queued_and_preserved(context, monkeypatch):
    client,_=context
    monkeypatch.setattr(assets,'download',lambda url:(PNG,'png'))
    mid=client.post('/api/materials',json={'url':'https://example.org/manual','text':'前段\n![用户配图](https://example.org/image.png)\n后段'}).json()['id']
    assert store.get(mid)['collection']=='queued'
    with store.db() as c:job=dict(c.execute("SELECT * FROM jobs WHERE material_id=? AND kind='images'",(mid,)).fetchone())
    service.run_job(job)
    item=store.get(mid)
    assert item['collection']=='ready' and len(item['content']['media'])==1
    assert item['body'].index('前段')<item['body'].index('![')<item['body'].index('后段')

def test_missing_or_html_image_is_partial(context, monkeypatch):
    client, _ = context
    item=item_with_image(client,monkeypatch)
    with pytest.raises(ValueError):assets.raster_type(b'<svg onload="alert(1)"></svg>')
    monkeypatch.setattr(assets,'download',lambda url: (_ for _ in ()).throw(ValueError('fixture failure')))
    result={'title':'未取得图片','body':'段落 ![原图](https://example.org/missing.png)','collection':'ready','content':{}}
    result=assets.localize(result,store.material_folder(item['id'])/'failed',item['id'],item['url'])
    assert result['collection']=='partial' and '图片未存档' in result['body']
    assert result['content']['media'][0]['source_url'].endswith('/missing.png')

def test_obsidian_requires_preview_confirmation_and_preserves_existing(context, monkeypatch):
    client, config=context
    vault=store.ROOT/'test-vault'; vault.mkdir()
    existing=vault/'我的笔记.md'; existing.write_text('用户已有笔记','utf-8')
    config['obsidian_vault']=str(vault)
    item=item_with_image(client,monkeypatch)
    preview=service.preview(item['id'],'obsidian')
    from pathlib import Path
    note=Path(preview['destination'])
    assert not note.exists() and '收藏处理器' in str(note)
    response=client.post(f'/api/pushes/{preview["id"]}/confirm',json={'hash':preview['hash']})
    assert response.status_code==200,response.text
    assert note.read_text('utf-8')==preview['markdown']
    assert existing.read_text('utf-8')=='用户已有笔记'
    assert len(list(note.parent.glob('assets/*.png')))==1
    assert client.post(f'/api/pushes/{preview["id"]}/confirm',json={'hash':preview['hash']}).json()['duplicate']
    assert store.get(item['id'])['processing']=='done'

def test_obsidian_changed_config_and_conflicts_stop(context, monkeypatch):
    client, config=context
    vault=store.ROOT/'test-vault'; vault.mkdir(); config['obsidian_vault']=str(vault)
    item=item_with_image(client,monkeypatch)
    p=service.preview(item['id'],'obsidian')
    from pathlib import Path
    note=Path(p['destination']); note.parent.mkdir(parents=True); note.write_text('云端独有修改','utf-8')
    with pytest.raises(ValueError,match='已有不同内容'): service.confirm(p['id'],p['hash'])
    assert note.read_text('utf-8')=='云端独有修改' and store.get(item['id'])['processing']=='pending'
    other=store.ROOT/'other-vault'; other.mkdir(); config['obsidian_vault']=str(other)
    with pytest.raises(ValueError,match='配置已改变'):service.confirm(p['id'],p['hash'])
    assert not list(other.iterdir())

def test_preview_detects_picture_tampering(context, monkeypatch):
    client, _=context
    item=item_with_image(client,monkeypatch)
    p=service.preview(item['id'],'knowledge')
    path=assets.image_path(item['id'],item['content']['media'][0]['path'])
    path.write_bytes(PNG+b'changed')
    with pytest.raises(ValueError,match='图片已改变'):service.confirm(p['id'],p['hash'])
    assert not (store.DATA/'outbox').exists()

def tweet(tid, text='测试推文', media=None):
    data={'rest_id':str(tid),'legacy':{'full_text':text,'created_at':'2026-09-30',
          'entities':{'urls':[], 'media':media or []}}, 'note_tweet':{'note_tweet_results':{'result':{'text':text,'entity_set':{'urls':[]}}}}}
    return Tweet(None,data,SimpleNamespace(screen_name='fixture',name='测试',id='account1'))

def test_twikit_real_media_objects_full_text_and_bounded_replies(context,monkeypatch):
    root=tweet(100,'长文前段 https://t.co/photo 后段',[{'id_str':'1','type':'photo','media_url_https':'https://pbs.twimg.com/fixture.png','url':'https://t.co/photo','ext_alt_text':'原图说明'}])
    first=tweet(101,'第一条回复');first.replies=Result([tweet(102,'嵌套回复')])
    root.replies=Result([first,tweet(103,'超过本次上限')])
    async def detail(*args):return root
    async def close():pass
    session=SimpleNamespace(get_tweet_by_id=detail,http=SimpleNamespace(aclose=close))
    monkeypatch.setattr(xbookmarks,'client',lambda:session)
    result=asyncio.run(xbookmarks.detail('https://x.com/i/status/100',comment_limit=2))
    assert result['collection']=='ready'
    assert result['body']=='长文前段 ![原图说明](https://pbs.twimg.com/fixture.png) 后段'
    assert [c['id'] for c in result['content']['comments']]==['101','102']
    assert '不是全部评论' in result['content']['comments_status']

def test_x_detail_failure_keeps_original_bookmark(context,monkeypatch):
    async def detail(*args):raise RuntimeError('must-not-leak-secret')
    async def close():pass
    monkeypatch.setattr(xbookmarks,'client',lambda:SimpleNamespace(get_tweet_by_id=detail,http=SimpleNamespace(aclose=close)))
    seed=xbookmarks.seed_record(tweet(100,'列表里的原文'))
    result=asyncio.run(xbookmarks.detail(seed['url'],seed))
    assert result['body']=='列表里的原文' and result['collection']=='partial'
    assert 'must-not-leak-secret' not in result['content']['warning']

def test_x_sync_partial_pagination_and_resume_no_note_loss(context,monkeypatch):
    client, config=context
    async def pages(cursor=None,folder_id=None):
        if cursor is None:
            yield {'id':'account1','username':'fixture','name':'测试'},[xbookmarks.seed_record(tweet(100))],'cursor2'
            raise ValueError('测试分页失败')
        yield {'id':'account1','username':'fixture','name':'测试'},[xbookmarks.seed_record(tweet(100)),xbookmarks.seed_record(tweet(200))],None
    monkeypatch.setattr(xbookmarks,'bookmark_pages',pages)
    monkeypatch.setattr(xbookmarks,'read_cookies',lambda:{'auth_token':'fixture','ct0':'fixture'})
    jid=client.post('/api/x/sync',json={}).json()['job_id']
    assert client.post('/api/x/sync',json={}).json()['duplicate']
    with store.db() as c:job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
    with pytest.raises(ValueError):service.run_job(job)
    items=client.get('/api/materials?state=all').json()['items'];assert len(items)==1
    mid=items[0]['id'];item=store.get(mid)
    client.put(f'/api/materials/{mid}/notes',json={'notes':'用户已经消化的理解','revision':item['revision']})
    with store.db() as c:c.execute("UPDATE jobs SET state='failed' WHERE id=?",(jid,))
    resume=client.post('/api/x/sync',json={'resume_job_id':jid}).json()['job_id']
    with store.db() as c:job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(resume,)).fetchone())
    service.run_job(job)
    assert len(client.get('/api/materials?state=all').json()['items'])==2
    assert store.get(mid)['notes']=='用户已经消化的理解'
    assert client.get('/api/x/status').json()['last_sync']['progress']['complete']

def test_x_cookies_only_two_keys_and_never_returned(context):
    client,_=context
    cookies=[{'domain':'.x.com','name':'auth_token','value':'private-token'}, {'domain':'.x.com','name':'ct0','value':'private-csrf'}]
    response=client.put('/api/cookies',json={'platform':'x','text':json.dumps(cookies)})
    assert response.status_code==200
    assert xbookmarks.read_cookies()['ct0']=='private-csrf'
    session=xbookmarks.client()
    assert 'private-token' in session.http.build_request('GET','https://x.com/i/bookmarks').headers['cookie']
    assert 'cookie' not in session.http.build_request('GET','https://example.org/asset').headers
    asyncio.run(session.http.aclose())
    video_cookies=adapters.cookie_args('x')
    assert video_cookies[0]=='--cookies'
    from pathlib import Path
    assert 'private-token' in Path(video_cookies[1]).read_text('utf-8')
    assert 'private-token' not in client.get('/api/x/status').text
    assert 'private-csrf' not in client.get('/api/settings').text
    cookies.append({'domain':'.other.org','name':'secret','value':'other'})
    assert client.put('/api/cookies',json={'platform':'x','text':json.dumps(cookies)}).status_code==400
    assert client.put('/api/cookies',json={'platform':'x','text':''}).status_code==200
    with pytest.raises(ValueError):xbookmarks.read_cookies()
    assert not Path(video_cookies[1]).exists()
