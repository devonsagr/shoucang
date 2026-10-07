"""Automatic captions -> bounded temporary audio -> local timecoded ASR."""
from __future__ import annotations
import contextvars
import json
import math
import os
from pathlib import Path
import httpx
from . import store

PROGRESS = contextvars.ContextVar('video_progress', default=None)

def stage(name, message, **details):
    callback = PROGRESS.get()
    if callback: callback({'stage':name, 'message':message, **details})

def download(url, target, headers=None):
    from .adapters import public_url
    stage('audio', '没有可用平台字幕，正在获取临时音频；不会在阅读区放入视频')
    with httpx.Client(timeout=httpx.Timeout(90, connect=25), follow_redirects=False) as client:
        for _ in range(6):
            public_url(url)
            with client.stream('GET', url, headers={'User-Agent':'Mozilla/5.0', **(headers or {})}) as r:
                if r.is_redirect:
                    url = str(r.url.join(r.headers['location'])); continue
                if r.status_code in (401,403,429): raise ValueError('平台拒绝音频访问或限流；已停止，不绕过验证')
                r.raise_for_status()
                size = 0
                try:
                    with target.open('xb') as stream:
                        for chunk in r.iter_bytes():
                            size += len(chunk)
                            if size > 300_000_000: raise ValueError('临时音频/媒体超过 300MB 安全上限')
                            stream.write(chunk)
                    if size < 1024: raise ValueError('平台未返回有效音频')
                except BaseException:
                    target.unlink(missing_ok=True); raise
                return target
    raise ValueError('媒体重定向次数过多')

DLL_HANDLES=[]

def whisper_runtime():
    # CUDA runtime packages live only in this project's venv, never the global PATH.
    if os.name=='nt' and not DLL_HANDLES:
        import sys
        nvidia=Path(sys.prefix)/'Lib/site-packages/nvidia'
        bins=[nvidia/name/'bin' for name in ('cuda_runtime','cublas','cudnn')]
        bins=[path for path in bins if path.is_dir()]
        for path in bins: DLL_HANDLES.append(os.add_dll_directory(str(path)))
        if bins:os.environ['PATH']=os.pathsep.join(str(path) for path in bins)+os.pathsep+os.environ.get('PATH','')
    import ctranslate2
    cfg=store.settings()
    requested=cfg.get('whisper_device','auto')
    gpu=ctranslate2.get_cuda_device_count()>0
    device='cuda' if requested!='cpu' and gpu else 'cpu'
    if device=='cuda' and os.name=='nt' and not DLL_HANDLES: device='cpu'
    return device,'int8_float16' if device=='cuda' else 'int8'

def transcription_failure(content,exc):
    no_speech=isinstance(exc,NoSpeech)
    content.update(transcript_state='no_speech' if no_speech else 'failed',
                   transcription_attempt={'created':store.now(),'model':store.settings().get('whisper_model','turbo'),
                                          'error':str(exc)[:500]})

class NoSpeech(ValueError):pass

