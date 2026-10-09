'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
// Validate the fixture through the real backend schema, so a misspelled single
// document_id cannot silently stand in for production document_ids.
const canonicalWorkObjects=JSON.parse(execFileSync('python3',['-c',`import json
import operations
class FixtureStore:
    def all(self, con, kind, project_id):
        return [{'id':'source-extra'},{'id':'d1'}] if kind == 'documents' else []
print(json.dumps(operations.validate_objects(FixtureStore(), None, 'p1', [{'code':'B1','name':'生产批','quantity':1,'unit':'批','document_ids':['source-extra','d1']}]), ensure_ascii=False))`],{cwd:path.join(__dirname,'..'),encoding:'utf8'}));
const app=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');
const range=(start,end)=>app.slice(app.indexOf(start),app.indexOf(end,app.indexOf(start)));
const shared=range('function projectWorkflowContext(', 'function projectHead(');
function boot(overrides={}){
  const c={console,URLSearchParams,Set,Map,Number,Array,workspaceType:'cabinet',search:'',tradeFilter:'',statusFilter:'',executionFocus:'all',trades:['木工','五金','玻璃'],tradeIcons:{},state:{projects:[{id:'p1',revision:2,factory_type:'cabinet',name:'测试订单',status:'review'}],parts:[],tasks:[],documents:[],people:[]},document:{},
    esc:v=>String(v??'').replace(/[&<>"]/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[x])),icon:()=>'',num:v=>String(v),button:(text,action)=>`<button data-action="${action}">${text}</button>`,empty:(title,description,action,label)=>`<h3>${title}</h3><p>${description}</p>${action?'<button data-action="'+action+'">'+label+'</button>':''}`,projectHead:()=>'',projectIsClosed:p=>!!p?.is_closed,executionSorted:v=>v,executionPriority:t=>t.priority||0,executionPerson:()=>null,executionCompleted:()=>null,executionRemaining:()=>null,executionStatusTag:t=>t.status,executionPriorityTag:()=>'',executionPauseNames:{},workspaceProfile:()=>({name:'展柜工厂',example:'展柜订单'}),operationsFactories:()=>[],openModal:(title,body,foot)=>{c.modal={title,body,foot};},toast:message=>{c.notice=message;},navigate:(...args)=>{c.navigation=args;},renderUploadQueue(){},...overrides};
  c.currentProject=()=>c.state.projects[0];c.tasks=()=>c.state.tasks;c.parts=()=>c.state.parts;c.docs=()=>c.state.documents;
  vm.createContext(c);
  vm.runInContext(app.split('\n').find(line=>line.startsWith('function historicalDemoIsComplete(')),c);
  vm.runInContext(shared,c);
  vm.runInContext(range('function reviewPanel(', 'function drawingView('),c);
  vm.runInContext(range('function taskView(', 'function projectList('),c);
  vm.runInContext(range('async function newProjectModal(', 'let uploadQueue='),c);
  vm.runInContext(range('function processBasisIsCurrent(', 'function uploadDocSummary('),c);
  vm.runInContext(range('let processBasisDialog=', 'function capabilitiesModal('),c);
  c.run=code=>vm.runInContext(code,c);return c;
}
function profile(extra={}){return {status:'installed',factory_id:'f1',factory_type:'cabinet',industry_id:'rattan',industry_name:'藤铁家居',nodes:[{name:'按样编织',trade:'编织'}],...extra};}

test('rattan and stone use work packages despite cabinet compatibility type',()=>{
  for(const industry of ['rattan','stone']){
    const c=boot();Object.assign(c.currentProject(),{industry_id:industry,factory_id:'f1'});
    c.kanpaceInstanceContext={profile:profile({industry_id:industry})};
    assert.equal(c.projectWorkflowContext(c.currentProject()).useWorkflow,true);
    assert.match(c.reviewPanel(),/工作包复核|打开项目工作包/);
    assert.match(c.taskView(),/data-action="ops-go-templates"/);
    assert.doesNotMatch(c.taskView()+c.reviewPanel(),/data-action="generate"|构件确认进度|开料 → 封边/);
  }
});
test('industry review shows this route roles, not generic cabinet coverage',()=>{
  const c=boot();Object.assign(c.currentProject(),{industry_id:'food',factory_type:'machinery',factory_id:'f1'});
  c.kanpaceInstanceContext={profile:profile({factory_type:'machinery',industry_id:'food',industry_name:'食品',nodes:[{trade:'备料',name:'原料验收'},{trade:'质检',name:'质量放行'}]})};
  const html=c.reviewPanel();assert.match(html,/原料验收|质量放行/);assert.doesNotMatch(html,/木工|五金|玻璃/);
});
test('selected industry without installed route clearly requests control setup',()=>{
  const c=boot();Object.assign(c.currentProject(),{industry_id:'food',factory_type:'machinery',factory_id:'f1'});
  assert.equal(c.projectWorkflowContext(c.currentProject()).needsConfiguration,true);
  assert.match(c.taskView()+c.reviewPanel(),/中台核对并启用本厂流程/);
  assert.doesNotMatch(c.taskView(),/data-action="generate"/);
});
test('installed profile does not silently capture unbound or another factory project',()=>{
  const c=boot();c.kanpaceInstanceContext={profile:profile()};
  assert.equal(c.projectWorkflowContext(c.currentProject()).useWorkflow,false);
  c.currentProject().factory_id='other';assert.equal(c.projectWorkflowContext(c.currentProject()).profile,null);
  c.currentProject().factory_id='f1';assert.equal(c.projectWorkflowContext(c.currentProject()).industryId,'rattan');
  c.currentProject().industry_id='stone';assert.equal(c.projectWorkflowContext(c.currentProject()).profile,null);
});
test('legacy cabinet generation remains while stale workflow tasks return to version review',()=>{
  const c=boot();assert.match(c.taskView(),/data-action="generate"/);
  assert.match(c.reviewPanel(),/构件确认进度/);
  c.currentProject().workflow_id='wf1';c.state.tasks=[{id:'t1',project_id:'p1',revision:1,status:'invalidated',name:'旧工序',trade:'编织'}];
  assert.match(c.taskView(),/核对工作包版本/);assert.doesNotMatch(c.taskView(),/data-action="generate"/);
});
test('even a stale generation action navigates industry users without requesting legacy generate',async()=>{
  const c=boot();c.currentProject().industry_id='stone';c.requests=[];c.api=async(...args)=>c.requests.push(args);c.submitOperation=async(_button,fn)=>fn();
  c.history={replaceState(){}};c.b={};c.p=c.currentProject();c.a='generate';
  await c.run('(async()=>{'+range("if(a==='generate'&&", "if(a==='release')")+'})()');
  assert.deepEqual(Array.from(c.navigation),['templates','parts','p1']);assert.equal(c.requests.length,0);
});
test('new order defaults to exact installed factory and never guesses among multiple factories',async()=>{
  const c=boot();c.operationsFactories=()=>[{id:'f1',name:'本厂'},{id:'f2',name:'另一工厂'}];
  c.kanpaceInstanceContext={profile:profile()};await c.newProjectModal();
  assert.match(c.modal.body,/<option value="f1" selected>本厂/);assert.match(c.modal.title,/藤铁家居/);
  c.kanpaceInstanceContext.profile.factory_id='foreign';await c.newProjectModal();assert.doesNotMatch(c.modal.body,/<option value="f[12]" selected>/);
});
test('process evidence verification expires with workflow revision or source hash',()=>{
  const c=boot();Object.assign(c.currentProject(),{workflow_id:'wf1'});
  const d={project_id:'p1',resolved:true,sha256:'hash',process_verification:{workflow_id:'wf1',workflow_version:3,project_revision:2,document_sha256:'hash'}};
  c.state.tasks=[{id:'t1',project_id:'p1',workflow_id:'wf1',workflow_version:3,revision:2,status:'draft'}];
  assert.equal(c.processBasisIsCurrent(d),true);
  c.state.tasks[0].workflow_version=4;assert.equal(c.processBasisIsCurrent(d),false);
  c.state.tasks[0].workflow_version=3;d.sha256='replaced';assert.equal(c.processBasisIsCurrent(d),false);
  d.sha256='hash';c.currentProject().revision=3;assert.equal(c.processBasisIsCurrent(d),false);
});
test('process evidence cannot be confirmed before linked reviewed current work package',async()=>{
  const c=boot();Object.assign(c.currentProject(),{workflow_id:'wf1',industry_id:'food'});
  c.state.documents=[{id:'d1',project_id:'p1',purpose:'process',filename:'批准工艺单.xlsx'}];
  c.operationsData={workflows:[{id:'wf1',project_id:'p1',status:'draft',revision:2,version:3,objects:structuredClone(canonicalWorkObjects)}]};
  c.ensureOperationsLoaded=async()=>{};await c.processBasisModal('d1');assert.doesNotMatch(c.modal.foot,/data-action="do-resolve"/);assert.match(c.modal.body,/复核当前工程版本/);
  c.operationsData.workflows[0].status='reviewed';await c.processBasisModal('d1');assert.match(c.modal.foot,/data-action="do-resolve"/);
  assert.match(c.modal.body,/已打开原件/);
  const calls=[];c.$=()=>({reportValidity:()=>true});c.formValues=()=>({note:'已核对本批工艺'});c.submitOperation=async(_b,fn)=>fn();c.api=async(...args)=>calls.push(args);
  await c.saveProcessBasis({dataset:{id:'d1'}});assert.equal(calls.length,1);assert.equal(calls[0][1].expected_workflow_version,3);assert.equal(calls[0][1].expected_revision,2);assert.equal(calls[0][1].acknowledge_process_basis,true);
});

test('task progress uses the configured package unit instead of hard-coded pieces',()=>{
  const c=boot();c.executionQuantity=t=>t.quantity;c.executionRecorded=()=>true;
  c.run(range('function executionProgress(', 'function executionCompletionNote('));
  const html=c.executionProgress({quantity:3,completed_quantity:1,unit:'批'});
  assert.match(html,/<small> 批<\/small>/);assert.doesNotMatch(html,/<small> 件<\/small>/);
  c.run(range('function executionCountInput(', 'function executionOperationForm('));
  assert.match(c.executionCountInput({quantity:3,completed_quantity:1,unit:'批'}),/累计已完成数量（批）/);
});

test('evidence membership uses the canonical multi-document array and rejects unlinked or scalar lookalikes',async()=>{
  const c=boot();Object.assign(c.currentProject(),{workflow_id:'wf1',industry_id:'food'});
  c.state.documents=[{id:'d1',project_id:'p1',purpose:'process',filename:'工艺资料.xlsx'}];
  const workflow={id:'wf1',project_id:'p1',status:'reviewed',revision:2,version:3,objects:structuredClone(canonicalWorkObjects)};
  c.operationsData={workflows:[workflow]};c.ensureOperationsLoaded=async()=>{};
  await c.processBasisModal('d1');assert.match(c.modal.foot,/data-action="do-resolve"/);
  workflow.objects[0].document_ids=['source-extra'];await c.processBasisModal('d1');assert.doesNotMatch(c.modal.foot,/data-action="do-resolve"/);
  delete workflow.objects[0].document_ids;workflow.objects[0].document_id='d1';
  await c.processBasisModal('d1');assert.doesNotMatch(c.modal.foot,/data-action="do-resolve"/);
});
test('industry source tab counts active process files while legacy tab counts parts',()=>{
  const c=boot();c.tab='parts';c.currentProject().industry_id='food';
  c.state.documents=[{id:'d1',purpose:'process'},{id:'d2',purpose:'render'},{id:'d3',purpose:'process',superseded:true},{id:'d4',purpose:'reference'}];
  c.run(range('function tabs(', 'function demoDrawing('));
  assert.match(c.tabs(),/工艺资料<span class="mono">1<\/span>/);
  delete c.currentProject().industry_id;assert.match(c.tabs(),/图纸与构件<span class="mono">0<\/span>/);
});

test('industry task trade filter contains only this project roles',()=>{
  const c=boot();Object.assign(c.currentProject(),{industry_id:'food',factory_type:'machinery',factory_id:'f1'});
  c.state.tasks=[{id:'t1',project_id:'p1',revision:2,status:'draft',name:'原料验收',trade:'备料'},{id:'t2',project_id:'p1',revision:2,status:'draft',name:'放行',trade:'质检'}];
  c.tradeFilter='木工';
  const html=c.taskView(),filter=html.match(/<select id="trade-filter"[^>]*>(.*?)<\/select>/)[1];
  assert.equal(c.tradeFilter,'');assert.match(html,/data-id="t1"/);
  assert.match(filter,/全部工种/);assert.match(filter,/备料/);assert.match(filter,/质检/);assert.doesNotMatch(filter,/木工|五金|玻璃/);
});
test('industry order heading does not describe order count as cabinet sets or task batches',()=>{
  const c=boot();Object.assign(c.currentProject(),{industry_id:'food',quantity:1});
  c.fulfillmentBadge=()=>'';c.tag=()=>'';c.date=()=>'';c.projectLifecycleActions=()=>'';c.projectReadOnlyNotice=()=>'';
  c.run(range('function projectHead(', 'function stageStrip('));
  assert.match(c.projectHead(),/订单数量 1/);assert.doesNotMatch(c.projectHead(),/1 套|1 批/);
  delete c.currentProject().industry_id;assert.match(c.projectHead(),/1 套/);
});
