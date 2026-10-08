const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const code=fs.readFileSync('browser-extension/popup.js','utf8');
function setup({platform='x',connection='cangye:8766:'+('t'.repeat(32)),grant=true,response={ok:true,json:async()=>({})}}={}){
  const elements={'#connect':{},'#status':{},'#platform':{value:platform},'#connectionCode':{value:connection}};
  const permissions=[],reads=[],writes=[];
  const cookies=[{domain:'.x.com',name:'auth_token',value:'synthetic-auth',path:'/',session:true,secure:true,httpOnly:true,sameSite:'lax'},
    {domain:'.x.com',name:'ct0',value:'synthetic-csrf',path:'/',session:true},
    {domain:'.unrelated.test',name:'secret',value:'must-stay-out',path:'/',session:true},
    {domain:'.x.com',name:'partitioned',value:'must-stay-out',path:'/',session:true,partitionKey:{topLevelSite:'https://unrelated.test'}}];
  const context={document:{querySelector:s=>elements[s]},chrome:{permissions:{request:async p=>{permissions.push(p);return grant;}},cookies:{getAll:async p=>{reads.push(p);return cookies;}}},fetch:async(url,options)=>{writes.push({url,options});return response;}};
  vm.runInNewContext(code,context);return {elements,permissions,reads,writes,run:()=>elements['#connect'].onclick()};
}
(async()=>{
  const valid=setup();await valid.run();assert.equal(valid.writes.length,1);assert.equal(valid.writes[0].url,'http://127.0.0.1:8766/api/accounts/browser-connect');
  assert.equal(valid.writes[0].options.credentials,'omit');const body=JSON.parse(valid.writes[0].options.body);
  assert.equal(body.platform,'x');assert.deepEqual(body.state.cookies.map(c=>c.name).sort(),['auth_token','ct0']);
  assert(!JSON.stringify(body).includes('must-stay-out'));assert.equal(valid.elements['#connectionCode'].value,'');assert.match(valid.elements['#status'].textContent,/成功/);
  assert.deepEqual(Array.from(valid.permissions[0].origins).sort(),['http://127.0.0.1/*','https://*.twitter.com/*','https://*.x.com/*'].sort());
  const denied=setup({grant:false});await denied.run();assert.equal(denied.reads.length,0);assert.equal(denied.writes.length,0);assert.match(denied.elements['#status'].textContent,/未导入/);assert.equal(denied.elements['#connect'].disabled,false);
  for(const connection of ['https://outside.test','cangye:0:'+('t'.repeat(32)),'cangye:8766:'+('t'.repeat(32))+'/outside']){
    const bad=setup({connection});await bad.run();assert.equal(bad.permissions.length,0);assert.equal(bad.writes.length,0);
  }
  const expired=setup({response:{ok:false,json:async()=>({detail:'连接码已过期'})}});await expired.run();assert.match(expired.elements['#status'].textContent,/过期/);assert.notEqual(expired.elements['#connectionCode'].value,'');
  console.log('Chrome popup: scoped snapshot, one loopback POST, permissions denied, malformed code and server failure passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
