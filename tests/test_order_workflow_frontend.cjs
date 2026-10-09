'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/order-workflow.js'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(){
  const mount={innerHTML:''},handlers={},requests=[],timers=new Map();let n=0;
  const c={console,URLSearchParams,AbortController,Set,Array,Object,Date,Number,String,Math,Blob,URL,
    page:'workflow',projectId:'A',accessState:null,location:{hash:'#page=workflow&stage=recognition'},
    project:{id:'A',revision:1},currentProject(){return c.project;},workspaceProjects(){return [c.project];},
    projectIsClosed(){return false;},icon:()=>'',esc:value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])),
    document:{hidden:true,activeElement:null,getElementById:id=>id==='order-workflow-content'?mount:null,addEventListener:(type,fn)=>(handlers[type]??=[]).push(fn)},
    setTimeout(fn,ms){timers.set(++n,{fn,ms});return n;},clearTimeout(id){timers.delete(id);},
    KanpaceHttp:{request(path,data,options){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});requests.push({path,data,options,resolve,reject});return promise;}},
  };c.window=c;vm.createContext(c);vm.runInContext(source,c);return {c,mount,requests,timers,handlers};
}
function answer(requests,id,name='当前订单资料.csv'){
  for(const req of requests){if(req.path.endsWith('/workflow'))req.resolve({project_id:id,revision:1,steps:[]});else req.resolve({sources:[{source_id:'doc:'+id,document_id:id,filename:name,source_revision:1,source_sha256:'a'.repeat(64),format:'csv'}],jobs:[],capabilities:{native_text:{available:true}}});}
}
async function previewFixture(){
  const f=fixture(),previews=[],highlights=[];let currentImage=null;
  f.c.uploadPreviewRequest=0;f.c.uploadPreviewDocument='';f.c.uploadPreviewPage=0;
  f.c.showError=error=>{throw error;};
  f.c.document.querySelector=()=>currentImage;
  f.c.document.createElement=()=>({style:{},setAttribute(){},append(child){
    if(child.documentId)this.image=child;
    if(child.style?.cssText)highlights.push({documentId:this.image.documentId,page:this.image.page,cssText:child.style.cssText});
  }});
  // The legacy preview renderer ignores superseded responses, but its promise
  // still resolves. The caller must not put an old box on the current image.
  f.c.previewUploadedDocument=(documentId,page)=>{
    const request=++f.c.uploadPreviewRequest;f.c.uploadPreviewDocument=documentId;f.c.uploadPreviewPage=page;
    return new Promise(resolve=>previews.push({documentId,page,resolve(){
      if(request===f.c.uploadPreviewRequest)currentImage={documentId,page,replaceWith(){}};
      resolve();
    }}));
  };
  const ref=(documentId,x)=>({document_id:documentId,raw_text:documentId,locator:{kind:'pdf_region',page:1,
    canonical_origin:'top_left',bbox_pdf_points:[x,0,x+10,10],page_size_pdf_points:[100,100]}});
  f.c.KanpaceOrderWorkflow.afterRender();
  f.requests[0].resolve({steps:[]});
  f.requests[1].resolve({sources:[],jobs:[{id:'rec_preview',status:'completed',sources:[]}],capabilities:{}});
  await tick();
  f.requests[2].resolve({job:{id:'rec_preview',status:'completed',sources:[],result:{evidence_refs:[ref('doc_A',10),ref('doc_B',50)]}}});
  await tick();
  const action=(workflowAction,index)=>f.handlers.click[0]({target:{closest:()=>({disabled:false,dataset:{workflowAction,index:String(index)}})}});
  return {...f,previews,highlights,action};
}
(async()=>{
  const f=fixture(),w=f.c.KanpaceOrderWorkflow;
  // A slow prior order cannot replace the currently selected project's evidence.
  w.afterRender();assert.equal(f.requests.length,2);assert(f.requests.every(r=>r.data===undefined));const old=f.requests.slice();
  f.c.project={id:'B',revision:1};w.afterRender();assert.equal(f.requests.length,4);assert(old.every(r=>r.options.signal.aborted));
  answer(f.requests.slice(2),'B','<img src=x onerror=alert(1)>.csv');await tick();
  assert(f.mount.innerHTML.includes('&lt;img'));assert(!f.mount.innerHTML.includes('<img src=x'));assert(f.mount.innerHTML.includes('/api/documents/B/download'));
  answer(old,'A','OLD_ORDER.csv');await tick();assert(!f.mount.innerHTML.includes('OLD_ORDER'));assert(f.mount.innerHTML.includes('/api/documents/B/download'));
  // Logout/reset invalidates all pending work, even if transport ignores cancellation.
  f.c.project={id:'C',revision:1};w.afterRender();const pending=f.requests.slice(4),before=f.mount.innerHTML;w.reset();answer(pending,'C','AFTER_LOGOUT.csv');await tick();assert.equal(f.mount.innerHTML,before);
  // The original PDF coordinate frame maps to percentages; no malformed frame is highlighted.
  const good={canonical_origin:'top_left',bbox_pdf_points:[50,100,150,200],page_size_pdf_points:[500,1000]};
  assert.deepEqual(JSON.parse(JSON.stringify(w.bboxPercent(good))),{left:10,top:10,width:20,height:10});
  for(const bad of [{...good,canonical_origin:'bottom_left'},{...good,bbox_pdf_points:[0,0,0,3]},{...good,bbox_pdf_points:[0,0,501,200]},{...good,bbox_pdf_points:[NaN,0,10,10]},{...good,page_size_pdf_points:[0,100]}])assert.equal(w.bboxPercent(bad),null);
  assert.equal(w.locate({locator:{kind:'table_cell',row:3,column:2}}),'第 3 行 · 2');
  assert(w.link('recognition','<& /订单').includes('project=%3C%26'));
  assert.equal(f.timers.size,0,'hidden documents do not poll');
  // An optional geometry step must not prevent an otherwise completed order reaching 100%.
  const optional=fixture();optional.c.KanpaceOrderWorkflow.afterRender();
  optional.requests[0].resolve({steps:optional.c.KanpaceOrderWorkflow.stages.map(([id])=>({id,state:id==='geometry'?'optional':'complete'}))});
  optional.requests[1].resolve({sources:[],jobs:[],capabilities:{}});await tick();
  assert(optional.mount.innerHTML.includes('/ 9 个必做阶段'));
  assert(optional.mount.innerHTML.includes('width:100%'));
  // A refresh while POST is pending must not orphan the write or leave the UI busy.
  const g=fixture();g.c.KanpaceOrderWorkflow.afterRender();answer(g.requests,'A');await tick();
  const act=(action,id)=>g.handlers.click[0]({target:{closest:()=>({disabled:false,dataset:{workflowAction:action,id}})}});
  g.handlers.change[0]({target:{id:'',checked:true,dataset:{workflowSource:'doc:A'}}});
  const write=act('recognize');assert.equal(g.requests[2].data.expected_revision,1);
  const refresh=act('sources-refresh');answer(g.requests.slice(3),'A');await refresh;
  g.requests[2].resolve({job:{id:'rec_one'}});await tick();answer(g.requests.slice(5),'A');await write;
  assert(!g.mount.innerHTML.includes('正在提交…'));
  await tick();const second=act('recognize');assert.equal(g.requests.length,8,'a later write remains possible');
  g.c.KanpaceOrderWorkflow.reset();g.requests[7].resolve({job:{id:'after_logout'}});await second;
  // GET transport errors are not invented failed jobs or resumable checkpoints.
  const h=fixture();h.c.KanpaceOrderWorkflow.afterRender();
  h.requests[0].resolve({steps:[]});h.requests[1].resolve({sources:[],jobs:[{id:'rec_existing',status:'completed',sources:[]}],capabilities:{}});await tick();
  h.requests[2].reject(new Error('服务器暂时不可达'));await tick();
  assert(h.mount.innerHTML.includes('任务结果暂时无法读取'));assert(!h.mount.innerHTML.includes('继续未完成资料'));
  // Two evidence previews resolve backwards: only B may be highlighted on B.
  const p=await previewFixture(),firstPreview=p.action('locate',0),secondPreview=p.action('locate',1);
  p.previews[1].resolve();await secondPreview;
  assert.deepEqual(p.highlights,[{documentId:'doc_B',page:1,cssText:'left:50%;top:0%;width:10%;height:10%'}]);
  p.previews[0].resolve();await firstPreview;
  assert.equal(p.highlights.length,1,'a superseded A preview must never paint its box on B');
  // A pending preview also loses authority when order/version/session/page changes.
  for(const invalidate of [
    f=>{f.c.project={id:'B',revision:1};f.c.KanpaceOrderWorkflow.afterRender();},
    f=>{f.c.project={id:'A',revision:2};f.c.KanpaceOrderWorkflow.afterRender();},
    f=>f.c.KanpaceOrderWorkflow.reset(),
    f=>{f.c.page='projects';f.c.KanpaceOrderWorkflow.afterRender();},
  ]){
    const scoped=await previewFixture(),pendingPreview=scoped.action('locate',0);
    invalidate(scoped);scoped.previews[0].resolve();await pendingPreview;
    assert.equal(scoped.highlights.length,0,'out-of-scope evidence must not paint coordinates');
  }
  console.log('PASS: transport contract, project races, logout, safe HTML, PDF bounds, table locations, deep links, hidden polling, POST/refresh race, GET errors, reversed previews, order/version/session/page preview invalidation.');
})().catch(err=>{console.error(err);process.exitCode=1;});
