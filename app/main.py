from __future__ import annotations
from pathlib import Path
import json
import threading
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import adapters, assets, bilingual, first_layer, knowledge, obsidian, playback, reading_preview, service, store, topics, vault_files, xbookmarks, sessions, platform_browser, xofficial

@asynccontextmanager
async def lifespan(app):
    store.init()
    service.organize_topics()
    service.STOP.clear()
    thread = threading.Thread(target=service.worker, daemon=True, name='collector')
    favorite_thread=threading.Thread(target=service.favorites_worker,daemon=True,name='favorite-lists')
    thread.start()
    favorite_thread.start()
    yield
    service.STOP.set()
    thread.join(timeout=2)
    favorite_thread.join(timeout=2)

app = FastAPI(title='藏页 · 多平台收藏与批注', version='0.5.4', lifespan=lifespan, docs_url=None, redoc_url=None)

@app.get('/design/v6/reference-{variant}.png')
def new_design_reference(variant: Literal['a','b','c','d','e','f','g']):
    path=store.ROOT / 'docs' / 'design' / 'v6' / f'reference-{variant}.png'
    if not path.is_file():raise HTTPException(404,'本机没有这张历史设计参考')
    return FileResponse(path)

@app.get('/design/motion')
def motion_reference():
    return FileResponse(store.ROOT / 'web' / 'motion.html')

@app.get('/design')
def design_gallery():
    return FileResponse(store.ROOT / 'web' / 'design.html')

@app.get('/design/reference-{variant}.png')
def design_reference(variant: Literal['a','b','c']):
    path=store.ROOT / 'docs' / 'design' / 'v5' / f'reference-{variant}.png'
    if not path.is_file():raise HTTPException(404,'本机没有这张历史设计参考')
    return FileResponse(path)

@app.get('/api/storage')
def storage_locations():
    vault=obsidian.root()
    layout=obsidian.paths()
    return {'local_root':str(store.DATA/'materials'),
            'database':str(store.DATA/'library.sqlite3'),
            'outbox':str(store.DATA/'outbox'),
            'review_root':str(store.DATA/'review'),
            'layer_root':str(store.DATA/'layers'),
            'documents':str(store.ROOT/'docs'),
            'references':str(store.ROOT/'docs'/'design'/'v6'),
            'local_layout':'<平台>/<材料ID>/material.md；原图、字幕和历史在同一材料目录',
            'vault':vault,
            'knowledge_paths':obsidian.paths(),
            'vault_layout':f'第一层：{layout["callable"]} 或 {layout["digest"]}/<标题--导出ID>/index.md，图片在同条assets。第二层：<主题目录>/{layout["materials"]}/可调用资料或待消化/<标题--导出ID>/index.md，同条来源与批注.md和assets。原始材料单独导出：{layout["archive"]}/<平台>/<状态>/<单条目录>。回收站：{layout["trash"]}。换层、删除与恢复按文件归属联动。',
            'notice':'两种批注去向各有独立第一层记录，与新收藏分开。首次保存不运行AI；所有小库写入先预览确认，已确认快照不自动移动或覆盖。'}

@app.post('/api/obsidian/structure')
def create_vault_structure():
    return obsidian.create_structure()

@app.get('/docs', response_class=HTMLResponse)
def api_docs():
    import html
    schema = app.openapi()
    rows = ''.join(f'<tr><td>{html.escape(method.upper())}</td><td>{html.escape(path)}</td><td>{html.escape(value.get("summary", ""))}</td></tr>' for path, methods in schema['paths'].items() for method, value in methods.items())
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>API 接口</title><link rel="stylesheet" href="/static/style.css"><main><h1>API 接口</h1><p>本机服务；写请求需设置 X-Local-Request: 1 与 Content-Type: application/json。</p><p><a href="/openapi.json">查看完整 OpenAPI 3.1 请求与响应定义</a> · <a href="/">返回材料库</a></p><table><thead><tr><th>方法</th><th>路径</th><th>操作</th></tr></thead><tbody>' + rows + '</tbody></table></main></html>'

@app.middleware('http')
async def local_only(request: Request, call_next):
    host = request.headers.get('host', '').split(':')[0]
    if host not in ('127.0.0.1', 'localhost', 'testserver'):
        return JSONResponse({'detail': '仅允许本机访问'}, 403)
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if (origin and origin != str(request.base_url).rstrip('/')) or request.headers.get('x-local-request') != '1':
            return JSONResponse({'detail': '仅接受本机界面或显式 API 请求'}, 403)
        if int(request.headers.get('content-length', '0')) > 5_000_000:
            return JSONResponse({'detail': '请求超过 5MB'}, 413)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' https://www.youtube.com/iframe_api https://www.youtube.com/s/player/; style-src 'self'; img-src 'self' data:; connect-src 'self'; media-src 'self'; frame-src https://www.youtube.com https://player.bilibili.com https://open.douyin.com; frame-ancestors 'none'; base-uri 'none'"
    return response

@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse({'detail': str(exc)}, 400)

class MaterialInput(BaseModel):
    engine: Literal['local', 'firecrawl'] = 'local'
    url: str = Field(min_length=8, max_length=4000)
    origin: Literal['favorite', 'link'] = 'link'
    title: str = Field(default='', max_length=1000)
    text: str = Field(default='', max_length=1_000_000)
    subtitles: str = Field(default='', max_length=2_000_000)
    subtitle_format: Literal['vtt', 'srt', 'json', 'json3'] = 'vtt'
    subtitle_source: str = Field(default='来源未声明', max_length=200)
    language: str = Field(default='未指定', max_length=40)
    transcribe: bool = True
    recollect_deleted: bool = False

