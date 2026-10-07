"""Owned Vault bundles: exact-file moves, reversible trash and hash-protected cleanup.

Only paths recorded in confirmed exports are touched; there is no Vault walk.
The journal bridges SQLite and filesystem commits and survives process interruption.
"""
from __future__ import annotations
import json
import os
import re
import shutil
from pathlib import Path, PurePosixPath
from . import obsidian, store


def checked(vault, relative):
    root=Path(vault)
    if not root.is_dir():raise ValueError('知识库不可访问，停止文件操作')
    value=PurePosixPath(relative)
    if not relative or value.is_absolute() or '\\' in relative or ':' in relative or any(p in ('..','.') or p.startswith('.') for p in value.parts):
        raise ValueError('托管文件路径无效，停止文件操作')
    target=root.joinpath(*value.parts)
    if not target.resolve().is_relative_to(root.resolve()):raise ValueError('托管文件越界，停止文件操作')
    for path in (target,*target.parents):
        if path.is_symlink() or path.exists() and getattr(path.lstat(),'st_file_attributes',0)&0x400:
            raise ValueError('托管路径包含链接，停止文件操作')
        if path==root:break
    return target


def _legacy_manifest(payload):
    archive=payload['obsidian'];folder=archive['note'].rsplit('/',1)[0]
    files={archive['note']:store.digest(payload['markdown']),folder+'/payload.json':store.digest(store.dumps(payload))}
    files.update({folder+'/'+a['target']:a['sha256'] for a in payload.get('assets',[])})
    outcome=payload.get('knowledge_output') or payload.get('shelf_output')
    if outcome:files[outcome['note']]=store.digest(outcome['markdown'])
    return (outcome or archive)['note'],files


def track_legacy(c,mid):
    """Register old confirmed manifests without reading or changing Vault files."""
    layer=c.execute('SELECT source_push_id,source_material_id FROM first_layers WHERE id=?',(mid,)).fetchone()
    rows=c.execute("SELECT * FROM pushes WHERE destination='obsidian' AND state='confirmed' AND (material_id=? OR id=?)",
                   (mid,layer['source_push_id'] if layer else '')).fetchall()
    for row in rows:
        if c.execute('SELECT 1 FROM vault_exports WHERE id=?',(row['id'],)).fetchone():continue
        # A raw source's first-layer export belongs to that independent layer.
        owner=c.execute('SELECT id FROM first_layers WHERE source_push_id=?',(row['id'],)).fetchone()
        if owner and owner[0]!=mid:continue
        p=json.loads(row['payload']);note,files=_legacy_manifest(p)
        c.execute('INSERT INTO vault_exports(id,owner_id,vault,note,files_json,updated) VALUES (?,?,?,?,?,?)',
                  (row['id'],mid,p['obsidian']['vault'],note,store.dumps(files),store.now()))


def relocation(c,owners):
    for mid in owners:track_legacy(c,mid)
    rows=[]
    for mid in owners:
        rows.extend(dict(r) for r in c.execute("SELECT * FROM vault_exports WHERE owner_id=? AND state='live'",(mid,)))
    vault=str(obsidian.configuration())
    if any(r['vault']!=vault for r in rows):raise ValueError('旧材料在另一知识库，请先恢复对应知识库配置再迁移')
    return {'exports':[{k:r[k] for k in ('id','vault','note','files_json')} for r in rows],
            'remove':[{'path':p,'sha256':sha} for r in rows for p,sha in json.loads(r['files_json']).items()]}


def verify_relocation(c,plan):
    for expected in plan.get('exports',[]):
        row=c.execute('SELECT * FROM vault_exports WHERE id=?',(expected['id'],)).fetchone()
        if not row or row['state']!='live' or any(row[k]!=expected[k] for k in ('vault','note','files_json')):
            raise ValueError('材料位置已变化，请重新预览')
    if plan.get('exports'):
        _exclusive(c,plan['exports'][0]['vault'],{a['path'] for a in plan['remove']},{r['id'] for r in plan['exports']})


