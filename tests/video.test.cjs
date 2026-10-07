const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
let timer,stopped=false;
const context={URL,URLSearchParams,setTimeout,clearTimeout,setInterval:fn=>(timer=fn,1),clearInterval:()=>stopped=true};
vm.createContext(context);
vm.runInContext(fs.readFileSync('web/video.js','utf8')+'\nthis.reader=VideoReader;',context);
const r=context.reader;
const material=(platform,url,content={})=>({platform,url,content});
assert.equal(r.target(material('youtube','https://youtu.be/TST00001606')).id,'TST00001606');
for(const url of ['https://youtube.com.evil.test/watch?v=TST00001606','javascript:alert(1)','https://user@youtube.com/watch?v=TST00001606','https://youtube.com:444/watch?v=TST00001606'])assert.equal(r.target(material('youtube',url)),null);
assert.equal(r.target(material('x','https://youtu.be/TST00001606')),null);
const bili=r.target(material('bilibili','https://www.bilibili.com/video/BV1TST001604?p=3'));
const embed=new URL(r.embedUrl(bili,'http://localhost:8766',81.5,true));
assert.equal(embed.hostname,'player.bilibili.com');assert.equal(embed.searchParams.get('p'),'3');assert.equal(embed.searchParams.get('t'),'81.5');assert.equal(embed.searchParams.get('autoplay'),'1');
assert.equal(r.target(material('douyin','https://www.douyin.com/note/9000000000000000957')),null);
const dy=r.target(material('douyin','https://www.douyin.com/video/9000000000000000957'));assert.equal(dy.seek,false);
for(const url of ['javascript:alert(1)','https://v3.douyinvod.com.evil.test/a','https://user@v3.douyinvod.com/a','http://v3.douyinvod.com/a','https://localhost/a','//evil.test/api/materials/a','/api/materials/a/playback-stream/b','/api/materials/'+ 'a'.repeat(32)+'/playback-stream/'+ 'b'.repeat(32)+'?redirect=evil'])assert.equal(r.nativeUrl(url),null);
const relay='/api/materials/'+'a'.repeat(32)+'/playback-stream/'+'b'.repeat(32);
assert.equal(r.nativeUrl(relay),relay);
assert.equal(r.translationFor({start:95,end:105},{segments:[{start:0,end:100,text:'long cue'},{start:100,end:110,text:'next cue'}]}),'long cue next cue');
assert.equal(r.translationFor({start:110,end:115},{segments:[{start:100,end:110,text:'boundary'}]}),'');
function frame(){return {src:'',removeAttribute(name){if(name==='src')this.src='';}};}
(async()=>{
  let events,seekCalls=[],destroyed=0,status=[];
  const yt={Player:function(_frame,options){events=options.events;this.seekTo=(...args)=>seekCalls.push(args);this.playVideo=()=>seekCalls.push(['play']);this.getCurrentTime=()=>12.4;this.getPlayerState=()=>1;this.destroy=()=>destroyed++;}};
  const target=r.target(material('youtube','https://www.youtube.com/watch?v=TST00001606'));
  let observed;
  const f=frame(),controller=r.mount(f,target,{origin:'http://localhost:8766',onStatus:s=>status.push(s),onTime:t=>observed=t,loadApi:()=>Promise.resolve(yt)});
  assert.equal(controller.seek(82.25),true);await Promise.resolve();events.onReady();
  assert.deepEqual(seekCalls,[[82.25,true],['play']]);timer();assert.equal(observed,12.4);
  controller.destroy();assert.equal(destroyed,1);assert(stopped);assert.equal(f.src,'');assert.equal(controller.seek(1),false);
  let resolveApi,constructed=false;
  const late=r.mount(frame(),target,{origin:'http://localhost:8766',loadApi:()=>new Promise(resolve=>resolveApi=resolve)});
  late.destroy();resolveApi({Player:function(){constructed=true;}});await Promise.resolve();assert.equal(constructed,false);
  const failed=r.mount(frame(),target,{origin:'http://localhost:8766',loadApi:()=>Promise.reject(new Error('offline'))});
  await Promise.resolve();await Promise.resolve();await Promise.resolve();assert.equal(failed.seek(3),false);failed.destroy();
  const b=frame(),bc=r.mount(b,bili,{origin:'http://localhost:8766'});bc.seek(125);assert.equal(new URL(b.src).searchParams.get('t'),'125');bc.destroy();
  const d=frame(),dc=r.mount(d,dy,{origin:'http://localhost:8766'}),before=d.src;assert.equal(dc.seek(20),false);assert.equal(d.src,before);dc.destroy();
  const mediaEvents=new Map();let paused=0,loads=0,plays=0,nativeTime,nativeReady=0,errors=0;
  const media={duration:90,currentTime:0,src:'',addEventListener:(k,fn)=>mediaEvents.set(k,fn),removeEventListener:k=>mediaEvents.delete(k),
    load:()=>loads++,pause:()=>paused++,play:()=>{plays++;return Promise.resolve();},removeAttribute(){this.src='';}};
  const native=r.mountNative(media,relay,{onTime:t=>nativeTime=t,onReady:()=>nativeReady++,onFailure:()=>errors++});
  assert.equal(media.src,relay);
  assert.equal(native.seek(32.5),true);assert.equal(media.currentTime,0); // waits for actual metadata
  mediaEvents.get('loadedmetadata')();assert.equal(nativeReady,1);assert.equal(media.currentTime,32.5);assert.equal(plays,1);
  mediaEvents.get('seeked')();assert.equal(nativeTime,32.5);
  media.currentTime=34;mediaEvents.get('timeupdate')();assert.equal(nativeTime,34);
  assert.equal(native.seek(91),false);assert.equal(media.currentTime,34); // never fake an out-of-range jump
  mediaEvents.get('error')();assert.equal(errors,1);assert.equal(native.seek(3),false);
  native.destroy();assert.equal(mediaEvents.size,0);assert.equal(media.src,'');assert(paused&&loads>=2);assert.equal(native.seek(3),false);
  console.log('Video targets, native seeking, cleanup and bilingual time alignment passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