@app.get('/api/health')
def health():
    return {'status': 'ok', 'version': app.version,
            'design_references':(store.ROOT/'docs'/'design'/'v6'/'reference-e.png').is_file()}

@app.get('/api/capabilities')
def capabilities():
    return [{'id':key,'name':name,'favorites':'网页登录后通过专用收藏接口读取自己的清单，offset分页；断点与稳定ID去重' if key=='heybox' else '官方网页登录后读取自己的收藏页；逐页保存、去重，可停止或继续',
             'content':'自动平台字幕 → 本机音频转写，逐段时间轴' if key in ('bilibili','youtube','douyin') else '正文与对应图片、已加载的部分评论；视频仅留原链接',
             'status':'B站遍历全部自建收藏夹；其他平台按实际可访问收藏页读取。页面结构与账号权限需现场验证，未到末尾不标成全部成功。'}
            for key,(name,_) in adapters.PLATFORMS.items()]

@app.get('/api/accounts')
def accounts():
    return [sessions.status(kind) for kind in sessions.PAGES]

class LoginInput(BaseModel):
    action: Literal['open','save','close','forget']

class BrowserSessionInput(BaseModel):
    state: dict

@app.get('/api/browser-extension')
def browser_extension():
    import io,zipfile
    package=io.BytesIO()
    root=Path(__file__).resolve().parents[1]/'browser-extension'
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
        for name in ('manifest.json','popup.html','popup.css','popup.js','README.md'):
            z.writestr('cangye-login/'+name,(root/name).read_bytes())
    return Response(package.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="cangye-chrome-login.zip"'})

@app.post('/api/accounts/{kind}/browser-session')
def import_browser_session(kind:str,body:BrowserSessionInput):
    if kind not in sessions.PAGES:raise ValueError('未知平台')
    return sessions.import_state(kind,body.state)

@app.post('/api/accounts/{kind}/login')
def login(kind: str, body: LoginInput):
    if kind not in sessions.PAGES: raise ValueError('未知平台')
    if body.action == 'forget':
        cfg = store.settings(); old = cfg.setdefault('cookies',{}).pop(kind,None)
        if old:
            target=(store.ROOT/old).resolve()
            if target.is_relative_to(store.DATA/'credentials'): target.unlink(missing_ok=True)
        if kind=='x': cfg.pop('x_account',None)
        store.save_settings(cfg)
    return sessions.command(kind,body.action)

class XClientInput(BaseModel):
    client_id: str = Field(max_length=500)

@app.put('/api/accounts/x/client')
def x_client(body: XClientInput):
    if any(c.isspace() for c in body.client_id): raise ValueError('Client ID 不应包含空白')
    cfg=store.settings(); cfg['x_client_id']=body.client_id; store.save_settings(cfg)
    return {'saved':True,'redirect_uri':xofficial.REDIRECT}

@app.get('/oauth/x/callback',response_class=HTMLResponse)
def x_callback(code: str='',state: str='',error: str=''):
    import html
    try:
        xofficial.callback(code,state,error)
        message='X 官方授权已保存。可以关闭此窗口，回到收藏处理器导入收藏。'
    except ValueError as exc:
        message=str(exc)
    return HTMLResponse('<!doctype html><meta charset="utf-8"><title>X 官方授权</title><p>'+html.escape(message)+'</p>',
                        headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})

class FavoritesInput(BaseModel):
    platform: Literal['bilibili','youtube','douyin','x','heybox','xiaohongshu']
    url: str = Field(default='',max_length=4000)
    resume_job_id: str | None = None
    repair_incomplete: bool=False

@app.post('/api/favorites')
def favorites(body: FavoritesInput):
    kind=body.platform
    if not sessions.path(kind).exists(): raise ValueError('请先打开该平台官方登录窗口，完成登录并保存状态')
    if kind=='x':
        if store.settings().get('x_read_mode','session')=='oauth':
            if not xofficial.configured(): raise ValueError('请先完成 X 官方 OAuth 授权')
        else:
            xbookmarks.read_cookies()
            xbookmarks.clear_block()  # Only an explicit new import/continue permits another attempt.
    url=body.url or sessions.status(kind)['favorite_url']
    platform_browser.safe_page(kind,url)
    if kind!='bilibili' and not any(word in url for word in ('bookmark','playlist','favorite','favour','collect','user/profile')):
        raise ValueError('请在官方窗口打开自己的收藏页，然后复制该页地址；首页不能代替收藏列表')
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        active=c.execute("SELECT id FROM jobs WHERE kind='favorites' AND state IN ('queued','running') AND json_extract(payload,'$.platform')=?",(kind,)).fetchone()
        if active: return {'job_id':active['id'],'duplicate':True}
        progress={}
        repair=body.repair_incomplete
        if body.resume_job_id:
            previous=c.execute("SELECT payload,progress,state FROM jobs WHERE id=? AND kind='favorites'",(body.resume_job_id,)).fetchone()
            if not previous or json.loads(previous['payload']).get('platform')!=kind: raise ValueError('没有这个平台的可继续任务')
            progress=json.loads(previous['progress'])
            repair=json.loads(previous['payload']).get('repair_incomplete',False)
            if progress.get('complete'): raise ValueError('上次已读到末尾；请开始一次新的导入')
        jid=store.enqueue(c,'favorites',{'platform':kind,'url':url,'repair_incomplete':repair,**({'resumed_from':body.resume_job_id} if body.resume_job_id else {})})
        c.execute('UPDATE jobs SET progress=? WHERE id=?',(store.dumps(progress),jid))
    cfg=store.settings(); cfg.setdefault('favorite_pages',{})[kind]=url; store.save_settings(cfg)
    return {'job_id':jid,'duplicate':False}

