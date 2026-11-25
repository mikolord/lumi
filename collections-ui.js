(() => {
  const storageKey = 'photo-collections-preferences-v1' + (window.PHOTO_ACCOUNT?.id ? ':' + window.PHOTO_ACCOUNT.id : '');
  const sectionNames = { albums: 'Альбомы', people: 'Люди', media: 'Типы медиафайлов', other: 'Другое' };
  let stored = {};
  try { stored = JSON.parse(localStorage.getItem(storageKey) || '{}') || {}; } catch {}
  const preferences = {
    name: window.PHOTO_ACCOUNT?.name || (typeof stored.name === 'string' && stored.name.trim() ? stored.name.trim().slice(0, 80) : 'Мой аккаунт'),
    avatar: typeof stored.avatar === 'string' && /^data:image\/(jpeg|png|webp);base64,[a-z0-9+/=]+$/i.test(stored.avatar) && stored.avatar.length < 600000 ? stored.avatar : '',
    theme:['system','light','dark'].includes(stored.theme)?stored.theme:'system',
    layout: ['list', 'grid', 'large'].includes(stored.layout) ? stored.layout : 'grid',
    order: [...new Set([...(Array.isArray(stored.order) ? stored.order : []), 'albums', 'people', 'media', 'other'])].filter(id => id in sectionNames),
    collapsed: Array.isArray(stored.collapsed) ? stored.collapsed.filter(id => id in sectionNames) : [],
    loop: stored.loop === true, autoplay: stored.autoplay === true,
  };
  const escape = text => String(text).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name]}</svg>`;
  const cross = '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>';
  const popup = document.createElement('div');
  popup.className = 'collections-popup hidden';
  popup.setAttribute('role', 'dialog'); popup.setAttribute('aria-label', 'Вид коллекций');
  popup.tabIndex = -1;
  document.body.append(popup);
  let menuOpen = false;
  function save() {
    try { localStorage.setItem(storageKey, JSON.stringify(preferences)); return true; } catch { return false; }
  }
  function animate(element, frames, duration) {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) duration = 1;
    const animation = element.animate(frames, { duration, easing: 'cubic-bezier(.22,.75,.2,1)', fill: 'both' });
    animation.finished.catch(() => {}).then(() => animation.cancel());
    return animation;
  }
  function avatarMarkup() {
    return preferences.avatar ? `<img src="${escape(preferences.avatar)}" alt="Аватар профиля">` : escape(preferences.name.split(/\s+/).slice(0, 2).map(word => [...word][0]).join('').toUpperCase());
  }
  function applyPreferences(animateSections = false) {
    window.PHOTO_THEME=preferences.theme;syncSystemBackdrop();
    $('#collections').dataset.layout = preferences.layout;
    const container = $('#collectionSections');
    // Do not detach sections during a collapse or a settings change: that resets scroll anchoring.
    if ([...container.children].map(section => section.dataset.section).join() !== preferences.order.join()) {
      preferences.order.forEach(id => container.append(document.querySelector(`[data-section="${id}"]`)));
    }
    for (const id of Object.keys(sectionNames)) {
      const section = document.querySelector(`[data-section="${id}"]`), collapsed = preferences.collapsed.includes(id);
      const content = section.querySelector('.collection-group-content');
      const changed = section.classList.contains('is-collapsed') !== collapsed;
      const height = changed && animateSections ? content.getBoundingClientRect().height : 0;
      if (changed) content.getAnimations().forEach(animation => animation.cancel());
      section.classList.toggle('is-collapsed', collapsed);
      section.querySelector('[data-collapse]').setAttribute('aria-expanded', String(!collapsed));
      content.inert = collapsed;
      if (changed && animateSections && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
        const animation = content.animate([{ height: `${height}px` }, { height: `${collapsed ? 0 : content.scrollHeight}px` }], { duration: 220, easing: 'cubic-bezier(.25,.1,.25,1)', fill: 'both' });
        animation.finished.catch(() => {}).then(() => animation.cancel());
      }
    }
    if (preferences.avatar) {
      if ($('#accountButton img')?.getAttribute('src') !== preferences.avatar) $('#accountButton').innerHTML = avatarMarkup();
    } else $('#accountButton').textContent = preferences.name.split(/\s+/).slice(0, 2).map(word => [...word][0]).join('').toUpperCase();
    $('#accountButton').setAttribute('aria-label', `Аккаунт и настройки: ${preferences.name}`);
    $('#demoVideo').loop = preferences.loop;
  }
  function renderMenu() {
    popup.innerHTML = `<div class="collections-layout-choices" role="group" aria-label="Вид альбомов">
      <button data-layout="list" aria-label="Список" aria-pressed="${preferences.layout === 'list'}"><svg class="icon" viewBox="0 0 24 24"><path d="M10 6h10M10 12h10M10 18h10"/><rect x="3" y="4" width="4" height="4" rx="1"/><rect x="3" y="10" width="4" height="4" rx="1"/><rect x="3" y="16" width="4" height="4" rx="1"/></svg></button>
      <button data-layout="grid" aria-label="Сетка" aria-pressed="${preferences.layout === 'grid'}"><svg class="icon" viewBox="0 0 24 24"><path d="M3 3h4v4H3zm7 0h4v4h-4zm7 0h4v4h-4zM3 10h4v4H3zm7 0h4v4h-4zm7 0h4v4h-4zM3 17h4v4H3zm7 0h4v4h-4zm7 0h4v4h-4z"/></svg></button>
      <button data-layout="large" aria-label="Крупные альбомы" aria-pressed="${preferences.layout === 'large'}"><svg class="icon" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg></button>
      </div><button class="collections-menu-row" data-collections-action="expand">Все</button><button class="collections-menu-row" data-collections-action="collapse">Свернуть все</button><div class="photo-context-divider"></div><button class="collections-menu-row" data-collections-action="order">Изменить порядок</button>`;
  }
  function positionMenu() {
    if (!menuOpen) return;
    const rect = $('#collectionsMore').getBoundingClientRect(), width = popup.getBoundingClientRect().width || 260;
    const left = Math.max(12, Math.min(innerWidth - width - 12, rect.right - width + 8));
    popup.style.left = `${left}px`; popup.style.top = `${Math.max(12, rect.top)}px`;
    popup.style.maxHeight = `${Math.max(150, innerHeight - rect.top - 16)}px`;
    popup.style.transformOrigin = `${rect.left + rect.width / 2 - left}px 24px`;
  }
  function closeMenu(restore = false) {
    menuOpen = false; popup.classList.add('hidden');
    $('#collectionsMore').setAttribute('aria-expanded', 'false');
    if (restore) $('#collectionsMore').focus({ preventScroll: true });
  }
  function openMenu() {
    if (menuOpen) { closeMenu(); return; }
    setFilterMenu(false); renderMenu();
    menuOpen = true; popup.classList.remove('hidden'); positionMenu();
    $('#collectionsMore').setAttribute('aria-expanded', 'true');
    animate(popup, [{ opacity: 0, transform: 'scale(.14,.1)' }, { opacity: 1, transform: 'none' }], 330);
    popup.focus({ preventScroll: true });
  }
  popup.addEventListener('click', e => {
    const layout = e.target.closest('[data-layout]')?.dataset.layout;
    if (layout) { preferences.layout = layout; applyPreferences(); save(); renderMenu(); return; }
    const action = e.target.closest('[data-collections-action]')?.dataset.collectionsAction;
    if (!action) return;
    closeMenu();
    if (action === 'order') openSheet('order');
    else { preferences.collapsed = action === 'collapse' ? Object.keys(sectionNames) : []; applyPreferences(true); save(); }
  });
  document.querySelectorAll('[data-collapse]').forEach(button => button.addEventListener('click', () => {
    const id = button.dataset.collapse;
    preferences.collapsed = preferences.collapsed.includes(id) ? preferences.collapsed.filter(value => value !== id) : [...preferences.collapsed, id];
    applyPreferences(true); save();
  }));
  document.addEventListener('pointerdown', e => { if (menuOpen && !e.target.closest('.collections-popup,#collectionsMore')) closeMenu(); });
  document.addEventListener('scroll', e => { if (menuOpen && !popup.contains(e.target)) closeMenu(); }, true);
  window.addEventListener('resize', positionMenu);

  const modal = document.createElement('div');
  modal.className = 'collections-modal hidden';
  modal.innerHTML = '<div class="collections-modal-backdrop"></div><section class="account-sheet" role="dialog" aria-modal="true" tabindex="-1"></section>';
  document.body.append(modal);
  let sheet = modal.querySelector('section');
  let sheetState = null, storageRequest = null;
  const bytes = value => {
    const unit = value >= 1024**4 ? ['ТБ', 1024**4] : value >= 1024**3 ? ['ГБ', 1024**3] : ['МБ', 1024**2];
    return `${(value / unit[1]).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} ${unit[0]}`;
  };
  function sheetHeader(title) {
    return `<div class="account-sheet-header"><h2>${title}</h2><button class="glass circle" data-account-action="close" aria-label="${sheetState?.history.length ? 'Вернуться в настройки' : 'Закрыть'}">${cross}</button></div>`;
  }
  const themeNames={system:'Автоматически',light:'Светлое',dark:'Тёмное'};
  function protectionMarkup(){
    const status=window.PhotoVault.status(),enabled=status.protectionEnabled!==false;
    return `<button class="account-settings-row" data-account-action="vault-unlock"><span>Код-пароль</span><span class="account-value">${status.configured?'Настроен':'Настроить'} ›</span></button><button class="account-settings-row" data-account-action="vault-passkey"><span>Ключ доступа / Face ID</span><span class="account-value">${status.passkey?'Подключён':'Подключить'} ›</span></button>${status.passkey?'<button class="account-settings-row account-danger" data-account-action="manage-passkey-remove">Удалить ключ доступа</button>':''}${enabled?`<button class="account-settings-row" data-account-action="vault-lock" ${status.authenticated?'':'disabled'}><span>${status.authenticated?'Заблокировать сейчас':'Альбомы заблокированы'}</span><span class="account-value"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10" width="14" height="11" rx="3"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg></span></button>${status.configured?'<button class="account-settings-row account-danger" data-account-action="manage-protection-disable">Отключить код-пароль и Face ID</button>':'<button class="account-settings-row account-danger" data-account-action="manage-protection-disable">Не использовать код-пароль</button>'}`:'<div class="account-settings-row"><span>Защита альбомов</span><span class="account-value">Выключена</span></div>'}<label class="account-settings-row"><span>Скрывать папку «Скрытые»</span><input class="account-switch" role="switch" type="checkbox" data-conceal-hidden ${status.concealHidden?'checked':''}></label>${status.concealHidden?`<button class="account-settings-row" data-account-action="reveal-hidden" ${window.PhotoVault.hiddenVisible()?'disabled':''}>${window.PhotoVault.hiddenVisible()?'«Скрытые» доступны до выхода':'Показать «Скрытые» до выхода'}</button>`:''}`;
  }
  function refreshProtection(){
    const group=modal.querySelector('#accountProtectionRows');if(!group)return;
    const parent=group.closest('.account-sheet'),top=parent.scrollTop;group.innerHTML=protectionMarkup();parent.scrollTop=top;
  }
  function renderAccount() {
    const items=ids.map((_,i)=>i).filter(i=>!deleted.has(i)&&!window.PhotoTrash?.isGone(i)&&window.PhotoVault?.state(i)!=='shared'),videos=items.filter(isVideo).length;
    sheet.innerHTML=sheetHeader('')+`<div class="account-summary"><button class="profile-avatar account-large-avatar" data-account-action="choose-avatar" aria-label="Изменить фотографию профиля">${avatarMarkup()}</button><button class="account-change-photo" data-account-action="choose-avatar">Изменить фото</button><p class="account-avatar-error" role="alert"></p><h2>${escape(preferences.name)}</h2><p>${items.length-videos} фото, ${videos} видео</p><small>${escape(window.PHOTO_ACCOUNT?.login||'Локальный профиль')}</small></div>
    <section class="account-storage" aria-label="Личное хранилище"><div class="account-storage-top">${icon('albums')}<h3>Личное хранилище</h3><button data-account-action="refresh-storage" aria-label="Обновить сведения о хранилище">↻</button></div><div id="accountStorageData" role="status"><p class="account-muted">Загрузка…</p></div></section>
    <h3 class="account-group-title">Аккаунт</h3><div class="account-settings-group"><button class="account-settings-row" data-account-action="profile"><span>Имя профиля</span><span class="account-value">${escape(preferences.name)} ›</span></button>${window.PHOTO_ACCOUNT?.id?'<button class="account-settings-row" data-account-action="manage-devices">Устройства и вход по QR <span>›</span></button><button class="account-settings-row" data-account-action="manage-password">Сменить пароль <span>›</span></button><button class="account-settings-row account-danger" data-account-action="manage-delete-account">Удалить аккаунт <span>›</span></button>':''}</div>
    ${window.PHOTO_ACCOUNT?.id?`<h3 class="account-group-title">Медиатека</h3><div class="account-settings-group"><button class="account-settings-row" data-account-action="manage-immich">Импорт из Immich <span>›</span></button>${window.PHOTO_ACCOUNT.role==='admin'?'<button class="account-settings-row" data-account-action="manage-users">Пользователи и лимиты <span>›</span></button>':''}</div>`:''}
    ${window.PHOTO_ACCOUNT?.role==='admin'?`<h3 class="account-group-title">Сервер</h3><div class="account-settings-group"><button class="account-settings-row" data-account-action="manage-metrics">Нагрузка приложения <span>›</span></button><button class="account-settings-row" data-account-action="manage-updates">Обновления <span>›</span></button></div>`:''}
    ${window.PhotoVault?`<h3 class="account-group-title">Защита альбомов</h3><div class="account-settings-group" id="accountProtectionRows">${protectionMarkup()}</div><p class="account-muted" id="vaultSettingsMessage" role="status"></p>`:''}
    <h3 class="account-group-title">Настройки</h3><div class="account-settings-group">${window.PHOTO_ACCOUNT?.id?`<label class="account-settings-row"><span>Распознавание людей</span><input class="account-switch" role="switch" type="checkbox" data-people-visible ${window.PhotoPeople?.visible()?'checked':''}></label>`:''}<label class="account-settings-row"><span>Автовоспроизведение видео</span><input class="account-switch" type="checkbox" data-preference="autoplay" ${preferences.autoplay?'checked':''}></label><label class="account-settings-row"><span>Повтор видео</span><input class="account-switch" type="checkbox" data-preference="loop" ${preferences.loop?'checked':''}></label><button class="account-settings-row" data-account-action="theme"><span>Оформление</span><span class="account-value" data-theme-label>${themeNames[preferences.theme]} ›</span></button></div>${window.PhotoAccount?'<button class="account-reset-order account-danger" data-account-action="sign-out">Выйти из аккаунта</button>':''}`;
    loadStorage();
  }
  function renderTheme(){sheet.innerHTML=sheetHeader('Оформление')+`<div class="account-settings-group">${Object.entries(themeNames).map(([value,name])=>`<button class="account-settings-row" data-theme-choice="${value}" aria-pressed="${preferences.theme===value}"><span>${name}</span><span class="account-value">${preferences.theme===value?'✓':''}</span></button>`).join('')}</div>`;}
  async function loadStorage() {
    storageRequest?.abort();
    const request = new AbortController(); storageRequest = request;
    const target = $('#accountStorageData');
    if (!target) return;
    target.innerHTML = '<p class="account-muted">Получаем данные сервера…</p>';
    try {
      const data = window.PhotoAccount ? await window.PhotoAccount.api('/api/storage') : await (await fetch('/api/storage', { cache: 'no-store', signal: request.signal })).json();
      if (!Number.isFinite(data.used) || data.used<0) throw new Error('Invalid storage data');
      if (request.signal.aborted || !target.isConnected) return;
      const limited=Number.isFinite(data.total)&&data.total>0,percentage=limited?Math.min(100,data.used/data.total*100):0;
      target.innerHTML = `<p class="account-free-space">${limited?'Осталось '+bytes(data.free):'Без лимита'}</p>${limited?`<div class="account-storage-track" role="progressbar" aria-label="Использование личного лимита" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(percentage)}"><span style="width:${percentage}%"></span></div>`:''}<div class="account-storage-numbers"><span>Мои файлы: ${bytes(data.used)}</span><span>${limited?'Лимит '+bytes(data.total):'Лимит не установлен'}</span></div>${!limited&&Number.isFinite(data.available)?`<p class="account-muted">На сервере доступно ${bytes(data.available)}</p>`:''}`;
    } catch (error) {
      if (error.name !== 'AbortError' && target.isConnected) target.innerHTML = '<p class="account-muted">Данные хранилища недоступны. Проверь соединение с сервером и обнови сведения.</p>';
    }
  }
  function renderOrder() {
    sheet.innerHTML = sheetHeader('Порядок разделов') + `<p class="account-muted account-order-hint">Подними или опусти раздел, чтобы изменить его положение в коллекциях.</p><div class="account-settings-group account-order-list">${preferences.order.map((id, index) => `<div class="account-settings-row"><span>${sectionNames[id]}</span><div class="account-order-buttons"><button data-order-id="${id}" data-direction="-1" aria-label="${sectionNames[id]}: поднять" ${index === 0 ? 'disabled' : ''}>↑</button><button data-order-id="${id}" data-direction="1" aria-label="${sectionNames[id]}: опустить" ${index === preferences.order.length - 1 ? 'disabled' : ''}>↓</button></div></div>`).join('')}</div><button class="account-reset-order" data-account-action="reset-order">Восстановить исходный порядок</button>`;
  }
  function renderProfile() {
    sheet.innerHTML = sheetHeader('Аккаунт') + `<div class="account-avatar-editor"><button class="profile-avatar account-large-avatar" data-account-action="choose-avatar" aria-label="Выбрать фотографию профиля">${avatarMarkup()}</button><div class="account-avatar-actions"><button data-account-action="choose-avatar">Выбрать фото</button>${preferences.avatar ? '<button data-account-action="remove-avatar">Удалить фото</button>' : ''}</div><p class="account-avatar-error" role="alert"></p></div><form class="account-profile-form"><label for="accountProfileName">Имя профиля</label><input id="accountProfileName" name="name" required maxlength="80" autocomplete="name" value="${escape(preferences.name)}"><button type="submit">Сохранить</button></form>`;
  }
  const avatarInput = document.createElement('input');
  avatarInput.type = 'file'; avatarInput.accept = 'image/*'; avatarInput.hidden = true;
  avatarInput.id = 'profileAvatarFile'; avatarInput.setAttribute('aria-label', 'Фотография профиля');
  document.body.append(avatarInput);
  function avatarError(message) { const error = sheet.querySelector('.account-avatar-error'); if (error) error.textContent = message; }
  function refreshAvatar() {
    applyPreferences();
    const summary=modal.querySelector('.account-summary h2');if(summary)summary.textContent=preferences.name;
    const label=modal.querySelector('[data-account-action=profile] .account-value');if(label)label.textContent=preferences.name+' ›';
    modal.querySelectorAll('.account-large-avatar').forEach(element => element.innerHTML = avatarMarkup());
    const actions = sheet.querySelector('.account-avatar-actions');
    if (actions) actions.innerHTML = `<button data-account-action="choose-avatar">Выбрать фото</button>${preferences.avatar ? '<button data-account-action="remove-avatar">Удалить фото</button>' : ''}`;
  }
  avatarInput.addEventListener('change', async () => {
    const file = avatarInput.files?.[0]; avatarInput.value = '';
    if (!file) return;
    avatarError('');
    if (!file.type.startsWith('image/') && !/\.(heic|heif)$/i.test(file.name)) { avatarError('Выбери файл фотографии.'); return; }
    if (file.size > 20 * 1024 * 1024) { avatarError('Выбери фотографию размером до 20 МБ.'); return; }
    try {
      const avatar = await window.AvatarCrop.open(file);
      if (!avatar) return;
      const previous = preferences.avatar;
      preferences.avatar = avatar;
      if (!save()) { preferences.avatar = previous; avatarError('Браузер не разрешил сохранить фотографию. Освободи место и попробуй ещё раз.'); return; }
      refreshAvatar();
    } catch { avatarError('Не удалось открыть фото. Попробуй JPEG, PNG или WebP.'); }
  });

  function openSheet(page = 'account', options = {}) {
    closeMenu();
    const opening = !sheetState;
    if (!sheetState) sheetState = { focus: document.activeElement, overflow: document.body.style.overflow, page, history: [] };
    else if (sheetState.closing) return;
    else if(page!==sheetState.page){
      sheetState.history.push({page:sheetState.page,sheet,scrollTop:sheet.scrollTop,focus:document.activeElement});
      sheet.inert=true;sheet.setAttribute('inert','');sheet.setAttribute('aria-hidden','true');
      sheet=document.createElement('section');sheet.className='account-sheet account-child-sheet';sheet.setAttribute('role','dialog');sheet.setAttribute('aria-modal','true');sheet.tabIndex=-1;modal.append(sheet);
      window.PhotoSheetGestures.attach(sheet,{dismiss:dismissSheet,backdrop:modal.querySelector('.collections-modal-backdrop')});
    }
    sheetState.page = page;
    sheet.getAnimations().forEach(animation => animation.cancel());
    sheet.style.transform = '';
    modal.querySelector('.collections-modal-backdrop').style.opacity = '';
    if (page === 'account') renderAccount(); else if (page === 'profile') renderProfile();else if(page==='theme')renderTheme(); else renderOrder();
    sheet.scrollTop = options.scrollTop || 0;
    window.PhotoSheetMotion.hold(sheet);
    modal.classList.remove('hidden'); document.querySelector('.app').inert = true; document.body.style.overflow = 'hidden';
    $('#accountButton').setAttribute('aria-expanded', 'true');
    window.PhotoSheetMotion.show(sheet,modal.querySelector('.collections-modal-backdrop'),!opening);
    sheet.focus({ preventScroll: true });
  }
  async function dismissSheet() {
    if(!sheetState||sheetState.closing)return;
    if(!sheetState.history.length)return closeSheet();
    sheetState.closing=true;
    const child=sheet,previous=sheetState.history.pop();
    await window.PhotoSheetMotion.hide(child);
    child.remove();window.PhotoSheetMotion.release(child);
    sheet=previous.sheet;sheet.inert=false;sheet.removeAttribute('inert');sheet.removeAttribute('aria-hidden');
    sheetState.page=previous.page;sheetState.closing=false;
    refreshAvatar();sheet.scrollTop=previous.scrollTop;
    if(previous.focus?.isConnected)previous.focus.focus({preventScroll:true});
    sheet.scrollTop=previous.scrollTop;
  }
  async function closeSheet() {
    if (!sheetState || sheetState.closing) return;
    sheetState.closing = true;
    storageRequest?.abort();
    const old = sheetState;
    await window.PhotoSheetMotion.hide(sheet,modal.querySelector('.collections-modal-backdrop'));
    modal.classList.add('hidden'); sheetState = null;
    document.querySelector('.app').inert = false; document.body.style.overflow = old.overflow;
    $('#accountButton').setAttribute('aria-expanded', 'false');
    old.focus?.isConnected && old.focus.focus({ preventScroll: true });
    window.PhotoSheetMotion.release(sheet);
  }
  modal.addEventListener('click', async e => {
    if(e.target.closest('.account-sheet')!==sheet)return;
    const theme=e.target.closest('[data-theme-choice]')?.dataset.themeChoice;
    if(theme in themeNames){preferences.theme=theme;save();applyPreferences();renderTheme();modal.querySelector('[data-theme-label]').textContent=themeNames[theme]+' ›';return;}
    const move = e.target.closest('[data-order-id]');
    if (move) {
      const position = preferences.order.indexOf(move.dataset.orderId), next = position + Number(move.dataset.direction);
      if (next < 0 || next >= preferences.order.length) return;
      [preferences.order[position], preferences.order[next]] = [preferences.order[next], preferences.order[position]];
      applyPreferences(); save(); renderOrder(); return;
    }
    const action = e.target.closest('[data-account-action]')?.dataset.accountAction;
    if(action==='reveal-hidden'){if(await window.PhotoVault.revealHidden()){refreshProtection();toast('«Скрытые» доступны до выхода из приложения');}return;}
    if(action?.startsWith('manage-')){window.PhotoManage.open(action.slice(7));return;}
    if(action?.startsWith('vault-')){
      const settings=sheet,top=sheet.scrollTop;
      try{
        if(action==='vault-passkey')await window.PhotoVault.registerPasskey();
        else if(action==='vault-lock'){await window.PhotoVault.lock(true);toast('Скрытые и недавно удалённые альбомы заблокированы');}
        else if(window.PhotoVault.status().protectionEnabled===false)await window.PhotoVault.configure();else await window.PhotoVault.ensure();
        const status=window.PhotoVault.status(),lock=settings.querySelector('[data-account-action=vault-lock]');
        if(lock){lock.disabled=!status.authenticated;lock.firstElementChild.textContent=status.authenticated?'Заблокировать сейчас':'Альбомы заблокированы';}
        const pin=settings.querySelector('[data-account-action=vault-unlock] .account-value');if(pin)pin.textContent=(status.configured?'Настроен':'Настроить')+' ›';
        const key=settings.querySelector('[data-account-action=vault-passkey] .account-value');if(key)key.textContent=(status.passkey?'Подключён':'Подключить')+' ›';
      }catch(error){const message=settings.querySelector('#vaultSettingsMessage');if(message)message.textContent=error.name==='NotAllowedError'?'Подключение отменено. Можно пользоваться код-паролем.':error.message;}
      finally{if(settings.isConnected)settings.scrollTop=top;}
      return;
    }

    if (action === 'sign-out') { await window.PhotoAccount.logout(); return; }
    if (action === 'close') dismissSheet();
    if (action === 'choose-avatar') avatarInput.click();
    if (action === 'remove-avatar') {
      const previous = preferences.avatar; preferences.avatar = '';
      if (save()) refreshAvatar();
      else { preferences.avatar = previous; avatarError('Не удалось сохранить изменение. Попробуй ещё раз.'); }
    }
    if (action === 'refresh-storage') loadStorage();
    if (action === 'profile' || action === 'order'||action==='theme') openSheet(action);
    if (action === 'reset-order') { preferences.order = Object.keys(sectionNames); applyPreferences(); save(); renderOrder(); }
  });
  modal.addEventListener('change', async e => {
    if(e.target.closest('.account-sheet')!==sheet)return;
    if(e.target.matches('[data-people-visible]')){const input=e.target;input.disabled=true;try{await window.PhotoPeople.setVisible(input.checked);}catch(error){input.checked=!!window.PhotoPeople.visible();avatarError(error.message);}finally{input.disabled=false;}return;}
    if(e.target.matches('[data-conceal-hidden]')){const input=e.target;input.disabled=true;try{await window.PhotoVault.setConcealHidden(input.checked);refreshProtection();}catch(error){input.checked=!!window.PhotoVault.status().concealHidden;avatarError(error.message);}finally{input.disabled=false;}return;}
    const setting = e.target.dataset.preference;
    if (!['loop', 'autoplay'].includes(setting)) return;
    preferences[setting] = e.target.checked; applyPreferences(); save();
  });
  modal.addEventListener('submit', async e => {
    if(e.target.closest('.account-sheet')!==sheet)return;
    e.preventDefault();
    const name = String(new FormData(e.target).get('name') || '').trim();
    if (!name) return;
    if(window.PhotoAccount){try{await window.PhotoAccount.rename(name)}catch(error){avatarError(error.message);return;}}
    preferences.name = name.slice(0, 80); applyPreferences(); save(); dismissSheet();
  });
  modal.querySelector('.collections-modal-backdrop').onclick = dismissSheet;
  window.PhotoSheetGestures.attach(sheet, { dismiss: dismissSheet, backdrop: modal.querySelector('.collections-modal-backdrop') });
  document.addEventListener('keydown', e => {
    if (menuOpen && e.key === 'Escape') { e.preventDefault(); closeMenu(true); return; }
    if (!sheetState) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); dismissSheet(); }
    if (e.key === 'Tab') {
      const items = [...sheet.querySelectorAll('button:not(:disabled),input')], first = items[0], last = items.at(-1);
      if (e.shiftKey && (document.activeElement === first || document.activeElement === sheet)) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    }
  }, true);
  let playbackSource = '';
  window.PhotoCollections = {
    screenChanged(which) {
      closeMenu();
      $('#collectionsMore').classList.toggle('hidden', which !== 'collections');
      $('#accountButton').classList.toggle('hidden', which !== 'collections');
    },
    syncVideo() {
      const video = $('#demoVideo'), source = video.getAttribute('src');
      video.loop = preferences.loop;
      if (!isVideo(current)) { playbackSource = ''; return; }
      if (source !== playbackSource) { playbackSource = source; if (preferences.autoplay && !document.hidden) video.play().catch(() => {}); }
    },
  };
  document.addEventListener('vault-state-change',refreshProtection);
  window.addEventListener('pageshow',refreshProtection);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshProtection();});
  $('#collectionsMore').onclick = openMenu;
  $('#accountButton').onclick = () => openSheet();
  applyPreferences();
  window.PhotoCollections.screenChanged(screen);
})();
