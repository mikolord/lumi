(() => {
  if (new URLSearchParams(location.hash.slice(1)).has('setup')) history.replaceState(null, '', location.pathname + location.search);
  let status, root, busy = false, source = '', folder = '';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  let csrf='';
  function accountChanged(data){
    const expected=window.PHOTO_ACCOUNT?.id,actual=data.accountId||(data.authenticated?data.id:null);
    if(expected&&actual&&expected!==actual){document.querySelector('.app')?.replaceChildren();location.reload();throw new Error('Аккаунт изменён в другой вкладке.');}
  }
  async function api(path, body, retried=false) {
    const headers={'X-Photo-App-Origin':location.origin};
    if(body!==undefined){
      if(!csrf)await api('/api/account/status');
      headers['Content-Type']='application/json';headers['X-Photo-CSRF']=csrf;
    }
    const response=await fetch(path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body),cache:'no-store',credentials:'same-origin'});
    const data=await response.json();
    if(typeof data.csrf==='string')csrf=data.csrf;
    accountChanged(data);
    if(!response.ok){
      if(data.code==='csrf'&&!retried){const state=await api('/api/account/status');if(window.PHOTO_ACCOUNT?.id&&!state.authenticated){document.querySelector('.app')?.replaceChildren();location.reload();throw new Error('Войди в аккаунт.');}return api(path,body,true);}
      const failure=new Error(data.error||'Не удалось подключиться к серверу.');failure.status=response.status;throw failure;
    }
    return data;
  }
  const error = message => { root.querySelector('[role="alert"]').textContent = message; };
  function page(title, description, content) {
    root.innerHTML = `<section class="onboarding-card"><div class="onboarding-icon" aria-hidden="true">✳</div><p class="onboarding-brand">lumi</p><h1>${title}</h1><p class="onboarding-description">${description}</p>${content}<p class="onboarding-error" role="alert"></p></section>`;
  }
  function credentials() {
    const registering = !status.configured;
    if(registering && status.canSetup===false){page('Настройка сервера','Первого администратора создают из домашней сети — как в Rack Live.',`${status.setupUrl?`<a class="onboarding-local" href="${escape(status.setupUrl)}">Открыть локальную настройку</a>`:''}<p>Открой приложение по локальному IP-адресу сервера. После регистрации вход с любого разрешённого адреса будет обычным — по логину и паролю.</p>`);return;}
    page(registering?'Создать администратора':'С возвращением', registering?'Это первый запуск сервера. Создай администратора, затем подключи папку или начни с пустой медиатеки.':'Войди в свой аккаунт, чтобы открыть фотографии.',
      `<form id="ownerCredentials">${registering?'<label>Твоё имя<input name="name" autocomplete="name" maxlength="80" required></label>':''}<label>Логин<input name="login" autocomplete="username" minlength="3" maxlength="80" pattern="[a-zA-Z0-9_.@+\\-]+" required autocapitalize="none" spellcheck="false"></label><label>Пароль<input name="password" type="password" autocomplete="${registering?'new-password':'current-password'}" minlength="10" maxlength="256" required></label>${registering?'<label>Повтори пароль<input name="confirm" type="password" autocomplete="new-password" minlength="10" maxlength="256" required></label>':''}<button type="submit">${registering?'Создать аккаунт':'Войти'}</button></form>`);
    root.querySelector('form').onsubmit = async event => {
      event.preventDefault(); if (busy) return;
      const body = Object.fromEntries(new FormData(event.target));
      if (registering && body.password !== body.confirm) {error('Пароли не совпадают.');return;}
      busy = true; event.submitter.disabled = true; error('');
      try {status = await api(`/api/account/${registering?'register':'login'}`,body); await next();}
      catch (failure) {error(failure.message);}
      finally {busy = false; if(event.submitter.isConnected)event.submitter.disabled = false;}
    };
  }
  async function folders() {
    page('Выбери папку с фотографиями','Исходные файлы на Synology останутся на месте. В медиатеку добавятся отдельные копии фото и видео.', '<div id="folderBrowser" aria-live="polite">Получаем список папок…</div><button type="button" id="startEmpty">Начать с пустой медиатеки</button>');
    root.querySelector('#startEmpty').onclick=async()=>{try{status=await api('/api/account/finish',{});complete();}catch(failure){error(failure.message);}};
    const data = await api('/api/account/folders'+(source?`?source=${encodeURIComponent(source)}&path=${encodeURIComponent(folder)}`:''));
    const browser = root.querySelector('#folderBrowser');
    browser.innerHTML = source?`<button type="button" class="folder-back">‹ Назад</button><p class="folder-location">${escape(source+(folder?'/'+folder:''))}</p><div class="folder-list">${data.folders.map(name=>`<button type="button" data-folder="${escape(name)}"><span>▱ ${escape(name)}</span><span>›</span></button>`).join('')||'<p class="onboarding-note">Вложенных папок нет</p>'}</div><button type="button" id="connectFolder">Подключить эту папку</button><p class="onboarding-note">Будут добавлены также файлы из вложенных папок. Подключение большой библиотеки займёт время и место на диске.</p>`:
      `<div class="folder-list">${data.roots.map(item=>`<button type="button" data-source="${escape(item.id)}"><span>▱ ${escape(item.name)}</span><span>›</span></button>`).join('')||'<p>Нет доступных папок. Подключи папку Synology к серверу приложения.</p>'}</div>`;
    browser.onclick = async event => {
      if(busy)return;
      try {
        if(event.target.closest('[data-source]')) {source=event.target.closest('[data-source]').dataset.source;folder='';await folders();}
        else if(event.target.closest('[data-folder]')) {folder=[folder,event.target.closest('[data-folder]').dataset.folder].filter(Boolean).join('/');await folders();}
        else if(event.target.closest('.folder-back')) {if(folder)folder=folder.split('/').slice(0,-1).join('/');else source='';await folders();}
        else if(event.target.closest('#connectFolder')) {busy=true;event.target.disabled=true;await api('/api/account/folder',{source,path:folder});busy=false;await progress();}
      } catch(failure) {busy=false;error(failure.message);const button=root.querySelector('#connectFolder');if(button)button.disabled=false;}
    };
  }
  async function progress() {
    page('Подключаем фотографии','Можно закрыть приложение — сервер продолжит работу. После входа ты увидишь результат.', '<div id="importProgress" role="status"></div>');
    while(root.isConnected) {
      const job = await api('/api/account/import');
      const target=root.querySelector('#importProgress');
      target.innerHTML=`<p class="import-count">${job.done||0}${job.total===null?'':` / ${job.total||0}`}</p><p>Добавлено: ${job.added||0}${job.skipped?` · Пропущено: ${job.skipped}`:''}</p><p class="onboarding-note">${job.state==='running'?'Создаём миниатюры и читаем сведения о файлах.':job.state==='complete'?'Папка подключена.':escape(job.error||'Подключение прервано.')}</p>`;
      if(job.state==='complete') {
        target.insertAdjacentHTML('beforeend','<button type="button" id="finishOnboarding">Открыть медиатеку</button><p class="onboarding-note">Код защищённых альбомов и Face ID можно подключить в настройках аккаунта.</p>');
        root.querySelector('#finishOnboarding').onclick=async event=>{event.target.disabled=true;try{status=await api('/api/account/finish',{});complete();}catch(failure){error(failure.message);event.target.disabled=false;}};
        return;
      }
      if(job.state!=='running') {
        target.insertAdjacentHTML('beforeend','<button type="button" id="retryImport">Продолжить подключение</button>');
        root.querySelector('#retryImport').onclick=async()=>{const parts=status.folder.split('/');source=parts.shift();folder=parts.join('/');await api('/api/account/folder',{source,path:folder});await progress();}; return;
      }
      await new Promise(resolve=>setTimeout(resolve,1500));
    }
  }
  async function next() {
    if(!status.authenticated)credentials();
    else if(status.ready)complete();
    else if(status.job?.state)await progress();
    else await folders();
  }
  let done;
  function complete(){root.remove();window.PHOTO_ACCOUNT=status;done(status);}
  window.PhotoAccount={
    async start(){
      status=await api('/api/account/status');
      if(status.authenticated&&status.ready){window.PHOTO_ACCOUNT=status;return status;}
      root=document.createElement('main');root.className='onboarding';document.body.append(root);
      const result=new Promise(resolve=>{done=resolve;});await next();return result;
    },
    async logout(){await api('/api/account/logout',{});location.reload();},
    async rename(name){status=await api('/api/account/profile',{name});window.PHOTO_ACCOUNT=status;},
    status:()=>status,
    api,
    async headers(){if(!csrf||Number(csrf.split('.')[1])*1000<Date.now()+60000)await api('/api/account/status');return {'X-Photo-CSRF':csrf,'X-Photo-App-Origin':location.origin};},
    async refresh(){status=await api('/api/account/status');window.PHOTO_ACCOUNT=status;return status;},
    async checkSession(){if(!window.PHOTO_ACCOUNT)return;try{const data=await api('/api/account/status');if(!data.authenticated){document.querySelector('.app')?.replaceChildren();location.reload();}}catch{}},
  };
  setInterval(()=>window.PhotoAccount.checkSession(),60000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)window.PhotoAccount.checkSession();});
})();
