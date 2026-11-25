// Album presentation shares the library's selection and media actions.
(() => {
  const album=document.querySelector('#collectionScreen'),heading=album.querySelector('.album-heading'),summary=heading.querySelector('div'),grid=document.querySelector('#collectionGrid');
  const key='photo-album-view-v1:'+ (window.PHOTO_ACCOUNT?.id||'demo');let preferences={};try{preferences=JSON.parse(localStorage.getItem(key))||{};}catch{}
  const svg=path=>`<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${path}</svg>`;
  const icons={grid:svg('<rect x="3" y="3" width="6" height="6" rx="1"/><rect x="15" y="3" width="6" height="6" rx="1"/><rect x="3" y="15" width="6" height="6" rx="1"/><rect x="15" y="15" width="6" height="6" rx="1"/>'),sort:svg(paths.filter),more:svg(paths.more),play:svg('<path d="m8 4 13 8-13 8Z" fill="currentColor" stroke="none"/>')};
  summary.classList.add('album-summary');
  const navigation=document.createElement('nav');navigation.className='album-navigation';navigation.setAttribute('aria-label','Управление альбомом');
  navigation.innerHTML=`<div class="album-view-tools glass"><button id="albumView" aria-label="Вид фотографий" aria-haspopup="menu">${icons.grid}</button><button id="albumSort" aria-label="Порядок фотографий" aria-haspopup="menu">${icons.sort}</button><button id="albumMore" aria-label="Действия с альбомом" aria-haspopup="menu">${icons.more}</button></div>`;heading.append(navigation);
  const hero=document.createElement('div');hero.className='album-hero hidden';hero.innerHTML=`<button class="album-hero-open" aria-label="Открыть обложку"><img alt=""></button><div class="album-hero-caption"><h2></h2><p></p></div><div class="album-hero-actions"><button class="glass circle" aria-label="Показать только сетку">${icons.grid}</button><button class="glass circle" aria-label="Начать слайд-шоу">${icons.play}</button></div>`;heading.after(hero);
  const popup=document.createElement('div');popup.className='album-popup hidden';popup.setAttribute('role','menu');document.body.append(popup);let popupAnchor=null,heroIndex=null;
  const select=document.querySelector('#select'),all=document.querySelector('#selectAll'),options=document.querySelector('.selection-options'),filter=document.querySelector('#filter');
  const homes=[options,all,select].map(element=>{const marker=document.createComment('album-control-home');element.before(marker);return {element,marker};});
  const normal=()=>screen==='collectionScreen'&&collectionName!=='Недавно удалённые'&&document.querySelector('.vault-gate')?.classList.contains('hidden')!==false;
  const config=name=>({...{layout:'mosaic',sort:'added',hero:name.startsWith('person:')||name.startsWith('album:')},...preferences[name]});
  const save=change=>{preferences[collectionName]={...config(collectionName),...change};try{localStorage.setItem(key,JSON.stringify(preferences));}catch{}render();};
  function order(name,items){
    if(name==='Недавно удалённые')return items;
    const sort=config(name).sort;return [...items].sort((a,b)=>{
      if(sort==='oldest')return stamp(a,'takenAt')-stamp(b,'takenAt')||a-b;
      if(sort==='newest')return stamp(b,'takenAt')-stamp(a,'takenAt')||b-a;
      if(sort==='name')return (window.PhotoVault?.metadata(a)?.name||'').localeCompare(window.PhotoVault?.metadata(b)?.name||'','ru')||a-b;
      return stamp(b,'addedAt')-stamp(a,'addedAt')||b-a;
    });
  }
  function stamp(i,field){const data=window.PhotoMetadata?.get(i)||window.PhotoVault?.metadata(i)||{};return Date.parse(data[field]||data.addedAt)||0;}
  function closePopup(){popup.classList.add('hidden');popupAnchor?.setAttribute('aria-expanded','false');popupAnchor=null;}
  function openPopup(kind,anchor){
    if(popupAnchor===anchor){closePopup();return;}closePopup();popupAnchor=anchor;anchor.setAttribute('aria-expanded','true');const value=config(collectionName);
    const row=(action,label,checked=false)=>`<button role="menuitem${action.startsWith('layout:')||action.startsWith('sort:')?'radio':''}" ${action.startsWith('layout:')||action.startsWith('sort:')?`aria-checked="${checked}"`:''} data-album-action="${action}"><span>${label}</span><span aria-hidden="true">${checked?'✓':''}</span></button>`;
    popup.innerHTML=kind==='view'?'<p>Вид фотографий</p>'+[['mosaic','Мозаика'],['square','Квадратная сетка'],['dense','Компактная сетка']].map(([id,label])=>row('layout:'+id,label,value.layout===id)).join('')+'<hr>'+row('hero',value.hero?'Скрыть большую обложку':'Показать большую обложку'):kind==='sort'?'<p>Порядок фотографий</p>'+[['added','Недавно добавленные'],['newest','Сначала новые по дате съёмки'],['oldest','Сначала старые по дате съёмки'],['name','По имени файла']].map(([id,label])=>row('sort:'+id,label,value.sort===id)).join(''):(window.PhotoManage?.canUploadAlbumCover?.(collectionName)?row('upload-cover','Выбрать обложку с телефона'):'')+row('select','Выбрать фотографии')+row('slideshow','Начать слайд-шоу');
    popup.classList.remove('hidden');const rect=anchor.getBoundingClientRect();popup.style.left=Math.max(12,Math.min(innerWidth-296,rect.right-280))+'px';popup.style.top=Math.max(12,Math.min(innerHeight-popup.offsetHeight-12,rect.bottom+8))+'px';popup.querySelector('button')?.focus({preventScroll:true});
  }
  function selectionChanged(){
    if(!normal())return;
    navigation.classList.toggle('album-selecting',selecting);heading.classList.toggle('album-selecting',selecting);options.classList.toggle('hidden',!selecting);filter.classList.add('hidden');select.classList.remove('hidden');all.classList.add('hidden');
    const count=getCollectionItems(collectionName).length;document.querySelector('#albumCount').textContent=selecting?chosen.size?`Выбрано: ${chosen.size}`:'Выберите фотографии':`${count} объектов`;
    hero.classList.toggle('hidden',selecting||!config(collectionName).hero||!count);album.classList.toggle('album-has-hero',!hero.classList.contains('hidden'));
  }
  function refresh(){
    if(!normal())return;const items=getCollectionItems(collectionName),cfg=config(collectionName),title=document.querySelector('#albumTitle').textContent;
    grid.dataset.layout=cfg.layout;grid.classList.toggle('selecting',selecting);const cover=collectionName.startsWith('person:')?window.PhotoPeople?.coverIndex():window.PhotoManage?.coverIndex?.(collectionName);
    heroIndex=items.includes(cover)?cover:items[0];const img=hero.querySelector('img');if(heroIndex!==undefined&&img.getAttribute('src')!==photo(heroIndex))img.src=photo(heroIndex);
    hero.querySelector('h2').textContent=title;hero.querySelector('p').textContent=`${items.length} объектов`;selectionChanged();if(selecting)updateSelectionUI();window.PhotoTimeline?.refresh();
  }
  function render(){if(!normal())return;const scroll=album.scrollTop,items=getCollectionItems(collectionName),current=[...grid.children].map(tile=>Number(tile.dataset.index));if(items.length!==current.length||items.some((id,i)=>id!==current[i]))grid.replaceChildren(...items.map(makeTile));refresh();album.scrollTop=scroll;}
  function screenChanged(which){
    closePopup();if(which==='collectionScreen'&&collectionName!=='Недавно удалённые'){
      for(const {element} of homes)navigation.append(element);navigation.classList.remove('hidden');options.classList.add('hidden');select.classList.remove('hidden');filter.classList.add('hidden');
    }else{
      for(const {element,marker} of homes)marker.after(element);
      navigation.classList.add('hidden');hero.classList.add('hidden');hero.querySelector('img').removeAttribute('src');heroIndex=null;album.classList.remove('album-has-hero');if(collectionName==='Недавно удалённые')delete grid.dataset.layout;
      select.classList.toggle('hidden',which!=='library');options.classList.toggle('hidden',which!=='library');filter.classList.toggle('hidden',which!=='library');
    }
  }
  popup.onclick=e=>{const action=e.target.closest('[data-album-action]')?.dataset.albumAction;if(!action)return;closePopup();if(action.startsWith('layout:'))save({layout:action.slice(7)});else if(action.startsWith('sort:'))save({sort:action.slice(5)});else if(action==='hero')save({hero:!config(collectionName).hero});else if(action==='upload-cover')window.PhotoManage?.uploadAlbumCover(collectionName);else if(action==='select')select.click();else if(action==='slideshow')window.PhotoActions?.slideshow(getCollectionItems(collectionName));};
  document.querySelector('#albumView').onclick=e=>openPopup('view',e.currentTarget);document.querySelector('#albumSort').onclick=e=>openPopup('sort',e.currentTarget);
  document.querySelector('#albumMore').onclick=e=>collectionName.startsWith('person:')?window.PhotoPeople?.openMenu(e.currentTarget):openPopup('more',e.currentTarget);
  hero.querySelector('.album-hero-open').onclick=()=>heroIndex!==undefined&&openViewer(heroIndex,hero.querySelector('img'));
  hero.querySelectorAll('.album-hero-actions button')[0].onclick=()=>save({hero:false});hero.querySelectorAll('.album-hero-actions button')[1].onclick=()=>window.PhotoActions?.slideshow(getCollectionItems(collectionName));
  document.addEventListener('pointerdown',e=>{if(popupAnchor&&!e.target.closest('.album-popup,#albumView,#albumSort,#albumMore'))closePopup();});
  album.addEventListener('scroll',closePopup,{passive:true});window.addEventListener('resize',closePopup);
  window.addEventListener('keydown',e=>{if(!popupAnchor)return;if(e.key==='Escape'){const anchor=popupAnchor;closePopup();anchor.focus({preventScroll:true});e.preventDefault();e.stopImmediatePropagation();}else if(['ArrowDown','ArrowUp','Tab'].includes(e.key)){const buttons=[...popup.querySelectorAll('button')],index=buttons.indexOf(document.activeElement),back=e.key==='ArrowUp'||e.key==='Tab'&&e.shiftKey;buttons[(index+(back?-1:1)+buttons.length)%buttons.length]?.focus();e.preventDefault();e.stopImmediatePropagation();}},true);
  document.addEventListener('vault-state-change',()=>{if(normal())render();});
  window.PhotoAlbums={order,refresh,selectionChanged,screenChanged,locked(){window.PhotoTimeline?.reset();if(selecting)select.click();navigation.classList.add('hidden');hero.classList.add('hidden');hero.querySelector('img').removeAttribute('src');heroIndex=null;album.classList.remove('album-has-hero');},opened(){screenChanged(screen);refresh();}};
})();