@app.post('/api/jobs/{jid}/stop')
def stop_job(jid: str):
    with store.db() as c:
        row=c.execute("SELECT payload,state,kind FROM jobs WHERE id=?",(jid,)).fetchone()
        if not row or row['kind']!='favorites': raise ValueError('只支持停止收藏读取任务')
        payload=json.loads(row['payload']); payload['stop']=True
        c.execute('UPDATE jobs SET payload=?,updated=? WHERE id=?',(store.dumps(payload),store.now(),jid))
        if row['state']=='queued': c.execute("UPDATE jobs SET state='failed',error='用户停止读取；可继续' WHERE id=?",(jid,))
    return {'stopping':True}

@app.get('/api/materials')
def materials(state: str = 'pending', q: str = '', origin: str = '', platform: str = '', capture: str = '', topic: str = ''):
    if topic and topic not in topics.LABELS: raise ValueError('未知主题')
    scope, scope_params = [], []
    for column, value in [('origin', origin), ('platform', platform)]:
        if value:
            scope.append(column + '=?'); scope_params.append(value)
    clauses, params = scope.copy(), scope_params.copy()
    clauses.append("trashed<>''" if state=='trash' else "trashed=''")
    routed="(EXISTS(SELECT 1 FROM first_layers f WHERE f.source_material_id=materials.id) OR EXISTS(SELECT 1 FROM pushes p WHERE p.material_id=materials.id AND p.state='confirmed' AND p.destination='obsidian' AND json_extract(p.payload,'$.shelf_output.stage') IN ('callable','digest')))"
    if state not in ('all_raw','trash'):clauses.append(routed if state=='source_archive' else 'NOT '+routed)
    if state in ('pending', 'later', 'review', 'done'):
        clauses.append('processing=?'); params.append(state)
        clauses.append("coalesce(json_extract(content_json,'$.reading_intent'),'human')<>'reference'")
    elif state=='reference':clauses.append("json_extract(content_json,'$.reading_intent')='reference'")
    if q:
        clauses.append("(title LIKE ? OR body LIKE ? OR notes LIKE ? OR summary LIKE ? OR content_json LIKE ?)")
        params += ['%' + q + '%'] * 5
    statuses = {
        'transcribed': "coalesce(json_array_length(content_json,'$.segments'),0)>0 AND coalesce(json_extract(content_json,'$.transcript_state'),'')<>'uncertain'",
        'uncertain': "json_extract(content_json,'$.transcript_state')='uncertain'",
        'missing': "platform IN ('bilibili','youtube','douyin') AND coalesce(json_array_length(content_json,'$.segments'),0)=0",
        'failed': "json_extract(content_json,'$.transcript_state')='failed'",
        'paused': "collection='paused'",
    }
    if capture in statuses: clauses.append(statuses[capture])
    topic_clauses, topic_params = clauses.copy(), params.copy()
    if topic:
        clauses.append('topic=?'); params.append(topic)
        scope.append('topic=?'); scope_params.append(topic)
    with store.db() as c:
        rows = c.execute("""
            SELECT id,title,url,platform,origin,collection,processing,error,updated,revision,body,
              trashed,content_json,topic,topic_source,
              substr(coalesce(json_extract(content_json,'$.segments[0].text'),body),1,240) AS excerpt,
              (SELECT json_extract(value,'$.path') FROM json_each(materials.content_json,'$.media')
               WHERE json_extract(value,'$.status')='saved' LIMIT 1) AS thumbnail
            FROM materials
        """ + (' WHERE ' + ' AND '.join(clauses) if clauses else '') + ' ORDER BY updated DESC', params).fetchall()
        counts = dict(c.execute("SELECT CASE WHEN "+routed+" THEN 'source_archive' WHEN json_extract(content_json,'$.reading_intent')='reference' THEN 'reference' ELSE processing END AS state,count(*) FROM materials WHERE trashed=''"+
            (' AND '+' AND '.join(scope) if scope else '')+' GROUP BY state',scope_params).fetchall())
        for stage in ('pending','later','review','done','reference'): counts.setdefault(stage,0)
        counts['all'] = sum(counts.get(s,0) for s in ('pending','later','review','done','reference'))
        counts['trash'] = c.execute("SELECT count(*) FROM materials WHERE trashed<>''"+
            (' AND '+' AND '.join(scope) if scope else ''),scope_params).fetchone()[0]
        counts.setdefault('source_archive',0)
        for track in first_layer.LABELS:
            counts[track]=c.execute("SELECT count(*) FROM first_layers WHERE active=1 AND trashed='' AND track=?"+
                                   (' AND '+' AND '.join(scope) if scope else ''),[track,*scope_params]).fetchone()[0]
        topic_counts = dict(c.execute('SELECT topic,count(*) FROM materials WHERE '+
            ' AND '.join(topic_clauses)+' GROUP BY topic', topic_params).fetchall())
    items=[]
    for row in rows:
        item=dict(row); content=json.loads(item.pop('content_json'))
        body=item.pop('body')
        item['excerpt']=reading_preview.excerpt({'platform':item['platform'],'body':body,'content':content}) or item['excerpt']
        item['media_kind']=content.get('media_kind')
        item['transcript_state']=store.transcript_status(item['platform'],item['collection'],content)
        item['segments_count']=len(content.get('segments',[]))
        item['transcription_model']=content.get('transcription',{}).get('model','')
        item['reading_intent']=content.get('reading_intent','human')
        items.append(item)
    return {'items': items, 'counts': counts,
            'topics': [{'id': key, 'label': label, 'count': topic_counts.get(key, 0)} for key,label in topics.LABELS.items()]}

@app.get('/api/first-layer')
def first_catalogue(track: Literal['callable','digest'],state: str='all',q: str='',origin: str='',platform: str='',topic: str=''):
    if topic and topic not in topics.LABELS:raise ValueError('未知主题')
    result=first_layer.catalogue(track,{'q':q,'origin':origin,'platform':platform,'topic':topic},state)
    result['counts']=materials(state='all',origin=origin,platform=platform,topic=topic)['counts']
    return result

