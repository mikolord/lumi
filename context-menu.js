// Local prototype actions. The server's original media files are never modified.
(() => {
  const holdDelay = 480, moveTolerance = 9;
  let pending = null, state = null, closing = false, suppressClickUntil = 0;
  const overlay = document.createElement('div');
  overlay.className = 'photo-context hidden';
  overlay.innerHTML = `<div class="photo-context-shade"></div>
    <div class="photo-context-layout">
      <button class="photo-context-preview" aria-label="Открыть фотографию"><img alt="" draggable="false"></button>
      <div class="photo-context-panel" role="dialog" aria-modal="true" aria-label="Действия с фотографией" tabindex="-1"></div>
    </div><button class="photo-context-close glass circle" aria-label="Отменить выделение"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button>`;
  document.body.append(overlay);
  const panel = overlay.querySelector('.photo-context-panel');
  const preview = overlay.querySelector('.photo-context-preview');
  const image = preview.querySelector('img');
  const notice = document.createElement('div');
  notice.className = 'photo-context-notice hidden';
  notice.setAttribute('role', 'status');
  document.body.append(notice);
  let noticeTimer;
  function announce(message) {
    notice.textContent = message;
    notice.classList.remove('hidden');
    clearTimeout(noticeTimer);
    noticeTimer = setTimeout(() => notice.classList.add('hidden'), 2600);
  }
  const extraPaths = {
    copy: '<path d="M8 7H5v14h12v-3M9 3h7l4 4v10H9zM16 3v5h4"/>',
    duplicate: '<rect x="7" y="7" width="14" height="14" rx="3"/><path d="M17 4H6a2 2 0 0 0-2 2v11m10-7v8m-4-4h8"/>',
    hide: '<path d="m3 3 18 18M10.5 6.1A13 13 0 0 1 12 6c6.5 0 10 6 10 6a18 18 0 0 1-3.2 3.7M6.1 6.9A20 20 0 0 0 2 12s3.5 6 10 6a12 12 0 0 0 4.1-.7M10 10a3 3 0 0 0 4 4"/>',
    slideshow: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m10 9 5 3-5 3z"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4m10-4v4M3 10h18M7 14h.01M12 14h.01M17 14h.01M7 18h.01M12 18h.01"/>',
    location: '<path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 0 1 14 0Z"/><circle cx="12" cy="10" r="2.5"/>',
    unfavorite: '<path d="M7 5a4.6 4.6 0 0 1 5 2 4.6 4.6 0 0 1 8.8 1.8c0 1.4-1 3.1-2.4 4.7M14.7 17.1 12 19s-8.8-5.8-8.8-10a4.5 4.5 0 0 1 .7-2.5M3 3l18 18"/>',
  };
  const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${extraPaths[name] || paths[name]}</svg>`;
  const row = (action, name, label, more = false, danger = false) => `<button class="photo-context-row${danger ? ' destructive' : ''}" data-action="${action}">${icon(name)}<span>${label}</span>${more ? '<span class="photo-context-chevron">›</span>' : ''}</button>`;
  const indexForCover=()=>state?.indices.length===1?state.indices[0]:-1;
  function renderMain() {
    if(state?.indices.some(i=>window.PhotoVault?.state(i)==='shared')){panel.innerHTML='<p class="photo-context-heading">Общий альбом · только просмотр</p>'+row('share','share','Поделиться и сохранить')+row('slideshow','slideshow','Начать слайд-шоу');return;}

    const items = state.indices, trashed = items.length > 0 && items.every(i => deleted.has(i)), hidden = items.length > 0 && items.every(i => hiddenItems.has(i));
    const allFavorite = items.length > 0 && items.every(i => favorites.has(i));
    panel.innerHTML = `<div class="photo-context-quick">
      <button data-action="copy">${icon('copy')}<span>Скопиро-<br>вать</span></button>
      <button data-action="duplicate">${icon('duplicate')}<span>Дублиро-<br>вать</span></button>
      <button data-action="hide">${icon('hide')}<span>${hidden ? 'Показать' : 'Скрыть'}</span></button>
    </div><div class="photo-context-divider"></div>
    ${state.viewerMenu ? '' : state.bulk ? row('select-all', 'photos', chosen.size === getSelectionItems().length ? 'Снять выделение' : 'Выбрать всё') : row('share', 'share', 'Поделиться')}
    ${state.viewerMenu ? '' : row('favorite', allFavorite ? 'unfavorite' : 'heart', allFavorite ? 'Удалить<br>из Избранного' : 'В Избранное')}
    ${row('save','share','Сохранить фото и видео')}
    ${state.bulk || state.viewerMenu ? row('slideshow', 'slideshow', 'Начать слайд-шоу') : ''}
    <div class="photo-context-divider"></div>
    ${!state.bulk&&!state.viewerMenu&&window.PhotoManage?.canSetCover?.(indexForCover())?row('album-cover','photos','Сделать обложкой'):''}
    ${row('albums', 'photos', 'Добавить в', true)}
    ${row('information', 'info', 'Изменение<br>информации', true)}
    ${state.bulk || state.viewerMenu ? '' : `<div class="photo-context-divider"></div>${row(trashed ? 'restore' : 'delete', 'trash', trashed ? 'Восстановить' : 'Удалить', false, !trashed)}`}`;
    if (!items.length) panel.querySelectorAll('[data-action]:not([data-action="select-all"])').forEach(button => button.disabled = true);
  }
  function cancelHold() {
    if (pending) clearTimeout(pending.timer);
    pending = null;
  }
  function startHold(tile, x, y) {
    cancelHold();
    if (selecting || busy || state || closing || !viewer.classList.contains('hidden')) return;
    pending = { tile, x, y, timer: setTimeout(() => {
      const target = pending?.tile;
      pending = null;
      if (target?.isConnected && !selecting && !pinching) openMenu(target);
    }, holdDelay) };
  }
  function moveHold(x, y) {
    if (pending && Math.hypot(x - pending.x, y - pending.y) > moveTolerance) cancelHold();
  }
  function motion(element, frames, duration) {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) duration = 1;
    return element.animate(frames, { duration, easing: 'cubic-bezier(.22,.75,.2,1)', fill: 'both' });
  }
  function previewTransform(rect) {
    const end = image.getBoundingClientRect();
    if (!end.width || !end.height) return 'scale(.8)';
    return `translate(${rect.left + rect.width / 2 - end.left - end.width / 2}px,${rect.top + rect.height / 2 - end.top - end.height / 2}px) scale(${rect.width / end.width},${rect.height / end.height})`;
  }
  function openMenu(tile) {
    if (state || closing) return;
    cancelHold();
    setFilterMenu(false);
    const index = Number(tile.dataset.index), original = tile.querySelector('img');
    state = { index, indices: [index], bulk: false, tile, focus: document.activeElement, overflow: document.body.style.overflow };
    overlay.classList.remove('photo-context-bulk', 'photo-context-viewer');
    panel.style.removeProperty('--selection-menu-top');
    panel.style.removeProperty('--selection-menu-left');
    panel.setAttribute('aria-label', 'Действия с фотографией');
    suppressClickUntil = Date.now() + 650;
    image.src = photo(index);
    image.style.aspectRatio = `${original.naturalWidth || 1} / ${original.naturalHeight || 1}`;
    overlay.classList.remove('hidden');
    renderMain();
    document.body.style.overflow = 'hidden';
    document.querySelector('.app').inert = true;
    tile.classList.add('context-source');
    const animations = [
      motion(overlay.querySelector('.photo-context-shade'), [{ opacity: 0 }, { opacity: 1 }], 280),
      motion(image, [{ transform: previewTransform(tile.getBoundingClientRect()), borderRadius: '4px' }, { transform: 'none', borderRadius: '24px' }], 420),
      motion(panel, [{ opacity: 0, transform: 'translateY(-14px) scale(.88)' }, { opacity: 1, transform: 'none' }], 360),
    ];
    animations.forEach(a => a.finished.catch(() => {}).then(() => a.cancel()));
    panel.focus({ preventScroll: true });
  }
  function openSelectionMenu() {
    if (!selecting || state || closing || busy) return;
    cancelHold(); setFilterMenu(false);
    const indices = [...chosen].filter(i => getSelectionItems().includes(i));
    state = { index: indices[0], indices, bulk: true, focus: document.activeElement, overflow: document.body.style.overflow };
    overlay.classList.add('photo-context-bulk');
    overlay.classList.remove('photo-context-viewer');
    overlay.classList.remove('hidden');
    panel.setAttribute('aria-label', `Действия с выбранными: ${indices.length}`);
    renderMain();
    positionSelectionMenu();
    document.body.style.overflow = 'hidden';
    document.querySelector('.app').inert = true;
    $('#selectionMore').setAttribute('aria-expanded', 'true');
    const animations = [
      motion(overlay.querySelector('.photo-context-shade'), [{ opacity: 0 }, { opacity: 1 }], 240),
      motion(panel, [{ opacity: 0, transform: 'scale(.2,.12)' }, { opacity: 1, transform: 'scale(1.025,1.01)', offset: .8 }, { opacity: 1, transform: 'none' }], 360),
    ];
    animations.forEach(a => a.finished.catch(() => {}).then(() => a.cancel()));
    panel.focus({ preventScroll: true });
  }
  function positionSelectionMenu() {
    if (state?.viewerMenu) { positionViewerMenu(); return; }
    if (!state?.bulk) return;
    const button = $('#selectionMore').getBoundingClientRect(), close = $('#select').getBoundingClientRect();
    const width = panel.getBoundingClientRect().width || Math.min(312, innerWidth - 84);
    const left = Math.max(12, Math.min(innerWidth - width - 72, button.right - width + 8));
    panel.style.setProperty('--selection-menu-top', `${Math.max(12, button.top)}px`);
    panel.style.setProperty('--selection-menu-left', `${left}px`);
    panel.style.transformOrigin = `${button.left + button.width / 2 - left}px 24px`;
    const cross = overlay.querySelector('.photo-context-close');
    Object.assign(cross.style, { top: `${close.top}px`, left: `${close.left}px`, width: `${close.width}px`, height: `${close.height}px` });
  }
  function positionViewerMenu() {
    const rect = $('#more').getBoundingClientRect();
    const width = panel.getBoundingClientRect().width || Math.min(292, innerWidth - 48);
    const left = Math.max(12, Math.min(innerWidth - width - 12, rect.right - width));
    panel.style.setProperty('--selection-menu-top', `${Math.max(12, rect.top)}px`);
    panel.style.setProperty('--selection-menu-left', `${left}px`);
    panel.style.transformOrigin = `${rect.left + rect.width / 2 - left}px 24px`;
  }
  function openViewerMenu() {
    if(screen==='collectionScreen'&&collectionName==='Недавно удалённые'&&window.PhotoTrash){window.PhotoTrash.viewerMenu();return;}
    if (state || closing || viewer.classList.contains('hidden')) return;
    finishSlideTransition();
    if (busy) return;
    cancelHold();
    state = { index: current, indices: [current], viewerMenu: true, focus: document.activeElement, overflow: document.body.style.overflow };
    overlay.classList.remove('photo-context-bulk');
    overlay.classList.add('photo-context-viewer');
    overlay.classList.remove('hidden');
    panel.setAttribute('aria-label', 'Действия с открытой фотографией');
    renderMain(); positionViewerMenu();
    document.querySelector('.app').inert = true;
    document.body.style.overflow = 'hidden';
    $('#more').setAttribute('aria-expanded', 'true');
    const animations = [
      motion(overlay.querySelector('.photo-context-shade'), [{ opacity: 0 }, { opacity: 1 }], 220),
      motion(panel, [{ opacity: 0, transform: 'scale(.16,.1)' }, { opacity: 1, transform: 'none' }], 340),
    ];
    animations.forEach(a => a.finished.catch(() => {}).then(() => a.cancel()));
    panel.focus({ preventScroll: true });
  }
  async function closeMenu() {
    if (!state || closing) return;
    closing = true;
    const old = state;
    overlay.getAnimations({ subtree: true }).forEach(a => a.cancel());
    const animations = [
      motion(overlay.querySelector('.photo-context-shade'), [{ opacity: 1 }, { opacity: 0 }], 240),
      motion(panel, [{ opacity: 1, transform: 'none' }, { opacity: 0, transform: old.bulk || old.viewerMenu ? 'scale(.2,.12)' : 'translateY(-10px) scale(.92)' }], 240),
    ];
    if (!old.bulk && !old.viewerMenu) animations.push(motion(image, [{ transform: 'none' }, { transform: previewTransform(old.tile.getBoundingClientRect()), borderRadius: '4px', opacity: .2 }], 300));
    await Promise.all(animations.map(a => a.finished.catch(() => {})));
    overlay.classList.add('hidden');
    animations.forEach(a => a.cancel());
    old.tile?.classList.remove('context-source');
    $('#selectionMore').setAttribute('aria-expanded', 'false');
    $('#more').setAttribute('aria-expanded', 'false');
    panel.style.transformOrigin = '';
    document.body.style.overflow = old.overflow;
    document.querySelector('.app').inert = false;
    state = null;
    closing = false;
    suppressClickUntil = Date.now() + 400;
    if (old.focus?.isConnected) old.focus.focus({ preventScroll: true });
  }
  function refreshContextGrid() {
    refreshLibrary();
    if (screen === 'collectionScreen' && viewer.classList.contains('hidden')) {
      const items = getCollectionItems(collectionName), grid = $('#collectionGrid');
      grid.replaceChildren(...items.map(makeTile));
      $('#albumCount').textContent = `${items.length} объектов`;
      $('#albumEmpty').classList.toggle('hidden', items.length > 0);globalThis.PhotoAlbums?.refresh();
    }
  }
  const shareCache = new Map();
  function mediaFile(index) {
    if (shareCache.has(index)) return shareCache.get(index).promise;
    const entry = {};
    entry.promise = fetch(window.PhotoVault?.original(index) || (isVideo(index) ? videoSource(index) : photo(index))).then(response => {
      if (!response.ok) throw new Error('Media unavailable');
      return response.blob();
    }).then(blob => {
      const name=window.PhotoVault?.metadata(index)?.name || (isVideo(index) ? `Видео-${index + 1}.mp4` : `Фото-${index + 1}.jpg`);
      entry.file = new File([blob], name, { type: blob.type || (isVideo(index) ? 'video/mp4' : 'image/jpeg') });
      return entry.file;
    }).catch(error => { shareCache.delete(index); throw error; });
    if (shareCache.size >= 8) shareCache.delete(shareCache.keys().next().value);
    shareCache.set(index, entry);
    return entry.promise;
  }
  async function shareMedia(indices, button) {
    if (!navigator.share) { announce('Системное меню «Поделиться» недоступно в этом браузере'); return false; }
    button.disabled = true;
    try {
      // Ready files let iOS open its share sheet directly inside the tap's user activation.
      const ready = indices.map(i => shareCache.get(i)?.file);
      const files = ready.every(Boolean) ? ready : await Promise.all(indices.map(mediaFile));
      if (navigator.canShare && !navigator.canShare({ files })) { announce('Этот браузер не поддерживает отправку файлов'); return false; }
      await navigator.share({ files });
      return true;
    } catch (error) {
      if (error.name !== 'AbortError') announce('Не удалось открыть отправку. Попробуй ещё раз.');
      return false;
    } finally { button.disabled = false; }
  }
  function renderAlbums() {
    panel.innerHTML = `<button class="photo-context-back" data-action="back">‹ Назад</button><p class="photo-context-heading">Добавить в альбом</p>` +
      ['Путешествия', 'Природа', 'Избранное'].map((name, n) => row(`album-${n}`, 'albums', name)).join('');
  }
  function renderInformation() {
    panel.innerHTML = `<button class="photo-context-back" data-action="back">‹ Назад</button><div class="photo-context-information-title">${icon('info')}<strong>Изменение<br>информации</strong><span>⌄</span></div><div class="photo-context-divider"></div>` +
      row('metadata-date', 'calendar', 'Изменить дату<br>и время') + row('metadata-location', 'location', 'Изменить<br>геопозицию');
    panel.animate([{ opacity: 0, transform: 'translateY(10px) scale(.96)' }, { opacity: 1, transform: 'none' }], { duration: 260, easing: 'cubic-bezier(.22,.75,.2,1)' });
  }
  panel.addEventListener('click', e => {
    e.stopPropagation();
    const button = e.target.closest('[data-action]');
    if (!button || !state || closing) return;
    runAction(button.dataset.action, button);
  });
  async function runAction(action, button) {
    if (!state || closing) return;
    const index = state.index, indices = [...state.indices], wasViewer = Boolean(state.viewerMenu);
    if (action === 'back') { renderMain(); return; }
    if (action === 'album-cover') {await closeMenu();try{await window.PhotoManage.setCover(index);announce('Обложка альбома обновлена');}catch(e){announce(e.message);}return;}
    if (action === 'albums') { if(window.PhotoManage){await closeMenu();window.PhotoManage.pickAlbum(indices);}else renderAlbums(); return; }
    if (action === 'information') { renderInformation(); return; }
    if (action === 'metadata-date' || action === 'metadata-location') {
      await closeMenu();
      window.PhotoMetadata.openEditor(action === 'metadata-date' ? 'date' : 'location', indices);
      return;
    }
    if (action === 'select-all') { await closeMenu(); $('#selectAll').click(); return; }
    if (action === 'slideshow') {
      await closeMenu();
      if (wasViewer) { stopSlideshow(); enterCinema(); scheduleSlide(); }
      else startSelectedViewer(indices, true);
      return;
    }
    if (action === 'share' || action === 'save') {
      const opened = state;
      if(action==='save'&&!navigator.share){
        button.disabled=true;
        try{
          for(const index of indices){const file=await mediaFile(index),url=URL.createObjectURL(file),link=document.createElement('a');link.href=url;link.download=file.name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);}
          if(state===opened)await closeMenu();announce('Файлы переданы в загрузки браузера');
        }catch{announce('Не удалось сохранить файлы. Попробуй ещё раз.');}finally{button.disabled=false;}
        return;
      }
      if (await shareMedia(indices, button) && state === opened) await closeMenu();
      return;
    }
    if (action === 'copy') {
      try {
        if (indices.length > 1) {
          if (!navigator.clipboard?.writeText) { announce('Копирование недоступно в этом браузере'); return; }
          await navigator.clipboard.writeText(indices.map(i => new URL(isVideo(i) ? videoSource(i) : photo(i), location.href).href).join('\n'));
          await closeMenu(); announce(`Скопированы ссылки на выбранные файлы (${indices.length})`); return;
        }
        if (isVideo(index) || !navigator.clipboard?.write || !window.ClipboardItem) {
          announce('Копирование этого файла не поддерживается браузером'); return;
        }
        // Pass a promise directly to ClipboardItem to retain the iOS user activation.
        const png = fetch(photo(index)).then(r => { if (!r.ok) throw new Error(); return r.blob(); }).then(blob => new Promise((resolve, reject) => {
          const img = new Image(), url = URL.createObjectURL(blob);
          img.onload = () => { const canvas = document.createElement('canvas'); canvas.width = img.naturalWidth; canvas.height = img.naturalHeight; canvas.getContext('2d').drawImage(img, 0, 0); URL.revokeObjectURL(url); canvas.toBlob(result => result ? resolve(result) : reject(new Error()), 'image/png'); };
          img.onerror = () => { URL.revokeObjectURL(url); reject(new Error()); }; img.src = url;
        }));
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': png })]);
        await closeMenu(); announce('Фото скопировано');
      } catch { announce('Браузер не разрешил копирование фотографии'); }
      return;
    }
    // Animate back to the original thumbnail before changing the grid.
    await closeMenu();
    if (window.PhotoVault && ['hide','delete','restore','duplicate'].includes(action)) {
      try {
        const operation = action === 'hide' ? (indices.every(i => hiddenItems.has(i)) ? 'unhide' : 'hide') : action === 'delete' ? 'trash' : action;
        if (!await window.PhotoVault.mutate(operation, indices)) return;
        if (wasViewer && ['hide','delete','restore'].includes(action)) await closeViewer();
        refreshContextGrid(); updateSelectionUI();
        if (wasViewer && !viewer.classList.contains('hidden')) { if(action==='duplicate'){viewerSequence.push(ids.length-1);$('#filmstrip').replaceChildren()}renderViewer(false); }
      } catch(error) { announce(error.message); }
      return;
    }
    if (wasViewer && (action === 'hide' || action === 'delete' || action === 'restore')) await closeViewer();
    if(action==='favorite'&&window.PHOTO_ACCOUNT?.id){try{await window.PhotoVault.favorite(indices,!indices.every(i=>favorites.has(i)));refreshContextGrid();if(wasViewer)renderViewer(false)}catch(error){announce(error.message)}return;}
    if (action === 'favorite') { const remove = indices.every(i => favorites.has(i)); indices.forEach(i => remove ? favorites.delete(i) : favorites.add(i)); }
    if (action === 'hide') { const remove = indices.every(i => hiddenItems.has(i)); indices.forEach(i => remove ? hiddenItems.delete(i) : hiddenItems.add(i)); }
    if (action === 'delete') indices.forEach(i => { deleted.add(i); hiddenItems.delete(i); });
    if (action === 'restore') indices.forEach(i => deleted.delete(i));
    if (action === 'duplicate') {
      indices.forEach(i => { ids.push(ids[i]); if(!libraryVirtual)$('#grid').append(makeTile(ids.length - 1)); });
      announce(`Созданы дубликаты в этом сеансе: ${indices.length}`);
    }
    if (action.startsWith('album-')) {
      const name = ['Путешествия', 'Природа', 'Избранное'][Number(action.slice(6))];
      if (name === 'Избранное') indices.forEach(i => favorites.add(i));
      else { if (!albumExtras.has(name)) albumExtras.set(name, new Set()); indices.forEach(i => albumExtras.get(name).add(i)); }
      announce(`Добавлено: ${name}`);
    }
    refreshContextGrid();
    updateSelectionUI();
    if (wasViewer && !viewer.classList.contains('hidden')) {
      if (action === 'duplicate') { viewerSequence.push(ids.length - 1); $('#filmstrip').replaceChildren(); }
      renderViewer(false);
    }
  }
  overlay.addEventListener('click', async e => {
    if (e.target.closest('.photo-context-close')) { await closeMenu(); if (selecting) $('#select').click(); return; }
    if (e.target.closest('.photo-context-panel')) return;
    if (e.target.closest('.photo-context-preview') && state && !closing) {
      const { index, tile } = state;
      await closeMenu();
      openViewer(index, tile);
    } else closeMenu();
  });
  document.addEventListener('touchstart', e => {
    if (e.touches.length !== 1) { cancelHold(); return; }
    const tile = e.target.closest('.grid .tile');
    if (!tile) return;
    startHold(tile, e.touches[0].clientX, e.touches[0].clientY);
  }, { passive: true });
  document.addEventListener('touchmove', e => {
    if (e.touches.length !== 1) { cancelHold(); return; }
    moveHold(e.touches[0].clientX, e.touches[0].clientY);
    if (state && !e.target.closest('.photo-context-panel')) e.preventDefault();
  }, { passive: false });
  document.addEventListener('touchend', cancelHold, { passive: true });
  document.addEventListener('touchcancel', cancelHold, { passive: true });
  document.addEventListener('pointerdown', e => {
    if (e.pointerType === 'touch' || e.button !== 0) return;
    const tile = e.target.closest('.grid .tile');
    if (tile) startHold(tile, e.clientX, e.clientY);
  });
  document.addEventListener('pointermove', e => { if (e.pointerType !== 'touch') moveHold(e.clientX, e.clientY); });
  document.addEventListener('pointerup', e => { if (e.pointerType !== 'touch') cancelHold(); });
  document.addEventListener('pointercancel', cancelHold);
  document.addEventListener('scroll', cancelHold, true);
  document.addEventListener('visibilitychange', () => { if (document.hidden) { cancelHold(); closeMenu(); } });
  document.addEventListener('click', e => {
    if (e.target.closest('.grid .tile') && (state || closing || Date.now() < suppressClickUntil)) {
      e.preventDefault(); e.stopImmediatePropagation();
    }
  }, true);
  document.addEventListener('contextmenu', e => {
    const tile = e.target.closest('.grid .tile');
    if (!tile) return;
    e.preventDefault();
    const index = Number(tile.dataset.index);
    // Ctrl+right-click acts on the whole selection, Shift+right-click takes the range first.
    if (e.shiftKey) { selectRangeTo(index, e.ctrlKey || e.metaKey); openSelectionMenu(); return; }
    if (e.ctrlKey || e.metaKey) {
      if (!selecting) { enterSelectionMode(); selectOnly(index); }
      else if (!chosen.has(index)) toggleChosen(index);
      openSelectionMenu(); return;
    }
    if (selecting && !busy && viewer.classList.contains('hidden')) { if (!chosen.has(index)) selectOnly(index); openSelectionMenu(); return; }
    if (!selecting && !busy && viewer.classList.contains('hidden')) openMenu(tile);
  });
  document.addEventListener('keydown', e => {
    if (!state) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); closeMenu(); }
    if (e.key === 'Tab') {
      const buttons = [...panel.querySelectorAll('button:not(:disabled),textarea')];
      const first = buttons[0], last = buttons[buttons.length - 1];
      if (e.shiftKey && (document.activeElement === first || document.activeElement === panel)) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    }
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') e.stopImmediatePropagation();
  }, true);

  // Selection controls use the same menu and action handlers as an individual photo.
  function syncSelectionControls() {
    const count = chosen.size;
    $('#selectionBar').classList.toggle('hidden', !selecting);
    $('#selectionMore').classList.toggle('hidden', !selecting);globalThis.PhotoAlbums?.selectionChanged();
    document.querySelector('.bottom').inert = selecting;
    $('#selectionPreview').textContent = `Показать выбранные (${count})`;
    for (const id of ['selectionShare', 'selectionPreview', 'selectionDelete']) $('#' + id).disabled = !count;$('#selectionDelete').disabled ||= [...chosen].some(i=>window.PhotoVault?.state(i)==='shared');
    $('#selectionMore').setAttribute('aria-label', `Действия с выбранными: ${count}`);
    if (!selecting && state?.bulk) closeMenu();
  }
  let slideshowTimer;
  function stopSlideshow() { clearTimeout(slideshowTimer); slideshowTimer = null; }
  function scheduleSlide() {
    const media = $('#demoVideo');
    if (isVideo(current)) media.play().catch(() => {});
    const delay = isVideo(current) && Number.isFinite(media.duration) ? Math.max(4000, media.duration * 1000 + 300) : 4000;
    slideshowTimer = setTimeout(async () => {
      if (document.hidden || viewer.classList.contains('hidden') || !viewer.classList.contains('cinema')) { stopSlideshow(); return; }
      if (!busy && !gesture) {
        const position = viewerSequence.indexOf(current), next = viewerSequence[(position + 1) % viewerSequence.length];
        if (next !== undefined && next !== current) await slideTo(next);
      }
      scheduleSlide();
    }, delay);
  }
  async function startSelectedViewer(indices, slideshow = false) {
    if (!indices.length || busy) return;
    stopSlideshow();
    const source = selectionGrid().querySelector(`[data-index="${indices[0]}"]`);
    await openViewer(indices[0], source, indices);
    if (slideshow && !viewer.classList.contains('hidden')) { enterCinema(); scheduleSlide(); }
  }
  new MutationObserver(() => {
    if (viewer.classList.contains('hidden') || !viewer.classList.contains('cinema')) stopSlideshow();
  }).observe(viewer, { attributes: true, attributeFilter: ['class'] });
  document.addEventListener('photo-selection-change', syncSelectionControls);
  document.addEventListener('visibilitychange', () => { if (document.hidden) stopSlideshow(); });
  window.addEventListener('resize', positionSelectionMenu);
  window.visualViewport?.addEventListener('resize', positionSelectionMenu);
  $('#selectionMore').onclick = openSelectionMenu;
  $('#selectionPreview').onclick = () => startSelectedViewer([...chosen]);
  $('#selectionShare').onclick = () => {
    openSelectionMenu();
    runAction('share', $('#selectionShare'));
  };
  $('#selectionDelete').onclick = () => {
    openSelectionMenu();
    if (!state) return;
    panel.innerHTML = `<p class="photo-context-heading">Удалить выбранные (${state.indices.length})?</p><p class="photo-context-explanation">Их можно будет восстановить в разделе «Удалены недавно».</p>${row('delete', 'trash', 'Удалить выбранные', false, true)}${row('dismiss', 'back', 'Отмена')}`;
  };
  $('#more').onclick = openViewerMenu;
  $('#more').setAttribute('aria-label', 'Действия с фотографией');
  $('#more').setAttribute('aria-haspopup', 'dialog');
  $('#share').onclick = () => shareMedia([current], $('#share'));
  window.PhotoActions = { slideshow:indices=>startSelectedViewer(indices,true), clear(){shareCache.clear();if(state){state.tile?.classList.remove('context-source');overlay.classList.add('hidden');document.body.style.overflow=state.overflow;document.querySelector('.app').inert=false;state=null;closing=false}image.removeAttribute('src')}, prepare(index) { mediaFile(index).catch(() => {}); } };
  syncSelectionControls();
})();
