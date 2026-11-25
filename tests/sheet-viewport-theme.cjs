const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const {JSDOM}=require(path.join(process.env.TEMP,'photo-design-test-tools/node_modules/jsdom'));
const root=path.join(__dirname,'..'),dom=new JSDOM('<body><main class="app"><section id="library" class="screen"></section></main><div class="collections-modal"><section class="account-sheet"></section></div><div class="manage-modal"><section class="manage-sheet"></section></div></body>',{runScripts:'outside-only',pretendToBeVisual:true});
const w=dom.window,d=w.document;w.matchMedia=()=>({matches:true});w.scrollTo=()=>{};w.HTMLElement.prototype.animate=()=>({finished:Promise.resolve(),cancel(){}});
const source=d.createElement('style');source.textContent=fs.readFileSync(path.join(root,'style.css'),'utf8');d.head.append(source);
// Evaluate the installed iPhone's dark OS media rules while forcing light in the app.
function rules(list){return [...list].map(rule=>{if(!rule.cssRules||![4,12].includes(rule.type))return rule.cssText;const condition=rule.conditionText||'';if(condition.includes('prefers-reduced-motion')||condition.includes('landscape')||condition.includes('min-width:700'))return '';return rules(rule.cssRules);}).join('\n');}
const active=d.createElement('style');active.textContent=rules(source.sheet.cssRules);d.head.append(active);d.documentElement.dataset.theme='light';
assert.strictEqual(w.getComputedStyle(d.querySelector('.app')).backgroundColor,'rgb(255, 255, 255)','Manual light must paint the actual library, even on a dark standalone device');
assert.strictEqual(w.getComputedStyle(d.documentElement).backgroundColor,'rgb(255, 255, 255)','Root canvas must follow manual light');
assert.strictEqual(w.getComputedStyle(d.documentElement).colorScheme,'light');
d.documentElement.dataset.theme='dark';assert.strictEqual(w.getComputedStyle(d.querySelector('.app')).backgroundColor,'rgb(0, 0, 0)');d.documentElement.dataset.theme='light';assert.strictEqual(w.getComputedStyle(d.querySelector('#library')).backgroundColor,'rgb(255, 255, 255)');
vm.runInContext(fs.readFileSync(path.join(root,'sheet-gestures.js'),'utf8'),dom.getInternalVMContext());
Object.defineProperty(w,'scrollY',{value:460});const app=d.querySelector('.app'),profile=d.querySelector('.account-sheet'),upload=d.querySelector('.manage-sheet');
w.PhotoSheetMotion.hold(profile);assert.notStrictEqual(d.body.style.position,'fixed','Sheet scroll lock must not fix the root body and clip its overlay children in WebKit');assert.strictEqual(app.style.position,'fixed');assert.strictEqual(app.style.top,'-460px');
w.PhotoSheetMotion.hold(upload);w.PhotoSheetMotion.release(upload);assert.strictEqual(app.style.top,'-460px');w.PhotoSheetMotion.release(profile);assert.strictEqual(app.style.position,'');
console.log('Manual light paints the library/root; sheet locking freezes only app content, with nested scroll restoration');dom.window.close();
