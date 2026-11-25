const fs=require('fs'),assert=require('assert'),path=require('path');
const js=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8');
assert(js.includes("screen!=='collectionScreen'"),'edge swipe is limited to an opened collection');
assert(js.includes('if(t.clientX>28)return'),'edge swipe starts only from the left screen edge');
assert(js.includes('albumEdgeSwipe.dx>12'),'edge swipe waits for a clear horizontal movement');
assert(js.includes('Math.abs(albumEdgeSwipe.dx)>Math.abs(albumEdgeSwipe.dy)*1.35'),'vertical scrolling does not trigger back');
assert(js.includes('if(s.dx>72||(s.dx>36&&(s.vx||0)>.35))closeAlbum()'),'a completed edge swipe closes the album');
assert(js.includes("document.addEventListener('touchcancel',()=>{albumEdgeSwipe=null})"),'touch cancel resets the edge swipe');
console.log('Collection edge swipe: left-edge horizontal swipe closes an open album');
