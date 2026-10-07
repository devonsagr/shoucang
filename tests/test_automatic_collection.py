import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import pytest
from fastapi.testclient import TestClient
from app import adapters, main, platform_browser, service, sessions, store, video_pipeline, xbookmarks, xofficial

@pytest.fixture
def local(tmp_path,monkeypatch):
    config={}
    monkeypatch.setattr(store,'ROOT',tmp_path)
    monkeypatch.setattr(store,'DATA',tmp_path/'data')
    monkeypatch.setattr(store,'settings',lambda:config.copy())
    monkeypatch.setattr(store,'save_settings',lambda value:(config.clear(),config.update(value)))
    monkeypatch.setattr(service,'worker',lambda:None)
    monkeypatch.setattr(service,'favorites_worker',lambda:None)
    monkeypatch.setattr(adapters,'public_url',lambda u:None)
    monkeypatch.setattr(sessions,'LOGIN',{})
    with TestClient(main.app,headers={'X-Local-Request':'1'}) as client: yield client,config

def test_douyin_modal_alias_preserves_notes_and_history(local):
    client,_=local
    url='https://www.douyin.com/user/self?modal_id=9000000000000001598&showTab=favorite_collection'
    result=client.post('/api/materials',json={'url':url,'text':'用户原文'}).json()
    mid=result['id']; item=store.get(mid)
    client.put('/api/materials/'+mid+'/notes',json={'notes':'用户自己的理解','revision':item['revision']})
    # Model a historical entry from before modal_id normalization was supported.
    with store.db() as c:c.execute('UPDATE materials SET canonical=? WHERE id=?',(url,mid))
    again=client.post('/api/materials',json={'url':'https://www.douyin.com/video/9000000000000001598'}).json()
    assert again=={'id':mid,'duplicate':True}
    assert store.get(mid)['notes']=='用户自己的理解' and store.get(mid)['url']==url
    assert adapters.canonical('https://www.iesdouyin.com/share/video/9000000000000001598/')==adapters.canonical(url)

def test_video_is_automatic_even_legacy_transcribe_false(local,monkeypatch,tmp_path):
    monkeypatch.setattr(adapters,'bili_api',lambda path,params: {
        '/x/web-interface/view':{'title':'真实字段夹具','bvid':'BVabc123','aid':1,'cid':2,'duration':15,'pages':[{'cid':2,'duration':15}]},
        '/x/v2/reply':{}, '/x/player/v2':{'subtitle':{'subtitles':[]}},
        '/x/player/playurl':{'dash':{'audio':[{'baseUrl':'https://cdn.example.org:448/audio','backupUrl':['https://cdn.example.org/audio'],'bandwidth':1}]}}
    }[path])
    got=[]
    def audio(url,duration,content,folder,headers):
        got.append((url,duration));content.update(segments=[{'start':1,'end':3,'text':'音频转写夹具'}],subtitle_source='本机机器转写（非平台字幕）')
    monkeypatch.setattr(video_pipeline,'direct_audio',audio)
    result=adapters.collect('https://www.bilibili.com/video/BVabc123',tmp_path,False)
    assert result['collection']=='ready' and got==[('https://cdn.example.org/audio',15)]
    assert result['content']['segments'][0]['end']==3

def test_platform_subtitles_precede_audio(local,monkeypatch,tmp_path):
    def api(path,params):
        if path.endswith('/view'):return {'title':'字幕夹具','bvid':'BVabc123','aid':1,'cid':2,'pages':[{'cid':2}]}
        if path.endswith('/v2'):return {'subtitle':{'subtitles':[{'lan':'zh','subtitle_url':'https://cdn.example.org/sub.json'}]}}
        return {}
    monkeypatch.setattr(adapters,'bili_api',api)
    monkeypatch.setattr(adapters,'fetch',lambda *a:(json.dumps({'body':[{'from':1,'to':2,'content':'平台字幕夹具'}]}),'https://cdn.example.org/sub.json'))
    monkeypatch.setattr(video_pipeline,'direct_audio',lambda *a:pytest.fail('平台字幕可用时不应下载音频'))
    result=adapters.collect('https://www.bilibili.com/video/BVabc123',tmp_path)
    assert result['collection']=='ready' and result['content']['subtitle_source']=='B站平台字幕'

def test_douyin_share_fallback_uses_returned_media_without_rewrites(local,monkeypatch,tmp_path):
    monkeypatch.setattr(adapters,'video',lambda *a:(_ for _ in ()).throw(ValueError('提取器暂不支持')))
    value={'loaderData':{'layout':None,'video':{'videoInfoRes':{'item_list':[{'aweme_id':'12345','desc':'抖音原说明',
        'video':{'duration':18000,'play_addr':{'url_list':['https://cdn.example.org/playwm?video_id=real']}}}]}}}}
    monkeypatch.setattr(adapters,'fetch',lambda *a:('<script>window._ROUTER_DATA = '+json.dumps(value)+'</script>',a[0]))
    got=[]
    def audio(url,duration,content,folder,headers):
        got.append(url);content.update(segments=[{'start':0,'end':18,'text':'测试夹具机器转写'}],subtitle_source='本机机器转写（非平台字幕）')
    monkeypatch.setattr(video_pipeline,'direct_audio',audio)
    result=video_pipeline.douyin('https://www.douyin.com/video/12345',tmp_path)
    assert result['collection']=='ready' and got==['https://cdn.example.org/playwm?video_id=real']
    assert result['content']['segments'][0]['end']==18

