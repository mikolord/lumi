const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const {JSDOM}=require(path.join(process.env.TEMP,'photo-design-test-tools/node_modules/jsdom'));
const root=path.join(__dirname,'..');
function fixture(role){
 const dom=new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),{url:'https://photos.example/',runScripts:'outside-only',pretendToBeVisual:true}),w=dom.window;
 w.PHOTO_ACCOUNT={role};w.matchMedia=()=>({matches:false});w.scrollTo=()=>{};w.HTMLElement.prototype.getAnimations=()=>[];w.HTMLElement.prototype.animate=()=>({finished:Promise.resolve(),cancel(){}});
 vm.runInContext(fs.readFileSync(path.join(root,'sheet-gestures.js'),'utf8'),dom.getInternalVMContext());return dom;
}
const wait=()=>new Promise(resolve=>setTimeout(resolve,30));
(async()=>{
 const regular=fixture('user');vm.runInContext(fs.readFileSync(path.join(root,'system-ui.js'),'utf8'),regular.getInternalVMContext());assert(!regular.window.PhotoSystem);assert(!regular.window.document.querySelector('.system-modal'));regular.window.close();
 const dom=fixture('admin'),w=dom.window,d=w.document,calls=[];
 let info={current:'0.67.0',latest:'0.68.0',newer:true,phase:'idle',canInstall:true,canRollback:false};
 w.PhotoAccount={api:async(url,body)=>{
  calls.push({url,body});
  if(url==='/api/admin/metrics')return {cpu:5.5,memory:100*1024**2,cores:4,components:[{name:'Медиатека',cpu:10,memory:40*1024**2,scope:'container'},{name:'Распознавание людей',cpu:12,memory:60*1024**2,scope:'container'}]};
  if(url==='/api/admin/updates/action'){
   if(body.action==='download')info={...info,phase:'ready',downloaded:'v0.68.0'};
   if(body.action==='install')info={...info,current:'0.68.0',newer:false,phase:'idle',canRollback:true};
  }
  return {...info};
 }};
 let parentEscapes=0;d.addEventListener('keydown',e=>{if(e.key==='Escape'){parentEscapes++;e.stopImmediatePropagation();}},true);
 vm.runInContext(fs.readFileSync(path.join(root,'system-ui.js'),'utf8'),dom.getInternalVMContext());
 w.PhotoSystem.open('metrics');await wait();assert.strictEqual(d.querySelector('#systemCpu').textContent,'5,5%');assert(d.querySelector('#systemMemory').textContent.includes('100'));assert.strictEqual(d.querySelectorAll('.system-component').length,2);
 d.querySelector('.system-sheet .manage-close').click();await wait();assert.strictEqual(d.querySelector('.app').style.position,'');
 w.PhotoSystem.open('updates');await wait();d.querySelector('#checkUpdates').click();await wait();d.querySelector('#downloadUpdate').click();await wait();assert(!d.querySelector('#installUpdate').classList.contains('hidden'));d.querySelector('#installUpdate').click();await wait();assert(!d.querySelector('#reloadUpdated').classList.contains('hidden'));assert(calls.some(c=>c.body?.action==='install'));
 d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));await wait();assert(d.querySelector('.system-modal').classList.contains('hidden'));assert.strictEqual(parentEscapes,0,'Only the top sheet handles Escape; parent profile stays open');
 console.log('Admin system UI: hidden for ordinary users, CPU/RAM components, update check/download/install, reload and accepted sheet cleanup passed');dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1;});
