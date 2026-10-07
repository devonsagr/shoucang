const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const python=fs.readFileSync('app/platform_browser.py','utf8');
const code=python.split("challenge=page.evaluate('''")[1].split("''')")[0];
function check({x=30,opacity='1',visibility='visible'}={}){
  const parent={style:{display:'block',opacity,visibility},parentElement:null};
  const frame={tagName:'IFRAME',parentElement:parent,style:{display:'block',opacity:'1',visibility:'visible'},getBoundingClientRect:()=>({left:x,right:x+300,top:x,bottom:x+300,width:300,height:300})};
  const context={innerWidth:1000,innerHeight:700,document:{querySelectorAll:()=>[frame]},getComputedStyle:n=>n.style};
  vm.createContext(context);return vm.runInContext('('+code+')()',context);
}
assert.equal(check(),true,'a real visible CAPTCHA must stop capture');
assert.equal(check({opacity:'0'}),false,'an initialized but hidden CAPTCHA is not a blocking challenge');
assert.equal(check({x:-9999}),false,'the inactive offscreen frame must not reject a valid article');
assert.equal(check({visibility:'hidden'}),false);
console.log('Heybox verification: visible challenges stop; hidden and offscreen widgets do not reject source content');
