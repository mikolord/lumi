(() => {
  if(window.PHOTO_ACCOUNT?.role!=='admin')return;
  const api=(path,body)=>window.PhotoAccount.api(path,body),esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const bytes=value=>value==null?'—':`${(value/1024**2).toLocaleString('ru-RU',{maximumFractionDigits:1})} МБ`;
  const percent=value=>value==null?'Измеряем…':`${value.toLocaleString('ru-RU',{maximumFractionDigits:1})}%`;
  const modal=document.createElement('div');modal.className='manage-modal system-modal hidden';modal.innerHTML='<div class="manage-shade"></div><section class="manage-sheet system-sheet" role="dialog" aria-modal="true" tabindex="-1"></section>';document.body.append(modal);
  const sheet=modal.querySelector('section');let opened=false,closing=false,view,revision=0,timer,focus,inert,updateState,busy=false,initialVersion;
  function message(text){const target=sheet.querySelector('[role=alert]');if(target)target.textContent=text;}
  function updates(data){
    updateState=data;if(!initialVersion)initialVersion=data.current;
    sheet.querySelector('#systemCurrent').textContent=data.current;
    sheet.querySelector('#systemLatest').textContent=data.latest||'Пока нет';
    sheet.querySelector('#systemUpdateStatus').textContent=data.rollbackMessage||data.message||'Проверь наличие новой версии';
    const running=['checking','downloading','installing'].includes(data.phase);
    sheet.querySelector('#checkUpdates').disabled=busy||running;
    const download=sheet.querySelector('#downloadUpdate');download.classList.toggle('hidden',!data.newer||(data.downloaded===('v'+data.latest)&&data.phase==='ready'));download.disabled=busy||running;
    const install=sheet.querySelector('#installUpdate');install.classList.toggle('hidden',!data.newer||!data.canInstall||data.phase!=='ready');install.disabled=busy||running;
    const rollback=sheet.querySelector('#rollbackUpdate');rollback.classList.toggle('hidden',!data.canRollback);rollback.disabled=busy||running;
    sheet.querySelector('.system-update-loading').classList.toggle('hidden',!running);
    sheet.querySelector('#reloadUpdated').classList.toggle('hidden',!initialVersion||initialVersion===data.current);
  }
  async function poll(request=revision){
    try{
      const data=await api(view==='metrics'?'/api/admin/metrics':'/api/admin/updates');if(request!==revision||!opened)return;
      message('');
      if(view==='metrics'){
        sheet.querySelector('#systemCpu').textContent=percent(data.cpu);sheet.querySelector('#systemMemory').textContent=bytes(data.memory);
        const target=sheet.querySelector('#systemComponents'),markup=data.components.map(c=>`<div class="system-component"><strong>${esc(c.name)}</strong><span>${percent(c.cpu)} CPU · ${bytes(c.memory)}</span><small>${c.scope==='process'?'Учтён процесс приложения':'Учтён весь контейнер'}</small></div>`).join('');if(target.innerHTML!==markup)target.innerHTML=markup;
        sheet.querySelector('#systemMetricsNote').textContent=data.partial?'Распознавание временно недоступно: показана нагрузка медиатеки.':`Общая нагрузка приложения на сервер с ${data.cores} потоками CPU. В деталях 100% CPU — один поток.`;
      }else updates(data);
    }catch(error){if(request===revision&&opened)message(view==='updates'&&updateState?.phase==='installing'?'Приложение перезапускается…':error.message);}
    finally{if(request===revision&&opened&&!document.hidden){clearTimeout(timer);timer=setTimeout(()=>poll(request),view==='metrics'?3000:2000);}}
  }
  async function action(which){
    if(busy)return;const request=revision;busy=true;message('');sheet.querySelectorAll('button[data-update]').forEach(b=>b.disabled=true);
    try{const data=await api('/api/admin/updates/action',{action:which});if(opened&&request===revision)updates(data);}
    catch(error){message(error.message);}finally{busy=false;if(opened&&request===revision&&updateState)updates(updateState);}
  }
  function open(which){
    if(opened||closing)return;view=which;opened=true;revision++;initialVersion=null;updateState=null;focus=document.activeElement;inert=document.querySelector('.app').inert;
    window.PhotoSheetMotion.hold(sheet);document.querySelector('.app').inert=true;modal.classList.remove('hidden');
    sheet.innerHTML=`<div class="sheet-grabber" aria-hidden="true"></div><header><h2>${which==='metrics'?'Нагрузка приложения':'Обновления'}</h2><button type="button" class="manage-close" aria-label="Закрыть">×</button></header>${which==='metrics'?'<div class="system-summary"><div><small>Процессор</small><strong id="systemCpu">Измеряем…</strong></div><div><small>Оперативная память</small><strong id="systemMemory">—</strong></div></div><div id="systemComponents" class="system-components"></div><p id="systemMetricsNote"></p>':'<div class="system-version-card"><div><span>Установлена</span><strong id="systemCurrent">…</strong></div><div><span>Последний выпуск</span><strong id="systemLatest">…</strong></div></div><p id="systemUpdateStatus" role="status"></p><div class="system-update-loading hidden"><span class="manage-spinner"></span><span>Подожди немного…</span></div><div class="system-update-actions"><button id="checkUpdates" data-update="check">Проверить обновления</button><button id="downloadUpdate" data-update="download" class="hidden">Скачать обновление</button><button id="installUpdate" data-update="install" class="hidden">Установить обновление</button><button id="rollbackUpdate" data-update="rollback" class="hidden">Вернуть предыдущую версию</button><button id="reloadUpdated" class="hidden">Открыть новую версию</button></div><p>Обновления устанавливаются из стабильных выпусков. Если новая версия не запустится, приложение вернётся к предыдущей.</p>'}<p class="manage-message" role="alert"></p>`;
    sheet.querySelector('.manage-close').onclick=close;
    if(which==='updates'){
      sheet.querySelectorAll('[data-update]').forEach(button=>button.onclick=()=>action(button.dataset.update));sheet.querySelector('#reloadUpdated').onclick=()=>location.reload();
    }
    sheet.scrollTop=0;sheet.focus({preventScroll:true});window.PhotoSheetMotion.show(sheet,modal.querySelector('.manage-shade'));poll();
  }
  async function close(){
    if(!opened||closing)return;closing=true;revision++;clearTimeout(timer);await window.PhotoSheetMotion.hide(sheet,modal.querySelector('.manage-shade'));opened=false;closing=false;modal.classList.add('hidden');sheet.replaceChildren();document.querySelector('.app').inert=inert||false;window.PhotoSheetMotion.release(sheet);if(focus?.isConnected)focus.focus({preventScroll:true});
  }
  modal.querySelector('.manage-shade').onclick=close;window.PhotoSheetGestures.attach(sheet,{dismiss:close,backdrop:modal.querySelector('.manage-shade')});
  window.addEventListener('keydown',e=>{if(!opened)return;if(e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();close();}if(e.key==='Tab'){const fields=[...sheet.querySelectorAll('button:not(:disabled)')].filter(b=>!b.closest('.hidden'));if(e.shiftKey&&(document.activeElement===sheet||document.activeElement===fields[0])){e.preventDefault();fields.at(-1)?.focus();}else if(!e.shiftKey&&document.activeElement===fields.at(-1)){e.preventDefault();fields[0]?.focus();}}},true);
  document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(opened&&!document.hidden)poll();});
  window.PhotoSystem={open};
})();
