import json
import pytest
from fastapi.testclient import TestClient
from app import adapters, main, playback, service, store, video_pipeline

@pytest.fixture
def local(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'ROOT',tmp_path)
    monkeypatch.setattr(store,'DATA',tmp_path/'data')
    monkeypatch.setattr(store,'settings',lambda:{})
    monkeypatch.setattr(service,'worker',lambda:None)
    monkeypatch.setattr(service,'favorites_worker',lambda:None)
    monkeypatch.setattr(playback,'CACHE',{})
    monkeypatch.setattr(playback,'STREAMS',{})
    with TestClient(main.app,headers={'X-Local-Request':'1'}) as client:
        yield client

def item(client):
    return client.post('/api/materials',json={'url':'https://www.douyin.com/video/9000000000000001533',
        'text':'测试原文','title':'播放测试夹具'}).json()['id']

@pytest.mark.parametrize('url',['http://v3.douyinvod.com/a','https://douyinvod.com.evil.test/a',
    'https://127.0.0.1/a','https://user:secret@v3.douyinvod.com/a','https://v3.douyinvod.com:444/a'])
def test_media_address_rejects_unrelated_private_and_credentialled_urls(url,monkeypatch):
    monkeypatch.setattr(adapters,'public_url',lambda _:None)
    with pytest.raises(ValueError):playback.safe_media_url(url)

def test_native_address_is_ephemeral_cached_and_leaves_material_unchanged(local,monkeypatch):
    mid=item(local);before=store.get(mid);calls=[]
    def metadata(url):
        calls.append(url)
        return {'aweme_id':'9000000000000001533','video':{'duration':90000,'width':1920,'height':1080,
            'play_addr':{'url_list':['https://v3.douyinvod.com/media.mp4?sign=fixture']}}},'平台测试信息'
    monkeypatch.setattr(video_pipeline,'douyin_metadata',metadata)
    monkeypatch.setattr(playback,'resolve_address',lambda u:u)
    response=local.post(f'/api/materials/{mid}/playback')
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    assert response.json()['mode']=='stream' and response.json()['duration']==90
    assert response.json()['url'].startswith(f'/api/materials/{mid}/playback-stream/')
    assert 'sign=fixture' not in json.dumps(response.json())
    assert local.post(f'/api/materials/{mid}/playback').json()==response.json() and len(calls)==1
    assert store.get(mid)==before
    assert 'sign=fixture' not in store.markdown(store.get(mid))
    assert not list(store.material_folder(mid).glob('*.mp4'))

def test_failure_is_explicit_fallback_and_redacts_signed_addresses(local,monkeypatch):
    mid=item(local)
    def fail(_):raise ValueError('平台拒绝 https://v3.douyinvod.com/a?sign=secret')
    monkeypatch.setattr(video_pipeline,'douyin_metadata',fail)
    response=local.post(f'/api/materials/{mid}/playback').json()
    assert response['mode']=='embed' and '未取得' in response['notice']
    assert 'secret' not in json.dumps(response) and 'url' not in response
    assert store.get(mid)['collection']=='ready'

def test_wrong_video_or_trashed_material_never_returns_media(local,monkeypatch):
    mid=item(local)
    monkeypatch.setattr(video_pipeline,'douyin_metadata',lambda _:({'aweme_id':'different','video':{'duration':20000}},'平台'))
    assert local.post(f'/api/materials/{mid}/playback').json()['mode']=='embed'
    local.delete(f'/api/materials/{mid}')
    assert local.post(f'/api/materials/{mid}/playback').status_code==400

def test_redirect_header_probe_does_not_consume_media(monkeypatch):
    calls=[]
    monkeypatch.setattr(adapters,'public_url',lambda _:None)
    class Response:
        status_code=206;headers={'content-type':'video/mp4'};is_redirect=False
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):raise AssertionError('must not read media body')
        def iter_bytes(self):raise AssertionError('must not read media body')
    class Client:
        def __init__(self,**kwargs):assert kwargs['follow_redirects'] is False
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def stream(self,method,url,headers):calls.append(headers);return Response()
    monkeypatch.setattr(playback.httpx,'Client',Client)
    url='https://v3.douyinvod.com/fixture.mp4'
    assert playback.resolve_address(url)==url and calls[0]['Range']=='bytes=0-0'

