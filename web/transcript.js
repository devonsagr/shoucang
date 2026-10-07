/* A single scrollable timeline with measured rows, not time-range pages. */
const TranscriptList=(()=>{
  class HeightIndex{
    constructor(count,estimate=()=>64){this.heights=Array.from({length:count},(_,i)=>Math.max(48,estimate(i)));this.rebuild();}
    rebuild(){this.offsets=new Float64Array(this.heights.length+1);for(let i=0;i<this.heights.length;i++)this.offsets[i+1]=this.offsets[i]+this.heights[i];}
    get total(){return this.offsets.at(-1);}
    at(y){let left=0,right=this.heights.length;while(left<right){const middle=(left+right)>>1;if(this.offsets[middle+1]<=y)left=middle+1;else right=middle;}return Math.min(left,Math.max(0,this.heights.length-1));}
    window(top,height,overscan=10){return {start:Math.max(0,this.at(top)-overscan),end:Math.min(this.heights.length,this.at(top+height)+overscan+1)};}
    measure(changes){let changed=false;for(const [i,height] of changes){if(i>=0&&i<this.heights.length&&height>0&&Math.abs(this.heights[i]-height)>.75){this.heights[i]=height;changed=true;}}if(changed)this.rebuild();return changed;}
  }
  function mount(scroller,items,renderRow,{onSelect=()=>{},onManualScroll=()=>{},onRender=()=>{}}={}){
    let disposed=false,frame=0,range='',rangeStart=0,rangeEnd=0,pinnedEnd=false,width=scroller.clientWidth;
    const estimate=i=>{const row=items[i],columns=Math.max(10,(scroller.clientWidth-76)/9);return Math.max(48,20+Math.ceil(row.text.length/columns)*26+(row.translation?8+Math.ceil(row.translation.length/columns)*24:0));};
    let index=new HeightIndex(items.length,estimate);
    const top=document.createElement('div'),window=document.createElement('div'),bottom=document.createElement('div');
    top.className=bottom.className='caption-spacer';top.setAttribute('aria-hidden','true');bottom.setAttribute('aria-hidden','true');window.className='caption-window';
    scroller.replaceChildren(top,window,bottom);
    const spacers=()=>{top.style.height=index.offsets[rangeStart]+'px';bottom.style.height=(index.total-index.offsets[rangeEnd])+'px';};
    const schedule=()=>{if(!disposed&&!frame)frame=requestAnimationFrame(render);};
    const observer=new ResizeObserver(entries=>{
      if(disposed)return;
      const anchor=index.at(scroller.scrollTop),offset=scroller.scrollTop-index.offsets[anchor],atBottom=pinnedEnd||scroller.scrollTop+scroller.clientHeight>=scroller.scrollHeight-3;
      const changes=entries.filter(e=>e.target!==scroller).map(e=>[Number(e.target.dataset.virtualIndex),e.target.getBoundingClientRect().height]);
      let changed=false;
      if(scroller.clientWidth!==width){width=scroller.clientWidth;index=new HeightIndex(items.length,estimate);range='';changed=true;}
      changed=index.measure(changes)||changed;
      if(changed){spacers();pinnedEnd=atBottom;scroller.scrollTop=atBottom?scroller.scrollHeight:Math.max(0,index.offsets[anchor]+Math.min(offset,index.heights[anchor]-1));schedule();}
    });
    function render(){
      frame=0;if(disposed)return;
      pinnedEnd=pinnedEnd||Boolean(range)&&scroller.scrollTop+scroller.clientHeight>=scroller.scrollHeight-3;
      const {start,end}=index.window(scroller.scrollTop,scroller.clientHeight||480),key=start+':'+end;
      rangeStart=start;rangeEnd=end;
      if(key!==range){
        range=key;observer.disconnect();window.innerHTML=items.slice(start,end).map((row,i)=>renderRow(row,start+i)).join('');
        window.querySelectorAll('[data-virtual-index]').forEach(row=>observer.observe(row));observer.observe(scroller);
      }
      spacers();if(pinnedEnd)scroller.scrollTop=scroller.scrollHeight;onRender();
    }
    const click=event=>{const row=event.target.closest('[data-virtual-index]');if(row&&window.contains(row))onSelect(items[Number(row.dataset.virtualIndex)],row);};
    const manual=event=>{if(event.type!=='keydown'||['ArrowDown','ArrowUp','PageDown','PageUp','Home','End',' '].includes(event.key)){pinnedEnd=false;onManualScroll();}};
    scroller.addEventListener('scroll',schedule,{passive:true});scroller.addEventListener('wheel',manual,{passive:true});scroller.addEventListener('pointerdown',manual);scroller.addEventListener('keydown',manual);window.addEventListener('click',click);
    observer.observe(scroller);render();
    return {
      scrollToIndex(i){if(disposed||!items.length)return;pinnedEnd=false;scroller.scrollTop=Math.max(0,index.offsets[Math.max(0,Math.min(i,items.length-1))]-scroller.clientHeight/3);render();},
      first(){this.scrollToIndex(0);},
      last(){if(disposed)return;pinnedEnd=true;scroller.scrollTop=scroller.scrollHeight;render();},
      anchor(){const i=index.at(scroller.scrollTop);return {sourceIndex:items[i]?.sourceIndex,offset:scroller.scrollTop-index.offsets[i]};},
      restore(anchor){const i=items.findIndex(row=>row.sourceIndex===anchor?.sourceIndex);if(i>=0){pinnedEnd=false;scroller.scrollTop=index.offsets[i]+anchor.offset;render();}},
      follow(seconds){const i=items.findIndex(row=>seconds>=row.start&&seconds<row.end);if(i<0)return;const top=index.offsets[i],end=index.offsets[i+1];if(top<scroller.scrollTop||end>scroller.scrollTop+scroller.clientHeight)this.scrollToIndex(i);},
      destroy(){disposed=true;cancelAnimationFrame(frame);observer.disconnect();scroller.removeEventListener('scroll',schedule);scroller.removeEventListener('wheel',manual);scroller.removeEventListener('pointerdown',manual);scroller.removeEventListener('keydown',manual);window.removeEventListener('click',click);}
    };
  }
  return {HeightIndex,mount};
})();
