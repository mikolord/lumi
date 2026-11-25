const assert=require('assert'),fs=require('fs'),vm=require('vm'),path=require('path');
const {indexedDB}=require(path.join(process.env.TEMP,'photo-design-test-tools/node_modules/fake-indexeddb'));
const source=fs.readFileSync(path.join(__dirname,'../upload-queue.js'),'utf8');
const wait=ms=>new Promise(r=>setTimeout(r,ms)),receipts=new Map();let written=0,mode='ok',sent=[];
function environment(owner){
 const window=new EventTarget(),document=new EventTarget();document.hidden=false;window.PHOTO_ACCOUNT={id:owner};window.indexedDB=indexedDB;window.PhotoAccount={api:async url=>url==='/api/assets/check'?{duplicate:mode==='duplicate'}:{complete:receipts.has(owner+url.split('key=')[1])},headers:async()=>({'X-Photo-CSRF':'signed'})};window.PhotoVault={refresh:async()=>{}};
 class XHR{
  constructor(){this.upload={};this.headers={};}open(){}setRequestHeader(name,value){this.headers[name]=value;}
  send(file){assert(file instanceof Blob);const key=owner+this.headers['X-Upload-ID'];sent.push(key);setTimeout(()=>{
   if(this.aborted)return;this.upload.onprogress({loaded:file.size/2});this.upload.onload();
   if(!receipts.has(key)){receipts.set(key,++written);}
   if(mode==='lost'){mode='ok';this.onerror();return;}
   this.status=200;this.responseText=JSON.stringify({id:receipts.get(key)});this.onload();
  },20);}abort(){this.aborted=true;this.onabort?.();}
 }
 const context={window,document,indexedDB,navigator:{onLine:true},crypto:require('crypto').webcrypto,XMLHttpRequest:XHR,AbortController,DOMException,Uint8Array,setTimeout,clearTimeout,console};vm.runInNewContext(source,context);return {window,document,queue:window.PhotoUploadQueue};
}
async function settled(queue){for(let i=0;i<300;i++){const s=queue.snapshot();if(!s.running&&!s.saving)return s;await wait(5);}throw new Error('Queue did not settle');}
(async()=>{
 let app=environment('alice');await app.queue.ready;await settled(app.queue);
 mode='lost';await app.queue.enqueue([new File(['photo'],'portrait.jpg',{type:'image/jpeg'})]);await settled(app.queue);assert.strictEqual(written,1);assert.strictEqual(app.queue.snapshot().pending,1);assert(app.queue.snapshot().persistent);assert(!app.queue.snapshot().paused,'Transient network errors should resume on foreground/online');
 app.queue.dispose();
 app=environment('alice');await app.queue.ready;await settled(app.queue);assert.strictEqual(app.queue.snapshot().done,1);assert.strictEqual(written,1,'A lost response must not duplicate the saved image');assert.strictEqual(sent.length,1,'Receipt lookup after reload avoids sending the file again');
 await app.queue.clearFinished();assert.strictEqual(app.queue.snapshot().total,0);mode='duplicate';const sentBefore=sent.length;await app.queue.enqueue([new File(['same'],'renamed.jpg')]);await settled(app.queue);assert.strictEqual(app.queue.snapshot().skipped,1);assert.strictEqual(sent.length,sentBefore,'Matching hash must avoid another transmission');await app.queue.clearFinished();mode='ok';
 await app.queue.enqueue([new File(['a'],'a.jpg'),new File(['b'],'b.jpg')]);await app.queue.pause();await settled(app.queue);assert(app.queue.snapshot().paused);const before=written;await wait(30);assert.strictEqual(written,before);
 app.queue.dispose();const other=environment('bob');await other.queue.ready;await settled(other.queue);assert.strictEqual(other.queue.snapshot().total,0,'Queue files belong to one account');other.queue.dispose();
 app=environment('alice');await app.queue.ready;await settled(app.queue);assert(app.queue.snapshot().paused,'Manual pause survives reload');await app.queue.resume();await settled(app.queue);assert.strictEqual(app.queue.snapshot().done,2);assert.strictEqual(written,3);await app.queue.discard();assert.strictEqual(app.queue.snapshot().total,0);app.queue.dispose();
 console.log('Durable queue: real IndexedDB file blobs, reload recovery, stable retry IDs, account isolation, pause/resume and cleanup passed');
})().catch(e=>{console.error(e);process.exitCode=1});
