// Real layout and interactions against a disposable fixture server, no user files.
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('assert');
const {webkit,chromium}=require(path.join(process.env.TEMP,'photo-design-test-tools/node_modules/playwright'));
const engine=process.env.LUMI_TEST_BROWSER==='chromium'?chromium:webkit;
const root=path.join(__dirname,'..'),jpeg=fs.readFileSync(path.join(root,'assets/10.jpg'));
const items=Array.from({length:600},(_,i)=>({id:i,key:'fixture-'+i,state:'public',kind:'photo',metadata:{name:'Photo '+i,addedAt:new Date(Date.UTC(2024,0,1)+i*86400000).toISOString(),takenAt:new Date(Date.UTC(2024,0,1)+i*86400000).toISOString()}}));
const server=http.createServer((req,res)=>{
 const p=new URL(req.url,'http://localhost').pathname;let data,type='application/json';
 if(p==='/api/account/status')data=JSON.stringify({authenticated:true,configured:true,ready:true,id:'a'.repeat(32),name:'Fixture',role:'user'});
 else if(p==='/api/library')data=JSON.stringify({items,vault:{authenticated:true,configured:false,protectionEnabled:false},albums:[],accountId:'a'.repeat(32)});
 else if(p==='/api/people')data=JSON.stringify({people:[{id:'fixture',name:'Каролина',indices:[1,2],cover:null}],hidden:[],excluded:[],visible:true,enabled:false,available:true,total:600,done:600});
 else if(p.startsWith('/api/'))data='{}';
 else if(/^\/media\/\d+\//.test(p)){data=jpeg;type='image/jpeg';}
 else {const file=path.join(root,p==='/'?'index.html':p.slice(1));if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404).end();return;}data=fs.readFileSync(file);type=({'.html':'text/html','.js':'text/javascript','.css':'text/css','.jpg':'image/jpeg','.png':'image/png'})[path.extname(file)]||'application/octet-stream';}
 res.writeHead(200,{'Content-Type':type,'Cache-Control':'no-store'});res.end(data);
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let browser;
 try{
  browser=await engine.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.waitForFunction(()=>!document.documentElement.classList.contains('account-loading'));
  await page.waitForFunction(()=>window.PhotoPeople&&window.PhotoAlbums);
  await page.locator('#searchButton').click();await page.locator('#searchInput').fill('Каролина');
  await page.locator('.people-search-results').waitFor({state:'visible'});
  const gap=await page.evaluate(()=>document.querySelector('.people-search-results h2').getBoundingClientRect().top-document.querySelector('.searchbox').getBoundingClientRect().bottom);
  assert(gap>=0&&gap<80,`Desktop people search has a compact gap, got ${gap}`);
  for(const width of [1024,1440,1920]){
   await page.setViewportSize({width,height:900});await page.evaluate(()=>{show('library');window.scrollTo(0,0)});
   await page.waitForTimeout(100);
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No horizontal page overflow');
   const navigation=await page.locator('.bottom').boundingBox();assert(navigation.x===0&&navigation.width===248);
   const geometry=await page.evaluate(()=>({columns:libraryColumns(),grid:document.querySelector('#grid').getBoundingClientRect().width,mounted:document.querySelectorAll('#grid .tile').length}));
   assert(geometry.columns>=5&&geometry.mounted<300,JSON.stringify(geometry));
  }
  await page.locator('#grid .tile').first().click();await page.waitForFunction(()=>!busy&&!viewer.classList.contains('hidden'));
  const surface=()=>page.evaluate(()=>{const p=document.querySelector('#photoWrap').getBoundingClientRect(),b=document.querySelector('.viewer-bottom').getBoundingClientRect();return {top:p.top,bottom:p.bottom,barTop:b.top};});
  const normal=await surface();assert(normal.bottom<=normal.barTop+1,'Desktop controls are below the photo surface');
  assert(await page.locator('#filmstrip button').count()>1,'Filmstrip retained');
  await page.evaluate(()=>enterCinema());assert.deepEqual(await surface(),normal,'Cinema does not recenter the photo');await page.evaluate(()=>exitCinema());
  await page.locator('#back').click();await page.waitForFunction(()=>viewer.classList.contains('hidden')&&!busy);
  await page.evaluate(()=>openCollection('Недавние'));await page.locator('#select').click();
  assert(await page.locator('#selectAll').isVisible(),'Select all stays accessible inside desktop albums');
  await page.locator('#selectAll').click();assert.equal(await page.evaluate(()=>chosen.size),600);
  await page.locator('#select').click();await page.locator('#albumView').click();await page.locator('[data-album-action="layout:dense"]').click();
  await page.locator('#collectionGrid').dispatchEvent('wheel',{ctrlKey:true,deltaY:-120});
  assert.equal(await page.locator('#collectionGrid').getAttribute('data-layout'),'square','Ctrl+wheel changes album density');
  await page.keyboard.press('Control+a');assert.equal(await page.evaluate(()=>chosen.size),600,'Album keyboard selection stays scoped');
  await page.evaluate(()=>{if(selecting)document.querySelector('#select').click();show('library')});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>libraryColumns()),5,'Phone density remains unchanged');
  await page.locator('#grid .tile').first().click();await page.waitForFunction(()=>!busy&&!viewer.classList.contains('hidden'));
  const mobile=await surface();assert.equal(mobile.bottom,844,'Phone media still extends behind floating controls');
  await page.evaluate(()=>viewer.style.setProperty('--media-bottom','210px'));assert.deepEqual(await surface(),mobile,'Toolbar height cannot move phone media');
  await page.evaluate(()=>enterCinema());assert.deepEqual(await surface(),mobile,'Phone cinema keeps the same media surface');
  assert.deepEqual(errors,[]);
  await page.screenshot({path:path.join(process.env.TEMP,'lumi-desktop-mobile-regression.png')});
  console.log('Desktop '+engine.name()+': real responsive geometry, people search, viewer/cinema, album selection and wheel; phone density preserved');
 }finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(e=>{console.error(e);process.exitCode=1});
