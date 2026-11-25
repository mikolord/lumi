// Deterministic finger reversals through the actual timeline controller.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert'),{JSDOM}=require(path.join(process.env.TEMP,'photo-design-test-tools/node_modules/jsdom'));
const dom=new JSDOM('<main class="app"><section id="library"><div id="grid"></div></section><div id="viewer" class="hidden"></div></main>',{url:'https://photos.example',runScripts:'outside-only'}),w=dom.window,d=w.document,ctx=dom.getInternalVMContext();let clock=0,next=0,scrolls=[],frames=new Map();
w.requestAnimationFrame=fn=>{frames.set(++next,fn);return next;};w.cancelAnimationFrame=id=>frames.delete(id);w.matchMedia=()=>({matches:false});w.HTMLCanvasElement.prototype.getContext=()=>({scale(){},fillRect(){},drawImage(){}});w.scrollTo=value=>scrolls.push(value);Object.defineProperty(d.documentElement,'scrollHeight',{value:100000});
w.HTMLElement.prototype.getBoundingClientRect=()=>({top:100,bottom:700,height:600,left:0,right:390,width:390});
vm.runInContext("let screen='library',selecting=false;const viewer=document.querySelector('#viewer');const getVisibleLibraryItems=()=>Array.from({length:2500},(_,i)=>i);const libraryDate=i=>Date.UTC(2020,0,i+1);",ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../timeline-ui.js'),'utf8'),ctx);
const track=d.querySelector('.timeline-track'),thumb=d.querySelector('.timeline-thumb');
function tick(){clock+=16;const pending=[...frames.values()];frames.clear();pending.forEach(fn=>fn(clock));}
function touch(type,y){const e=new w.Event(type,{bubbles:true,cancelable:true});Object.defineProperty(e,'touches',{value:type==='touchend'?[]:[{clientX:370,clientY:y}]});track.dispatchEvent(e);}
function markerY(){const transform=thumb.style.transform.match(/translate3d\(0,\s*([\d.]+)px/);return transform?Number(transform[1]):parseFloat(thumb.style.top)/100*600;}
try{
 d.querySelector('.library-timeline-trigger').click();tick();touch('touchstart',200);tick();
 let worst=0;for(const y of [600,220,570,250,520,300]){touch('touchmove',y);tick();worst=Math.max(worst,Math.abs(markerY()-(y-100)));}
 console.log('Largest marker/finger gap after a frame:',Math.round(worst),'px; background scrolls during drag:',scrolls.length);
 assert(worst<=2,'Timeline marker must follow reversals within one frame, without trailing the finger');assert.equal(scrolls.length,0,'Frozen glass background must not rebuild the library during a drag');
 touch('touchend',300);assert.equal(scrolls.length,1,'One library jump when the finger is released');console.log('Timeline reversals: marker follows finger; library navigation commits once on release');
}finally{dom.window.close();}
