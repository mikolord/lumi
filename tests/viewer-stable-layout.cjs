const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const {JSDOM}=require(path.join(process.env.TEMP,'photo-design-test-tools/node_modules/jsdom'));
const root=path.join(__dirname,'..');
const dom=new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),{url:'https://photos.example/',runScripts:'outside-only',pretendToBeVisual:true});
const w=dom.window,d=w.document,run=s=>vm.runInContext(s,dom.getInternalVMContext());
w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};
w.HTMLElement.prototype.scrollTo=()=>{};w.HTMLElement.prototype.getAnimations=()=>[];
w.HTMLElement.prototype.animate=()=>({finished:Promise.resolve(),cancel(){}});
w.HTMLMediaElement.prototype.pause=()=>{};w.HTMLMediaElement.prototype.load=()=>{};
w.Image=class{set src(value){}};
const style=d.createElement('style');style.textContent=fs.readFileSync(path.join(root,'style.css'),'utf8');d.head.append(style);
run(fs.readFileSync(path.join(root,'app.js'),'utf8'));
const viewer=d.querySelector('#viewer'),wrap=d.querySelector('#photoWrap');
function surface(){const css=w.getComputedStyle(wrap);return {top:css.top,bottom:css.bottom,height:css.height,transition:css.transition};}
(async()=>{
 run('viewer.classList.remove("hidden");viewerSequence=[0,videoIndex,1,verticalVideoIndex];current=0;renderViewer();syncVideo()');
 const baseline=surface();
 for(const index of ['videoIndex','1','verticalVideoIndex','0']){
  await run(`slideTo(${index})`);
  assert.deepStrictEqual(surface(),baseline,'Swipe must keep the same media surface from photo to video and back; no vertical recenter after arrival');
  viewer.style.setProperty('--media-bottom','210px');
  assert.deepStrictEqual(surface(),baseline,'Changes in the toolbar height must not move the media');
  run('enterCinema()');assert.deepStrictEqual(surface(),baseline,'Cinema must preserve the same surface');run('exitCinema()');
 }
 assert.strictEqual(baseline.bottom,'0px','Media extends behind floating controls');
 assert(!/bottom|all/.test(baseline.transition),'The viewing surface must not animate vertically');
 console.log('Viewer: shared stable surface across photo/video swipes, toolbar height changes and cinema');dom.window.close();
})().catch(error=>{console.error(error);dom.window.close();process.exitCode=1});
