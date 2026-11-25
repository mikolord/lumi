const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(require('path').join(__dirname,'../app.js'),'utf8');
let cinema=false,dark=false,color='#161719';
const root={dataset:{},classList:{toggle(){}}};
const context={document:{documentElement:root,querySelector:()=>({setAttribute:(key,value)=>{color=value}})},viewer:{classList:{contains:()=>cinema}},matchMedia:()=>({matches:dark})};
vm.createContext(context);
vm.runInContext(source.match(/function syncSystemBackdrop\(\)\{[^\n]+/)[0],context);
function check(expectedTheme,expectedColor){context.syncSystemBackdrop();assert.equal(root.dataset.theme,expectedTheme);assert.equal(color,expectedColor)}
check('light','#161719');
cinema=true;check('dark','#161719');
dark=true;check('dark','#161719');
cinema=false;check('dark','#161719');
dark=false;check('light','#161719');
cinema=true;check('dark','#161719');
cinema=false;check('light','#161719');
assert(!/setAttribute\('content'/.test(source),'theme-color is never changed from JS (AGENTS.md)');
console.log('Cinema theme override and system-theme restoration passed (theme-color stays #161719)');

context.PHOTO_THEME='light';cinema=false;dark=true;check('light','#161719');
context.PHOTO_THEME='dark';dark=false;check('dark','#161719');
context.PHOTO_THEME='light';cinema=true;check('dark','#161719');cinema=false;check('light','#161719');