def _exclusive(c,vault,paths,export_ids):
    for r in c.execute("SELECT id,files_json FROM vault_exports WHERE vault=? AND state IN ('live','trash')",(vault,)):
        if r['id'] not in export_ids and paths.intersection(json.loads(r['files_json'])):raise ValueError('文件仍被另一条材料使用，停止删除或迁移')


def current(c,pid):
    seen=set()
    while pid and pid not in seen:
        seen.add(pid);row=c.execute('SELECT * FROM vault_exports WHERE id=?',(pid,)).fetchone()
        if not row:return None
        if row['state']=='moved':pid=row['replacement_id'];continue
        return dict(row)
    return None


def register(c,payload,owner,contents):
    note=(payload.get('knowledge_output') or payload.get('shelf_output') or payload['obsidian'])['note']
    prefix=note.rsplit('/',1)[0]
    manifest={prefix+'/'+p:store.digest_bytes(data) for p,data in contents.items()}
    c.execute('INSERT INTO vault_exports(id,owner_id,vault,note,files_json,updated) VALUES (?,?,?,?,?,?)',
              (payload['idempotency_key'],owner,payload['obsidian']['vault'],note,store.dumps(manifest),store.now()))
    for old in payload.get('relocation',{}).get('exports',[]):
        c.execute("UPDATE vault_exports SET state='moved',replacement_id=?,updated=? WHERE id=?",
                  (payload['idempotency_key'],store.now(),old['id']))


def bundle_contents(payload,contents):
    """One primary document, one image directory, optional preserved source document."""
    outcome=payload.get('knowledge_output') or payload.get('shelf_output')
    value={k:v for k,v in contents.items() if k.startswith('assets/')}
    value['index.md']=(outcome['markdown'] if outcome else payload['markdown']).encode('utf-8')
    if outcome and outcome['source_note']!=outcome['note']:
        value[PurePosixPath(outcome['source_note']).name]=payload['markdown'].encode('utf-8')
    return value


def source_snapshot(item,manifest):
    layer=item['content'].get('first_layer_context')
    if not layer:return None
    with store.db() as c:
        row=c.execute("SELECT payload FROM pushes WHERE id=? AND state='confirmed'",(layer['source_push_id'],)).fetchone()
    if not row:raise ValueError('第一层原文快照缺失，停止迁移')
    p=json.loads(row['payload']);text=p['shelf_output']['markdown']
    # Old snapshots used cross-folder image links. The new bundle keeps images beside the note.
    for asset in manifest:
        filename=re.escape(PurePosixPath(asset['target']).name)
        text=re.sub(r'\]\([^\s)]*/assets/'+filename+r'\)',']('+asset['target']+')',text)
    if '\n## 原始存档\n' in text:text=text.rsplit('\n## 原始存档\n',1)[0]+'\n\n原链接：'+item['url']+'\n'
    return text


