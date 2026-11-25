// The square image saved here is displayed through the circular avatar mask.
(() => {
  const overlay = document.createElement('div');
  overlay.className = 'avatar-crop hidden';
  overlay.innerHTML = `<section class="avatar-crop-sheet" role="dialog" aria-modal="true" aria-label="Обрезать фотографию профиля" tabindex="-1">
    <div class="avatar-crop-header"><button data-crop-action="cancel">Отмена</button><h2>Фото профиля</h2><button data-crop-action="save">Готово</button></div>
    <p class="avatar-crop-hint">Перемещай фото и меняй масштаб щипком</p>
    <div class="avatar-crop-stage"><img alt="Предпросмотр аватара" draggable="false"><div class="avatar-crop-mask" aria-hidden="true"></div></div>
    <label class="avatar-crop-zoom"><span aria-hidden="true">−</span><input type="range" min="1" max="4" step="0.01" value="1" aria-label="Масштаб фотографии"><span aria-hidden="true">+</span></label>
    <button class="avatar-crop-reset" data-crop-action="reset">По центру</button><p class="avatar-crop-error" role="alert"></p>
  </section>`;
  document.body.append(overlay);
  const sheet = overlay.querySelector('section'), stage = overlay.querySelector('.avatar-crop-stage'), image = stage.querySelector('img'), zoom = overlay.querySelector('input');
  const pointers = new Map();
  let state = null;
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  function draw() {
    if (!state) return;
    const { naturalWidth: w, naturalHeight: h } = state.image;
    const side = stage.getBoundingClientRect().width || 280;
    if (state.side && side !== state.side) { state.x *= side / state.side; state.y *= side / state.side; }
    state.side = side; state.base = Math.max(side / w, side / h);
    const width = w * state.base * state.zoom, height = h * state.base * state.zoom;
    state.x = clamp(state.x, -(width - side) / 2, (width - side) / 2);
    state.y = clamp(state.y, -(height - side) / 2, (height - side) / 2);
    Object.assign(image.style, { width: `${width}px`, height: `${height}px`, transform: `translate(-50%,-50%) translate(${state.x}px,${state.y}px)` });
    zoom.value = state.zoom;
  }
  function baseline() {
    if (!state) return;
    const values = [...pointers.values()];
    if (values.length >= 2) {
      const [a, b] = values, rect = stage.getBoundingClientRect();
      const cx = (a.x + b.x) / 2 - rect.left - rect.width / 2, cy = (a.y + b.y) / 2 - rect.top - rect.height / 2;
      state.gesture = { distance: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)), zoom: state.zoom, anchorX: (cx - state.x) / state.zoom, anchorY: (cy - state.y) / state.zoom };
    } else if (values.length) state.gesture = { pointer: values[0], x: state.x, y: state.y };
    else state.gesture = null;
  }
  function setZoom(value) {
    if (!state) return;
    const next = clamp(Number(value), 1, 4), ratio = next / state.zoom;
    state.x *= ratio; state.y *= ratio; state.zoom = next;
    draw(); baseline();
  }
  stage.addEventListener('pointerdown', e => {
    if (!state || (e.pointerType === 'mouse' && e.button !== 0)) return;
    e.preventDefault(); stage.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY }); baseline();
  });
  stage.addEventListener('pointermove', e => {
    if (!state || !pointers.has(e.pointerId)) return;
    e.preventDefault(); pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const values = [...pointers.values()], g = state.gesture;
    if (!g) return;
    if (values.length >= 2 && g.distance) {
      const [a, b] = values, rect = stage.getBoundingClientRect();
      state.zoom = clamp(g.zoom * Math.hypot(a.x - b.x, a.y - b.y) / g.distance, 1, 4);
      state.x = (a.x + b.x) / 2 - rect.left - rect.width / 2 - g.anchorX * state.zoom;
      state.y = (a.y + b.y) / 2 - rect.top - rect.height / 2 - g.anchorY * state.zoom;
    } else if (g.pointer) {
      state.x = g.x + values[0].x - g.pointer.x; state.y = g.y + values[0].y - g.pointer.y;
    }
    draw();
  });
  function release(e) { pointers.delete(e.pointerId); baseline(); }
  ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(name => stage.addEventListener(name, release));
  zoom.addEventListener('input', () => setZoom(zoom.value));
  stage.addEventListener('wheel', e => { if (state) { e.preventDefault(); setZoom(state.zoom * Math.exp(-e.deltaY * .002)); } }, { passive: false });
  async function finish(result) {
    if (!state||state.closing) return;
    const old = state;old.closing=true;
    await window.PhotoSheetMotion.hide(sheet);
    state = null; pointers.clear();
    overlay.classList.add('hidden'); image.removeAttribute('src');
    URL.revokeObjectURL(old.url);
    if (old.parent) old.parent.inert = old.parentInert;
    old.focus?.isConnected && old.focus.focus({ preventScroll: true });
    window.PhotoSheetMotion.release(sheet);
    old.resolve(result);
  }
  overlay.addEventListener('click', e => {
    const action = e.target.closest('[data-crop-action]')?.dataset.cropAction;
    if (!state) return;
    if (action === 'cancel') finish(null);
    if (action === 'reset') { state.x = state.y = 0; state.zoom = 1; draw(); baseline(); }
    if (action === 'save') {
      try {
        const scale = state.base * state.zoom, side = state.side / scale;
        const sx = (state.image.naturalWidth - side) / 2 - state.x / scale;
        const sy = (state.image.naturalHeight - side) / 2 - state.y / scale;
        const canvas = document.createElement('canvas'); canvas.width = canvas.height = 384;
        const context = canvas.getContext('2d'); context.fillStyle = '#fff'; context.fillRect(0, 0, 384, 384);
        context.drawImage(state.image, sx, sy, side, side, 0, 0, 384, 384);
        const result = canvas.toDataURL('image/jpeg', .86);
        if (!result.startsWith('data:image/jpeg;base64,') || result.length >= 600000) throw new Error('Invalid crop');
        finish(result);
      } catch { overlay.querySelector('.avatar-crop-error').textContent = 'Не удалось сохранить обрезку. Попробуй ещё раз.'; }
    }
  });
  document.addEventListener('keydown', e => {
    if (!state) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); finish(null); }
    if (e.key === 'Tab') {
      const items = [...sheet.querySelectorAll('button,input')], first = items[0], last = items.at(-1);
      if (e.shiftKey && (document.activeElement === first || document.activeElement === sheet)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  }, true);
  window.addEventListener('resize', draw);
  window.PhotoSheetGestures.attach(sheet, { dismiss: () => finish(null), handleOnly: true });
  window.AvatarCrop = { async open(file) {
    if (state) finish(null);
    const url = URL.createObjectURL(file), source = new Image();
    try {
      await new Promise((resolve, reject) => { source.onload = resolve; source.onerror = reject; source.src = url; });
      if (!source.naturalWidth || !source.naturalHeight) throw new Error('Empty image');
    } catch (error) { URL.revokeObjectURL(url); throw error; }
    return new Promise(resolve => {
      const parent = document.querySelector('.collections-modal');
      state = { image: source, url, resolve, zoom: 1, x: 0, y: 0, focus: document.activeElement, parent, parentInert: parent?.inert };
      if (parent) parent.inert = true;
      image.src = url; overlay.querySelector('.avatar-crop-error').textContent = '';
      window.PhotoSheetMotion.hold(sheet);overlay.classList.remove('hidden'); draw(); sheet.focus({ preventScroll: true });window.PhotoSheetMotion.show(sheet);
    });
  } };
})();
