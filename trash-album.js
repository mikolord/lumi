// Prototype records only. Original demo files are never erased by this client-side module.
(() => {
  const DAY = 86400000, RETENTION = 90 * DAY, storageKey = 'photo-demo-trash-v1' + (window.PHOTO_ACCOUNT?.id ? ':' + window.PHOTO_ACCOUNT.id : '');
  const removedAt = new Map(), gone = new Set(), selected = new Set();
  const nativeAdd = deleted.add.bind(deleted), nativeDelete = deleted.delete.bind(deleted);
  let selection = false, writeQueued = false;
  const server = Boolean(window.PHOTO_INITIAL_STATE);
  let saved;
  try { saved = JSON.parse(localStorage.getItem(storageKey) || 'null'); } catch {}
  if (!server && saved && Array.isArray(saved.ids) && saved.ids.length <= 5000 && ids.every((id, i) => saved.ids[i] === id) && saved.ids.every(id => Number.isInteger(id) || ['video', 'vertical'].includes(id))) {
    for (let i = ids.length; i < saved.ids.length; i++) { ids.push(saved.ids[i]); if(!libraryVirtual)$('#grid').append(makeTile(i)); }
    for (const [index, time] of Array.isArray(saved.removedAt) ? saved.removedAt : []) {
      if (Number.isInteger(index) && index >= 0 && index < ids.length && Number.isFinite(time)) { nativeAdd(index); removedAt.set(index, Math.min(Date.now(), time)); }
    }
    for (const index of Array.isArray(saved.gone) ? saved.gone : []) if (Number.isInteger(index) && index >= 0 && index < ids.length) gone.add(index);
  }
  function persist() {
    if(server)return;
    if (writeQueued) return;
    writeQueued = true;
    queueMicrotask(() => {
      writeQueued = false;
      try { localStorage.setItem(storageKey, JSON.stringify({ ids, removedAt: [...removedAt], gone: [...gone] })); } catch {}
      if (screen === 'collectionScreen' && collectionName === 'Недавно удалённые') updateBadges();
    });
  }
  if(!server)deleted.add = index => { if (!deleted.has(index)) removedAt.set(index, Date.now()); nativeAdd(index); persist(); return deleted; };
  if(!server)deleted.delete = index => { const existed = nativeDelete(index); removedAt.delete(index); persist(); return existed; };
  function expire(now = Date.now()) {
    if(server)return false;
    let changed = false;
    for (const index of deleted) {
      if (!removedAt.has(index)) removedAt.set(index, now);
      if (now >= removedAt.get(index) + RETENTION) { gone.add(index); nativeDelete(index); removedAt.delete(index); changed = true; }
    }
    if (changed) persist();
    return changed;
  }
  function days(index, now = Date.now()) { return Math.max(0, Math.ceil(((window.PhotoVault?.deletedAt(index) ?? removedAt.get(index) ?? now) + RETENTION - now) / DAY)); }
  function dayLabel(count) { const mod = count % 100, unit = mod >= 11 && mod <= 14 ? 'дней' : count % 10 === 1 ? 'день' : count % 10 >= 2 && count % 10 <= 4 ? 'дня' : 'дней'; return `${count} ${unit}`; }
  const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name]}</svg>`;
  const controls = document.createElement('div');
  controls.className = 'trash-controls hidden';
  controls.innerHTML = `<button id="trashAlbumMore" class="glass circle" aria-label="Действия с удалёнными" aria-haspopup="dialog" aria-expanded="false">${icon('more')}</button><button id="trashAlbumSelect" class="glass select">Выбрать</button>`;
  document.querySelector('.album-heading').append(controls);
  const counter = document.createElement('div');
  counter.className = 'trash-selection-counter glass hidden'; counter.setAttribute('role', 'status');
  document.body.append(counter);
  const menu = document.createElement('div'); menu.className = 'trash-actions-menu hidden';
  menu.setAttribute('role', 'dialog'); menu.setAttribute('aria-label', 'Действия с удалёнными фотографиями'); menu.tabIndex = -1;
  document.body.append(menu);
  const confirmation = document.createElement('div'); confirmation.className = 'trash-confirmation hidden';
  confirmation.innerHTML = `<div class="trash-confirmation-shade"></div><section role="dialog" aria-modal="true" aria-label="Подтверждение удаления" tabindex="-1"></section>`;
  document.body.append(confirmation);
  let confirmState = null;
  function decorate(index, tile) {
    if (screen !== 'collectionScreen' || collectionName !== 'Недавно удалённые' || !deleted.has(index)) return;
    const badge = document.createElement('span'), count = days(index);
    badge.className = 'trash-deadline' + (count <= 7 ? ' urgent' : ''); badge.textContent = dayLabel(count);
    tile.append(badge); tile.setAttribute('aria-label', `Фотография ${index + 1}, до удаления ${dayLabel(count)}`);
  }
  function updateBadges() {
    document.querySelectorAll('#collectionGrid .tile').forEach(tile => {
      const index = Number(tile.dataset.index), badge = tile.querySelector('.trash-deadline');
      if (badge) { const count = days(index); badge.textContent = dayLabel(count); badge.classList.toggle('urgent', count <= 7); }
      else decorate(index, tile);
    });
    if (!$('#trashRetentionInfo')) {
      const button=document.createElement('button');button.id='trashRetentionInfo';button.className='trash-retention-info';button.setAttribute('aria-label','О сроке хранения удалённых');button.innerHTML=icon('info');
      button.onclick=()=>{alertMessage('Файлы хранятся 90 дней. За 7 дней до удаления срок отмечается красным.');setTimeout(()=>syncSelection(),4500)};
      $('#albumCount').append(' ',button);
    }
  }
  function syncSelection() {
    for (const index of selected) if (!deleted.has(index)) selected.delete(index);
    const grid = $('#collectionGrid'); grid.classList.toggle('trash-selecting', selection);
    for (const tile of grid.children) tile.classList.toggle('trash-chosen', selected.has(Number(tile.dataset.index)));
    $('#trashAlbumSelect').innerHTML = selection ? '<svg class="icon" viewBox="0 0 24 24"><path d="m6 6 12 12M18 6 6 18"/></svg>' : 'Выбрать';
    $('#trashAlbumSelect').setAttribute('aria-label', selection ? 'Отменить выделение' : 'Выбрать фотографии');
    counter.textContent = `Выбрано объектов: ${selected.size}`;
    counter.classList.toggle('hidden', !selection);
    document.body.classList.toggle('trash-selection-mode', selection);
  }
  function render() {
    expire();
    const items = window.PhotoTrash.items();
    $('#collectionGrid').replaceChildren(...items.map(makeTile));
    $('#albumCount').textContent = `${items.length} объектов`;
    $('#albumEmpty').classList.toggle('hidden', items.length > 0);
    $('#albumHint').textContent = 'Удалённые файлы хранятся здесь 90 дней.';
    syncSelection(); refreshLibrary();
  }
  let viewerTarget = null;
  function closeMenu() { menu.classList.add('hidden'); $('#trashAlbumMore').setAttribute('aria-expanded', 'false'); $('#more').setAttribute('aria-expanded','false'); }
  function openMenu(fromViewer = false) {
    if (!menu.classList.contains('hidden')) { closeMenu(); return; }
    viewerTarget=fromViewer===true?current:null;
    const items = window.PhotoTrash.items(), targets = viewerTarget!==null?[viewerTarget]:selection ? [...selected] : items;
    menu.innerHTML = `${selection && viewerTarget===null ? `<button data-trash-action="select-all">${selected.size === items.length ? 'Снять выделение' : 'Выбрать всё'}</button>` : ''}<button class="destructive" data-trash-action="delete" ${targets.length ? '' : 'disabled'}>${icon('trash')}<span>${selection || viewerTarget!==null ? 'Удалить' : 'Удалить всё'}</span></button><button data-trash-action="restore" ${targets.length ? '' : 'disabled'}>${icon('albums')}<span>${selection || viewerTarget!==null ? 'Восстановить' : 'Восстановить всё'}</span></button><p>Хранятся 90 дней. Последние 7 дней отмечены красным.</p>`;
    const rect = $(viewerTarget!==null?'#more':'#trashAlbumMore').getBoundingClientRect();
    menu.style.top = `${Math.max(12, rect.top)}px`; menu.style.right = `${Math.max(12, innerWidth - rect.right)}px`;
    menu.classList.remove('hidden'); $('#trashAlbumMore').setAttribute('aria-expanded', 'true');
    if (!matchMedia('(prefers-reduced-motion: reduce)').matches) menu.animate([{ opacity: 0, transform: 'scale(.85)' }, { opacity: 1, transform: 'none' }], { duration: 240, easing: 'ease-out' });
    menu.focus({ preventScroll: true });
  }
  async function restore(indices) {
    if(server){if(await window.PhotoVault.mutate('restore',indices)){if(!viewer.classList.contains('hidden'))await closeViewer();selected.clear();render()}return;}
    indices.forEach(index => deleted.delete(index)); selected.clear();
    render();
  }
  function confirmDelete(indices) {
    if (!indices.length) return;
    const panel = confirmation.querySelector('section');
    confirmState = { indices: [...indices], focus: document.activeElement, overflow: document.body.style.overflow };
    panel.innerHTML = `<h2>Удалить окончательно?</h2><p>Выбрано объектов: ${indices.length}. Восстановить их из «Удалены недавно» больше не получится.</p><button data-trash-confirm="delete">Удалить ${indices.length === 1 ? 'объект' : 'выбранные'}</button><button data-trash-confirm="cancel">Отмена</button>`;
    confirmation.classList.remove('hidden'); document.querySelector('.app').inert = true; document.body.style.overflow = 'hidden'; panel.focus({ preventScroll: true });
  }
  function cancelConfirmation() {
    if (!confirmState) return;
    const old = confirmState; confirmState = null; confirmation.classList.add('hidden');
    document.querySelector('.app').inert = false; document.body.style.overflow = old.overflow;
    old.focus?.isConnected && old.focus.focus({ preventScroll: true });
  }
  menu.addEventListener('click', async e => {
    const action = e.target.closest('[data-trash-action]')?.dataset.trashAction;
    if (!action) return;
    closeMenu();
    if (action === 'select-all') {
      const items = window.PhotoTrash.items(), all = items.every(index => selected.has(index)); selected.clear();
      if (!all) items.forEach(index => selected.add(index)); syncSelection();
    } else {
      const items = viewerTarget!==null?[viewerTarget]:selection ? [...selected] : window.PhotoTrash.items();
      if (action === 'restore') {try{await restore(items)}catch(error){alertMessage(error.message)}} else confirmDelete(items);
    }
  });
  confirmation.addEventListener('click', async e => {
    const action = e.target.closest('[data-trash-confirm]')?.dataset.trashConfirm;
    if (!confirmState) return;
    if (action === 'delete') {
      const items = confirmState.indices; cancelConfirmation();
      if(server){try{if(!await window.PhotoVault.mutate('purge',items))return;if(!viewer.classList.contains('hidden'))await closeViewer();selected.clear();render()}catch(error){alertMessage(error.message)}return;}
      if (!viewer.classList.contains('hidden')) await closeViewer();
      items.forEach(index => { gone.add(index); deleted.delete(index); hiddenItems.delete(index); });
      selected.clear(); persist(); render();
    } else if (action === 'cancel' || e.target.classList.contains('trash-confirmation-shade')) cancelConfirmation();
  });
  $('#collectionGrid').addEventListener('click', e => {
    if(Date.now()<ignoreClickUntil){e.preventDefault();e.stopImmediatePropagation();return;}
    if (!selection || collectionName !== 'Недавно удалённые') return;
    const tile = e.target.closest('.tile'); if (!tile) return;
    e.preventDefault(); e.stopImmediatePropagation();
    const index = Number(tile.dataset.index); selected.has(index) ? selected.delete(index) : selected.add(index); syncSelection();
  }, true);
  let drag=null,scrollFrame=0,ignoreClickUntil=0;
  const collectionGrid=$('#collectionGrid');
  function dragPoint(x,y){
    if(!drag)return;
    const tile=document.elementFromPoint(x,y)?.closest('#collectionGrid .tile');if(!tile)return;
    const position=drag.items.indexOf(Number(tile.dataset.index));if(position<0)return;
    for(let i=Math.min(drag.last,position);i<=Math.max(drag.last,position);i++)drag.select?selected.add(drag.items[i]):selected.delete(drag.items[i]);
    drag.last=position;syncSelection();
  }
  function autoScroll(){if(!drag?.active)return;const panel=$('#collectionScreen'),speed=drag.y<130?-12:drag.y>innerHeight-110?12:0;if(speed){panel.scrollTop+=speed;dragPoint(drag.x,drag.y)}scrollFrame=requestAnimationFrame(autoScroll)}
  collectionGrid.addEventListener('touchstart',e=>{if(!selection||e.touches.length!==1)return;const tile=e.target.closest('.tile');if(!tile)return;const touch=e.touches[0],index=Number(tile.dataset.index),items=window.PhotoTrash.items();drag={items,last:items.indexOf(index),select:!selected.has(index),x:touch.clientX,y:touch.clientY,startX:touch.clientX,startY:touch.clientY,active:false}},{passive:true});
  collectionGrid.addEventListener('touchmove',e=>{if(!drag)return;if(e.touches.length!==1){drag=null;cancelAnimationFrame(scrollFrame);return}const touch=e.touches[0];drag.x=touch.clientX;drag.y=touch.clientY;if(!drag.active&&Math.hypot(drag.x-drag.startX,drag.y-drag.startY)>8){drag.active=true;drag.select?selected.add(drag.items[drag.last]):selected.delete(drag.items[drag.last]);scrollFrame=requestAnimationFrame(autoScroll)}if(drag.active){e.preventDefault();dragPoint(drag.x,drag.y)}},{passive:false});
  collectionGrid.addEventListener('touchend',e=>{if(drag?.active){e.preventDefault();ignoreClickUntil=Date.now()+400}drag=null;cancelAnimationFrame(scrollFrame)},{passive:false});
  collectionGrid.addEventListener('touchcancel',()=>{drag=null;cancelAnimationFrame(scrollFrame)});
  $('#trashAlbumMore').onclick = openMenu;
  $('#trashAlbumSelect').onclick = () => { selection = !selection; selected.clear(); closeMenu(); syncSelection(); };
  document.addEventListener('pointerdown', e => { if (!e.target.closest('.trash-actions-menu,#trashAlbumMore')) closeMenu(); });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (confirmState) { e.preventDefault(); e.stopImmediatePropagation(); cancelConfirmation(); }
    else if (!menu.classList.contains('hidden')) { e.preventDefault(); e.stopImmediatePropagation(); closeMenu(); }
  }, true);
  window.PhotoTrash = {
    viewerMenu(){openMenu(true)},
    lock(){cancelConfirmation();selection=false;selected.clear();syncSelection();closeMenu();controls.classList.add('hidden')},
    items() { expire(); return [...deleted].filter(index => !gone.has(index)).sort((a, b) => (window.PhotoVault?.deletedAt(b) ?? removedAt.get(b) ?? 0) - (window.PhotoVault?.deletedAt(a) ?? removedAt.get(a) ?? 0)); },
    isGone: index => window.PhotoVault?.state(index)==='purged'||gone.has(index), days, dayLabel, decorate,
    opened(name) {
      const trash = name === 'Недавно удалённые'; controls.classList.toggle('hidden', !trash);
      document.querySelector('.album-heading').classList.toggle('trash-heading', trash);
      if (trash) { $('#albumTitle').textContent = 'Удалены недавно'; updateBadges(); syncSelection(); }
    },
    screenChanged(which) {
      closeMenu();
      if (which !== 'collectionScreen') { selection = false; selected.clear(); syncSelection(); controls.classList.add('hidden'); }
    },
  };
  function alertMessage(message){counter.textContent=message;counter.classList.remove('hidden')}
  document.addEventListener('vault-state-change',()=>{if(screen==='collectionScreen'&&collectionName==='Недавно удалённые')updateBadges()});
  const originalTrash = $('#trash').onclick;
  $('#trash').onclick = () => collectionName === 'Недавно удалённые' && screen === 'collectionScreen' ? confirmDelete([current]) : originalTrash();
  expire(); refreshLibrary();
  setInterval(() => { if (!document.hidden) { const changed = expire(); if (screen === 'collectionScreen' && collectionName === 'Недавно удалённые') changed ? render() : updateBadges(); } }, 60000);
})();
