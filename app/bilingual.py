"""Local bilingual reading. Original material never leaves the machine."""
from __future__ import annotations
import hashlib
import json
import re
import shutil
import threading
import zipfile
from pathlib import PurePosixPath
import httpx
from . import adapters, store

VERSION = 2
MODEL_VERSION = '1.9'
SOURCE = '本机机器翻译 · CTranslate2 / Argos 1.9'
IMAGE = re.compile(r'!\[([^\]\n]*)\]\(([^\s)]+)(?:\s+"[^"]*")?\)')
URL = re.compile(r'https?://[^\s<>]+')
PROTECTED = re.compile(r'https?://[^\s<>]+|(?<![\w@])@[A-Za-z0-9_]{1,50}(?!\w)')
RUNTIMES = {}
MODEL_LOCK = threading.Lock()

def identity(item):
    content=item['content']
    return store.digest(store.dumps({'body':item['body'],'segments':content.get('segments',[]),
        'comments':content.get('comments',[]),'language':content.get('language',''),
        'tracks':content.get('subtitle_tracks',[])}))

def paragraphs(text):
    """Same paragraph/image boundaries as the original rich reader."""
    end=0;output=[]
    for image in IMAGE.finditer(text):
        output.extend(p for p in re.split(r'\n\s*\n',text[end:image.start()].strip()) if p)
        end=image.end()
    output.extend(p for p in re.split(r'\n\s*\n',text[end:].strip()) if p)
    return output

def language(text,hint=''):
    if hint and not hint.lower().startswith(('en','zh','ai-zh')):return None
    readable=PROTECTED.sub('',text)
    if re.search(r'[\u4e00-\u9fff]',readable):return 'zh'
    if re.search(r'[A-Za-z]',readable):return 'en'
    return None

def units(item):
    output=[];content=item['content']
    def append(key,text,hint='',**extra):
        source=language(text,hint)
        if not source:return
        output.append({'id':key,'original':text,'source_language':source,
                       'language':'zh' if source=='en' else 'en',**extra})
    for index,text in enumerate(paragraphs(item['body'])):append(f'body:{index}',text)
    for index,segment in enumerate(content.get('segments',[])):
        append(f'caption:{index}',segment['text'],content.get('language',''),start=segment['start'],end=segment['end'])
        if not output or output[-1]['id']!=f'caption:{index}':continue
        unit=output[-1]
        track=next((t for t in content.get('subtitle_tracks',[]) if str(t.get('language','')).startswith(unit['language'])),None)
        if track:
            translated=' '.join(s['text'] for s in track.get('segments',[])
                if s['start']<segment['end'] and s['end']>segment['start'])
            if translated.strip():unit.update(provided=translated,provided_source=track.get('source','平台第二语言字幕'))
    for index,comment in enumerate(content.get('comments',[])):
        for paragraph,text in enumerate(paragraphs(comment.get('body',''))):append(f'comment:{index}:{paragraph}',text)
    return output

def current(item):
    result=item['content'].get('reader_translation')
    return result if result and result.get('source_hash')==identity(item) and result.get('version')==VERSION else None

def prepare_model(direction,report=lambda _:None):
    if direction not in ('en_zh','zh_en'):raise ValueError('当前本机翻译只支持中英双语')
    root=store.DATA/'models'/'translation';root.mkdir(parents=True,exist_ok=True)
    destination=root/direction
    if (destination/'model'/'model.bin').is_file():return destination
    url=f'https://argos-net.com/v1/translate-{direction}-1_9.argosmodel'
    package=root/(direction+'.argosmodel');partial=root/(direction+'.part')
    report({'stage':'translation_model','message':f'首次下载本机{direction}翻译模型；材料不会上传'})
    if not package.exists():
        try:
            with httpx.Client(timeout=httpx.Timeout(120,connect=25),follow_redirects=False) as client:
                for _ in range(5):
                    adapters.public_url(url)
                    with client.stream('GET',url) as response:
                        if response.is_redirect:
                            url=str(response.url.join(response.headers['location']))
                            if not url.startswith('https://'):raise ValueError('翻译模型下载跳转不是HTTPS')
                            continue
                        response.raise_for_status();size=0;digest=hashlib.sha256()
                        with partial.open('wb') as target:
                            for chunk in response.iter_bytes(65536):
                                size+=len(chunk)
                                if size>450_000_000:raise ValueError('翻译模型超过下载上限，已停止')
                                target.write(chunk);digest.update(chunk)
                        partial.replace(package)
                        (root/(direction+'.download.json')).write_text(store.dumps({'url':url,'sha256':digest.hexdigest(),'bytes':size,'version':MODEL_VERSION}),'utf-8')
                        break
                else:raise ValueError('翻译模型下载重定向过多')
        except BaseException:
            partial.unlink(missing_ok=True);raise
    stage=root/('install-'+store.uid());stage.mkdir()
    try:
        with zipfile.ZipFile(package) as archive:
            entries=archive.infolist()
            if len(entries)>2000 or sum(e.file_size for e in entries)>650_000_000:raise ValueError('翻译模型包大小不合法')
            for entry in entries:
                name=PurePosixPath(entry.filename)
                if name.is_absolute() or '..' in name.parts or '\\' in entry.filename or ':' in entry.filename or (entry.external_attr>>16)&0o170000==0o120000:
                    raise ValueError('翻译模型包包含越界路径或链接')
                target=stage.joinpath(*name.parts)
                if not target.resolve().is_relative_to(stage.resolve()):raise ValueError('翻译模型目录越界')
                if entry.is_dir():target.mkdir(parents=True,exist_ok=True);continue
                target.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(entry) as source,target.open('wb') as out:shutil.copyfileobj(source,out,65536)
        candidates=list(stage.rglob('metadata.json'))
        if len(candidates)!=1:raise ValueError('翻译模型缺少唯一语言信息')
        folder=candidates[0].parent;metadata=json.loads(candidates[0].read_text('utf-8'))
        if metadata.get('from_code')+'_'+metadata.get('to_code')!=direction or not (folder/'model'/'model.bin').is_file() or not (folder/'sentencepiece.model').is_file():
            raise ValueError('翻译模型语言或文件不匹配')
        folder.replace(destination);package.unlink(missing_ok=True)
    finally:
        if not stage.resolve().is_relative_to(root.resolve()):raise ValueError('临时模型目录越界')
        shutil.rmtree(stage)
    return destination

