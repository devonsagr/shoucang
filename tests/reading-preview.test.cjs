const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8');
const fn=src.slice(src.indexOf('function renderReadingPreview('),src.indexOf('function renderDetail('));
const c={escape:s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),icon:()=>'<svg></svg>'};
vm.createContext(c);vm.runInContext(fn,c);
assert.equal(c.renderReadingPreview({}), '');
assert.equal(c.renderReadingPreview({reading_preview:{reading_only:false,model_used:false,text:'not allowed'}}),'');
assert.equal(c.renderReadingPreview({reading_preview:{reading_only:true,model_used:true,text:'wrong model label'}}),'');
const html=c.renderReadingPreview({reading_preview:{reading_only:true,model_used:false,source:'原文导读',text:'<script>bad</script>\n原作者第二句'}});
assert(html.includes('原文导读')&&html.includes('非AI')&&html.includes('概要')&&html.includes('&lt;script&gt;')&&!html.includes('<script>'));
assert(!html.includes('AI 总结'));
console.log('Reading preview: original-only rendering, explicit extractive label, empty/model guards and HTML escaping passed');

const modelHtml=c.renderReadingPreview({id:'fixture',body:'原文',content:{},reading_overview:{reading_only:true,model_used:true,source:'AI概要',text:'整体讨论了<script>bad()</script>这个问题。'}});
assert(modelHtml.includes('仅供筛选')&&modelHtml.includes('重新生成')&&!modelHtml.includes('<script>'));
const pending=c.renderReadingPreview({id:'fixture',body:'原文',content:{},overview_job:{state:'queued',progress:{}}});
assert(pending.includes('disabled')&&pending.includes('等待生成概要'));

let fragment={dataset:{},querySelector:()=>({open:true})},updates=0;
Object.defineProperty(fragment,'outerHTML',{set(html){assert(html.includes('概要'));updates++;fragment={dataset:{},querySelector:()=>({open:false})};}});
c.$=selector=>selector==='#readingOverview'?fragment:null;c.selected='fixture';c.current={id:'fixture',overview_source_hash:'frozen-source',notes:'未保存批注'};
const video={currentTime:62},draft={value:'未保存批注'};c.video=video;c.draft=draft;
const data={id:'fixture',overview_source_hash:'frozen-source',body:'原文',content:{},reading_overview:{reading_only:true,model_used:true,source:'AI概要',text:'整篇概括。'},overview_job:{state:'done'}};
c.updateReadingOverview(data);assert.equal(updates,1);assert.equal(c.video,video);assert.equal(video.currentTime,62);assert.equal(c.draft,draft);assert.equal(draft.value,'未保存批注');assert.equal(c.current.notes,'未保存批注');
c.updateReadingOverview(data);assert.equal(updates,1);c.updateReadingOverview({...data,overview_source_hash:'changed'});assert.equal(updates,1);c.selected='other';c.updateReadingOverview(data);assert.equal(updates,1);
console.log('Reading overview: fragment-only update, draft/player preservation, unchanged result and stale selection/source guards passed');
