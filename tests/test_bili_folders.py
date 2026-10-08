import json
import pytest
from app import adapters,platform_browser,service,sessions,store
from test_automatic_collection import local

def folders_api(monkeypatch):
    calls=[]
    def read(path,params):
        calls.append((path,params))
        if path.endswith('/nav'):return {'isLogin':True,'mid':111}
        if path.endswith('created/list-all'):return {'list':[{'id':1001,'title':'学习','media_count':2},{'id':1002,'title':'音乐','media_count':1}]}
        return {'medias':[{'bvid':'BV1Fixture001','title':'合成视频'}],'has_more':False}
    monkeypatch.setattr(adapters,'bili_api',read);monkeypatch.setattr(platform_browser.time,'sleep',lambda _:None)
    return calls

def test_only_selected_folders_are_read_and_each_source_has_folder_provenance(local,monkeypatch):
    calls=folders_api(monkeypatch);progress={'folder_ids':['1002']};entries=[]
    list(platform_browser.bili_favorites(entries.append,progress,lambda:False))
    assert [v[1]['media_id'] for v in calls if v[0].endswith('resource/list')]==['1002']
    assert entries[0]['favorite_folder']=={'id':'1002','title':'音乐'} and progress['complete']
    assert progress['selected_folders']==[{'id':'1002','title':'音乐'}]

def test_removed_folder_or_different_account_does_not_silently_import_everything(local,monkeypatch):
    folders_api(monkeypatch)
    with pytest.raises(ValueError,match='收藏夹'):list(platform_browser.bili_favorites(lambda e:pytest.fail('不应登记'),{'folder_ids':['999']},lambda:False))
    with pytest.raises(ValueError,match='账号'):list(platform_browser.bili_favorites(lambda e:pytest.fail('不应登记'),{'account_id':'222'},lambda:False))

def test_folder_choices_and_resume_keep_the_original_scope(local,monkeypatch):
    client,_=local;folders_api(monkeypatch)
    assert len(client.get('/api/accounts/bilibili/folders').json()['folders'])==2
    sessions.path('bilibili').parent.mkdir(parents=True,exist_ok=True);sessions.path('bilibili').write_bytes(b'fixture')
    first=client.post('/api/favorites',json={'platform':'bilibili','folder_ids':['1002']}).json()['job_id']
    with store.db() as c:
        assert json.loads(c.execute('select payload from jobs where id=?',(first,)).fetchone()[0])['folder_ids']==['1002']
        c.execute("update jobs set state='failed' where id=?",(first,))
    second=client.post('/api/favorites',json={'platform':'bilibili','folder_ids':['1001'],'resume_job_id':first}).json()['job_id']
    with store.db() as c:assert json.loads(c.execute('select payload from jobs where id=?',(second,)).fetchone()[0])['folder_ids']==['1002']
    assert client.post('/api/favorites',json={'platform':'bilibili','folder_ids':[]}).status_code==400

def test_one_video_in_two_folders_stays_one_material_and_capture_keeps_provenance(local):
    client,_=local;url='https://www.bilibili.com/video/BV1Fixture001'
    first=service.add({'url':url,'origin':'favorite','favorite_folder':{'id':'1001','title':'学习'}},enqueue_collect=False)
    service.add({'url':url,'origin':'favorite','favorite_folder':{'id':'1002','title':'音乐'}},enqueue_collect=False)
    before=store.get(first['id']);revision=before['revision']
    service.add({'url':url,'origin':'favorite','favorite_folder':{'id':'1001','title':'学习'}},enqueue_collect=False)
    assert store.get(first['id'])['revision']==revision
    with store.db() as c:
        service.write_content(c,first['id'],{'title':'真实来源类型的合成夹具','body':'脚本处理后的正文','content':{},'collection':'ready'})
        assert c.execute('select count(*) from materials').fetchone()[0]==1
    item=store.get(first['id']);assert {f['id'] for f in item['content']['favorite_folders']}=={'1001','1002'}
    assert '收藏夹记录：学习、音乐' in store.markdown(item)

def test_switching_the_visible_platform_does_not_cancel_background_capture(local):
    client,_=local;mid=client.post('/api/materials',json={'url':'https://www.xiaoheihe.cn/app/bbs/link/996600','text':'合成原文'}).json()['id']
    result=client.post('/api/materials/'+mid+'/retry',json={'refresh':True}).json()
    client.get('/api/materials?platform=x&state=all');client.get('/api/materials?platform=bilibili&state=all')
    with store.db() as c:assert c.execute('select state from jobs where id=?',(result['job_id'],)).fetchone()[0]=='queued'

@pytest.mark.parametrize('selected',[None,['1001','1002']])
def test_resume_keeps_folder_order_and_does_not_add_new_folders(local,monkeypatch,selected):
    calls=[];listing=[{'id':'1001','title':'学习'},{'id':'1002','title':'音乐'}]
    def api(path,params):
        if path.endswith('/nav'):return {'mid':111,'isLogin':True}
        if path.endswith('list-all'):return {'list':listing}
        calls.append(params['media_id'])
        return {'medias':[{'bvid':'BV1Fixture'+params['media_id']}],'has_more':False}
    monkeypatch.setattr(adapters,'bili_api',api);monkeypatch.setattr(platform_browser.time,'sleep',lambda _:None)
    progress={'folder_ids':selected};entries=[];iterator=platform_browser.bili_favorites(entries.append,progress,lambda:False)
    next(iterator);iterator.close()
    assert progress['checkpoint']=={'folder':1,'page':1} and calls==['1001']
    listing[:]=[{'id':'1002','title':'音乐已改名'},{'id':'1003','title':'新建夹'},{'id':'1001','title':'学习'}]
    list(platform_browser.bili_favorites(entries.append,progress,lambda:False))
    assert calls==['1001','1002'] and progress['complete']
    assert [folder['id'] for folder in progress['selected_folders']]==['1001','1002']
    assert entries[-1]['favorite_folder']=={'id':'1002','title':'音乐已改名'}
