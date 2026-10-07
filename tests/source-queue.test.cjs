const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
const helpers=app.slice(app.indexOf('function sourceQueueContext(){'),app.indexOf('async function refresh()'));
assert(helpers.includes('async function continueSourceQueue('));
function fixture(ids=['before','saved','next','tail'],remaining=['tail','next','before']){
  const fields={'#platformFilter':{value:'x'},'#search':{value:'tools'},'#originFilter':{value:'favorite'},'#captureFilter':{value:''},'#materialList':{scrollTop:318}};
  const calls=[];
  const context={filter:'pending',layerPhase:'all',topicFilter:'tech',dirty:false,selected:'saved',visibleLimit:80,catalogueItems:ids.map(id=>({id})),
    $:key=>fields[key],inFirstLibrary:()=>['callable','digest'].includes(context.filter),
    refresh:async()=>{calls.push('refresh');context.catalogueItems=remaining.map(id=>({id}));fields['#materialList'].scrollTop=0;if(context.duringRefresh)context.duringRefresh();},
    select:async(id,force)=>{calls.push({id,force});context.selected=id;fields['#materialList'].scrollTop=0;},
    clearReader:()=>{calls.push('clear');context.selected=null;}};
  vm.createContext(context);vm.runInContext(helpers,context);
  return {context,fields,calls};
}
async function run(){
  // A note save or polling may reorder the list; continue from its earlier position.
  let f=fixture(),queue=f.context.captureSourceQueue('saved'),originalContext=f.context.sourceQueueContext();
  f.context.catalogueItems.reverse();await f.context.continueSourceQueue(queue);
  assert.equal(f.context.selected,'next');assert.equal(f.context.sourceQueueContext(),originalContext);assert.equal(f.fields['#materialList'].scrollTop,318);
  assert.equal(f.calls[1].force,undefined,'advancing must respect any new draft');
  // Skip a following item that has left this filtered queue.
  f=fixture(undefined,['before','tail']);await f.context.continueSourceQueue(f.context.captureSourceQueue('saved'));assert.equal(f.context.selected,'tail');
  // The last item can continue with an earlier remaining item without switching library.
  f=fixture(['before','saved'],['before']);await f.context.continueSourceQueue(f.context.captureSourceQueue('saved'));assert.equal(f.context.selected,'before');assert.equal(f.context.filter,'pending');
  // Finishing the whole queue clears the reader but retains every filter.
  f=fixture(['saved'],[]);originalContext=f.context.sourceQueueContext();await f.context.continueSourceQueue(f.context.captureSourceQueue('saved'));
  assert.equal(f.context.selected,null);assert(f.calls.includes('clear'));assert.equal(f.context.sourceQueueContext(),originalContext);
  // An archive may still contain the saved source; don't reopen it when it's the only entry.
  f=fixture(['saved'],['saved']);f.context.filter='source_archive';await f.context.continueSourceQueue(f.context.captureSourceQueue('saved'));assert.equal(f.context.selected,null);assert.equal(f.context.filter,'source_archive');
  // Use the complete queue even when the next row was beyond the rendered first 80.
  const ids=Array.from({length:100},(_,i)=>'m'+i);f=fixture(ids,['new1','new2',...ids.filter(id=>id!=='m79')]);f.context.selected='m79';
  await f.context.continueSourceQueue(f.context.captureSourceQueue('m79'));assert.equal(f.context.selected,'m80');assert.equal(f.context.visibleLimit,82);
  // Another selection, filter, library, or draft must not be displaced by late confirmation.
  for(const change of [f=>f.context.dirty=true,f=>f.context.selected='other',f=>f.fields['#platformFilter'].value='youtube',f=>f.fields['#search'].value='other',f=>f.context.filter='digest']){
    f=fixture();queue=f.context.captureSourceQueue('saved');change(f);await f.context.continueSourceQueue(queue);assert.equal(f.calls.length,0);
  }
  // Re-check after the list request, while the user can start another draft or switch.
  for(const change of [f=>f.context.dirty=true,f=>f.context.selected='other',f=>f.context.topicFilter='music']){
    f=fixture();queue=f.context.captureSourceQueue('saved');f.context.duringRefresh=()=>change(f);await f.context.continueSourceQueue(queue);assert.deepEqual(f.calls,['refresh']);
  }
  console.log('Source queue: original order, next/last/empty, complete filtered list, scroll preservation and draft/navigation protection passed');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
