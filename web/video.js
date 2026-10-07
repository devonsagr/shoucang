'use strict';
// Playback stays on the platform. No video files or media proxy are used here.
const VideoReader = (() => {
  function target(material) {
    const urls=[material.content?.resolved_url,material.content?.video_url,material.url].filter(Boolean);
    for(const value of urls){
      let u;try{u=new URL(value);}catch{continue;}
      if(!['http:','https:'].includes(u.protocol)||u.username||u.password||u.port)continue;
      const host=u.hostname.toLowerCase().replace(/^www\./,'');
      if(material.platform==='youtube'&&['youtube.com','m.youtube.com','youtu.be'].includes(host)){
        const id=host==='youtu.be'?u.pathname.slice(1).split('/')[0]:u.searchParams.get('v')||u.pathname.match(/^\/(?:shorts|embed|live)\/([^/]+)/)?.[1];
        if(/^[\w-]{11}$/.test(id||''))return {platform:'youtube',id,seek:true,liveTime:true};
      }
      if(material.platform==='bilibili'&&['bilibili.com','m.bilibili.com'].includes(host)){
        const id=u.pathname.match(/^\/video\/(BV[\da-zA-Z]{10}|av\d+)(?:\/|$)/)?.[1];
        const part=Number(u.searchParams.get('p')||material.content?.part?.index||1);
        if(id&&Number.isInteger(part)&&part>0&&part<=10000)return {platform:'bilibili',id,part,seek:true,liveTime:false};
      }
      if(material.platform==='douyin'&&['douyin.com','m.douyin.com'].includes(host)){
        const id=u.pathname.match(/^\/video\/(\d{10,25})(?:\/|$)/)?.[1]||u.searchParams.get('modal_id');
        if(/^\d{10,25}$/.test(id||''))return {platform:'douyin',id,seek:false,liveTime:false};
      }
    }
    return null;
  }
  function embedUrl(spec,origin,seconds=0,autoplay=false){
    const time=Number.isFinite(seconds)?Math.max(0,seconds):0;
    if(spec.platform==='youtube'){
      const u=new URL('https://www.youtube.com/embed/'+spec.id);
      u.search=new URLSearchParams({enablejsapi:'1',origin,playsinline:'1',autoplay:autoplay?'1':'0',start:String(Math.floor(time))}).toString();return u.href;
    }
    if(spec.platform==='bilibili'){
      const u=new URL('https://player.bilibili.com/player.html');
      u.search=new URLSearchParams({[spec.id.startsWith('BV')?'bvid':'aid']:spec.id.replace(/^av/,''),p:String(spec.part),t:String(time),autoplay:autoplay?'1':'0',danmaku:'0'}).toString();return u.href;
    }
    return 'https://open.douyin.com/player/video?'+new URLSearchParams({vid:spec.id,autoplay:'0'});
  }
  function translationFor(segment,track){
    if(!track?.segments?.length)return '';
    const start=Number(segment.start),end=Number(segment.end);
    // Time overlap, not segment index: platforms split their language tracks differently.
    const lines=[];
    for(let i=0;i<track.segments.length;i++){
      const s=track.segments[i];if(s.start>=end)break;
      if(Math.min(s.end,end)-Math.max(s.start,start)>0&&s.text&&!lines.includes(s.text))lines.push(s.text);
    }
    return lines.join(' ');
  }
  function nativeUrl(value){
    if(/^\/api\/materials\/[a-f\d]{32}\/playback-stream\/[a-f\d]{32}$/.test(value||''))return value;
    let u;try{u=new URL(value);}catch{return null;}
    const domains=['douyinvod.com','douyin.com','iesdouyin.com','amemv.com'];
    return u.protocol==='https:'&&!u.username&&!u.password&&(!u.port||u.port==='443')&&domains.some(d=>u.hostname===d||u.hostname.endsWith('.'+d))?u.href:null;
  }
  function mountNative(video,address,{onStatus=()=>{},onTime=()=>{},onFailure=()=>{},onReady=()=>{}}={}){
    let disposed=false,pending=null,ready=false,failed=false;
    const url=nativeUrl(address);if(!url)throw new Error('不支持的播放来源');
    const status=text=>{if(!disposed)onStatus(text);};
    const play=()=>{const result=video.play();result?.catch(()=>status('时间点已定位；请点击播放按钮继续。'));};
    const seek=seconds=>{
      if(disposed||failed||!Number.isFinite(seconds)||seconds<0)return false;
      if(!ready){pending=seconds;status('视频正在加载，加载后会请求定位到所选字幕。');return true;}
      if(seconds>=video.duration){status('这句字幕时间超出实际视频时长，请核查原时间轴。');return false;}
      video.currentTime=seconds;status('正在定位到所选字幕，以实际播放进度为准。');play();return true;
    };
    const metadata=()=>{if(disposed)return;ready=Number.isFinite(video.duration)&&video.duration>0;status(ready?'抖音视频在线播放 · 点击字幕定位 · 本工具不保存视频文件':'未取得有效视频时长。');if(ready)onReady();if(pending!==null){const value=pending;pending=null;seek(value);}};
    const time=()=>{if(!disposed&&ready)onTime(video.currentTime);};
    const seeked=()=>{if(!disposed&&ready){onTime(video.currentTime);status('已定位到 '+Math.floor(video.currentTime)+' 秒，使用原生播放器继续播放。');}};
    const error=()=>{if(disposed)return;failed=true;ready=false;pending=null;status('平台视频流未能播放，返回原站播放器。');onFailure();};
    video.addEventListener('loadedmetadata',metadata);video.addEventListener('timeupdate',time);
    video.addEventListener('seeked',seeked);video.addEventListener('error',error);
    video.src=url;video.load();
    return {seek,destroy(){disposed=true;pending=null;video.pause();for(const [name,fn] of [['loadedmetadata',metadata],['timeupdate',time],['seeked',seeked],['error',error]])video.removeEventListener(name,fn);video.removeAttribute('src');video.load();}};
  }
  let apiPromise;
  function youtubeApi(){
    if(window.YT?.Player)return Promise.resolve(window.YT);
    if(apiPromise)return apiPromise;
    apiPromise=new Promise((resolve,reject)=>{
      const timeout=setTimeout(()=>{apiPromise=null;reject(new Error('YouTube 控制接口未连接；可以使用播放器或原网站。'));},15000);
      const previous=window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady=()=>{clearTimeout(timeout);if(typeof previous==='function')previous();resolve(window.YT);};
      const script=document.createElement('script');script.src='https://www.youtube.com/iframe_api';
      script.onerror=()=>{clearTimeout(timeout);apiPromise=null;script.remove();reject(new Error('YouTube 接口加载失败，请检查网络。'));};
      document.head.append(script);
    });
    return apiPromise;
  }
  // Injectable API promise keeps the control contract testable without remote playback.
  function mount(frame,spec,{origin,onStatus=()=>{},onTime=()=>{},loadApi=youtubeApi}={}){
    let disposed=false,player=null,clock=null,pending=null,ready=false,unavailable=false;
    frame.src=embedUrl(spec,origin);
    const status=value=>{if(!disposed)onStatus(value);};
    if(spec.platform==='youtube'){
      status('点击字幕定位播放；正在连接 YouTube 控制接口。');
      loadApi().then(YT=>{
        if(disposed)return;
        player=new YT.Player(frame,{events:{
          onReady:()=>{if(disposed)return;ready=true;status('点击一句字幕，视频会跳到对应时间。');if(pending!==null){player.seekTo(pending,true);player.playVideo();pending=null;}
            clock=setInterval(()=>{if(!disposed&&ready&&player.getPlayerState?.()===1)onTime(player.getCurrentTime());},450);},
          onError:event=>{ready=false;unavailable=true;status('YouTube 播放受限（'+event.data+'），可在原网站查看。');},
          onAutoplayBlocked:()=>status('浏览器拦截自动播放，请点播放器的播放按钮。')
        }});
      }).catch(error=>{unavailable=true;status(error.message);});
    }else status(spec.seek?'点击字幕会带时间点重新载入 B站播放器。':'抖音播放器暂无已验证的逐句跳转接口；字幕可阅读，播放使用原生控制。');
    return {
      seek(seconds){
        if(disposed||!Number.isFinite(seconds)||seconds<0)return false;
        if(unavailable){status('播放器控制不可用，请使用原站播放器。');return false;}
        if(!spec.seek){status('抖音暂不支持逐句定位，请使用播放器进度条。');return false;}
        if(spec.platform==='youtube'){
          if(!ready){pending=seconds;status('正在连接播放器，连接后将跳到所选字幕。');return true;}
          player.seekTo(seconds,true);player.playVideo();
        }else frame.src=embedUrl(spec,origin,seconds,true);
        status(spec.platform==='bilibili'?'已请求从所选时间点播放；以播放器实际进度为准。':'已请求定位到所选字幕。');return true;
      },
      destroy(){disposed=true;clearInterval(clock);pending=null;try{player?.destroy();}catch{}frame.removeAttribute('src');}
    };
  }
  return {target,embedUrl,translationFor,mount,nativeUrl,mountNative};
})();
