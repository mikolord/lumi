(async () => {
  if('scrollRestoration' in history)history.scrollRestoration='manual';
  if('serviceWorker' in navigator&&window.isSecureContext)navigator.serviceWorker.register('./sw.js',{updateViaCache:'none'}).catch(()=>{});
  const scripts = ['vault-client.js', 'app.js', 'sheet-gestures.js', 'avatar-crop.js', 'metadata.js', 'context-menu.js', 'collections-ui.js', 'trash-album.js', 'upload-queue.js', 'manage.js', 'media-editor.js', 'people-ui.js','album-ui.js','timeline-ui.js','system-ui.js'];
  try {
    await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='account-client.js?v=95';script.onload=resolve;script.onerror=reject;document.body.append(script);});
    await window.PhotoAccount.start();
    const response = await fetch('/api/library', { cache: 'no-store' });
    if (!response.ok) throw new Error('Server unavailable');
    window.PHOTO_INITIAL_STATE = await response.json();
    for (const source of scripts) await new Promise((resolve, reject) => {
      const script = document.createElement('script'); script.src = `${source}?v=95`; script.onload = resolve; script.onerror = reject; document.body.append(script);
    });
    window.PhotoVault.ready();
    if('scrollRestoration' in history)history.scrollRestoration='manual';
    let userMoved=false;const cancel=()=>{userMoved=true;};for(const event of ['touchstart','wheel','pointerdown','keydown'])window.addEventListener(event,cancel,{once:true,passive:true});
    const toLatest=()=>{if(!userMoved)scrollToLatest();};
    const build='0.75.9';let updateNotice=null,checking=false;
    const notice=()=>{if(updateNotice)return;updateNotice=document.createElement('button');updateNotice.className='app-update-notice';updateNotice.textContent='Доступно обновление · Обновить';updateNotice.onclick=()=>{if(window.PhotoUploadQueue?.snapshot().saving){updateNotice.textContent='Дождись подготовки загрузки';return;}location.reload();};document.body.append(updateNotice);};
    const checkUpdate=async()=>{if(checking||document.hidden)return;checking=true;try{const response=await fetch('/VERSION',{cache:'no-store'});if(response.ok&&(await response.text()).trim()!==build)notice();const registration=await navigator.serviceWorker?.getRegistration();await registration?.update();}catch{}finally{checking=false;}};
    navigator.serviceWorker?.addEventListener('controllerchange',()=>{if(navigator.serviceWorker.controller)checkUpdate();});window.addEventListener('pageshow',checkUpdate);document.addEventListener('visibilitychange',()=>{if(!document.hidden)checkUpdate();});setInterval(checkUpdate,300000);

    toLatest();
    document.documentElement.classList.remove("account-loading");
    loadNearbyLibraryTiles();
    requestAnimationFrame(()=>requestAnimationFrame(toLatest));setTimeout(toLatest,180);setTimeout(toLatest,700);

  } catch {
    const message = document.createElement('div'); message.className = 'vault-startup-error';
    message.textContent = 'Не удалось подключиться к серверу. Проверь соединение и обнови страницу.';
    document.body.append(message);
  }
})();
