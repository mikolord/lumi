(() => {
  let catalogue = window.PHOTO_INITIAL_STATE.items, status = window.PHOTO_INITIAL_STATE.vault, collectionCovers = window.PHOTO_INITIAL_STATE.collectionCovers || {},lastLibrarySnapshot=JSON.stringify(window.PHOTO_INITIAL_STATE);
  let setupToken = new URLSearchParams(location.hash.slice(1)).get('setup');
  if (setupToken) history.replaceState(null, '', location.pathname + location.search);
  let pendingAuth = null, authBusy = false, authClosing = false, returningAlbum = null, authGestures = null;
  const isPrivate = name => ['Скрытые', 'Недавно удалённые'].includes(name);
  let hiddenRevealed=false;
  const pendingInfo=new Map(),infoAttempts=new Map();
  const blank = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/%3E';
  const modal = document.createElement('div'); modal.className = 'vault-auth hidden';
  modal.innerHTML = '<div class="vault-auth-shade"></div><section class="vault-auth-sheet" role="dialog" aria-modal="true" tabindex="-1"></section>';
  document.body.append(modal);
  const authSheet = modal.querySelector('section');
  const gate = document.createElement('div'); gate.className = 'vault-gate hidden';
  gate.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10V7a5 5 0 0 1 10 0v3M5 10h14v11H5z"/></svg><h3>Этот альбом защищён</h3><p>Используй ключ доступа или введи код-пароль.</p><button id="vaultEnterAlbum">Перейти к альбому</button>';
  document.querySelector('#collectionScreen').append(gate);
  async function api(path, body) {
    if(window.PhotoAccount?.api)return window.PhotoAccount.api(path,body);
    const response = await fetch(path, { method: body === undefined ? 'GET' : 'POST', headers: body === undefined ? {} : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store', credentials: 'same-origin' });
    const data = await response.json();
    if (!response.ok) { const error = new Error(data.error || 'Не удалось выполнить запрос.'); error.status = response.status; throw error; }
    return data;
  }
  function apply(data) {
    lastLibrarySnapshot=JSON.stringify(data);
    const reconcile = status.authenticated && screen === 'collectionScreen' && isPrivate(collectionName) && gate.classList.contains('hidden') && viewer.classList.contains('hidden');
    const priorRevision=catalogue[current]?.revision;
    catalogue = data.items; status = data.vault;
    if(data.collectionCovers!==undefined)collectionCovers=data.collectionCovers;
    if(data.albums)window.PhotoManage?.updateAlbums(data.albums);
    if(window.PHOTO_ACCOUNT?.id){favorites.clear();catalogue.forEach(item=>{if(item.favorite)favorites.add(item.id)});}
    deleted.clear(); hiddenItems.clear();
    catalogue.forEach(item => { if (item.state === 'trash') deleted.add(item.id); else if (item.state === 'hidden' || item.state === 'locked') hiddenItems.add(item.id); });
    while (ids.length < catalogue.length) { ids.push(catalogue[ids.length].key); if(!libraryVirtual){const tile=makeTile(ids.length - 1);observeLibraryTile(tile);$('#grid').append(tile);} }
    document.querySelectorAll('.grid .tile').forEach(tile => {
      const i = Number(tile.dataset.index), img = tile.querySelector('img'), url = tilePhoto(i);
      if(img){if(tile.parentElement?.id==='grid')updateLibraryTileImage(img,url);else if(img.getAttribute('src')!==url)img.src=url;}
      const badge=tile.querySelector('.video-badge');if(badge)badge.textContent=videoBadgeText(i);
      if (tile.closest('#searchGrid')) tile.classList.toggle('hidden', catalogue[i]?.state !== 'public');
    });
    document.querySelectorAll('#filmstrip button[data-index] img').forEach(img=>{const url=filmstripPhoto(Number(img.parentElement.dataset.index));if(img.getAttribute('src')!==url)img.src=url;});
    if(priorRevision!==catalogue[current]?.revision&&!viewer.classList.contains('hidden')&&(!window.PhotoEditor||document.querySelector('.media-editor')?.classList.contains('hidden'))){renderViewer(false);syncVideo();}
    refreshLibrary();
    document.querySelectorAll('#albums .album:not([data-server-album]):not(.album-create)').forEach((tile,index)=>{const items=getCollectionItems(albumDefs[index]?.[0]); const img=tile.querySelector('img'); if(img){const url=items.length?window.PhotoVault.preview((albumDefs[index]?.[0]==='Недавние'?items.reduce((latest,index)=>Math.max(latest,index),-1):(items.includes(collectionCovers[albumDefs[index]?.[0]])?collectionCovers[albumDefs[index][0]]:items[0]))):blank;if(img.getAttribute('src')!==url)img.src=url;}});
    if(reconcile){const expected=getCollectionItems(collectionName),actual=[...$('#collectionGrid').children].map(tile=>Number(tile.dataset.index));if(expected.join()!==actual.join())openCollection(collectionName);}
    syncHiddenVisibility();
    document.dispatchEvent(new Event('vault-state-change'));
  }
  async function closeAuth(result) {
    if (authBusy || authClosing) return;
    authClosing=true;
    await window.PhotoSheetMotion.hide(authSheet,modal.querySelector('.vault-auth-shade'));
    modal.classList.add('hidden'); document.querySelector('.app').inert = pendingAuth?.inert || false;
    document.body.style.overflow = pendingAuth?.overflow || '';
    const pending = pendingAuth; pendingAuth = null;
    authSheet.replaceChildren();
    pending?.focus?.isConnected && pending.focus.focus({preventScroll:true});
    window.PhotoSheetMotion.release(authSheet);
    authClosing=false;pending?.resolve(result);
  }
  function authForm(register = false) {
    authSheet.innerHTML = `<div class="sheet-grabber" aria-hidden="true"></div><div class="vault-auth-header"><h2>${!status.configured ? 'Создать код-пароль' : register ? 'Подключить ключ доступа' : 'Вход в защищённый альбом'}</h2><button type="button" data-vault="cancel" aria-label="Закрыть">×</button></div>
      ${!status.configured && !setupToken && !status.ownerRegistered ? '<p>Настройка защиты доступна владельцу по одноразовой ссылке. Открой её, чтобы создать код-пароль.</p>' : `<form><label>Код-пароль<input name="pin" type="password" inputmode="numeric" pattern="[0-9]{6,12}" minlength="6" maxlength="12" autocomplete="${status.configured ? 'current-password' : 'new-password'}" required placeholder="От 6 до 12 цифр"></label>${status.configured ? '' : '<label>Повтори код<input name="confirm" type="password" inputmode="numeric" minlength="6" maxlength="12" autocomplete="new-password" required></label>'}<button type="submit">${status.configured ? 'Открыть' : 'Создать код-пароль'}</button></form>`}
      ${status.passkey && window.PublicKeyCredential ? '<button class="vault-passkey" data-vault="passkey">Войти с ключом доступа / Face ID</button>' : ''}<p class="vault-error" role="alert"></p>`;
  }
  function ensure(configure=false) {
    if (status.authenticated&&!configure) return Promise.resolve(true);
    if (pendingAuth) return pendingAuth.promise;
    let resolve;
    const promise = new Promise(done => { resolve = done; });
    pendingAuth = { promise, resolve, overflow: document.body.style.overflow, inert: document.querySelector('.app').inert, focus:document.activeElement };
    if(!authGestures)authGestures=window.PhotoSheetGestures.attach(authSheet,{dismiss:()=>closeAuth(false),backdrop:modal.querySelector('.vault-auth-shade')});
    window.PhotoSheetMotion.hold(authSheet);
    authForm(); modal.classList.remove('hidden'); document.querySelector('.app').inert = true; document.body.style.overflow = 'hidden';
    authSheet.focus({ preventScroll: true });
    window.PhotoSheetMotion.show(authSheet,modal.querySelector('.vault-auth-shade'));
    return promise;
  }
  function bytes(value) { return Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/')), char => char.charCodeAt(0)); }
  function encoded(value) { return btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); }
  function serialize(credential) {
    const response = {};
    for (const field of ['clientDataJSON', 'attestationObject', 'authenticatorData', 'signature', 'userHandle']) {
      const value = credential.response[field]; if (value) response[field] = encoded(value);
    }
    return { id: credential.id, rawId: encoded(credential.rawId), type: credential.type, response, clientExtensionResults: credential.getClientExtensionResults() };
  }
  async function passkey(registration = false) {
    const type = registration ? 'register' : 'login';
    const options = await api(`/api/vault/${type}/options`, {}), publicKey = options.publicKey;
    publicKey.challenge = bytes(publicKey.challenge);
    if (publicKey.user) publicKey.user.id = bytes(publicKey.user.id);
    for (const list of ['allowCredentials', 'excludeCredentials']) if (publicKey[list]) publicKey[list].forEach(item => item.id = bytes(item.id));
    const credential = await navigator.credentials[registration ? 'create' : 'get']({ publicKey });
    if (!credential) throw new Error('Проверка отменена.');
    const data = await api(`/api/vault/${type}/verify`, { challengeId: options.challengeId, credential: serialize(credential) });
    apply(data);
  }
  authSheet.addEventListener('submit', async e => {
    e.preventDefault(); if (authBusy) return;
    const form = new FormData(e.target), pin = String(form.get('pin') || '');
    if (!status.configured && pin !== form.get('confirm')) { authSheet.querySelector('.vault-error').textContent = 'Коды не совпадают.'; return; }
    authBusy = true;
    try {
      const data = await api(status.configured ? '/api/vault/unlock' : '/api/vault/setup', status.configured ? { pin } : { pin, setupToken });
      setupToken = null; apply(data); authBusy = false; closeAuth(true);
    } catch (error) { authSheet.querySelector('.vault-error').textContent = error.message; }
    finally { authBusy = false; }
  });
  authSheet.addEventListener('click', async e => {
    const action = e.target.closest('[data-vault]')?.dataset.vault;
    if (action === 'cancel') closeAuth(false);
    if (action === 'passkey' && !authBusy) {
      authBusy = true;
      try { await passkey(); authBusy = false; closeAuth(true); }
      catch (error) { authSheet.querySelector('.vault-error').textContent = error.name === 'NotAllowedError' ? 'Вход отменён. Можно ввести код-пароль.' : error.message; }
      finally { authBusy = false; }
    }
  });
  modal.querySelector('.vault-auth-shade').onclick = () => closeAuth(false);
  async function showAlbum() { if (await ensure()) { gate.classList.add('hidden'); openCollection(returningAlbum); } }
  gate.querySelector('button').onclick = showAlbum;
  function guard(name, source) {
    if(name==='Скрытые'&&status.concealHidden&&!hiddenRevealed){toast('Открой «Скрытые» через профиль.');return true;}
    gate.classList.add('hidden');
    if (!isPrivate(name) || status.authenticated) return false;
    returningAlbum = name; collectionName = name;
    if (source) { albumSource = source; albumOrigin = source.getBoundingClientRect(); }
    show('collectionScreen');
    $('#albumTitle').textContent = name === 'Недавно удалённые' ? 'Удалены недавно' : name;
    $('#albumCount').textContent = ''; $('#collectionGrid').replaceChildren(); $('#albumEmpty').classList.add('hidden');
    document.querySelector('.trash-controls')?.classList.add('hidden'); gate.classList.remove('hidden');window.PhotoAlbums?.locked();
    if (source) { $('#collections').classList.remove('hidden'); animateAlbum(true).then(() => $('#collections').classList.add('hidden')); }
    return true;
  }
  function syncHiddenVisibility(){
    document.querySelector('[data-collection="Скрытые"]')?.classList.toggle('hidden',!!status.concealHidden&&!hiddenRevealed);
  }
  function concealOnExit(){
    hiddenRevealed=false;syncHiddenVisibility();
    if(!status.concealHidden||screen!=='collectionScreen'||collectionName!=='Скрытые')return;
    window.PhotoActions?.clear();window.PhotoMetadata?.lock();if(!document.querySelector('.media-editor')?.classList.contains('hidden'))window.PhotoEditor?.close(true);
    hideVideo();$('#demoVideo').removeAttribute('src');$('#demoVideo').load();viewer.classList.add('hidden');activePhoto.src=blank;nextPhoto.src=blank;$('#filmstrip').replaceChildren();exitCinema();
    originTile?.classList.remove('source-placeholder');originTile=null;$('#collectionGrid').replaceChildren();$('#collectionScreen').classList.add('hidden');show('collections');
    if(!window.PhotoSheetMotion?.locked())document.body.style.overflow='';
  }
  document.addEventListener('visibilitychange',()=>{if(document.hidden)concealOnExit();});
  window.addEventListener('pagehide',concealOnExit);
  let locking = false;
  async function lock(manual=false) {
    if(status.protectionEnabled===false)return;
    if (locking) {if(manual)throw new Error('Блокировка уже выполняется.');return;}
    locking = true;
    status.authenticated = false;
    window.PhotoActions?.clear();
    window.PhotoTrash?.lock();
    window.PhotoMetadata?.lock();
    catalogue = catalogue.map(item => ['public','shared','purged'].includes(item.state) ? item : { ...item, state: 'locked', metadata: undefined, deletedAt: null });
    if (screen === 'collectionScreen' && isPrivate(collectionName)) {
      $('#demoVideo').pause(); $('#demoVideo').removeAttribute('src');$('#demoVideo').load(); viewer.classList.add('hidden'); activePhoto.src = blank; nextPhoto.src = blank; $('#filmstrip').replaceChildren();
      originTile?.classList.remove('source-placeholder'); originTile = null; document.body.style.overflow = ''; exitCinema();
      guard(collectionName);
    }
    apply({ items: catalogue, vault: status });
    try { await api('/api/vault/lock', {}); } catch (error) {if(manual)throw error;}
    finally { locking = false; }
  }
  document.addEventListener('visibilitychange', () => { if (document.hidden && status.authenticated && !authBusy) lock(); });
  document.addEventListener('keydown', e => {
    if (!pendingAuth) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); closeAuth(false); }
    if (e.key === 'Tab') {
      const fields = [...authSheet.querySelectorAll('button,input')], first = fields[0], last = fields.at(-1);
      if (e.shiftKey && (document.activeElement === first || document.activeElement === authSheet)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  }, true);
  setInterval(async () => {
    if (document.hidden || authBusy) return;
    try { const data = await api('/api/library'); if (status.authenticated&&!data.vault.authenticated) await lock(); if(JSON.stringify(data)!==lastLibrarySnapshot)apply(data); } catch {}
  }, 15000);
  window.PhotoVault = {
    guard, ensure, lock, preview: i => catalogue[i]?.state === 'locked' || catalogue[i]?.state === 'purged' ? blank : (catalogue[i]?.preview || `/media/${i}/preview`)+(catalogue[i]?.revision?'?v='+catalogue[i].revision:''),
    thumbnail: i => `/media/${i}/thumbnail`+(catalogue[i]?.revision?'?v='+catalogue[i].revision:''),
    original: i => (catalogue[i]?.original || `/media/${i}/original`)+(catalogue[i]?.revision?'?v='+catalogue[i].revision:''),
    source: i => `/media/${i}/source`,sourcePreview: i => `/media/${i}/source-preview`, isVideo: i => catalogue[i]?.kind === 'video',
    metadata: i => catalogue[i]?.metadata, deletedAt: i => catalogue[i]?.deletedAt, state: i => catalogue[i]?.state,
    async mutate(action, indices) {
      if(indices.some(i=>catalogue[i]?.state==='shared'))throw new Error('Общий альбом доступен только для просмотра.');
      if ((!window.PHOTO_ACCOUNT?.id||indices.some(i=>['hidden','trash','locked'].includes(catalogue[i]?.state))) && !await ensure()) return false;
      try { apply(await api('/api/assets/action', { action, indices })); return true; }
      catch (error) { if (error.status === 401) { await lock(); if (await ensure()) { apply(await api('/api/assets/action', { action, indices })); return true; } return false; } throw error; }
    },
    apply,
    ensureInfo(index){
      const item=catalogue[index];if(!item||item.kind!=='video'||item.state==='shared'||item.state==='locked'||item.state==='purged'||item.metadata?.dateChecked||Number.isFinite(new Date(item.metadata?.takenAt||NaN).getTime())||pendingInfo.has(index)||Date.now()-(infoAttempts.get(index)||0)<60000)return;
      infoAttempts.set(index,Date.now());const task=api('/api/assets/info?index='+index).then(data=>{apply(data);if(current===index&&!viewer.classList.contains('hidden'))renderViewer(false);}).catch(()=>{}).finally(()=>pendingInfo.delete(index));pendingInfo.set(index,task);
    },
    async refresh(){apply(await api('/api/library'));},
    async favorite(indices,value){apply(await api('/api/assets/favorite',{indices,value}));},
    async registerPasskey() { if(!window.isSecureContext)throw new Error('Для ключа доступа / Face ID открой приложение по HTTPS.'); if (!window.PublicKeyCredential) throw new Error('Ключи доступа не поддерживаются этим браузером.'); if (!await ensure(status.protectionEnabled===false)) return false; authBusy=true;try{await passkey(true);return true}finally{authBusy=false} },
    configure:()=>ensure(true),
    hiddenVisible:()=>!status.concealHidden||hiddenRevealed,
    async setConcealHidden(value){const data=await api('/api/vault/preferences',{concealHidden:value});hiddenRevealed=false;apply(data);if(value)concealOnExit();},
    async revealHidden(){if(!await ensure())return false;hiddenRevealed=true;syncHiddenVisibility();return true;},
    status: () => status,
    screenChanged(which) { if (which !== 'collectionScreen' && isPrivate(collectionName) && status.authenticated) lock(); },
    ready() { apply(window.PHOTO_INITIAL_STATE); if (setupToken && !status.configured && !window.PHOTO_ACCOUNT) ensure(); },
  };
})();
