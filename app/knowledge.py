"""Explicit, bounded reads of selected Vault notes and additive knowledge outputs."""
from __future__ import annotations
import os
import re
from pathlib import Path,PurePosixPath
from urllib.parse import quote
from . import obsidian, store, topics

SKIP = {'AGENTS.md','HARNESS.md','dashboard.md'}
MAX_BYTES = 400_000
MAX_CONTEXT = 6000
SHELVES={'ai_review':'01_AI待查看','reference':'02_资料索引','annotation':'03_我的批注'}
ANNOTATIONS={'note':'备注','inspiration':'灵感','viewpoint':'观点','question':'疑问','material':'可用素材'}
PROMPT_FILE=Path(__file__).resolve().parents[1]/'docs'/'第一层到主题材料区提示词.md'

def organization_prompt():
    vault=obsidian.root()
    text=PROMPT_FILE.read_text('utf-8').replace('{{KNOWLEDGE_ROOT}}',vault)
    for key,value in obsidian.paths().items():text=text.replace('{{'+key.upper()+'}}',value)
    return {'text':text,'vault':vault,'source':'docs/第一层到主题材料区提示词.md','writes_performed':False}

def review(item):
    value=item['content'].get('ai_review',{})
    fingerprint=store.digest(item['summary']) if item['summary'].strip() else ''
    return {'summary_hash':fingerprint,'reviewed':bool(fingerprint and value.get('summary_hash')==fingerprint),
            'reviewed_at':value.get('reviewed_at') if value.get('summary_hash')==fingerprint else None}

def topic_label(item):
    return re.sub(r'[\s/\\]','',topics.LABELS.get(item.get('topic'),'未分类'))

def shelf_folder(item,stage):
    if stage not in SHELVES:raise ValueError('请选择AI待查看、资料索引或我的批注')
    return obsidian.paths()['archive']+'/'+SHELVES[stage]+('' if stage=='ai_review' else '/'+topic_label(item))

def shelf_output(item,pid,stage,overview,archive):
    if stage=='ai_review' and not item['summary'].strip():raise ValueError('尚未生成AI整理，不会用占位文字冒充AI结果')
    if stage=='annotation' and not item['notes'].strip():raise ValueError('请先保存你的备注或批注')
    if stage=='reference' and not overview.strip():raise ValueError('资料索引需要一个可检索的简短概览，不要求消化全文')
    folder=shelf_folder(item,stage)
    title=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',item['title']).strip(' .')[:70] or '材料'
    relative=folder+'/'+title+'--'+pid+'.md'
    path=checked(relative)
    text=item['summary'] if stage=='ai_review' else item['notes'] if stage=='annotation' else overview.strip()
    if stage=='ai_review':
        annotation=item['content'].get('ai_workflow',{}).get('annotation',item['notes'])
        text='### 本次整理依据的批注\n\n'+(annotation or '（旧结果没有批注快照）')+'\n\n### 整理结果\n\n'+text
    state=('已审查；等待本人选择正式入库' if review(item)['reviewed'] else '待本人审查') if stage=='ai_review' else '资料备查；不表示已消化' if stage=='reference' else '个人批注；可继续交给AI整理'
    lines=['---','type: information-'+stage,'material_id: '+item['id'],'topic: '+item.get('topic','uncategorized'),
           'source_url: '+store.dumps(item['url']),'stage: '+stage,'human_digest: false','created: '+store.now(),
           '---','','# '+item['title'],'','- 用途：'+state,'- 平台：'+item['platform'],
           '- 批注类型：'+ANNOTATIONS.get(item['content'].get('annotation_kind','note'),'备注'),'','## '+SHELVES[stage][3:],'',text,'',
           '## 原始材料','',link(archive['note'],'完整原文、图片、字幕与回复'),'',
           '本页集中保存处理结果或索引，不代表已正式沉淀或已执行建议。','']
    return {'vault':str(obsidian.configuration()),'note':relative,'path':str(path),'markdown':'\n'.join(lines),
            'stage':stage,'folder':folder,'related_notes':[],'source_note':archive['note'],'title':item['title'],
            'overview':overview.strip() if stage=='reference' else '', 'topic':item.get('topic','uncategorized'),
            'source_url':item['url'],'annotation_kind':item['content'].get('annotation_kind','note')}

