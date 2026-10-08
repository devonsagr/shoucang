const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Node{
  constructor(){this.dataset={};this.events={};this.attrs={};this.classes=new Set();this.classList={add:n=>this.classes.add(n),remove:n=>this.classes.delete(n),contains:n=>this.classes.has(n),toggle:n=>{if(this.classes.has(n)){this.classes.delete(n);return false;}this.classes.add(n);return true;}};this.isConnected=true;}
  setAttribute(k,v){this.attrs[k]=v;}removeAttribute(k){delete this.attrs[k];if(k==='src')delete this.src;}
  addEventListener(k,fn){this.events[k]=fn;}focus(){this.focused=true;}
  dispatch(k,event={}){this.events[k]?.(event);}
}
let dialog;
const clicks={},document={addEventListener:(k,fn)=>clicks[k]=fn,body:{append:()=>{}},createElement:()=>{
  dialog=new Node();dialog.children={img:new Node(),'[role="status"]':new Node(),'.image-viewer-canvas':new Node()};
  for(const key of ['previous','next','zoom','close'])dialog.children['[data-viewer="'+key+'"]']=new Node();
  dialog.querySelector=s=>dialog.children[s];dialog.showModal=()=>dialog.open=true;dialog.close=()=>{dialog.open=false;dialog.dispatch('close');};return dialog;
}};
const context={document,window:{}};vm.runInNewContext(fs.readFileSync('web/media.js','utf8'),context);
const group={querySelectorAll:()=>buttons};const makeButton=(src,alt)=>{const n=new Node();n.dataset.imageSrc=src;n.querySelector=()=>({alt});n.closest=s=>s==='.media-group'?group:n;return n;};
const buttons=[makeButton('/api/materials/fixture/images/a.png','原图一'),makeButton('/api/materials/fixture/images/b.png','原图二')];
let prevented=false;clicks.click({target:buttons[0],preventDefault:()=>prevented=true});
assert(prevented&&dialog.open);assert.equal(dialog.children.img.src,buttons[0].dataset.imageSrc);assert.equal(dialog.children['[role="status"]'].textContent,'图片 1 / 2');
assert(dialog.children['[data-viewer="previous"]'].disabled);assert(!dialog.children['[data-viewer="next"]'].disabled);
const event=key=>({key,preventDefault(){},stopPropagation(){}});dialog.dispatch('keydown',event('ArrowRight'));assert.equal(dialog.children.img.src,buttons[1].dataset.imageSrc);
dialog.dispatch('click',{target:{closest:()=>({dataset:{viewer:'zoom'}})}});assert(dialog.classList.contains('original-size'));assert.equal(dialog.children['[data-viewer="zoom"]'].textContent,'适合窗口');
dialog.dispatch('keydown',event('Escape'));assert(!dialog.open);assert(!dialog.children.img.src);assert(buttons[0].focused);
clicks.click({target:buttons[1],preventDefault(){}});assert(dialog.open&&!dialog.classList.contains('original-size'));context.window.MediaViewer.close();assert(!dialog.open&&buttons[1].focused);
const outside=makeButton('https://outside.test/image.png','不应打开');clicks.click({target:outside,preventDefault(){throw Error('不应打开远程图片');}});assert(!dialog.open);
console.log('Image viewer: local full image, group navigation, original size, Escape, cleanup and focus restoration passed');
