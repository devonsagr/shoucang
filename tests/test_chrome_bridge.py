import json
import pytest
from app import chrome_bridge,sessions
from test_automatic_collection import local

ORIGIN='chrome-extension://'+'a'*32
STATE={'cookies':[{'name':'user_pkey','value':'synthetic-login','domain':'.xiaoheihe.cn','path':'/','secure':True,'httpOnly':True,'sameSite':'Lax','expires':-1}],'origins':[]}

def pair(client,kind='heybox'):
    response=client.post('/api/accounts/'+kind+'/connect')
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    return response.json()['code'].split(':')[-1]

def test_only_the_paired_platform_can_import_once_and_no_secret_is_returned(local,monkeypatch):
    client,_=local;monkeypatch.setattr(sessions,'protect',lambda value,decrypt=False:value)
    token=pair(client)
    wrong=client.post('/api/accounts/browser-connect',json={'platform':'x','token':token,'state':STATE},headers={'Origin':ORIGIN})
    assert wrong.status_code==400 and not sessions.path('x').exists()
    response=client.post('/api/accounts/browser-connect',json={'platform':'heybox','token':token,'state':STATE},headers={'Origin':ORIGIN})
    assert response.status_code==200 and response.json()['saved'] and response.headers['access-control-allow-origin']==ORIGIN
    assert 'synthetic-login' not in response.text and sessions.LOGIN['heybox']['state']=='saved'
    assert client.post('/api/accounts/browser-connect',json={'platform':'heybox','token':token,'state':STATE},headers={'Origin':ORIGIN}).status_code==400

def test_a_web_page_or_expired_code_cannot_refresh_credentials(local):
    client,_=local;token=pair(client)
    response=client.post('/api/accounts/browser-connect',json={'platform':'heybox','token':token,'state':STATE},headers={'Origin':'https://example.org'})
    assert response.status_code==403 and not sessions.path('heybox').exists()
    chrome_bridge.PENDING[token]['expires']=0
    assert client.post('/api/accounts/browser-connect',json={'platform':'heybox','token':token,'state':STATE},headers={'Origin':ORIGIN}).status_code==400

def test_extension_cors_is_limited_to_its_cookie_handoff_not_general_writes(local):
    client,_=local
    assert client.options('/api/accounts/browser-connect',headers={'Origin':ORIGIN}).status_code==204
    assert client.options('/api/accounts/browser-connect',headers={'Origin':'https://example.org'}).status_code==403
    assert client.post('/api/materials',json={'url':'https://example.org/post','text':'fixture'},headers={'Origin':ORIGIN}).status_code==403

def test_failed_cookie_validation_keeps_the_code_and_existing_login(local,monkeypatch):
    client,_=local;monkeypatch.setattr(sessions,'protect',lambda value,decrypt=False:value)
    sessions.import_state('heybox',STATE);old=sessions.path('heybox').read_bytes();token=pair(client)
    response=client.post('/api/accounts/browser-connect',json={'platform':'heybox','token':token,'state':{'cookies':[]}},headers={'Origin':ORIGIN})
    assert response.status_code==400 and token in chrome_bridge.PENDING and sessions.path('heybox').read_bytes()==old