def checked(relative, *, directory=False):
    if len(relative)>600:raise ValueError('知识库相对路径过长')
    vault=obsidian.configuration()
    value=PurePosixPath(relative)
    if value.is_absolute() or '\\' in relative or ':' in relative or any(p in ('..','.') or p.startswith('.') for p in value.parts):
        raise ValueError('只允许知识库内的普通相对路径')
    path=vault.joinpath(*value.parts)
    if not path.resolve().is_relative_to(vault):raise ValueError('知识库路径越界')
    for ancestor in (path,*path.parents):
        if ancestor==vault:break
        if ancestor.is_symlink() or (ancestor.exists() and getattr(ancestor.lstat(),'st_file_attributes',0)&0x400):
            raise ValueError('知识库路径包含链接，停止读取或写入')
    if not directory and (path.suffix.lower()!='.md' or path.name in SKIP):raise ValueError('请选择普通 Markdown 笔记')
    return path

def link(path,title=''):
    if any(c in path for c in '#|^[]%'):
        label=(title or PurePosixPath(path).stem).replace('\\','\\\\').replace('[','\\[').replace(']','\\]')
        return '['+label+']('+quote(path,safe='/')+')'
    value=path.removesuffix('.md')
    label=title.replace(']','').replace('|','').replace('\n',' ')
    return '[['+value+('|'+label if label else '')+']]'

def url(path):
    return 'obsidian://open?vault='+quote(obsidian.configuration().name,safe='')+'&file='+quote(path,safe='')

def browse(folder='',query=''):
    """One chosen directory only: no recursive walk, hidden data, or body search."""
    parent=checked(folder,directory=True)
    if not parent.is_dir():raise ValueError('知识目录不存在')
    directories=[];notes=[];examined=0;limited=False
    with os.scandir(parent) as entries:
        for entry in entries:
            examined+=1
            if examined>300:limited=True;break
            if entry.name.startswith('.') or entry.name in SKIP or entry.is_symlink():continue
            relative=(PurePosixPath(folder)/entry.name).as_posix()
            try:checked(relative,directory=entry.is_dir(follow_symlinks=False))
            except ValueError:continue
            if entry.is_dir(follow_symlinks=False):directories.append({'path':relative,'title':entry.name})
            elif entry.name.lower().endswith('.md') and (not query or query.casefold() in entry.name.casefold()):
                notes.append({'path':relative,'title':entry.name[:-3],'url':url(relative)})
    return {'vault':str(obsidian.configuration()),'folder':folder,'directories':sorted(directories,key=lambda n:n['title']),
            'notes':sorted(notes,key=lambda n:n['title'])[:60],'limited':limited or len(notes)>60,
            'notice':'仅浏览当前目录及标题；选中笔记后才读取正文，不递归扫描小库。'}

def read(path):
    file=checked(path)
    if not file.is_file():raise ValueError('关联笔记不存在，请重新选择')
    if file.stat().st_size>MAX_BYTES:raise ValueError('这篇笔记超过40万字节读取上限；请选择更具体的笔记')
    data=file.read_bytes()
    if len(data)>MAX_BYTES:raise ValueError('这篇笔记超过40万字节读取上限')
    try:text=data.decode('utf-8-sig')
    except UnicodeDecodeError:raise ValueError('笔记不是UTF-8，未自动改写编码') from None
    return {'path':path,'title':file.stem,'sha256':store.digest_bytes(data),'text':text,'url':url(path)}

def select(paths):
    if len(paths)>5 or len(set(paths))!=len(paths):raise ValueError('最多关联五篇不同笔记')
    if not paths:return {'vault':store.settings().get('obsidian_vault',''),'notes':[]}
    notes=[read(path) for path in paths]
    return {'vault':str(obsidian.configuration()),'notes':[{k:n[k] for k in ('path','title','sha256')} for n in notes]}

def context(item):
    saved=item['content'].get('knowledge_context',{})
    if not saved.get('notes'):return []
    if saved.get('vault')!=str(obsidian.configuration()):raise ValueError('小库配置已变化，请重新关联笔记')
    output=[]
    for ref in saved['notes']:
        note=read(ref['path'])
        if note['sha256']!=ref['sha256']:raise ValueError('关联笔记已更新，请重新选择后再整理或确认')
        output.append({**{k:note[k] for k in ('path','title','sha256')},'text':note['text'][:MAX_CONTEXT],
                       'excerpt':len(note['text'])>MAX_CONTEXT})
    return output

def output_folders(topic):
    values=store.settings().get('knowledge_targets',[])
    return [{'path':path,'title':PurePosixPath(path).name} for path in values if checked(path,directory=True).is_dir()]

