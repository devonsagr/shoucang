/* Selected Vault notes support reading, AI context and reviewed knowledge notes. */
const KnowledgeUI=(()=>{
  let firstPreview=null;
  function invalidateFirstPreview(){
    firstPreview=null;$('#firstLayerPreview')?.remove();
    if($('#saveCallable'))$('#saveCallable').textContent='留作资料';
    if($('#saveDigest'))$('#saveDigest').textContent='以后细读';
  }
  const refs=m=>m.content.knowledge_context?.notes||[];
  const noteURL=(vault,path)=>'obsidian://open?vault='+encodeURIComponent(vault.split(/[\\/]/).at(-1))+'&file='+encodeURIComponent(path);
  const links=m=>refs(m).map(n=>`<a href="${escape(noteURL(m.content.knowledge_context.vault,n.path))}" title="${escape(n.path)}">${escape(n.title)}</a>`).join('');
  const shelves={ai_review:'AI待查看',reference:'资料索引',annotation:'我的批注'};
  const kinds={note:'备注',inspiration:'灵感',viewpoint:'观点',question:'疑问',material:'可用素材'};
  const aiJobText=m=>m.ai_job?['queued','running'].includes(m.ai_job.state)?'AI任务正在排队或整理，原文与批注保留。':m.ai_job.state==='failed'?'整理未完成：'+m.ai_job.error:'':'';
  function updateJob(m){
    if($('#annotationAiStatus'))$('#annotationAiStatus').textContent=aiJobText(m);
    const active=['queued','running'].includes(m.ai_job?.state);
    if($('#annotationSubmit'))$('#annotationSubmit').disabled=m.collection!=='ready'||Boolean(m.trashed)||active;
    if($('#secondPassAi'))$('#secondPassAi').disabled=!m.summary||Boolean(m.trashed)||!m.ai_review?.reviewed||active;
  }
  function mount(m){
    invalidateFirstPreview();
    let section=$('#knowledgeSection');
    if(!section){section=document.createElement('section');section.id='knowledgeSection';section.className='knowledge-context';$('#processingPanelBody').append(section);}
    section.innerHTML=`<details class="processing-more"><summary>更多</summary><button id="chooseKnowledge" class="text-button">关联笔记</button><div class="knowledge-links">${links(m)}</div><button id="showProcessingPaths" class="text-button">保存位置</button>${m.first_layer?`<p>原批注</p><p>${escape(m.content.first_layer_context.annotation)}</p><code class="storage-path">${escape(m.first_layer.path)}</code><button id="openRawSource" class="text-button">原始收藏</button>`:''}</details>`;
    $('#chooseKnowledge').onclick=guard(async()=>{if(dirty)await saveNotes();await choose(current);});
    $('#showProcessingPaths').onclick=guard(()=>showPaths(current));
    $('#openRawSource')?.addEventListener('click',guard(async()=>{await chooseLibrary('source');await select(m.first_layer.source_material_id);}));
    $('#notesText').placeholder='写点备注…';
    if($('#completeAction')?.parentElement)$('#completeAction').parentElement.hidden=true;
    $('#annotationKind')?.remove();$('#annotationSubmit')?.remove();$('#firstLayerChoices')?.remove();$('#aiShelfControls')?.remove();
    $('#saveState').textContent=m.notes?'已保存':'未保存';
    $('#saveNotes').textContent='存草稿';
    if(!m.first_layer){
      $('#notesSection .note-editor').insertAdjacentHTML('afterend',`<div id="firstLayerChoices" class="annotation-route-actions"><button id="saveCallable" class="primary">留作资料</button><button id="saveDigest">以后细读</button></div>`);
      $('#saveCallable').disabled=$('#saveDigest').disabled=Boolean(m.trashed);
      $('#saveCallable').onclick=busy($('#saveCallable'),()=>saveFirstLayer('callable'));
      $('#saveDigest').onclick=busy($('#saveDigest'),()=>saveFirstLayer('digest'));
      $('#generateAi').hidden=true;
      return;
    }
    $('#notesSection .note-editor').insertAdjacentHTML('afterend','<button id="annotationSubmit" class="primary">按批注 AI 整理</button>');
    $('#annotationSubmit').onclick=busy($('#annotationSubmit'),()=>submitAnnotation(false));
    $('#generateAi').textContent='按批注 AI 整理';$('#generateAi').hidden=false;
    $('#generateAi').onclick=busy($('#generateAi'),()=>submitAnnotation(false));
    $('#generateAi').insertAdjacentHTML('afterend',`<div id="aiShelfControls" class="ai-shelf-controls"><p id="annotationAiStatus">${escape(aiJobText(m))}</p>${m.content.ai_workflow?`<details><summary>本轮批注 · 第${m.content.ai_workflow.pass}轮</summary><p>${escape(m.content.ai_workflow.annotation)}</p></details>`:''}<button id="reviewAiResult" ${!m.summary||m.trashed||m.ai_review?.reviewed?'disabled':''}>我已审查结果</button><button id="secondPassAi" ${!m.ai_review?.reviewed?'disabled':''}>按批注再整理</button></div>`);
    $('#secondPassAi').onclick=busy($('#secondPassAi'),()=>submitAnnotation(true));
    $('#reviewAiResult').onclick=busy($('#reviewAiResult'),async()=>{if(dirty)await saveNotes();const latest=await api('/materials/'+selected);await api(`/materials/${selected}/ai-review`,'POST',{revision:latest.revision,summary_hash:latest.ai_review.summary_hash});await select(selected,true);openProcessing('ai');});
    updateJob(m);
  }
  async function saveFirstLayer(track){
    const mid=current.id;if(!$('#notesText').value.trim())throw new Error('先写一条批注。');
    if(firstPreview?.mid===mid&&firstPreview.track===track&&firstPreview.revision===current.revision&&!dirty&&$('#notesText').value===firstPreview.annotation){
      const confirmedPreview=firstPreview,{p,queue}=confirmedPreview;
      await api(`/pushes/${p.id}/confirm`,'POST',{hash:p.hash});
      const continueHere=firstPreview===confirmedPreview&&current?.id===mid&&current.revision===confirmedPreview.revision&&!dirty;
      if(firstPreview===confirmedPreview)invalidateFirstPreview();
      toast('已保存到'+(track==='callable'?'调用资料':'消化暂存'));
      if(continueHere)await continueSourceQueue(queue);
      return;
    }
    invalidateFirstPreview();
    const queue=captureSourceQueue(mid);
    await saveNotes(track);
    if(current?.id!==mid)throw new Error('材料已切换，请重新选择去向。');
    if(dirty)throw new Error('批注已变化，请再点一次预览。');
    const annotation=current.notes,revision=current.revision;
    const p=await api(`/materials/${mid}/push-preview`,'POST',{destination:'obsidian',complete_processing:false,shelf_output:{stage:track}});
    if(current?.id!==mid||current.revision!==revision||dirty||$('#notesText').value!==annotation)return;
    firstPreview={mid,track,p,queue,annotation,revision};
    $('#firstLayerChoices').insertAdjacentHTML('afterend',`<section id="firstLayerPreview" class="first-layer-preview"><h3>保存位置</h3><code class="storage-path">${escape(p.destination)}</code>${p.relocation?.remove?.length?`<p>文档和图片一起迁移。</p><details><summary>旧位置</summary><pre class="preview">${escape(p.relocation.remove.map(a=>a.path).join('\n'))}</pre></details>`:''}<details><summary>原文与附件</summary><pre class="preview">${escape(p.shelf_markdown)}</pre></details></section>`);
    $(track==='callable'?'#saveCallable':'#saveDigest').textContent=p.duplicate?'继续处理':'确认保存';
  }
  async function showOrganizationPrompt(){
    const p=await api('/first-layer/organization-prompt');
    dialog('整理提示词',`<label class="sr-only" for="organizationPrompt">已批注材料到主题材料区的完整提示词</label><textarea id="organizationPrompt" class="organization-prompt" readonly>${escape(p.text)}</textarea><div class="button-row"><button id="copyOrganizationPrompt" class="primary">复制提示词</button><span id="promptCopyState" role="status" aria-live="polite"></span></div>`);
    $('#copyOrganizationPrompt').onclick=busy($('#copyOrganizationPrompt'),async()=>{
      try{await navigator.clipboard.writeText(p.text);$('#promptCopyState').textContent='已复制';}
      catch{$('#organizationPrompt').focus();$('#organizationPrompt').select();$('#promptCopyState').textContent='请手动复制已选中的文字';}
    });
  }
  async function submitAnnotation(secondPass){
    const mid=current.id;if(dirty)await saveNotes();
    if(current?.id!==mid)throw new Error('材料已切换，请重新提交批注');
    if(!current.notes.trim())throw new Error('请先写一条批注，它就是这次整理的依据。');
    await api(`/materials/${mid}/ai`,'POST',{from_annotation:true,second_pass:secondPass,revision:current.revision,include_knowledge:refs(current).length>0});
    if(current?.id===mid){await select(mid,true);openProcessing('ai');}
    toast('AI 辅助已提交，结果留在本库的「AI 整理待审」。');
  }
  async function showPaths(m){
    const p=await api(`/materials/${m.id}/processing-paths`);
    dialog('材料保存位置',`${p.vault_available===false?`<p>${escape(p.vault_error)}</p>`:''}<h3>原始收藏</h3><code class="storage-path">${escape(p.local_source)}</code><h3>批注后的保存位置</h3>${Object.values(p.first_layer_folders).map(path=>`<code class="storage-path">${escape(path)}</code>`).join('')}<p>原文＋批注。先预览确认，不需要 AI。</p>${m.first_layer?`<h3>这条材料已保存到</h3><code class="storage-path">${escape(m.first_layer.path)}</code>`:''}<h3>主题目录</h3>${p.formal_folders.map(f=>`<code class="storage-path">${escape(f.absolute_path)}</code>`).join('')||'<p>没有可用的主题目录。</p>'}<p>材料归位与个人知识稿分开保存。</p>${m.vault_receipts?.length?'<h3>已确认的文件</h3>'+m.vault_receipts.map(r=>`<code class="storage-path">${escape(r.path)}</code>`).join(''):''}`);
  }
  async function choose(m){
    const chosen=new Map(refs(m).map(n=>[n.path,n])),mid=m.id;let sequence=0;
    async function show(folder='',query=''){
      const seq=++sequence,data=await api('/vault/notes?'+new URLSearchParams({folder,query}));
      if(seq!==sequence||current?.id!==mid)return;
      dialog('关联资料文件夹已有笔记',`<p>${escape(data.notice)}</p><div class="vault-directory"><button id="vaultParent" class="text-button" ${folder?'':'disabled'}>${icon('back')}上一级</button><span>资料文件夹${folder?' / '+escape(folder):''}</span></div><div class="vault-folder-list">${data.directories.map((d,i)=>`<button class="text-button" data-vault-folder="${i}">${icon('book')}${escape(d.title)}</button>`).join('')}</div><div class="vault-search"><input id="vaultQuery" type="search" aria-label="搜索当前目录笔记标题" placeholder="搜索当前目录的笔记标题" value="${escape(query)}"><button id="vaultSearch">搜索</button></div><div class="vault-note-list">${data.notes.map((n,i)=>`<div class="vault-note-row"><label><input type="checkbox" data-vault-note="${i}" ${chosen.has(n.path)?'checked':''}><span>${escape(n.title)}<small>${escape(n.path)}</small></span></label><button class="text-button" data-vault-preview="${i}">看正文</button></div>`).join('')||'<p class="muted">当前目录没有符合条件的笔记，可以进入子目录。</p>'}</div><pre id="vaultNotePreview" class="preview" hidden></pre>${data.limited?'<p class="muted">当前目录结果超过显示上限，未假称已遍历全部；可进入更具体目录或填写笔记路径。</p>':''}<div class="vault-direct-path"><label for="vaultDirectPath">也可粘贴已有笔记的相对路径</label><input id="vaultDirectPath" placeholder="例如 08_专辑学习积累/The money store.md"><button id="vaultAddPath" class="text-button">加入选择</button></div><p id="vaultChosen" class="muted"></p><button id="saveKnowledgeContext" class="primary">保存关联（不修改资料文件夹笔记）</button>`);
      function update(){const box=$('#vaultChosen');box.replaceChildren();box.append(document.createTextNode(`已选 ${chosen.size}/5 篇：`));for(const n of chosen.values()){const b=document.createElement('button');b.className='text-button';b.textContent=n.title+' ×';b.title=n.path;b.onclick=()=>{chosen.delete(n.path);const checkbox=data.notes.findIndex(row=>row.path===n.path);if(checkbox>=0)$(`[data-vault-note="${checkbox}"]`).checked=false;update();};box.append(b);}}
      function add(note){if(!chosen.has(note.path)&&chosen.size>=5)throw new Error('最多关联五篇笔记');chosen.set(note.path,note);update();}
      update();$('#vaultParent').onclick=guard(()=>show(folder.split('/').slice(0,-1).join('/')));
      document.querySelectorAll('[data-vault-folder]').forEach(b=>b.onclick=guard(()=>show(data.directories[Number(b.dataset.vaultFolder)].path)));
      $('#vaultSearch').onclick=guard(()=>show(folder,$('#vaultQuery').value));$('#vaultQuery').onkeydown=e=>{if(e.key==='Enter')$('#vaultSearch').click();};
      document.querySelectorAll('[data-vault-note]').forEach(b=>b.onchange=()=>{const n=data.notes[Number(b.dataset.vaultNote)];try{if(b.checked)add(n);else{chosen.delete(n.path);update();}}catch(error){b.checked=false;toast(error.message,true);}});
      document.querySelectorAll('[data-vault-preview]').forEach(b=>b.onclick=busy(b,async()=>{const n=await api('/vault/note?'+new URLSearchParams({path:data.notes[Number(b.dataset.vaultPreview)].path}));if(seq!==sequence)return;$('#vaultNotePreview').hidden=false;$('#vaultNotePreview').textContent=n.title+'\n\n'+n.text.slice(0,60000)+(n.text.length>60000?'\n\n（预览仅显示前60000字符，未改写原文）':'');}));
      $('#vaultAddPath').onclick=busy($('#vaultAddPath'),async()=>{const n=await api('/vault/note?'+new URLSearchParams({path:$('#vaultDirectPath').value.trim().replaceAll('\\','/')}));if(seq!==sequence)return;add(n);});
      $('#saveKnowledgeContext').onclick=busy($('#saveKnowledgeContext'),async()=>{
        if(current?.id!==mid)throw new Error('材料已切换，请重新选择关联');
        const saved=await api(`/materials/${mid}/knowledge-context`,'PUT',{paths:[...chosen.keys()],revision:current.revision});
        if(current?.id!==mid)return;current.content=saved.content;current.revision=saved.revision;mount(current);$('#dialog').close();toast('已关联资料文件夹笔记；原文、理解与处理状态保留。');
      });
    }
    await show();
  }
  function draft(m){return [m.notes?'## 我的批注\n\n'+m.notes:'',m.summary?'## AI 整理（已查看，仍需核对内容）\n\n'+m.summary:''].filter(Boolean).join('\n\n');}
  async function filing(m){
    if(!m.first_layer){openProcessing('notes');return;}
    const p=await api(`/materials/${m.id}/processing-paths`);
    dialog('继续整理',`<code class="storage-path">${escape(m.first_layer.path)}</code><div class="button-row"><button id="referenceMaterial" class="primary">材料归位</button><button id="manualKnowledge">我的知识稿</button><button id="aiKnowledge" ${!m.summary||!m.ai_review?.reviewed?'disabled':''}>AI 整理稿</button></div><button id="backToNotes" class="text-button">继续写批注</button><details><summary>保存位置</summary>${p.formal_folders.map(f=>`<code class="storage-path">${escape(f.absolute_path)}</code>`).join('')}</details>`);
    $('#referenceMaterial').onclick=guard(()=>compose(current,true,null,'reference'));
    $('#manualKnowledge').onclick=guard(()=>compose(current,true,null,'manual'));
    $('#aiKnowledge').onclick=guard(()=>compose(current,true,null,'edited'));
    $('#backToNotes').onclick=()=>{$('#dialog').close();openProcessing('notes');$('#notesText').focus();};
  }
  async function shelf(m,stage,savedOverview=''){
    if(dirty)await saveNotes();
    if(stage==='reference'){
      const snippet=(m.body||m.title).replace(/!\[[^\]]*\]\([^)]*\)/g,'').replace(/\s+/g,' ').trim().slice(0,180);
      dialog('资料索引：只知道大概，留待调用',`<p>不要求阅读消化全文。写一段“它是什么、以后可能用在哪里”，原文另外保存，AI可通过索引找到它。</p><label for="referenceOverview">简短概览 / 用途（默认截取原文，可修改）</label><textarea id="referenceOverview" maxlength="2000">${escape(savedOverview||snippet)}</textarea><p class="muted">确认后进入「资料备查」，离开人工待处理；原文保留，也可再调回待处理。不标成已消化。</p><button id="previewReference" class="primary">预览资料索引</button>`);
      $('#previewReference').onclick=busy($('#previewReference'),()=>showShelfPreview(current,stage,$('#referenceOverview').value));
      return;
    }
    await showShelfPreview(m,stage,'');
  }
  async function showShelfPreview(m,stage,overview){
    const mid=m.id,p=await api(`/materials/${mid}/push-preview`,'POST',{destination:'obsidian',complete_processing:false,shelf_output:{stage,overview}});
    dialog('确认存入'+shelves[stage],`<p>${stage==='ai_review'?'本次批注与整理结果在同一篇，统一放在待审目录，不先按主题分散。':'已批注材料按用途集中存放，不自动分散到正式知识目录。'}</p><h3>${shelves[stage]}</h3><code class="storage-path">${escape(p.destination)}</code><pre class="preview">${escape(p.shelf_markdown)}</pre><details><summary>完整原文、图片、字幕与回复</summary><code class="storage-path">${escape(p.source_destination)}</code><pre class="preview">${escape(p.markdown)}</pre></details><p class="muted">${stage==='reference'?'只转入资料备查，不标成已消化。':'保留当前处理状态，不标成已完成。'}</p><div class="button-row">${stage==='reference'?'<button id="editReferenceOverview">返回改概览</button>':''}<button id="confirmShelfOutput" class="primary">确认存入${shelves[stage]}</button></div>`);
    $('#editReferenceOverview')?.addEventListener('click',guard(()=>shelf(current,stage,overview)));
    $('#confirmShelfOutput').onclick=busy($('#confirmShelfOutput'),async()=>{await api(`/pushes/${p.id}/confirm`,'POST',{hash:p.hash});$('#dialog').close();await select(mid,true);toast('已存入'+shelves[stage]+'；'+(stage==='reference'?'以后需要时再调取。':'正式沉淀仍由你选择。'));});
  }
  async function compose(m,complete,savedDraft=null,authorship="edited"){
    const mid=m.id,folders=await api(`/materials/${mid}/knowledge-folders`),paths=await api(`/materials/${mid}/processing-paths`);
    dialog(authorship==='manual'?'我的知识稿':'材料归位',`<p>${authorship==='manual'?'保存你自己加工的内容。':'按主题放到材料专区，保留批注和来源。'}文档与图片一起迁移。</p><label for="knowledgeTitle">标题</label><input id="knowledgeTitle" value="${escape(savedDraft?.title||displayTitle(m))}" maxlength="300"><label for="knowledgeText">我要留下的内容</label><textarea id="knowledgeText" class="knowledge-output-editor" placeholder="写下你真正理解或准备引用的内容。AI 结果与自己的判断请分开。">${escape(savedDraft?.text??(authorship==='manual'?'':authorship==='reference'?'用途：'+m.notes+'\n\n完整资料：'+(m.content.first_layer_context?.note?'[['+m.content.first_layer_context.note.replace(/\.md$/,'')+']]':m.url):draft(m)))}</textarea><label for="knowledgeFolder">放到哪里</label><select id="knowledgeFolder">${folders.map(f=>`<option value="${escape(f.path)}">${escape(f.title)} · ${escape(f.path)}</option>`).join('')}</select><p class="muted">关联笔记：${refs(m).map(n=>escape(n.title)).join('、')||'未选择。可先在「我的批注」中关联已有笔记。'}</p><label class="export-state"><input id="knowledgeComplete" type="checkbox" ${complete?'checked':''}> 确认写入后，这条材料移入已完成</label><p class="muted">取消勾选可保留待处理或稍后整理。知识笔记不会自动变成今日行动或修改知识景观节点。</p><button id="previewKnowledgeOutput" class="primary">预览位置与内容</button>`);
    if(m.topic==='music'&&folders.some(f=>f.path==='08_专辑学习积累'))$('#knowledgeFolder').value='08_专辑学习积累';
    if(savedDraft?.folder)$('#knowledgeFolder').value=savedDraft.folder;
    $('#knowledgeFolder').insertAdjacentHTML('afterend','<code id="formalFolderPath" class="storage-path"></code>');
    const showFolder=()=>{$('#formalFolderPath').textContent=paths.formal_folders.find(f=>f.path===$('#knowledgeFolder').value)?.absolute_path||'请选择可用的主题目录';};
    $('#knowledgeFolder').onchange=showFolder;showFolder();
    $('#previewKnowledgeOutput').onclick=busy($('#previewKnowledgeOutput'),async()=>{
      if(current?.id!==mid)throw new Error('材料已切换，请重新打开处理结果');
      const done=$('#knowledgeComplete').checked;
      const edit={title:$('#knowledgeTitle').value,text:$('#knowledgeText').value,folder:$('#knowledgeFolder').value,authorship};
      const p=await api(`/materials/${mid}/push-preview`,'POST',{destination:'obsidian',complete_processing:done,knowledge_output:edit});
      dialog('确认归位',`<p>确认后迁移文档与图片，清理旧托管位置。</p><h3>${authorship==='manual'?'我的知识稿':'材料'}</h3><code class="storage-path">${escape(p.destination)}</code><pre class="preview">${escape(p.knowledge_markdown)}</pre><details><summary>原文、图片、完整字幕与回复存档</summary><code class="storage-path">${escape(p.source_destination)}</code><pre class="preview">${escape(p.markdown)}</pre></details><p class="muted">${done?'确认后，这条材料移入已完成。':'确认后，保留材料当前处理状态。'}</p><div class="button-row"><button id="editKnowledgeOutput">返回编辑</button><button id="confirmKnowledgeOutput" class="primary">确认新增到资料文件夹</button></div>`);
      $('#editKnowledgeOutput').onclick=guard(()=>compose(current,done,edit,authorship));
      $('#confirmKnowledgeOutput').onclick=busy($('#confirmKnowledgeOutput'),async()=>{
        const result=await api(`/pushes/${p.id}/confirm`,'POST',{hash:p.hash});$('#dialog').close();await select(mid,true);
        toast(authorship==='manual'?'知识稿已保存':'材料已归位');
      });
    });
  }
  return {mount,choose,compose,draft,noteURL,filing,shelf,submitAnnotation,showPaths,updateJob,invalidateFirstPreview,showOrganizationPrompt};
})();
