const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const {JSDOM}=require(path.join(process.env.TEMP,'photo-design-test-tools/node_modules/jsdom'));
const root=path.join(__dirname,'..'),dom=new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),{url:'https://photos.example/',runScripts:'outside-only',pretendToBeVisual:true});
const w=dom.window,d=w.document,ctx=dom.getInternalVMContext(),evaluate=code=>vm.runInContext(code,ctx);
w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.ResizeObserver=class{observe(){}};
w.HTMLElement.prototype.scrollTo=()=>{};w.HTMLElement.prototype.setPointerCapture=()=>{};w.HTMLElement.prototype.getAnimations=()=>[];
w.HTMLElement.prototype.getBoundingClientRect=()=>({left:10,top:80,right:130,bottom:240,width:120,height:160});
const motions=[];w.HTMLElement.prototype.animate=function(frames,options){motions.push({element:this,frames,options});return {finished:Promise.resolve(),cancel(){}}};
w.HTMLMediaElement.prototype.pause=()=>{};w.HTMLMediaElement.prototype.load=()=>{};w.HTMLMediaElement.prototype.play=()=>Promise.resolve();
const scheduled=[],nativeTimeout=w.setTimeout.bind(w);w.setTimeout=(fn,ms,...args)=>{scheduled.push(ms);return nativeTimeout(fn,ms,...args);};
w.PHOTO_ACCOUNT={id:'own',name:'Admin',login:'admin',role:'admin',ready:true};
const items=[{id:0,key:'photo0',kind:'photo',state:'public',metadata:{}},{id:1,key:'photo1',kind:'photo',state:'public',metadata:{}}];
w.PHOTO_INITIAL_STATE={items,albums:[],vault:{configured:false,authenticated:false,ownerRegistered:true,protectionEnabled:true}};
let state={visible:true,excluded:[],available:true,enabled:false,total:2,done:0,failed:0,error:'',people:[]},calls=[];
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms||30)),clone=value=>JSON.parse(JSON.stringify(value));
w.PhotoAccount={api:async(url,body)=>{
  calls.push({url,body});
  if(url==='/api/people')return clone(state);
  if(url.startsWith('/api/people?id=')){
    const id=url.split('=')[1],person=state.people.find(p=>p.id===id);
    if(!person){const error=new Error('Человек не найден.');error.status=404;throw error;}
    return {...clone(person),faces:person.indices.map(index=>({id:'face'+index,index}))};
  }
  if(url==='/api/people/action'){
    await wait(40);
    if(body.action==='enabled')state.enabled=body.value;
    if(body.action==='visible'){state.visible=body.value;state.enabled=body.value;}
    if(body.action==='rename')state.people.find(p=>p.id===body.id).name=body.name;
    if(body.action==='profile'){const p=state.people.find(p=>p.id===body.id);p.name=body.name;p.cover=body.cover;}
    if(body.action==='preference')state.people.find(p=>p.id===body.id)[body.field]=body.value;
    if(body.action==='move'){
      const person=state.people.find(p=>p.indices.includes(Number(body.face.slice(4))));
      person.indices=person.indices.filter(i=>'face'+i!==body.face);
      state.people=state.people.filter(p=>p.indices.length);
    }
    if(body.action==='merge-many'){const target=state.people.find(p=>p.id===body.target);for(const id of body.sources){const source=state.people.find(p=>p.id===id);target.indices.push(...source.indices);state.people=state.people.filter(p=>p!==source);}target.name=body.name;}
    if(body.action==='merge'){
      const source=state.people.find(p=>p.id===body.id),target=state.people.find(p=>p.id===body.target);
      target.indices.push(...source.indices);state.people=state.people.filter(p=>p!==source);
    }
    return clone(state);
  }
  if(url==='/api/library')return w.PHOTO_INITIAL_STATE;
  if(url==='/api/storage')return {used:0,total:0,free:0,scope:'account'};
  throw new Error('Unexpected API '+url);
},status:()=>w.PHOTO_ACCOUNT};
w.fetch=async()=>({ok:true,json:async()=>({})});
for(const name of ['vault-client.js','app.js','sheet-gestures.js','avatar-crop.js','metadata.js','collections-ui.js','people-ui.js','album-ui.js'])vm.runInContext(fs.readFileSync(path.join(root,name),'utf8'),ctx);
w.PhotoVault.ready();const peopleStyle=d.createElement('style');peopleStyle.textContent=fs.readFileSync(path.join(root,'style.css'),'utf8');d.head.append(peopleStyle);
(async()=>{
  await wait();d.querySelector('#accountButton').click();await wait();const visible=d.querySelector('[data-people-visible]');assert(visible.checked);visible.checked=false;visible.dispatchEvent(new w.Event('change',{bubbles:true}));await wait(100);assert(d.querySelector('[data-section=people]').classList.contains('hidden'));visible.checked=true;visible.dispatchEvent(new w.Event('change',{bubbles:true}));await wait(100);assert(!d.querySelector('[data-section=people]').classList.contains('hidden'));d.querySelector('[data-account-action=close]').click();await wait();state.enabled=false;
  d.querySelector('#peopleOpen').click();await wait();
  assert(!d.querySelector('.people-modal').classList.contains('hidden'));
  assert.strictEqual(d.querySelector('.app').style.position,'fixed');assert.notStrictEqual(d.body.style.position,'fixed');
  d.querySelector('#peopleToggle').click();assert(d.querySelector('#peopleToggle').disabled);assert(!d.querySelector('.people-sheet .manage-pending').classList.contains('hidden'));await wait(100);
  assert(state.enabled);assert.strictEqual(d.querySelector('#peopleToggle').textContent,'Приостановить распознавание');
  state.done=2;state.people=[{id:'personA',name:'',cover:'face0',indices:[0]},{id:'personB',name:'Bob',cover:'face1',indices:[1]}];
  await w.PhotoPeople.refresh();assert(d.querySelector('.people-job').classList.contains('hidden'),'Completed progress must disappear');assert.strictEqual(d.querySelectorAll('#peopleCards .person-card').length,2);assert(d.querySelector('#peopleJob').textContent.includes('Все фотографии'));
  d.querySelector('.people-all [data-person=personA]').click();await wait(70);
  assert(d.querySelector('.people-modal').classList.contains('hidden'));assert.strictEqual(d.querySelector('#albumTitle').textContent,'Без имени');assert.strictEqual(d.querySelectorAll('#collectionGrid .tile').length,1);assert(!d.querySelector('#peopleEdit').classList.contains('hidden'));
  d.querySelector('#peopleEdit').click();assert(!d.querySelector('.people-context').classList.contains('hidden'));assert(d.querySelector('[data-person-action=pinned]'));assert(!d.querySelector('#personName'),'Long hold opens a compact menu, not an edit sheet');d.querySelector('[data-person-action=edit]').click();await wait();const form=d.querySelector('#personName');form.elements.name.value='<Каролина>';d.querySelector('[data-choose-cover]').click();assert(form.closest('.people-sheet').inert);assert.strictEqual(w.getComputedStyle(d.querySelector('.people-child-sheet')).position,'absolute');d.querySelector('[data-cover-face]').click();await wait();assert.strictEqual(d.querySelector('#personName'),form);assert.strictEqual(form.elements.name.value,'<Каролина>','Cover choice preserves the unsaved name');
  form.dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await wait(100);assert.strictEqual(d.querySelector('#albumTitle').textContent,'<Каролина>');
  assert(!d.querySelector('.people-sheet каролина'),'Names are text, never markup');
  d.querySelector('#peopleEdit').click();d.querySelector('[data-person-action=edit]').click();await wait();const parentEdit=d.querySelector('#personName');parentEdit.elements.name.value='Unsaved draft';d.querySelector('[data-check-faces]').click();assert(parentEdit.closest('.people-sheet').inert,'Parent form is retained behind the child');d.querySelector('[data-separate]').click();await wait(110);assert(d.querySelector('.people-modal').classList.contains('hidden'));assert.strictEqual(evaluate('screen'),'collections','Separating the final face leaves the empty person');
  state.people.push({id:'personC',name:'',cover:'face0',indices:[0]});await w.PhotoPeople.refresh();
  const card=d.querySelector('#peopleCards [data-person-id=personC]');
  await w.PhotoPeople.open();await wait();const listSearch=d.querySelector('#peopleListSearch');listSearch.value='bob';listSearch.dispatchEvent(new w.Event('input',{bubbles:true}));assert.strictEqual(d.querySelectorAll('.people-all [data-person]').length,1);assert(d.querySelector('.people-all [data-person=personB]'));listSearch.value='';listSearch.dispatchEvent(new w.Event('input',{bubbles:true}));d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));await wait();
  evaluate("show('searchScreen')");const globalSearch=d.querySelector('#searchInput');globalSearch.value='bOb';globalSearch.dispatchEvent(new w.Event('input',{bubbles:true}));assert(d.querySelector('.people-search-results [data-person=personB]'));assert(d.querySelector('#empty').classList.contains('hidden'));globalSearch.value='no-such-name';globalSearch.dispatchEvent(new w.Event('input',{bubbles:true}));assert(!d.querySelector('.people-search-results [data-person]'));assert(!d.querySelector('#empty').classList.contains('hidden'));state.hidden=[{id:'hiddenPerson',name:'Секретный',cover:'face0',indices:[0]}];state.excluded=[{id:'excludedPerson',name:'Секретный',cover:'face1',indices:[1]}];await w.PhotoPeople.refresh();globalSearch.value='Секретный';globalSearch.dispatchEvent(new w.Event('input',{bubbles:true}));assert(!d.querySelector('.people-search-results [data-person]'),'Hidden and excluded people stay out of global search');state.hidden=[];state.excluded=[];evaluate("show('collections')");
  const touch=(type,x)=>{const e=new w.Event(type,{bubbles:true,cancelable:true});Object.defineProperty(e,'touches',{value:type==='touchend'?[]:[{clientX:x,clientY:150}]});card.dispatchEvent(e);return e;};touch('touchstart',20);assert(!touch('touchmove',45).defaultPrevented,'Horizontal movement stays native');touch('touchend',45);await wait(520);assert(d.querySelector('.people-context').classList.contains('hidden'),'Scrolling cancels long hold');
  card.dispatchEvent(new w.MouseEvent('contextmenu',{bubbles:true,cancelable:true}));assert(!d.querySelector('.people-context').classList.contains('hidden'));d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowUp',bubbles:true,cancelable:true}));assert.strictEqual(d.activeElement.dataset.personAction,'pinned');d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true}));assert.strictEqual(d.activeElement.dataset.personAction,'favorite');d.querySelector('[data-person-action=favorite]').click();await wait(110);assert(state.people.find(p=>p.id==='personC').favorite);assert(d.querySelector('.people-context').classList.contains('hidden'));
  d.querySelector('#peopleCards [data-person-id=personC]').dispatchEvent(new w.MouseEvent('contextmenu',{bubbles:true,cancelable:true}));d.querySelector('[data-person-action=edit]').click();await wait();const editSheet=d.querySelector('.people-sheet:last-child');editSheet.querySelector('[data-pick-merge]').click();assert(!d.querySelector('select'),'Merge never uses the native name dropdown');
  const mergeSearch=d.querySelector('#peopleMergeSearch');mergeSearch.value='Bob';mergeSearch.dispatchEvent(new w.Event('input',{bubbles:true}));assert.strictEqual(d.querySelectorAll('[data-merge-target]').length,1);
  const merges=calls.filter(c=>c.body?.action==='merge-many').length;const candidate=d.querySelector('[data-merge-target=personB]'),candidateImg=candidate.querySelector('img');candidate.click();assert.strictEqual(d.querySelector('[data-merge-target=personB]'),candidate);assert.strictEqual(candidate.querySelector('img'),candidateImg,'Selecting people preserves image nodes');assert.strictEqual(d.querySelector('[data-merge-target=personB]').getAttribute('aria-pressed'),'true');assert.strictEqual(calls.filter(c=>c.body?.action==='merge-many').length,merges);d.querySelector('#peopleMergeNext').click();assert.strictEqual(d.querySelectorAll('.people-merge-pair img').length,2);assert(d.querySelector('.people-modal > .people-merge-dock:not(.hidden)'));assert(!d.querySelector('.people-merge-sheet .people-merge-dock'),'Floating button is outside the scrolling sheet');assert(d.querySelector('.people-merge-sheet'));assert.strictEqual(d.querySelectorAll('.people-modal > .people-merge-dock:not(.hidden)').length,1);
  d.querySelector('.people-merge-cancel').click();await wait();assert.strictEqual(d.querySelector('#peopleMergeSearch'),mergeSearch);assert.strictEqual(mergeSearch.value,'Bob');d.querySelector('#peopleMergeNext').click();d.querySelector('#peopleMergedName').value='Bob';d.querySelector('#personMergeConfirm').click();await wait(130);assert.strictEqual(calls.filter(c=>c.body?.action==='merge-many').length,merges+1);assert.strictEqual(evaluate('screen'),'collectionScreen');assert.strictEqual(evaluate('collectionName'),'person:personC');assert.strictEqual(d.querySelectorAll('#collectionGrid .tile').length,2);assert.strictEqual(items.length,2);
  await w.PhotoPeople.open();await wait();d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));await wait();assert(d.querySelector('.people-modal').classList.contains('hidden'));assert.strictEqual(d.querySelector('.app').style.position,'');
  assert(motions.some(m=>m.element.classList.contains('people-sheet')&&m.options.duration===480));assert(motions.some(m=>m.element.classList.contains('people-context-panel')&&m.options.duration===240));assert(motions.some(m=>m.element.classList.contains('people-sheet')&&m.options.duration===420));
  evaluate("show('collections')");
  // Closing while detail is loading must not reopen a dismissed page.
  await w.PhotoPeople.open();await wait();const originalAPI=w.PhotoAccount.api;let finishDetail;
  w.PhotoAccount.api=(url,body)=>url.startsWith('/api/people?id=')?new Promise(resolve=>{finishDetail=resolve;}):originalAPI(url,body);
  d.querySelector('.people-all [data-person=personC]').click();d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));await wait();finishDetail({id:'personC',name:'Bob',indices:[1],faces:[{id:'face1',index:1}]});await wait();
  assert(d.querySelector('.people-modal').classList.contains('hidden'));assert.strictEqual(evaluate('screen'),'collections');
  const refreshes=[];w.PhotoAccount.api=(url,body)=>url==='/api/people'?new Promise(resolve=>{refreshes.push(resolve);}):originalAPI(url,body);
  const pending=w.PhotoPeople.refresh(),before=scheduled.length;await w.PhotoPeople.open();await wait();refreshes.forEach(resolve=>resolve(clone(state)));await pending;assert(scheduled.slice(before).includes(4000),'Stale refresh must still schedule background polling');
  w.PhotoAccount.api=originalAPI;d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));await wait();
  const style=d.createElement('style');style.textContent=fs.readFileSync(path.join(root,'style.css'),'utf8');d.head.append(style);assert.strictEqual(w.getComputedStyle(d.querySelector('#peopleCards')).overflowX,'auto');assert.strictEqual(w.getComputedStyle(d.querySelector('#peopleCards .person-photo')).borderRadius,'20px');
  console.log('People UI: anchored action menu, native scrolling, name/cover editing, visual merge confirmation/cancel, unchanged photos, nested sheets and privacy preferences passed');
  dom.window.close();
})().catch(error=>{console.error(error);dom.window.close();process.exitCode=1;});
