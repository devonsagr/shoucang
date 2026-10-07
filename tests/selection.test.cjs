const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
const helpers=app.slice(app.indexOf('function sourceQueueContext(){'),app.indexOf('async function refresh()'));
function fixture(count=130){
  const fields={'#platformFilter':{value:'x'},'#search':{value:''},'#originFilter':{value:'favorite'},'#captureFilter':{value:''},'#materialList':{scrollTop:170}};
  let remaining=Array.from({length:count},(_,i)=>({id:'m'+i,revision:1,title:'材料'+i,trashed:false}));
  const requests=[],messages=[];
  const c={filter:'all',layerPhase:'all',topicFilter:'',dirty:false,selected:'m50',current:{id:'m50',revision:1},visibleLimit:80,catalogueItems:remaining,
    catalogueContext:'',selectionScope:'',multiSelect:true,batchRunning:false,purgeSelection:null,batchFailures:[],batchProgress:'',checkedMaterials:new Map(),
    $:key=>fields[key],displayTitle:m=>m.title,
    inFirstLibrary:()=>['callable','digest'].includes(c.filter),trashCatalogue:()=>c.filter==='trash'||c.layerPhase==='trash',
    toast:(...args)=>messages.push(args),
    api:async(path,method,body)=>{
      requests.push(body);if(c.networkFailure&&requests.length===2)throw Error('连接中断');
      const results=body.items.map(m=>({id:m.id,ok:m.id!==c.failId,...(m.id===c.failId?{error:'材料已改变，请重新勾选后重试'}:{revision:m.revision+1}),...(m.id===c.warnId?{warning:'状态已保存，清理需核对'}:{})}));
      const successful=new Set(results.filter(r=>r.ok).map(r=>r.id));if(body.action!=='retry')remaining=remaining.filter(m=>!successful.has(m.id));
      if(c.duringRequest)c.duringRequest();return {results};
    },
    refresh:async()=>{c.catalogueItems=remaining;c.updateSelectionScope();const available=new Set(remaining.map(m=>m.id));for(const id of c.checkedMaterials.keys())if(!available.has(id))c.checkedMaterials.delete(id);},
    select:async id=>{c.selected=id;},clearReader:()=>{c.selected=null;},
    saveNotes:async()=>{c.dirty=false;c.current.revision=2;}}
  vm.createContext(c);vm.runInContext(helpers,c);c.renderSelectionControls=()=>{};
  c.catalogueContext=c.sourceQueueContext();c.selectionScope=c.catalogueContext;
  return {c,fields,requests,messages};
}
async function run(){
  let f=fixture();f.c.chooseAllMaterials(true);
  assert.equal(f.c.checkedMaterials.size,130,'select all must include results beyond the first 80 rendered cards');
  f.c.catalogueItems.push({id:'new-arrival',revision:1,title:'新材料'});
  assert.equal(f.c.batchTargets().length,130,'incoming materials are not silently added to an already reviewed selection');
  f.c.chooseBatchItem('m0',false);assert.equal(f.c.checkedMaterials.size,129);
  f.c.chooseAllMaterials(false);assert.equal(f.c.checkedMaterials.size,0);
  // A selected snapshot does not silently adopt a newer server revision.
  f.c.chooseBatchItem('m1',true);f.c.catalogueItems.find(m=>m.id==='m1').revision=8;
  assert.equal(f.c.batchTargets()[0].revision,1);
  f.c.purgeSelection={};f.c.chooseBatchItem('m2',true);assert.equal(f.c.purgeSelection,null);
  for(const change of [f=>f.fields['#search'].value='new',f=>f.fields['#platformFilter'].value='youtube',f=>f.c.filter='digest',f=>f.c.layerPhase='trash']){
    f=fixture();f.c.chooseAllMaterials(true);change(f);f.c.updateSelectionScope();assert.equal(f.c.checkedMaterials.size,0);assert.equal(f.c.multiSelect,false);
  }
  f=fixture();f.c.chooseAllMaterials(true);f.c.failId='m20';await f.c.runMaterialBatch('trash');
  assert.deepEqual(f.requests.map(r=>r.items.length),[100,30]);assert.equal(f.c.checkedMaterials.size,1);assert(f.c.checkedMaterials.has('m20'));
  assert.equal(f.c.selected,'m20');assert.equal(f.c.filter,'all');assert.equal(f.c.batchFailures.length,1);assert(f.messages[0][0].includes('129 条'));
  f=fixture();f.c.chooseAllMaterials(true);await f.c.runMaterialBatch('trash');assert.equal(f.c.selected,null);assert.equal(f.c.checkedMaterials.size,0);
  f=fixture();f.c.warnId='m50';f.c.chooseBatchItem('m50',true);await f.c.runMaterialBatch('trash');
  assert.equal(f.c.checkedMaterials.size,0);assert.equal(f.c.selected,'m51');assert(f.c.batchFailures[0].warning);assert(f.messages[0][0].includes('清理需核对'));
  // Preserve and include an explicitly saved draft in the deletion snapshot.
  f=fixture();f.c.chooseBatchItem('m50',true);f.c.dirty=true;await f.c.runMaterialBatch('trash');assert.equal(f.requests[0].items[0].revision,2);assert.equal(f.c.selected,'m51');
  f=fixture();f.c.chooseBatchItem('m50',true);f.c.dirty=true;let finishSave;
  f.c.saveNotes=()=>new Promise(resolve=>{finishSave=()=>{f.c.dirty=false;f.c.current.revision=2;resolve();};});
  const saving=f.c.runMaterialBatch('trash');await f.c.runMaterialBatch('trash');assert.equal(f.requests.length,0);finishSave();await saving;assert.equal(f.requests.length,1,'a second click while saving a draft must not submit twice');
  // A late result must not take the reader back from a different filter or new draft.
  for(const change of [c=>c.dirty=true,c=>c.selected='m100',c=>{c.filter='later';c.updateSelectionScope();}]){
    f=fixture();f.c.chooseBatchItem('m50',true);f.c.duringRequest=()=>change(f.c);await f.c.runMaterialBatch('trash');assert.notEqual(f.c.selected,'m51');
  }
  f=fixture(250);f.c.chooseAllMaterials(true);f.c.networkFailure=true;await f.c.runMaterialBatch('trash');
  assert.equal(f.requests.length,2,'a broken connection must stop rather than keep submitting unconfirmed batches');
  assert.equal(f.c.checkedMaterials.size,150);assert.equal(f.c.batchFailures.length,150);assert(f.messages[0][0].includes('结果待核对'));
  f=fixture();f.c.chooseAllMaterials(true);await f.c.runMaterialBatch('retry');
  assert.deepEqual(f.requests.map(r=>r.items.length),[100,30]);assert.equal(f.c.catalogueItems.length,130);assert.equal(f.c.selected,'m50');
  assert.equal(f.c.checkedMaterials.size,0);assert(f.messages[0][0].includes('排队 130 条')&&!f.messages[0][0].includes('采集成功'));
  console.log('Selection: full-filter/snapshot scope, chunking, partial failure, next reader, draft guards and interrupted request recovery passed');
}
run().catch(e=>{console.error(e);process.exitCode=1;});
