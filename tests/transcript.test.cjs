const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context={};vm.createContext(context);vm.runInContext(fs.readFileSync('web/transcript.js','utf8')+'\nthis.timeline=TranscriptList;',context);
const Index=context.timeline.HeightIndex,heights=Array.from({length:6000},(_,i)=>48+(i%4)*28),index=new Index(6000,i=>heights[i]);
assert.equal(index.total,heights.reduce((a,b)=>a+b,0));assert.equal(index.at(0),0);assert.equal(index.at(index.total-1),5999);
for(let top=0;top<index.total;top+=311){const visible=index.window(top,620);assert(visible.end-visible.start<=37);assert(index.offsets[visible.start]<=top);assert(index.offsets[visible.end]>=Math.min(index.total,top+620));}
const old=index.total;assert(index.measure([[2,150],[3,90]]));assert.equal(index.total,old-heights[2]-heights[3]+240);
assert.equal(index.at(index.offsets[4000]),4000);
assert.equal(index.window(index.total-620,620).end,6000);
assert(!fs.readFileSync('web/app.js','utf8').includes('id="transcriptRange"'));
console.log('One continuous 6000-cue timeline: variable heights, bounded visible rows, first/last and no time-range selector passed');

// Layout harness: unlike a headless DOM without layout, this clamps scrollTop
// against measured content and delivers ResizeObserver after rows are mounted.
let nextFrame=0;const frames=new Map(),observers=[];
class Element{
  constructor(){this.children=[];this.style={};this.dataset={};this.events=new Map();this.clientWidth=440;this.clientHeight=320;this._top=0;}
  setAttribute(){}
  replaceChildren(...nodes){this.children=nodes;}
  set innerHTML(html){this.children=[...html.matchAll(/data-virtual-index="(\d+)" data-height="(\d+)"/g)].map(hit=>{const row=new Element();row.dataset.virtualIndex=hit[1];row.height=Number(hit[2]);return row;});}
  get scrollHeight(){return this.children.reduce((sum,node)=>sum+node.getBoundingClientRect().height,0);}
  get scrollTop(){this._top=Math.min(this._top,Math.max(0,this.scrollHeight-this.clientHeight));return this._top;}
  set scrollTop(value){this._top=Math.max(0,Math.min(value,this.scrollHeight-this.clientHeight));}
  getBoundingClientRect(){return {height:this.height??(this.style.height?parseFloat(this.style.height):this.scrollHeight)};}
  querySelectorAll(){return this.children.filter(node=>node.dataset.virtualIndex!==undefined);}
  addEventListener(name,fn){this.events.set(name,fn);}
  removeEventListener(name){this.events.delete(name);}
  contains(node){return this.children.includes(node);}
  closest(){return this;}
}
class Observer{
  constructor(callback){this.callback=callback;this.targets=new Set();observers.push(this);}
  observe(target){this.targets.add(target);}
  disconnect(){this.targets.clear();}
  deliver(){if(this.targets.size)this.callback([...this.targets].map(target=>({target})));}
}
context.document={createElement:()=>new Element()};context.ResizeObserver=Observer;
context.requestAnimationFrame=fn=>{frames.set(++nextFrame,fn);return nextFrame;};context.cancelAnimationFrame=id=>frames.delete(id);
function settle(){for(let round=0;round<15;round++){for(const observer of observers)observer.deliver();if(!frames.size)return;const ready=[...frames.values()];frames.clear();ready.forEach(fn=>fn());}assert.fail('timeline layout did not settle');}
const scroller=new Element(),items=Array.from({length:6000},(_,i)=>({sourceIndex:i,start:i*2,end:i*2+2,text:'A continuous cue.',translation:i%3?'':'A multiline translated cue.'}));
let manual=0,selectedCue=-1;
const mount=context.timeline.mount(scroller,items,(row,i)=>`<button data-virtual-index="${i}" data-height="${i%3?72:116}"></button>`,{onManualScroll:()=>manual++,onSelect:row=>selectedCue=row.sourceIndex});
settle();assert(scroller.children[1].children.length<45);assert.equal(scroller.scrollTop,0);assert.equal(scroller.children[1].children[0].dataset.virtualIndex,'0');
mount.last();settle();assert.equal(scroller.children[1].children.at(-1).dataset.virtualIndex,'5999');
assert(scroller.scrollTop+scroller.clientHeight>=scroller.scrollHeight-3,'the last cue must actually be visible, beyond the overscan');
scroller.events.get('wheel')({type:'wheel'});scroller.scrollTop-=240;scroller.events.get('scroll')();settle();assert(scroller.scrollTop+scroller.clientHeight<scroller.scrollHeight-3,'manual scrolling up must release the end position');
mount.first();settle();assert.equal(scroller.scrollTop,0);
mount.follow(8000);settle();assert(scroller.children[1].children.some(row=>row.dataset.virtualIndex==='4000'));
const anchor=mount.anchor();mount.first();settle();mount.restore(anchor);settle();assert.equal(mount.anchor().sourceIndex,anchor.sourceIndex);
scroller.events.get('wheel')({type:'wheel'});assert.equal(manual,2);
const row=scroller.children[1].children[5];scroller.children[1].events.get('click')({target:row});assert.equal(selectedCue,Number(row.dataset.virtualIndex));
mount.destroy();assert.equal(scroller.events.size,0);assert(observers.every(observer=>observer.targets.size===0));
console.log('Measured DOM lifecycle: bottom reachability, cue following, anchor restoration, manual scroll and disposal passed');
