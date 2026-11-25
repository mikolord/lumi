const fs=require('fs'),assert=require('assert'),p=require('path');
const js=fs.readFileSync(p.join(__dirname,'../app.js'),'utf8'),css=fs.readFileSync(p.join(__dirname,'../style.css'),'utf8');
assert(!/function hideVideo\(\)\{[^}]*cinema/.test(js),'hideVideo must not leave full screen');
assert(!/function syncVideo\(\)\{[^\n]*classList\.remove\('cinema'\)/.test(js),'syncVideo must not leave full screen');
assert(/busy=true;hideVideo\(\);exitCinema\(\);/.test(js),'closing the viewer leaves full screen');
assert(/wrap\.addEventListener\('click',e=>\{if\(e\.target===video/.test(js)&&!/getBoundingClientRect\(\),w=activePhoto\.naturalWidth/.test(js),'tap anywhere in the media area enters full screen');
assert(!/\.viewer\.cinema \.photo-wrap\{bottom:0\}/.test(css),'full screen keeps media size');
console.log('Full screen: enter anywhere, stays while swiping, same media size, exits on close');
