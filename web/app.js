'use strict';
const $ = (s) => document.querySelector(s);
const names = {bilibili:'B站',youtube:'YouTube',douyin:'抖音',x:'X',heybox:'小黑盒',xiaohongshu:'小红书',web:'网页'};
const states = {queued:'等待收集',running:'正在收集',ready:'已收集',partial:'部分内容',failed:'收集失败',done:'已完成',pending:'待处理',later:'稍后整理',paused:'已暂停',cancelled:'已取消'};
const topics={tech:'科技 / AI',music:'音乐',entertainment:'影视 / 娱乐',games:'游戏',society:'社会 / 观点',life:'生活 / 学习',uncategorized:'未分类'};
let topicFilter='',topicSignature='';
const appearanceNames={e:'单页书桌（已选定）'};
function setAppearance(value){
  const theme=appearanceNames[value]?value:'e';document.documentElement.dataset.appearance=theme;
  try{localStorage.setItem('appearance',theme);}catch{}
}
let initialAppearance='e';
setAppearance(initialAppearance);
let selected = null, current = null, filter = 'all', dirty = false, listSeq = 0, detailSeq = 0;
let firstLoad = true, listSignature = '', readerTab = 'transcript';
let xDialogRun = 0, visibleLimit = 80;
let catalogueItems=[];
let catalogueContext='',selectionScope='',multiSelect=false,batchRunning=false,purgeSelection=null,batchFailures=[],batchProgress='';
const checkedMaterials=new Map();
let processingMode=null,annotationTrack=null,notesBaseline="";
let layerPhase='all',firstFolders=null;
const inFirstLibrary=()=>['callable','digest'].includes(filter);
const trashCatalogue=()=>filter==='trash'||inFirstLibrary()&&layerPhase==='trash';
let videoController=null, videoMaterial=null, playbackTime=0, subtitleQuery='', followPlayback=true;
let embedResize=null,playbackRequest=null,nativePlayback=false,captionList=null;
let bilingualVisible=false;try{bilingualVisible=localStorage.getItem('bilingualVisible')==='true';}catch{}
const translationRequests=new Set();
const ICONS = {
  leaf:'<path d="M12 19C4 18 2 9 3 4c7 0 10 5 9 15ZM12 17C12 8 17 3 23 2c1 7-4 14-11 15Z" fill="currentColor" stroke="none"/><path d="M12 23c0-9-2-12-6-15m6 9c2-6 4-8 8-11"/>',
  bookmark:'<path d="M6 3h12v18l-6-4-6 4z"/>',
  file:'<path d="M14 2H5v20h14V7z"/><path d="M14 2v6h5"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
  'check-circle':'<circle cx="12" cy="12" r="9"/><path d="m7 12 3 3 7-7"/>',
  globe:'<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18M5 6.5h14M5 17.5h14"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  book:'<path d="M12 5c-3-2-7-2-10-1v16c3-1 7-1 10 1 3-2 7-2 10-1V4c-3-1-7-1-10 1v16"/>',
  sparkles:'<path d="m12 2 2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5zM20 2v4M18 4h4"/>',
  export:'<path d="M14 3h7v7M21 3l-11 11M10 5H4v16h16v-7"/>',
  arrow:'<path d="M6 18 18 6M6 6h12v12"/>',
  back:'<path d="m14 6-6 6 6 6"/>',
  download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  transcript:'<rect x="5" y="2" width="14" height="20" rx="2"/><path d="M8 7h8M8 11h8M8 15h5M8 18h3"/>',
  edit:'<path d="m15 4 5 5M4 20l5-1L21 7a2 2 0 0 0-5-5L4 14z"/>',
  history:'<path d="M3 11a9 9 0 1 1 2 7M3 4v7h7M12 7v6l4 2"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
  trash:'<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
  close:'<path d="m6 6 12 12M6 18 18 6"/>',
  comments:'<path d="M4 4h16v13H9l-5 4z"/><path d="M8 10h.01M12 10h.01M16 10h.01"/>',
  chevron:'<path d="m6 9 6 6 6-6"/>',
  expand:'<path d="M3 9V3h6m6 0h6v6M21 15v6h-6M9 21H3v-6M8 8l-5-5m13 5 5-5m-5 13 5 5M8 16l-5 5"/>',
  settings:'<path d="m9 3 1-1h4l1 3 3 1 3-1 2 4-2 2v3l2 2-2 4-3-1-3 1-1 3h-4l-1-3-3-1-3 1-2-4 2-2v-3L1 9l2-4 3 1 3-1z" transform="translate(1 0) scale(.92)"/><circle cx="12" cy="12" r="3"/>',
  youtube:'<rect x="1" y="4" width="22" height="16" rx="5" fill="currentColor" stroke="none"/><path d="m10 8 6 4-6 4z" fill="white" stroke="none"/>',
  bilibili:'<rect x="3" y="6" width="18" height="15" rx="3"/><path d="m7 2 3 4m7-4-3 4M7 11v3m10-3v3m-7 3 2 1 2-1"/>',
  douyin:'<path d="M14 2h4c0 3 2 5 5 5v4c-3 0-5-1-6-2v8a6 6 0 1 1-6-6v4a2 2 0 1 0 3 2z" fill="currentColor" stroke="none"/>',
  x:'<path d="M4 3h5l11 18h-5zM20 3 4 21"/>',
  heybox:'<path d="m3 7 8-5v7l-3 2v5l3 2v5l-8-5zm10-5 8 5v11l-8 5v-7l3-2V9l-3-2z" fill="currentColor" stroke="none"/>',
  github:'<path d="M12 2a10 10 0 0 0-3.2 19.5v-2.2c-2.6.6-3.2-1.2-3.2-1.2-.4-1.1-1-1.4-1-1.4-.9-.6.1-.6.1-.6 1 .1 1.5 1 1.5 1 .9 1.5 2.2 1 2.7.8.1-.7.4-1.1.6-1.4-2.1-.2-4.3-1-4.3-4.5 0-1 .4-1.8 1-2.4-.1-.2-.4-1.2.1-2.4 0 0 .8-.3 2.7 1a9 9 0 0 1 5 0c1.9-1.3 2.7-1 2.7-1 .5 1.2.2 2.2.1 2.4.6.6 1 1.4 1 2.4 0 3.5-2.2 4.3-4.3 4.5.4.3.7.9.7 1.8v3.2A10 10 0 0 0 12 2z" fill="currentColor" stroke="none"/>'
};
function icon(name){return `<svg class="icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]||ICONS.file}</svg>`;}
function platformKey(m){return m.platform==='web'&&/^https?:\/\/(www\.)?github\.com\//i.test(m.url||'')?'github':m.platform;}
function platformName(m){return platformKey(m)==='github'?'GitHub':names[m.platform]||m.platform;}
function platformIcon(key){return `<span class="platform-symbol ${key}" aria-hidden="true">${key==='xiaohongshu'?'小红书':icon(key==='web'?'globe':key)}</span>`;}
document.querySelectorAll('[data-icon]').forEach(el=>{if(el.className)el.innerHTML=icon(el.dataset.icon);else el.outerHTML=icon(el.dataset.icon);});
document.querySelectorAll('[data-platform-icon]').forEach(el=>el.outerHTML=platformIcon(el.dataset.platformIcon));
const emptyMarkup = $('#detail').innerHTML;
function clearReader(){
  window.MediaViewer?.close();captionList?.destroy();captionList=null;playbackRequest?.abort();playbackRequest=null;videoController?.destroy();videoController=null;embedResize?.disconnect();embedResize=null;videoMaterial=null;playbackTime=0;nativePlayback=false;$('#readingPane').classList.remove('video-reader','text-reader');selected=null;current=null;annotationTrack=null;detailSeq++;$('#detail').innerHTML=inFirstLibrary()?`<div class="empty"><p>第一层 · ${filter==='callable'?'调用资料':'消化暂存'}</p><h2>从一条批注开始。</h2><p>在原始收藏选择去向，确认保存后出现在这里。</p><button id="emptyCollect" class="primary">去原始收藏写批注</button></div>`:emptyMarkup;$('#emptyCollect').onclick=()=>inFirstLibrary()?chooseLibrary('source'):materialDialog();$('.app-shell').classList.remove('reading-open');$('#processingDock').hidden=true;openProcessing(null);}
const escape = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path, method='GET', body) {
  const response = await fetch('/api' + path, {method, headers:{'Content-Type':'application/json','X-Local-Request':'1'}, ...(body === undefined ? {} : {body:JSON.stringify(body)})});
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : JSON.stringify(value.detail));
  return value;
}
let toastTimer;
function toast(text, error=false, action=null) {
  const box=$('#dialog').open?$('#dialogFeedback'):$('#toast');
  $('#toast').hidden=$('#dialogFeedback').hidden=true;
  box.textContent=text;box.className=error?'error':'';box.hidden=false;
  if(action){const b=document.createElement('button');b.textContent=action.label;b.onclick=guard(action.run);box.append(b);}
  clearTimeout(toastTimer);toastTimer=setTimeout(()=>box.hidden=true,action?12000:error?12000:5000);
}
function captureLabel(m){
  if((m.media_kind||m.content?.media_kind)==='video_reference')return '原视频链接 · 未转写';
  if(m.first_layer)return ({review:'AI 整理待审',done:'已归位',later:'稍后加工'})[m.processing]||((m.first_layer.track==='callable'?'调用资料':'消化暂存')+' · '+(m.first_layer.level===2?'第二层':'第一层'));
  if((m.reading_intent||m.content?.reading_intent)==='reference')return '资料备查 · 不要求消化';
  if(m.processing==='review')return '整理待审';
  const state=m.transcript_state;
  if(state==='uncertain')return '部分转录 · 语音稀疏，需核查';
  if(state==='machine')return `机器转录 · ${m.transcription_model||m.content?.transcription?.model||'模型未记录'}`;
  if(state==='text')return m.collection==='ready'?'图文已保存':({queued:'等待补存图文',running:'正在补采回复',partial:'图文部分完成',paused:'图文已暂停',failed:'图文读取失败'})[m.collection]||states[m.collection];
  return ({platform:'已有平台 / 导入字幕',queued:'等待转录',running:'正在转录',paused:'转录已暂停',failed:'转录失败',no_speech:'未识别出语音',unavailable:'来源不可访问',missing:'尚无字幕，未确认转录结果',text:'图文材料'})[state]||states[m.collection]||m.collection;
}
async function removeMaterial(id){
  const queue=id===selected?captureSourceQueue(id):null;
  if(id===selected&&dirty)await saveNotes();
  if(id===selected&&dirty)throw new Error('批注有新改动，请先保存后再删除');
  await api(`/materials/${id}`,'DELETE');
  if(queue)await continueCatalogue(queue);else await refresh();
  toast('已删除，原文与理解可从回收站恢复。',false,{label:'撤销',run:async()=>{await api(`/materials/${id}/restore`,'POST',{});toast('已恢复材料');await refresh();}});
}

