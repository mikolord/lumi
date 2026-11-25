// A downward drag dismisses a sheet only from its header or the top of its scroll content.
window.PhotoSheetGestures = {
  attach(sheet, { dismiss, backdrop, handleOnly = false }) {
    let drag = null, suppressUntil = 0;
    const reset = () => {
      drag = null; sheet.style.transform = ''; sheet.classList.remove('sheet-dragging');
      if (backdrop) backdrop.style.opacity = '';
    };
    sheet.addEventListener('touchstart', e => {
      if (e.touches.length !== 1 || e.target.closest('input,textarea,select,button,a,[data-sheet-no-drag]')) { reset(); return; }
      const header = e.target.closest('.account-sheet-header,.avatar-crop-header,.avatar-crop-hint,.sheet-grabber');
      if ((handleOnly && !header) || (!header && sheet.scrollTop > 1)) return;
      const touch = e.touches[0];
      drag = { x: touch.clientX, y: touch.clientY, dy: 0, time: performance.now(), active: false };
    }, { passive: true });
    sheet.addEventListener('touchmove', e => {
      if (!drag) return;
      if (e.touches.length !== 1) { reset(); return; }
      const dx = e.touches[0].clientX - drag.x, dy = e.touches[0].clientY - drag.y;
      if (!drag.active) {
        if (Math.hypot(dx, dy) < 9) return;
        if (dy <= 0 || Math.abs(dx) > dy / 1.25) { drag = null; return; }
        drag.active = true; sheet.classList.add('sheet-dragging');
      }
      e.preventDefault();
      drag.dy = Math.max(0, dy);
      sheet.style.transform = `translateY(${drag.dy}px)`;
      if (backdrop) backdrop.style.opacity = Math.max(.3, 1 - drag.dy / Math.max(300, sheet.clientHeight));
    }, { passive: false });
    sheet.addEventListener('touchend', e => {
      if (!drag) return;
      const old = drag; drag = null;
      if (!old.active) return;
      e.preventDefault(); suppressUntil = Date.now() + 400;
      sheet.classList.remove('sheet-dragging');
      if (old.dy > 100 || (old.dy > 36 && old.dy / Math.max(16, performance.now() - old.time) > .5)) {
        Promise.resolve(dismiss()).finally(reset);
      } else {
        const animation = sheet.animate([{ transform: sheet.style.transform }, { transform: 'translateY(0)' }], { duration: matchMedia('(prefers-reduced-motion: reduce)').matches ? 1 : 180, easing: 'ease-out', fill: 'both' });
        animation.finished.catch(() => {}).then(() => { animation.cancel(); reset(); });
      }
    }, { passive: false });
    sheet.addEventListener('touchcancel', reset);
    sheet.addEventListener('click', e => { if (Date.now() < suppressUntil) { e.preventDefault(); e.stopImmediatePropagation(); } }, true);
    return { reset };
  },
};

// Shared presentation timing for management and protected-album sheets.
window.PhotoSheetMotion = (()=>{
  const active=new WeakMap();
  function run(sheet,backdrop,opening,nested=false){
    const start=sheet.style.transform||getComputedStyle(sheet).transform||'translateY(0)',exitY=Math.max(window.innerHeight,sheet.getBoundingClientRect().height)+24;
    for(const animation of active.get(sheet)||[])animation.cancel();
    const duration=matchMedia('(prefers-reduced-motion: reduce)').matches?1:opening?480:420;
    const options={duration,easing:opening?'cubic-bezier(.22,.75,.2,1)':'cubic-bezier(.4,0,.65,1)',fill:'both'};
    const frames=opening?[{transform:`translateY(${exitY}px)`,opacity:1},{transform:'translateY(0)',opacity:1}]:[{transform:start,opacity:1},{transform:`translateY(${exitY}px)`,opacity:1}];
    const animations=[sheet.animate(frames,options)];
    if(backdrop&&!nested)animations.push(backdrop.animate(opening?[{opacity:0},{opacity:1}]:[{opacity:1},{opacity:0}],options));
    active.set(sheet,animations);
    return Promise.all(animations.map(a=>a.finished.catch(()=>{}))).then(()=>{if(active.get(sheet)!==animations)return;animations.forEach(a=>a.cancel());active.delete(sheet);});
  }
  const holders=new Map();let saved;
  function hold(owner){
    if(holders.has(owner))return;
    if(!holders.size){
      const body=document.body,app=document.querySelector('.app'),keys=['position','top','left','right','width'];
      saved={x:window.scrollX,y:window.scrollY,app,appStyles:app?Object.fromEntries(keys.map(key=>[key,app.style[key]])):null,bodyStyles:{overflow:body.style.overflow,minHeight:body.style.minHeight}};
      // Keep Safari's root canvas and fixed overlay viewport unchanged.
      // Only the underlying content is frozen at its original scroll position.
      const pageHeight=Math.max(document.documentElement.scrollHeight,body.scrollHeight,window.innerHeight);
      body.style.minHeight=`${pageHeight}px`;body.style.overflow='hidden';
      if(app)Object.assign(app.style,{position:'fixed',top:`${-saved.y}px`,left:'0',right:'0',width:'100%'});

    }
    holders.set(owner,[...document.querySelectorAll('.account-sheet,.manage-sheet')].filter(node=>node!==owner&&!node.closest('.hidden')).map(node=>({node,top:node.scrollTop,left:node.scrollLeft})));
  }
  function release(owner){
    const parents=holders.get(owner);if(!parents)return;holders.delete(owner);
    for(const {node,top,left} of parents)if(node.isConnected){node.scrollTop=top;node.scrollLeft=left;}
    if(holders.size||!saved)return;
    const old=saved;saved=null;if(old.app)Object.assign(old.app.style,old.appStyles);Object.assign(document.body.style,old.bodyStyles);
    const root=document.documentElement,behavior=root.style.scrollBehavior;root.style.scrollBehavior='auto';
    window.scrollTo({left:old.x,top:old.y,behavior:'instant'});root.style.scrollBehavior=behavior;
  }
  document.addEventListener('touchmove',event=>{if(holders.size&&!event.target.closest('[role=dialog]'))event.preventDefault();},{passive:false});
  return {locked:()=>holders.size>0,show:(s,b,n=false)=>run(s,b,true,n),hide:(s,b)=>run(s,b,false),hold,release};
})();