@app.get('/api/first-layer/folders')
def first_folders():
    location=obsidian.location();vault=Path(location['vault']) if location['vault'] else None
    return {k:{'label':first_layer.LABELS[k],'path':str(vault.joinpath(*v.split('/'))) if vault else '',
               'available':location['available'],'error':location['error']} for k,v in first_layer.folders().items()}

@app.get('/api/first-layer/organization-prompt')
def organization_prompt():
    return knowledge.organization_prompt()

class TopicInput(BaseModel):
    topic: str = Field(max_length=40)
    revision: int

@app.post('/api/materials/{mid}/topic')
def material_topic(mid: str, body: TopicInput):
    return service.set_topic(mid, body.topic, body.revision)

@app.post('/api/materials')
def create(body: MaterialInput):
    return service.add(body.model_dump(),retry_incomplete=True,allow_deleted=body.recollect_deleted)

class BatchMaterialItem(BaseModel):
    id: str = Field(min_length=1,max_length=80,pattern=r'^[A-Za-z0-9_-]+$')
    revision: int = Field(ge=1)

class BatchMaterialsInput(BaseModel):
    action: Literal['trash','restore','purge']
    items: list[BatchMaterialItem] = Field(min_length=1,max_length=100)
    confirmation: Literal['彻底删除'] | None = None

@app.post('/api/materials/batch-actions')
def batch_materials(body: BatchMaterialsInput):
    return store.batch_materials(body.action,[item.model_dump() for item in body.items],body.confirmation)

@app.delete('/api/materials/{mid}')
def trash(mid: str):
    return store.trash(mid)

@app.post('/api/materials/{mid}/restore')
def restore(mid: str):
    return store.trash(mid,restore=True)

class PurgeInput(BaseModel):
    revision: int = Field(ge=1)
    confirmation: Literal['彻底删除']

@app.post('/api/materials/{mid}/purge')
def purge(mid: str, body: PurgeInput):
    return store.purge(mid, body.revision, body.confirmation)

@app.post('/api/import')
def batch(items: list[MaterialInput]):
    if len(items) > 500:
        raise ValueError('每批最多 500 条')
    results = []
    for i, item in enumerate(items):
        try:
            results.append({'index': i, **service.add(item.model_dump(), source='用户导入清单')})
        except ValueError as exc:
            results.append({'index': i, 'error': str(exc)})
    return {'results': results}

@app.get('/api/materials/{mid}')
def detail(mid: str):
    item = store.get(mid)
    item['transcript_state']=store.transcript_status(item['platform'],item['collection'],item['content'])
    with store.db() as c:
        item['events'] = [dict(r) for r in c.execute('SELECT * FROM events WHERE material_id=? ORDER BY id DESC', (mid,))]
        item['pushes'] = [dict(r) for r in c.execute('SELECT id,destination,state,created,confirmed FROM pushes WHERE material_id=? ORDER BY created DESC', (mid,))]
        job=c.execute("SELECT progress FROM jobs WHERE material_id=? AND kind='collect' AND state='running' ORDER BY created DESC LIMIT 1",(mid,)).fetchone()
        item['progress']=json.loads(job['progress']) if job else {}
        subtitle_job=c.execute("SELECT id,state,error FROM jobs WHERE material_id=? AND kind='subtitle_tracks' ORDER BY created DESC LIMIT 1",(mid,)).fetchone()
        item['subtitle_job']=dict(subtitle_job) if subtitle_job else None
        translation_job=c.execute("SELECT id,state,error,progress FROM jobs WHERE material_id=? AND kind='bilingual' ORDER BY created DESC LIMIT 1",(mid,)).fetchone()
        item['translation_job']=dict(translation_job) if translation_job else None
        if item['translation_job']:item['translation_job']['progress']=json.loads(item['translation_job']['progress'])
    item['reader_translation']=bilingual.current(item)
    item['ai_review']=knowledge.review(item)
    with store.db() as c:
        ai_job=c.execute("SELECT id,state,error,progress FROM jobs WHERE material_id=? AND kind='ai' ORDER BY created DESC LIMIT 1",(mid,)).fetchone()
    item['ai_job']=dict(ai_job) if ai_job else None
    if item['ai_job']:item['ai_job']['progress']=json.loads(item['ai_job']['progress'])
    with store.db() as c:
        receipts=c.execute("SELECT id,payload,confirmed FROM pushes WHERE material_id=? AND state='confirmed' ORDER BY confirmed DESC",(mid,)).fetchall()
    item['vault_receipts']=[]
    with store.db() as c:
        item['vault_files']=vault_files.describe(c,mid)
        for r in receipts:
            outcome=json.loads(r['payload']).get('shelf_output') or json.loads(r['payload']).get('knowledge_output')
            if not outcome:continue
            location=vault_files.current(c,r['id'])
            note=location['note'] if location else outcome['note'];vault=location['vault'] if location else outcome['vault']
            item['vault_receipts'].append({'id':r['id'],'confirmed':r['confirmed'],'note':note,'path':str(Path(vault)/note),
                                          'state':location['state'] if location else 'legacy','stage':outcome.get('stage','formal')})
    item['markdown'] = store.markdown(item)
    item['reading_preview']=reading_preview.make(item)
    return item

@app.get('/api/materials/{mid}/markdown', response_class=PlainTextResponse)
def markdown(mid: str):
    return PlainTextResponse(store.markdown(store.get(mid)), headers={'Content-Disposition': f'attachment; filename="{mid}.md"'})

