const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert'),{JSDOM}=require(path.join(process.env.TEMP,'photo-design-test-tools/node_modules/jsdom'));
const dom=new JSDOM('<!doctype html><body></body>',{url:'https://photos.example',runScripts:'outside-only'}),w=dom.window;
w.fetch=()=>{throw Error('Obsolete startup must not prefetch the entire library')};
vm.runInContext(fs.readFileSync(path.join(__dirname,'../cache-preparation.js'),'utf8'),dom.getInternalVMContext());
(async()=>{const result=await w.PhotoCachePreparation.prepare({items:Array.from({length:2500},(_,id)=>({id,state:'public'}))},{id:'test'});assert.equal(result,undefined);assert(!w.document.querySelector('.cache-preparation'));console.log('Older startup clients also bypass the removed full-library preparation');dom.window.close()})().catch(e=>{console.error(e);dom.window.close();process.exitCode=1});
