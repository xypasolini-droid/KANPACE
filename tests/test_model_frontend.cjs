const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const nodes=new Map(),node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',disabled:false,hidden:true,setAttribute(){},replaceChildren(...values){this.textContent=values.join('');}});return nodes.get(id);};
const context={console,URLSearchParams,location:{search:'?project=qa'},TextDecoder,Uint8Array,DataView,ArrayBuffer,DOMException,Promise,Math,Number,Set,JSON,THREE:{Box3:class{setFromObject(){return this;}getSize(){return {x:1,y:2,z:3};}},Vector3:class{}},document:{querySelector:node,createTextNode:s=>s},fetch:()=>Promise.reject(new Error('offline'))};vm.createContext(context);
const source=fs.readFileSync(path.join(__dirname,'../static/model/app.js'),'utf8').replace(/^import .*;\n/gm,'').split("\ndocument.querySelectorAll('[data-upload]')")[0];vm.runInContext(source,context);
const run=s=>vm.runInContext(s,context);
function glb(json){let text=JSON.stringify(json);while(text.length%4)text+=' ';const buffer=new ArrayBuffer(20+text.length),v=new DataView(buffer);v.setUint32(0,0x46546c67,true);v.setUint32(4,2,true);v.setUint32(8,buffer.byteLength,true);v.setUint32(12,text.length,true);v.setUint32(16,0x4e4f534a,true);new Uint8Array(buffer,20).set(Buffer.from(text));return buffer;}
(async()=>{
for(const payload of [{buffers:[{uri:'https://example.com/private.bin'}]},{images:[{uri:'../texture.png'}]},{accessors:[{type:'VEC3',count:5000000}]}]){context.testBuffer=glb(payload);assert.throws(()=>run('inspectGLB(testBuffer)'));}
context.testBuffer=glb({asset:{version:'2.0'},images:[{uri:'data:image/png;base64,AA=='}]});run('inspectGLB(testBuffer)');
run("model={name:'first'};activeDocument={id:'d1'};unit='mm';$('#model-unit').value='inch';");await run('saveUnit()');assert.equal(run('unit'),'mm');assert.equal(node('#model-unit').value,'mm');assert.equal(node('#model-unit').disabled,false);
let resolveFetch;context.fetch=()=>new Promise(resolve=>resolveFetch=resolve);run("$('#model-unit').value='cm'");const pending=run('saveUnit()');run("model={name:'second'};activeDocument={id:'d2'};unit='m';$('#model-unit').value='m';$('#model-unit').disabled=true;");resolveFetch({ok:true,json:async()=>({unit:'cm',links:{}})});await pending;assert.equal(run('unit'),'m');assert.equal(node('#model-unit').value,'m');assert.equal(node('#model-unit').disabled,true);
run("appState={parts:[{id:'p1',project_id:'qa',name:'侧板',revision:2,quantity:3,work_scopes:[{trade:'木工',title:'封边'}]}]};selected={name:'panel',userData:{meshKey:'mesh-0'}};linksState={links:{'mesh-0':{part_id:'p1',stale:true}}};renderInspector()");assert(node('#selected-detail').innerHTML.includes('拆单已更新，重新确认关联'));assert(!node('#selected-detail').innerHTML.includes('class="part-work"'));assert(node('#selected-detail').innerHTML.includes('重新确认关联'));
run("project={fulfillment_status:'shipped'};renderInspector()");assert(node('#selected-detail').innerHTML.includes('id=\"part-link\" disabled'));assert(!node('#selected-detail').innerHTML.includes('id=\"remove-link\"'));
let embedWrites=0;
const embedContext={...context,location:{search:'?project=qa&embed=1'},fetch:()=>{embedWrites++;throw new Error('Embed must not write');}};
vm.createContext(embedContext);vm.runInContext(source,embedContext);
await vm.runInContext('saveLink();saveUnit();uploadFile({name:"fixture.glb"})',embedContext);
assert.equal(embedWrites,0);
console.log('PASS: embedded-only GLB, geometry budget, unit failure rollback, stale model response isolation, and outdated BOM association visibility.');
})().catch(error=>{console.error(error);process.exitCode=1;});