def test_temporary_media_deleted_on_transcription_failure(local,monkeypatch,tmp_path):
    monkeypatch.setattr(video_pipeline,'download',lambda url,path,headers:path.write_bytes(b'audio fixture'))
    monkeypatch.setattr(video_pipeline,'transcribe',lambda *a:(_ for _ in ()).throw(ValueError('转写失败')))
    with pytest.raises(ValueError,match='转写失败'):video_pipeline.direct_audio('https://cdn.example.org/audio',10,{},tmp_path)
    assert not (tmp_path/'temporary-media.bin').exists()

def test_windows_session_encrypted_and_platform_scoped(local):
    if __import__('os').name!='nt':pytest.skip('DPAPI Windows only')
    sessions.save('douyin',{'cookies':[{'domain':'.douyin.com','name':'sessionid','value':'private-session'},
                                     {'domain':'.other.org','name':'unrelated','value':'do-not-keep'}],
                           'origins':[{'origin':'https://www.douyin.com','localStorage':[]},
                                      {'origin':'https://other.org','localStorage':[]}]})
    state=sessions.load('douyin')
    assert len(state['cookies'])==1 and len(state['origins'])==1
    assert b'private-session' not in sessions.path('douyin').read_bytes()
    assert 'private-session' not in local[0].get('/api/accounts').text

def test_optional_x_official_mode_is_explicit(local,monkeypatch):
    client,config=local
    config['x_read_mode']='oauth'
    config['x_client_id']='public-client-id'
    parsed=parse_qs(urlparse(xofficial.authorize()).query)
    assert parsed['code_challenge_method']==['S256']
    assert set(parsed['scope'][0].split())=={'tweet.read','users.read','bookmark.read','offline.access'}
    assert 'tweet.write' not in parsed['scope'][0]
    with pytest.raises(ValueError,match='状态失效'):xofficial.callback('authorization-code','wrong-state')
    monkeypatch.setattr(sessions,'load',lambda k:{'cookies':[{'name':'auth_token','value':'legacy'}]})
    sessions.path('x').parent.mkdir(parents=True,exist_ok=True);sessions.path('x').write_bytes(b'fixture')
    response=client.post('/api/favorites',json={'platform':'x'})
    assert response.status_code==400 and '官方 OAuth' in response.text

def test_x_official_photos_only_no_video_preview():
    value={'data':[{'id':'123','text':'帖文原文','attachments':{'media_keys':['photo','video']}}],
        'includes':{'media':[{'media_key':'photo','type':'photo','url':'https://pbs.twimg.com/photo.jpg'},
                             {'media_key':'video','type':'video','url':'https://pbs.twimg.com/video.jpg'}]}}
    record=next(xofficial.records(value))
    assert 'photo.jpg' in record['body'] and 'video.jpg' not in record['body'] and record['collection']=='ready'
    tweet=SimpleNamespace(full_text='帖文',text='帖文',urls=[],media=[{'type':'video','media_url_https':'https://cdn.example.org/video.jpg'},
        {'type':'photo','media_url_https':'https://cdn.example.org/photo.jpg'}])
    body,video=xbookmarks.photo_markdown(tweet)
    assert video and 'photo.jpg' in body and 'video.jpg' not in body

def test_favorites_page_failure_keeps_registered_references(local,monkeypatch):
    def pages(kind,url,record,progress,cancelled):
        record({'url':'https://www.douyin.com/video/12345','title':'已收到的收藏'})
        progress.update(complete=False,pages=1)
        yield progress
        raise ValueError('平台限流，停止')
    monkeypatch.setattr(platform_browser,'favorites',pages)
    with store.db() as c: jid=store.enqueue(c,'favorites',{'platform':'douyin','url':'https://www.douyin.com/user/self?showTab=favorite_collection'})
    job={'id':jid,'kind':'favorites','material_id':None,'payload':json.dumps({'platform':'douyin','url':'https://www.douyin.com/user/self?showTab=favorite_collection'}),'progress':'{}'}
    with pytest.raises(ValueError,match='平台限流'):service.run_job(job)
    with store.db() as c:
        row=c.execute('SELECT progress FROM jobs WHERE id=?',(jid,)).fetchone()
        material=c.execute('SELECT * FROM materials').fetchone()
        assert json.loads(row['progress'])['new']==1 and not json.loads(row['progress'])['complete']
        assert material['origin']=='favorite'
        assert c.execute("SELECT 1 FROM jobs WHERE material_id=? AND kind='collect'",(material['id'],)).fetchone()

