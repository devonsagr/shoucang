import httpx
from app import assets,service,store
from test_automatic_collection import local

PNG=b'\x89PNG\r\n\x1a\n'+b'synthetic-raster'

def test_image_response_uses_content_type_and_inline_even_with_an_unknown_extension(local):
    client,_=local
    mid=service.add({'url':'https://example.org/image-fixture','text':'合成原文'},enqueue_collect=False)['id']
    file=store.material_folder(mid)/'images'/'synthetic.bin';file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(PNG)
    assert client.get(f'/api/materials/{mid}/images/images/synthetic.bin').status_code==404
    service.save_content(mid,{'title':'合成材料','body':'![图](images/synthetic.bin)','collection':'ready','content':{'media':[{'status':'saved','path':'images/synthetic.bin','source_url':'https://example.org/synthetic.png'}]}})
    response=client.get(f'/api/materials/{mid}/images/images/synthetic.bin')
    assert response.status_code==200 and response.headers['content-type']=='image/png'
    assert response.headers['content-disposition'].startswith('inline') and response.content==PNG

def test_many_images_reuse_one_connection_pool_without_sending_response_cookies(local,monkeypatch):
    requests=[];clients=[];real_client=httpx.Client
    def send(request):
        requests.append(request)
        if request.url.path=='/redirect.png':return httpx.Response(302,headers={'location':'https://other.example.org/first.png','set-cookie':'private=image-token; Path=/'})
        return httpx.Response(200,content=PNG,headers={'set-cookie':'private=image-token; Path=/'})
    def pooled(**kwargs):
        client=real_client(transport=httpx.MockTransport(send),**kwargs);clients.append(client);return client
    monkeypatch.setattr(assets.httpx,'Client',pooled);monkeypatch.setattr(assets.adapters,'public_url',lambda url:url)
    mid=service.add({'url':'https://example.org/pool-fixture','text':'合成原文'},enqueue_collect=False)['id']
    result={'body':'![图一](https://images.example.org/redirect.png)\n\n![图二](https://other.example.org/second.png)','content':{},'collection':'ready'}
    assets.localize(result,store.material_folder(mid)/'capture',mid,'https://example.org/pool-fixture')
    assert len(clients)==1 and len(requests)==3 and clients[0].is_closed
    assert all(not request.headers.get('cookie') for request in requests)
    assert len(result['content']['media'])==2 and all(a['status']=='saved' for a in result['content']['media'])
    assert assets.IMAGE_CLIENT.get() is None
