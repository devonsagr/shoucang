const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const elements=new Map();
function parse(html){for(const hit of html.matchAll(/id="([^"]+)"/g))element('#'+hit[1]);}
function element(key){
  if(elements.has(key))return elements.get(key);
  const node={value:'',checked:false,children:[],innerHTML:'',focus(){this.focused=true;},select(){this.selected=true;},addEventListener(name,fn){this['on'+name]=fn;},remove(){elements.delete(key);},insertAdjacentHTML(where,html){this.insertedHTML=html;parse(html);},prepend(child){this.children.unshift(child);},append(child){this.children.push(child);},close(){this.closed=true;}};
  Object.defineProperty(node,'innerHTML',{get(){return this.html||'';},set(html){this.html=html;parse(html);}});
  elements.set(key,node);return node;
}
let lastDialog,lastToast,requests=[],savedNotes=0,selections=0,chosenLibraries=[],continuedQueues=[],confirmError=null,copiedText='';
const m={id:'fixture',platform:'x',collection:'ready',notes:'我自己的理解',summary:'AI 建议尚未执行',title:'原材料',topic:'tech',revision:4,first_layer:{track:'digest',path:'T:\\示例库\\收藏材料库\\02_消化暂存\\夹具.md'},content:{first_layer_context:{annotation:'待消化的问题',note:'收藏材料库/02_消化暂存/夹具.md'},knowledge_context:{vault:'T:\\示例库',notes:[{path:'06_资料与教程/已有理解.md',title:'已有理解',sha256:'fixture'}]}}};
const preview={id:'preview-fixture',hash:'immutable-hash',knowledge_markdown:'处理正文 <script>unsafe()</script>',markdown:'原文',destination:'T:\\示例库\\06_资料与教程\\新判断.md',source_destination:'T:\\示例库\\收藏处理器\\X\\已完成\\来源\\index.md',payload:{knowledge_output:{vault:'T:\\示例库',note:'06_资料与教程/新判断.md'}}};
const context={current:m,selected:m.id,dirty:false,document:{createElement(){const node=element('#knowledgeSection');return node;}},
  $:key=>elements.get(key)||null,icon:()=>'',escape:s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  displayTitle:item=>item.title,guard:fn=>fn,busy:(button,fn)=>fn,saveNotes:async()=>{savedNotes++;context.current.notes=element('#notesText').value;context.current.revision++;context.dirty=false;},toast:(text,error,action)=>{lastToast={text,error,action};},
  navigator:{clipboard:{writeText:async text=>{copiedText=text;}}},
  captureSourceQueue:id=>({id,ids:[id,'next-source'],context:'current-source-filters',scrollTop:240}),continueSourceQueue:async queue=>{continuedQueues.push(queue);},
  chooseLibrary:async(mode,track)=>{chosenLibraries.push({mode,track});},select:async()=>{selections++;},openProcessing:()=>{},dialog:(title,html)=>{lastDialog={title,html};parse(html);},api:async(path,method,body)=>{
    requests.push({path,method,body});
    if(path.endsWith('/knowledge-folders'))return [{path:'06_资料与教程',title:'资料与教程'}];
    if(path.endsWith('/organization-prompt'))return {text:'合成提示词：材料归位 <script>unsafe()</script>\n保留批注'};
    if(path.endsWith('/processing-paths'))return {formal_folders:[{path:'06_资料与教程',absolute_path:'T:\\示例库\\06_资料与教程'}]};
    if(path.endsWith('/push-preview'))return preview;
    if(path.includes('/confirm')){if(confirmError)throw new Error(confirmError);return {state:'confirmed',path:preview.destination,layer_id:'l1_fixture'};}
    return {job_id:'job-fixture'};
  }};
for(const key of ['#processingPanelBody','#notesText','#notesSection .note-editor','#generateAi','#dialog','#saveNotes','#saveState'])element(key);
element('#notesText').value='未保存的阅读草稿';
vm.createContext(context);vm.runInContext(fs.readFileSync('web/knowledge.js','utf8')+'\nthis.ui=KnowledgeUI;',context);
async function run(){
  context.ui.mount({...m,first_layer:undefined});assert(element('#saveCallable')&&element('#saveDigest'));assert(!elements.has('#annotationSubmit'),'raw first save must not require AI');assert.equal(requests.length,0);
  context.ui.mount(m);assert.equal(requests.length,0,'mounting must not upload private notes or write Vault');
  assert.equal(element('#notesText').value,'未保存的阅读草稿');
  assert(element('#knowledgeSection').innerHTML.includes('已有理解'));
  assert(context.ui.noteURL('T:\\示例库','06_资料与教程/已有理解.md').includes('vault=%E7%A4%BA%E4%BE%8B%E5%BA%93'));
  context.dirty=true;await element('#annotationSubmit').onclick();assert.equal(savedNotes,1);
  assert.equal(requests.at(-1).path,'/materials/fixture/ai');assert.equal(requests.at(-1).body.include_knowledge,true);
  assert.equal(requests.at(-1).body.from_annotation,true);assert.equal(requests.at(-1).body.revision,m.revision);
  assert.equal(requests.at(-1).body.second_pass,false);
  context.ui.updateJob({...m,ai_job:{state:'failed',error:'<合成错误>'}});
  assert(element('#annotationAiStatus').textContent.includes('整理未完成：<合成错误>'));
  assert(context.ui.draft(m).includes('我的批注')&&context.ui.draft(m).includes('AI 整理（已查看'));
  requests=[];await context.ui.compose(m,true);
  element('#knowledgeTitle').value='新判断';element('#knowledgeText').value='用户编辑后的具体理解';element('#knowledgeFolder').value='06_资料与教程';element('#knowledgeComplete').checked=false;
  await element('#previewKnowledgeOutput').onclick();
  const request=requests.find(r=>r.path.endsWith('/push-preview'));
  assert.equal(request.body.destination,'obsidian');assert.equal(request.body.complete_processing,false);
  assert.equal(request.body.knowledge_output.text,'用户编辑后的具体理解');
  assert(!requests.some(r=>r.path.includes('/confirm')),'a preview must not automatically confirm');
  assert(lastDialog.html.includes('原文')&&lastDialog.html.includes('收藏处理器'));
  assert(lastDialog.html.includes('&lt;script&gt;')&&!lastDialog.html.includes('<script>'));
  await element('#editKnowledgeOutput').onclick();assert(lastDialog.html.includes('用户编辑后的具体理解'),'returning to edit keeps the draft');
  // Return to a preview to explicitly confirm the frozen id/hash.
  element('#knowledgeTitle').value='新判断';element('#knowledgeText').value='用户编辑后的具体理解';element('#knowledgeFolder').value='06_资料与教程';element('#knowledgeComplete').checked=false;
  await element('#previewKnowledgeOutput').onclick();await element('#confirmKnowledgeOutput').onclick();
  assert.equal(requests.at(-1).path,'/pushes/preview-fixture/confirm');assert.equal(requests.at(-1).body.hash,'immutable-hash');assert.equal(selections,2);
  assert.equal(lastToast.text,'材料已归位');assert.equal(element('#dialog').closed,true,'successful save must not open another success dialog');
  assert.equal(requests.filter(r=>r.path.includes('/confirm')).length,1);
  requests=[];await context.ui.compose(m,true,null,'manual');assert(lastDialog.html.includes('id="knowledgeText"'));assert(!lastDialog.html.includes('待消化的问题</textarea>'),'a purpose annotation must not masquerade as understanding');
  element('#knowledgeText').value='我独立写的知识';element('#knowledgeTitle').value='我的知识';element('#knowledgeFolder').value='06_资料与教程';await element('#previewKnowledgeOutput').onclick();assert.equal(requests.find(r=>r.path.endsWith('/push-preview')).body.knowledge_output.authorship,'manual');
  context.current={...m,first_layer:undefined};context.ui.mount(context.current);
  const beforeFirstSaveSelections=selections;
  for(const [button,track] of [['#saveCallable','callable'],['#saveDigest','digest']]){
    requests=[];element('#notesText').value='这条材料的用途或疑问';
    const beforeContinue=continuedQueues.length,beforeDialog=lastDialog;await element(button).onclick();
    assert.equal(requests.at(-1).body.shelf_output.stage,track);assert.equal(requests.at(-1).body.complete_processing,false);
    assert(!requests.some(r=>r.path.endsWith('/ai')||r.path.includes('/confirm')));assert.equal(continuedQueues.length,beforeContinue);
    assert.equal(lastDialog,beforeDialog,'first preview must stay in the annotation panel');
    assert.equal(element(button).textContent,'确认保存');assert(element('#firstLayerChoices').insertedHTML.includes(preview.destination));
    await element(button).onclick();
    assert.equal(requests.at(-1).body.hash,'immutable-hash');assert.equal(continuedQueues.at(-1).id,m.id);
    assert.equal(continuedQueues.length,beforeContinue+1);assert.equal(chosenLibraries.length,0,'save must keep the source library');
    assert.equal(selections,beforeFirstSaveSelections,'save must not open the first-layer record automatically');
    assert.equal(lastToast.action,undefined,'save feedback must not add a blocking view button');
  }
  preview.duplicate=true;await element('#saveCallable').onclick();assert.equal(element('#saveCallable').textContent,'继续处理');
  await element('#saveCallable').onclick();assert.equal(continuedQueues.length,3);assert.equal(chosenLibraries.length,0);
  await element('#saveDigest').onclick();confirmError='fixture confirmation failed';
  await assert.rejects(element('#saveDigest').onclick(),/fixture confirmation failed/);
  assert.equal(continuedQueues.length,3,'failed confirmation must not advance the queue');assert(elements.has('#firstLayerPreview'));
  confirmError=null;context.dirty=true;element('#notesText').value='修改了批注';context.ui.invalidateFirstPreview();
  assert.equal(element('#saveDigest').textContent,'以后细读');assert(!elements.has('#firstLayerPreview'));
  requests=[];await element('#saveDigest').onclick();assert(!requests.some(r=>r.path.includes('/confirm')),'changed note needs a new preview');
  // Editing while a preview is loading must never install an old confirm button.
  context.ui.invalidateFirstPreview();const realApi=context.api;
  context.api=async(...args)=>{const result=await realApi(...args);if(args[0].endsWith('/push-preview')){element('#notesText').value='请求期间新写的备注';context.dirty=true;}return result;};
  await element('#saveCallable').onclick();assert(!elements.has('#firstLayerPreview'));assert.equal(element('#saveCallable').textContent,'留作资料');context.api=realApi;
  context.dirty=false;await element('#saveCallable').onclick();
  let finishOldConfirm;context.api=async(...args)=>args[0].includes('/confirm')?new Promise(resolve=>{finishOldConfirm=resolve;}):realApi(...args);
  const pendingOld=element('#saveCallable').onclick();
  context.current={...context.current,id:'another-source',notes:'下一条批注',revision:1};context.selected=context.current.id;
  context.ui.mount(context.current);element('#notesText').value='下一条批注';await element('#saveDigest').onclick();
  const newPreview=element('#firstLayerPreview'),beforeLateContinue=continuedQueues.length;
  finishOldConfirm({state:'confirmed'});await pendingOld;
  assert.equal(element('#firstLayerPreview'),newPreview);assert.equal(element('#saveDigest').textContent,'继续处理');
  assert.equal(continuedQueues.length,beforeLateContinue,'a late confirmation cannot clear or advance a newer preview');context.api=realApi;
  await context.ui.showOrganizationPrompt();assert(lastDialog.html.includes('&lt;script&gt;')&&!lastDialog.html.includes('<script>'));
  await element('#copyOrganizationPrompt').onclick();assert(copiedText.includes('保留批注'));assert.equal(element('#promptCopyState').textContent,'已复制');
  context.navigator.clipboard.writeText=async()=>{throw new Error('fixture clipboard denied');};await element('#copyOrganizationPrompt').onclick();assert(element('#organizationPrompt').selected);assert(element('#promptCopyState').textContent.includes('手动复制'));
  context.current=m;await context.ui.filing(m);await element('#referenceMaterial').onclick();assert.equal(lastDialog.title,'材料归位');
  await context.ui.filing(m);await element('#manualKnowledge').onclick();assert.equal(lastDialog.title,'我的知识稿');
  console.log('Knowledge UI: inline exact-hash confirmation, source continuation, edited/late-preview protection, no view toast, prompt escaping/copy/fallback passed');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