def test_bili_all_folders_checkpoint_not_lost(local,monkeypatch):
    calls=[]
    def api(path,params):
        if path.endswith('/nav'):return {'mid':77,'isLogin':True}
        if path.endswith('list-all'):return {'list':[{'id':1,'title':'夹一'},{'id':2,'title':'夹二'}]}
        calls.append((params['media_id'],params['pn']))
        if params['media_id']==2:raise ValueError('第二个收藏夹权限拒绝')
        return {'medias':[{'bvid':'BVone'}],'has_more':False}
    monkeypatch.setattr(adapters,'bili_api',api)
    monkeypatch.setattr(platform_browser.time,'sleep',lambda _:None)
    stored=[];progress={}
    iterator=platform_browser.bili_favorites(stored.append,progress,lambda:False)
    next(iterator)
    assert progress['checkpoint']=={'folder':1,'page':1} and len(stored)==1
    with pytest.raises(ValueError,match='权限拒绝'):next(iterator)
    assert not progress['complete'] and calls==[(1,1),(2,1)]

def test_favorites_resume_scrolls_past_saved_cards_and_ignores_likes_end(local,monkeypatch):
    """Simulate a long saved list, then one new page and an inaccessible reference."""
    from contextlib import contextmanager
    import playwright.sync_api
    class Response:
        status=200
        def __init__(self,path,data):self.url='https://www.douyin.com'+path;self.data=data
        def json(self):return self.data
    class Listing:
        first=None
        def __init__(self,page):self.page=page;self.first=self
        def count(self):return 1
        def locator(self,_):return self
        def evaluate_all(self,_):
            return [{'url':'https://www.douyin.com/video/'+('101' if self.page.step>=7 else '100'),'title':'收藏夹具'}]
        def evaluate(self,_):return self.page.step<7
        def inner_text(self,**_):return '收藏 视频'
    class Tab:
        def count(self):return 1
        def click(self,**_):pass
        def evaluate(self,_):return True
    class Page:
        step=0
        def on(self,_,callback):self.response=callback
        def goto(self,*a,**k):
            self.response(Response('/aweme/v1/web/aweme/favorite/',{'has_more':0,'aweme_list':[]}))
        def wait_for_timeout(self,ms):
            if ms!=5000:return
            self.step+=1
            if self.step==8:
                self.response(Response('/aweme/v1/web/aweme/listcollection/',{'has_more':0,'aweme_list':[],
                    'disabled_item_ids':['999'],'invalid_item_id_list':['999']}))
        def get_by_text(self,*a,**k):return Tab()
        def locator(self,_):return Listing(self)
        def evaluate(self,_):pass
    page=Page()
    class Context:
        def route(self,*a):pass
        def new_page(self):return page
    class Browser:
        closed=False
        def new_context(self,**_):return Context()
        def close(self):self.closed=True
    browser=Browser()
    @contextmanager
    def runtime():yield None
    monkeypatch.setattr(playwright.sync_api,'sync_playwright',runtime)
    monkeypatch.setattr(sessions,'browser',lambda _:browser)
    monkeypatch.setattr(sessions,'load',lambda _:{})
    sessions.path('douyin').parent.mkdir(parents=True,exist_ok=True)
    sessions.path('douyin').write_bytes(b'fixture')
    progress={'seen_urls':['https://www.douyin.com/video/100']};entries=[]
    pages=list(platform_browser.favorites('douyin','https://www.douyin.com/user/self',entries.append,progress))
    assert progress['complete'] and progress['pages']==10 and browser.closed
    assert {entry['url'].rsplit('/',1)[-1] for entry in entries}=={'101','999'}
    assert next(e for e in entries if e.get('unavailable'))['url'].endswith('/999')
    assert progress['unavailable']==1 and progress['unavailable_ids']==['999']

def test_unavailable_favorite_remains_failed_without_media_job(local,monkeypatch):
    def pages(kind,url,record,progress,cancelled):
        record({'url':'https://www.douyin.com/video/999','title':'失效收藏','unavailable':True})
        progress.update(complete=True,unavailable=1);yield progress
    monkeypatch.setattr(platform_browser,'favorites',pages)
    with store.db() as c:jid=store.enqueue(c,'favorites',{'platform':'douyin','url':'https://www.douyin.com/user/self'})
    service.run_job({'id':jid,'kind':'favorites','material_id':None,'payload':json.dumps({'platform':'douyin','url':'https://www.douyin.com/user/self'}),'progress':'{}'})
    with store.db() as c:
        item=c.execute('SELECT * FROM materials').fetchone()
        assert item['collection']=='failed' and item['origin']=='favorite' and item['body']==''
        assert not c.execute("SELECT 1 FROM jobs WHERE material_id=? AND kind='collect'",(item['id'],)).fetchone()
        assert c.execute("SELECT 1 FROM events WHERE material_id=? AND kind='source_unavailable'",(item['id'],)).fetchone()
