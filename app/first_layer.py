"""Independent annotated records backed by confirmed, immutable source snapshots."""
from __future__ import annotations
import json,re
from pathlib import Path
from urllib.parse import quote
from . import knowledge,obsidian,store,topics

FOLDERS={'callable':'收藏材料库/01_调用资料','digest':'收藏材料库/02_消化暂存'}
LABELS={'callable':'调用资料','digest':'消化暂存'}
def folders():
    return {k:obsidian.paths()[k] for k in FOLDERS}
CONTENT_KEYS={'source','source_url','resolved_url','warning','language','subtitle_source','segments','transcript_state',
              'transcription','subtitle_tracks','media','comments','comments_status','thread_status','duration',
              'original_text_complete','reader_translation','knowledge_context','annotation_kind'}

def snapshot(item):
    return {**{k:item[k] for k in ('id','platform','url','origin','title','body','collection','error','created','topic','topic_source','topic_detail')},
            'content':{k:v for k,v in item['content'].items() if k in CONTENT_KEYS}}

def fingerprint(item,track):
    return store.digest(store.dumps({'source':snapshot(item),'track':track,'annotation':item['notes'],
                                    'vault':str(obsidian.configuration()),'folder':folders()[track]}))

def existing_preview(item,track):
    key=fingerprint(item,track)
    with store.db() as c:
        row=c.execute("SELECT p.* FROM first_layers f JOIN pushes p ON p.id=f.source_push_id WHERE f.source_material_id=? AND f.track=? AND f.fingerprint=? AND f.active=1 AND f.trashed='' AND p.state='confirmed'",
                      (item['id'],track,key)).fetchone()
    if not row:return None
    from . import vault_files
    p=json.loads(row['payload'])
    with store.db() as c:location=vault_files.current(c,row['id'])
    destination=str(Path(location['vault'])/location['note']) if location and location['state']=='live' else p['shelf_output']['path']
    if not Path(destination).is_file():return None
    return {'id':row['id'],'hash':row['hash'],'markdown':p['markdown'],'payload':p,'destination':destination,
            'shelf_markdown':p['shelf_output']['markdown'],'source_destination':p['obsidian']['path'],'duplicate':True}

def outcome(item,pid,track,archive,manifest):
    if track not in FOLDERS:raise ValueError('请选择调用资料或消化暂存')
    if item['id'].startswith('l1_'):raise ValueError('第一层材料请继续加工，不重复分流为新的原始收藏')
    if not item['notes'].strip():raise ValueError('请先写这条路线的批注')
    folder=folders()[track]
    title=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',item['title']).strip(' .')[:70] or '材料'
    note=folder+'/'+title+'--'+pid+'/index.md';path=knowledge.checked(note)
    original=store.markdown(item,include_processing=False)
    for asset in manifest:
        target=asset['target']
        original=original.replace(']('+asset['source']+')',']('+quote(target,safe='/')+')')
    text='\n'.join(['---','type: first-layer-material','track: '+track,'human_digest: false',
          'source_material_id: '+item['id'],'source_url: '+store.dumps(item['url']),'---','',
          '## '+('调用批注' if track=='callable' else '消化线索'),'',item['notes'],'',original,'',
          '## 原始来源','','- 原链接：'+item['url'],''])
    return {'vault':archive['vault'],'note':note,'path':str(path),'stage':track,'folder':folder,'markdown':text,
            'related_notes':[],'source_note':note,'title':item['title'],'overview':item['notes'],
            'annotation':item['notes'],'topic':item['topic'],'source_url':item['url'],
            'fingerprint':fingerprint(item,track),'source_snapshot':snapshot(item),'config_paths':obsidian.paths()}

