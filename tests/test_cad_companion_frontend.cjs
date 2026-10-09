const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.join(__dirname,'../static');
const visual=fs.readFileSync(path.join(root,'project-visual.js'),'utf8');
const packet=fs.readFileSync(path.join(root,'order-packet.js'),'utf8');
const source={id:'doc_native',project_id:'project-a',filename:'柜体.SLDASM',sha256:'a'.repeat(64),purpose:'drawing'};
const pdf={id:'doc_pdf',project_id:'project-a',filename:'柜体核对图.pdf',sha256:'b'.repeat(64),purpose:'drawing',companion_for:[{document_id:source.id,sha256:source.sha256}]};
const dxf={id:'doc_dxf',project_id:'project-a',filename:'柜体尺寸.dxf',sha256:'c'.repeat(64),purpose:'drawing',geometry:[{units:'mm'}],companion_for:[{document_id:source.id,sha256:source.sha256}]};
const stale={id:'doc_stale',project_id:'project-a',filename:'过期核对图.pdf',sha256:'d'.repeat(64),purpose:'drawing',companion_for:[{document_id:source.id,sha256:'0'.repeat(64)}]};
const other={id:'doc_other',project_id:'project-b',filename:'其他订单.pdf',sha256:'e'.repeat(64),purpose:'drawing',companion_for:[{document_id:source.id,sha256:source.sha256}]};
const documents=[source,pdf,dxf,stale,other];
const context={console,URL,Map,Set,Math,Number,Array,Promise,Uint8Array,globalThis:null,
  state:{projects:[{id:'project-a',name:'测试工程'}],documents,parts:[]},draftMediaCache:new Map(),projectId:'project-a',uploadBusy:false,
  esc:s=>String(s??'').replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;'),icon:()=>'',
  button:(label,action,icon,cls,attrs)=>`<button data-action="${action}" ${attrs||''}>${label}</button>`,
  currentProject(){return context.state.projects[0]},projectIsClosed:p=>Boolean(p.closed),
  docs(){return documents.filter(d=>d.project_id==='project-a')},draftMediaUnique:x=>x,draftMediaURL:x=>x,
  uploadDocIsPdf:d=>/\.pdf$/i.test(d.filename),uploadDocIsModel:d=>/\.(step|stp|iges|igs|brep|glb|obj|stl)$/i.test(d.filename),
  uploadPreviewSrc:(d,thumb)=>`/api/documents/${d.id}/preview-image?page=1${thumb?'&thumb=1':''}`,
  uploadDocSummary:()=>'',uploadRelated:()=>'',uploadModelLink:d=>/\.step$/i.test(d.filename)?'<a>查看 3D 模型</a>':'',
  projectWorkflowContext:()=>({}),draftMediaCache:new Map()};
context.globalThis=context;
vm.createContext(context);
vm.runInContext(visual.split("document.addEventListener('click'")[0],context);
let linked=vm.runInContext('projectVisualCompanions(state.documents[0],state.documents).map(d=>d.id)',context);
assert.deepEqual(Array.from(linked),['doc_pdf','doc_dxf']);
let card=vm.runInContext('projectVisualEngineeringCard(state.documents[0],state.documents)',context);
assert.match(card,/data-action="upload-companion" data-id="doc_native"/);
assert.match(card,/data-action="preview-upload" data-id="doc_pdf"/);
assert.match(card,/doc_pdf\/preview-image\?page=1&amp;thumb=1/);
assert.match(card,/data-action="project-geometry" data-id="doc_dxf"/);
assert.doesNotMatch(card,/过期核对图|其他订单|导入 \/ 查看工程模型/);
assert.match(vm.runInContext('projectVisualEngineeringCard(state.documents[3],state.documents)',context),/关联原件已更新/);
let panel=vm.runInContext('projectEngineeringPanel()',context);
assert.match(panel,/柜体\.SLDASM/);
assert.doesNotMatch(panel,/导入 \/ 查看工程模型/);
context.state.projects[0].closed=true;
card=vm.runInContext('projectVisualEngineeringCard(state.documents[0],state.documents)',context);
assert.doesNotMatch(card,/upload-companion/);
context.state.projects[0].closed=false;

const bomFns=packet.slice(packet.indexOf('function orderPacketSource('),packet.indexOf('const packetOriginalCard='));
vm.runInContext(bomFns,context);
const row={name:'侧板',specification:'600×400',note:'密度板',per_assembly_quantity:2,parent:'高柜工程图',evidence:{document_id:pdf.id,page:3,sha256:pdf.sha256}};
context.row=row;
let cell=vm.runInContext('orderPacketSourceCell(row)',context);
assert.match(cell,/doc_pdf\/preview-image\?page=3&amp;thumb=1/);
assert.match(cell,/整页缩略图/);
assert.match(cell,/data-document="doc_pdf" data-page="3"/);
let bom=vm.runInContext('orderPacketBom({name:"高柜",engineering_bom:[row]})',context);
assert.match(bom,/侧板/);
assert.match(bom,/构件清单/);
context.row={...row,evidence:{...row.evidence,sha256:'0'.repeat(64)}};
assert.match(vm.runInContext('orderPacketSourceCell(row)',context),/来源图已更新/);
assert.doesNotMatch(vm.runInContext('orderPacketSourceCell(row)',context),/preview-image/);
console.log('PASS: SHA-pinned CAD companions and source-PDF page thumbnails');
