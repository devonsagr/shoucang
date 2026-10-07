from __future__ import annotations
import contextlib
import hashlib
import json
import re
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'

def now():
    return datetime.now(timezone.utc).isoformat()

def uid():
    return uuid.uuid4().hex

def dumps(value):
    return json.dumps(value, ensure_ascii=False)

def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()

def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()

@contextlib.contextmanager
def db():
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATA / 'library.sqlite3', timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

def init():
    if not settings().get('obsidian_vault'):
        (DATA/'knowledge-base').mkdir(parents=True,exist_ok=True)
    with db() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS materials (
          id TEXT PRIMARY KEY, canonical TEXT UNIQUE NOT NULL, url TEXT NOT NULL,
          platform TEXT NOT NULL, origin TEXT NOT NULL, title TEXT NOT NULL,
          collection TEXT NOT NULL DEFAULT 'queued', processing TEXT NOT NULL DEFAULT 'pending',
          body TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
          content_json TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '',
          revision INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, material_id TEXT, kind TEXT NOT NULL,
          detail TEXT NOT NULL, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS versions (
          id INTEGER PRIMARY KEY AUTOINCREMENT, material_id TEXT NOT NULL,
          content_json TEXT NOT NULL, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, material_id TEXT, kind TEXT NOT NULL, payload TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'queued', error TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS pushes (
          id TEXT PRIMARY KEY, material_id TEXT NOT NULL, revision INTEGER NOT NULL,
          destination TEXT NOT NULL, markdown TEXT NOT NULL, payload TEXT NOT NULL,
          hash TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'preview', created TEXT NOT NULL, confirmed TEXT);
        CREATE TABLE IF NOT EXISTS first_layers (
          id TEXT PRIMARY KEY,source_material_id TEXT NOT NULL,source_push_id TEXT UNIQUE NOT NULL,
          track TEXT NOT NULL,fingerprint TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,
          platform TEXT NOT NULL,url TEXT NOT NULL,origin TEXT NOT NULL,title TEXT NOT NULL,
          body TEXT NOT NULL,notes TEXT NOT NULL,summary TEXT NOT NULL DEFAULT '',content_json TEXT NOT NULL,
          collection TEXT NOT NULL,error TEXT NOT NULL DEFAULT '',processing TEXT NOT NULL DEFAULT 'pending',
          topic TEXT NOT NULL,topic_source TEXT NOT NULL,topic_detail TEXT NOT NULL,
          revision INTEGER NOT NULL DEFAULT 1,trashed TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,updated TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS first_layers_current ON first_layers(source_material_id,track) WHERE active=1;
        CREATE TABLE IF NOT EXISTS vault_exports (
          id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,vault TEXT NOT NULL,note TEXT NOT NULL,
          files_json TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'live',restore_json TEXT NOT NULL DEFAULT '{}',
          replacement_id TEXT NOT NULL DEFAULT '',updated TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS vault_exports_owner ON vault_exports(owner_id);
        CREATE TABLE IF NOT EXISTS retired_sources (
          identity TEXT PRIMARY KEY,material_id TEXT NOT NULL,platform TEXT NOT NULL,retired_at TEXT NOT NULL);
        ''')
        if 'progress' not in {r['name'] for r in c.execute('PRAGMA table_info(jobs)')}:
            c.execute("ALTER TABLE jobs ADD COLUMN progress TEXT NOT NULL DEFAULT '{}'")
        if 'trashed' not in {r['name'] for r in c.execute('PRAGMA table_info(materials)')}:
            c.execute("ALTER TABLE materials ADD COLUMN trashed TEXT NOT NULL DEFAULT ''")
        columns = {r['name'] for r in c.execute('PRAGMA table_info(materials)')}
        for name, default in [('topic', 'uncategorized'), ('topic_source', 'unclassified'), ('topic_detail', '{}')]:
            if name not in columns:
                c.execute(f"ALTER TABLE materials ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'")
        c.execute('CREATE INDEX IF NOT EXISTS materials_topic ON materials(topic)')
        # Interrupted operations are explicitly retried; a committed job is never lost.
        c.execute("UPDATE jobs SET state='queued',error='进程中断，已恢复排队' WHERE state='running'")
        c.execute("UPDATE materials SET collection='queued' WHERE collection='running'")
    organize_material_files()
    from . import vault_files
    vault_files.recover()
    recover_deleted_identities()

def remember_deleted(c,mid,url,platform,retired_at=None):
    from . import adapters
    identity=digest(adapters.canonical(url))
    c.execute('INSERT INTO retired_sources VALUES (?,?,?,?) ON CONFLICT(identity) DO UPDATE SET material_id=excluded.material_id,platform=excluded.platform,retired_at=excluded.retired_at WHERE excluded.retired_at>retired_sources.retired_at',(identity,mid,platform,retired_at or now()))
    return identity

def recover_deleted_identities():
    """Recover only purged IDs from local receipts/backups; retain no deleted content."""
    from . import adapters
    with db() as c:
        before=c.execute('SELECT COUNT(*) FROM retired_sources').fetchone()[0]
        known={r[0] for r in c.execute('SELECT material_id FROM retired_sources')}
        live={r[0] for r in c.execute('SELECT id FROM materials')}
        events=c.execute("SELECT detail,created FROM events WHERE kind='material_purged'").fetchall()
        missing={}
        for row in events:
            value=json.loads(row['detail']);mid=value.get('id','')
            if not re.fullmatch(r'[a-f0-9]{32}',mid) or mid in known or mid in live:continue
            if re.fullmatch(r'[a-f0-9]{64}',value.get('source_identity','')):
                c.execute('INSERT OR IGNORE INTO retired_sources VALUES (?,?,?,?)',(value['source_identity'],mid,value.get('platform','web'),row['created']))
                known.add(mid)
            else:missing[mid]=row['created']
        for mid in list(missing):
            receipts=c.execute("SELECT payload FROM pushes WHERE material_id=? AND state='confirmed' ORDER BY created DESC",(mid,)).fetchall()
            for row in receipts:
                url=json.loads(row['payload']).get('source_url')
                if url:
                    remember_deleted(c,mid,url,adapters.platform(url),missing.pop(mid));break
    root=DATA/'backups'
    if missing and root.exists() and not root.is_symlink() and root.resolve().is_relative_to(DATA.resolve()):
        for backup in sorted(root.glob('*.sqlite3'),reverse=True):
            if not missing:break
            if backup.is_symlink() or not backup.resolve().is_relative_to(root.resolve()):continue
            try:
                with contextlib.closing(sqlite3.connect('file:'+backup.as_posix()+'?mode=ro',uri=True)) as old:
                    ids=list(missing)
                    rows=old.execute('SELECT id,url,platform FROM materials WHERE id IN ('+','.join('?' for _ in ids)+')',ids).fetchall()
                with db() as c:
                    for mid,url,platform in rows:remember_deleted(c,mid,url,platform,missing.pop(mid))
            except (sqlite3.Error,ValueError,OSError):continue
    with db() as c:after=c.execute('SELECT COUNT(*) FROM retired_sources').fetchone()[0]
    result={'recovered':after-before,'unresolved':len(missing)}
    if result['recovered']:
        with db() as c:event(c,None,'deleted_identities_recovered',result)
    return result

def material_folder(mid, platform=None):
    """A stable platform/material directory; accept old directories during migration."""
    if not re.fullmatch(r'[A-Za-z0-9_-]+', mid):
        raise ValueError('材料目录 ID 无效')
    if mid.startswith('l1_'):
        with db() as c:row=c.execute('SELECT track FROM first_layers WHERE id=?',(mid,)).fetchone()
        if not row or row[0] not in ('callable','digest'):raise ValueError('第一层材料不存在')
        target=DATA/'layers'/row[0]/mid
        for path in (DATA,DATA/'layers',target.parent,target):
            if path.is_symlink() or (path.exists() and getattr(path.lstat(),'st_file_attributes',0)&0x400):raise ValueError('第一层目录包含链接')
        return target
    if platform is None:
        with db() as c:
            row = c.execute('SELECT platform FROM materials WHERE id=?', (mid,)).fetchone()
        platform = row['platform'] if row else 'web'
    if platform not in ('x','bilibili','youtube','douyin','heybox','xiaohongshu','web'):
        raise ValueError('材料平台无效')
    base = DATA / 'materials'
    legacy, target = base / mid, base / platform / mid
    for path in (legacy, target):
        if not path.resolve().is_relative_to(DATA.resolve()):
            raise ValueError('材料目录超出本项目数据目录')
    return legacy if legacy.exists() else target

def organize_material_files():
    """Move known legacy directories before workers start; preserve relative asset paths."""
    with db() as c:
        rows = c.execute('SELECT id,platform FROM materials').fetchall()
    for row in rows:
        legacy = DATA / 'materials' / row['id']
        checked = material_folder(row['id'], row['platform'])
        if checked != legacy or not legacy.exists():
            continue
        target = DATA / 'materials' / row['platform'] / row['id']
        if target.exists():
            raise ValueError('材料的新旧目录同时存在，停止迁移以保留文件')
        target.parent.mkdir(parents=True, exist_ok=True)
        legacy.rename(target)

def event(c, material_id, kind, detail):
    c.execute('INSERT INTO events(material_id,kind,detail,created) VALUES (?,?,?,?)',
              (material_id, kind, dumps(detail), now()))

def table_for(mid):
    return 'first_layers' if mid.startswith('l1_') else 'materials'

def unpack(row):
    value = dict(row)
    value['content'] = json.loads(value.pop('content_json'))
    value['topic_detail'] = json.loads(value.get('topic_detail') or '{}')
    if value['id'].startswith('l1_'):
        value['first_layer']={'track':value['track'],'source_material_id':value['source_material_id'],
                              'source_push_id':value['source_push_id'],'level':value['content'].get('current_export',{}).get('level',1),
                              'path':value['content'].get('current_export',{}).get('path') or value['content'].get('first_layer_context',{}).get('path'),'archived':not bool(value['active'])}
    return value

def get(mid):
    with db() as c:
        r = c.execute('SELECT * FROM '+table_for(mid)+' WHERE id=?', (mid,)).fetchone()
    if not r:
        raise ValueError('材料不存在')
    return unpack(r)

def enqueue(c, kind, payload, mid=None, *, exclude_job=None):
    if mid:
        row = c.execute('SELECT trashed FROM '+table_for(mid)+' WHERE id=?', (mid,)).fetchone()
        if row and row['trashed']: raise ValueError('材料已删除，请先从回收站恢复')
        active = c.execute("SELECT id FROM jobs WHERE material_id=? AND kind=? AND state IN ('queued','running') AND id<>?", (mid, kind,exclude_job or '')).fetchone()
        if active:
            return active['id']
    jid = uid()
    c.execute('INSERT INTO jobs(id,material_id,kind,payload,created,updated) VALUES (?,?,?,?,?,?)',
              (jid, mid, kind, dumps(payload), now(), now()))
    event(c, mid, 'job_queued', {'id': jid, 'kind': kind})
    return jid

def settings():
    path = ROOT / 'config.json'
    return json.loads(path.read_text('utf-8')) if path.exists() else {}

def save_settings(value):
    path = ROOT / 'config.json'
    tmp = path.with_suffix('.tmp')
    tmp.write_text(dumps(value), 'utf-8')
    tmp.replace(path)

def available(mid):
    item = get(mid)
    if item.get('trashed'): raise ValueError('材料已删除，请先从回收站恢复')
    if mid.startswith('l1_') and not item['active']:raise ValueError('这是第一层材料的旧版本，请打开当前版本继续处理')
    return item

def transcript_status(platform, collection, content):
    if content.get('transcript_state')=='uncertain': return 'uncertain'
    if content.get('segments'):
        return 'machine' if content.get('transcription') or '机器转写' in content.get('subtitle_source','') else 'platform'
    if platform not in ('bilibili','youtube','douyin'): return 'text'
    if content.get('transcript_state'): return content['transcript_state']
    if collection in ('queued','running','paused'): return collection
    if collection == 'failed': return 'unavailable'
    # Older partial records did not record an attempted transcription reliably.
    return 'missing'

def trash(mid, restore=False, revision=None):
    from . import vault_files
    with vault_files.Change() as file_change,db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT trashed,revision FROM '+table_for(mid)+' WHERE id=?',(mid,)).fetchone()
        if not row: raise ValueError('材料不存在')
        if revision is not None and row['revision'] != revision:
            raise ValueError('材料已改变，请重新勾选后重试')
        changed = bool(row['trashed']) if restore else not bool(row['trashed'])
        if changed:
            moved=vault_files.recycle(c,mid,restore,file_change)
            c.execute('UPDATE '+table_for(mid)+' SET trashed=?,revision=revision+1,updated=? WHERE id=?',
                      ('' if restore else now(),now(),mid))
            if not restore:
                c.execute("UPDATE jobs SET state='cancelled',error='材料已移入回收站',updated=? WHERE material_id=? AND state IN ('queued','paused')", (now(),mid))
                c.execute("UPDATE "+table_for(mid)+" SET collection='paused' WHERE id=? AND collection IN ('queued','running')",(mid,))
            event(c,mid,'material_restored' if restore else 'material_trashed',{'originals_retained':True,'vault_bundles_moved':moved})
    archive(mid)
    return get(mid)

def timestamp(seconds):
    ms = round(float(seconds) * 1000)
    return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}'

def purge(mid, revision, confirmation):
    """Remove one trashed record and its owned Vault files; other records stay intact."""
    if confirmation != '彻底删除': raise ValueError('请明确确认彻底删除')
    from . import vault_files
    with vault_files.Change() as file_change,db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM '+table_for(mid)+' WHERE id=?', (mid,)).fetchone()
        if not row: raise ValueError('材料不存在')
        if not row['trashed']: raise ValueError('只能彻底删除回收站里的材料')
        if row['revision'] != revision: raise ValueError('材料已改变，请重新查看后确认')
        if c.execute("SELECT 1 FROM jobs WHERE material_id=? AND state='running'", (mid,)).fetchone():
            raise ValueError('该材料的后台任务还在结束中，请稍后再确认彻底删除')
        folder = material_folder(mid, row['platform'])
        base = DATA / ('layers' if mid.startswith('l1_') else 'materials')
        if not folder.resolve().is_relative_to(base.resolve()):
            raise ValueError('材料目录越界，已停止删除')
        # A junction at the root could otherwise redirect deletion to another local folder.
        for path in (DATA, base, folder.parent, folder):
            if path.is_symlink() or (path.exists() and getattr(path.lstat(), 'st_file_attributes', 0) & 0x400):
                raise ValueError('材料目录包含链接，已停止删除')
        review_root=DATA/'review';review_file=review_root/(mid+'.md')
        if review_file.resolve().parent!=review_root.resolve() or not review_root.resolve().is_relative_to(DATA.resolve()):
            raise ValueError('待审文件越界，停止删除')
        for path in (review_root,review_file):
            if path.is_symlink() or (path.exists() and getattr(path.lstat(),'st_file_attributes',0)&0x400):
                raise ValueError('待审文件包含链接，停止删除')
        removed_bundles=vault_files.purge(c,mid,file_change)
        local_files=[folder,review_file]
        cache_ids={r[0] for r in c.execute("SELECT id FROM pushes WHERE material_id=? AND destination='obsidian'",(mid,))}
        if mid.startswith('l1_'):cache_ids.add(row['source_push_id'])
        for pid in cache_ids:
            if not re.fullmatch(r'[a-f0-9]{32}',pid):raise ValueError('本机附件缓存ID无效')
            if c.execute('SELECT 1 FROM first_layers WHERE source_push_id=? AND id<>?',(pid,mid)).fetchone():continue
            local_files.append(DATA/'outbox'/'obsidian'/pid)
        file_change.stash_local(c,local_files)
        for table in ('versions', 'events', 'jobs'):
            c.execute(f'DELETE FROM {table} WHERE material_id=?', (mid,))
        c.execute("DELETE FROM pushes WHERE material_id=? AND state<>'confirmed'", (mid,))
        c.execute('DELETE FROM '+table_for(mid)+' WHERE id=?', (mid,))
        identity=remember_deleted(c,mid,row['url'],row['platform']) if not mid.startswith('l1_') else None
        event(c, None, 'material_purged', {'id':mid,'source_identity':identity,'platform':row['platform'],'vault_bundles_deleted':removed_bundles,'other_records_retained':True})
    return {'id':mid, 'purged':True, 'vault_bundles_deleted':removed_bundles,'other_records_retained':True}

def batch_materials(action, items, confirmation=None):
    """Freeze explicit targets; commit each existing file/DB operation independently."""
    if action not in ('trash','restore','purge','retry'):raise ValueError('未知批量操作')
    if not 1 <= len(items) <= 100:raise ValueError('每次请求需包含1到100条材料')
    ids=[item['id'] for item in items]
    if len(set(ids)) != len(ids):raise ValueError('同一批次不能重复选择材料')
    if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',item['id']) or item['revision'] < 1 for item in items):
        raise ValueError('材料ID或版本无效')
    if action=='purge' and confirmation!='彻底删除':raise ValueError('请明确确认彻底删除')
    batch_id=uid()
    with db() as c:event(c,None,'material_batch_started',{'batch_id':batch_id,'action':action,'items':items})
    results=[]
    for item in items:
        mid=item['id'];attempt_started=now()
        try:
            if action=='retry':
                from .service import retry_capture
                result=retry_capture(mid,revision=item['revision'])
                results.append({'id':mid,'ok':True,**result});continue
            result=purge(mid,item['revision'],confirmation) if action=='purge' else trash(mid,restore=action=='restore',revision=item['revision'])
            results.append({'id':mid,'ok':True,**({'purged':True} if action=='purge' else {'revision':result['revision'],'trashed':bool(result['trashed'])})})
        except Exception as exc:
            # Projection/journal cleanup happens after commit. Report that outcome honestly.
            committed=False
            try:
                with db() as c:
                    kind={'trash':'material_trashed','restore':'material_restored','purge':'material_purged'}.get(action,'capture_retry_requested')
                    proof=c.execute("SELECT 1 FROM events WHERE kind=? AND created>=? AND (material_id=? OR json_extract(detail,'$.id')=?) LIMIT 1",(kind,attempt_started,mid,mid)).fetchone()
                    row=c.execute('SELECT revision,trashed FROM '+table_for(mid)+' WHERE id=?',(mid,)).fetchone()
                    committed=bool(proof and (not row if action=='purge' else row and row['revision']>item['revision'] and bool(row['trashed'])==(action=='trash')))
            except sqlite3.Error:pass
            if committed:
                saved={'purged':True} if action=='purge' else {'revision':row['revision'],'trashed':bool(row['trashed'])}
                results.append({'id':mid,'ok':True,**saved,'warning':'状态已保存，但本机存档或清理未完成，请核对文件操作记录'})
                continue
            if isinstance(exc,ValueError):message=str(exc)
            elif isinstance(exc,OSError):message='文件读写失败，请确认目录可用后重试'
            elif isinstance(exc,sqlite3.Error):message='本机存储暂时不可写，请稍后重试'
            else:
                import logging
                logging.getLogger(__name__).exception('Batch %s failed for material %s',batch_id,mid)
                message='本条处理失败，请重试'
            results.append({'id':mid,'ok':False,'error':message})
    succeeded=sum(r['ok'] for r in results)
    with db() as c:event(c,None,'material_batch_completed',{'batch_id':batch_id,'action':action,'results':results})
    return {'batch_id':batch_id,'action':action,'total':len(items),'succeeded':succeeded,'failed':len(items)-succeeded,'warnings':sum(bool(r.get('warning')) for r in results),'results':results}

def markdown(item,include_processing=True):
    from . import topics
    content = item.get('content', {})
    lines = [f'# {item["title"]}', '', f'- 来源：{item["platform"]}',
             f'- 原链接：{item["url"]}', f'- 材料 ID：{item["id"]}',
             f'- 收集类型：{"收藏" if item["origin"] == "favorite" else "明确提供的非收藏链接"}',
             f'- 收集时间：{item["created"]}', f'- 内容状态：{item["collection"]}',
             f'- 处理状态：'+{'pending':'待处理','later':'稍后整理（暂存，尚未处理完成）','review':'整理待审','done':'已完成'}.get(item.get('processing','pending'),'待处理'),
             f'- 内容主题：{topics.LABELS.get(item.get("topic"), "未分类")}（'+('手动分类' if item.get('topic_source')=='manual' else '本机规则粗分，可改类')+'）',
             f'- 原文获取方式：{content.get("source", "尚未获取")}',
             f'- 字幕来源：{content.get("subtitle_source", "无字幕")}',
             f'- 字幕语言：{content.get("language", "未指定")}', '',
             '> 视频字幕是语音文字记录，不包含画面信息；自动字幕和机器转写可能有误。' if content.get('segments') else '',
             f'> {content["warning"]}' if content.get('warning') else '', '', '## 原文 / 视频说明', '', item['body'] or '（尚未取得原文）']
    if content.get('segments'):
        lines += ['', '## 逐段字幕', '']
        for s in content['segments']:
            lines.append(f'[{timestamp(s["start"])} → {timestamp(s["end"])}] {s["text"]}')
    for track in content.get('subtitle_tracks', []):
        lines += ['', f'## 第二语言字幕 · {track.get("language", "未指定")}', '',
                  f'- 字幕来源：{track.get("source", "来源未声明")}',
                  '- 各语言分别保留完整时间轴；界面按时间重叠显示对应句。', '']
        for s in track.get('segments', []):
            lines.append(f'[{timestamp(s["start"])} → {timestamp(s["end"])}] {s["text"]}')
    if content.get('comments_status'):
        lines += ['', '## 部分评论 / 回复', '', '> ' + content['comments_status'], '']
        for comment in content.get('comments', []):
            lines += [f'### {comment.get("author", "未署名")} · {comment.get("created", "")}',
                      '', comment.get('body', ''), '', f'来源：{comment.get("url", item["url"])}', '']
    if content.get('media'):
        lines += ['', '## 图片来源', '']
        for image in content['media']:
            lines.append(f'- {image.get("alt") or "图片"}：{image["source_url"]}；{"本地已存档" if image["status"] == "saved" else "未存档"}')
    from . import bilingual
    translated=bilingual.current(item)
    if translated:
        lines += ['', '## 双语阅读译文', '', '- 原文及原时间轴完整保留；译文单独存档，不代替原文。',
                  '- 平台第二轨与本机机器翻译分别标明来源；机器译文可能有误。', '']
        for key,unit in translated['units'].items():
            if key.startswith('caption:'):label=f'[{timestamp(unit["start"])} → {timestamp(unit["end"])}]'
            elif key.startswith('comment:'):label='回复 '+str(int(key.split(':')[1])+1)+' 的译文'
            else:label='正文译文'
            lines += [f'### {label} · {unit["language"]}', '', f'来源：{unit["source"]}', '', unit['text'], '']
    if not include_processing:return '\n'.join(lines)
    from . import knowledge
    if content.get('annotations'):
        for track,text in content['annotations'].items():
            if track in ('callable','digest'):lines+=['## '+('调用批注' if track=='callable' else '消化批注'),'',text,'']
    lines += ['', '## AI 整理', '', item.get('summary') or '（未生成）', '',
              '- AI人工查看：'+('已查看当前这份结果' if knowledge.review(item)['reviewed'] else '尚未确认查看'),
              '- 阅读用途：'+('AI资料备查，不表示本人已消化' if content.get('reading_intent')=='reference' else '待本人处理'), '',
              '## 我的批注 / 理解', '', '- 批注类型：'+knowledge.ANNOTATIONS.get(content.get('annotation_kind','note'),'备注'),
              '',item.get('notes') or '（未填写）', '']
    if content.get('knowledge_context',{}).get('notes'):
        from . import knowledge
        lines += ['## 关联的小库笔记','',*['- '+knowledge.link(n['path'],n['title']) for n in content['knowledge_context']['notes']],
                  '', '关联仅表示用户选择；AI建议、人工理解及已写入知识库分别记录。','']
    return '\n'.join(lines)

def archive(mid):
    item = get(mid)
    folder = material_folder(mid, item['platform'])
    folder.mkdir(parents=True, exist_ok=True)
    # Revision snapshots remain immutable. Latest is only a convenience projection.
    body = markdown(item)
    if mid.startswith('l1_'):
        import os
        from . import assets
        for media in item['content'].get('media',[]):
            if media['status']=='saved':body=body.replace(']('+media['path']+')',']('+os.path.relpath(assets.image_path(mid,media['path']),folder).replace('\\','/')+')')
    (folder / f'revision-{item["revision"]}.md').write_text(body, 'utf-8')
    temp = folder / 'latest.tmp'
    temp.write_text(body, 'utf-8')
    temp.replace(folder / 'material.md')
    workflow=item['content'].get('ai_workflow')
    if workflow and item['summary']:
        from . import knowledge
        review_root=DATA/'review';review_root.mkdir(parents=True,exist_ok=True)
        review_lines=['# '+item['title'],'','- 材料ID：'+mid,'- 原链接：'+item['url'],
                      '- 整理轮次：'+str(workflow['pass']),
                      '- 审查：'+('处理已完成；确认写入记录见材料历史' if item['processing']=='done' else '已审查，待本人选择入库' if knowledge.review(item)['reviewed'] else '待本人审查'),
                      '','## 本次整理依据的批注','',workflow['annotation'],'','## 整理结果','',item['summary'],
                      '','## 完整原文与历史','',str(folder/'material.md'),'']
        if workflow['annotation']!=item['notes']:
            review_lines+=['## 当前批注 / 审查反馈（尚未用于上述结果）','',item['notes'],'']
        review_temp=review_root/(mid+'.tmp');review_temp.write_text('\n'.join(review_lines),'utf-8')
        review_temp.replace(review_root/(mid+'.md'))
    elif (DATA/'review'/(mid+'.md')).exists() and not item['summary']:
        (DATA/'review'/(mid+'.md')).write_text('# '+item['title']+'\n\n当前原文或整理状态已变化，需重新整理。旧结果保留在材料历史中。\n\n'+str(folder/'material.md')+'\n','utf-8')
    return folder
