'use strict';
const domains={bilibili:['bilibili.com'],youtube:['youtube.com'],douyin:['douyin.com','iesdouyin.com'],x:['x.com','twitter.com'],heybox:['xiaoheihe.cn'],xiaohongshu:['xiaohongshu.com']};
function scopedCookie(c,allowed){
  const domain=c.domain.replace(/^\./,'').toLowerCase();
  if(!allowed.some(h=>domain===h||domain.endsWith('.'+h)))return null;
  return {name:c.name,value:c.value,domain:c.domain,path:c.path,expires:c.session?-1:c.expirationDate,
    httpOnly:c.httpOnly,secure:c.secure,sameSite:({no_restriction:'None',strict:'Strict',lax:'Lax',unspecified:'Lax'})[c.sameSite]||'Lax'};
}
document.querySelector('#export').onclick=async()=>{
  const button=document.querySelector('#export'),status=document.querySelector('#status');
  button.disabled=true;status.textContent='';
  try{
    const platform=document.querySelector('#platform').value,allowed=domains[platform];
    if(!await chrome.permissions.request({origins:allowed.map(h=>'https://*.'+h+'/*')}))throw Error('没有取得本平台权限，未读取登录。');
    const byIdentity=new Map();
    for(const domain of allowed)for(const c of await chrome.cookies.getAll({domain})){
      const value=scopedCookie(c,allowed);if(value)byIdentity.set([value.domain,value.path,value.name].join('|'),value);
    }
    const cookies=[...byIdentity.values()];if(!cookies.length)throw Error('没有取得本平台 Cookie；请先在当前 Chrome 登录。');
    if(platform==='heybox'&&!cookies.some(c=>['pkey','user_pkey'].includes(c.name)&&c.value))throw Error('当前 Chrome 尚未登录小黑盒，未导出访客状态。');
    if(platform==='x'&&!['auth_token','ct0'].every(name=>cookies.some(c=>c.name===name&&c.value)))throw Error('当前 Chrome 尚未完成 X 登录，未导出。');
    const blob=new Blob([JSON.stringify({platform,cookies,origins:[]})],{type:'application/json'}),url=URL.createObjectURL(blob);
    try{await chrome.downloads.download({url,filename:'cangye-'+platform+'-login.json',saveAs:true});}
    finally{setTimeout(()=>URL.revokeObjectURL(url),60000);}
    status.textContent='回到藏页 → 导入收藏 → 当前平台 → 导入 Chrome 登录快照。';
  }catch(error){status.textContent=error.message||'导出失败，未改动登录状态。';}
  finally{button.disabled=false;}
};
