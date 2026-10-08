/* Global read-only task activity. View/filter changes never cancel work. */
(()=>{
  let button,badge,panel,rows,deps,snapshot,tab='active',busy=false,timer,signature='';
  const names={collect:'收集正文',images:'保存图片',favorites:'读取收藏',sync:'读取列表',x_sync:'读取X收藏',x_check:'检查X登录',subtitle_tracks:'读取双语字幕',bilingual:'翻译',ai:'按批注整理',overview:'生成概要'};
  const esc=value=>deps.escape(String(value??''));
  function close(returnFocus=false){if(!panel)return;panel.hidden=true;button.setAttribute('aria-expanded','false');if(returnFocus)button.focus({preventScroll:true});}
  function render(){
    if(!snapshot)return;
    const c=snapshot.counts,total=c.running+c.queued;
    badge.textContent=total?String(total):c.attention?'!':'';badge.hidden=!badge.textContent;
    button.dataset.state=c.running?'running':c.queued?'queued':c.attention?'attention':'idle';
    button.setAttribute('aria-label','后台任务，'+c.running+'进行中，'+c.queued+'等待，'+c.attention+'需处理');
    button.title=c.running+'进行中 · '+c.queued+'等待 · '+c.attention+'需处理';
    panel.querySelector('#taskRunning').textContent=c.running;panel.querySelector('#taskQueued').textContent=c.queued;panel.querySelector('#taskAttention').textContent=c.attention;
    panel.querySelectorAll('[data-task-tab]').forEach(n=>{n.setAttribute('aria-selected',String(n.dataset.taskTab===tab));n.setAttribute('tabindex',n.dataset.taskTab===tab?'0':'-1');n.classList.toggle('active',n.dataset.taskTab===tab);});
    const entries=snapshot[tab]||[];const count=tab==='active'?total:tab==='attention'?c.attention:entries.length;
    const html=entries.map(t=>{
      const p=t.progress||{};let percent=null;
      if(Number(p.total)>0&&Number.isFinite(Number(p.completed)))percent=Math.max(0,Math.min(100,Math.round(Number(p.completed)/Number(p.total)*100)));
      else if(Number(p.duration)>0&&Number.isFinite(Number(p.seconds)))percent=Math.max(0,Math.min(100,Math.round(Number(p.seconds)/Number(p.duration)*100)));
      return '<li class="task-row"><div class="task-row-heading"><strong>'+esc(t.title)+'</strong><span class="task-state '+esc(t.state)+'">'+esc(t.status_label)+'</span></div><div class="task-meta"><span>'+esc(deps.names[t.platform]||'本机')+'</span><span>'+esc(t.label||names[t.kind]||'后台任务')+'</span></div>'+(p.message?'<p>'+esc(p.message)+'</p>':'')+(percent!==null&&t.state==='running'?'<progress max="100" value="'+percent+'" aria-label="任务进度">'+percent+'%</progress>':'')+(t.error?'<p class="task-error">'+esc(t.error)+'</p>':'')+'</li>';
    }).join('')||'<li class="task-empty">'+({active:'当前没有进行中或等待的任务。',attention:'没有需要处理的失败或暂停任务。',recent:'还没有任务记录。'})[tab]+'</li>';
    const label=count>entries.length?'显示 '+entries.length+' / '+count+' 条；所有任务计入顶栏数量':entries.length+' 条';
    if(signature!==html){const scroll=rows.scrollTop;rows.innerHTML=html;rows.scrollTop=scroll;signature=html;}
    panel.querySelector('#taskShown').textContent=label;
  }
  async function refresh(){
    if(busy)return;busy=true;
    try{snapshot=await deps.api('/tasks');panel.querySelector('#taskConnection').hidden=true;render();}
    catch{button.dataset.state='offline';button.title=snapshot?'任务状态暂未连接，保留上次记录':'尚未取得任务状态';panel.querySelector('#taskConnection').hidden=false;panel.querySelector('#taskConnection').textContent=snapshot?'状态暂未连接，保留上次记录；连接恢复后自动更新。':'尚未取得任务状态；连接恢复后自动更新。';}
    finally{busy=false;}
  }
  function init(options){
    if(button)return;deps=options;button=document.querySelector('#taskMonitorBtn');badge=document.querySelector('#taskBadge');
    panel=document.createElement('section');panel.id='taskPopover';panel.className='task-popover';panel.hidden=true;panel.setAttribute('role','dialog');panel.setAttribute('aria-labelledby','taskPanelTitle');
    panel.innerHTML='<header><h2 id="taskPanelTitle">后台任务</h2><button type="button" data-task-close aria-label="收起任务窗口">'+deps.icon('close')+'</button></header><div class="task-counts"><span><b id="taskRunning">—</b> 进行中</span><span><b id="taskQueued">—</b> 等待</span><span><b id="taskAttention">—</b> 需处理</span></div><div class="task-tabs" role="tablist"><button data-task-tab="active" role="tab" aria-selected="true">当前</button><button data-task-tab="attention" role="tab" aria-selected="false">需处理</button><button data-task-tab="recent" role="tab" aria-selected="false">最近结束</button></div><p id="taskConnection" class="task-connection" role="status" hidden></p><ul id="taskRows" class="task-rows" aria-live="polite"></ul><footer id="taskShown"></footer>';
    document.body.append(panel);rows=panel.querySelector('#taskRows');
    button.addEventListener('click',()=>{const opening=panel.hidden;panel.hidden=!opening;button.setAttribute('aria-expanded',String(opening));if(opening){render();refresh();panel.querySelector('[data-task-tab="'+tab+'"]').focus({preventScroll:true});}});
    panel.addEventListener('click',event=>{if(event.target.closest('[data-task-close]'))close(true);const selected=event.target.closest('[data-task-tab]');if(selected){tab=selected.dataset.taskTab;render();}});
    panel.addEventListener('keydown',event=>{
      if(!event.target.closest('[data-task-tab]'))return;
      const keys=['active','attention','recent'];let index=keys.indexOf(tab);
      if(event.key==='ArrowRight')index=(index+1)%3;else if(event.key==='ArrowLeft')index=(index+2)%3;
      else if(event.key==='Home')index=0;else if(event.key==='End')index=2;else return;
      event.preventDefault();tab=keys[index];render();panel.querySelector('[data-task-tab="'+tab+'"]').focus({preventScroll:true});
    });
    document.addEventListener('click',event=>{if(!panel.hidden&&!panel.contains(event.target)&&!button.contains(event.target))close();});
    document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!panel.hidden){event.preventDefault();close(true);}});
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
    timer=setInterval(()=>{if(!document.hidden)refresh();},3000);
    return refresh();
  }
  window.TaskMonitor={init,refresh,open:()=>{if(panel?.hidden)button.click();}};
})();