@app.post('/api/materials/{mid}/playback')
def video_playback(mid: str,payload: dict | None = None):
    item=store.available(mid)
    return JSONResponse(playback.douyin(item,refresh=(payload or {}).get('refresh') is True), headers={'Cache-Control':'no-store'})

@app.get('/api/materials/{mid}/playback-stream/{token}')
def video_stream(mid: str,token: str,request: Request):
    origin=request.headers.get('origin')
    if origin and origin!=str(request.base_url).rstrip('/'):
        raise HTTPException(403,'只允许本机同源播放')
    if request.headers.get('x-local-request')!='1' and request.headers.get('sec-fetch-site')!='same-origin':
        raise HTTPException(403,'只允许材料页面播放或显式本机 API 请求')
    return playback.stream(store.available(mid),token,request.headers.get('range',''))

@app.get('/api/materials/{mid}/images/{relative:path}')
def image(mid: str, relative: str):
    item = store.get(mid)
    if not any(a.get('path') == relative and a['status'] == 'saved' for a in item['content'].get('media', [])):
        raise HTTPException(404, '此图片不属于当前材料')
    return FileResponse(assets.image_path(mid, relative))

@app.get('/api/materials/{mid}/versions')
def versions(mid: str):
    store.get(mid)
    with store.db() as c:
        return [dict(r) for r in c.execute('SELECT * FROM versions WHERE material_id=? ORDER BY id DESC', (mid,))]

class NoteInput(BaseModel):
    notes: str = Field(max_length=200000)
    revision: int
    annotation_kind: Literal['note','inspiration','viewpoint','question','material'] | None=None
    annotation_track: Literal['callable','digest'] | None=None

@app.put('/api/materials/{mid}/notes')
def notes(mid: str, body: NoteInput):
    item=store.available(mid);content=item['content']
    if body.annotation_kind is not None:content['annotation_kind']=body.annotation_kind
    if body.annotation_track is not None:
        content.setdefault('annotations',{})[body.annotation_track]=body.notes
    with store.db() as c:
        r = c.execute('UPDATE '+store.table_for(mid)+' SET notes=?,content_json=?,revision=revision+1,updated=? WHERE id=? AND revision=?', (body.notes,store.dumps(content),store.now(),mid,body.revision))
        if not r.rowcount:
            raise HTTPException(409, '材料已更新，请重新打开后保存，以免覆盖')
        store.event(c, mid, 'notes_saved', {'notes': body.notes,'annotation_kind':body.annotation_kind,'annotation_track':body.annotation_track})
    store.archive(mid)
    return store.get(mid)

@app.post('/api/materials/{mid}/supplement')
def supplement(mid: str, body: MaterialInput):
    if mid.startswith('l1_'):raise ValueError('第一层原文是保存时快照；请打开原始收藏补充，再保存新版材料')
    item = store.available(mid)
    with store.db() as c:
        if c.execute("SELECT 1 FROM jobs WHERE material_id=? AND state IN ('queued','running')", (mid,)).fetchone():
            raise ValueError('材料仍在处理，请等待任务结束后补充')
    result = adapters.manual({**body.model_dump(), 'title': body.title or item['title']})
    if not body.text.strip():
        result['body'] = item['body']
        result['content']['original_text'] = item['content'].get('original_text', item['body'])
    if not body.subtitles.strip():
        for key in ('segments', 'subtitle_source', 'language', 'raw_subtitles', 'subtitle_format', 'subtitle_tracks', 'bilingual_notice'):
            if key in item['content']:
                result['content'][key] = item['content'][key]
    for key in ('media', 'comments', 'comments_status', 'thread_status', 'author', 'created_at'):
        if key in item['content']: result['content'][key] = item['content'][key]
    service.save_content(mid, result)
    service.queue_images(mid)
    return store.get(mid)

class RetryInput(BaseModel):
    transcribe: bool = True
    engine: Literal['local', 'firecrawl'] = 'local'
    refresh: bool = False

@app.post('/api/materials/{mid}/subtitle-tracks')
def subtitle_tracks(mid: str):
    item = store.available(mid)
    if item['platform'] not in ('bilibili', 'youtube') or not item['content'].get('segments'):
        raise ValueError('请先取得 B站或 YouTube 原字幕；第二语言由平台已有字幕轨道提供')
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT 1 FROM jobs WHERE material_id=? AND kind<>'subtitle_tracks' AND state IN ('queued','running')", (mid,)).fetchone():
            raise ValueError('材料仍在处理，请等待任务结束后获取双语')
        jid = store.enqueue(c, 'subtitle_tracks', {}, mid)
    return {'job_id':jid}

@app.post('/api/materials/{mid}/bilingual')
def bilingual_reading(mid: str):
    item=store.available(mid)
    if bilingual.current(item):return {'cached':True,'source':'本机双语阅读缓存'}
    if not bilingual.units(item):raise ValueError('尚无可翻译的中英正文、字幕或回复')
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT 1 FROM jobs WHERE material_id=? AND kind<>'bilingual' AND state IN ('queued','running')",(mid,)).fetchone():
            raise ValueError('材料仍在处理，请等待任务结束后开启双语')
        jid=store.enqueue(c,'bilingual',{},mid)
    return {'cached':False,'job_id':jid,'source':'平台第二轨优先，其他文字本机翻译，不上传材料'}

@app.post('/api/materials/{mid}/retry')
def retry(mid: str, body: RetryInput):
    if mid.startswith('l1_'):raise ValueError('第一层不重复抓取；请打开原始收藏后重试')
    item = store.available(mid)
    if item['collection'] == 'ready' and not body.refresh:
        raise ValueError('已取得正文；如需修改请补充原文，保留旧版本')
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        jid = store.enqueue(c, 'collect', body.model_dump(), mid)
        c.execute("UPDATE materials SET collection='queued',error='' WHERE id=?", (mid,))
    return {'job_id': jid}