def register(c,pid,value):
    stamp=store.now();source=value['source_snapshot'];track=value['stage']
    old=c.execute("SELECT id FROM first_layers WHERE source_material_id=? AND track=? AND active=1",(source['id'],track)).fetchall()
    for row in old:
        c.execute('UPDATE first_layers SET active=0,revision=revision+1 WHERE id=?',(row['id'],))
        store.event(c,row['id'],'first_layer_superseded',{'new_source_push_id':pid})
    mid='l1_'+store.uid();content=dict(source['content']);body=source['body']
    payload=json.loads(c.execute('SELECT payload FROM pushes WHERE id=?',(pid,)).fetchone()[0])
    images={a['source']:a['target'] for a in payload['assets']}
    for old_path,new_path in images.items():body=body.replace(']('+old_path+')',']('+new_path+')')
    content['media']=[{**a,'path':images.get(a.get('path'),a.get('path'))} for a in content.get('media',[])]
    comments=[]
    for comment in content.get('comments',[]):
        text=comment.get('body','')
        for old_path,new_path in images.items():text=text.replace(']('+old_path+')',']('+new_path+')')
        comments.append({**comment,'body':text})
    content['comments']=comments
    content['first_layer_context']={**{k:value[k] for k in ('vault','path','note','source_note')},'track':track,'source_material_id':source['id'],'source_push_id':pid,'annotation':value['annotation']}
    c.execute('''INSERT INTO first_layers(id,source_material_id,source_push_id,track,fingerprint,platform,url,origin,title,
          body,notes,content_json,collection,error,topic,topic_source,topic_detail,created,updated)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
          (mid,source['id'],pid,track,value['fingerprint'],source['platform'],source['url'],source['origin'],source['title'],
           body,value['annotation'],store.dumps(content),source['collection'],source['error'],source['topic'],source['topic_source'],
           store.dumps(source['topic_detail']),stamp,stamp))
    store.event(c,mid,'first_layer_saved',{'track':track,'source_material_id':source['id'],'path':value['path']})
    return mid

def media_root(mid):
    with store.db() as c:row=c.execute('SELECT source_push_id FROM first_layers WHERE id=?',(mid,)).fetchone()
    if not row or not re.fullmatch(r'[A-Za-z0-9_-]+',row[0]):raise ValueError('第一层附件不存在')
    base=store.DATA/'outbox'/'obsidian';path=base/row[0]
    if not path.resolve().is_relative_to(store.DATA.resolve()):raise ValueError('第一层附件目录越界')
    for ancestor in (store.DATA,store.DATA/'outbox',base,path):
        if ancestor.is_symlink() or (ancestor.exists() and getattr(ancestor.lstat(),'st_file_attributes',0)&0x400):raise ValueError('第一层附件包含链接')
    return path

def catalogue(track,params,state='all'):
    if track not in LABELS:raise ValueError('未知第一层材料库')
    clauses=['track=?','active=1',"trashed<>''" if state=='trash' else "trashed=''"];args=[track]
    for key in ('origin','platform','topic'):
        if params.get(key):clauses.append(key+'=?');args.append(params[key])
    if state in ('pending','later','review','done'):clauses.append('processing=?');args.append(state)
    if params.get('q'):clauses.append('(title LIKE ? OR body LIKE ? OR notes LIKE ? OR summary LIKE ?)');args+=['%'+params['q']+'%']*4
    with store.db() as c:
        rows=c.execute('SELECT * FROM first_layers WHERE '+' AND '.join(clauses)+' ORDER BY updated DESC',args).fetchall()
    items=[]
    for row in rows:
        item=store.unpack(row);item['excerpt']=item['notes'][:240];item.pop('body');item.pop('summary')
        item['thumbnail']=next((a['path'] for a in item['content'].get('media',[]) if a.get('status')=='saved'),None)
        item['transcript_state']=store.transcript_status(item['platform'],item['collection'],item['content']);item.pop('content')
        items.append(item)
    topic_clauses=[];topic_args=[]
    for clause in clauses:
        if clause!='topic=?':topic_clauses.append(clause)
    # Keep topic counts contextual while ignoring the selected topic itself.
    topic_args=[track]+[params[k] for k in ('origin','platform') if params.get(k)]
    if state in ('pending','later','review','done'):topic_args.append(state)
    if params.get('q'):topic_args+=['%'+params['q']+'%']*4
    with store.db() as c:counts=dict(c.execute('SELECT topic,count(*) FROM first_layers WHERE '+' AND '.join(topic_clauses)+' GROUP BY topic',topic_args).fetchall())
    return {'items':items,'topics':[{'id':k,'label':v,'count':counts.get(k,0)} for k,v in topics.LABELS.items()]}
