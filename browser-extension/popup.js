'use strict';
const domains={bilibili:['bilibili.com'],youtube:['youtube.com'],douyin:['douyin.com','iesdouyin.com'],x:['x.com','twitter.com'],heybox:['xiaoheihe.cn'],xiaohongshu:['xiaohongshu.com']};
function scopedCookie(c,allowed){
  const domain=c.domain.replace(/^\./,'').toLowerCase();
  if(!allowed.some(h=>domain===h||domain.endsWith('.'+h)))return null;
  return {name:c.name,value:c.value,domain:c.domain,path:c.path,expires:c.session?-1:c.expirationDate,
    httpOnly:c.httpOnly,secure:c.secure,sameSite:({no_restriction:'None',strict:'Strict',lax:'Lax',unspecified:'Lax'})[c.sameSite]||'Lax'};
}
function connection(value){
  const match=String(value).trim().match(/^cangye:(\d{1,5}):([A-Za-z0-9_-]{32})$/);
  if(!match||Number(match[1])<1||Number(match[1])>65535)throw Error('请复制网站给出的连接码');
  return {base:'http://127.0.0.1:'+Number(match[1]),token:match[2]};
}
document.querySelector('#connect').onclick=async()=>{
  const button=document.querySelector('#connect'),status=document.querySelector('#status');button.disabled=true;status.textContent='';
  try{
    const target=connection(document.querySelector('#connectionCode').value),platform=document.querySelector('#platform').value,allowed=domains[platform];
    if(!await chrome.permissions.request({origins:[...allowed.map(h=>'https://*.'+h+'/*'),'http://127.0.0.1/*']}))throw Error('没有授权读取所选平台，未导入');
    const byIdentity=new Map();
    for(const domain of allowed)for(const cookie of await chrome.cookies.getAll({domain})){
      if(cookie.partitionKey)continue;
      const value=scopedCookie(cookie,allowed);if(value)byIdentity.set([value.domain,value.path,value.name].join('|'),value);
    }
    const cookies=[...byIdentity.values()];if(!cookies.length)throw Error('这个Chrome还没有登录所选平台，请先登录');
    if(platform==='heybox'&&!cookies.some(c=>['pkey','user_pkey'].includes(c.name)&&c.value))throw Error('这个Chrome尚未登录小黑盒');
    if(platform==='x'&&!['auth_token','ct0'].every(name=>cookies.some(c=>c.name===name&&c.value)))throw Error('这个Chrome尚未登录X');
    const response=await fetch(target.base+'/api/accounts/browser-connect',{method:'POST',credentials:'omit',headers:{'Content-Type':'application/json','X-Local-Request':'1'},body:JSON.stringify({platform,token:target.token,state:{cookies,origins:[]}})});
    const result=await response.json();if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'连接失败，请回网站重新生成连接码');
    document.querySelector('#connectionCode').value='';status.textContent='成功：已沿用这个Chrome的账号。回网站点击导入收藏即可。';
  }catch(error){status.textContent=error.message||'连接失败，登录状态未改动';}
  finally{button.disabled=false;}
};
