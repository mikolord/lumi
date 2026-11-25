(()=>{
  if(window.__lumiNativeInstalled||!window.LumiNative)return;window.__lumiNativeInstalled=true;
  const awaiting=new Map();let sequence=0,busy=false;
  const rpc=(op,data={})=>new Promise((resolve,reject)=>{const id=String(++sequence),timer=setTimeout(()=>{awaiting.delete(id);reject(Error('Приложение долго не отвечает'))},120000);awaiting.set(id,{resolve,reject,timer});LumiNative.postMessage(JSON.stringify({op,id,...data}));});
  LumiNative.onmessage=e=>{try{const data=JSON.parse(e.data),call=awaiting.get(data.id);if(call){clearTimeout(call.timer);awaiting.delete(data.id);data.error?call.reject(Error(data.error)):call.resolve(data)}}catch{}};
  async function transfer(file,mode){
    const {token}=await rpc('export-begin',{name:file.name||'photo.jpg',mime:file.type||'application/octet-stream',size:file.size});
    try{for(let offset=0;offset<file.size;offset+=49152){const bytes=new Uint8Array(await file.slice(offset,offset+49152).arrayBuffer());await rpc('export-chunk',{token,offset,bytes:btoa(String.fromCharCode.apply(null,bytes))});}
    await rpc('export-finish',{token,mode});return token;}catch(error){await rpc('export-abort',{token}).catch(()=>{});throw error;}
  }
  navigator.canShare=data=>!data.files||data.files.length>0&&data.files.length<=100;
  navigator.share=async data=>{
    if(busy)throw Error('Дождись завершения подготовки файлов');busy=true;
    try{if(data.files?.length){if(data.files.length>100)throw Error('Выбери до 100 файлов за один раз');const tokens=[];for(const file of data.files)tokens.push(await transfer(file,'share'));await rpc('export-share',{tokens});}else await rpc('share-text',{title:data.title||'',text:data.text||'',url:data.url||''});}
    finally{busy=false;}
  };
  window.__lumiSaveUrl=async(url,name)=>{
    if(busy)return;busy=true;
    try{const response=await fetch(url,{credentials:'same-origin',redirect:'error'});if(!response.ok)throw Error('Не удалось скачать файл');const blob=await response.blob();await transfer(new File([blob],name||'photo.jpg',{type:blob.type}),'save');}catch(error){alert(error.message)}finally{busy=false;}
  };
  document.addEventListener('click',event=>{
    const a=event.target.closest?.('a[download]');if(!a)return;
    const url=new URL(a.href,location.href);if(url.protocol!=='blob:'&&url.origin!==location.origin)return;
    event.preventDefault();window.__lumiSaveUrl(a.href,a.download);
  },true);
  function patch(){
    if(!patch.ready&&window.PHOTO_ACCOUNT?.authenticated&&window.PhotoManage){patch.ready=true;rpc('ready').catch(()=>{});}
    if(window.PhotoManage&&!PhotoManage.__nativeUploads){const previous=PhotoManage.open;PhotoManage.open=function(type,...args){if(type==='upload'){rpc('queue').catch(()=>{});return;}return previous.call(this,type,...args)};PhotoManage.__nativeUploads=true;}
    const qr=document.querySelector('.manage-sheet[data-view="pair-scan"]');
    if(qr&&!qr.querySelector('[data-native-scan]')){
      const button=document.createElement('button');button.type='button';button.dataset.nativeScan='';button.textContent='Открыть камеру Android';button.onclick=()=>{qr.querySelector('#pairVideo')?.srcObject?.getTracks().forEach(t=>t.stop());rpc('scan-tv').catch(()=>{})};
      qr.querySelector('#pairStatus')?.after(button);
    }
    const storage=document.querySelector('.account-storage');
    if(storage&&!document.querySelector('[data-lumi-native-settings]')){
      const group=document.createElement('div');group.className='account-settings-group';
      const button=document.createElement('button');button.type='button';button.className='account-settings-row';button.dataset.lumiNativeSettings='';
      button.innerHTML='<span>Приложение Android</span><span>›</span>';button.onclick=()=>rpc('settings').catch(()=>{});group.append(button);storage.after(group);
    }
    const light=document.documentElement.dataset.theme==='light'||document.body.dataset.theme==='light'||getComputedStyle(document.body).backgroundColor==='rgb(255, 255, 255)';
    if(patch.light!==light){patch.light=light;rpc('theme',{light}).catch(()=>{})}
    let secure=false;try{secure=typeof collectionName!=='undefined'&&['Скрытые','Недавно удалённые'].includes(collectionName);if(typeof current!=='undefined'&&document.querySelector('#viewer:not(.hidden)'))secure=secure||['hidden','trash','locked'].includes(window.PhotoVault?.state(current));}catch{}
    if(patch.secure!==secure){patch.secure=secure;rpc('secure',{value:secure}).catch(()=>{})}
  }
  let scheduled=false;new MutationObserver(()=>{if(scheduled)return;scheduled=true;requestAnimationFrame(()=>{scheduled=false;patch()})}).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['data-theme','class']});
  patch();setInterval(patch,3000);
})();