@app.get('/api/vault/notes')
def vault_notes(folder: str='',query: str=''):
    return knowledge.browse(folder,query)

@app.get('/api/vault/note')
def vault_note(path: str):
    return knowledge.read(path)

class KnowledgeContextInput(BaseModel):
    paths: list[str] = Field(max_length=5)
    revision: int

@app.put('/api/materials/{mid}/knowledge-context')
def knowledge_context(mid: str,body: KnowledgeContextInput):
    return service.save_knowledge_context(mid,body.paths,body.revision)

@app.get('/api/materials/{mid}/knowledge-folders')
def knowledge_folders(mid: str):
    return knowledge.output_folders(store.available(mid).get('topic','uncategorized'))

@app.get('/api/materials/{mid}/processing-paths')
def processing_paths(mid: str):
    return knowledge.processing_paths(store.available(mid))

class AIInput(BaseModel):
    include_knowledge: bool=False
    from_annotation: bool=False
    second_pass: bool=False
    revision: int | None=None

class AIReviewInput(BaseModel):
    revision: int
    summary_hash: str

@app.post('/api/materials/{mid}/ai-review')
def ai_review(mid: str,body: AIReviewInput):
    return service.mark_ai_reviewed(mid,body.revision,body.summary_hash)

@app.post('/api/materials/{mid}/ai')
def ai(mid: str,body: AIInput | None=None):
    item = store.available(mid)
    if item['collection'] != 'ready':
        raise ValueError('请先补充完整内容后再进行 AI 整理')
    annotation=bool(body and (body.from_annotation or body.second_pass))
    if annotation and not item['notes'].strip():raise ValueError('请先为这条材料保存一条批注；它就是整理依据')
    if annotation and body.revision!=item['revision']:raise ValueError('批注或材料已变化，请刷新后再提交')
    if body and body.second_pass and not knowledge.review(item)['reviewed']:raise ValueError('请先审查上一轮整理结果，再按批注继续整理')
    cfg = store.settings()
    if not cfg.get('ai_api_key') or not cfg.get('ai_model'):
        raise ValueError('请先在设置中配置 AI 服务')
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        refs=knowledge.context(item) if body and body.include_knowledge else []
        if body and body.include_knowledge and not refs:raise ValueError('请先选择要结合的小库笔记')
        payload={'knowledge_notes':refs} if refs else {}
        if annotation:
            payload['workflow']={'revision':item['revision'],'annotation_hash':store.digest(item['notes']),
                                 'second_pass':body.second_pass,'previous_summary_hash':store.digest(item['summary']) if body.second_pass else ''}
        active=c.execute("SELECT payload FROM jobs WHERE material_id=? AND kind='ai' AND state IN ('queued','running')",(mid,)).fetchone()
        if active and json.loads(active['payload'])!=payload:raise ValueError('已有不同内容的AI整理任务，请等其结束后再结合所选笔记')
        latest=c.execute('SELECT revision,trashed FROM '+store.table_for(mid)+' WHERE id=?',(mid,)).fetchone()
        if latest['trashed'] or latest['revision']!=item['revision']:raise ValueError('材料已改变，请刷新后再整理')
        jid = store.enqueue(c, 'ai', payload, mid)
    return {'job_id': jid}

class StatusInput(BaseModel):
    state: Literal['pending', 'later', 'done']
    revision: int | None = Field(default=None, ge=1)

class ReadingIntentInput(BaseModel):
    revision: int

@app.post('/api/materials/{mid}/return-to-reading')
def return_to_reading(mid: str,body: ReadingIntentInput):
    with store.db() as c:
        row=c.execute('UPDATE materials SET content_json=json_set(content_json,\'$.reading_intent\',\'human\'),processing=\'pending\',revision=revision+1 WHERE id=? AND revision=? AND trashed=\'\'',(mid,body.revision))
        if not row.rowcount:raise ValueError('材料已变化或已删除，请刷新后再调入待消化')
        store.event(c,mid,'reading_intent_changed',{'intent':'human','processing':'pending'})
    store.archive(mid)
    return store.get(mid)

@app.post('/api/materials/{mid}/status')
def status(mid: str, body: StatusInput):
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        item = c.execute('SELECT * FROM '+store.table_for(mid)+' WHERE id=?', (mid,)).fetchone()
        if not item or item['trashed']:
            raise ValueError('材料不存在或已删除，请先恢复材料')
        if body.revision is not None and body.revision != item['revision']:
            raise HTTPException(409, '材料已更新，请重新打开后调整处理状态')
        if body.state == 'done' and item['collection'] != 'ready':
            raise ValueError('抓取未完成；请补充原文后再标记完成')
        if item['processing'] == body.state:
            return {'state': body.state}
        c.execute('UPDATE '+store.table_for(mid)+' SET processing=?,revision=revision+1,updated=? WHERE id=?', (body.state, store.now(), mid))
        store.event(c, mid, 'processing_changed', {'from':item['processing'],'state':body.state})
    store.archive(mid)
    return {'state': body.state}

class KnowledgeOutputInput(BaseModel):
    title: str = Field(min_length=1,max_length=300)
    text: str = Field(min_length=1,max_length=100000)
    folder: str = Field(min_length=1,max_length=600)
    authorship: Literal['edited','manual','reference']='edited'

class ShelfOutputInput(BaseModel):
    stage: Literal['ai_review','reference','annotation','callable','digest']
    overview: str = Field(default='',max_length=2000)

class PushInput(BaseModel):
    destination: Literal['todo', 'knowledge', 'markdown', 'obsidian']
    complete_processing: bool = True
    knowledge_output: KnowledgeOutputInput | None=None
    shelf_output: ShelfOutputInput | None=None

