const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const {JSDOM}=require(path.join(process.env.TEMP,'photo-design-test-tools/node_modules/jsdom'));
const root=path.join(__dirname,'..');
async function scenario(configured){
 const dom=new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),{url:'https://foto.mira5.netcraze.club/#setup=private-test-capability',runScripts:'outside-only',pretendToBeVisual:true});
 const w=dom.window,doc=w.document;let logged=false,finished=false;const calls=[];
 w.fetch=async(url,options={})=>{
  const body=options.body?JSON.parse(options.body):undefined;calls.push({url,body,headers:options.headers});let data;
  if(url==='/api/account/status')data={configured,authenticated:logged,canSetup:true};
  else if(url==='/api/account/register'||url==='/api/account/login'){logged=true;data={configured:true,authenticated:true,ready:configured,name:'Мой аккаунт',login:'owner'};}
  else if(url==='/api/account/folders')data={roots:[{id:'photo',name:'photo'}]};
  else if(url.startsWith('/api/account/folders?'))data={folders:[]};
  else if(url==='/api/account/folder')data={state:'running'};
  else if(url==='/api/account/import')data={state:'complete',total:2,done:2,added:2,skipped:0};
  else if(url==='/api/account/finish'){finished=true;data={configured:true,authenticated:true,ready:true,name:'Мой аккаунт',folder:'photo'};}
  else throw new Error('unexpected '+url);
  return {ok:true,json:async()=>({...data,csrf:'test-csrf'})};
 };
 vm.runInContext(fs.readFileSync(path.join(root,'account-client.js'),'utf8'),dom.getInternalVMContext());
 const start=w.PhotoAccount.start();await new Promise(r=>setTimeout(r,0));
 assert.strictEqual(w.location.hash,'');assert(doc.documentElement.classList.contains('account-loading'));
 assert.strictEqual(w.PHOTO_ACCOUNT,undefined);
 const form=doc.querySelector('form');form.elements.login.value='owner';form.elements.password.value='a strong password';
 if(!configured){form.elements.name.value='Мой аккаунт';form.elements.confirm.value='a strong password';}
 form.dispatchEvent(new w.SubmitEvent('submit',{bubbles:true,cancelable:true,submitter:form.querySelector('button')}));
 await new Promise(r=>setTimeout(r,0));
 if(!configured){
  assert(!('setupToken' in calls.find(call=>call.url==='/api/account/register').body));
  assert(!doc.querySelector('[name=setupToken]'));
  doc.querySelector('[data-source]').click();await new Promise(r=>setTimeout(r,0));
  doc.querySelector('#connectFolder').click();await new Promise(r=>setTimeout(r,0));
  assert(doc.querySelector('#finishOnboarding'));doc.querySelector('#finishOnboarding').click();
 }
 const status=await start;assert(status.ready);assert(!doc.querySelector('.onboarding'));
 assert(calls.filter(call=>call.body).every(call=>call.headers['X-Photo-CSRF']==='test-csrf'));
 assert(calls.every(call=>call.headers['X-Photo-App-Origin']==='https://foto.mira5.netcraze.club'));
 assert.strictEqual(finished,!configured);assert(!calls.some(call=>call.url==='/api/library'));dom.window.close();
}
(async()=>{await scenario(false);await scenario(true);console.log('Account onboarding: private registration, login, folder selection, import progress and deferred gallery boot passed');})().catch(error=>{console.error(error);process.exit(1)});