class Change:
    def __init__(self):
        self.id=store.uid();self.root=store.DATA/'vault_operations'/self.id
        self.journal=None;self.applied=False

    def __enter__(self):return self

    def save_journal(self):
        path=self.root/'journal.tmp'
        with path.open('w',encoding='utf-8') as out:
            out.write(store.dumps(self.journal));out.flush();os.fsync(out.fileno())
        path.replace(self.root/'journal.json')

    def stash_local(self,c,paths):
        paths=list(dict.fromkeys(p for p in paths if p.exists()))
        if not paths:return
        for path in paths:
            if not path.resolve().is_relative_to(store.DATA.resolve()) or len(path.relative_to(store.DATA).parts)<2:raise ValueError('本机清理路径越界')
            for ancestor in (path,*path.parents):
                if ancestor.is_symlink() or ancestor.exists() and getattr(ancestor.lstat(),'st_file_attributes',0)&0x400:raise ValueError('本机清理路径包含链接')
                if ancestor==store.DATA:break
        if self.journal is None:
            for path in (store.DATA,store.DATA/'vault_operations',self.root):
                if path.is_symlink() or path.exists() and getattr(path.lstat(),'st_file_attributes',0)&0x400:raise ValueError('本机恢复目录包含链接')
            self.root.mkdir(parents=True,exist_ok=False)
            self.journal={'id':self.id,'vault':'','backups':{},'created':{}}
        self.applied=True
        moves=self.journal.setdefault('local_moves',[])
        for path in paths:
            backup='local/'+str(len(moves));moves.append({'source':path.relative_to(store.DATA).as_posix(),'backup':backup})
            self.save_journal()
            destination=self.root/backup;destination.parent.mkdir(parents=True,exist_ok=True)
            path.rename(destination)
        store.event(c,None,'vault_operation_committed',{'operation_id':self.id})

    def apply(self,c,vault,writes,removes,*,allow_missing=False):
        if str(obsidian.configuration())!=vault:raise ValueError('知识库配置已改变，停止文件操作')
        before={}
        for relative,sha in removes.items():
            path=checked(vault,relative)
            if not path.exists():
                if allow_missing:continue
                raise ValueError('托管文件已缺失，请核对：'+relative)
            data=path.read_bytes()
            if store.digest_bytes(data)!=sha:raise ValueError('文件在 Obsidian 中已被修改，未删除或迁移：'+relative)
            before[relative]=data
        created=[]
        for relative,data in writes.items():
            path=checked(vault,relative)
            if path.exists() and path.read_bytes()!=data:raise ValueError('目标已有不同内容，未覆盖：'+relative)
            if not path.exists():created.append(relative)
        # Persist backups before touching any file. File names in this journal are hashes.
        for path in (store.DATA,store.DATA/'vault_operations',self.root):
            if path.is_symlink() or path.exists() and getattr(path.lstat(),'st_file_attributes',0)&0x400:raise ValueError('恢复记录目录包含链接')
        self.root.mkdir(parents=True,exist_ok=False)
        backups={}
        for relative,data in before.items():
            key=store.digest(relative);(self.root/key).write_bytes(data);backups[relative]={'file':key,'sha256':store.digest_bytes(data)}
        self.journal={'id':self.id,'vault':vault,'backups':backups,'created':{p:store.digest_bytes(writes[p]) for p in created}}
        self.save_journal()
        self.applied=True
        for relative in created:
            path=checked(vault,relative);path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as out:out.write(writes[relative])
        for relative,data in before.items():
            if relative in writes:continue
            path=checked(vault,relative)
            if store.digest_bytes(path.read_bytes())!=store.digest_bytes(data):raise ValueError('文件在操作期间改变，已停止：'+relative)
            path.unlink()
        # Verify bytes, not just existence, before recording the filesystem side.
        for relative,data in writes.items():
            if checked(vault,relative).read_bytes()!=data:raise ValueError('文件写入校验失败：'+relative)
        for relative in before:
            if relative not in writes and checked(vault,relative).exists():raise ValueError('原文件未完成迁移：'+relative)
        store.event(c,None,'vault_operation_committed',{'operation_id':self.id})

    def __exit__(self,kind,value,traceback):
        if self.applied:
            if kind:
                _rollback(self.journal,self.root)
                _clean_created(self.journal)
            else:_clean_empty(self.journal)
            _remove_journal(self.root)
        return False


def _remove_journal(root):
    base=store.DATA/'vault_operations'
    if root.parent.resolve()!=base.resolve() or not re.fullmatch(r'[a-f0-9]{32}',root.name):raise ValueError('恢复记录路径无效')
    for p in (store.DATA,base,root):
        if p.is_symlink() or p.exists() and getattr(p.lstat(),'st_file_attributes',0)&0x400:raise ValueError('恢复记录包含链接')
    shutil.rmtree(root)


