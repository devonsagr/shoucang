"""Confirmed, additive exports. No Vault scan and no overwrite of existing notes."""
from __future__ import annotations
import re
from pathlib import Path, PurePosixPath
from . import assets, store

PLATFORM_FOLDERS = {'bilibili':'B站', 'youtube':'YouTube', 'douyin':'抖音', 'x':'X',
                    'heybox':'小黑盒', 'xiaohongshu':'小红书', 'web':'其他网页'}
STATE_FOLDERS = {'pending':'待处理', 'later':'稍后整理', 'review':'整理待审', 'done':'已完成'}
DEFAULT_PATHS={'archive':'收藏处理器','callable':'收藏材料库/01_调用资料','digest':'收藏材料库/02_消化暂存',
               'trash':'收藏材料库/_回收站','materials':'材料'}

def root():
    return store.settings().get('obsidian_vault') or str(store.DATA/'knowledge-base')

def paths():
    return {**DEFAULT_PATHS,**store.settings().get('knowledge_paths',{})}

def validate_paths(values,vault):
    if set(values)!=set(DEFAULT_PATHS):raise ValueError('知识库目录配置项不完整或有未知项目')
    from .vault_files import checked
    clean={}
    for key,value in values.items():
        if not isinstance(value,str) or not value.strip() or len(value)>400:raise ValueError('请填写知识库内的相对目录')
        value=value.strip().replace('\\','/')
        if '//' in value or value.endswith('/') or any(part in ('','.','..') for part in value.split('/')):raise ValueError('目录不能包含空段或相对跳转')
        checked(str(vault),value)
        clean[key]=value
    separate=[PurePosixPath(clean[k]) for k in ('archive','callable','digest','trash')]
    if any(a.is_relative_to(b) or b.is_relative_to(a) for i,a in enumerate(separate) for b in separate[i+1:]):
        raise ValueError('原始存档、两种第一层材料和回收站目录应互相独立')
    return clean

def configuration():
    vault = Path(root()).resolve()
    if not vault.is_dir(): raise ValueError('保存材料的文件夹不存在或当前不可访问')
    return vault

def target(item, pid):
    vault = configuration()
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', item['title']).strip(' .')[:70] or '材料'
    relative = Path(paths()['archive']) / PLATFORM_FOLDERS[item['platform']] / STATE_FOLDERS[item['processing']] / (title + '--' + pid) / 'index.md'
    if not (vault/relative).resolve().is_relative_to(vault):
        raise ValueError('材料分类目录越界')
    return {'vault':str(vault), 'note':relative.as_posix(), 'path': str(vault / relative),'config_paths':paths()}


def location():
    """Report the configured path even while a cloud drive is unavailable; never create it."""
    value={'vault':root(),'available':False,'error':''}
    try:
        value.update(vault=str(configuration()),available=True)
    except (ValueError,OSError) as exc:
        value['error']=str(exc)
    return value

def create_structure():
    """Only create the requested empty category tree; never enumerate or move Vault notes."""
    vault = configuration()
    archive=paths()['archive']
    directories = [vault/archive/platform/state
             for platform in PLATFORM_FOLDERS.values() for state in STATE_FOLDERS.values()]
    for path in directories:
        if not path.resolve().is_relative_to(vault):
            raise ValueError('材料分类目录越界')
        for ancestor in (path,*path.parents):
            if ancestor==vault:break
            if ancestor.is_symlink() or (ancestor.exists() and getattr(ancestor.lstat(), 'st_file_attributes', 0) & 0x400):
                raise ValueError('材料分类目录包含链接，停止创建')
        if path.exists() and not path.is_dir():
            raise ValueError('分类路径已有同名文件，停止创建目录')
    for path in directories: path.mkdir(parents=True, exist_ok=True)
    return {'root':str(vault/archive), 'directories':len(directories), 'materials_written':0}

def bundle(item, markdown):
    manifest = []
    for image in item['content'].get('media', []):
        if image['status'] != 'saved': continue
        path = assets.image_path(item['id'], image['path'])
        digest = store.digest_bytes(path.read_bytes())
        if digest != image['sha256']: raise ValueError('本地图片已改变，请重新采集后生成预览')
        filename = 'assets/' + digest[:24] + path.suffix
        markdown = markdown.replace('](' + image['path'] + ')', '](' + filename + ')')
        if not any(a['target'] == filename for a in manifest):
            manifest.append({'source':image['path'], 'target':filename, 'sha256':digest, 'bytes':path.stat().st_size})
    return markdown, manifest

def files(payload):
    value = {'material.md': payload['markdown'].encode('utf-8'), 'payload.json':store.dumps(payload).encode('utf-8')}
    if payload.get('knowledge_output'):value['knowledge.md']=payload['knowledge_output']['markdown'].encode('utf-8')
    if payload.get('shelf_output'):value['shelf.md']=payload['shelf_output']['markdown'].encode('utf-8')
    for image in payload.get('assets', []):
        path = assets.image_path(payload['material_id'], image['source'])
        data = path.read_bytes()
        if store.digest_bytes(data) != image['sha256']: raise ValueError('预览后的图片已改变，请重新预览')
        value[image['target']] = data
    return value

def preflight_files(root,contents):
    root = root.resolve()
    # Validate every existing file before writing the first byte.
    targets = []
    for relative, value in contents.items():
        target_path = (root / relative).resolve()
        if not target_path.is_relative_to(root): raise ValueError('导出路径越界')
        if target_path.exists() and target_path.read_bytes() != value:
            raise ValueError('目标文件已有不同内容；已停止以保护原有笔记或附件')
        targets.append((target_path, value))
    return targets

def write_files(root, contents):
    targets=preflight_files(root,contents)
    for path, value in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists(): continue
        # Exclusive create protects against a user/cloud sync racing the preflight.
        try:
            with path.open('xb') as output: output.write(value)
        except FileExistsError:
            if path.read_bytes() != value: raise ValueError('目标文件被其他程序修改，停止写入') from None

def preflight_target(payload,contents):
    snapshot = payload['obsidian']
    vault = configuration()
    if str(vault) != snapshot['vault']: raise ValueError('知识库配置已改变，请重新生成预览')
    if snapshot.get('config_paths',DEFAULT_PATHS)!=paths():raise ValueError('材料目录已改变，请重新生成预览')
    note = (vault / snapshot['note']).resolve()
    allowed = (vault / paths()['archive']).resolve()
    if not allowed.is_relative_to(vault) or not note.is_relative_to(allowed):
        raise ValueError('材料保存路径越界')
    value = {**{k:v for k,v in contents.items() if k not in ('material.md','knowledge.md','shelf.md')}, 'index.md':contents['material.md']}
    preflight_files(note.parent,value)
    return note,value

def confirm_target(payload, contents):
    note,value=preflight_target(payload,contents)
    write_files(note.parent, value)
    return str(note)
