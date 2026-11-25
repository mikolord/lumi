(() => {
  const storageKey = 'photo-demo-metadata-v1' + (window.PHOTO_ACCOUNT?.id ? ':' + window.PHOTO_ACCOUNT.id : '');
  let edits = {};
  try { edits = JSON.parse(localStorage.getItem(storageKey) || '{}'); } catch {}
  if (!edits || Array.isArray(edits) || typeof edits !== 'object') edits = {};
  const key = index => `${index}:${ids[index]}`;
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const glyph = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name]}</svg>`;
  function get(index) {
    const source = isVideo(index) ? videoSource(index) : photo(index);
    return { ...(window.PhotoVault?.metadata(index) || window.PHOTO_FILE_METADATA?.[source] || { name: source.split('/').pop(), format: isVideo(index) ? 'MP4' : 'JPEG' }), ...(edits[key(index)] || {}) };
  }
  function update(indices, patch) {
    for (const index of indices) {
      const entry = { ...(edits[key(index)] || {}) };
      for (const field of ['takenAt', 'location', 'latitude', 'longitude', 'caption', 'keywords']) {
        if (!(field in patch)) continue;
        if (patch[field] === undefined) delete entry[field];
        else entry[field] = patch[field];
      }
      edits[key(index)] = entry;
    }
    let saved = true;
    try { localStorage.setItem(storageKey, JSON.stringify(edits)); } catch { saved = false; }
    if (infoOpen) renderInfo(current);
    return saved;
  }
  function dateLabel(value) {
    if (!value) return 'Дата съёмки неизвестна';
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return 'Дата съёмки неизвестна';
    return date.toLocaleDateString('ru-RU', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' }) + '<br>в ' + date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  }
  function sizeLabel(bytes) {
    if (!Number.isFinite(bytes)) return 'Размер неизвестен';
    return bytes >= 1e6 ? `${(bytes / 1e6).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} МБ` : `${(bytes / 1000).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} КБ`;
  }
  function locationLabel(data) {
    if (data.location) return escape(data.location);
    if (Number.isFinite(data.latitude) && Number.isFinite(data.longitude)) return `${data.latitude.toFixed(5)}, ${data.longitude.toFixed(5)}`;
    return 'Добавить геопозицию…';
  }
  const pane = document.createElement('section');
  pane.className = 'metadata-pane hidden';
  pane.setAttribute('aria-label', 'Информация о медиафайле');
  viewer.append(pane);
  let infoOpen = false, displayedIndex = null;
  function renderInfo(index) {
    displayedIndex = index;
    const data = get(index);
    const resolution = data.width && data.height ? `${(data.width * data.height / 1e6).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} Мпикс · ${data.width} × ${data.height}` : 'Разрешение неизвестно';
    const exposure = data.exposure ? data.exposure < 1 ? `1/${Math.round(1 / data.exposure)} с` : `${data.exposure} с` : '—';
    const duration = Number.isFinite(data.duration) ? ` · ${formatMediaDuration(data.duration,true)}` : '';
    pane.innerHTML = `<button class="metadata-dismiss glass circle" data-meta-action="close" aria-label="Закрыть информацию"><svg class="icon" viewBox="0 0 24 24"><path d="m6 6 12 12M18 6 6 18"/></svg></button>
      <button class="metadata-preview" data-meta-action="close" aria-label="Вернуться к просмотру"><img src="${photo(index)}" alt="" draggable="false"></button>
      <div class="metadata-content">
        <label class="metadata-caption-label"><span class="sr-only">Подпись</span><input class="metadata-caption" maxlength="500" placeholder="Добавить подпись" value="${escape(data.caption)}"></label>
        <div class="metadata-card">
          <div class="metadata-date"><div>${dateLabel(data.takenAt)}</div><button data-meta-action="date">Изменить</button></div>
          <div class="metadata-filename">${glyph(isVideo(index) ? 'video' : 'photos')}<span>${escape(data.name)}</span></div>
          <div class="metadata-camera"><span>${escape(data.camera || 'Нет сведений о камере')}</span><span class="metadata-format">${escape(data.format)}</span></div>
          <div class="metadata-details"><div>${escape(data.lens || 'Нет сведений об объективе')}</div><div>${resolution} · ${sizeLabel(data.bytes)}${duration}</div></div>
          <div class="metadata-exposure"><span>${data.iso ? 'ISO ' + escape(data.iso) : '—'}</span><span>${data.focalLength ? escape(data.focalLength) + ' мм' : '—'}</span><span>${data.aperture ? 'ƒ/' + escape(data.aperture) : '—'}</span><span>${exposure}</span></div>
        </div>
        <button class="metadata-field" data-meta-action="location">${glyph('eye')}<span>${locationLabel(data)}</span></button>
        <button class="metadata-field" data-meta-action="keywords">${glyph('info')}<span>${escape(data.keywords || 'Добавить ключевые слова')}</span></button>
      </div>`;
  }
  function hideInfo() {
    infoOpen = false;
    viewer.classList.remove('showing-info');
    pane.classList.add('hidden');
    $('#info').setAttribute('aria-expanded', 'false');
    $('#info').classList.remove('active');
    if (viewer.classList.contains('hidden')) displayedIndex = null;
  }
  function toggle(index) {
    if (infoOpen) { hideInfo(); return; }
    if (viewer.classList.contains('cinema')) exitCinema();
    $('#demoVideo').pause();
    renderInfo(index); infoOpen = true;
    pane.scrollTop = 0;
    viewer.classList.add('showing-info');
    pane.classList.remove('hidden');
    $('#info').setAttribute('aria-expanded', 'true');
    $('#info').classList.add('active');
    if (!matchMedia('(prefers-reduced-motion: reduce)').matches) pane.animate([{ opacity: 0, transform: 'translateY(24px)' }, { opacity: 1, transform: 'none' }], { duration: 340, easing: 'cubic-bezier(.22,.75,.2,1)' });
  }
  pane.addEventListener('click', e => {
    const button = e.target.closest('[data-meta-action]');
    if (!button) return;
    if (button.dataset.metaAction === 'close') hideInfo();
    else openEditor(button.dataset.metaAction, [displayedIndex]);
  });
  pane.addEventListener('change', e => {
    if (e.target.matches('.metadata-caption')) {
      if(window.PhotoVault?.state(displayedIndex)==='shared')return;
      const scroll = pane.scrollTop;
      update([displayedIndex], { caption: e.target.value.trim() });
      pane.scrollTop = scroll;
    }
  });
  new MutationObserver(() => { if (infoOpen && viewer.classList.contains('hidden')) hideInfo(); }).observe(viewer, { attributes: true, attributeFilter: ['class'] });

  const editor = document.createElement('div');
  editor.className = 'metadata-editor hidden';
  editor.innerHTML = '<div class="metadata-editor-backdrop"></div><section class="metadata-editor-sheet" role="dialog" aria-modal="true" tabindex="-1"></section>';
  document.body.append(editor);
  const sheet = editor.querySelector('section');
  let editState = null;
  function openEditor(mode, indices) {
    if(indices.some(i=>window.PhotoVault?.state(i)==='shared')){toast('Общий альбом доступен только для просмотра.');return;}
    if (!indices.length) return;
    const previous=editState;
    const data = get(indices[0]), same = field => indices.every(i => get(i)[field] === data[field]) ? data[field] : '';
    editState = { mode, indices: [...indices], focus: previous?.focus||document.activeElement, overflow: previous?.overflow??document.body.style.overflow, inert: previous?.inert??document.querySelector('.app').inert };
    const title = mode === 'date' ? 'Дата и время' : mode === 'location' ? 'Геопозиция' : 'Ключевые слова';
    sheet.setAttribute('aria-label', title);
    sheet.innerHTML = `<form><div class="metadata-editor-header"><button type="button" data-editor-action="cancel">Отмена</button><h2>${title}</h2><button type="submit">Готово</button></div>
      ${indices.length > 1 ? `<p class="metadata-editor-count">Для выбранных объектов: ${indices.length}</p>` : ''}
      <div class="metadata-editor-fields">${mode === 'date' ? `<label>Дата и время съёмки<input name="takenAt" type="datetime-local" value="${escape((same('takenAt') || '').slice(0, 16))}" required></label>` : mode === 'location' ?
        `<label>Название места<input name="location" placeholder="Город или место" maxlength="200" value="${escape(same('location'))}"></label><div class="metadata-coordinates"><label>Широта<input name="latitude" type="number" min="-90" max="90" step="any" placeholder="−90…90" value="${escape(same('latitude'))}"></label><label>Долгота<input name="longitude" type="number" min="-180" max="180" step="any" placeholder="−180…180" value="${escape(same('longitude'))}"></label></div>` :
        `<label>Ключевые слова<input name="keywords" maxlength="500" placeholder="Через запятую" value="${escape(same('keywords'))}"></label>`}
      <p class="metadata-editor-error" role="alert"></p>
      <button type="button" class="metadata-reset" data-editor-action="reset">Вернуть исходные данные</button>
      <p class="metadata-editor-note">Изменения сохраняются в этом браузере. Исходный файл не изменяется.</p></div></form>`;
    window.PhotoSheetMotion.hold(sheet);
    editor.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    document.querySelector('.app').inert = true;
    sheet.focus({ preventScroll: true });
    window.PhotoSheetMotion.show(sheet,editor.querySelector('.metadata-editor-backdrop'));
  }
  async function closeEditor() {
    if (!editState||editState.closing) return;
    const old = editState;old.closing=true;
    await window.PhotoSheetMotion.hide(sheet,editor.querySelector('.metadata-editor-backdrop'));
    if(editState!==old)return;
    editor.classList.add('hidden'); editState = null;
    document.body.style.overflow = old.overflow;
    document.querySelector('.app').inert = old.inert;
    old.focus?.isConnected && old.focus.focus({ preventScroll: true });
    window.PhotoSheetMotion.release(sheet);
  }
  window.PhotoSheetGestures.attach(sheet, { dismiss: closeEditor, backdrop: editor.querySelector('.metadata-editor-backdrop') });
  sheet.addEventListener('submit', e => {
    e.preventDefault();
    if (!editState) return;
    const values = new FormData(e.target), { mode, indices } = editState;
    let patch;
    if (mode === 'date') {
      const value = String(values.get('takenAt') || '');
      if (!value || !Number.isFinite(new Date(value).getTime())) return;
      patch = { takenAt: value };
    } else if (mode === 'location') {
      const lat = String(values.get('latitude') || ''), lon = String(values.get('longitude') || '');
      if (Boolean(lat) !== Boolean(lon)) { sheet.querySelector('[role=alert]').textContent = 'Укажи обе координаты или только название места.'; return; }
      if (lat && (!Number.isFinite(Number(lat)) || !Number.isFinite(Number(lon)) || Math.abs(Number(lat)) > 90 || Math.abs(Number(lon)) > 180)) return;
      patch = { location: String(values.get('location') || '').trim(), latitude: lat ? Number(lat) : null, longitude: lon ? Number(lon) : null };
    } else patch = { keywords: String(values.get('keywords') || '').trim() };
    const saved = update(indices, patch);
    if (!saved) { sheet.querySelector('[role=alert]').textContent = 'Браузер не разрешил сохранение. Изменения доступны до закрытия страницы.'; return; }
    closeEditor();
  });
  editor.addEventListener('click', e => {
    const action = e.target.closest('[data-editor-action]')?.dataset.editorAction;
    if (action === 'reset' && editState) {
      const fields = editState.mode === 'date' ? ['takenAt'] : editState.mode === 'location' ? ['location', 'latitude', 'longitude'] : ['keywords'];
      update(editState.indices, Object.fromEntries(fields.map(field => [field, undefined]))); closeEditor();
    } else if (action === 'cancel' || e.target.classList.contains('metadata-editor-backdrop')) closeEditor();
  });
  document.addEventListener('keydown', e => {
    if (editState) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); closeEditor(); }
      if (e.key === 'Tab') {
        const items = [...sheet.querySelectorAll('button,input')], first = items[0], last = items.at(-1);
        if (e.shiftKey && (document.activeElement === first || document.activeElement === sheet)) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
      if (e.key.startsWith('Arrow')) e.stopImmediatePropagation();
    } else if (infoOpen && e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); hideInfo(); }
  }, true);
  window.PhotoMetadata = { get, update, toggle, hide: hideInfo, lock(){hideInfo();closeEditor();pane.replaceChildren();sheet.replaceChildren();displayedIndex=null}, openEditor, refresh(index) {
    if(!infoOpen)return;if(displayedIndex!==index){renderInfo(index);return;}
    const data=get(index),resolution=data.width&&data.height?`${(data.width*data.height/1e6).toLocaleString('ru-RU',{maximumFractionDigits:1})} Мпикс · ${data.width} × ${data.height}`:'Разрешение неизвестно';
    pane.querySelector('.metadata-details>div:last-child').textContent=resolution+' · '+sizeLabel(data.bytes)+(Number.isFinite(data.duration)?' · '+formatMediaDuration(data.duration,true):'');
    pane.querySelector('.metadata-date>div').innerHTML=dateLabel(data.takenAt);pane.querySelector('.metadata-filename>span').textContent=data.name||'';pane.querySelector('.metadata-format').textContent=data.format||'';
    const image=pane.querySelector('.metadata-preview img'),url=photo(index);if(image.getAttribute('src')!==url)image.src=url;
  } };
})();