@app.post('/api/materials/{mid}/push-preview')
def push_preview(mid: str, body: PushInput):
    return service.preview(mid, body.destination, complete_processing=body.complete_processing,
                           knowledge_output=body.knowledge_output.model_dump() if body.knowledge_output else None,
                           shelf_output=body.shelf_output.model_dump() if body.shelf_output else None)

class ConfirmInput(BaseModel):
    hash: str

@app.post('/api/pushes/{pid}/confirm')
def push_confirm(pid: str, body: ConfirmInput):
    try:
        return service.confirm(pid, body.hash)
    except (ValueError, OSError) as exc:
        error = service.safe_error(exc)
        with store.db() as c:
            row = c.execute('SELECT material_id FROM pushes WHERE id=?',(pid,)).fetchone()
            if row: store.event(c,row['material_id'],'push_failed',{'id':pid,'error':error})
        raise ValueError(error) from None

@app.get('/api/outbox')
def outbox():
    with store.db() as c:
        return [dict(r) for r in c.execute("SELECT id,material_id,destination,payload,confirmed FROM pushes WHERE state='confirmed' ORDER BY confirmed")]

@app.get('/api/reference-index')
def reference_index(topic: str='',q: str='',limit: int=50):
    if topic and topic not in topics.LABELS:raise ValueError('未知主题')
    if not 1<=limit<=100 or len(q)>200:raise ValueError('索引最多读取100条；关键词最多200字符')
    with store.db() as c:
        rows=c.execute("""SELECT id,material_id,payload,confirmed FROM pushes p
          WHERE state='confirmed' AND json_extract(payload,'$.shelf_output.stage')='reference'
          AND NOT EXISTS(SELECT 1 FROM pushes n WHERE n.material_id=p.material_id AND n.state='confirmed'
            AND json_extract(n.payload,'$.shelf_output.stage')='reference'
            AND (n.confirmed>p.confirmed OR (n.confirmed=p.confirmed AND n.id>p.id)))
          AND (?='' OR json_extract(payload,'$.shelf_output.topic')=?)
          AND (?='' OR json_extract(payload,'$.shelf_output.title') LIKE ? OR json_extract(payload,'$.shelf_output.overview') LIKE ?)
          ORDER BY confirmed DESC LIMIT ?""",(topic,topic,q,'%'+q+'%','%'+q+'%',limit)).fetchall()
    return {'items':[{'id':r['id'],'material_id':r['material_id'],'confirmed':r['confirmed'],
                    **{k:value[k] for k in ('title','overview','topic','source_url','note','path')}} for r in rows
                    if (value:=json.loads(r['payload']).get('shelf_output'))],
            'notice':'只返回本人确认存放的最新资料索引；原文通过source_url或来源笔记读取，不表示已读或已消化。'}

class SyncInput(BaseModel):
    url: str
    transcribe: bool = True

@app.post('/api/sync')
def sync(body: SyncInput):
    adapters.canonical(body.url)
    if adapters.platform(body.url) not in ('bilibili', 'youtube'):
        raise ValueError('此平台未支持收藏列表自动同步，请导入链接清单')
    with store.db() as c:
        jid = store.enqueue(c, 'sync', body.model_dump())
    return {'job_id': jid}

@app.get('/api/jobs')
def jobs():
    with store.db() as c:
        values = [dict(r) for r in c.execute('SELECT id,material_id,kind,state,error,progress,created,updated FROM jobs ORDER BY updated DESC,created DESC LIMIT 200')]
    for value in values: value['progress'] = json.loads(value['progress'])
    return values

@app.post('/api/x/check')
def x_check():
    if not store.settings().get('x_legacy_read_enabled'):
        raise ValueError('旧 Cookie / 非官方入口默认关闭，请在统一「导入收藏 → X」使用官方授权')
    xbookmarks.read_cookies()
    with store.db() as c:
        active = c.execute("SELECT id FROM jobs WHERE kind='x_check' AND state IN ('queued','running')").fetchone()
        jid = active['id'] if active else store.enqueue(c, 'x_check', {})
    return {'job_id':jid}

class XSyncInput(BaseModel):
    limit: int = Field(default=100, ge=20, le=500, multiple_of=20)
    comment_limit: int = Field(default=20, ge=0, le=20)
    resume_job_id: str | None = None

@app.post('/api/x/sync')
def x_sync(body: XSyncInput):
    if not store.settings().get('x_legacy_read_enabled'):
        raise ValueError('旧 Cookie / 非官方入口默认关闭，请在统一「导入收藏 → X」使用官方授权')
    xbookmarks.read_cookies()
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        active = c.execute("SELECT id FROM jobs WHERE kind='x_sync' AND state IN ('queued','running')").fetchone()
        if active: return {'job_id':active['id'], 'duplicate':True}
        payload = body.model_dump(exclude={'resume_job_id'})
        if body.resume_job_id:
            previous = c.execute("SELECT * FROM jobs WHERE id=? AND kind='x_sync'", (body.resume_job_id,)).fetchone()
            if not previous: raise ValueError('没有找到可继续的同步任务')
            progress = json.loads(previous['progress'])
            if progress.get('complete'): raise ValueError('此任务已读到当前书签末尾，请从最新书签开始')
            old = json.loads(previous['payload'])
            payload.update(cursor=old.get('cursor'), account_id=old.get('account_id'))
        jid = store.enqueue(c, 'x_sync', payload)
    return {'job_id':jid, 'duplicate':False}