def test_share_metadata_must_match_requested_video(monkeypatch):
    value={'loaderData':{'a':{'videoInfoRes':{'item_list':[{'aweme_id':'another','video':{}}]}}}}
    raw='<script>window._ROUTER_DATA = '+json.dumps(value)+'</script>'
    monkeypatch.setattr(adapters,'fetch',lambda *args:(raw,'https://www.iesdouyin.com/'))
    with pytest.raises(ValueError,match='编号'):video_pipeline.douyin_metadata('https://www.douyin.com/video/9000000000000001533')

@pytest.mark.parametrize('header,expected',[('', 'bytes=0-8388607'),('bytes=1048576-', 'bytes=1048576-9437183'),
    ('bytes=100-200','bytes=100-200'),('bytes=-512','bytes=-512')])
def test_relay_bounds_ranges_without_claiming_a_complete_video(header,expected):
    assert playback.bounded_range(header)==expected

@pytest.mark.parametrize('header',['bytes=500-100','bytes=0-1,5-6','bytes=-0','bytes=-','nonsense'])
def test_relay_rejects_invalid_or_multi_ranges(header):
    with pytest.raises(Exception) as error:playback.bounded_range(header)
    assert error.value.status_code==416

def test_stream_is_same_origin_and_bound_to_the_material(local,monkeypatch):
    mid=item(local);token='a'*32
    playback.STREAMS[token]={'material_id':mid,'url':'https://v3.douyinvod.com/a','expires':playback.time.monotonic()+100}
    assert local.get(f'/api/materials/{mid}/playback-stream/{token}',headers={'Origin':'https://evil.test'}).status_code==403
    with TestClient(main.app) as anonymous:
        assert anonymous.get(f'/api/materials/{mid}/playback-stream/{token}').status_code==403
    called=[]
    monkeypatch.setattr(playback,'stream',lambda item,t,r:called.append((item['id'],t,r)) or {'ok':True})
    assert local.get(f'/api/materials/{mid}/playback-stream/{token}',headers={'Range':'bytes=50-100'}).status_code==200
    assert called==[(mid,token,'bytes=50-100')]

def test_stream_forwards_exact_range_then_closes_without_writing(local,monkeypatch):
    mid=item(local);token='b'*32;address='https://v3.douyinvod.com/fixture.mp4'
    playback.STREAMS[token]={'material_id':mid,'url':address,'expires':playback.time.monotonic()+100}
    monkeypatch.setattr(adapters,'public_url',lambda _:None)
    seen=[];closed=[]
    class Response:
        status_code=206;is_redirect=False
        headers={'content-type':'video/mp4','content-range':'bytes 10-13/100'}
        def iter_raw(self,size):yield b'ab';yield b'cd'
        def close(self):closed.append('response')
    class Client:
        def __init__(self,**kwargs):pass
        def build_request(self,method,url,headers):seen.append((url,headers));return 'request'
        def send(self,request,stream):assert stream;return Response()
        def close(self):closed.append('client')
    monkeypatch.setattr(playback.httpx,'Client',Client)
    response=local.get(f'/api/materials/{mid}/playback-stream/{token}',headers={'Range':'bytes=10-13'})
    assert response.status_code==206 and response.content==b'abcd'
    assert response.headers['content-range']=='bytes 10-13/100' and response.headers['accept-ranges']=='bytes'
    assert seen[0][1]['Range']=='bytes=10-13' and 'response' in closed and 'client' in closed
    assert not list(store.material_folder(mid).glob('*.mp4'))
    assert local.get(f'/api/materials/{mid}/playback-stream/invalid').status_code==404

