import pytest
from app import sessions
from test_automatic_collection import local

def cookie(domain,name,value):return {'domain':domain,'name':name,'value':value,'path':'/','expires':-1,'httpOnly':True,'secure':True,'sameSite':'Lax','priority':'High'}

def test_authorized_chrome_snapshot_is_platform_scoped_and_encrypted(local):
    client,_=local
    state={'cookies':[cookie('.xiaoheihe.cn','user_pkey','private-platform-token'),cookie('.other.org','foreign','must-not-keep')],
           'origins':[{'origin':'https://www.xiaoheihe.cn','localStorage':[{'name':'session','value':'private-local-state'}]},{'origin':'https://other.org','localStorage':[]}],
           'passwords':'must-not-keep'}
    r=client.post('/api/accounts/heybox/browser-session',json={'state':state})
    assert r.status_code==200 and r.json()['cookie_count']==1
    assert 'private-platform-token' not in r.text and 'private-platform-token' not in client.get('/api/accounts').text
    loaded=sessions.load('heybox')
    assert len(loaded['cookies'])==1 and len(loaded['origins'])==1 and 'passwords' not in loaded
    assert b'private-platform-token' not in sessions.path('heybox').read_bytes()

def test_guest_chrome_snapshot_does_not_replace_saved_account(local):
    client,_=local
    sessions.save('heybox',{'cookies':[cookie('.xiaoheihe.cn','user_pkey','valid-private-token')],'origins':[]})
    before=sessions.path('heybox').read_bytes()
    r=client.post('/api/accounts/heybox/browser-session',json={'state':{'cookies':[cookie('.xiaoheihe.cn','lang','zh')],'origins':[]}})
    assert r.status_code==400 and sessions.path('heybox').read_bytes()==before
    assert 'valid-private-token' not in r.text

def test_saved_login_is_reusable_when_window_is_closed(local):
    client,_=local
    sessions.save('heybox',{'cookies':[cookie('.xiaoheihe.cn','user_pkey','valid-private-token')],'origins':[]})
    sessions.LOGIN['heybox']={'state':'closed'}
    account=next(a for a in client.get('/api/accounts').json() if a['platform']=='heybox')
    assert account['saved'] and account['login']['state']=='closed'
    assert sessions.load('heybox')['cookies'][0]['value']=='valid-private-token'

def test_malformed_or_foreign_state_is_not_saved(local):
    client,_=local
    for state in [{'cookies':'bad'}, {'cookies':[None]}, {'cookies':[cookie('.other.org','pkey','foreign-secret')]}]:
        response=client.post('/api/accounts/heybox/browser-session',json={'state':state})
        assert response.status_code==400 and 'foreign-secret' not in response.text
    assert not sessions.path('heybox').exists()

def test_untrusted_cookie_shapes_fail_before_overwriting_saved_state(local):
    client,_=local
    good=cookie('.xiaoheihe.cn','user_pkey','fixture-session-only')
    sessions.save('heybox',{'cookies':[good],'origins':[]});before=sessions.path('heybox').read_bytes()
    values=[{'cookies':[{**good,'domain':None}]},{'cookies':[{**good,'expires':'bad'}]},
            {'cookies':[{**good,'sameSite':'bad'}]},{'cookies':[good],'origins':'bad'},
            {'cookies':[good],'origins':[{'origin':'https://www.xiaoheihe.cn','localStorage':[None]}]},
            {'platform':'x','cookies':[good]}]
    for state in values:
        response=client.post('/api/accounts/heybox/browser-session',json={'state':state})
        assert response.status_code==400 and sessions.path('heybox').read_bytes()==before
        assert 'fixture-session-only' not in response.text

def test_extension_download_is_code_only_and_requests_no_hosts_at_install(local):
    import io,json,zipfile
    client,_=local
    response=client.get('/api/browser-extension')
    assert response.status_code==200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert len(archive.namelist())==5 and all(p.startswith('cangye-login/') for p in archive.namelist())
        manifest=json.loads(archive.read('cangye-login/manifest.json'))
        assert not manifest.get('host_permissions') and not manifest.get('content_scripts') and not manifest.get('background')
        script=archive.read('cangye-login/popup.js').decode()
        assert 'fetch(' not in script and 'chrome.cookies.getAll({domain})' in script and 'chrome.permissions.request' in script
