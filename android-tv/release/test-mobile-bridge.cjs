const assert=require('node:assert/strict');
const fs=require('node:fs');
const {File}=require('node:buffer');
const {JSDOM}=require('jsdom');
(async()=>{
 const dom=new JSDOM('<body><div class="account-storage"></div></body>',{url:'https://photos.example',runScripts:'outside-only',pretendToBeVisual:true});
 const w=dom.window,calls=[],forwarded=[];let rejectChunk=false;
 w.File=File;w.PhotoManage={open:(...args)=>forwarded.push(args)};
 w.LumiNative={postMessage(raw){const message=JSON.parse(raw);calls.push(message);let reply={id:message.id};if(message.op==='export-begin')reply.token='fixture';if(message.op==='export-chunk'&&rejectChunk)reply.error='Full storage';queueMicrotask(()=>w.LumiNative.onmessage?.({data:JSON.stringify(reply)}));}};
 try{
  w.eval(fs.readFileSync(require('node:path').join(__dirname,'../app/src/main/assets/mobile-native.js'),'utf8'));
  assert.equal(w.document.querySelectorAll('[data-lumi-native-settings]').length,1);
  w.PhotoManage.open('devices');assert.deepEqual(forwarded,[['devices']]);w.PhotoManage.open('upload');
  assert(calls.some(x=>x.op==='queue'));assert.equal(forwarded.length,1);
  const bytes=Buffer.alloc(120000,121);await w.navigator.share({files:[new File([bytes],'photo.jpg',{type:'image/jpeg'})]});
  const chunks=calls.filter(x=>x.op==='export-chunk');assert.deepEqual(chunks.map(x=>x.offset),[0,49152,98304]);assert.deepEqual(Buffer.concat(chunks.map(x=>Buffer.from(x.bytes,'base64'))),bytes);
  assert(calls.some(x=>x.op==='export-share'));
  rejectChunk=true;await assert.rejects(()=>w.navigator.share({files:[new File([bytes],'failure.jpg')]}),/Full storage/);
  assert(calls.some(x=>x.op==='export-abort'));
  assert.equal(w.navigator.canShare({files:[]}),false);
  console.log('Mobile bridge: native upload routing, profile insertion, streamed sharing and error cleanup passed');
 }finally{dom.window.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
