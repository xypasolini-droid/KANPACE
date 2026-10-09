const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const c={console,URL,Map,Set,Promise,Number,String,Array,Math,HTMLInputElement:class{},HTMLImageElement:class{},requestAnimationFrame:fn=>fn(),location:{origin:'http://127.0.0.1:8765'},document:{activeElement:null,addEventListener(){},getElementById(){return null}},window:{scrollX:20,scrollY:200,scrollTo(){},addEventListener(){}},renders:0,requests:[],page:'drawing',tab:'parts'};
vm.createContext(c);vm.runInContext(`
let project={id:'p1',name:'深圳博物馆',order_draft:{issues:[],source_revision:'G01'}};
const state={documents:[],get projects(){return [project]}};
let allParts=[{id:'x1',project_id:'p1',source:{part_number:'A-1'},name:'高柜 <script>坏</script>',quantity:1,quantity_unit:'套',item_level:'assembly',material:'木作 & 玻璃',specification:'6300 × 600 × 3000',evidence:[],work_scopes:[{trade:'木工',title:'柜体开料与封边'}]}];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=n=>n==null?'—':String(n),parts=()=>allParts,currentProject=()=>project,icon=s=>'<i></i>',button=(text,action,icon,cls,extra='')=>'<button data-action="'+action+'" '+extra+'>'+text+'</button>',date=s=>s,localTimestamp=s=>s||'未记录',historyView=()=>'',uploadDocumentsPanel=()=>'<div id="uploads">已上传图纸</div>';
const trades=['木工','玻璃'],tradeIcons={木工:'ruler',玻璃:'glass'};
function render(){renders++;}function api(path){return new Promise((resolve,reject)=>requests.push({path,resolve,reject}));}function toast(){}
`,c);
// Exercise the same lifecycle helpers used by the main shell; missing helper
// dependencies should fail this fixture instead of being replaced by stubs.
const appLines=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8').split('\n');
for(const prefix of ['const fulfillmentNames=','function projectIsClosed(','function historicalDemoIsComplete(','function fulfillmentStatus(','function fulfillmentBadge(','function projectLifecycleActions(','function projectReadOnlyNotice(','function docs(','function uploadDocIsModel(','function uploadDocIsPdf(','function uploadDocSummary(','function uploadRelated(','function uploadModelLink(','function uploadPreviewSrc(']){
  const line=appLines.find(line=>line.startsWith(prefix));assert(line,'missing shell dependency: '+prefix);vm.runInContext(line,c);
}
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/order-drafts.js'),'utf8'),c);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/project-visual.js'),'utf8'),c);
function get(expr){return vm.runInContext(expr,c);}
(async()=>{
const a=get('orderDraftView()');assert(a.includes('上传图纸'));assert(!a.includes('/model/index.html?project=p1'),'do not show a 3D viewer when no real model was uploaded');assert(!a.includes('id="uploads"'),'uploaded engineering cards must not precede the project hero');assert(get('draftSourceList()').includes('id="uploads"'),'uploaded files remain available under source files');assert(a.includes('整体效果图'));assert(a.includes('加工图与清单'));assert(a.includes('正在加载对应图纸'));assert(!a.includes('<script>坏'));
get('orderDraftView()');assert.equal(c.requests.length,1,'cached loading request should not refetch');
get("project={id:'p2',name:'other',order_draft:{issues:[],source_revision:'G01'}};ensureDraftMedia(project)");assert.equal(c.requests.length,2);
c.requests[0].resolve({parts:{'A-1':[{id:'one',url:'/api/drawing-media/full.png',thumb_url:'/api/drawing-media/thumb.png',source_file:'施工图.pdf',page:1,kind:'施工图'}]}});await new Promise(r=>setImmediate(r));assert.equal(c.renders,0,'old project response should not rerender current project');
c.requests[1].reject(new Error('offline'));await new Promise(r=>setImmediate(r));assert.equal(c.renders,1);assert(get('draftMediaStatus()').includes('重新加载'));
get("project={id:'p1',name:'深圳博物馆',order_draft:{issues:[],source_revision:'G01'}}");assert(get('draftCard(allParts[0])').includes('/api/drawing-media/thumb.png'));assert(get('draftScopes()').includes('draft-work-card'));assert(!get('draftScopes()').includes('<table>'));
for(const status of ['completed','shipped']){
  get(`project.fulfillment_status='${status}';project.is_closed=true`);
  const closed=get('orderDraftView()');
  assert(/<button[^>]*data-action="import"[^>]*\bdisabled\b/.test(closed),'closed draft upload must be disabled');
  assert(closed.includes('重新打开项目'));assert(closed.includes('图纸与任务只读'));
  assert(closed.includes(status==='shipped'?'项目已发货':'项目已完成'));
  assert(!closed.includes('data-status="completed"'),'closed draft cannot offer mark-completed action');
  assert(!closed.includes('/model/index.html?project=p1'),'closing an order cannot create a model that was never uploaded');
  assert(closed.includes('/api/drawing-media/thumb.png'),'closed source drawings remain viewable');
}
get("project.fulfillment_status='active';project.is_closed=false");
const reopened=get('orderDraftView()');assert(!/<button[^>]*data-action="import"[^>]*\bdisabled\b/.test(reopened));assert(!reopened.includes('图纸与任务只读'));assert(reopened.includes('标记完成'));
assert.equal(get("draftMediaURL('https://attacker.invalid/image.png')"),'');assert.equal(get("draftMediaURL('javascript:alert(1)')"),'');
get('ensureDraftMedia(project,true)');get('ensureDraftMedia(project,true)');c.requests[3].resolve({parts:{'A-1':[{id:'new',url:'/api/media/new.png'}]}});await new Promise(r=>setImmediate(r));c.requests[2].resolve({parts:{'A-1':[{id:'stale',url:'/api/media/stale.png'}]}});await new Promise(r=>setImmediate(r));assert.equal(get('draftMediaEntries(allParts[0])[0].id'),'new','stale refresh must not replace later response');
console.log('PASS: upload/3D entries, closed draft read-only and reopening, escaped real text, per-project cache, stale navigation/refresh guard, recoverable fetch failure, image cards, image work scopes, and URL validation.');
})().catch(e=>{console.error(e);process.exitCode=1});
