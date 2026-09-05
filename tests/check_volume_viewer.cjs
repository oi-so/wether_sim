// Pure JavaScript renderer/input unit test. No browser, network or UI automation.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(process.argv[2],'utf8');
const data=html.match(/<script id="data" type="application\/json">([\s\S]*?)<\/script>/)[1];
const script=html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
const elements=new Map(),queue=[],timers=new Map();let width=1280,height=640,primitives=0;
const context=new Proxy({}, {get:(o,k)=>o[k]??((...a)=>{for(const v of a)if(typeof v==='number')assert(Number.isFinite(v),`nonfinite canvas ${k}`);primitives++;}),set:(o,k,v)=>(o[k]=v,true)});
function element(id){if(elements.has(id))return elements.get(id);const e={id,value:'0',children:[],style:{},classList:{toggle(){}},append(c){this.children.push(c);},setAttribute(){},remove(){},addEventListener(){},setPointerCapture(){},getBoundingClientRect(){return {width,height,left:0,top:0};},getContext(){return context;}};elements.set(id,e);return e;}
for(const match of html.matchAll(/<input[^>]*id="([^"]+)"[^>]*>/g)){const e=element(match[1]);e.value=(match[0].match(/value="([^"]*)"/)||[])[1]||'0';}
element('data').textContent=data;element('speed').value='2';
const sandbox={document:{getElementById:element,createElement:()=>({dataset:{},children:[],classList:{toggle(){}},append(c){this.children.push(c);},setAttribute(){}}),addEventListener(){}},atob:t=>Buffer.from(t,'base64').toString('binary'),Float32Array,Uint8Array,console,devicePixelRatio:1,requestAnimationFrame:f=>queue.push(f),ResizeObserver:class{constructor(f){this.f=f}observe(){this.f();}},setInterval:f=>(timers.set(1,f),1),clearInterval:i=>timers.delete(i)};
vm.createContext(sandbox);vm.runInContext(script,sandbox,{timeout:10000});
function flush(){while(queue.length)queue.shift()();}
const read=s=>vm.runInContext(s,sandbox);flush();assert(primitives>100);
for(const key of ['temperature','humidity','wind','QCLOUD','QICE','CLDFRA','W','pressure']){read(`selectField('${key}')`);flush();assert(element('fieldTitle').textContent.length>0);assert(read('visible.length')>=0);}
element('next').onclick();flush();assert.equal(read('state.frame'),1);
element('play').onclick();timers.get(1)();flush();assert.equal(read('state.frame'),2);element('play').onclick();
const yaw=read('state.yaw');element('scene').onpointerdown({pointerId:1,clientX:30,clientY:30});element('scene').onpointermove({pointerId:1,clientX:80,clientY:40,pointerType:'touch'});element('scene').onpointerup({pointerId:1,clientX:80,clientY:40});flush();assert.notEqual(read('state.yaw'),yaw);
element('scene').onpointerdown({pointerId:1,clientX:20,clientY:20});element('scene').onpointerdown({pointerId:2,clientX:50,clientY:20});element('scene').onpointermove({pointerId:2,clientX:80,clientY:20,pointerType:'touch'});flush();assert(read('state.zoom')>1);element('scene').onpointercancel({pointerId:1});element('scene').onpointercancel({pointerId:2});
width=390;height=420;read('requestDraw()');flush();assert.equal(element('scene').width,390);
element('reset').onclick();flush();assert.equal(read('state.zoom'),1);
console.log(JSON.stringify({result:'pass',fields:8,frames:read('nt'),pointCount:read('count'),checks:['finite canvas coordinates','field switching','time stepping','playback','touch drag','pinch zoom','mobile canvas resize','camera reset']}));