@app.get('/api/x/status')
def x_status():
    cfg = store.settings()
    with store.db() as c:
        row = c.execute("SELECT id,state,error,progress FROM jobs WHERE kind='x_sync' ORDER BY created DESC LIMIT 1").fetchone()
    last = dict(row) if row else None
    if last: last['progress'] = json.loads(last['progress'])
    return {'configured':bool(cfg.get('cookies',{}).get('x')), 'account':cfg.get('x_account'), 'last_sync':last}

class ObsidianInput(BaseModel):
    vault: str = Field(max_length=4000)
    paths: dict[str,str] | None=None
    targets: list[str] | None=Field(default=None,max_length=30)

@app.put('/api/obsidian')
def obsidian_config(body: ObsidianInput):
    from pathlib import Path
    raw=body.vault.strip()
    if raw and not Path(raw).is_absolute():raise ValueError('知识库根目录请填写绝对路径')
    path = Path(raw or store.DATA/'knowledge-base').resolve()
    if not raw:path.mkdir(parents=True,exist_ok=True)
    if not path.is_dir(): raise ValueError('所选知识库目录不存在或不可访问')
    cfg = store.settings()
    values=obsidian.validate_paths({**obsidian.paths(),**(body.paths or {})},path)
    if body.targets is not None:
        from .vault_files import checked
        targets=[]
        for target in body.targets:
            value=target.strip().replace('\\','/')
            if not value or len(value)>400:raise ValueError('二级常用目录请填写知识库内的相对路径')
            checked(str(path),value)
            if value not in targets:targets.append(value)
        cfg['knowledge_targets']=targets
    cfg['obsidian_vault']=str(path);cfg['knowledge_paths']=values;store.save_settings(cfg)
    return {'vault':str(path),'paths':values,'targets':cfg.get('knowledge_targets',[]),
            'notice':'路径已保存；已有材料保持原位，后续写入仍需预览确认'}

@app.get('/api/events')
def events():
    with store.db() as c:
        return [dict(r) for r in c.execute('SELECT * FROM events ORDER BY id DESC LIMIT 300')]

@app.get('/api/settings')
def settings():
    cfg = store.settings()
    return {'ai_base_url': cfg.get('ai_base_url', 'https://api.openai.com/v1'), 'ai_model': cfg.get('ai_model', ''),
            'ai_configured': bool(cfg.get('ai_api_key')), 'cookies': list(cfg.get('cookies', {})),
            'whisper_model': cfg.get('whisper_model', 'turbo'), 'obsidian_vault':obsidian.root(),
            'knowledge_paths':obsidian.paths(),'knowledge_targets':cfg.get('knowledge_targets',[])}

class SettingsInput(BaseModel):
    ai_base_url: str
    ai_model: str = ''
    ai_api_key: str = ''
    whisper_model: Literal['tiny', 'base', 'small', 'medium', 'large-v3', 'turbo'] = 'turbo'

@app.put('/api/settings')
def update_settings(body: SettingsInput):
    p = urlparse(body.ai_base_url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError('AI 地址必须是无凭据的 http/https API 根地址')
    cfg = store.settings()
    values = body.model_dump()
    if not values['ai_api_key']:
        values.pop('ai_api_key')
    cfg.update(values)
    store.save_settings(cfg)
    return settings()

class CookieInput(BaseModel):
    platform: Literal['bilibili', 'youtube', 'douyin', 'x', 'heybox', 'xiaohongshu']
    text: str = Field(max_length=1_000_000)

@app.put('/api/cookies')
def cookies(body: CookieInput):
    cfg = store.settings()
    folder = store.DATA / 'credentials'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (body.platform + '.txt')
    if not body.text.strip():
        path.unlink(missing_ok=True)
        cfg.setdefault('cookies', {}).pop(body.platform, None)
    else:
        if body.platform == 'x' and body.text.lstrip().startswith(('[', '{')):
            value = json.loads(body.text)
            if isinstance(value, list):
                for entry in value:
                    if entry.get('domain', '').lstrip('.') not in ('x.com','twitter.com'):
                        raise ValueError('只接受从 X 网站导出的 Cookie，不能混入其他网站')
                value = {entry['name']:entry['value'] for entry in value}
            if not isinstance(value, dict) or not value.get('auth_token') or not value.get('ct0'):
                raise ValueError('X 登录信息缺少 auth_token 或 ct0')
            path = folder / 'x.json'
            path.write_text(store.dumps({k:str(value[k]) for k in ('auth_token','ct0')}), 'utf-8')
            cfg.setdefault('cookies', {})['x'] = str(path.relative_to(store.ROOT))
            cfg.pop('x_account', None)
            store.save_settings(cfg)
            return {'saved':True}
        if not body.text.startswith(('# Netscape HTTP Cookie File', '# HTTP Cookie File')):
            raise ValueError('需要 Netscape 格式 Cookie 文件内容')
        allowed = adapters.PLATFORMS[body.platform][1]
        for line in body.text.splitlines():
            if not line.strip() or (line.startswith('#') and not line.startswith('#HttpOnly_')):
                continue
            domain = line.split('\t')[0].removeprefix('#HttpOnly_').lstrip('.')
            if not any(domain == h or domain.endswith('.' + h) for h in allowed):
                raise ValueError('Cookie 文件含其他网站登录信息；请只导出所选平台')
        path.write_text(body.text, 'utf-8')
        cfg.setdefault('cookies', {})[body.platform] = str(path.relative_to(store.ROOT))
    if body.platform == 'x':
        cfg.pop('x_account', None)
        if not body.text.strip():
            (folder/'x.json').unlink(missing_ok=True)
            (folder/'x.ytdlp.txt').unlink(missing_ok=True)
    store.save_settings(cfg)
    return {'saved': bool(body.text.strip())}

@app.get('/')
def home():
    return FileResponse(store.ROOT / 'web' / 'index.html')

app.mount('/static', StaticFiles(directory=store.ROOT / 'web'), name='static')
