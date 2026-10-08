"""Read-only global task activity, independent of the visible library filter."""
import json
from . import store

LIVE=('queued','running')
KINDS={'collect':'收集正文','images':'保存图片','favorites':'读取收藏','sync':'读取列表','x_sync':'读取X收藏','x_check':'检查X登录','subtitle_tracks':'读取双语字幕','bilingual':'翻译','ai':'按批注整理','overview':'生成概要'}
STAGES={'audio':'获取音频','model':'加载转写模型','transcribing':'转写字幕','saving':'保存内容','subtitles':'读取字幕','generating':'生成概要'}
RANKED="""WITH ranked AS (
 SELECT j.*,row_number() OVER (
 PARTITION BY coalesce(material_id,''),kind,
 CASE WHEN material_id IS NULL THEN coalesce(json_extract(payload,'$.platform'),'')||'|'||coalesce(json_extract(payload,'$.url'),'') ELSE '' END
 ORDER BY created DESC,rowid DESC) AS position FROM jobs j)
"""

def stopped(row):return row['state']=='cancelled' or row['state']=='failed' and row['error'].startswith('用户停止')

def item(row):
    value=dict(row);payload=json.loads(value.pop('payload'));value.pop('position',None)
    progress=json.loads(value['progress']);value['progress']=progress if isinstance(progress,dict) else {}
    value['platform']=value.get('platform') or payload.get('platform','')
    value['title']=value.get('title') or KINDS.get(value['kind'],'后台任务')
    value['label']=STAGES.get(value['progress'].get('stage'),KINDS.get(value['kind'],'后台任务'))
    state=value['state']
    if stopped(value):value['status_label']='已停止'
    elif state=='done':
        if value['kind']=='favorites':value['status_label']='清单读完' if value['progress'].get('complete') else '本批结束，未确认末尾'
        elif value['kind']=='collect':value['status_label']='收集完整' if value.get('collection')=='ready' else '本次结束，内容需核对'
        else:value['status_label']='已结束'
    else:value['status_label']={'running':'进行中','queued':'等待中','paused':'已暂停','failed':'失败'}.get(state,state)
    return value

def snapshot(limit=40):
    with store.db() as c:
        c.execute('BEGIN')
        counts={state:c.execute('SELECT count(*) FROM jobs WHERE state=?',(state,)).fetchone()[0] for state in LIVE}
        # A successful later retry resolves an earlier failed attempt, without deleting history.
        counts['attention']=c.execute(RANKED+"SELECT count(*) FROM ranked WHERE position=1 AND state IN ('failed','paused') AND error NOT LIKE '用户停止%' ").fetchone()[0]
        groups=[dict(row) for row in c.execute("SELECT kind,state,count(*) AS count FROM jobs WHERE state IN ('queued','running') GROUP BY kind,state ORDER BY state,kind")]
        columns="r.*,coalesce(m.title,f.title,'') AS title,coalesce(m.platform,f.platform,'') AS platform,coalesce(m.collection,f.collection,'') AS collection"
        join=" FROM ranked r LEFT JOIN materials m ON m.id=r.material_id LEFT JOIN first_layers f ON f.id=r.material_id "
        active=[item(row) for row in c.execute(RANKED+'SELECT '+columns+join+"WHERE r.state IN ('running','queued') ORDER BY CASE r.state WHEN 'running' THEN 0 ELSE 1 END,r.created LIMIT ?",(limit,))]
        attention=[item(row) for row in c.execute(RANKED+'SELECT '+columns+join+"WHERE r.position=1 AND r.state IN ('failed','paused') AND r.error NOT LIKE '用户停止%' ORDER BY r.updated DESC LIMIT ?",(limit,))]
        recent=[item(row) for row in c.execute(RANKED+'SELECT '+columns+join+"WHERE r.state NOT IN ('queued','running') ORDER BY r.updated DESC,r.created DESC LIMIT ?",(limit,))]
    return {'counts':counts,'groups':groups,'active':active,'attention':attention,'recent':recent,'limit':limit,'checked_at':store.now()}