def _clean_empty(journal):
    vault=Path(journal['vault'])
    for relative in journal['backups']:
        parent=checked(journal['vault'],relative).parent
        # Retain top-level/category directories; never recurse or remove nonempty folders.
        while len(parent.relative_to(vault).parts)>2:
            try:parent.rmdir()
            except OSError:break
            parent=parent.parent


def _clean_created(journal):
    if not journal['created']:return
    vault=Path(journal['vault'])
    for relative in journal['created']:
        parent=checked(journal['vault'],relative).parent
        while len(parent.relative_to(vault).parts)>2:
            try:parent.rmdir()
            except OSError:break
            parent=parent.parent


def _rollback(journal,root):
    for path in (store.DATA,store.DATA/'vault_operations',root):
        if path.is_symlink() or path.exists() and getattr(path.lstat(),'st_file_attributes',0)&0x400:raise ValueError('恢复记录包含链接')
    for relative,sha in journal['created'].items():
        path=checked(journal['vault'],relative)
        if path.exists():
            if store.digest_bytes(path.read_bytes())!=sha:raise ValueError('恢复时发现人工修改，请保留恢复记录：'+str(root))
            path.unlink()
    for relative,backup in journal['backups'].items():
        if not re.fullmatch(r'[a-f0-9]{64}',backup['file']):raise ValueError('恢复记录文件名无效')
        path=checked(journal['vault'],relative);data=(root/backup['file']).read_bytes()
        if store.digest_bytes(data)!=backup['sha256']:raise ValueError('恢复副本校验失败：'+str(root))
        if path.exists():
            if path.read_bytes()!=data:raise ValueError('恢复位置已被修改，请保留恢复记录：'+str(root))
        else:
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as out:out.write(data)
    for move in journal.get('local_moves',[]):
        relative=PurePosixPath(move['source']);backup=move['backup']
        if relative.is_absolute() or len(relative.parts)<2 or '..' in relative.parts or ':' in move['source'] or '\\' in move['source'] or not re.fullmatch(r'local/\d+',backup):raise ValueError('本机恢复路径无效')
        source=store.DATA.joinpath(*relative.parts);saved=root/backup
        if not source.resolve().is_relative_to(store.DATA.resolve()):raise ValueError('本机恢复路径越界')
        for path in (source,*source.parents):
            if path.is_symlink() or path.exists() and getattr(path.lstat(),'st_file_attributes',0)&0x400:raise ValueError('本机恢复路径包含链接')
            if path==store.DATA:break
        if saved.exists():
            if source.exists():raise ValueError('本机恢复位置已有文件，请保留恢复记录：'+str(root))
            source.parent.mkdir(parents=True,exist_ok=True);saved.rename(source)


def recover():
    base=store.DATA/'vault_operations'
    if not base.exists():return
    for path in (store.DATA,base):
        if path.is_symlink() or getattr(path.lstat(),'st_file_attributes',0)&0x400:raise ValueError('恢复记录根目录包含链接')
    # Only this project's named journals; no Vault enumeration.
    for root in base.iterdir():
        if not re.fullmatch(r'[a-f0-9]{32}',root.name):continue
        if root.is_symlink() or root.exists() and getattr(root.lstat(),'st_file_attributes',0)&0x400:raise ValueError('恢复记录包含链接')
        path=root/'journal.json'
        if not path.is_file():continue
        journal=json.loads(path.read_text('utf-8'))
        with store.db() as c:
            committed=c.execute("SELECT 1 FROM events WHERE kind='vault_operation_committed' AND json_extract(detail,'$.operation_id')=?",(journal['id'],)).fetchone()
        if not committed:
            _rollback(journal,root);_clean_created(journal)
        else:_clean_empty(journal)
        _remove_journal(root)


