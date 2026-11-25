const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const {JSDOM}=require(path.join(process.env.TEMP,'photo-design-test-tools/node_modules/jsdom'));
const root=path.join(__dirname,'..');
const dom=new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),{url:'https://photos.example/',runScripts:'outside-only',pretendToBeVisual:true});
const w=dom.window,d=w.document,ctx=dom.getInternalVMContext(),evaluate=code=>vm.runInContext(code,ctx);
w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.ResizeObserver=class{observe(){}};
w.HTMLElement.prototype.scrollTo=()=>{};w.HTMLElement.prototype.setPointerCapture=()=>{};w.HTMLElement.prototype.getAnimations=()=>[];
const motions=[];w.HTMLElement.prototype.animate=function(frames,options){motions.push({element:this,frames,options});return {finished:Promise.resolve(),cancel(){}}};
w.HTMLElement.prototype.getBoundingClientRect=()=>({left:10,top:80,right:130,bottom:240,width:120,height:160});
w.HTMLMediaElement.prototype.pause=()=>{};w.HTMLMediaElement.prototype.load=()=>{};w.HTMLMediaElement.prototype.play=()=>Promise.resolve();
w.PHOTO_ACCOUNT={id:'adminid',name:'Admin',login:'admin',role:'admin',ready:true};
w.localStorage.setItem('photo-collections-preferences-v1',JSON.stringify({name:'Another account'}));
const items=[{id:0,key:'own-photo',kind:'photo',state:'public',metadata:{name:'mine.jpg'}},{id:1,key:'shared-photo',kind:'photo',state:'shared',metadata:{name:'shared.jpg'},preview:'/media/shared/owner/album/0/preview',original:'/media/shared/owner/album/0/original'}];
const albums=[{id:'family',name:'Family',indices:[0]},{id:'shared:owner:album',name:'Other family',indices:[1],shared:true}];
let vaultFlags={ownerRegistered:true,configured:false,authenticated:false,passkey:false,protectionEnabled:true,concealHidden:false};const snapshot=()=>({items,albums,vault:{...vaultFlags}});
w.PHOTO_INITIAL_STATE=snapshot();const calls=[];let storageData={total:1024**3,used:500,free:1024**3-500,media_bytes:500,scope:'account'};
async function api(url,body){
 calls.push({url,body});
 if(url==='/api/account/sessions')return {sessions:[{id:'a',device:'iPhone',current:true,seen:1700000000},{id:'b',device:'TV',current:false,seen:1700000000}]};
 if(url==='/api/account/sessions/revoke')return {sessions:[]};
 if(url==='/api/tv/pair/inspect')return {device:'TV',code:'123456'};
 if(url==='/api/tv/pair/approve')return {ok:true};
 if(url==='/api/library')return snapshot();
 if(url.startsWith('/api/assets/upload-status'))return {complete:false};
 if(url==='/api/import/immich')return {};
 if(url==='/api/import/immich/start')return {state:'running',stage:'Подключение'};
 if(url==='/api/admin/users')return {users:[{id:'adminid',name:'Admin',login:'admin',role:'admin',quota:0,used:100},{id:'alice',name:'Alice',login:'alice',role:'user',quota:1024**3,used:500}]};
 if(url==='/api/admin/users/create'){await new Promise(resolve=>setTimeout(resolve,80));return {ok:true};}
 if(url==='/api/admin/users/update'||url==='/api/admin/users/delete')return {ok:true};
 if(url==='/api/albums/action')return snapshot();
 if(url==='/api/storage')return storageData;
 if(url==='/api/albums/people')return {users:[{id:'alice',name:'Alice',login:'alice'}],grants:[]};
 if(url==='/api/albums/share')return {ok:true};
 if(url==='/api/vault/lock')return snapshot().vault;
 if(url==='/api/vault/setup'){vaultFlags={...vaultFlags,protectionEnabled:true,configured:true,authenticated:true};return snapshot();}
 if(url==='/api/vault/preferences'){vaultFlags.concealHidden=body.concealHidden;return snapshot();}
 if(url==='/api/vault/disable'){assert.strictEqual(body.password,'admin password');vaultFlags={...vaultFlags,configured:false,passkey:false,authenticated:true,protectionEnabled:false};return snapshot();}
 throw new Error('Unexpected API '+url);
}
w.PhotoAccount={api,headers:async()=>({'X-Photo-CSRF':'signed-token','X-Photo-App-Origin':w.location.origin}),status:()=>w.PHOTO_ACCOUNT,refresh:async()=>w.PHOTO_ACCOUNT};
let uploadMode='quota',sent=[],coverUpload=false;
w.XMLHttpRequest=class{
 constructor(){this.upload={};this.headers={};}
 open(method,url){assert.strictEqual(method,'POST');assert.strictEqual(url,'/api/assets/upload');}
 setRequestHeader(name,value){this.headers[name]=value;}
 send(file){
  sent.push(file.name);assert.strictEqual(this.headers['X-Photo-CSRF'],'signed-token');
  setTimeout(()=>{
   if(this.aborted)return;
   this.upload.onprogress({loaded:file.size/2});
   assert(w.PhotoUploadQueue.snapshot().progress>=0);
   this.upload.onload();assert.strictEqual(w.PhotoUploadQueue.snapshot().phase,'Проверка и сохранение');
   this.status=uploadMode==='quota'?413:uploadMode==='one-bad'&&file.name==='1.jpg'?400:200;
   this.responseText=JSON.stringify(this.status===413?{error:'Достигнут лимит аккаунта.'}:this.status===400?{error:'Повреждён файл.'}:{id:1});this.onload();
  },1);
 }
 abort(){this.aborted=true;this.onabort?.();}
};
w.fetch=async(url,options={})=>{
 if(url==='/api/assets/upload')return coverUpload?{ok:true,json:async()=>({id:0})}:{ok:false,json:async()=>({error:'Достигнут лимит аккаунта.'})};
 if(!String(url).startsWith('/api/'))return {ok:true,blob:async()=>new w.Blob(['x'])};
 return {ok:true,json:async()=>api(url,options.body?JSON.parse(options.body):undefined)};
};
for(const name of ['vault-client.js','app.js','sheet-gestures.js','avatar-crop.js','metadata.js','context-menu.js','collections-ui.js','trash-album.js','upload-queue.js','manage.js'])vm.runInContext(fs.readFileSync(path.join(root,name),'utf8'),ctx);
w.PhotoVault.ready();const wait=()=>new Promise(resolve=>setTimeout(resolve,20));
function submit(form){form.dispatchEvent(new w.SubmitEvent('submit',{bubbles:true,cancelable:true,submitter:form.querySelector('button[type=submit]')}));}
(async()=>{
 assert.strictEqual(evaluate('getVisibleLibraryItems().join()'),'0');

 evaluate("openCollection('album:family')");const held=d.querySelector('#collectionGrid .tile');assert(held);held.dispatchEvent(new w.MouseEvent('contextmenu',{bubbles:true,cancelable:true}));const coverAction=d.querySelector('[data-action=album-cover]');assert(coverAction,'Album long press should offer a cover');coverAction.click();await wait();assert(calls.some(c=>c.url==='/api/albums/action'&&c.body.action==='cover'&&c.body.id==='family'&&c.body.index===0));evaluate("show('library')");
 evaluate("openCollection('Недавние')");d.querySelector('#collectionGrid .tile').dispatchEvent(new w.MouseEvent('contextmenu',{bubbles:true,cancelable:true}));assert(!d.querySelector('[data-action=album-cover]'),'Recent cover is automatic');d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await wait();evaluate("show('library')");
 assert.strictEqual(evaluate('getCollectionItems("album:shared:owner:album").join()'),'1');
 assert.strictEqual(w.PhotoVault.original(1),'/media/shared/owner/album/0/original');
 assert(d.querySelector('#accountButton').getAttribute('aria-label').includes('Admin'));
 assert(d.querySelector('.tabs #libraryUploadButton'),'Upload must be third dock button');assert(!d.querySelector('#libraryUploadButton').classList.contains('hidden'));const dockPress=new w.MouseEvent('pointerdown',{bubbles:true,cancelable:true,button:0});d.querySelector('#libraryUploadButton').dispatchEvent(dockPress);assert(dockPress.defaultPrevented,'Upload participates in the glass drag');const add=d.querySelector('#libraryUploadButton');add.getBoundingClientRect=()=>({left:210,top:700,right:275,bottom:754,width:65,height:54});add.dispatchEvent(new w.MouseEvent('pointerup',{bubbles:true,cancelable:true,button:0,clientX:240}));assert(d.querySelectorAll('.manage-sheet input[type=file]').length===1,'Only one photo picker');assert(d.querySelector('#uploadFiles'));d.querySelector('.manage-close').click();
 const card=d.querySelector('[data-server-album=family]');await w.PhotoVault.refresh();assert.strictEqual(card,d.querySelector('[data-server-album=family]'),'Polling must preserve album thumbnail nodes');
 await w.PhotoManage.open('devices');assert(d.querySelector('.device-row').textContent.includes('Это устройство'));assert.strictEqual(d.querySelectorAll('[data-revoke]').length,1);w.confirm=()=>true;d.querySelector('[data-revoke]').click();await wait();assert(calls.some(c=>c.url==='/api/account/sessions/revoke'&&c.body.id==='b'));d.querySelector('#pairCamera').click();await wait();const pairForm=d.querySelector('#pairManual');submit(pairForm);await wait();assert(d.querySelector('#pairStatus').textContent.includes('пустой'));pairForm.elements.qr.value='https://photos.example/';submit(pairForm);await wait();assert(d.querySelector('#pairStatus').textContent.includes('не код входа'));assert(!calls.some(c=>c.url==='/api/tv/pair/inspect'));pairForm.elements.qr.value='mira-photos://pair?server='+encodeURIComponent('http://192.168.1.3:8098')+'&id=test&secret=secret';submit(pairForm);await wait();assert(d.querySelector('.pair-confirm-code').textContent==='123456');assert(!calls.some(c=>c.url==='/api/tv/pair/approve'));d.querySelector('#pairApprove').click();await wait();assert(calls.some(c=>c.url==='/api/tv/pair/approve'&&c.body.code==='123456'));
 coverUpload=true;w.PhotoManage.uploadAlbumCover('album:family');const coverForm=d.querySelector('#albumCoverUpload');Object.defineProperty(coverForm.elements.file,'files',{value:[new w.File(['photo'],'cover.jpg',{type:'image/jpeg'})],configurable:true});submit(coverForm);await wait();assert(calls.some(c=>c.url==='/api/albums/action'&&c.body.action==='add'&&c.body.id==='family'));assert(calls.some(c=>c.url==='/api/albums/action'&&c.body.action==='cover'&&c.body.index===0));coverUpload=false;
 await w.PhotoManage.open('users');d.querySelector('#newUserButton').click();const form=d.querySelector('#createUser');
 form.elements.name.value='New user';form.elements.login.value='newuser';form.elements.password.value='new password';form.elements.gigabytes.value='2.5';submit(form);
 assert(form.querySelector('[type=submit]').disabled,'Creation must disable repeated submits immediately');
 assert(d.querySelector('.manage-pending').textContent.includes('Создаём'),'Creation must show visible waiting state');
 const press=new w.Event('pointerdown',{bubbles:true});form.querySelector('[type=submit]').dispatchEvent(press);
 assert(!form.querySelector('[type=submit]').classList.contains('water-pressed'),'Plain form buttons must not stretch');
 await new Promise(resolve=>setTimeout(resolve,120));
 assert.strictEqual(calls.find(call=>call.url==='/api/admin/users/create').body.quota,2.5*1024**3);
 d.querySelector('[data-edit-user=alice]').click();const edit=d.querySelector('.manage-sheet form');edit.elements.gigabytes.value='4';edit.elements.disabled.checked=true;submit(edit);await wait();
 const changed=calls.find(call=>call.url==='/api/admin/users/update').body;assert(changed.disabled);assert.strictEqual(changed.quota,4*1024**3);
 await w.PhotoManage.open('users');d.querySelector('[data-edit-user=alice]').click();assert(d.querySelector('[role=switch]').classList.contains('account-switch'));d.querySelector('#deleteUser').click();assert(!calls.some(c=>c.url==='/api/admin/users/delete'));d.querySelector('#deleteUserForm [name=confirmLogin]').value='alice';submit(d.querySelector('#deleteUserForm'));await wait();assert(calls.some(c=>c.url==='/api/admin/users/delete'&&c.body.confirmLogin==='alice'&&c.body.files==='keep'));
 w.PhotoManage.pickAlbum([0]);d.querySelector('[data-pick=family]').click();await wait();assert(calls.some(call=>call.url==='/api/albums/action'&&call.body.action==='add'&&call.body.indices[0]===0));
 evaluate('current=1;viewer.classList.remove("hidden");renderViewer()');assert(d.querySelector('#trash').disabled);assert(d.querySelector('#favorite').disabled);
 await assert.rejects(w.PhotoVault.mutate('trash',[1]),/только для просмотра/);
 await w.PhotoManage.open('upload');const input=d.querySelector('#uploadFiles');Object.defineProperty(input,'files',{value:[new w.File(['xx'],'file.jpg',{type:'image/jpeg'})]});input.onchange();assert.strictEqual(sent.length,0,'Picking must not start uploads behind the native Photos picker');await d.querySelector('#startUpload').onclick();await wait();assert(w.PhotoUploadQueue.snapshot().notice.includes('лимит'));await w.PhotoUploadQueue.discard();
 uploadMode='one-bad';sent=[];await w.PhotoManage.open('upload');const batch=d.querySelector('#uploadFiles');
 Object.defineProperty(batch,'files',{value:Array.from({length:70},(_,i)=>new w.File(['xx'],`${i}.jpg`,{type:'image/jpeg'}))});
 assert.strictEqual(batch.oninput,null,'Intermediate picker events must not start upload');batch.onchange();assert.strictEqual(sent.length,0);assert(!batch.disabled);await d.querySelector('#startUpload').onclick();
 d.querySelector('.manage-close').click();await wait();assert(d.querySelector('.manage-modal').classList.contains('hidden'),'Queue must not block sheet close');assert(!d.querySelector('.upload-mini').classList.contains('hidden'));
 await w.PhotoManage.open('users');
 for(let n=0;n<100&&w.PhotoUploadQueue.snapshot().running;n++)await wait();
 assert.strictEqual(sent.length,70,'Queue must continue while users screen is open');assert.strictEqual(w.PhotoUploadQueue.snapshot().done,69);assert.strictEqual(w.PhotoUploadQueue.snapshot().failed,1);
 await w.PhotoUploadQueue.discard();w.PhotoUploadQueue.dispose();
 await w.PhotoManage.open('password');assert(d.querySelector('.manage-sheet .manage-form-group'),'Password uses grouped fields');assert(d.querySelector('.manage-sheet form').elements.confirm);
 motions.length=0;await w.PhotoManage.open('immich');const presentations=motions.filter(item=>item.element.classList.contains('manage-sheet'));assert.strictEqual(presentations.length,1,'Immich data refresh must not interrupt its entrance');assert(parseFloat(presentations[0].frames[0].transform.match(/[\d.]+/)[0])>=w.innerHeight,'Immich enters from below the screen');const importForm=d.querySelector('#immichForm');importForm.elements.url.value='https://immich.example';importForm.elements.key.value='fixture';submit(importForm);await wait();assert.strictEqual(importForm.elements.key.value,'');assert(calls.some(call=>call.url==='/api/import/immich/start'&&call.body.albums===true));d.querySelector('.manage-close').click();
 items.push({id:2,key:'second-own',kind:'photo',state:'public',metadata:{name:'second.jpg'}});w.PhotoVault.apply({...snapshot(),collectionCovers:{'Недавние':0}});const recentCover=d.querySelector('#albums .album img');assert(recentCover.src.endsWith('/media/2/preview'));w.PhotoVault.apply({items,vault:snapshot().vault});assert(recentCover.src.endsWith('/media/2/preview'),'Recent cover follows the latest own item despite a stale manual cover');
 items.push({id:3,key:'new-video',kind:'video',state:'public',metadata:{name:'older-recording.mp4',takenAt:'2000-01-01'}});w.PhotoVault.apply(snapshot());assert(recentCover.src.endsWith('/media/3/preview'),'Latest upload can be an older recorded video');items[3].state='hidden';w.PhotoVault.apply(snapshot());assert(recentCover.src.endsWith('/media/2/preview'),'Hidden latest item must not remain the cover');
 d.querySelector('.manage-close').click();await wait();
 let pageY=460;Object.defineProperty(w,'scrollY',{configurable:true,get:()=>pageY});const restored=[];w.scrollTo=options=>{if(typeof options==='object'){pageY=options.top;restored.push(options.top);}};
 d.querySelector('#accountButton').click();await wait();
 const account=d.querySelector('.account-sheet'),passwordButton=account.querySelector('[data-account-action=manage-password]');
 account.scrollTop=340;const protection=account.querySelector('[data-account-action=vault-unlock]');protection.click();await wait();assert(!d.querySelector('.vault-auth').classList.contains('hidden'));account.scrollTop=0;d.querySelector('[data-vault=cancel]').click();await wait();assert.strictEqual(account.scrollTop,340,'PIN dismissal restores the parent settings scroll');assert.strictEqual(account.querySelector('[data-account-action=vault-unlock]'),protection,'Protection actions must preserve the settings DOM');
 Object.defineProperty(w,'isSecureContext',{configurable:true,value:true});w.PublicKeyCredential=class{};account.querySelector('[data-account-action=vault-passkey]').click();await wait();account.scrollTop=0;d.querySelector('[data-vault=cancel]').click();await wait();assert.strictEqual(account.scrollTop,340,'Face ID dismissal preserves the same settings position');
 for(const action of ['profile','theme']){account.scrollTop=350;motions.length=0;account.querySelector(`[data-account-action=${action}]`).click();await wait();const child=d.querySelector('.account-child-sheet');assert(child&&child!==account,'Nested settings get their own sheet');assert(account.hasAttribute('inert'));const entry=motions.find(item=>item.element===child);assert(parseFloat(entry.frames[0].transform.match(/[\d.]+/)[0])>=w.innerHeight);child.querySelector('[data-account-action=close]').click();await wait();assert(!child.isConnected);assert.strictEqual(account.scrollTop,350);assert(!account.hasAttribute('inert'));}

 assert(account.querySelector('[data-account-action=manage-protection-disable]'),'Protection can be disabled without first creating a PIN');
 assert(!account.querySelector('[data-account-action=order]'));assert(!account.querySelector('[data-account-action=manage-albums]'));assert(!account.querySelector('[data-account-action=manage-upload]'));
 assert.strictEqual(passwordButton.parentElement.previousElementSibling.textContent,'Аккаунт','Password belongs to Account');
 assert(account.querySelector('[data-account-action=vault-lock]').disabled,'Locked albums show a disabled explicit status');
 assert(account.textContent.includes('Личное хранилище'));assert(account.textContent.includes('Мои файлы'));
 assert.strictEqual(d.querySelector('.app').style.top,'-460px');passwordButton.click();await wait();
 assert(d.querySelector('.app').style.position==='fixed');assert.notStrictEqual(d.body.style.position,'fixed');d.querySelector('.manage-close').click();await wait();
 assert(!d.querySelector('.collections-modal').classList.contains('hidden'),'Closing password returns to account');
 assert.strictEqual(d.querySelector('.app').style.top,'-460px','Nested sheet must keep the same background position');
 account.querySelector('[data-account-action=close]').click();await wait();assert.strictEqual(pageY,460);assert.strictEqual(d.body.style.position,'');assert(restored.includes(460));
 storageData={total:null,free:null,used:500,available:5*1024**4,scope:'account',quota:0};
 w.PhotoVault.apply({items,vault:{configured:true,authenticated:true,ownerRegistered:true}});
 d.querySelector('#accountButton').click();await wait();assert(account.textContent.includes('Без лимита'));assert(account.textContent.includes('На сервере доступно'));assert(!account.querySelector('[role=progressbar]'),'Unlimited account must not pretend the whole disk is a personal quota');
 const lock=account.querySelector('[data-account-action=vault-lock]');assert(!lock.disabled);lock.click();await wait();assert(calls.some(call=>call.url==='/api/vault/lock'));assert(account.querySelector('[data-account-action=vault-lock]').disabled);
 account.querySelector('[data-account-action=close]').click();await wait();
 await w.PhotoManage.open('delete-account');assert(d.querySelector('[name=password]'),'Owner deletion requires password');assert(d.querySelector('[name=successor]'),'Last owner must choose a successor');
 assert(d.querySelector('[name=files][value=keep]').checked,'File retention is the default');
 d.querySelector('[name=files][value=delete]').click();assert(d.querySelector('#deleteFilesHint').textContent.includes('без возможности восстановления'));
 d.querySelector('.manage-close').click();await wait();
 d.querySelector('#accountButton').click();await wait();account.querySelector('[data-account-action=theme]').click();await wait();
 const themeSheet=d.querySelector('.account-child-sheet');themeSheet.querySelector('[data-theme-choice=dark]').click();assert.strictEqual(d.documentElement.dataset.theme,'dark');themeSheet.querySelector('[data-theme-choice=light]').click();assert.strictEqual(d.documentElement.dataset.theme,'light');evaluate('enterCinema()');assert.strictEqual(d.documentElement.dataset.theme,'dark');evaluate('exitCinema()');assert.strictEqual(d.documentElement.dataset.theme,'light');assert.strictEqual(JSON.parse(w.localStorage.getItem('photo-collections-preferences-v1:adminid')).theme,'light');themeSheet.querySelector('[data-account-action=close]').click();await wait();
 await w.PhotoManage.open('protection-disable');const disableForm=d.querySelector('.manage-sheet form');disableForm.elements.password.value='admin password';submit(disableForm);await wait();assert.strictEqual(w.PhotoVault.status().protectionEnabled,false);assert(!account.querySelector('[data-account-action=vault-lock]'));assert(account.textContent.includes('Выключена'));
 const conceal=account.querySelector('[data-conceal-hidden]');conceal.checked=true;conceal.dispatchEvent(new w.Event('change',{bubbles:true}));await wait();const hiddenFolder=d.querySelector('[data-collection="Скрытые"]');assert(hiddenFolder.classList.contains('hidden'));assert.strictEqual(w.PhotoVault.guard('Скрытые'),true,'A concealed folder cannot be opened through a stale button');
 account.querySelector('[data-account-action=reveal-hidden]').click();await wait();assert(!hiddenFolder.classList.contains('hidden'));assert(w.PhotoVault.hiddenVisible());
 account.querySelector('[data-account-action=close]').click();await wait();items[0].state='hidden';w.PhotoVault.apply(snapshot());evaluate('openCollection("Скрытые");current=0;viewer.classList.remove("hidden");renderViewer();syncVideo()');assert(!d.querySelector('#viewer').classList.contains('hidden'));
 Object.defineProperty(d,'hidden',{configurable:true,value:true});d.dispatchEvent(new w.Event('visibilitychange'));await wait();assert(hiddenFolder.classList.contains('hidden'));assert(!w.PhotoVault.hiddenVisible());assert(d.querySelector('#viewer').classList.contains('hidden'));assert(d.querySelector('#collectionScreen').classList.contains('hidden'));assert.strictEqual(w.PhotoVault.status().authenticated,true,'Disabled protection must not silently turn itself back on');
 Object.defineProperty(d,'hidden',{configurable:true,value:false});d.dispatchEvent(new w.Event('visibilitychange'));
 d.querySelector('#accountButton').click();await wait();account.querySelector('[data-account-action=vault-unlock]').click();await wait();assert(!d.querySelector('.vault-auth').classList.contains('hidden'),'Disabled protection can be configured again');const setup=d.querySelector('.vault-auth form');setup.elements.pin.value='12345678';setup.elements.confirm.value='12345678';submit(setup);await wait();assert(w.PhotoVault.status().protectionEnabled);assert(w.PhotoVault.status().configured);account.querySelector('[data-account-action=close]').click();await wait();
 const css=fs.readFileSync(path.join(root,'style.css'),'utf8');assert(css.includes('.manage-modal,.collections-modal,.vault-auth{bottom:0;height:auto}'));assert(!css.includes('margin-bottom:calc(-1 * env(safe-area-inset-bottom,0px))'),'Sheet bounds use the viewport without negative safe-area offsets');
 console.log('Multiuser UI: admin controls, GiB conversion, account-scoped profile, personal/shared albums, stable thumbnails, read-only sharing and upload quota errors passed');
 dom.window.close();
})().catch(error=>{console.error(error);dom.window.close();process.exitCode=1});
