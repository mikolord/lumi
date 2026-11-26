const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert');
const { JSDOM } = require(path.join(process.env.TEMP, 'photo-design-test-tools/node_modules/jsdom'));
const root = path.join(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root, 'index.html'), 'utf8'), {
  url: 'https://foto.mira5.netcraze.club/', runScripts: 'outside-only', pretendToBeVisual: true,
});
const w = dom.window, context = dom.getInternalVMContext();
// A desktop pointer: the desktop rules are the ones under test.
w.matchMedia = query => ({ matches: /pointer:\s*fine/.test(query) || /min-width:\s*1000px/.test(query), addEventListener() {} });
w.scrollTo = () => {};
w.scrollBy = () => {};
w.ResizeObserver = class { observe() {} };
w.HTMLElement.prototype.scrollTo = () => {};
w.HTMLElement.prototype.setPointerCapture = () => {};
w.HTMLElement.prototype.getBoundingClientRect = () => ({ left: 0, top: 0, right: 180, bottom: 50, width: 180, height: 50 });
w.HTMLElement.prototype.getAnimations = () => [];
w.HTMLElement.prototype.animate = () => ({ finished: Promise.resolve(), cancel() {} });
w.HTMLMediaElement.prototype.pause = () => {};
w.HTMLMediaElement.prototype.load = () => {};
w.HTMLMediaElement.prototype.play = () => Promise.resolve();
w.fetch = async url => ({ ok: true, blob: async () => new w.Blob([fs.readFileSync(path.join(root, String(url)))]) });
for (const file of ['app.js', 'sheet-gestures.js', 'avatar-crop.js', 'metadata-data.js', 'metadata.js', 'context-menu.js', 'collections-ui.js', 'trash-album.js'])
  vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), context);
const doc = w.document;
const evaluate = code => vm.runInContext(code, context);
const wait = () => new Promise(resolve => setTimeout(resolve, 20));
const tile = index => doc.querySelector(`#grid .tile[data-index="${index}"]`);
const menu = () => doc.querySelector('.photo-context');
function event(target, type, properties = {}) {
  const e = new w.Event(type, { bubbles: true, cancelable: true });
  Object.assign(e, properties); target.dispatchEvent(e); return e;
}
(async () => {
  const total = evaluate('getVisibleLibraryItems().length');
  assert(total > 10, 'the demo library has enough photos for a range');

  // Ctrl+A takes everything, and it also switches the library into selection mode.
  event(doc, 'keydown', { key: 'a', ctrlKey: true });
  assert(evaluate('selecting'), 'Ctrl+A enters selection mode');
  assert.equal(evaluate('chosen.size'), total, 'Ctrl+A selects every visible photo');
  assert(doc.querySelector('#date').textContent.includes(String(total)));
  assert(!doc.querySelector('#selectAll').classList.contains('hidden'), 'the select-all button is offered on a desktop');

  // Ctrl+click takes one photo out of the selection.
  event(tile(3), 'click', { ctrlKey: true });
  assert.equal(evaluate('chosen.size'), total - 1, 'Ctrl+click removes a single photo');
  assert(!evaluate('chosen.has(3)'));

  // A plain click keeps only the clicked photo, and Shift+click extends the range.
  event(tile(2), 'click', {});
  assert.equal(evaluate('chosen.size'), 1, 'a plain click selects one photo');
  event(tile(6), 'click', { shiftKey: true });
  assert.equal(evaluate('chosen.size'), 5, 'Shift+click selects the range from the anchor');
  assert(evaluate('chosen.has(3)') && evaluate('chosen.has(6)'));

  // Ctrl+right-click opens the actions of the whole selection.
  event(tile(6), 'contextmenu', { ctrlKey: true });
  await wait();
  assert(!menu().classList.contains('hidden'), 'Ctrl+right-click opens the menu');
  assert(menu().classList.contains('photo-context-bulk'), 'Ctrl+right-click acts on the selection');
  assert(doc.querySelector('.photo-context-panel').getAttribute('aria-label').includes('5'));
  event(doc, 'keydown', { key: 'Escape' }); await wait();
  assert(menu().classList.contains('hidden'));

  // Shift+right-click selects the range and offers its actions.
  event(tile(2), 'click', {});
  event(tile(8), 'contextmenu', { shiftKey: true });
  await wait();
  assert.equal(evaluate('chosen.size'), 7, 'Shift+right-click selects the range first');
  assert(!menu().classList.contains('hidden'), 'Shift+right-click opens the menu');
  event(doc, 'keydown', { key: 'Escape' }); await wait();

  // Ctrl+wheel changes the icon size.
  assert.equal(evaluate('size'), 'month');
  event(doc.querySelector('#grid'), 'wheel', { ctrlKey: true, deltaY: -120 });
  assert.equal(evaluate('size'), 'all', 'Ctrl+wheel enlarges the icons');
  event(doc.querySelector('#grid'), 'wheel', { ctrlKey: true, deltaY: 120 });
  assert.equal(evaluate('size'), 'month', 'Ctrl+wheel shrinks the icons back');
  const plainWheel = event(doc.querySelector('#grid'), 'wheel', { deltaY: -120 });
  assert(!plainWheel.defaultPrevented, 'a plain wheel still scrolls the library');

  // The desktop sheet keeps the select-all button and a visible timeline handle.
  const css = fs.readFileSync(path.join(root, 'style.css'), 'utf8');
  assert(/\.header\.is-selecting #selectAll\{display:inline-flex!important\}/.test(css), 'the desktop shows the select-all button');
  assert(/\.library-timeline-trigger\{[^}]*opacity:1/.test(css), 'the desktop timeline handle is visible');
  assert(/\.library-timeline-handle svg\{/.test(css), 'the timeline handle draws its own icon');
  const timeline = fs.readFileSync(path.join(root, 'timeline-ui.js'), 'utf8');
  assert(timeline.includes('library-timeline-handle'), 'the timeline trigger carries a handle icon');

  console.log('Desktop: Windows-style selection, Ctrl+wheel density and a visible timeline handle');
  dom.window.close();
})().catch(error => { console.error(error); process.exit(1); });
