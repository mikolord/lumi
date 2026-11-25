const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert');
const { JSDOM } = require(path.join(process.env.TEMP, 'photo-design-test-tools/node_modules/jsdom'));
const root = path.join(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'), { url:'https://foto.mira5.netcraze.club/', runScripts:'outside-only', pretendToBeVisual:true });
const w=dom.window, doc=w.document, context=dom.getInternalVMContext();
w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.ResizeObserver=class{observe(){}};
w.HTMLElement.prototype.scrollTo=()=>{};w.HTMLElement.prototype.setPointerCapture=()=>{};w.HTMLElement.prototype.getAnimations=()=>[];
w.HTMLElement.prototype.animate=()=>({finished:Promise.resolve(),cancel(){}});
w.HTMLElement.prototype.getBoundingClientRect=()=>({left:10,top:80,right:130,bottom:240,width:120,height:160});
w.HTMLMediaElement.prototype.pause=()=>{};w.HTMLMediaElement.prototype.load=()=>{};w.HTMLMediaElement.prototype.play=()=>Promise.resolve();
const source=fs.readFileSync(path.join(root,'app.js'),'utf8');
const keys=JSON.parse('['+source.match(/const baseIds=\[([^\]]+)\]/)[1].replace(/'/g,'"')+']');
const records=keys.map((key,id)=>({id,key,kind:typeof key==='string'?'video':'photo',state:id===0?'hidden':id===1?'trash':'public',deletedAt:id===1?Date.now()-89*86400000:null,metadata:{name:`${key}.jpg`,width:480,height:600,bytes:1234,format:'JPEG'}}));
let unlocked=false;
const snapshot=()=>({items:records.map(item=>unlocked||item.state==='public'?{...item}:{id:item.id,key:item.key,kind:item.kind,state:'locked'}),vault:{configured:true,authenticated:unlocked,passkey:false}});
w.PHOTO_ACCOUNT={name:'Владелец',login:'owner',ready:true,folder:'photo'};
w.PHOTO_INITIAL_STATE=snapshot();
const actions=[];
w.fetch=async (url,options={})=>{
  let data,status=200;
  if(url==='/api/vault/unlock') { if(JSON.parse(options.body).pin==='48271639'){unlocked=true;data=snapshot()}else{status=401;data={error:'Неверный код-пароль.'}} }
  else if(url==='/api/vault/lock'){unlocked=false;data=snapshot().vault}
  else if(url==='/api/vault/status')data=snapshot().vault;
  else if(url==='/api/assets/action'){
    const request=JSON.parse(options.body);actions.push(request);
    if(!unlocked){status=401;data={error:'Нужен вход'}}else{
      for(const index of request.indices){records[index].state=request.action==='restore'?'public':request.action==='purge'?'purged':request.action==='trash'?'trash':request.action==='hide'?'hidden':'public';if(request.action==='trash')records[index].deletedAt=Date.now()}
      data=snapshot();
    }
  }else if(url==='/api/storage')data={total:1e12,used:5e11,free:5e11,media_bytes:1234};
  else return {ok:true,blob:async()=>new w.Blob(['test'])};
  return {ok:status<400,status,json:async()=>data};
};
for(const name of ['vault-client.js','app.js','sheet-gestures.js','avatar-crop.js','metadata.js','context-menu.js','collections-ui.js','trash-album.js'])vm.runInContext(fs.readFileSync(path.join(root,name),'utf8'),context);
w.PhotoVault.ready();
const evaluate=code=>vm.runInContext(code,context), wait=()=>new Promise(r=>setTimeout(r,20));
const event=(target,type)=>target.dispatchEvent(new w.Event(type,{bubbles:true,cancelable:true}));
async function unlock(){doc.querySelector('#vaultEnterAlbum').click();await wait();doc.querySelector('.vault-auth [name=pin]').value='48271639';event(doc.querySelector('.vault-auth form'),'submit');await wait();}
(async()=>{
  assert.equal(doc.querySelectorAll('#albums .album').length,2);
  assert(!doc.querySelector('#count').textContent.includes('демонстрация'));
  assert(doc.querySelector('.video-badge').textContent.includes('Видео'));
  assert(!evaluate('getVisibleLibraryItems().includes(0)'));
  assert(doc.querySelector('#grid [data-index="0"] img').src.startsWith('data:'));
  doc.querySelector('#collectionTab').click();doc.querySelector('[data-collection="Скрытые"]').click();await wait();
  assert(!doc.querySelector('.vault-gate').classList.contains('hidden'));assert.equal(doc.querySelector('#collectionGrid').children.length,0);
  doc.querySelector('#vaultEnterAlbum').click();await wait();doc.querySelector('.vault-auth [name=pin]').value='000000';event(doc.querySelector('.vault-auth form'),'submit');await wait();
  assert(doc.querySelector('.vault-error').textContent.includes('Неверный'));
  doc.querySelector('.vault-auth [name=pin]').value='48271639';event(doc.querySelector('.vault-auth form'),'submit');await wait();
  assert(w.PhotoVault.status().authenticated);assert.equal(doc.querySelector('#collectionGrid').children.length,1);
  assert(doc.querySelector('#collectionGrid img').src.endsWith('/media/0/preview'));
  await evaluate('closeAlbum()');await wait();assert(!w.PhotoVault.status().authenticated);
  assert(doc.querySelector('#grid [data-index="0"] img').src.startsWith('data:'));
  doc.querySelector('[data-collection="Недавно удалённые"]').click();await wait();await unlock();
  assert(doc.querySelector('.trash-deadline.urgent').textContent.includes('1 день'));
  doc.querySelector('#trashAlbumMore').click();doc.querySelector('[data-trash-action="restore"]').click();await wait();
  assert.deepEqual(actions.at(-1),{action:'restore',indices:[1]});assert(evaluate('getVisibleLibraryItems().includes(1)'));
  await w.PhotoVault.mutate('trash',[2]);evaluate('openCollection("Недавно удалённые")');
  doc.querySelector('#trashAlbumMore').click();doc.querySelector('[data-trash-action="delete"]').click();
  assert(!actions.some(item=>item.action==='purge'),'permanent removal requires confirmation');
  doc.querySelector('[data-trash-confirm="delete"]').click();await wait();
  assert.equal(records[2].state,'purged');assert(w.PhotoTrash.isGone(2));
  await w.PhotoVault.lock();assert(!w.PhotoVault.status().authenticated);assert(doc.querySelector('.vault-gate:not(.hidden)'));
  assert.equal(evaluate('document.querySelector("meta[name=theme-color]").content'),'#161719');
  console.log('Server-mode UI: locked previews, wrong code, unlock, auto-lock, 90-day badges, server restore and confirmed purge passed');
  dom.window.close();
})().catch(error=>{console.error(error);dom.window.close();process.exitCode=1});
