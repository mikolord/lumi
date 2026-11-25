const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync(path.join(__dirname, '../app.js'), 'utf8');
const handlers = {};
const classes = new Set();
const classList = { add() {}, remove() {}, contains() { return false; } };
function media() {
  return {
    style: {}, src: '', getAttribute() { return this.src; },
    animate() {
      let resolve;
      const finished = new Promise(done => { resolve = done; });
      return { finished, cancel() { resolve(); } };
    },
  };
}
const ctx = {
  busy: false, slideTransition: null, gesture: null, current: 0,
  ids: [10, 11, 12], viewerSequence: [0, 1, 2],
  viewer: { classList: { add: x => classes.add(x), remove: x => classes.delete(x) } },
  wrap: { clientWidth: 390, addEventListener: (name, fn) => { handlers[name] = fn; } },
  activePhoto: media(), nextPhoto: media(), slideGap: 66,
  originTile: null, screen: 'library', grid: { children: [{ classList }, { classList }, { classList }] },
  photo: i => `photo-${i}.jpg`, libraryTile:i=>ctx.grid.children[i], ease: 'linear',
  hideVideo() {}, updateFilmstrip() {}, centerFilmstrip() {}, renderViewer() {},
  syncVideo() {}, controlsOpacity() {}, resetPhoto() {},
  $: () => ({ classList }), performance: { now: () => 100 },
};
vm.createContext(ctx);
const start = source.includes('function finishSlideTransition()')
  ? source.indexOf('function finishSlideTransition()') : source.indexOf('async function slideTo(');
vm.runInContext(source.slice(start, source.indexOf('async function closeViewer(')), ctx);
vm.runInContext(source.slice(source.indexOf("wrap.addEventListener('touchstart'"), source.indexOf("wrap.addEventListener('touchmove'")), ctx);
ctx.slideTo(1);
assert(ctx.busy, 'The first transition should still be animating');
handlers.touchstart({ touches: [{ clientX: 260, clientY: 300 }], target: { closest: () => null } });
assert(ctx.gesture, 'A second touch must be accepted before the first animation ends');
assert.equal(ctx.current, 1, 'The new gesture must start from the destination photo');
assert(classes.has('is-gesturing'), 'Direct finger tracking must remain active');
if (typeof ctx.shouldAdvanceSwipe === 'function') {
  assert(ctx.shouldAdvanceSwipe(-35, 390, 60), 'A short fast flick should advance');
  assert(!ctx.shouldAdvanceSwipe(-15, 390, 60), 'A tiny movement should not advance');
  assert(!ctx.shouldAdvanceSwipe(-35, 390, 600), 'A short slow drag should spring back');
}
ctx.gesture = null;
ctx.slideTo(2);
handlers.touchstart({ touches: [{ clientX: 250, clientY: 300 }], target: { closest: () => null } });
assert.equal(ctx.current, 2, 'Repeated rapid input must advance from the latest photo');
Promise.resolve().then(() => Promise.resolve()).then(() => {
  assert(ctx.gesture, 'Completing an older transition must not clear the new gesture');
  assert(classes.has('is-gesturing'), 'Older animation cleanup must not disable new finger tracking');
  console.log('Rapid repeated gestures and short flicks accepted; old animation cleanup is isolated');
}).catch(error => { console.error(error); process.exitCode = 1; });
