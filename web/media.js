/* Full images stay inside the reader; no new tab or automatic download. */
(()=>{
  let dialog,photo,counter,previous,next,zoom,items=[],position=0,trigger=null;
  const safeSource=value=>typeof value==='string'&&/^\/api\/materials\/[^/]+\/images\//.test(value)&&!/[<>"\s]/.test(value);
  const svg=path=>`<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6"><path d="${path}"/></svg>`;
  function mount(){
    if(dialog)return;
    dialog=document.createElement('dialog');dialog.id='imageViewer';dialog.className='image-viewer';dialog.setAttribute('aria-label','查看完整图片');
    dialog.innerHTML=`<header class="image-viewer-bar"><span class="image-viewer-count" role="status"></span><div><button type="button" data-viewer="previous" aria-label="上一张">${svg('m14 5-7 7 7 7')}</button><button type="button" data-viewer="next" aria-label="下一张">${svg('m10 5 7 7-7 7')}</button><button type="button" data-viewer="zoom">原尺寸</button><button type="button" data-viewer="close" aria-label="关闭图片">${svg('m6 6 12 12M18 6 6 18')}</button></div></header><div class="image-viewer-canvas" tabindex="0"><img alt="完整图片"></div>`;
    document.body.append(dialog);photo=dialog.querySelector('img');counter=dialog.querySelector('[role="status"]');previous=dialog.querySelector('[data-viewer="previous"]');next=dialog.querySelector('[data-viewer="next"]');zoom=dialog.querySelector('[data-viewer="zoom"]');
    dialog.addEventListener('click',event=>{const action=event.target.closest('[data-viewer]')?.dataset.viewer;if(action==='close')close();else if(action==='previous')move(-1);else if(action==='next')move(1);else if(action==='zoom'){dialog.classList.toggle('original-size');zoom.textContent=dialog.classList.contains('original-size')?'适合窗口':'原尺寸';}else if(event.target===dialog)close();});
    dialog.addEventListener('keydown',event=>{if(['Escape','ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();event.stopPropagation();if(event.key==='Escape')close();else move(event.key==='ArrowLeft'?-1:1);}});
    dialog.addEventListener('close',()=>{photo.removeAttribute('src');items=[];if(trigger?.isConnected)trigger.focus({preventScroll:true});trigger=null;});
  }
  function show(){const item=items[position];photo.src=item.src;photo.alt=item.alt;counter.textContent=`图片 ${position+1} / ${items.length}`;previous.disabled=position===0;next.disabled=position===items.length-1;dialog.querySelector('.image-viewer-canvas').scrollTop=0;}
  function move(delta){const target=position+delta;if(target<0||target>=items.length)return;position=target;show();}
  function close(){if(dialog?.open)dialog.close();}
  document.addEventListener('click',event=>{
    const button=event.target.closest('button[data-image-src]');if(!button||!safeSource(button.dataset.imageSrc))return;
    event.preventDefault();mount();trigger=button;
    const group=button.closest('.media-group');items=[...(group||button.parentElement).querySelectorAll('button[data-image-src]')].map(node=>({src:node.dataset.imageSrc,alt:node.querySelector('img')?.alt||'完整图片'})).filter(item=>safeSource(item.src));
    position=Math.max(0,items.findIndex(item=>item.src===button.dataset.imageSrc));dialog.classList.remove('original-size');zoom.textContent='原尺寸';show();dialog.showModal();
  });
  window.MediaViewer={close};
})();
