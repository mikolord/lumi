const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const {JSDOM}=require(path.join(process.env.TEMP,'photo-design-test-tools/node_modules/jsdom'));
const dom=new JSDOM('<body><section></section><aside></aside></body>',{runScripts:'outside-only',pretendToBeVisual:true});
const w=dom.window,sheet=w.document.querySelector('section'),backdrop=w.document.querySelector('aside');const calls=[];
w.matchMedia=()=>({matches:false});w.HTMLElement.prototype.animate=function(frames,options){calls.push({element:this,frames,options});return {finished:Promise.resolve(),cancel(){}}};
vm.runInContext(fs.readFileSync(path.join(__dirname,'../sheet-gestures.js'),'utf8'),dom.getInternalVMContext());
(async()=>{
 await w.PhotoSheetMotion.show(sheet,backdrop);const enter=calls.find(c=>c.element===sheet);
 assert.strictEqual(enter.options.duration,480);assert(parseFloat(enter.frames[0].transform.match(/[\d.]+/)[0])>=w.innerHeight,'Sheet enters from below the viewport');
 await w.PhotoSheetMotion.hide(sheet,backdrop);const exit=calls.filter(c=>c.element===sheet).at(-1);
 assert.strictEqual(exit.options.duration,420);assert(parseFloat(exit.frames[1].transform.match(/[\d.]+/)[0])>=w.innerHeight,'Sheet leaves completely through the bottom');assert.strictEqual(exit.frames[1].opacity,1,'Sheet slides away instead of disappearing early');
 await w.PhotoSheetMotion.show(sheet,backdrop,true);assert(parseFloat(calls.at(-1).frames[0].transform.match(/[\d.]+/)[0])>=w.innerHeight,'Nested pages use the same full-height presentation');
 w.matchMedia=()=>({matches:true});await w.PhotoSheetMotion.show(sheet);assert.strictEqual(calls.at(-1).options.duration,1);
 console.log('Sheets: consistent faster full-height slide in/out, opaque exit, reduced motion');dom.window.close();
})().catch(e=>{console.error(e);dom.window.close();process.exitCode=1});