function guard(fn) { return async function(...args) { try { await fn(...args); } catch(e) { toast(e.message,true); } }; }
function dialog(title, html) { $('#dialogFeedback').hidden=true;$('#dialogTitle').textContent=title; $('#dialogBody').innerHTML=html;$('#dialogBody').querySelectorAll('summary').forEach(summary=>{summary.innerHTML=`<span class="disclosure-label">${summary.innerHTML}</span>${icon('chevron')}`;}); if(!$('#dialog').open) $('#dialog').showModal(); $('#dialog').scrollTop=0; }
async function purgeDialog(id){
  const m=await api('/materials/'+id);
  if(!m.trashed)throw new Error('请先把材料移入回收站');
  dialog('彻底删除这条材料',`<h3>${escape(m.title)}</h3><p class="muted">${escape(m.url)}</p><p>将永久删除当前材料库中的原文、字幕、图片、理解和处理历史，无法从回收站恢复。</p><p class="muted">本条已保存的文档、专属图片和本机缓存一起清理；人工修改会停止删除。</p>${m.vault_files?.independent_layers?'<p>另有 '+m.vault_files.independent_layers+' 份独立第一层材料仍在使用原文，它们的附件保留。</p>':''}<label for="purgeText">输入「彻底删除」确认</label><input id="purgeText" autocomplete="off"><div class="button-row"><button id="cancelPurge">取消</button><button id="confirmPurge" class="danger" disabled>确认彻底删除</button></div>`);
  $('#cancelPurge').onclick=()=>$('#dialog').close();
  $('#purgeText').oninput=()=>{$('#confirmPurge').disabled=$('#purgeText').value!=='彻底删除';};
  $('#confirmPurge').onclick=busy($('#confirmPurge'),async()=>{
    const queue=id===selected?captureSourceQueue(id):null;
    await api(`/materials/${id}/purge`,'POST',{revision:m.revision,confirmation:$('#purgeText').value});
    $('#dialog').close();if(queue)await continueCatalogue(queue);else await refresh();toast('已从当前材料库彻底删除');
  });
}
$('#closeDialog').onclick=()=>$('#dialog').close();
function busy(button, fn) { return guard(async () => {button.disabled=true; try {await fn();} finally {button.disabled=false;}}); }
function formatTime(n) { const ms=Math.round(n*1000);return `${String(Math.floor(ms/3600000)).padStart(2,'0')}:${String(Math.floor(ms/60000)%60).padStart(2,'0')}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}.${String(ms%1000).padStart(3,'0')}`; }
function displayTitle(m){
  if(platformKey(m)==='github') { const match=m.url.match(/github\.com\/[^/]+\/([^/?#]+)/i); if(match)return match[1]; }
  return m.title;
}
function shortTime(n){const t=Math.floor(n);return t>=3600?formatTime(n).slice(0,8):`${String(Math.floor(t/60)).padStart(2,'0')}:${String(t%60).padStart(2,'0')}`;}
function materialImageUrl(id,path){
  return `/api/materials/${encodeURIComponent(id)}/images/${path.split('/').map(encodeURIComponent).join('/')}`;
}
function materialCard(m){
  const fallback=m.collection==='queued'?'链接已登记，等待获取内容':m.collection==='running'?'正在获取内容':'来源链接已保留';
  const preview=(m.excerpt||m.error||fallback).replace(/!\[[^\]]*\]\([^)]*\)/g,'').replace(/!\[[\s\S]*$/g,'').replace(/[*#`]/g,'').replace(/\s+/g,' ').trim();
  return `<div class="material-card ${multiSelect?'selectable':''}">${multiSelect?`<label class="material-check"><input type="checkbox" data-select-id="${escape(m.id)}" aria-label="选择：${escape(displayTitle(m))}" ${checkedMaterials.has(m.id)?'checked':''} ${batchRunning?'disabled':''}></label>`:''}<button class="material-row ${selected===m.id?'selected':''} ${m.thumbnail?'has-image':''}" data-id="${escape(m.id)}" aria-pressed="${selected===m.id}" title="${escape(m.title)}">
    <span class="row-content"><span class="row-title">${escape(displayTitle(m))}</span>
    <span class="row-meta">${platformIcon(platformKey(m))}<span class="row-platform">${escape(platformName(m))}</span><span class="meta-divider"></span><span>${m.first_layer?(m.first_layer.level===2?'第二层材料':'第一层材料'):m.origin==='favorite'?'我的收藏':'非收藏链接'}</span></span>
    <span class="row-state ${m.collection}">${m.trashed?'回收站':m.first_layer?escape(captureLabel(m)):(m.reading_intent||m.content?.reading_intent)==='reference'?'资料备查':m.processing==='done'?'已完成':m.processing==='later'?'稍后整理':escape(captureLabel(m))}</span>
    <span class="row-preview">${escape(preview||fallback)}</span></span>
    <span class="row-cover ${platformKey(m)} ${m.thumbnail?'':'no-cover'}">${m.thumbnail?`<img src="${materialImageUrl(m.id,m.thumbnail)}" alt="" loading="lazy">`:platformIcon(platformKey(m))}</span>
  </button><button class="quick-delete icon-button" data-trash-id="${escape(m.id)}" data-restore="${Boolean(m.trashed)}" title="${m.trashed?'彻底删除材料':'删除材料，可恢复'}" aria-label="${m.trashed?'彻底删除':'删除'}：${escape(displayTitle(m))}">${icon('trash')}</button></div>`;
}
function syncLibraryNavigation(){
  const first=inFirstLibrary();
  $('#sourceLibraryNav').hidden=first;$('#firstLibraryNav').hidden=!first;
  $('#layerPhase').hidden=!first;$('#syncBtn').hidden=first;
  $('#layerFolderPath').hidden=!first;
  $('#organizePromptBtn').hidden=!first;
  document.querySelectorAll('[data-library]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.library===(first?'first':'source'))));
  document.querySelectorAll('[data-state]').forEach(b=>{const active=b.dataset.state===filter;b.classList.toggle('active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
}
async function chooseLibrary(mode,track='callable'){
  if(dirty){toast('请先保存批注，再切换材料库。',true);return;}
  filter=mode==='first'?(track==='digest'?'digest':'callable'):'all';layerPhase='all';$('#layerPhase').value='all';visibleLimit=80;
  try{localStorage.setItem('collectionGroup',mode);localStorage.setItem('firstTrack',track);}catch{}
  clearReader();await refresh();
}
function sourceQueueContext(){
  return JSON.stringify([filter,layerPhase,topicFilter,$('#platformFilter').value,$('#search').value,$('#originFilter').value,$('#captureFilter').value]);
}
function captureSourceQueue(id){
  return {id,context:sourceQueueContext(),detailSeq:typeof detailSeq==='number'?detailSeq:null,ids:catalogueItems.map(m=>m.id),scrollTop:$('#materialList').scrollTop};
}
async function continueSourceQueue(queue){
  if(!inFirstLibrary())await continueCatalogue(queue);
}
async function continueCatalogue(queue,removed=new Set([queue.id])){
  const unchanged=()=>!dirty&&selected===queue.id&&(queue.detailSeq===null||detailSeq===queue.detailSeq)&&sourceQueueContext()===queue.context;
  if(!unchanged())return;
  await refresh();
  if(!unchanged())return;
  const available=new Set(catalogueItems.filter(m=>!removed.has(m.id)).map(m=>m.id));
  const position=queue.ids.indexOf(queue.id);
  // Follow the order before saving the note, which can change the updated-time sort.
  const candidates=[...queue.ids.slice(position+1),...queue.ids.slice(0,Math.max(0,position)).reverse()];
  const next=candidates.find(id=>available.has(id))||catalogueItems.find(m=>available.has(m.id))?.id;
  if(next){visibleLimit=Math.max(visibleLimit,catalogueItems.findIndex(m=>m.id===next)+1);await select(next);}
  else clearReader();
  if(sourceQueueContext()===queue.context)$('#materialList').scrollTop=queue.scrollTop;
}
function batchTargets(){return [...checkedMaterials.values()].map(m=>({...m}));}
function updateSelectionScope(){
  const context=sourceQueueContext();
  if(selectionScope!==context){selectionScope=context;checkedMaterials.clear();multiSelect=false;purgeSelection=null;batchFailures=[];}
}
function chooseBatchItem(id,checked){
  if(batchRunning||catalogueContext!==sourceQueueContext())return;
  purgeSelection=null;
  const m=catalogueItems.find(m=>m.id===id);
  if(checked&&m)checkedMaterials.set(id,{id:m.id,revision:m.revision,title:displayTitle(m),trashed:Boolean(m.trashed)});
  else checkedMaterials.delete(id);
  renderSelectionControls();
}
function chooseAllMaterials(checked){
  if(batchRunning||catalogueContext!==sourceQueueContext())return;
  purgeSelection=null;checkedMaterials.clear();
  if(checked)for(const m of catalogueItems)checkedMaterials.set(m.id,{id:m.id,revision:m.revision,title:displayTitle(m),trashed:Boolean(m.trashed)});
  renderSelectionControls();
}
function renderSelectionControls(){
  const count=checkedMaterials.size,total=catalogueItems.length,ready=catalogueContext===sourceQueueContext();
  $('.app-shell').classList.toggle('selecting-materials',multiSelect);
  $('#selectionTotal').hidden=multiSelect;$('#selectAllControl').hidden=!multiSelect;$('#selectionCount').hidden=!multiSelect;
  $('#selectionTotal').textContent=`${total} 条`;
  $('#multiSelectBtn').textContent=multiSelect?'取消':'多选';$('#multiSelectBtn').setAttribute('aria-pressed',String(multiSelect));$('#multiSelectBtn').disabled=batchRunning||!ready||(!total&&!multiSelect);
  $('#batchBar').hidden=!multiSelect;
  $('#selectAll').checked=Boolean(total&&count===total);$('#selectAll').indeterminate=count>0&&count<total;$('#selectAll').disabled=batchRunning||!ready||!total;
  $('#selectAllLabel').textContent=`全选 ${total} 条`;$('#selectAll').setAttribute('aria-label',`全选当前筛选的 ${total} 条材料`);
  $('#selectionCount').textContent=batchRunning?batchProgress:`已选 ${count} 条`;
  for(const [id,visible] of [['batchRetryBtn',!trashCatalogue()&&!inFirstLibrary()],['batchTrashBtn',!trashCatalogue()],['batchRestoreBtn',trashCatalogue()],['batchPurgeBtn',trashCatalogue()]]){
    $('#'+id).hidden=!visible;$('#'+id).disabled=batchRunning||!ready||!count;
  }
  document.querySelectorAll('[data-select-id]').forEach(input=>{input.checked=checkedMaterials.has(input.dataset.selectId);input.disabled=batchRunning;input.closest('.material-card').classList.toggle('checked-for-batch',input.checked);});
  $('#batchPurgePreview').hidden=!purgeSelection||batchRunning;
  $('#confirmBatchPurge').disabled=batchRunning||!purgeSelection||$('#batchPurgeText').value!=='彻底删除';
  $('#batchFailures').hidden=!batchFailures.length;
  $('#batchFailureSummary').textContent=`${batchFailures.length} 条${batchFailures.some(m=>m.warning)?'需核对':'未完成'}`;
  $('#batchFailureList').innerHTML=batchFailures.map(m=>`<li><strong>${escape(m.title)}</strong><span>${escape(m.error)}</span></li>`).join('');
}
async function runMaterialBatch(action,targets=batchTargets(),confirmation){
  if(batchRunning||!targets.length)return;
  const context=sourceQueueContext();
  if(selectionScope!==context||catalogueContext!==context)throw new Error('筛选已改变，请重新选择材料');
  const queue=targets.some(m=>m.id===selected)?captureSourceQueue(selected):null;
  const failures=[],warnings=[];
  batchRunning=true;batchFailures=failures;batchProgress=`处理中 0 / ${targets.length}`;purgeSelection=null;renderSelectionControls();
  const succeeded=new Set();let uncertain=false,skipped=0,duplicates=0;
  try{
    if(queue&&dirty){await saveNotes();if(dirty||sourceQueueContext()!==context||selected!==queue.id)throw new Error('批注有新改动，请先保存后重试');targets=targets.map(m=>m.id===current.id?{...m,revision:current.revision}:m);}
    for(let offset=0;offset<targets.length;offset+=100){
      const chunk=targets.slice(offset,offset+100);
      try{
        const result=await api('/materials/batch-actions','POST',{action,items:chunk.map(m=>({id:m.id,revision:m.revision})),...(confirmation?{confirmation}:{})});
        for(const outcome of result.results){const target=chunk.find(m=>m.id===outcome.id);if(!target)continue;if(outcome.ok){succeeded.add(outcome.id);skipped+=Number(Boolean(outcome.skipped));duplicates+=Number(Boolean(outcome.duplicate));if(selectionScope===context)checkedMaterials.delete(outcome.id);if(outcome.warning)warnings.push({...target,warning:true,error:outcome.warning});}else failures.push({...target,error:outcome.error});}
      }catch(error){
        uncertain=true;failures.push(...targets.slice(offset).map(m=>({...m,error:`结果未确认：${error.message}。请重新勾选后重试。`})));break;
      }
      batchProgress=`处理中 ${Math.min(offset+100,targets.length)} / ${targets.length}`;renderSelectionControls();
    }
    if(action!=='retry'&&queue&&succeeded.has(queue.id))await continueCatalogue(queue,succeeded);else await refresh();
  }finally{batchRunning=false;batchFailures=selectionScope===context?[...failures,...warnings]:[];renderSelectionControls();}
  const label={trash:'移入回收站',restore:'恢复',purge:'彻底删除'}[action];
  if(action==='retry'){toast(`重试已排队 ${succeeded.size-skipped-duplicates} 条${duplicates?` · 已在队列 ${duplicates} 条`:''}${skipped?` · 已完整跳过 ${skipped} 条`:''}${failures.length?` · ${failures.length} 条未排队，请查看原因`:''}。采集结果见材料状态。`,Boolean(failures.length));return;}
  toast(`已${label} ${succeeded.size} 条${failures.length?`，${failures.length} 条${uncertain?'结果待核对':'未完成，请查看列表上方原因'}`:''}${warnings.length?`；${warnings.length} 条存档或清理需核对`:''}`,Boolean(failures.length||warnings.length));
}
function previewBatchPurge(){
  if(batchRunning||!checkedMaterials.size||!trashCatalogue()||catalogueContext!==sourceQueueContext())return;
  purgeSelection={context:sourceQueueContext(),targets:batchTargets()};$('#batchPurgeText').value='';
  $('#batchPurgeLabel').textContent=`彻底删除 ${purgeSelection.targets.length} 条及其专属附件，无法恢复。`;
  $('#batchPurgeNames').innerHTML=purgeSelection.targets.map(m=>`<li>${escape(m.title)}</li>`).join('');
  renderSelectionControls();$('#batchPurgeText').focus();
}
async function refresh() {
  const videoLibrary=!$('#platformFilter').value||['bilibili','youtube','douyin'].includes($('#platformFilter').value);
  syncLibraryNavigation();
  $('#captureFilter').hidden=!videoLibrary||inFirstLibrary();
  if(!videoLibrary)$('#captureFilter').value='';
  updateSelectionScope();
  const context=sourceQueueContext();
  const seq=++listSeq;
  const params=new URLSearchParams({state:inFirstLibrary()?layerPhase:filter,q:$('#search').value,origin:$('#originFilter').value,platform:$('#platformFilter').value,capture:$('#captureFilter').value,topic:topicFilter});
  if(inFirstLibrary())params.set('track',filter);
  const data=await api((inFirstLibrary()?'/first-layer?':'/materials?')+params);
  if(seq!==listSeq||context!==sourceQueueContext())return;
  renderTopics(data.topics||[]);
  $('#archiveCount').textContent=data.counts.source_archive||0;$('#callableCount').textContent=data.counts.callable||0;$('#digestCount').textContent=data.counts.digest||0;
  if(inFirstLibrary()){try{firstFolders=await api('/first-layer/folders');if(seq!==listSeq)return;$('#layerFolderPath').textContent=firstFolders[filter].path+(firstFolders[filter].available?'':'\n'+firstFolders[filter].error);}catch{$('#layerFolderPath').textContent='尚未配置知识库路径';}}
  if(seq!==listSeq||context!==sourceQueueContext())return;
  const total=data.counts.all||0;
  $('#referenceCount').textContent=data.counts.reference||0;$('#pendingCount').textContent=data.counts.pending||0; $('#doneCount').textContent=data.counts.done||0;$('#allCount').textContent=total;
  $('#reviewCount').textContent=data.counts.review||0;
  $('#laterCount').textContent=data.counts.later||0;
  $('#trashCount').textContent=data.counts.trash||0;$('#libraryTitle').textContent=topicFilter?topics[topicFilter]+'材料':($('#platformFilter').value?names[$('#platformFilter').value]:'跨平台')+'材料库';
  if(inFirstLibrary())$('#libraryTitle').textContent='第一层材料库';
  $('#listCount').textContent=data.items.length;
  $('#listTitle').textContent=($('#platformFilter').value?names[$('#platformFilter').value]+' · ':'')+({callable:'调用资料',digest:'消化暂存',source_archive:'已分流原文',all:'未分流收藏',pending:'待处理',later:'稍后整理',review:'整理待审',done:'已完成',reference:'资料备查',trash:'回收站'})[filter];
  $('#listFooter').textContent=inFirstLibrary()?`${data.items.length} 条 · 第一层材料，原始收藏另存`:filter==='later'?`${data.items.length} 条暂存材料 · 留待以后处理`:`${data.items.length} 条材料 · 原文与历史均已保留`;
  data.items.sort((a,b)=>Number(b.collection==='ready')-Number(a.collection==='ready')||b.updated.localeCompare(a.updated));
  catalogueItems=data.items;
  catalogueContext=context;
  const available=new Set(catalogueItems.map(m=>m.id));for(const id of checkedMaterials.keys())if(!available.has(id)){checkedMaterials.delete(id);purgeSelection=null;}
  renderSelectionControls();
  if(firstLoad&&data.items.length&&!matchMedia('(max-width:760px)').matches){
    firstLoad=false;let saved;try{saved=localStorage.getItem('selectedMaterial');}catch{}
    const candidate=data.items.find(m=>m.id===saved)||data.items.find(m=>m.collection==='ready')||data.items[0];
    await select(candidate.id,false,false);return;
  }
  firstLoad=false;
  const signature=JSON.stringify([data.items,selected,visibleLimit,multiSelect]);
  if(signature===listSignature)return;
  listSignature=signature;
  $('#materialList').innerHTML=data.items.length?data.items.slice(0,visibleLimit).map(materialCard).join('')+(data.items.length>visibleLimit?'<button id="loadMore" class="load-more">显示更多材料</button>':''):`<div class="list-empty">${icon('search')}<strong>${$('#search').value?'没有找到相关材料':'这个筛选下没有材料'}</strong><p>可以切换主题、平台或处理状态。</p></div>`;
  document.querySelectorAll('.material-row').forEach(b=>b.onclick=guard(()=>select(b.dataset.id)));
  document.querySelectorAll('[data-trash-id]').forEach(b=>b.onclick=busy(b,async()=>{if(b.dataset.restore==='true'){await purgeDialog(b.dataset.trashId);}else await removeMaterial(b.dataset.trashId);}));
  document.querySelectorAll('[data-select-id]').forEach(input=>input.onchange=()=>chooseBatchItem(input.dataset.selectId,input.checked));
  renderSelectionControls();
  $('#loadMore')?.addEventListener('click',guard(async()=>{visibleLimit+=80;await refresh();}));
}
function renderTopics(groups){
  const signature=JSON.stringify([groups,topicFilter]);if(signature===topicSignature)return;topicSignature=signature;
  const total=groups.reduce((sum,g)=>sum+g.count,0);
  $('#topicBar').innerHTML=[{id:'',label:'全部主题',count:total},...groups].map(g=>`<button data-topic="${escape(g.id)}" aria-pressed="${g.id===topicFilter}" class="${g.id===topicFilter?'active-topic':''}"><span>${escape(g.label)}</span><small>${g.count}</small></button>`).join('');
  $('#topicBar').querySelectorAll('[data-topic]').forEach(b=>b.onclick=guard(()=>chooseTopic(b.dataset.topic)));
}
async function chooseTopic(value){
  if(dirty){toast('请先保存当前批注，再切换主题。',true);return;}
  topicFilter=value;visibleLimit=80;firstLoad=true;
  try{localStorage.setItem('selectedTopic',value);}catch{}
  clearReader();await refresh();
}
async function select(id, force=false, openMobile=true) {
  if(dirty&&!force) {toast('批注尚未保存，请先保存后再切换材料。',true);return;}
  const seq=++detailSeq; const item=await api('/materials/'+id); if(seq!==detailSeq)return;
  if(dirty&&!force){toast('批注尚未保存，请先保存后再切换材料。',true);return;}
  if(selected!==id){annotationTrack=null;readerTab='transcript';processingMode=null;subtitleQuery='';playbackTime=0;}
  current=item;selected=id;dirty=false;renderDetail(item);
  try{localStorage.setItem('selectedMaterial',id);}catch{}
  if(openMobile)$('.app-shell').classList.add('reading-open');
  $('#readingPane').scrollTop=0;
  await refresh();
}
function safeLink(url){try{const u=new URL(url);return ['http:','https:'].includes(u.protocol)?escape(u.href):'#';}catch{return '#';}}
function inlineReadingText(text){
  let out='',end=0;
  for(const hit of String(text).matchAll(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g)){
    out+=escape(text.slice(end,hit.index))+`<a href="${safeLink(hit[2])}" target="_blank" rel="noopener noreferrer">${escape(hit[1])}</a>`;end=hit.index+hit[0].length;
  }
  return (out+escape(text.slice(end))).replace(/\n/g,'<br>');
}
function richContent(text,m,prefix="body"){
  let result='',end=0,images=[];const source=String(text||'');
  let paragraphIndex=0;
  const paragraphs=value=>value.trim().split(/\n\s*\n/).filter(Boolean).map(p=>{const key=prefix+':'+paragraphIndex++,unit=typeof bilingualVisible!=='undefined'&&bilingualVisible?m.reader_translation?.units?.[key]:null;return `<p>${inlineReadingText(p)}</p>${unit?`<p class="reading-translation" lang="${escape(unit.language)}" title="${escape(unit.source)}"><span class="translation-label">${unit.source.includes('平台')?'平台译文':'机器译文'}</span>${escape(unit.text).replace(/\n/g,'<br>')}</p>`:''}`;}).join('');
  let imageIndex=0,layout='';
  const flush=()=>{if(images.length){result+=`<div class="media-group ${images.length===1?'single':'multiple'} ${layout}" data-image-count="${images.length}">${images.join('')}</div>`;images=[];}};
  for(const hit of source.matchAll(/!\[([^\]\n]*)\]\(([^\s)]+)(?:\s+"[^"]*")?\)/g)){
    const before=source.slice(end,hit.index);if(before.trim()){flush();result+=paragraphs(before);}
    const asset=(m.content.media||[]).find(a=>a.status==='saved'&&a.path===hit[2]);
    if(asset){const mode=imageLayout(m,prefix,imageIndex++);if(images.length&&layout!==mode)flush();layout=mode;const url=`/api/materials/${encodeURIComponent(m.id)}/images/${asset.path.split('/').map(encodeURIComponent).join('/')}`;const caption=imageCaption(hit[1]);images.push(`<figure class="material-image"><button type="button" class="image-open" data-image-src="${url}" aria-label="查看完整图片"><img src="${url}" alt="${escape(hit[1]||'材料图片')}" loading="lazy" decoding="async"><span class="image-expand">查看全图</span></button>${caption?`<figcaption>${escape(caption)}</figcaption>`:''}</figure>`);}
    else{flush();result+=`<p><a href="${safeLink(hit[2])}" target="_blank" rel="noopener noreferrer">图片来源：${escape(hit[1]||'图片')}（未存档）</a></p>`;}
    end=hit.index+hit[0].length;
  }
  flush();return result+paragraphs(source.slice(end));
}
function imageLayout(m,prefix,index){
  if(prefix.startsWith('comment:'))return 'comment-gallery';
  const c=m.content||{};
  if(m.platform==='heybox')return c.media_kind==='gallery_post'||index<Number(c.gallery_count||0)?'heybox-gallery':'article-images';
  if(c.article||c.media_kind==='article')return 'article-images';
  if(m.platform==='x')return 'x-photos';
  if(m.platform==='xiaohongshu')return 'note-gallery';
  return 'article-images';
}
function imageCaption(value){const caption=String(value||'').trim();return /^(?:帖子图片|材料图片|图片|原图|评论图片|image|photo)(?:\s*\d+)?$/i.test(caption)?'':caption;}
function renderTranscript(m){
  if(!$('#videoWorkbench'))$('#transcriptSection').classList.add('standalone-captions');
  renderVideoTranscript(m);
}
function renderReadingPreview(m){
  const p=m.reading_preview;
  if(!p?.reading_only||p.model_used!==false||!p.text)return '';
  return `<details class="reading-preview" open><summary><span>速览</span><span class="preview-source">${escape(p.source)}${icon('chevron')}</span></summary><div>${p.text.split('\n').filter(Boolean).map(text=>`<p>${escape(text)}</p>`).join('')}</div></details>`;
}
function renderDetail(m) {
  captionList?.destroy();captionList=null;
  nativePlayback=false;
  playbackRequest?.abort();playbackRequest=null;videoController?.destroy();videoController=null;embedResize?.disconnect();embedResize=null;
  const video=VideoReader.target(m);
  $('#readingPane').classList.toggle('video-reader',Boolean(video));
  $('#readingPane').classList.toggle('text-reader',!video);
  const ready=m.collection==='ready'&&!m.trashed, segments=m.content.segments||[], comments=m.content.comments||[];
  const language=({en:'English',zh:'中文','zh-Hans':'简体中文','zh-CN':'简体中文','ai-zh':'中文'})[m.content.language]||m.content.language||'未指定语言';
  const subtitleSource=m.content.subtitle_source||'无字幕';
  const transcriptTitle=subtitleSource.includes('机器转写')||subtitleSource.includes('本机')?(subtitleSource.includes('本机')?'本机机器转写':'机器转写（非平台字幕）'):subtitleSource.includes('自动')?'平台自动字幕':subtitleSource.includes('用户导入')?'导入的时间轴字幕':subtitleSource.includes('平台')?'平台原始字幕':'时间轴字幕';
  const originalBody=`<div class="prose rich-prose">${richContent(m.body||'尚未取得原文。链接已经保留，可以重试或补充材料。',m)}</div><a class="source-link" href="${safeLink(m.url)}" target="_blank" rel="noopener noreferrer">${icon('arrow')}查看完整原链接</a>`;
  $('#detail').innerHTML=`<div class="reader-toolbar"><button class="mobile-back" id="backToList">${icon('back')}材料列表</button><span class="breadcrumb">材料 <i>/</i><strong>${escape(platformName(m))}</strong></span><div class="toolbar-actions"><button id="deleteAction" class="icon-button" aria-label="${m.trashed?'恢复材料':'删除材料'}" title="${m.trashed?'恢复材料':'删除材料，可恢复'}">${icon(m.trashed?'history':'trash')}</button><button id="historyAction" class="icon-button" aria-label="查看处理历史" title="查看处理历史">${icon('history')}</button><button id="supplementAction" class="icon-button" aria-label="补充原文或字幕" title="补充原文 / 字幕">${icon('edit')}</button><a href="${safeLink(m.url)}" target="_blank" rel="noopener noreferrer">查看原链接 ${icon('arrow')}</a></div></div>
  <div class="reader-inner" data-reader-platform="${escape(m.platform)}"><header class="detail-header"><div class="detail-meta">${platformIcon(platformKey(m))}<span>${escape(platformName(m))}</span><span class="meta-divider"></span><span class="badge">${m.first_layer?((m.first_layer.track==='callable'?'调用资料':'消化暂存')+' · '+(m.first_layer.level===2?'第二层':'第一层')):m.origin==='favorite'?'我的收藏':'非收藏链接'}</span><span class="detail-state ${m.collection}">${m.trashed?'回收站':m.first_layer?escape(captureLabel(m)):(m.reading_intent||m.content?.reading_intent)==='reference'?'资料备查':m.processing==='done'?'已完成':m.processing==='later'?'稍后整理':escape(captureLabel(m))}</span></div><h2>${escape(displayTitle(m))}</h2><p class="detail-caption">${segments.length?`${escape(transcriptTitle)} · ${escape(language)} · ${segments.length} 段`:''}<button id="topicAction" class="topic-action" aria-label="修改内容主题" title="${m.topic_source==='manual'?'手动分类':'本机规则粗分，可改类'}">${escape(topics[m.topic]||'未分类')}${icon('chevron')}</button><span class="collected-date">${m.first_layer?'第一层保存于':'收集于'} ${new Date(m.created).toLocaleDateString('zh-CN')}</span></p><div class="reader-command-bar"><div class="detail-actions"><button id="aiAction" ${ready?'':'disabled'}>${icon('sparkles')}AI 整理</button><button id="readAction">${icon('book')}我的理解</button><button id="pushAction" ${m.trashed?'disabled':''}>${icon('export')}用于下一步</button></div><button id="laterAction" class="later-action" ${m.trashed?'disabled':''}>${icon(m.processing==='later'?'history':'clock')}${m.processing==='later'?'放回待处理':'稍后整理'}</button></div></header>
  <details class="provenance"><summary><span>来源与采集记录</span><span class="disclosure-meta">${icon('chevron')}</span></summary><div class="provenance-body"><strong>${segments.length?transcriptTitle:'原文存档'}</strong><p>${escape(m.content.source||'正在等待取得原文')}</p>${segments.length?`<p>字幕来源：${escape(subtitleSource)} · 保留完整时间轴</p>`:''}${m.content.favorite_folders?.length?`<p>收藏夹：${m.content.favorite_folders.map(f=>escape(f.title)).join('、')}</p>`:''}${ready&&m.content.warning?`<p>${escape(m.content.warning)}</p>`:''}<a class="download-link" href="/api/materials/${m.id}/markdown" aria-label="下载 Markdown" title="下载 Markdown">${icon('download')}<span>下载 Markdown</span></a></div></details>
  <div id="captureProgress" class="capture-progress" role="status" ${m.progress?.message?'':'hidden'}>${escape(m.progress?.message||'')}</div>
  ${m.error||(!ready&&m.content.warning)?`<div class="warning">${escape(m.error||m.content.warning)}</div>`:''}
  ${!ready&&!m.trashed?`<div class="minor-actions"><button id="retryAction">重试收集</button>${m.platform!=='web'&&names[m.platform]&&/验证|验证码|限流|拒绝/.test(m.error||'')?'<button id="verifyAccountAction">登录验证</button>':''}<button id="supplementInline">补充原文 / 字幕</button></div>`:''}
  ${renderReadingPreview(m)}
  ${video?`<div id="videoWorkbench" class="video-workbench ${video.platform==='douyin'?'douyin-player':''}"><section class="video-column" aria-label="平台视频"><div class="video-frame" data-player-platform="${video.platform}"><iframe id="platformPlayer" title="${escape(platformName(m))}原站视频播放器" scrolling="no" allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe></div></section><div class="caption-wrap"><section id="transcriptSection" class="caption-panel" aria-label="逐句字幕"></section></div><button id="exitVideo" class="fullscreen-exit" aria-label="退出视频字幕全屏">${icon('close')}退出全屏</button></div><div class="video-notes"><div class="player-caption"><span id="playerStatus" role="status">原站嵌入播放 · 不下载视频</span><div class="player-tools"><button id="focusVideo" class="text-button">${icon('expand')}全屏阅读</button>${video.platform==='douyin'?'<button id="retryPlayback" class="text-button" hidden>重试页内播放</button>':''}<a href="${safeLink(m.content.resolved_url||m.url)}" target="_blank" rel="noopener noreferrer">原站 ${icon('arrow')}</a></div></div><details class="video-description"><summary><span>视频说明与封面</span><span class="disclosure-meta">${icon('chevron')}</span></summary><section id="originalSection">${originalBody}</section></details></div>`:segments.length?`<div class="reading-controls"><div class="reader-tabs" role="tablist" aria-label="视频材料阅读方式"><button id="transcriptTab" role="tab" aria-controls="transcriptSection" data-reader-tab="transcript" aria-selected="${readerTab==='transcript'}">逐段字幕</button><button id="originalTab" role="tab" aria-controls="originalSection" data-reader-tab="original" aria-selected="${readerTab==='original'}">视频说明</button></div></div>
  <section id="transcriptSection" role="tabpanel" aria-labelledby="transcriptTab" ${readerTab==='original'?'hidden':''}></section>
  <section id="originalSection" role="tabpanel" aria-labelledby="originalTab" ${readerTab==='transcript'?'hidden':''}>${originalBody}</section>`:
  `<section id="originalSection" aria-label="原文">${originalBody}</section>`}
  ${m.content.comments_status?`<details class="comments-section"><summary><span>${icon('comments')}部分评论 / 回复</span><span class="disclosure-meta">${escape(/失败|中断/.test(m.content.comments_status)?'回复读取失败':/尚未|未读取/.test(m.content.comments_status)?'等待补采回复':comments.length+' 条已存档')} ${icon('chevron')}</span></summary><div id="commentsBody" class="comments-body">${commentsMarkup(m)}</div></details>`:''}
  <section class="notes" id="notesSection"><div class="section-heading"><h3>${icon('file')}我的批注</h3></div><div class="note-editor"><label class="sr-only" for="notesText">我的批注</label><textarea id="notesText" ${m.trashed?'disabled':''} placeholder="用自己的话，留下你的理解。">${escape(m.notes)}</textarea><div class="note-footer"><span id="saveState" class="muted">${m.notes?'理解已保存在本机':'与原文一起保留，仅在本机保存。'}</span><button id="saveNotes" class="primary" ${m.trashed?'disabled':''}>保存批注</button></div></div><div class="finish-row"><button id="completeAction" ${ready?'':'disabled'}>${icon(m.processing==='done'?'history':'check-circle')}${m.processing==='done'?'重新放回待处理':'整理完成，移入已完成'}</button></div></section>
  <details class="summary-block" id="summarySection" ${m.summary?'open':''}><summary><span>${icon('sparkles')}AI 整理</span><span class="disclosure-meta">${m.summary?'已生成':'尚未生成'} ${icon('chevron')}</span></summary><div class="prose">${escape(m.summary||'点击上方「AI 整理」，获取摘要、观点与建议。首次使用请在设置中配置模型。')}</div></details>
  <details class="history" id="historySection"><summary><span>${icon('history')}原文与处理历史</span><span class="disclosure-meta">${m.events.length} 条记录 ${icon('chevron')}</span></summary><div class="history-body"><div class="minor-actions"><button id="versionsAction">查看历史原文</button><button id="refreshContent">重新采集图片与评论</button></div>${m.events.map(e=>`<div class="event">${new Date(e.created).toLocaleString('zh-CN')} · ${escape(eventName(e.kind))}<code>${escape(e.detail)}</code></div>`).join('')}</div></details><div class="reader-bottom"><span>原文保留 · 操作可追溯 · 确认后导出</span><a href="/docs" target="_blank" rel="noopener">接口文档</a></div></div>`;
  if(!video&&!segments.length){$('.detail-caption').insertAdjacentHTML('afterend',`<div class="text-reading-tools">${bilingualSwitch()}<span id="bilingualStatus" role="status"></span><button id="retryTranslation" class="text-button" hidden>重试译文</button></div>`);bindBilingual(m);}
  if(video){
    $('#focusVideo').onclick=guard(async()=>{if(!$('#videoWorkbench').requestFullscreen)throw new Error('当前浏览器不支持全屏，请使用原站播放器。');await $('#videoWorkbench').requestFullscreen();});
    $('#exitVideo').onclick=guard(()=>document.exitFullscreen());
    $('#retryPlayback')?.addEventListener('click',busy($('#retryPlayback'),()=>startDouyinPlayback(m,video,true)));
    renderVideoTranscript(m);
    videoMaterial=m.id;
    if(video.platform==='douyin'){
      startDouyinPlayback(m,video);
    }else videoController=VideoReader.mount($('#platformPlayer'),video,{origin:location.origin,
      onStatus:message=>{if(current?.id===m.id&&$('#playerStatus'))$('#playerStatus').textContent=message;},
      onTime:time=>{if(current?.id===m.id){playbackTime=time;highlightCue(m,time);}}
    });
  }else if(segments.length)renderTranscript(m);
  $('#topicAction').disabled=Boolean(m.trashed);$('#topicAction').onclick=guard(async()=>{if(dirty)await saveNotes();topicDialog();});
  $('#deleteAction').onclick=guard(async()=>{if(m.trashed){await api(`/materials/${m.id}/restore`,'POST',{});toast('已恢复材料');clearReader();await refresh();}else await removeMaterial(m.id);});
  if(m.trashed){
    $('.toolbar-actions').insertAdjacentHTML('afterbegin','<button id="purgeAction" class="danger">彻底删除</button>');
    $('#purgeAction').onclick=guard(()=>purgeDialog(m.id));
  }else{
    $('.provenance-body').insertAdjacentHTML('beforeend','<button id="archiveToVault">保存到 资料文件夹</button>');
    $('#archiveToVault').onclick=guard(async()=>{if(dirty)await saveNotes();await previewExport('obsidian',false);});
  }
  $('#supplementAction').disabled=Boolean(m.trashed);$('#refreshContent').disabled=Boolean(m.trashed);
  $('#notesText').oninput=()=>{dirty=$('#notesText').value!==notesBaseline;$('#saveState').textContent=dirty?'未保存':'已保存';KnowledgeUI.invalidateFirstPreview();};
  $('#saveNotes').onclick=busy($('#saveNotes'),saveNotes);
  $('#readAction').onclick=()=>{if(!m.first_layer){openAnnotation('callable');return;}openProcessing(processingMode==='notes'?null:'notes');if(processingMode==='notes')$('#notesText').focus();};
  $('#aiAction').onclick=()=>{if(!m.first_layer){openAnnotation('digest');return;}openProcessing(processingMode==='ai'?null:'ai');};
  $('#completeAction').onclick=busy($('#completeAction'),async()=>{if(dirty)await saveNotes();await api(`/materials/${selected}/status`,'POST',{state:current.processing==='done'?'pending':'done',revision:current.revision});toast(m.processing==='done'?'已放回待处理':'已完成，原文与历史仍保留。');await select(selected,true);});
  $('#laterAction').onclick=busy($('#laterAction'),async()=>{if(dirty)await saveNotes();const next=current.processing==='later'?'pending':'later';await api(`/materials/${selected}/status`,'POST',{state:next,revision:current.revision});toast(next==='later'?'已放入稍后整理':'已放回待处理');await select(selected,true);$('.detail-state')?.classList.add('state-feedback');});
  $('#supplementAction').onclick=()=>materialDialog(current);
  $('#supplementInline')?.addEventListener('click',()=>materialDialog(current));
  $('#historyAction').onclick=()=>{$('#historySection').open=true;$('#historySection').scrollIntoView({behavior:'smooth',block:'start'});};
  const setReaderTab=tab=>{
    readerTab=tab;
    $('#transcriptSection').hidden=tab!=='transcript';
    $('#originalSection').hidden=tab!=='original';
    document.querySelectorAll('[data-reader-tab]').forEach(b=>{const active=b.dataset.readerTab===tab;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;});
  };
  if(segments.length&&!video){
    setReaderTab(readerTab);
    document.querySelectorAll('[data-reader-tab]').forEach(b=>{
      b.onclick=()=>setReaderTab(b.dataset.readerTab);
      b.onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const tab=e.key==='Home'?'transcript':e.key==='End'?'original':readerTab==='transcript'?'original':'transcript';setReaderTab(tab);$(`[data-reader-tab="${tab}"]`).focus();}};
    });
  }
  $('#backToList').onclick=()=>{$('.app-shell').classList.remove('reading-open');$('.app-shell').classList.remove('sidebar-collapsed');};
  $('#retryAction')?.addEventListener('click',busy($('#retryAction'),async()=>{const id=m.id;if(selected!==id)return;if(dirty)await saveNotes();if(selected!==id||dirty)throw Error('材料或批注已改变，请重新重试');const r=await api(`/materials/${id}/retry`,'POST',{transcribe:true});toast(r.kind==='images'?'图片补存已排队，原文和批注保留':'重试已排队；遇到验证会暂停');if(selected===id&&!dirty)await select(id,true);else await refresh();}));
  $('#verifyAccountAction')?.addEventListener('click',guard(()=>favoritesDialog(m.platform,m.url)));
  $('#pushAction').onclick=guard(async()=>{if(dirty)await saveNotes();await pushDialog();});
  $('#refreshContent').onclick=busy($('#refreshContent'),async()=>{if(dirty)await saveNotes();await api(`/materials/${selected}/retry`,'POST',{refresh:true});toast('已排队重新采集，旧原文与理解继续保留。');await select(selected,true);});
  $('#versionsAction').onclick=guard(async()=>{const versions=await api(`/materials/${selected}/versions`);dialog('历史原文',versions.map(v=>{const c=JSON.parse(v.content_json);return `<details class="capability"><summary>${new Date(v.created).toLocaleString('zh-CN')} · ${escape(c.content.source)}</summary><pre class="preview">${escape(JSON.stringify(c,null,2))}</pre></details>`;}).join(''));});
  readingDesk(m);
}

async function startDouyinPlayback(m,spec,refresh=false){
  playbackRequest?.abort();videoController?.destroy();videoController=null;embedResize?.disconnect();embedResize=null;
  const request=new AbortController();playbackRequest=request;
  nativePlayback=false;
  const host=$('.video-frame'),frame=$('#platformPlayer');host.classList.add('native-stream');host.classList.remove('fallback-embed');
  frame.hidden=true;host.querySelector('#directPlayer')?.remove();
  const media=m.content.media?.find(a=>a.status==='saved');
  host.insertAdjacentHTML('beforeend',`<video id="directPlayer" controls controlslist="nodownload" playsinline preload="metadata" ${media?`poster="${materialImageUrl(m.id,media.path)}"`:''} aria-label="抖音视频在线播放"></video>`);
  const status=text=>{if(playbackRequest===request&&current?.id===m.id&&$('#playerStatus'))$('#playerStatus').textContent=text;};
  status('正在取得平台在线播放地址；本工具不保存视频文件。');
  const fallback=message=>{
    if(request.signal.aborted||playbackRequest!==request||current?.id!==m.id)return;
    videoController?.destroy();videoController=null;host.querySelector('#directPlayer')?.remove();host.classList.remove('native-stream');host.classList.add('fallback-embed');frame.hidden=false;
    nativePlayback=false;
    const fit=()=>host.style.setProperty('--embed-scale',String(Math.min(host.clientWidth/324,host.clientHeight/720)));
    fit();embedResize=new ResizeObserver(fit);embedResize.observe(host);
    videoController=VideoReader.mount(frame,spec,{origin:location.origin,onStatus:()=>status(message+' 此模式不能按字幕定位。')});
    $('#retryPlayback')?.removeAttribute('hidden');
  };
  try{
    const response=await fetch(`/api/materials/${encodeURIComponent(m.id)}/playback`,{method:'POST',headers:{'X-Local-Request':'1','Content-Type':'application/json'},body:JSON.stringify({refresh}),signal:request.signal});
    const result=await response.json();
    if(request.signal.aborted||playbackRequest!==request||current?.id!==m.id)return;
    if(!response.ok||!['direct','stream'].includes(result.mode)){fallback((result.notice||'这次未取得可定位的视频流。')+(result.reason?' '+result.reason:''));return;}
    videoController=VideoReader.mountNative($('#directPlayer'),result.url,{onStatus:status,
      onTime:time=>{if(playbackRequest===request&&current?.id===m.id){playbackTime=time;highlightCue(m,time);}},
      onReady:()=>{if(playbackRequest===request&&current?.id===m.id){nativePlayback=true;document.querySelectorAll('.subtitle-cue').forEach(b=>b.setAttribute('aria-label','播放 '+shortTime(Number(b.dataset.start))+'：'+b.querySelector('.cue-text').textContent));}},
      onFailure:()=>fallback('这次的视频流加载失败，保留原站播放器。')});
    status('平台视频正在加载，加载后可点击字幕定位。');
  }catch(e){if(e.name!=='AbortError')fallback('这次未取得可定位的视频流，保留原站播放器。');}
}
function bilingualSwitch(){return `<button class="bilingual-switch" id="bilingualToggle" role="switch" aria-label="中英双语阅读，包含回复" aria-checked="${bilingualVisible}"><span class="switch-track" aria-hidden="true"></span>双语</button>`;}
function commentsMarkup(m){
  const comments=m.content.comments||[];
  return `<p class="muted">${escape(m.content.comments_status||'')}${bilingualVisible?' · 双语开关同样作用于已存档回复':''}</p>${comments.map((c,i)=>`<article class="comment"><div class="comment-meta"><strong>${escape(c.author||'未署名')}</strong><a href="${safeLink(c.url||m.url)}" target="_blank" rel="noopener noreferrer">查看来源 ${icon('arrow')}</a></div><div class="prose rich-prose">${richContent(c.body,m,'comment:'+i)}</div></article>`).join('')}${comments.length?'':'<p class="muted">当前未取得可存档评论。</p>'}`;
}
function redrawReadingText(m){
  const prose=$('#originalSection .prose');if(prose)prose.innerHTML=richContent(m.body||'尚未取得原文。链接已经保留，可以重试或补充材料。',m);
  if($('#commentsBody'))$('#commentsBody').innerHTML=commentsMarkup(m);
}
function bindBilingual(m){
  $('#bilingualToggle').onclick=guard(async()=>{
    const anchor=captionList?.anchor();bilingualVisible=!bilingualVisible;try{localStorage.setItem('bilingualVisible',String(bilingualVisible));}catch{}
    $('#bilingualToggle').setAttribute('aria-checked',String(bilingualVisible));
    if($('#transcriptSection')&&(m.content.segments?.length||$('#videoWorkbench')))renderVideoTranscript(m,anchor);
    redrawReadingText(m);updateTranslationJob(m);
    if(bilingualVisible)await ensureBilingual(m);
  });
  $('#retryTranslation').onclick=guard(async()=>{translationRequests.delete(m.id);await ensureBilingual(m);});
  updateTranslationJob(m);
  if(bilingualVisible)ensureBilingual(m).catch(error=>{if(current?.id===m.id){$('#bilingualStatus').textContent=error.message;$('#retryTranslation').hidden=false;}});
}
async function ensureBilingual(m){
  if(!bilingualVisible||m.trashed||m.reader_translation||translationRequests.has(m.id)||['queued','running'].includes(m.translation_job?.state))return;
  translationRequests.add(m.id);
  try{
    const result=await api(`/materials/${m.id}/bilingual`,'POST',{});if(current?.id!==m.id)return;
    if(result.cached){const latest=await api('/materials/'+m.id);acceptTranslation(latest);}
    else{m.translation_job={id:result.job_id,state:'queued',error:'',progress:{}};updateTranslationJob(m);}
  }catch(error){if(current?.id===m.id){$('#bilingualStatus').textContent=error.message;$('#retryTranslation').hidden=false;}throw error;}
}
function updateTranslationJob(m){
  const status=$('#bilingualStatus'),retry=$('#retryTranslation');if(!status)return;
  const job=m.translation_job,active=['queued','running'].includes(job?.state);
  status.hidden=!bilingualVisible;if(retry)retry.hidden=!bilingualVisible||job?.state!=='failed';
  status.textContent=m.reader_translation?(m.reader_translation.complete?'中英原文 + 译文 · 包括已存档回复':'部分译文已准备；非中英字幕未翻译，原文保留'):active?(job.progress?.message||'双语正在排队，原文可继续阅读'):job?.state==='failed'?'双语未完成：'+job.error:'开启后本机翻译中英正文、字幕及已存档回复';
}
function translationOnly(a,b){
  if(!a||['body','title','collection','processing','error','notes','summary','trashed'].some(k=>a[k]!==b[k]))return false;
  const strip=value=>{const c={...value};delete c.reader_translation;delete c.subtitle_tracks;delete c.bilingual_notice;return JSON.stringify(c);};
  return strip(a.content)===strip(b.content);
}
function acceptTranslation(m){
  if(current?.id!==m.id)return;
  const anchor=captionList?.anchor();Object.assign(current,{content:m.content,reader_translation:m.reader_translation,translation_job:m.translation_job,subtitle_job:m.subtitle_job,revision:m.revision,events:m.events});
  if($('#transcriptSection')&&(m.content.segments?.length||$('#videoWorkbench')))renderVideoTranscript(current,anchor);
  redrawReadingText(current);updateTranslationJob(current);
}
function renderVideoTranscript(m,restore){
  const anchor=restore||captionList?.anchor();captionList?.destroy();captionList=null;
  const all=m.content.segments||[],track=(m.content.subtitle_tracks||[]).find(t=>t.segments?.length),query=subtitleQuery.trim().toLowerCase(),spec=VideoReader.target(m);
  const rows=all.map((s,i)=>{const unit=bilingualVisible?m.reader_translation?.units?.['caption:'+i]:null;return {...s,sourceIndex:i,translation:bilingualVisible?(unit?.text||VideoReader.translationFor(s,track)):'',translationSource:unit?.source||track?.source||'',translationLanguage:unit?.language||track?.language||''};});
  const results=query?rows.filter(s=>(s.text+' '+s.translation).toLowerCase().includes(query)):rows;
  const last=all.reduce((end,s)=>Math.max(end,s.end),0),duration=m.content.duration||m.content.transcription?.duration;
  const primary=m.content.subtitle_source||'尚无字幕',timing=m.content.audio_validation?.duration_matches?' · 音频时长已核对':m.content.transcription?' · 此历史记录未核对音频时长':'';
  const sourceLabel=m.content.transcription?'机器转写 · '+(m.content.transcription.model||'模型未声明'):primary.includes('自动')?'平台自动字幕':primary.includes('平台')?'平台字幕':'字幕来源';
  $('#transcriptSection').innerHTML=`<header class="caption-header"><div class="caption-heading"><h3>${bilingualVisible?'双语字幕':'逐句字幕'}</h3><span>${all.length} 段 · ${shortTime(last)}${duration?' / 视频 '+shortTime(duration):''}</span></div><a class="download-link" href="/api/materials/${m.id}/markdown" aria-label="下载包含完整字幕的 Markdown">${icon('download')}</a></header>
    <div class="caption-tools"><div class="search-box">${icon('search')}<label class="sr-only" for="subtitleSearch">搜索字幕</label><input id="subtitleSearch" type="search" placeholder="搜索一句字幕" value="${escape(subtitleQuery)}" autocomplete="off"></div><div class="caption-reading-tools">${bilingualSwitch()}${spec?.liveTime||m.platform==='douyin'?`<label class="follow-control"><input id="followPlayback" type="checkbox" ${followPlayback?'checked':''}>跟随播放</label>`:''}<button id="captionFirst" class="text-button" aria-label="滚动到第一句字幕">开头</button><button id="captionLast" class="text-button" aria-label="滚动到最后一句字幕">末尾</button></div></div>
    <div id="captionScroll" class="caption-scroll" tabindex="0" aria-label="完整字幕，连续滚动">${results.length?'':`<div class="caption-empty"><p>${query?'没有找到这句话，可换一个关键词。':'尚未取得可读字幕。'}</p><p>${escape(query?'':m.content.warning||captureLabel(m))}</p></div>`}</div>
    <footer class="caption-source"><span id="bilingualStatus" role="status"></span><button id="retryTranslation" class="text-button" hidden>重试译文</button><span id="subtitleJobStatus" role="status" hidden></span>${query?`<span>找到 ${results.length} 句</span>`:''}<details class="caption-info"><summary><span>${escape(sourceLabel)} · 来源与阅读设置</span>${icon('chevron')}</summary><div class="caption-info-body"><span>原轨：${escape(primary)}${m.content.transcription?.model?' · '+escape(m.content.transcription.model):''}${timing}</span>${track?`<span>平台第二轨：${escape(track.source)}</span>`:''}<span>缺少平台译文时使用本机机器翻译；译文可能有误，原文和时间轴保留。</span>${['bilibili','youtube'].includes(m.platform)?'<button id="fetchBilingual" class="text-button">读取平台第二轨</button>':''}<span>完整字幕、译文与回复保留在 Markdown</span></div></details></footer>`;
  if(results.length){
    captionList=TranscriptList.mount($('#captionScroll'),results,(s,i)=>`<button class="subtitle-cue" data-virtual-index="${i}" data-source-index="${s.sourceIndex}" data-start="${s.start}" data-end="${s.end}" aria-label="${spec?.seek||(m.platform==='douyin'&&nativePlayback)?'播放':'查看'} ${shortTime(s.start)}：${escape(s.text)}" title="${formatTime(s.start)} → ${formatTime(s.end)}"><time>${shortTime(s.start)}</time><span class="cue-text"><span>${escape(s.text.replace(/\s*\n\s*/g,' '))}</span>${s.translation?`<span class="cue-translation" lang="${escape(s.translationLanguage)}" title="${escape(s.translationSource)}"><span class="translation-label">${s.translationSource.includes('平台')?'平台译文':'机器译文'}</span>${escape(s.translation)}</span>`:''}</span></button>`,{
      onManualScroll:()=>{followPlayback=false;if($('#followPlayback'))$('#followPlayback').checked=false;},
      onRender:()=>highlightCue(m,playbackTime,false),
      onSelect:(s,button)=>{document.querySelectorAll('.subtitle-cue').forEach(b=>b.classList.toggle('selected-cue',b===button));if(!videoController){toast('这条材料没有页内播放器；原文时间轴仍完整保留。');return;}followPlayback=true;if($('#followPlayback'))$('#followPlayback').checked=true;if(!videoController.seek(s.start))toast('这次未能定位，请查看播放器提示。');}
    });if(anchor)captionList.restore(anchor);
  }
  $('#captionFirst').onclick=()=>{followPlayback=false;captionList?.first();if($('#followPlayback'))$('#followPlayback').checked=false;};
  $('#captionLast').onclick=()=>{followPlayback=false;captionList?.last();if($('#followPlayback'))$('#followPlayback').checked=false;};
  let searchDelay;$('#subtitleSearch').oninput=e=>{const position=e.target.selectionStart;subtitleQuery=e.target.value;clearTimeout(searchDelay);searchDelay=setTimeout(()=>{if(current?.id!==m.id)return;followPlayback=false;renderVideoTranscript(m,{sourceIndex:0,offset:0});$('#subtitleSearch').focus();try{$('#subtitleSearch').setSelectionRange(position,position);}catch{}},180);};
  $('#followPlayback')?.addEventListener('change',e=>{followPlayback=e.target.checked;if(followPlayback)highlightCue(m,playbackTime);});
  $('#fetchBilingual')?.addEventListener('click',guard(async()=>{const result=await api(`/materials/${m.id}/subtitle-tracks`,'POST');m.subtitle_job={id:result.job_id,state:'queued',error:''};updateSubtitleJob(m);}));
  bindBilingual(m);highlightCue(m,playbackTime,false);updateSubtitleJob(m);
}
function updateSubtitleJob(m){
  const job=m.subtitle_job,status=$('#subtitleJobStatus'),button=$('#fetchBilingual');
  if(!status)return;
  const active=job&&['queued','running'].includes(job.state);
  if(button)button.disabled=Boolean(m.trashed||active);
  status.hidden=!job||job.state==='done';
  status.textContent=active?(job.state==='queued'?'第二语言字幕等待读取…':'正在读取第二语言字幕…'):job?.state==='failed'?'双语读取失败：'+job.error+'；原字幕保留，可重试。':job?.state==='cancelled'?'双语读取已取消':'';
}
function highlightCue(m,time,canFollow=true){
  if(followPlayback&&canFollow&&!subtitleQuery)captionList?.follow(time);
  document.querySelectorAll('.subtitle-cue').forEach(b=>{const hit=time>=Number(b.dataset.start)&&time<Number(b.dataset.end);b.classList.toggle('playing-cue',hit);});
}

function openAnnotation(track){
  if(dirty&&annotationTrack!==track){toast('先保存当前批注，再切换方向。',true);return;}
  if(processingMode==='notes'&&annotationTrack===track){openProcessing(null);return;}
  if(dirty){openProcessing('notes');$('#notesText').focus();return;}
  annotationTrack=track;
  const notes=current.content.annotations||{};
  $('#notesText').value=notes[track]??(Object.keys(notes).length?'':current.notes);
  notesBaseline=$('#notesText').value;dirty=false;$('#saveState').textContent=notes[track]!==undefined?'已保存':notesBaseline?'草稿':'未保存';
  openProcessing('notes');$('#notesText').focus();
}
function openProcessing(mode){
  processingMode=mode;
  const panel=$('#processingPanel');
  panel.classList.toggle('open',Boolean(mode));panel.inert=!mode;panel.setAttribute('aria-hidden',String(!mode));
  $('#processingTitle').textContent=mode==='ai'?'AI 整理':'批注';
  $('#processingDock').hidden=!current||Boolean(mode&&!current.first_layer);
  panel.classList.toggle('annotation-panel',!current?.first_layer);
  if($('#notesSection'))$('#notesSection').hidden=!['notes','ai'].includes(mode);
  if($('#summarySection')){$('#summarySection').hidden=mode!=='ai';if(mode==='ai')$('#summarySection').open=true;}
  if($('#annotationSubmit'))$('#annotationSubmit').hidden=mode!=='notes';
  if($('#firstLayerChoices'))$('#firstLayerChoices').hidden=mode!=='notes';
  $('#saveCallable')?.classList.toggle('primary',annotationTrack!=='digest');
  $('#saveDigest')?.classList.toggle('primary',annotationTrack==='digest');
  if(mode==='ai')$('#processingPanelBody').append($('#summarySection'),$('#notesSection'));
  if($('#knowledgeSection'))$('#processingPanelBody').append($('#knowledgeSection'));
  $('#aiAction')?.setAttribute('aria-expanded',String(mode==='ai'||mode==='notes'&&!current?.first_layer&&annotationTrack==='digest'));
  $('#readAction')?.setAttribute('aria-expanded',String(mode==='notes'&&(current?.first_layer||annotationTrack==='callable')));
}
function readingDesk(m){
  const inner=$('.reader-inner'), toolbar=$('.reader-toolbar'), actions=$('.detail-actions');
  $('.detail-header h2').classList.toggle('long-title',displayTitle(m).length>60);
  inner.prepend(toolbar);
  toolbar.prepend($('.detail-meta'));
  $('.toolbar-actions').prepend($('#laterAction'));
  $('#processingDock').replaceChildren(actions);$('#processingDock').hidden=false;
  actions.append($('#readAction'),$('#aiAction'),$('#pushAction'));
  if(!m.first_layer)actions.append($('#laterAction'));
  if(!m.first_layer)$('#aiAction').innerHTML=icon('bookmark');
  $('#processingDock').classList.toggle('annotation-dock',!m.first_layer);
  const labels=m.first_layer?{readAction:'批注',aiAction:'AI 整理',pushAction:'材料归位'}:{readAction:'留作资料',aiAction:'以后细读',laterAction:m.processing==='later'?'继续处理':'稍后整理'};
  $('#pushAction').hidden=!m.first_layer;
  for(const [id,title] of Object.entries(labels)){
    const button=$('#'+id), symbol=button.querySelector('svg');
    button.replaceChildren(symbol);
    button.insertAdjacentHTML('beforeend',`<span class="dock-label">${title}</span>`);
    button.setAttribute('aria-label',title);
  }
  const provenance=$('.provenance'), history=$('#historySection');
  inner.insertBefore(provenance,history);
  const notes=$('#notesSection'), summary=$('#summarySection');
  $('#processingPanelBody').replaceChildren(notes,summary);
  summary.querySelector('.prose').insertAdjacentHTML('afterend','<button id="generateAi" class="primary">生成 AI 整理</button>');
  $('#generateAi').disabled=m.collection!=='ready'||Boolean(m.trashed);
  $('#generateAi').onclick=busy($('#generateAi'),async()=>{await api(`/materials/${selected}/ai`,'POST');toast('AI 整理已排队，生成后会在这里显示。');});
  KnowledgeUI.mount(m);
  if(!m.first_layer&&annotationTrack){const notes=m.content.annotations||{};$('#notesText').value=notes[annotationTrack]??m.notes;}
  notesBaseline=$('#notesText').value;
  $('#aiAction').disabled=Boolean(m.trashed);
  if(m.first_layer){$('#refreshContent').hidden=true;$('#supplementAction').hidden=true;$('#supplementInline')?.setAttribute('hidden','');$('#retryAction')?.setAttribute('hidden','');}
  openProcessing(processingMode);
  inner.classList.add('entering');
}
$('#closeProcessing').onclick=()=>{openProcessing(null);$('#readAction')?.focus();};
$('#toggleSidebar').onclick=()=>{
  const shell=$('.app-shell');
  if(matchMedia('(max-width:760px)').matches&&shell.classList.contains('reading-open')){shell.classList.remove('reading-open');shell.classList.remove('sidebar-collapsed');}
  else shell.classList.toggle('sidebar-collapsed');
  const collapsed=shell.classList.contains('sidebar-collapsed');
  $('#toggleSidebar').setAttribute('aria-expanded',String(!collapsed));$('#toggleSidebar').setAttribute('aria-label',collapsed?'展开材料栏':'收起材料栏');
};
$('#expandLibrary').onclick=()=>{
  const wide=$('.app-shell').classList.toggle('library-expanded');
  $('#expandLibrary').setAttribute('aria-expanded',String(wide));$('#expandLibrary').setAttribute('aria-label',wide?'缩回材料库':'展开材料库');$('#expandLibrary').title=wide?'缩回材料库':'展开材料库';
};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&processingMode&&!$('#dialog').open){openProcessing(null);$('#readAction')?.focus();}});
function eventName(kind){return ({collected_reference:'登记来源',duplicate_seen:'识别到重复材料',job_queued:'任务排队',job_done:'任务结束',job_failed:'任务失败',content_saved:'保存原文',topic_assigned:'内容主题分类',notes_saved:'保存批注',ai_summary_saved:'保存 AI 整理',ai_reviewed:'本人查看AI结果',reading_intent_changed:'调回待消化',processing_changed:'处理状态变化',material_trashed:'移入回收站',material_restored:'从回收站恢复',job_paused:'用户暂停',push_preview:'生成推送预览',push_confirmed:'确认导出',push_failed:'写入失败（待重试）',x_sync_page:'读取 X 书签分页',ai_stale_result:'保留过期 AI 结果',subtitle_tracks_saved:'保存第二语言字幕',subtitle_tracks_stale:'双语结果已过期',bilingual_saved:'保存正文、字幕和回复译文',bilingual_stale:'原文变化，译文未覆盖'})[kind]||kind;}
async function saveNotes(track) {
  const mid=selected,text=$('#notesText').value,savedTrack=['callable','digest'].includes(track)?track:current.first_layer?undefined:annotationTrack||undefined;
  const item=await api(`/materials/${mid}/notes`,'PUT',{notes:text,revision:current.revision,...(savedTrack?{annotation_track:savedTrack}:{})});
  if(current?.id!==mid)throw new Error('原材料批注已保存，请重新打开材料。');
  current.revision=item.revision;current.notes=text;current.content=item.content;notesBaseline=text;dirty=$('#notesText').value!==text;$('#saveState').textContent=dirty?'未保存':'已保存';toast('批注已保存');
}
function materialDialog(item=null) {
  if(dirty){toast('请先保存当前材料的理解，再收集或补充材料。',true);return;}
  dialog(item?'补充材料（旧版本会保留）':'粘贴链接，收集材料',`<form id="materialForm"><label for="url">原始链接</label><input id="url" type="url" required placeholder="粘贴帖子、文章或视频链接" value="${escape(item?.url||'')}" ${item?'readonly':''}><div class="two-col"><div><label for="origin">收集类型</label><select id="origin" ${item?'disabled':''}><option value="favorite">我的收藏</option><option value="link">明确提供的非收藏材料</option></select></div><div><label for="title">标题（可选）</label><input id="title" value="${escape(item?.title||'')}"></div></div><details ${item?'open':''}><summary>粘贴原文 / 字幕（平台受限时也可使用）</summary><label for="originalText">原文</label><textarea id="originalText" placeholder="粘贴你实际看到的原文。不会用摘要代替原文。"></textarea><label for="subtitleText">带时间轴的字幕</label><textarea id="subtitleText" placeholder="粘贴 SRT / VTT / JSON 字幕，保留每段起止时间"></textarea><div class="two-col"><div><label for="subtitleFormat">字幕格式</label><select id="subtitleFormat"><option value="vtt">VTT</option><option value="srt">SRT</option><option value="json">B站 JSON</option><option value="json3">YouTube JSON3</option></select></div><div><label for="subtitleSource">字幕真实来源</label><select id="subtitleSource"><option>平台字幕</option><option>平台自动字幕（机器生成）</option><option>机器转写（非平台字幕）</option><option>人工整理</option><option>来源未声明</option></select></div></div></details>${item?'':'<p class="automatic-note">B站、YouTube、抖音视频自动获取字幕；没有字幕时，自动在本机转写并保留时间轴。X、小黑盒、小红书保存图文，视频保留在原链接。</p>'}<div class="button-row"><button type="submit" class="primary">${item?'保存补充材料':'开始收集'}</button></div></form>`);
  $('#origin').value=item?.origin||'link';
  $('#materialForm').insertAdjacentHTML('beforeend','<label id="recollectChoice" class="recollect-choice" hidden><input id="recollectDeleted" type="checkbox">我明确要重新收集这条已删除的材料</label>');
  $('#materialForm').onsubmit=guard(async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;try{const body={url:$('#url').value,origin:$('#origin').value,title:$('#title').value,text:$('#originalText').value,subtitles:$('#subtitleText').value,subtitle_format:$('#subtitleFormat').value,subtitle_source:$('#subtitleSource').value,transcribe:true,recollect_deleted:$('#recollectDeleted').checked};const result=await api(item?`/materials/${item.id}/supplement`:'/materials','POST',body);if(result.retired){$('#recollectChoice').hidden=false;toast('这条材料已彻底删除，未重新导入。',true);return;}$('#dialog').close();toast(result.retried?'此链接上次未完成，已重新排队自动提取字幕。':result.duplicate?'已在材料库中，已记录本次来源。':'材料已保存，正在自动获取内容');const target=await api('/materials/'+result.id);await chooseLibrary('source');await choosePlatform(target.platform);await select(result.id,true);}finally{button.disabled=false;}});
}
function topicDialog(){
  const m=current,detail=m.topic_detail||{};
  dialog('修改内容主题',`<p>主题帮助你分批消化材料，与平台和处理状态一起筛选。自动粗分在本机进行，不调用 AI，不读取图片里的文字；没有明确线索的材料留在未分类。</p><p class="muted">当前：${m.topic_source==='manual'?'你的手动分类':'本机规则粗分'}${detail.evidence?.length?' · 线索：'+escape(detail.evidence.join('、')):''}</p><label for="materialTopic">选择主题</label><select id="materialTopic">${Object.entries(topics).map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}<option value="auto">恢复自动粗分</option></select><p class="muted">手动选择会保留，重新采集不会覆盖。原文、理解和处理状态保持不变。</p><button id="saveTopic" class="primary">保存分类</button>`);
  $('#materialTopic').value=m.topic;
  $('#saveTopic').onclick=busy($('#saveTopic'),async()=>{
    const result=await api(`/materials/${m.id}/topic`,'POST',{topic:$('#materialTopic').value,revision:m.revision});$('#dialog').close();
    if(topicFilter&&topicFilter!==result.topic){clearReader();await refresh();}else await select(m.id,true);
    toast('已归入'+topics[result.topic]+'，原文和处理状态保留');
  });
}
async function pushDialog(){await KnowledgeUI.filing(current);}
async function previewExport(destination,complete){
  const mid=selected;
  const p=await api(`/materials/${mid}/push-preview`,'POST',{destination,complete_processing:complete});
  dialog('确认导出',`<p>${escape(p.notice)}</p><code class="storage-path">${escape(p.destination)}</code><pre class="preview">${escape(p.markdown)}</pre><button id="confirmPush" class="primary">${complete?'确认写入，并完成处理':'确认写入，保留当前状态'}</button>`);
  $('#confirmPush').onclick=busy($('#confirmPush'),async()=>{await api(`/pushes/${p.id}/confirm`,'POST',{hash:p.hash});$('#dialog').close();toast(complete?'已导出，材料已移入已完成。':'已保存到 资料文件夹，处理状态保留。');await select(mid,true);});
}
$('#addBtn').onclick=()=>materialDialog();
$('#organizePromptBtn').onclick=guard(()=>KnowledgeUI.showOrganizationPrompt());
async function favoritesDialog(platform=$('#platformFilter').value||'x',verificationURL=''){
  if(dirty){toast('请先保存当前批注，再导入收藏。',true);return;}
  const run=++xDialogRun;
  const accounts=await api('/accounts');
  if(!accounts.some(a=>a.platform===platform))platform='x';
  let account=accounts.find(a=>a.platform===platform), tracked=account.last_sync?.id;
  const official=platform==='x'&&account.read_mode==='oauth';
  dialog('导入我的收藏',`<p class="muted">已有登录状态可以直接导入；过期时再刷新登录。</p>
    <div class="platform-picker" aria-label="选择收藏平台">${Object.entries(names).filter(([k])=>k!=='web').map(([k,n])=>`<button data-favorite-platform="${k}" class="${k===platform?'chosen':''}" aria-pressed="${k===platform}">${platformIcon(k)}<span>${n}</span><small>${accounts.find(a=>a.platform===k)?.saved?'登录态已保存':'未连接'}</small></button>`).join('')}</div>
    <section class="connection-step"><span class="step-number">1</span><div><h3 id="accountHeading">${official?'X 官方授权':account.access_required?'需要平台验证':account.saved?'登录态已保存':'登录 '+escape(names[platform])}</h3><p id="accountMessage">${account.access_required?'打开窗口完成平台验证，再保存登录状态。':account.saved?'登录已记住，可以直接导入；过期时再登录。':'登录一次并保存，之后直接导入收藏。'}</p>
    ${official?`<p>X 禁止网站脚本自动化。本入口使用官方 OAuth 授权与书签 API，需要你的开发者应用 Client ID；API 访问额度由 X 决定。</p><details ${account.x_client_id?'':'open'}><summary>首次配置官方授权（不需要浏览器插件）</summary><p>在 <a href="https://console.x.com/" target="_blank" rel="noopener noreferrer">X 开发者控制台</a>创建自己的应用，开启 OAuth 2.0，类型选择 Native App / 公共客户端；回调地址填写下面这一行。只申请读取帖子、用户和书签权限，不申请发帖或修改收藏权限。</p><code>http://127.0.0.1:8766/oauth/x/callback</code><label for="xClientId">应用 Client ID（不是账号名，也不是 Client Secret）</label><input id="xClientId" value="${escape(account.x_client_id||'')}" autocomplete="off"><button id="saveXClient">保存 Client ID</button></details>`:''}<div class="button-row login-actions"><button id="openLogin" class="primary">${official?'打开 X 官方授权页面':account.access_required?'打开验证窗口':account.saved?'打开登录窗口':'登录账号'}</button><button id="saveLogin" ${official?'hidden':''} ${account.login.state==='open'?'':'disabled'}>保存登录状态</button></div><p id="loginState" class="muted" role="status">${escape(account.verification)}</p>${!official?'<details class="other-login"><summary>沿用常用Chrome · 可选扩展</summary><div class="chrome-primary"><button id="connectChrome">连接当前Chrome</button><div id="chromeConnection" hidden></div></div><div id="manualSessionImport"></div></details>':''}</div></section>
    <section class="connection-step"><span class="step-number">2</span><div><h3>确认自己的收藏页</h3><p>${platform==='x'?'本轮使用你的 X 登录会话低速读取书签，不需要开发者账号或付费 API。一次导入，不自动定期同步。':platform==='bilibili'?'先读取这个账号的收藏夹，你可以选择全部或其中几个。':platform==='youtube'?'默认读取「你」中的播放列表，并展开可访问列表。也可填入「稍后观看」或某个收藏播放列表地址；只处理当前页面可访问范围。':platform==='heybox'?'通过你的收藏接口分页核对清单，只给新来源排队正文；不枚举帖子编号。':'在上面的官方窗口打开「收藏」或「书签」页。小红书需要打开个人主页的「收藏」标签，再复制地址到这里。'}</p>
    ${platform==='bilibili'?'<div id="biliFolderPicker"><button id="loadBiliFolders">选择B站收藏夹</button><div id="biliFolders" role="status"></div></div>':''}<label for="favoritePage">我的收藏页地址</label><input id="favoritePage" type="url" value="${escape(account.favorite_url)}" ${['bilibili','x'].includes(platform)?'readonly':''}></div></section>
    <section class="connection-step"><span class="step-number">3</span><div><h3>导入并消化</h3><p>${['bilibili','youtube','douyin'].includes(platform)?'收藏中的每个视频会自动先取平台字幕；没有可用字幕时，自动获取临时音频并在本机转写。字幕与原站嵌入播放器并排显示，不保存视频播放副本。':'按图文材料保存正文、对应图片和实际可读的部分评论。视频仅保留原帖链接。'}只采集新材料；已删除的来源会跳过。清单自带完整正文时比较原帖变化，更新留旧版本和批注；只有链接时不重采旧正文。平台取消收藏不会删除本库材料。为避免漏项仍逐页核对清单，不是只读取新增页。新一天请从最新收藏开始；续读只补上次断点后剩余部分。</p>
    <label class="follow-control" title="新一轮核对时生效；续读沿用上次选项"><input id="repairIncomplete" type="checkbox">同时补齐未完成</label><div class="button-row"><button id="importFavorites" class="primary" ${!account.saved||account.access_required?'disabled':''}>从最新收藏开始核对</button><button id="resumeFavorites" ${!tracked||account.last_sync?.progress.complete?'disabled':''}>续读上次剩余部分</button><button id="stopFavorites" disabled>停止读取</button></div>
    <div id="favoritesProgress" class="sync-progress" role="status">尚未开始读取；登录状态保存不等于收藏权限已验证。</div></div></section>
    <details class="import-behavior"><summary>以后再次导入会怎样</summary><ul><li>新收藏新增；已有材料复用，不再重复抓正文。</li><li>本机回收站里的材料不恢复；彻底删除的来源记住，不会导回来。</li><li>源平台取消收藏，本机仍保留；重新收藏同一条也不重复。</li><li>没有读到完整清单时保留进度，不把它当作全部成功。</li></ul></details><details class="connection-risk"><summary>平台限制与账号风险</summary><p>网页读取和第三方提取可能不符合平台条款，也可能触发验证、限流或账号限制；低频读取不能保证零封号风险。工具仅读取，不点赞、不发帖、不改变收藏；遇到验证、权限拒绝或限流就停止，不自动绕过。X 官方规则限制非 API 自动化；本轮按你的选择使用登录会话读取，每次请求间隔 8–12 秒；仍存在账号限制风险。YouTube 条款也限制自动化访问与下载，使用前应核对自己具备的权限。</p><p>每页先保存再继续。只有平台明确返回末尾才显示完整；读不到末尾会显示未完成，已导入材料仍保留。登录态按平台用 Windows DPAPI 加密，不发给 AI。</p><div class="button-row"><button id="forgetAccount">删除此平台本机登录状态</button></div></details>
    <details><summary>已有收藏列表链接或导出文件</summary><p class="muted">可以直接读取 B站收藏夹 / YouTube 播放列表；其他平台也可导入每行一个链接的 TXT，或含 url、origin、text 的 JSON。这个入口不要求安装浏览器插件。</p><input id="listUrl" type="url" placeholder="B站 fid= / YouTube list= 链接"><button id="readList">读取指定收藏列表</button><label for="favoriteFile">收藏清单文件</label><input id="favoriteFile" type="file" accept=".txt,.json"><textarea id="favoriteLinks" placeholder="每行一个收藏链接，或 JSON 数组"></textarea><button id="readFile">导入收藏清单</button></details>`);
  document.querySelectorAll('[data-favorite-platform]').forEach(b=>b.onclick=guard(()=>favoritesDialog(b.dataset.favoritePlatform)));
  const login=async action=>{account=await api(`/accounts/${platform}/login`,'POST',{action,...(action==='open'&&verificationURL?{url:verificationURL}:{})});$('#loginState').textContent=account.login.message||account.verification;};
  $('#saveXClient')?.addEventListener('click',busy($('#saveXClient'),async()=>{await api('/accounts/x/client','PUT',{client_id:$('#xClientId').value.trim()});toast('Client ID 已保存，接下来打开官方授权页面。');}));
  $('#openLogin').onclick=busy($('#openLogin'),()=>login('open'));
  $('#saveLogin').onclick=busy($('#saveLogin'),()=>login('save'));
  if(!official){
    $('#connectChrome').onclick=busy($('#connectChrome'),async()=>{
      const result=await api(`/accounts/${platform}/connect`,'POST',{});if(run!==xDialogRun||!$('#chromeConnection'))return;const box=$('#chromeConnection');box.hidden=false;
      box.innerHTML=`<label for="chromeConnectionCode">复制连接码，粘贴到常用Chrome里的藏页扩展</label><div class="storage-copy-row"><input id="chromeConnectionCode" readonly value="${escape(result.code)}"><button id="copyChromeCode">复制连接码</button></div><p>扩展里选择「${escape(names[platform])}」，点「连接这个账号」。连接码10分钟内有效。</p><details><summary>首次安装扩展 · 只做一次</summary><ol><li><a href="/api/browser-extension" download>下载扩展包</a>并解压。</li><li>在常用Chrome打开 <code>chrome://extensions</code>，开启开发者模式，点「加载已解压的扩展程序」，选择解压后的文件夹。</li><li>在工具栏打开藏页扩展，粘贴上面的连接码。</li></ol></details>`;
      $('#copyChromeCode').onclick=()=>copyPath(result.code,$('#chromeConnectionCode'));
    });
    $('#manualSessionImport').insertAdjacentHTML('beforeend','<details><summary>手动导入登录文件</summary><input id="chromeLoginFile" type="file" accept=".json,application/json"><p id="chromeLoginResult" role="status"></p></details>');
    $('#chromeLoginFile').onchange=guard(async()=>{const file=$('#chromeLoginFile').files[0];if(!file)return;if(file.size>5_000_000)throw Error('登录文件过大');const state=JSON.parse(await file.text());if(state.platform&&state.platform!==platform)throw Error('请选择当前平台的登录文件');const result=await api(`/accounts/${platform}/browser-session`,'POST',{state});$('#chromeLoginResult').textContent=result.verification;$('#chromeLoginFile').value='';$('#importFavorites').disabled=false;});
  }
  $('#forgetAccount').onclick=busy($('#forgetAccount'),async()=>{await login('forget');toast('已删除此平台的本机登录状态');});
  let biliFolderSelection=null;
  async function loadFolders(){
    const result=await api('/accounts/bilibili/folders');if(run!==xDialogRun||!$('#biliFolders'))return;biliFolderSelection=result.folders.map(f=>f.id);
    $('#biliFolders').innerHTML=`<label class="folder-check"><input id="allBiliFolders" type="checkbox" checked>全部收藏夹</label>${result.folders.map((f,i)=>`<label class="folder-check"><input type="checkbox" data-bili-folder="${i}" checked><span>${escape(f.title)}</span><small>${f.count} 条</small></label>`).join('')||'<p>这个账号没有自建收藏夹。</p>'}`;
    const update=()=>{biliFolderSelection=[...document.querySelectorAll('[data-bili-folder]')].filter(n=>n.checked).map(n=>result.folders[Number(n.dataset.biliFolder)].id);$('#allBiliFolders').checked=biliFolderSelection.length===result.folders.length;$('#allBiliFolders').indeterminate=biliFolderSelection.length>0&&biliFolderSelection.length<result.folders.length;};
    $('#allBiliFolders').onchange=()=>{document.querySelectorAll('[data-bili-folder]').forEach(n=>n.checked=$('#allBiliFolders').checked);update();};
    document.querySelectorAll('[data-bili-folder]').forEach(n=>n.onchange=update);
  }
  if(platform==='bilibili')$('#loadBiliFolders').onclick=busy($('#loadBiliFolders'),loadFolders);
  const start=async resume=>{if(platform==='bilibili'&&!resume&&biliFolderSelection===null){await loadFolders();toast('请选择收藏夹，再点击导入');return;}if(platform==='bilibili'&&!resume&&!biliFolderSelection.length)throw Error('请至少选择一个收藏夹');tracked=(await api('/favorites','POST',{platform,...(platform==='bilibili'&&!resume?{folder_ids:biliFolderSelection}:{}),url:$('#favoritePage').value,repair_incomplete:$('#repairIncomplete').checked,...(resume?{resume_job_id:tracked}:{})})).job_id;toast(['bilibili','youtube','douyin'].includes(platform)?'收藏读取已排队，视频会自动生成时间轴文字。':'收藏读取已排队，先保存图文，再低速补采部分回复。');};
  $('#importFavorites').onclick=busy($('#importFavorites'),()=>start(false));
  $('#resumeFavorites').onclick=busy($('#resumeFavorites'),()=>start(true));
  $('#stopFavorites').onclick=busy($('#stopFavorites'),async()=>{await api(`/jobs/${tracked}/stop`,'POST');toast('已请求停止，当前页面处理完后停止；已导入材料保留。');});
  $('#readList').onclick=busy($('#readList'),async()=>{await api('/sync','POST',{url:$('#listUrl').value});toast('指定收藏列表已排队');});
  $('#favoriteFile').onchange=guard(async()=>{const f=$('#favoriteFile').files[0];if(f)$('#favoriteLinks').value=await f.text();});
  $('#readFile').onclick=busy($('#readFile'),async()=>{const text=$('#favoriteLinks').value.trim();const items=text.startsWith('[')?JSON.parse(text):text.split(/\r?\n/).filter(Boolean).map(url=>({url:url.trim(),origin:'favorite'}));const r=await api('/import','POST',items);const failed=r.results.filter(x=>x.error);$('#favoritesProgress').textContent=`清单登记 ${r.results.length-failed.length} 条；失败 ${failed.length} 条。`+failed.map(x=>`\n第 ${x.index+1} 条：${x.error}`).join('');await refresh();});
  const watch=async()=>{
    if(run!==xDialogRun||!$('#dialog').open||!$('#favoritesProgress'))return;
    const [values,jobs]=await Promise.all([api('/accounts'),api('/jobs')]);
    if(run!==xDialogRun||!$('#dialog').open||!$('#favoritesProgress'))return;
    const updated=values.find(a=>a.platform===platform);document.querySelectorAll('[data-favorite-platform]').forEach(b=>{b.querySelector('small').textContent=values.find(a=>a.platform===b.dataset.favoritePlatform)?.saved?'登录态已保存':'未连接';});
    $('#loginState').textContent=updated.login.message||updated.verification;
    if(!official){$('#accountHeading').textContent=updated.access_required?'需要平台验证':updated.saved?'登录态已保存':'登录 '+names[platform];$('#accountMessage').textContent=updated.access_required?'打开窗口完成平台验证，再保存登录状态。':updated.saved?'登录已记住，可以直接导入；过期时再登录。':'登录一次并保存，之后直接导入收藏。';$('#openLogin').textContent=updated.access_required?'打开验证窗口':updated.saved?'打开登录窗口':'登录账号';}
    $('#saveLogin').disabled=updated.login.state!=='open';
    if(updated.login.state==='saved'&&account.login.state!=='saved'&&platform!=='x')$('#favoritePage').value=updated.favorite_url;
    account=updated;$('#importFavorites').disabled=!updated.saved||updated.access_required;
    if(updated.last_sync?.id)tracked=updated.last_sync.id;
    const j=jobs.find(j=>j.id===tracked)||(updated.last_sync?.id===tracked?updated.last_sync:null);
    if(j){const p=j.progress||{}, active=['queued','running'].includes(j.state);$('#stopFavorites').disabled=!active;$('#resumeFavorites').disabled=active||Boolean(p.complete)||updated.access_required;$('#importFavorites').disabled=active||!updated.saved||updated.access_required;
      $('#favoritesProgress').textContent=`${({queued:'等待读取',running:'正在读取收藏',done:p.complete?'收藏列表读取完成':'本批读取结束，尚未确认末尾',failed:'读取中断，已保存结果',paused:'读取已暂停'})[j.state]||j.state}\n新增 ${p.new||0} 条 · 重复 ${p.duplicates||0} 条${p.retired?' · 已删除跳过 '+p.retired+' 条':''}${p.updated_content?' · 原帖更新 '+p.updated_content+' 条':''}${p.repair_queued?' · 补采排队 '+p.repair_queued+' 条':''}${p.unavailable?' · 其中失效 '+p.unavailable+' 条':''}${p.pages?' · 已读取 '+p.pages+' 页':''}\n${p.transport==='heybox_favorites_api'?'收藏接口 · 分页位置 '+(p.checkpoint?.offset||0)+'\n':p.transport==='heybox_compatibility_page'?'收藏页兼容模式 · 未确认完整\n':''}${p.selected_folders?.length?'收藏夹：'+p.selected_folders.map(f=>f.title).join('、')+'\n':''}${p.scope||''}\n${p.message||''}\n${['bilibili','youtube','douyin'].includes(platform)?'视频字幕在后台分别处理；列表读取结束不代表所有字幕已完成。':'链接先登记，正文、图片和部分回复在后台采集；列表读完不代表内容已全部成功。'}${j.error?'\n'+j.error:''}`;}
    setTimeout(()=>guard(watch)(),2500);
  };
  await watch();
}
$('#xConnectBtn').onclick=guard(()=>favoritesDialog());
$('#syncBtn').onclick=guard(()=>favoritesDialog());

$('#capabilitiesBtn').onclick=guard(async()=>{const caps=await api('/capabilities');dialog('平台能力与边界',caps.map(c=>`<section class="capability"><h3>${escape(c.name)}</h3><p>收藏：${escape(c.favorites)}</p><p>内容：${escape(c.content)}</p><p class="muted">${escape(c.status)}</p></section>`).join(''));});
$('#jobsBtn').onclick=guard(async()=>{const jobs=await api('/jobs');dialog('任务记录',`<p class="muted">显示最近更新的 200 条任务。失败的材料可在详情中重试；列表读取失败可重新提交。暂停与回收站任务不会自动恢复。</p>${jobs.length?jobs.map(j=>`<div class="job"><strong>${({collect:'收集',images:'存档图片',ai:'AI 整理',sync:'读取收藏列表',x_sync:'读取 X 收藏',x_check:'验证 X 账号',subtitle_tracks:'读取双语字幕',favorites:'读取平台收藏'})[j.kind]} · ${({queued:'等待中',running:'执行中',done:'任务结束',failed:'失败',paused:'已暂停',cancelled:'已取消'})[j.state]}</strong><p class="muted">${new Date(j.created).toLocaleString('zh-CN')}</p>${j.progress?.message?`<p>${escape(j.progress.message)}</p>`:''}${j.error?`<p>${escape(j.error)}</p>`:''}</div>`).join(''):'<p>还没有后台任务。</p>'}`);});
async function copyPath(value,field){
  try{await navigator.clipboard.writeText(value);toast('已复制');}catch{if(field){field.focus();field.select();}toast('请复制选中的路径');}
}
$('#storageBtn').onclick=guard(async()=>{
  const s=await api('/storage');
  dialog('保存位置',`<p class="storage-intro">${escape(s.notice)}</p><h3>保存到哪个文件夹</h3><div class="storage-destinations">${s.destinations.map((d,i)=>`<section class="storage-destination"><h4>${escape(d.label)}</h4><div class="storage-copy-row"><input id="storagePath${i}" value="${escape(d.path)}" readonly aria-label="${escape(d.label)}的保存路径"><button data-copy-storage="${i}">复制</button></div></section>`).join('')}</div><h3>整理到主题之后</h3><p>放到你选的主题目录下的「${escape(s.topic_subfolder)}」文件夹。</p><div class="storage-attachments"><h3>图片在哪里</h3><p>每条材料一个文件夹：<strong>index.md</strong> 是正文和批注，<strong>assets</strong> 放这条材料的图片与附件。移动或回收时一起处理。</p></div><button id="changeStorage" class="primary">更改保存位置</button><details class="storage-local"><summary>收集到的原文 · 本机缓存</summary><code class="storage-path">${escape(s.local_root)}</code><p>按平台、每条材料分别保存，图片和历史也在这条材料的目录内。</p></details>`);
  document.querySelectorAll('[data-copy-storage]').forEach(b=>b.onclick=()=>{const i=Number(b.dataset.copyStorage);return copyPath(s.destinations[i].path,$('#storagePath'+i));});
  $('#changeStorage').onclick=guard(async()=>{await $('#settingsBtn').onclick();$('#vaultSettings').scrollIntoView({block:'start'});$('#vaultPath').focus();});
});
$('#settingsBtn').onclick=guard(async()=>{
  const s=await api('/settings');dialog('设置',`<form id="settingsForm"><h3>AI 整理</h3><p class="muted">使用兼容 Chat Completions 的服务。只有点击 AI 整理时，才会把选中材料发给你配置的服务。</p><label for="aiBase">API 根地址</label><input id="aiBase" type="url" value="${escape(s.ai_base_url)}" required><label for="aiModel">模型名称</label><input id="aiModel" value="${escape(s.ai_model)}" placeholder="填入服务商提供的模型 ID"><label for="aiKey">API 密钥 ${s.ai_configured?'（已配置，留空保留）':''}</label><input id="aiKey" type="password" autocomplete="off"><label for="whisperModel">本机转写模型</label><select id="whisperModel"><option value="tiny">tiny · 速度优先</option><option value="base">base · 平衡</option><option value="small">small · 中等精度</option><option value="medium">medium · 较高精度</option><option value="turbo">large-v3 turbo · 高精度，优先使用显卡</option><option value="large-v3">large-v3 · 完整大模型</option></select><p class="muted">转写组件已纳入主安装流程。首次使用某个模型会联网下载，音频与转写都在本机处理。</p><button type="submit" class="primary">保存设置</button></form><hr><h3>平台登录</h3><p class="muted">六个平台都通过工具自己的官方网页窗口登录。登录态按平台保存，收藏权限在读取时验证。</p><button id="manageAccounts">登录与导入收藏</button>`);
  $('#whisperModel').value=s.whisper_model;
  $('#dialogBody').insertAdjacentHTML('afterbegin',`<section class="appearance-settings"><h3>阅读外观</h3><label for="appearance">选择界面</label><select id="appearance">${Object.entries(appearanceNames).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select><a class="source-link" href="/design" target="_blank" rel="noopener">查看七张参考（已选定 E）</a></section>`);
  $('#appearance').value=document.documentElement.dataset.appearance;$('#appearance').onchange=()=>setAppearance($('#appearance').value);
  if(!(await api('/health')).design_references)$('#dialogBody a[href="/design"]').hidden=true;
  $('#dialogBody').insertAdjacentHTML('beforeend',`<hr><form id="vaultSettings"><h3>材料归档</h3><label for="vaultPath">保存材料的文件夹</label><input id="vaultPath" value="${escape(s.obsidian_vault||'')}" placeholder="留空使用本机默认位置"><details><summary>自定义目录</summary>${Object.entries({callable:'留作资料',digest:'以后细读',archive:'原始材料存档',trash:'回收站',materials:'主题材料'}).map(([key,label])=>`<label for="path-${key}">${label}</label><input id="path-${key}" data-knowledge-path="${key}" value="${escape(s.knowledge_paths[key])}">`).join('')}<label for="knowledgeTargets">常用主题目录 · 每行一个</label><textarea id="knowledgeTargets" rows="3" placeholder="例如：学习/AI\n音乐/专辑">${escape(s.knowledge_targets.join('\n'))}</textarea><p>这些子文件夹建在上面的保存位置里面。</p></details><p>已有材料保持原位；保存前会显示具体去向。</p><button id="saveVault" type="submit" class="primary">保存归档位置</button></form>`);
  $('#vaultSettings').onsubmit=guard(async e=>{e.preventDefault();await busy($('#saveVault'),async()=>{const paths=Object.fromEntries([...document.querySelectorAll('[data-knowledge-path]')].map(input=>[input.dataset.knowledgePath,input.value]));await api('/obsidian','PUT',{vault:$('#vaultPath').value,paths,targets:$('#knowledgeTargets').value.split('\n').map(p=>p.trim()).filter(Boolean)});toast('归档位置已保存，已有文件保持原位。');})()});
  $('#settingsForm').onsubmit=guard(async e=>{e.preventDefault();await api('/settings','PUT',{ai_base_url:$('#aiBase').value,ai_model:$('#aiModel').value,ai_api_key:$('#aiKey').value,whisper_model:$('#whisperModel').value});$('#aiKey').value='';toast('设置已保存');});
  $('#manageAccounts').onclick=guard(()=>favoritesDialog());
});
document.querySelectorAll('[data-state]').forEach(b=>b.onclick=guard(async()=>{
  if(dirty){toast('请先保存当前批注，再切换材料分类。',true);return;}
  filter=b.dataset.state;visibleLimit=80;try{localStorage.setItem('collectionGroup',inFirstLibrary()?'first':'source');if(inFirstLibrary())localStorage.setItem('firstTrack',filter);}catch{};document.querySelectorAll('[data-state]').forEach(x=>{x.classList.toggle('active',x===b);if(x===b)x.setAttribute('aria-current','page');else x.removeAttribute('aria-current');});
  clearReader();await refresh();
}));
async function choosePlatform(value){
  if(dirty){toast('请先保存当前批注，再切换平台。',true);return;}
  $('#platformFilter').value=value;visibleLimit=80;try{localStorage.setItem('selectedPlatform',value);}catch{};document.querySelectorAll('[data-platform]').forEach(b=>{b.classList.toggle('active-platform',b.dataset.platform===value);b.setAttribute('aria-pressed',String(b.dataset.platform===value));});
  clearReader();await refresh();
}
$('#emptyCollect').onclick=()=>materialDialog();
document.querySelectorAll('[data-library]').forEach(b=>b.onclick=guard(()=>chooseLibrary(b.dataset.library)));
$('#multiSelectBtn').onclick=guard(async()=>{
  if(batchRunning||catalogueContext!==sourceQueueContext())return;
  multiSelect=!multiSelect;checkedMaterials.clear();purgeSelection=null;batchFailures=[];await refresh();
});
$('#selectAll').onchange=()=>chooseAllMaterials($('#selectAll').checked);
$('#batchTrashBtn').onclick=guard(()=>runMaterialBatch('trash'));
$('#batchRetryBtn').onclick=guard(()=>runMaterialBatch('retry'));
$('#batchRestoreBtn').onclick=guard(()=>runMaterialBatch('restore'));
$('#batchPurgeBtn').onclick=previewBatchPurge;
$('#batchPurgeText').oninput=renderSelectionControls;
$('#cancelBatchPurge').onclick=()=>{purgeSelection=null;renderSelectionControls();};
$('#confirmBatchPurge').onclick=guard(async()=>{
  const preview=purgeSelection;
  if(!preview||preview.context!==sourceQueueContext()||JSON.stringify(preview.targets)!==JSON.stringify(batchTargets())||$('#batchPurgeText').value!=='彻底删除')throw new Error('所选材料已改变，请重新确认');
  await runMaterialBatch('purge',preview.targets,'彻底删除');
});
$('#layerPhase').onchange=guard(async()=>{
  if(dirty){$('#layerPhase').value=layerPhase;toast('请先保存加工笔记，再切换状态。',true);return;}
  layerPhase=$('#layerPhase').value;clearReader();await refresh();
});
document.querySelectorAll('[data-platform]').forEach(b=>b.onclick=guard(()=>choosePlatform(b.dataset.platform)));

let searchTimer;$('#search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(guard(refresh),250);};
$('#captureFilter').onchange=guard(async()=>{visibleLimit=80;await refresh();});
$('#platformFilter').onchange=guard(()=>choosePlatform($('#platformFilter').value));$('#originFilter').onchange=guard(refresh);
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
let initialPlatform='';try{const saved=localStorage.getItem('selectedPlatform');if(saved!==null&&(saved===''||names[saved]))initialPlatform=saved;}catch{}
try{const saved=localStorage.getItem('selectedTopic');if(saved===''||topics[saved])topicFilter=saved;}catch{}
$('#platformFilter').value=initialPlatform;document.querySelectorAll('[data-platform]').forEach(b=>{b.classList.toggle('active-platform',b.dataset.platform===initialPlatform);b.setAttribute('aria-pressed',String(b.dataset.platform===initialPlatform));});
try{if(localStorage.getItem('collectionGroup')==='first')filter=localStorage.getItem('firstTrack')==='digest'?'digest':'callable';}catch{}
if(inFirstLibrary())clearReader();
guard(refresh)();

let polling=false;
setInterval(async()=>{if(polling||document.hidden)return;polling=true;try{await refresh();if(selected&&!$('#dialog').open){const m=await api('/materials/'+selected);if(m.id!==selected)return;if($('#captureProgress')){$('#captureProgress').textContent=m.progress?.message||'';$('#captureProgress').hidden=!m.progress?.message;}if($('#videoWorkbench'))updateSubtitleJob(m);if(current){current.translation_job=m.translation_job;updateTranslationJob(current);current.ai_job=m.ai_job;KnowledgeUI.updateJob(current);}if(current&&(m.revision!==current.revision||m.collection!==current.collection||m.error!==current.error||m.processing!==current.processing)){if(translationOnly(current,m))acceptTranslation(m);else if(!dirty&&document.activeElement?.id!=='notesText'){current=m;renderDetail(m);}}}}catch{}finally{polling=false;}},2000);