def runtime(direction,report):
    with MODEL_LOCK:
        key=(str(store.DATA.resolve()),direction)
        if key not in RUNTIMES:
            import ctranslate2
            import sentencepiece
            folder=prepare_model(direction,report)
            metadata=json.loads((folder/'metadata.json').read_text('utf-8'))
            RUNTIMES[key]=(ctranslate2.Translator(str(folder/'model'),device='cpu',compute_type='int8',intra_threads=4),
                sentencepiece.SentencePieceProcessor(model_proto=(folder/'sentencepiece.model').read_bytes()),metadata.get('target_prefix',''))
        return RUNTIMES[key]

def split_text(text):
    """Keep URLs and account handles verbatim; never truncate paragraphs."""
    parts=[];end=0
    for link in PROTECTED.finditer(text):
        parts.extend((p,False) for p in split_plain(text[end:link.start()]))
        parts.append((link.group(),True));end=link.end()
    parts.extend((p,False) for p in split_plain(text[end:]))
    return parts

def split_plain(text):
    output=[]
    while len(text)>500:
        cuts=[m.end() for m in re.finditer(r'[。！？.!?\n]|\s',text[:500]) if m.end()>=200]
        end=cuts[-1] if cuts else 500;output.append(text[:end]);text=text[end:]
    if text:output.append(text)
    return output

def translate_batch(texts,direction,report):
    translator,tokenizer,prefix=runtime(direction,report)
    parts=[split_text(text) for text in texts];inputs=[];positions=[]
    for row,pieces in enumerate(parts):
        for index,(text,protected) in enumerate(pieces):
            if not protected and text.strip():positions.append((row,index));inputs.append(tokenizer.encode(text,out_type=str))
    if inputs:
        results=translator.translate_batch(inputs,target_prefix=[[prefix]]*len(inputs) if prefix else None,
            replace_unknowns=True,beam_size=4,length_penalty=.2,max_batch_size=32,max_decoding_length=1024)
        for result,(row,index) in zip(results,positions):
            tokens=result.hypotheses[0]
            if len(tokens)>=1024:raise ValueError('译文达到模型长度上限，未把截断译文保存为成功')
            # Some target pieces are outside the source SentencePiece vocabulary.
            # Argos also removes residual U+2581 after decoding those pieces.
            value=tokenizer.decode(tokens).replace('\u2581',' ')
            if prefix and value.startswith(prefix):value=value[len(prefix):]
            if not value.strip():raise ValueError('本机翻译返回空内容')
            parts[row][index]=(value.strip(),False)
    separator=' ' if direction.endswith('_en') else ''
    return [separator.join(p[0] for p in pieces) for pieces in parts]

def translate(item,report=lambda _:None,cancelled=lambda:False):
    requested=units(item);result={};total=len(requested)
    if not total:raise ValueError('没有可翻译的中英正文、字幕或回复；原文保留')
    if total>10000 or sum(len(u['original']) for u in requested)>500000:raise ValueError('当前材料超过本机翻译上限；没有截断原文')
    for offset in range(0,total,24):
        if cancelled():raise ValueError('翻译已停止，原文和已有译文保留')
        batch=requested[offset:offset+24];values={}
        for direction in ('en_zh','zh_en'):
            pending=[u for u in batch if not u.get('provided') and u['source_language']+'_'+u['language']==direction]
            if pending:values.update(zip((u['id'] for u in pending),translate_batch([u['original'] for u in pending],direction,report)))
        for unit in batch:
            result[unit['id']]={'text':unit.get('provided') or values[unit['id']],
                'source':unit.get('provided_source') or SOURCE,'language':unit['language'],
                'source_hash':store.digest(unit['original']),**{k:unit[k] for k in ('start','end') if k in unit}}
        report({'stage':'translating','message':f'已准备 {len(result)}/{total} 段双语，包括已存档回复','done':len(result),'total':total})
    unsupported=len(item['content'].get('segments',[])) if item['content'].get('language') and not str(item['content']['language']).lower().startswith(('en','zh','ai-zh')) else 0
    return {'version':VERSION,'source_hash':identity(item),'created':store.now(),'source':SOURCE,
            'units':result,'scope':'中英正文、字幕、已存档回复；原文不替换','complete':not unsupported,
            'unsupported_captions':unsupported}
