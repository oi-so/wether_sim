// Run against a generated small HTML fixture. This checks application logic,
// not GPU shader compilation or a browser's actual pointer implementation.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2],'utf8');
const payload=html.match(/<script id="data" type="application\/json">([\s\S]*?)<\/script>/)[1];
const code=html.split('<script>')[1].split('</script>')[0];
const nodes=new Map();
class Node {
 constructor(id){this.id=id;this.children=[];this.style={};this.dataset={};this.classList={toggle(){}};this.value='';this.textContent='';this.listeners={};this.width=800;this.height=600;}
 append(x){this.children.push(x)} replaceChildren(){this.children=[]} setAttribute(k,v){this[k]=v} remove(){} addEventListener(k,v){this.listeners[k]=v}
 getBoundingClientRect(){return {width:800,height:600,left:0,top:0}} setPointerCapture(){}
 getContext(type){return type==='webgl'?gl:ctx;}
}
const calls=[];
const gl=new Proxy({getShaderParameter:()=>true,getProgramParameter:()=>true,getAttribLocation:()=>0,getUniformLocation:(_,n)=>n,
 bufferData:(_,data)=>{assert([...data].every(Number.isFinite),'nonfinite rendered geometry');},drawArrays:(...args)=>calls.push(args)},
 {get:(o,k)=>k in o?o[k]:k.toUpperCase()===k?k:()=>({})});
const ctx=new Proxy({}, {get:()=>()=>{}});
for(const m of html.matchAll(/id="([^"]+)"/g))nodes.set(m[1],new Node(m[1]));
nodes.get('data').textContent=payload;
for(const [k,v] of Object.entries({low:0,high:15,threshold:1,opacity:.65,exaggeration:2,zoom:1,speed:2,renderMode:'mesh',mode:'3d',interaction:'orbit'}))nodes.get(k).value=String(v);
const frames=[];
const context=vm.createContext({console,atob:s=>Buffer.from(s,'base64').toString('binary'),document:{getElementById:k=>nodes.get(k),createElement:()=>new Node(),addEventListener(){},querySelectorAll:()=>[]},
 Image:class{set src(v){if(this.onload)this.onload()}},ResizeObserver:class{observe(){}},requestAnimationFrame:f=>frames.push(f),devicePixelRatio:1,setInterval:()=>1,clearInterval(){},location:{}});
vm.runInContext(code,context);
function flush(){while(frames.length)frames.shift()();}
function evalCode(code){return vm.runInContext(code,context);}
flush();assert(calls.length>0);assert.equal(nodes.get('loading').hidden,true);
assert.equal(evalCode('geometry.length/6'),18,'2x2 grid at three heights becomes six connected triangles');
const canvas=nodes.get('scene');
canvas.onpointerdown({pointerId:1,clientX:10,clientY:10,button:0});
canvas.onpointermove({pointerId:1,clientX:10,clientY:-300,shiftKey:false});
canvas.onpointerup({pointerId:1});flush();assert(evalCode('state.elevation')<0,'side and underside view allowed');
canvas.onpointerdown({pointerId:1,clientX:10,clientY:10,button:2});
canvas.onpointermove({pointerId:1,clientX:60,clientY:30});canvas.onpointerup({pointerId:1});flush();assert(evalCode('state.target.some(v=>v!==0)'),'right drag pans');
canvas.onpointerdown({pointerId:1,clientX:10,clientY:10,button:0});canvas.onpointerdown({pointerId:2,clientX:30,clientY:10,button:0});
const zoom=evalCode('state.zoom');canvas.onpointermove({pointerId:2,clientX:60,clientY:25});flush();assert(evalCode('state.zoom')>zoom,'two-finger pinch zooms');canvas.onpointercancel({pointerId:1});canvas.onpointercancel({pointerId:2});assert.equal(evalCode('pointers.size'),0);
nodes.get('mode').value='2d';nodes.get('mode').onchange();flush();assert.equal(evalCode('state.mode'),'2d');assert.equal(nodes.get('fields').children.length,13);assert.equal(evalCode('geometry.length/6'),6);
for(const b of nodes.get('fields').children){b.onclick();flush();assert(nodes.get('fieldTitle').textContent.length>0);}
nodes.get('frame').value='1';nodes.get('frame').oninput();flush();assert.equal(evalCode('state.frame'),1);
nodes.get('mode').value='3d';nodes.get('mode').onchange();flush();assert(evalCode('state.elevation')<0,'3D viewpoint restored');
nodes.get('renderMode').value='points';nodes.get('renderMode').onchange();flush();assert.equal(evalCode('geometry.length/6'),12);
console.log('PASS: mesh topology, all 13 surface fields, frame change, unrestricted orbit, pan, two-pointer pinch, cancellation, mode/viewpoint restore, point mode. GPU rendering is not exercised.');