def processing_paths(item):
    from .first_layer import folders
    location=obsidian.location()
    vault=Path(location['vault']) if location['vault'] else None
    return {'local_source':str(store.material_folder(item['id'],item['platform'])/'material.md'),
            'local_review':str(store.DATA/'review'/(item['id']+'.md')),
            'vault':str(vault) if vault else '',
            'vault_available':location['available'],'vault_error':location['error'],
            'vault_review_folder':str(vault/obsidian.paths()['archive']/SHELVES['ai_review']) if vault else '',
            'first_layer_folders':{k:str(vault.joinpath(*v.split('/'))) if vault else '' for k,v in folders().items()},
            'formal_folders':[{'path':f['path'],'title':f['title'],'absolute_path':str(checked(f['path'],directory=True))}
                              for f in output_folders(item.get('topic'))] if location['available'] else [],
            'notice':'第一层保存原文与相应批注，不需要AI。目录是配置的去向；具体文件名在预览生成，本人确认后才新增，小库不可访问时停止写入。'}

def output(item,pid,title,text,folder,archive,authorship='edited'):
    target=checked(folder,directory=True)
    if not folder or target.exists() and not target.is_dir():raise ValueError('请选择知识库内的普通内容目录')
    target_relative=PurePosixPath(folder)
    if target_relative.parts[0] in ('系统','04_Vibecoding项目'):raise ValueError('系统与项目目录不能作为知识材料归位目标')
    if any(target_relative.is_relative_to(PurePosixPath(obsidian.paths()[k])) for k in ('archive','callable','digest','trash')):
        raise ValueError('原始存档、第一层材料和回收站不能作为二级归位目标')
    if not title.strip() or not text.strip():raise ValueError('请填写知识笔记标题和处理后的正文；不会用原文副本冒充理解')
    if authorship not in ('manual','reference') and item['summary'].strip() and not review(item)['reviewed']:
        raise ValueError('本条AI整理尚未由你查看确认；先保存到AI待查看或点击我已查看，再沉淀到正式知识目录')
    context(item)
    filename=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',title).strip(' .')[:70] or '知识笔记'
    layer=item['content'].get('first_layer_context')
    material_mode=authorship!='manual'
    lane='待消化' if layer and layer['track']=='digest' else '可调用资料'
    target_folder=PurePosixPath(folder)/obsidian.paths()['materials']/lane if material_mode else PurePosixPath(folder)
    relative=(target_folder/(filename+'--'+pid)/'index.md').as_posix()
    path=checked(relative)
    refs=item['content'].get('knowledge_context',{}).get('notes',[])
    source_note=(PurePosixPath(relative).parent/('来源与批注.md' if layer else '原文.md')).as_posix()
    if layer and layer.get('note'):text=text.replace(link(layer['note']),link(source_note))
    lines=['---','type: '+('material' if material_mode else 'knowledge'),'material_id: '+item['id'],'source: '+store.dumps(item['url']),
           'processing_level: 2','human_digest: '+('false' if material_mode else 'true' if authorship=='manual' else 'false'),
           'authorship: '+authorship,
           'created: '+store.now(),'---','','# '+title.strip(),'','## 处理后的内容','',text.strip(),'',
           '## 关联已有知识','',*['- '+link(r['path'],r['title']) for r in refs],
           *([] if refs else ['（未选择已有笔记）']),'','## 原始依据','',
           '- '+link(source_note,'完整原文、图片、字幕与处理记录'),'- 原链接：'+item['url'],
           *(['- '+link(source_note,'第一层批注材料')] if layer and layer.get('note') else []),
           '- AI 建议、个人理解与原文请分别核对；此笔记不表示已经执行建议。','']
    return {'vault':str(obsidian.configuration()),'note':relative,'path':str(path),'title':title.strip(),
            'markdown':'\n'.join(lines),'related_notes':refs,'folder':folder,'source_note':source_note,'authorship':authorship,'config_paths':obsidian.paths()}

def validate_output(value):
    if value['vault']!=str(obsidian.configuration()):raise ValueError('知识库配置已改变，请重新预览')
    if value.get('config_paths',obsidian.DEFAULT_PATHS)!=obsidian.paths():raise ValueError('材料目录已改变，请重新预览')
    path=checked(value['note'])
    if path.exists() and path.read_bytes()!=value['markdown'].encode('utf-8'):
        raise ValueError('知识笔记已有不同内容，停止以保护人工修改')
    for ref in value['related_notes']:
        if read(ref['path'])['sha256']!=ref['sha256']:raise ValueError('关联笔记已更新，请重新预览处理结果')
    return path
