const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/tasks.js','utf8');
class Node{
  constructor(){this.hidden=false;this.dataset={};this.attrs={};this.handlers={};this.classList={toggle(){}};this.scrollTop=0;this.innerHTML='';}
  setAttribute(k,v){this.attrs[k]=v;}
  addEventListener(k,fn){this.handlers[k]=fn;}
  focus(){this.focused=true;}
  contains(n){return n===this||Object.values(this.nodes||{}).includes(n)||(this.tabs||[]).includes(n);}
  click(){this.handlers.click?.({target:this});}
  closest(s){return s==='[data-task-tab]'&&this.dataset.taskTab?this:null;}
  querySelector(s){return this.nodes[s]||this.tabs.find(t=>s==='[data-task-tab="'+t.dataset.taskTab+'"]');}
  querySelectorAll(){return this.tabs;}
}
const button=new Node(),badge=new Node(),panel=new Node();
panel.nodes=Object.fromEntries(['taskRunning','taskQueued','taskAttention','taskConnection','taskRows','taskShown'].map(id=>['#'+id,new Node()]));
panel.tabs=['active','attention','recent'].map(key=>{const n=new Node();n.dataset.taskTab=key;return n;});
let tick,requests=[],next,fail=false;
const document={hidden:false,handlers:{},body:{append(){}},querySelector:s=>s==='#taskMonitorBtn'?button:badge,createElement:()=>panel,addEventListener(k,fn){this.handlers[k]=fn;}};
const c={document,window:{},setInterval(fn){tick=fn;return 1;}};vm.createContext(c);vm.runInContext(source,c);
const escaped=s=>s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const activity=(state='running')=>({counts:{running:state==='running'?1:0,queued:state==='running'?242:0,attention:0},active:state==='running'?[{title:'<合成视频>',platform:'douyin',kind:'collect',label:'转写字幕',state,status_label:'进行中',progress:{seconds:60,duration:600,message:'转写到1分钟'}}]:[],attention:[],recent:state==='done'?[{title:'合成视频',platform:'douyin',kind:'collect',state:'done',status_label:'已结束',progress:{}}]:[]});
(async()=>{
 next=activity();await c.window.TaskMonitor.init({api:async(...args)=>{requests.push(args);if(fail)throw Error('offline');return next;},escape:escaped,icon:()=>'<svg></svg>',names:{douyin:'抖音'}});
 assert.equal(badge.textContent,'243');assert.equal(button.dataset.state,'running');assert(panel.hidden);
 c.window.TaskMonitor.open();assert(!panel.hidden&&button.attrs['aria-expanded']==='true');assert(panel.nodes['#taskRows'].innerHTML.includes('value="10"'));assert(panel.nodes['#taskRows'].innerHTML.includes('&lt;合成视频&gt;'));assert(!panel.nodes['#taskRows'].innerHTML.includes('<合成视频>'));
 await new Promise(resolve=>setImmediate(resolve));
 panel.nodes['#taskRows'].scrollTop=110;await c.window.TaskMonitor.refresh();assert.equal(panel.nodes['#taskRows'].scrollTop,110);
 document.handlers.keydown({key:'Escape',preventDefault(){}});assert(panel.hidden&&button.focused);
 document.handlers.visibilitychange();await new Promise(resolve=>setImmediate(resolve));
 next=activity('done');tick();await new Promise(resolve=>setImmediate(resolve));assert.equal(button.dataset.state,'idle');assert(badge.hidden);
 c.window.TaskMonitor.open();await new Promise(resolve=>setImmediate(resolve));panel.handlers.click({target:panel.tabs[2]});assert(panel.nodes['#taskRows'].innerHTML.includes('已结束'));
 panel.handlers.keydown({key:'ArrowLeft',target:panel.tabs[2],preventDefault(){}});assert.equal(panel.tabs[1].attrs['aria-selected'],'true');assert.equal(panel.tabs[1].attrs.tabindex,'0');
 panel.handlers.click({target:panel.tabs[2]});const rows=panel.nodes['#taskRows'].innerHTML;fail=true;await c.window.TaskMonitor.refresh();assert.equal(button.dataset.state,'offline');assert.equal(panel.nodes['#taskRows'].innerHTML,rows);assert(!panel.nodes['#taskConnection'].hidden);
 fail=false;await c.window.TaskMonitor.refresh();assert(panel.nodes['#taskConnection'].hidden);
 assert(requests.length>=6&&requests.every(a=>a.length===1&&a[0]==='/tasks'));
 const html=fs.readFileSync('web/index.html','utf8'),app=fs.readFileSync('web/app.js','utf8');assert(html.indexOf('/static/tasks.js')<html.indexOf('/static/app.js'));assert(app.includes('TaskMonitor.init({api,escape,icon,names})'));
 const fresh={document,window:{},setInterval:()=>1};vm.createContext(fresh);vm.runInContext(source,fresh);
 await fresh.window.TaskMonitor.init({api:async()=>{throw Error('first connection unavailable');},escape:escaped,icon:()=>'',names:{}});
 assert.equal(button.title,'尚未取得任务状态');assert(panel.nodes['#taskConnection'].textContent.startsWith('尚未取得'));assert(panel.innerHTML.includes('id="taskRunning">—'));
 console.log('Task monitor: all-active count, escaped progress, close/filter-independent polling, completed state, retained offline state and integration passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
