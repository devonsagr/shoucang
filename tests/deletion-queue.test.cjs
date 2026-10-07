const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
const helpers=app.slice(app.indexOf('function sourceQueueContext(){'),app.indexOf('async function refresh()'));
const removal=app.slice(app.indexOf('async function removeMaterial('),app.indexOf('function guard('));
function fixture(ids=['before','current','next','tail']){
  const fields={'#platformFilter':{value:'x'},'#search':{value:''},'#originFilter':{value:''},'#captureFilter':{value:''},'#materialList':{scrollTop:142}};
  const calls=[];let remaining=[...ids];
  const c={filter:'pending',layerPhase:'all',topicFilter:'music',detailSeq:1,dirty:false,selected:'current',visibleLimit:80,catalogueItems:ids.map(id=>({id})),
    $:key=>fields[key],inFirstLibrary:()=>['callable','digest'].includes(c.filter),
    api:async(path)=>{calls.push(path);remaining=remaining.filter(id=>!path.includes(id));if(c.duringDelete)c.duringDelete();},
    refresh:async()=>{c.catalogueItems=remaining.map(id=>({id}));},
    select:async id=>{c.selected=id;},clearReader:()=>{c.selected=null;},toast:()=>{},
    saveNotes:async()=>{c.dirty=false;calls.push('save');}};
  vm.createContext(c);vm.runInContext(helpers+removal,c);return {c,fields,calls};
}
async function run(){
  let f=fixture();await f.c.removeMaterial('current');
  assert.equal(f.c.selected,'next','deleting the current item must open the following material');
  assert.equal(f.fields['#materialList'].scrollTop,142);assert.equal(f.c.filter,'pending');
  f=fixture(['before','current']);await f.c.removeMaterial('current');assert.equal(f.c.selected,'before');
  f=fixture(['current']);await f.c.removeMaterial('current');assert.equal(f.c.selected,null);
  f=fixture();await f.c.removeMaterial('tail');assert.equal(f.c.selected,'current','deleting another row must leave the reader alone');
  for(const filter of ['trash','callable','digest']){
    f=fixture();f.c.filter=filter;f.c.layerPhase='trash';await f.c.removeMaterial('current');assert.equal(f.c.selected,'next');assert.equal(f.c.filter,filter);
  }
  f=fixture();f.c.dirty=true;await f.c.removeMaterial('current');assert.equal(f.calls[0],'save');assert.equal(f.c.selected,'next');
  for(const change of [c=>c.selected='tail',c=>c.dirty=true,c=>c.layerPhase='pending',c=>c.filter='later',c=>c.detailSeq++]){
    f=fixture();f.c.duringDelete=()=>change(f.c);await f.c.removeMaterial('current');
    assert.notEqual(f.c.selected,'next','a late deletion must not steal another selection, draft or view');
  }
  console.log('Deletion queue: next/previous/empty, other row, all libraries, saved draft and late-navigation protection passed');
}
run().catch(e=>{console.error(e);process.exitCode=1;});