def test_upstream_refusal_stops_relay_without_consuming_body(local,monkeypatch):
    mid=item(local);token='c'*32
    playback.STREAMS[token]={'material_id':mid,'url':'https://v3.douyinvod.com/fixture.mp4','expires':playback.time.monotonic()+100}
    monkeypatch.setattr(adapters,'public_url',lambda _:None)
    class Response:
        status_code=403;is_redirect=False
        def iter_raw(self,*args):raise AssertionError('must stop on refusal')
        def close(self):pass
    class Client:
        def __init__(self,**kwargs):pass
        def build_request(self,*args,**kwargs):return None
        def send(self,*args,**kwargs):return Response()
        def close(self):pass
    monkeypatch.setattr(playback.httpx,'Client',Client)
    assert local.get(f'/api/materials/{mid}/playback-stream/{token}').status_code==502
    assert token not in playback.STREAMS
    assert local.post(f'/api/materials/{mid}/playback',json={'refresh':True}).json()['mode']=='embed'

def test_reading_session_survives_short_metadata_cache_timeout(local,monkeypatch):
    mid=item(local);calls=[];clock=[1000]
    monkeypatch.setattr(playback.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(video_pipeline,'douyin_metadata',lambda url:calls.append(url) or
        ({'aweme_id':'9000000000000001533','video':{'duration':90000,
          'play_addr':{'url_list':['https://v3.douyinvod.com/fixture.mp4']}}},'平台'))
    monkeypatch.setattr(playback,'resolve_address',lambda u:u)
    first=local.post(f'/api/materials/{mid}/playback').json()
    clock[0]+=600  # Previously re-read metadata after 240 seconds and lost a valid player.
    assert local.post(f'/api/materials/{mid}/playback').json()==first and len(calls)==1
    refreshed=local.post(f'/api/materials/{mid}/playback',json={'refresh':True}).json()
    assert refreshed['mode']=='stream' and refreshed['url']!=first['url'] and len(calls)==2
    assert first['url'].rsplit('/',1)[-1] not in playback.STREAMS

def test_evicted_or_expired_ticket_is_not_returned_from_cache(local,monkeypatch):
    mid=item(local);calls=[]
    monkeypatch.setattr(video_pipeline,'douyin_metadata',lambda url:calls.append(url) or
        ({'aweme_id':'9000000000000001533','video':{'duration':90000,
          'play_addr':{'url_list':['https://v3.douyinvod.com/fixture.mp4']}}},'平台'))
    monkeypatch.setattr(playback,'resolve_address',lambda u:u)
    first=local.post(f'/api/materials/{mid}/playback').json()
    playback.STREAMS.clear()
    second=local.post(f'/api/materials/{mid}/playback').json()
    assert second['url']!=first['url'] and len(calls)==2
    playback.STREAMS[second['url'].rsplit('/',1)[-1]]['expires']=0
    third=local.post(f'/api/materials/{mid}/playback').json()
    assert third['url']!=second['url'] and len(calls)==3

@pytest.mark.parametrize('content_range,declared_length',[('bytes 0-3/100','4'),('bytes 10-13/100','2')])
def test_wrong_range_or_length_never_becomes_a_playable_response(local,monkeypatch,content_range,declared_length):
    mid=item(local);token='d'*32
    playback.STREAMS[token]={'material_id':mid,'url':'https://v3.douyinvod.com/fixture.mp4','expires':playback.time.monotonic()+100}
    monkeypatch.setattr(adapters,'public_url',lambda _:None)
    class Response:
        status_code=206;is_redirect=False
        headers={'content-type':'video/mp4','content-range':content_range,'content-length':declared_length}
        def iter_raw(self,*args):raise AssertionError('must reject incorrect range before playback')
        def close(self):pass
    class Client:
        def __init__(self,**kwargs):pass
        def build_request(self,*args,**kwargs):return None
        def send(self,*args,**kwargs):return Response()
        def close(self):pass
    monkeypatch.setattr(playback.httpx,'Client',Client)
    response=local.get(f'/api/materials/{mid}/playback-stream/{token}',headers={'Range':'bytes=10-13'})
    assert response.status_code==502 and '不一致' in response.json()['detail']
