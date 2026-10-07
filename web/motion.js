'use strict';
const demoMaterials=[
  {title:'把信息留给以后的自己',paragraphs:['收藏是一种延迟的阅读。把文章、图片和视频留下来，是因为它们可能会在以后的某个时刻派上用场。','一条材料可以先读完，留下几句话，然后放入稍后整理。理解不必一次完成，原文和来源始终保留。'],later:false},
  {title:'读完之后，留下自己的判断',paragraphs:['读过一条材料之后，可以写下哪一点改变了自己的想法，以及它可能用在哪一个真实的问题上。','这个示例只展示材料切换和操作反馈。选定排版之后，正式界面使用你保存的真实材料。'],later:false}
];
let demoSelected=0;
const reader=document.querySelector('#motionReader'), drawer=document.querySelector('#demoDrawer');
function drawerState(open){
  drawer.classList.toggle('open',open);drawer.inert=!open;drawer.setAttribute('aria-hidden',String(!open));
  if(open)document.querySelector('#closeDemoNotes').focus();else document.querySelector('#openDemoNotes').focus();
}
function renderDemo(){
  const item=demoMaterials[demoSelected];
  document.querySelector('#demoTitle').textContent=item.title;
  const body=document.querySelector('#demoBody');body.replaceChildren(...item.paragraphs.map(text=>{const p=document.createElement('p');p.textContent=text;return p;}));
  document.querySelector('#demoState').textContent=item.later?'已读 · 稍后整理':'待处理';
  document.querySelector('#demoLater').textContent=item.later?'放回待处理':'已读，稍后整理';
  document.querySelectorAll('[data-material]').forEach(button=>{const selected=Number(button.dataset.material)===demoSelected;button.classList.toggle('active',selected);button.setAttribute('aria-pressed',String(selected));button.querySelector('.material-state').textContent=demoMaterials[Number(button.dataset.material)].later?'稍后整理':'待处理';});
  reader.classList.remove('entering');requestAnimationFrame(()=>requestAnimationFrame(()=>reader.classList.add('entering')));
}
document.querySelectorAll('[data-material]').forEach(button=>button.onclick=()=>{demoSelected=Number(button.dataset.material);renderDemo();});
document.querySelector('#openDemoNotes').onclick=()=>drawerState(true);
document.querySelector('#closeDemoNotes').onclick=()=>drawerState(false);
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&drawer.classList.contains('open'))drawerState(false);});
document.querySelector('#demoLater').onclick=()=>{demoMaterials[demoSelected].later=!demoMaterials[demoSelected].later;renderDemo();document.querySelector('#demoState').classList.remove('feedback');requestAnimationFrame(()=>document.querySelector('#demoState').classList.add('feedback'));document.querySelector('#motionNotice').textContent='示例已更新分类；你的实际收藏未改变。';};