def transcribe(audio, duration, content, folder):
    if not duration or float(duration) > 7200: raise ValueError('本机自动转写只处理时长明确且不超过两小时的视频；未截断内容')
    device,compute_type=whisper_runtime()
    from faster_whisper import WhisperModel
    os.environ.setdefault('HF_HOME', str(store.DATA/'models'/'hf-cache'))
    model_name=store.settings().get('whisper_model','turbo')
    local=store.DATA/'models'/model_name
    stage('model',f'正在加载 {model_name} 转写模型 · {"显卡" if device=="cuda" else "CPU"}',model=model_name,device=device)
    model=WhisperModel(str(local) if (local/'model.bin').exists() else model_name,device=device,compute_type=compute_type,
                       cpu_threads=min(os.cpu_count() or 4,8),download_root=str(store.DATA/'models'))
    stage('transcribing',f'正在本机使用 {model_name} 逐段转写；保留时间轴',duration=duration,model=model_name,device=device)
    prompt=store.settings().get('whisper_vocabulary','')
    segments,meta=model.transcribe(str(audio),vad_filter=True,beam_size=5,condition_on_previous_text=False,
                                   initial_prompt=prompt or None)
    # TranscriptionInfo.duration is the decoded duration BEFORE VAD. The last spoken
    # segment and duration_after_vad are not measures of downloaded audio completeness.
    decoded = float(meta.duration)
    expected = float(duration)
    checked = math.isfinite(decoded) and decoded > 0 and abs(decoded-expected) <= max(2, expected*.03)
    content['audio_validation'] = {'platform_duration':expected, 'decoded_duration':decoded,
                                   'duration_matches':checked, 'checked':store.now()}
    if not checked:
        raise ValueError(f'音频时长与视频不一致：实际 {decoded:.1f} 秒，平台 {expected:.1f} 秒；可能只取得片段，没有标成全片转写成功')
    def consume(iterator):
        values=[]
        for segment in iterator:
            if segment.text.strip():values.append({'start':segment.start,'end':segment.end,'text':segment.text.strip()})
            stage('transcribing',f'已转写到 {store.timestamp(segment.end)} / {store.timestamp(duration)}',
                  seconds=segment.end,duration=duration,segments=len(values),model=model_name,device=device)
        return values
    values=consume(segments)
    last=max((s['end'] for s in values),default=0)
    speech=sum(s['end']-s['start'] for s in values)
    sparse=expected>=60 and last<expected*.25 and speech<expected*.03
    if sparse:
        stage('transcribing','首轮只识别出很少语音，正在取消语音过滤重新检查全长音频；结果会标为需核查')
        second,second_meta=model.transcribe(str(audio),vad_filter=False,beam_size=5,condition_on_previous_text=False,
                                           initial_prompt=prompt or None)
        fallback=consume(second)
        content['transcript_check']={'reason':'sparse_first_pass','first_pass_segments':len(values),
                                     'first_pass_last':last,'vad_fallback':True,'requires_review':True}
        if fallback: values,meta=fallback,second_meta
    if not values: raise NoSpeech('音频未识别出可用语音；没有把空字幕标成成功')
    content.update(segments=values,transcript_state='uncertain' if sparse else 'machine',subtitle_source='本机 faster-whisper 机器转写（非平台字幕）',language=meta.language,
                   transcription={'engine':'faster-whisper','model':model_name,'device':device,'compute_type':compute_type,
                                  'beam_size':5,'created':store.now(),'duration':duration,'decoded_duration':decoded,
                                  'vad_filter':not sparse,'duration_after_vad':getattr(meta,'duration_after_vad',None),
                                  'audio_retention':'临时媒体在处理结束后删除'})
    content['warning']=f'原视频未取得可用平台字幕，已使用本机 {model_name} 模型转写。专有名词、数字及中英混读仍可能有误，请对照原视频核查。'
    if sparse: content['warning']+='首轮仅识别出少量语音，已取消语音过滤重试。可能存在音乐、静音或漏识别；重试文本也可能有误，仅按部分转录保存，不能确认全片字幕完整。'
    (folder/'machine-transcript.json').write_text(store.dumps(content),'utf-8')
    stage('saving','转写完成，正在保存逐段时间轴与图片')
    return content

def direct_audio(url, duration, content, folder, headers=None):
    target = folder/'temporary-media.bin'
    if not duration or duration > 7200: raise ValueError('视频时长未知或超过两小时；不会下载后截断冒充完整')
    try:
        download(url, target, headers)
        return transcribe(target, duration, content, folder)
    finally:
        target.unlink(missing_ok=True)

