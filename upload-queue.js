(() => {
  if(!window.PHOTO_ACCOUNT?.id)return;
  const owner=window.PHOTO_ACCOUNT.id,listeners=new Set();
  let db=null,memory=new Map(),jobs=[],running=false,paused=false,saving=0,current=null,controller=null,disposed=false,phase='',loaded=0,notice='',refreshTimer;
  const database=new Promise(resolve=>{
    if(!window.indexedDB){resolve(null);return;}
    const request=indexedDB.open('photo-upload-queue',1);
    request.onupgradeneeded=()=>{const data=request.result;data.createObjectStore('jobs',{keyPath:'id'});data.createObjectStore('files');data.createObjectStore('preferences');};
    request.onsuccess=()=>resolve(request.result);request.onerror=()=>resolve(null);request.onblocked=()=>resolve(null);
  });
  async function transaction(stores,mode,callback){
    if(!db)return callback(null);
    return new Promise((resolve,reject)=>{const tx=db.transaction(stores,mode);let value;try{value=callback(tx);}catch(e){tx.abort();reject(e);return;}tx.oncomplete=()=>resolve(value);tx.onerror=()=>reject(tx.error||new Error('Не удалось сохранить очередь.'));tx.onabort=()=>reject(tx.error||new Error('Запись очереди прервана.'));});
  }
  async function read(store,key){
    if(!db)return store==='jobs'?[...memory.values()].map(item=>item.job):store==='files'?memory.get(key)?.file:paused;
    return new Promise((resolve,reject)=>{const r=db.transaction(store).objectStore(store)[key===undefined?'getAll':'get'](key);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
  }
  async function save(job,file){
    if(!db){const old=memory.get(job.id);memory.set(job.id,{job:{...job},file:file===undefined?old?.file:file});return;}
    await transaction(['jobs','files'],'readwrite',tx=>{tx.objectStore('jobs').put(job);if(file!==undefined)tx.objectStore('files').put(file,job.id);});
  }
  async function removeFile(id){if(!db){const item=memory.get(id);if(item)item.file=null;return;}await transaction(['files'],'readwrite',tx=>tx.objectStore('files').delete(id));}
  function snapshot(){const done=jobs.filter(j=>j.state==='done'),pending=jobs.filter(j=>j.state==='pending'||j.state==='uploading'),failed=jobs.filter(j=>j.state==='error');return {jobs:jobs.map(({id,name,size,state,error,duplicate})=>({id,name,size,state,error,duplicate})),done:done.length,skipped:done.filter(j=>j.duplicate).length,pending:pending.length,failed:failed.length,total:jobs.length,running,paused,saving,persistent:!!db,current:current?.name||'',phase,notice,progress:Math.min(100,Math.round((jobs.filter(j=>j.state==='done'||j.state==='error').reduce((sum,j)=>sum+j.size,0)+loaded)/Math.max(1,jobs.reduce((sum,j)=>sum+j.size,0))*100))};}
  function emit(){const state=snapshot();for(const callback of listeners)callback(state);}
  async function persistPause(){if(db)await transaction(['preferences'],'readwrite',tx=>tx.objectStore('preferences').put(paused,owner));}
  function refresh(){clearTimeout(refreshTimer);refreshTimer=setTimeout(()=>{window.PhotoVault?.refresh().catch(()=>{});window.PhotoAccount?.refresh().catch(()=>{});},300);}
  function send(job,file,signal){return new Promise(async(resolve,reject)=>{
    let headers;try{const saved=await window.PhotoAccount.api('/api/assets/upload-status?key='+encodeURIComponent(job.id));if(saved.complete){resolve(saved);return;}
      if(crypto.subtle&&typeof file.arrayBuffer==='function'&&file.size<=16*1024**2){
        phase='Проверка повторов';emit();
        const digest=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());
        if(signal.aborted)throw new DOMException('Приостановлено','AbortError');
        const sha256=Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');
        const check=await window.PhotoAccount.api('/api/assets/check',{size:file.size,sha256});
        if(check.duplicate){resolve({duplicate:true});return;}
      }
      headers=await window.PhotoAccount.headers();}catch(e){reject(e);return;}
    if(signal.aborted){reject(new DOMException('Приостановлено','AbortError'));return;}
    const xhr=new XMLHttpRequest();let settled=false;
    const finish=(error,data)=>{if(settled)return;settled=true;signal.removeEventListener('abort',abort);error?reject(error):resolve(data);};
    const fail=(text,status=0)=>Object.assign(new Error(text),{status});
    const abort=()=>{xhr.abort();finish(new DOMException('Приостановлено','AbortError'));};
    xhr.open('POST','/api/assets/upload');xhr.withCredentials=true;xhr.timeout=15*60*1000;
    for(const [key,value] of Object.entries({...headers,'X-Upload-ID':job.id,'X-File-Name':encodeURIComponent(job.name),'Content-Type':job.type||'application/octet-stream'}))xhr.setRequestHeader(key,value);
    xhr.upload.onprogress=e=>{loaded=Math.min(e.loaded,job.size);phase='Передача';emit();};
    xhr.upload.onload=()=>{loaded=job.size;phase='Проверка и сохранение';emit();};
    xhr.onload=()=>{let data;try{data=JSON.parse(xhr.responseText);}catch{finish(fail('Сервер не ответил. Загрузка продолжится после повтора.',xhr.status));return;}finish(xhr.status>=200&&xhr.status<300?null:fail(data.error||'Не удалось загрузить файл.',xhr.status),data);};
    xhr.onerror=()=>finish(fail('Нет соединения. Продолжим при возвращении в приложение.'));
    xhr.ontimeout=()=>finish(fail('Сервер долго не отвечает. Нажми «Продолжить».'));
    xhr.onabort=()=>finish(new DOMException('Приостановлено','AbortError'));
    signal.addEventListener('abort',abort,{once:true});try{xhr.send(file);}catch(e){finish(e);}
  });}
  async function process(){
    if(running||paused||disposed||saving)return;let waitForReturn=false;running=true;emit();
    try{
      // Web Locks serializes tabs. The server receipt also prevents duplicates if a
      // suspended tab resumes or a response was lost after the file was saved.
      const work=async()=>{
        const stored=await read('jobs');jobs=stored.filter(j=>j.owner===owner).sort((a,b)=>a.created-b.created);
        for(const job of jobs)if(job.state==='uploading'){job.state='pending';await save(job);}
        while(!paused&&!disposed&&!waitForReturn){
          if(navigator.onLine===false){notice='Нет интернета. Очередь сохранена.';break;}
          const job=jobs.find(j=>j.state==='pending');if(!job)break;
          current=job;loaded=0;phase='Подготовка';notice='';job.state='uploading';await save(job);controller=new AbortController();emit();
          try{
            const file=await read('files',job.id);if(!file)throw Object.assign(new Error('Файл недоступен на устройстве. Выбери его заново.'),{status:410});
            const result=await send(job,file,controller.signal);job.duplicate=!!result?.duplicate;job.state='done';job.error='';await save(job);await removeFile(job.id);refresh();
          }catch(e){
            if(e.name==='AbortError'){job.state='pending';}
            else if(!e.status){job.state='pending';waitForReturn=true;notice=e.message;}
            else if([401,403,409,413,507].includes(e.status)){job.state='pending';paused=true;notice=e.message;await persistPause();}
            else{job.state='error';job.error=e.message;}
            await save(job);
          }finally{current=null;controller=null;loaded=0;emit();}
        }
      };
      if(navigator.locks?.request)await navigator.locks.request('photo-upload-'+owner,work);else await work();
    }catch(e){paused=true;notice='Не удалось прочитать очередь. '+e.message;}
    finally{running=false;phase='';emit();if(!paused&&!disposed&&!saving&&!waitForReturn&&navigator.onLine!==false&&jobs.some(job=>job.state==='pending'))setTimeout(()=>void process(),0);}
  }
  const ready=database.then(async value=>{db=value;paused=!!(await read('preferences',owner));jobs=(await read('jobs')).filter(j=>j.owner===owner).sort((a,b)=>a.created-b.created);emit();void process();});
  window.PhotoUploadQueue={ready,snapshot,subscribe(callback){listeners.add(callback);callback(snapshot());return()=>listeners.delete(callback);},
    async enqueue(files){await ready;if(files.some(file=>!file.size||file.size>10*1024**3))throw new Error('Выбери непустые файлы размером до 10 ГБ каждый.');if(jobs.length&&jobs.every(job=>job.state==='done'))await this.clearFinished();saving=files.length;emit();let added=0;
      try{for(const file of files){const id=Array.from(crypto.getRandomValues(new Uint8Array(16)),value=>value.toString(16).padStart(2,'0')).join('');const job={id,owner,name:file.name,size:file.size,type:file.type,state:'pending',error:'',created:Date.now()+added/1000};await save(job,file);jobs.push(job);added++;saving--;emit();}}
      catch(e){notice=`В очередь добавлено ${added} из ${files.length}. На устройстве недостаточно места для остальных файлов.`;throw new Error(notice);}
      finally{saving=0;if(added){paused=false;await persistPause();}emit();void process();}return added;
    },
    async pause(){paused=true;await persistPause();controller?.abort();emit();},
    async resume(){await ready;paused=false;notice='';for(const job of jobs)if(job.state==='error'){job.state='pending';job.error='';await save(job);}await persistPause();emit();void process();},
    async clearFinished(){await ready;for(const job of jobs.filter(j=>j.state==='done')){if(db)await transaction(['jobs','files'],'readwrite',tx=>{tx.objectStore('jobs').delete(job.id);tx.objectStore('files').delete(job.id);});else memory.delete(job.id);}jobs=jobs.filter(j=>j.state!=='done');emit();},
    async discard(){await this.pause();while(running)await new Promise(resolve=>setTimeout(resolve,20));for(const job of jobs){if(db)await transaction(['jobs','files'],'readwrite',tx=>{tx.objectStore('jobs').delete(job.id);tx.objectStore('files').delete(job.id);});else memory.delete(job.id);}jobs=[];notice='';emit();},
    dispose(){disposed=true;controller?.abort();clearTimeout(refreshTimer);db?.close();listeners.clear();}
  };
  window.addEventListener('online',()=>{if(!paused)void process();});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!paused)void process();});
})();