def recycle(c,mid,restore,change):
    track_legacy(c,mid)
    state='trash' if restore else 'live'
    rows=[dict(r) for r in c.execute('SELECT * FROM vault_exports WHERE owner_id=? AND state=?',(mid,state))]
    if not rows:return 0
    vault=str(obsidian.configuration());writes={};removes={};updates=[]
    for r in rows:
        if r['vault']!=vault:raise ValueError('已保存材料位于另一知识库，未移动文件')
        old=json.loads(r['files_json'])
        trash_prefix=obsidian.paths()['trash']+'/'+r['id']+'/'
        new=json.loads(r['restore_json']) if restore else {trash_prefix+p:sha for p,sha in old.items()}
        if restore:
            mapping={}
            for old_path in old:
                matches=[p for p in new if old_path.endswith('/'+p)]
                if len(matches)!=1:raise ValueError('回收站文件归属不明确，停止恢复')
                mapping[old_path]=matches[0]
            note=mapping[r['note']]
        else:
            mapping={p:trash_prefix+p for p in old};note=mapping[r['note']]
        for p,target in mapping.items():
            path=checked(vault,p)
            if not path.is_file():raise ValueError('托管文件已缺失：'+p)
            writes[target]=path.read_bytes()
        removes.update(old);updates.append((r,note,new,mapping))
    _exclusive(c,vault,set(removes),{r['id'] for r in rows})
    change.apply(c,vault,writes,removes)
    for r,note,new,mapping in updates:
        c.execute('UPDATE vault_exports SET state=?,note=?,files_json=?,restore_json=?,updated=? WHERE id=?',
                  ('live' if restore else 'trash',note,store.dumps(new),'{}' if restore else r['files_json'],store.now(),r['id']))
        if mid.startswith('l1_'):
            saved=json.loads(c.execute('SELECT content_json FROM first_layers WHERE id=?',(mid,)).fetchone()[0])
            for key in ('first_layer_context','current_export'):
                context=saved.get(key,{})
                for field in ('note','source_note'):
                    if context.get(field) in mapping:context[field]=mapping[context[field]]
                if context.get('note'):context['path']=str(Path(vault)/context['note'])
            c.execute('UPDATE first_layers SET content_json=? WHERE id=?',(store.dumps(saved),mid))
    return len(rows)


def describe(c,mid):
    rows=[dict(r) for r in c.execute("SELECT * FROM vault_exports WHERE owner_id=? AND state IN ('live','trash')",(mid,))]
    value={'bundles':[{'path':str(Path(r['vault'])/r['note']),'state':r['state'],'files':len(json.loads(r['files_json']))} for r in rows],
           'files':sum(len(json.loads(r['files_json'])) for r in rows),'independent_layers':0}
    if not mid.startswith('l1_'):value['independent_layers']=c.execute('SELECT count(*) FROM first_layers WHERE source_material_id=?',(mid,)).fetchone()[0]
    return value


def purge(c,mid,change):
    track_legacy(c,mid)
    rows=[dict(r) for r in c.execute("SELECT * FROM vault_exports WHERE owner_id=? AND state IN ('live','trash')",(mid,))]
    if not rows:return 0
    vault=str(obsidian.configuration());removes={}
    for r in rows:
        if r['vault']!=vault:raise ValueError('已保存材料位于另一知识库，未删除文件')
        removes.update(json.loads(r['files_json']))
    # Refuse cleanup of a file still owned by a different active export.
    for other in c.execute("SELECT * FROM vault_exports WHERE owner_id<>? AND vault=? AND state IN ('live','trash')",(mid,vault)):
        if set(removes).intersection(json.loads(other['files_json'])):raise ValueError('附件仍被其他材料使用，未删除')
    change.apply(c,vault,{},removes,allow_missing=True)
    c.execute("UPDATE vault_exports SET state='purged',updated=? WHERE owner_id=? AND state IN ('live','trash')",(store.now(),mid))
    return len(rows)