def douyin_metadata(url):
    """Official metadata only; never downloads or saves a video file."""
    from . import adapters
    from bs4 import BeautifulSoup
    import re
    url = adapters.canonical(url)
    match = re.search(r'/video/(\d+)', url)
    if not match:
        _, resolved = adapters.fetch(url)
        url = adapters.canonical(resolved); match = re.search(r'/video/(\d+)', url)
    if not match: raise ValueError('无法识别抖音视频编号；请提供视频链接或含 modal_id 的视频弹窗链接')
    mobile = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1'
    raw, resolved = adapters.fetch('https://www.iesdouyin.com/share/video/'+match[1]+'/', {'User-Agent':mobile})
    soup = BeautifulSoup(raw, 'html.parser')
    state = None
    for script in soup.find_all('script'):
        source = script.string or script.get_text()
        if 'window._ROUTER_DATA' not in source: continue
        start = source.find('{')
        try: state, _ = json.JSONDecoder().raw_decode(source[start:])
        except ValueError: continue
        break
    info = None
    for entry in (state or {}).get('loaderData', {}).values():
        if not isinstance(entry, dict): continue
        candidates = entry.get('videoInfoRes', {}).get('item_list') or []
        if candidates: info = candidates[0]; break
    metadata_source='抖音官方分享页视频信息'
    if not info:
        from .platform_browser import douyin_info
        info=douyin_info(url)
        metadata_source='抖音官方视频网页实际返回的视频信息（本机浏览器）'
    if str(info.get('aweme_id', '')) != match[1]:
        raise ValueError('平台返回的视频编号与当前材料不一致，停止播放与转写')
    return info, metadata_source

def douyin(url, folder):
    from . import adapters
    import re
    url = adapters.canonical(url)
    stage('subtitles','正在读取抖音视频与平台字幕信息')
    # Platform subtitles remain first choice when the extractor can access them.
    try:
        result = adapters.video(url, folder, True)
        if result['collection']=='ready': return result
    except Exception as exc:
        if re.search(r'429|403|验证码|Too Many Requests',str(exc),re.I):
            raise ValueError('抖音限制了访问，已停止；请在官方窗口正常登录后重试') from None
    info, metadata_source = douyin_metadata(url)
    identifier = str(info['aweme_id'])
    mobile = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1'
    video = info.get('video') or {}
    duration = video.get('duration',0)/1000
    body = info.get('desc') or ''
    covers = (video.get('cover') or {}).get('url_list') or []
    if covers: body += '\n\n![视频封面（不代表视频画面内容）]('+covers[0]+')'
    content = {'source':metadata_source, 'segments':[], 'subtitle_source':'未取得字幕', 'duration':duration,
               'comments':[], 'comments_status':'官方分享页没有返回评论；未把未获取视为无评论。'}
    (folder/'original-metadata.json').write_text(store.dumps({'id':info.get('aweme_id'),'description':info.get('desc'),
                                                            'author':info.get('author',{}).get('nickname'),'duration':duration}), 'utf-8')
    # Use only URLs actually returned by the official page; no watermark rewrites or third-party parser.
    tracks = video.get('subtitle_info') or []
    for track in tracks:
        link = track.get('url')
        if not link: continue
        try:
            text, _ = adapters.fetch(link)
            segments = adapters.parse_subtitles(text, 'json' if text.lstrip().startswith('{') else 'vtt')
            content.update(segments=segments, subtitle_source='抖音平台提供的字幕（生成方式未声明）', language=track.get('language','未指定'))
            (folder/'original-subtitles.txt').write_text(text,'utf-8')
            return {'title':info.get('desc') or identifier, 'body':body, 'content':content,'collection':'ready'}
        except (ValueError,httpx.HTTPError): continue
    audio = (video.get('play_addr') or {}).get('url_list') or []
    result = {'title':info.get('desc') or identifier, 'body':body, 'content':content,'collection':'partial'}
    if not audio: content.update(transcript_state='unavailable',warning='平台未返回可用媒体地址，无法转写；请登录后重试'); return result
    try:
        direct_audio(audio[0], duration, content, folder, {'User-Agent':mobile,'Referer':'https://www.iesdouyin.com/'})
        result['collection']='partial' if content.get('transcript_state')=='uncertain' else 'ready'
    except Exception as exc:
        transcription_failure(content,exc)
        content['warning']='已尝试自动字幕与本机转写，但未取得正文：'+re.sub(r'https?://\S+','[资源链接]',str(exc))[:500]
    return result
