const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=['operations.js','operations-production.js','operations-finance.js','operations-commercial.js','operations-migration.js','operations-exchange.js','operations-scheduling.js','operations-calibration.js'].map(name=>fs.readFileSync(path.join(__dirname,'../static',name),'utf8')).join('\n');
const tests=[];const test=(name,fn)=>tests.push([name,fn]);
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};};
function fixture(){
  const elements={'#modal':{open:true,classList:{add(){},remove(){}}},'#modal .dialog-error':{textContent:'',insertAdjacentHTML(_,value){this.extra=value}},'#ops-record-form':{reportValidity:()=>true,querySelectorAll:()=>[]},'#ops-resource-form':{reportValidity:()=>true}};
  const c={console,URLSearchParams,Date,Set,Map,Math,JSON,Number,String,Array,document:{addEventListener(){},createElement:()=>({append(){}})},workspaceType:'cabinet',page:'people',state:{projects:[{id:'cab',name:'客户甲',factory_type:'cabinet'},{id:'mach',name:'设备乙',factory_type:'machinery'}],tasks:[{id:'t1',project_id:'cab',title:'开料',trade:'木工',status:'ready',execution_version:4}],people:[]},requests:[],values:{},renders:0,esc:s=>String(s??'').replace(/[&<>"]/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[x])),num:n=>n==null?'—':String(n),money:n=>n==null?'待核对':'¥ '+n,icon:()=>'',button:(label,action,i,cls,extra)=>`<button data-action="${action}" ${extra||''}>${label}</button>`,statusText:{ready:'待开工'},localTimestamp:x=>x||'—',taskProjectIsClosed:()=>false,projectIsClosed:p=>!!p?.is_closed,showError:e=>{c.error=e.message},toast:t=>{c.toast=t},closeModal:()=>{c.closed=true},openModal:(title,body,foot)=>{c.modal={title,body,foot}},$:selector=>elements[selector],formValues:()=>c.values,currentProject:()=>c.state.projects[0],navigate:p=>{c.navigated=p},taskModal:()=>{},refresh:async()=>{},render:()=>{c.renders++},executionRequest:async(url,data)=>{c.requests.push({url,data});return c.reply?c.reply(url,data):{};}};
  vm.createContext(c);vm.runInContext(source,c);const run=code=>vm.runInContext(code,c);
  c.data={factories:[{id:'f1',name:'展柜一厂',factory_type:'cabinet'},{id:'f2',name:'设备二厂',factory_type:'machinery'}],teams:[],workcenters:[],people:[{id:'p1',name:'张三',factory_id:'f1',skills:['木工'],capacity_minutes:null},{id:'p2',name:'李四',factory_id:'f2',skills:['装配'],capacity_minutes:480},{id:'p3',name:'待归属',factory_id:null,skills:['五金']},{id:'pd',name:'演示人员',demo:true,factory_id:null,skills:['木工']}],templates:[],workflows:[],builtin_templates:[]};run('operationsData=data');
  return {c,run,elements};
}
test('resources filter the selected factory type and mark unassigned staff',()=>{const {run}=fixture();assert.deepEqual(Array.from(run('operationsPeople().map(p=>p.id)')),['p1','p3']);const html=run('operationsPeopleView()');assert(html.includes('待分配工厂'));assert(!html.includes('李四'));assert(!html.includes('演示人员'));assert(html.includes('待核定'));});
test('explicit factory filter excludes unassigned people without losing them',()=>{const {run}=fixture();run("operationsFactory='f1'");assert.deepEqual(Array.from(run('operationsPeople().map(p=>p.id)')),['p1']);run("operationsFactory=''");assert(run('operationsPeople().some(p=>p.id==="p3")'));});
test('demo records require explicit toggle',()=>{const {run}=fixture();run('operationsShowDemo=true');assert(run('operationsPeopleView()').includes('演示人员'));assert(run('operationsPeopleView()').includes('演示</span>'));});
test('resource labels and task notes are HTML escaped',()=>{const {c,run}=fixture();c.data.people[0].name='<img src=x onerror=alert(1)>';assert(!run('operationsPeopleView()').includes('<img src=x'));assert(run('operationsPeopleView()').includes('&lt;img'));});
test('person editor saves active or left status and shows work needing reassignment',async()=>{
  const {c,run}=fixture();c.data.people[0].employment_status='left';c.data.people[0].version=3;
  c.state.tasks=[{id:'t-left',project_id:'cab',status:'ready',assignee:null,reassignment_from:'p1'}];
  const table=run('operationsPeopleView()');assert(table.includes('已离职'));assert(table.includes('待重新分派 1 道'));
  run("operationsResourceEditor('people','p1')");
  assert(c.modal.body.includes('name="employment_status"'));
  assert(c.modal.body.includes('<option value="left" selected>离职</option>'));
  assert(c.modal.body.includes('进行中需先暂停交接'));
  c.values={name:'张三',role:'木工',skills:'木工',factory_id:'f1',team_id:'',capacity_hours:'8',employment_status:'left'};
  c.b={disabled:false,isConnected:true,innerHTML:'保存'};
  await run('operationsResourceSave(b)');
  assert.equal(c.requests[0].data.employment_status,'left');
  assert.equal(c.requests[0].data.expected_version,3);
  assert.match(c.toast,/待重新分派/);
});
test('people Excel preview exposes automatically recognized employment status without extra mapping steps',async()=>{
  const {c,run}=fixture();run("operationsExchangeType='people'");
  assert(run('operationsExchangeFields().some(field=>field.key===\"employment_status\")'));
  assert(run('operationsExchangeView()').includes('在职状态自动识别'));
  c.btoa=value=>Buffer.from(value,'binary').toString('base64');
  c.file={name:'工厂人员.xlsx',size:4,arrayBuffer:async()=>Uint8Array.from([1,2,3,4]).buffer};
  run('operationsExchangeFile=file');
  c.reply=async()=>({preview:{id:'preview-people',entity_type:'people',headers:['姓名','员工状态'],mapping:{name:'姓名',employment_status:'员工状态'},rows:[{row_number:2,action:'update',data:{name:'李师傅',employment_status:'left'}}]}});
  await run('operationsExchangeRead(null)');
  assert.equal(c.requests[0].data.auto_map,true);
  assert.equal(run('operationsExchangeMapping.employment_status'),'员工状态');
  const preview=run('operationsExchangePreviewView()');
  assert(preview.includes('<th>在职状态</th>'));
  assert(preview.includes('<td>离职</td>'));
});
test('unknown daily capacity does not default to an eight hour shift',()=>{const {run}=fixture();assert.equal(run('operationsHours(null)'),'待核定');assert.equal(run('operationsHours(480)'),'8 h / 日');});
test('DAG validation accepts parallel join and rejects cycle',()=>{const {c,run}=fixture();c.nodes=[{id:'a',name:'拆单',trade:'技术',predecessors:[]},{id:'b',name:'木作',trade:'木工',predecessors:['a']},{id:'c',name:'五金',trade:'五金',predecessors:['a']},{id:'d',name:'总装',trade:'装配',predecessors:['b','c']}];assert.equal(run('operationsValidateNodes(nodes).length'),0);c.nodes[0].predecessors=['d'];assert(run('operationsValidateNodes(nodes)').some(x=>x.includes('循环')));});
test('DAG validation rejects duplicate IDs and missing predecessor',()=>{const {c,run}=fixture();c.nodes=[{id:'a',name:'A',trade:'技术',predecessors:['missing']},{id:'a',name:'B',trade:'木工',predecessors:[]}];const errors=run('operationsValidateNodes(nodes)');assert(errors.some(e=>e.includes('重复')));assert(errors.some(e=>e.includes('无效')));});
test('published template copy keeps original immutable and stores source',()=>{const {c,run}=fixture();c.data.templates=[{id:'tpl',name:'企业模板',version:3,status:'published',factory_type:'cabinet',nodes:[{id:'wood',name:'木作',trade:'木工',predecessors:[],start_checks:[],acceptance:[]}]}];run("operationsTemplateEditor('tpl',true)");assert.equal(run('operationsDialog.draft.id'),undefined);assert.equal(run('operationsDialog.draft.source_template_id'),'tpl');run("operationsDialog.draft.nodes[0].name='修改'");assert.equal(c.data.templates[0].nodes[0].name,'木作');});
test('unknown node duration remains blank in template editor',()=>{const {c,run}=fixture();c.data.templates=[{id:'tpl',name:'模板',factory_type:'cabinet',nodes:[{id:'n',name:'木作',trade:'木工',estimated_minutes:null}]}];run("operationsTemplateEditor('tpl')");assert(/data-node-field="estimated_hours"[^>]*value=""/.test(c.modal.body));});
test('reference template cannot directly create production tasks',()=>{const {c,run}=fixture();c.data.builtin_templates=[{id:'builtin',name:'参考',factory_type:'cabinet',status:'reference',nodes:[]}];run("operationsWorkflowEditor('builtin')");assert.equal(c.modal,undefined);assert.equal(c.requests.length,0);});
test('older operations response cannot replace a newer workspace',async()=>{const {c,run}=fixture();const first=deferred(),second=deferred();c.reply=url=>url.includes('factory_type=cabinet')?first.promise:second.promise;const old=run('ensureOperationsLoaded(true)');run("workspaceType='machinery';operationsReset()");const newer=run('ensureOperationsLoaded()');second.resolve({...c.data,marker:'new'});await newer;first.resolve({...c.data,marker:'old'});await old;assert.equal(run('operationsData.marker'),'new');});
test('network failure is not retried on every render',async()=>{const {c,run}=fixture();c.reply=async()=>{throw new Error('离线')};await run('ensureOperationsLoaded(true)');await run('ensureOperationsLoaded()');assert.equal(c.requests.length,1);assert.equal(run('operationsError'),'离线');});
test('resource update carries version and leaves conflict form intact',async()=>{const {c,run,elements}=fixture();run("operationsDialog={kind:'people',entity:{id:'p1',version:7},type:'resource'}");c.values={name:'张三',role:'木工组长',skills:'木工，装配',factory_id:'f1',team_id:'',capacity_hours:''};c.b={disabled:false,isConnected:true,innerHTML:'保存'};c.reply=async()=>{const error=new Error('版本冲突');error.status=409;throw error;};await run('operationsResourceSave(b)');assert.equal(c.requests[0].data.expected_version,7);assert.equal(c.requests[0].data.capacity_minutes,null);assert.deepEqual(Array.from(c.requests[0].data.skills),['木工','装配']);assert.equal(c.closed,undefined);assert.equal(c.b.disabled,false);assert.equal(elements['#modal .dialog-error'].textContent,'版本冲突');});
test('production rows stay scoped to the factory type',()=>{const {c,run}=fixture();c.production={projects:c.state.projects,materials:[{id:'a',project_id:'cab'},{id:'b',project_id:'mach'}]};run('operationsProductionData=production');assert.deepEqual(Array.from(run('operationsProductionRows("materials").map(r=>r.id)')),['a']);});
test('production subpages show only neighbouring stage tabs and omit a redundant single tab',()=>{
  const {c,run}=fixture();
  for(const [current,expected,label] of [['materials',[],null],['checks',[],null],['issues',[],null],['inspections',['inspections','deliveries'],'验收发货'],['deliveries',['inspections','deliveries'],'验收发货'],['costs',['costs','commercial'],'成本款项'],['commercial',['costs','commercial'],'成本款项']]){
    c.current=current;run('operationsProductionTab=current');const html=run('operationsReadinessView()');
    assert.deepEqual([...html.matchAll(/data-action="ops-production-tab" data-id="([^"]+)"/g)].map(match=>match[1]),expected);
    if(label)assert(html.includes(`aria-label="${label}"`));else assert(!html.includes('role="tablist"'));
    assert.equal(run('operationsProductionTab'),current);
  }
  assert.equal(c.requests.length,0);
});
test('production stage tabs honour independent module switches and financial access',()=>{
  const {c,run}=fixture();c.window={kanpaceInstanceContext:{profile:{enabled_modules:['readiness','deliveries','costs','commercial']}}};c.accessState={enabled:true,financial_access:false};
  run("operationsProductionTab='materials'");let html=run('operationsReadinessView()');assert(!html.includes('role="tablist"'));assert(!html.includes('开工检查'));
  run("operationsProductionTab='inspections'");html=run('operationsReadinessView()');assert.equal(run('operationsProductionTab'),'deliveries');assert(html.includes('<h1>发货与交付</h1>'));assert(!html.includes('质量验收'));
  run("operationsProductionTab='costs'");html=run('operationsReadinessView()');assert.equal(run('operationsProductionTab'),'materials');assert(!html.includes('成本与款项'));assert(!html.includes('变更与收款'));
  c.accessState.financial_access=true;run("operationsProductionTab='commercial'");html=run('operationsReadinessView()');assert(html.includes('data-id="costs"'));assert(html.includes('data-id="commercial"'));
  assert.equal(c.requests.length,0);
});
test('production view without enabled modules has no create action or fabricated records',()=>{
  const {c,run}=fixture();c.window={kanpaceInstanceContext:{profile:{enabled_modules:[]}}};const html=run('operationsReadinessView()');
  assert(html.includes('当前工厂尚未启用这项功能'));assert(!html.includes('data-action="ops-record-new"'));assert(!html.includes('role="tablist"'));assert.equal(c.requests.length,0);
});
test('readiness late response does not leak previous workspace data',async()=>{const {c,run}=fixture();const old=deferred();c.reply=()=>old.promise;const pending=run('ensureOperationsReadiness(true)');run("workspaceType='site';operationsReadinessReset()");c.reply=async()=>({marker:'site'});await run('ensureOperationsReadiness()');old.resolve({marker:'cabinet'});await pending;assert.equal(run('operationsProductionData.marker'),'site');});
test('resolving issue requires a recorded conclusion before write',async()=>{const {c,run,elements}=fixture();run("operationsProductionDialog={kind:'issue',row:{id:'i1',version:4}}");c.values={project_id:'cab',status:'resolved',resolution:'  ',title:'玻璃破损'};c.b={disabled:false};await run('operationsRecordSave(b)');assert.equal(c.requests.length,0);assert(elements['#modal .dialog-error'].textContent.includes('处理结论'));});
test('unknown financial fields post null, never fabricated zeros',async()=>{const {c,run}=fixture();run("operationsProductionDialog={kind:'financial',row:{project_id:'cab',version:2}}");c.values={project_id:'cab',contract_amount:'1000',budget_cost:'',remaining_cost:'',received_amount:'0',approved_change_amount:'',note:'核对合同'};c.b={disabled:false,isConnected:true,innerHTML:'保存'};c.reply=async()=>{throw new Error('测试截获')};await run('operationsRecordSave(b)');assert.equal(c.requests[0].data.expected_version,2);assert.equal(c.requests[0].data.contract_amount,1000);assert.equal(c.requests[0].data.budget_cost,null);assert.equal(c.requests[0].data.received_amount,0);assert.equal(c.requests[0].data.approved_change_amount,null);assert(!('amount' in c.requests[0].data));});
test('owner financial view does not calculate profit from missing amounts',()=>{const {c,run}=fixture();c.production={projects:c.state.projects,financials:[{project_id:'cab',contract_amount:10000,budget_cost:null,remaining_cost:null,received_amount:null,approved_change_amount:null}],costs:[]};run('operationsProductionData=production');const html=run('operationsOwnerFinancialPanel()');assert(html.includes('待核对'));assert(!html.includes('¥ 10000'));});
test('file exchange uses backend catalog including original unique key',()=>{const {c,run}=fixture();c.catalog={field_catalog:{projects:[{key:'external_key',label:'原系统订单号',required:true},{key:'name',label:'项目名称',required:true}]}};run('operationsExchangeData=catalog');assert.deepEqual(Array.from(run('operationsExchangeFields().map(f=>f.key)')),['external_key','name']);});
test('exchange errors prevent apply and escaped source text stays inert',()=>{const {c,run}=fixture();c.preview={id:'p1',status:'preview',filename:'test.csv',rows:[{row_number:2,action:'create',data:{name:'<script>alert(1)</script>'},errors:[]},{row_number:3,action:'error',errors:['编号重复']}]};run('operationsExchangePreview=preview');assert.equal(run('operationsExchangeCanApply()'),false);const html=run('operationsExchangePreviewView()');assert(!html.includes('<script>'));assert(html.includes('&lt;script&gt;'));assert(!html.includes('data-action="ops-exchange-apply"'));});
test('applied preview cannot be applied again from UI',()=>{const {c,run}=fixture();c.preview={id:'p1',status:'applied',rows:[{action:'create',errors:[]}]};run('operationsExchangePreview=preview');assert.equal(run('operationsExchangeCanApply()'),false);});
test('all skipped import rows do not create a write action',()=>{const {c,run}=fixture();c.preview={status:'preview',rows:[{action:'skip',errors:[]}]};run('operationsExchangePreview=preview');assert.equal(run('operationsExchangeCanApply()'),false);});
test('missing scheduling duration remains absent instead of zero',()=>{const {c,run}=fixture();c.scheduling={tasks:[{id:'t1',project_id:'cab',title:'开料',status:'ready'}]};run('operationsSchedulingData=scheduling');const payload=run('operationsSchedulingPayload()');assert.deepEqual(Array.from(payload.task_ids),['t1']);assert.equal(payload.overrides.length,0);});
test('scheduling uses chosen tasks, rush list and hour conversion',()=>{const {c,run}=fixture();c.scheduling={tasks:[{id:'t1',project_id:'cab',status:'ready'},{id:'t2',project_id:'cab',status:'ready'}]};run("operationsSchedulingData=scheduling;operationsScheduleSelections.set('t1',{included:true,rush:true,hours:'1.5',setup_minutes:'10',wait_hours:'24'});operationsScheduleSelections.set('t2',{included:false,rush:true,hours:'2'})");const payload=run('operationsSchedulingPayload()');assert.deepEqual(Array.from(payload.task_ids),['t1']);assert.deepEqual(Array.from(payload.rush_task_ids),['t1']);assert.equal(payload.overrides[0].minutes,90);assert.equal(payload.overrides[0].setup_minutes,10);assert.equal(payload.overrides[0].wait_hours,24);});
test('scheduling excludes archived completed draft and other type tasks',()=>{const {c,run}=fixture();c.scheduling={tasks:[{id:'ok',project_id:'cab',status:'ready'},{id:'done',project_id:'cab',status:'done'},{id:'draft',project_id:'cab',status:'draft'},{id:'arc',project_id:'cab',status:'ready',archived:true},{id:'mach',project_id:'mach',status:'ready'}]};run('operationsSchedulingData=scheduling');assert.deepEqual(Array.from(run('operationsSchedulingTasks().map(t=>t.id)')),['ok']);});
test('calibration empty result shows no invented hours or margin',()=>{const {c,run}=fixture();c.calibration={groups:[],summary:{sample_count:0},excluded:{no_sessions:2},basis:'仅实际报工',cost_basis:'已登记费用'};run('operationsCalibrationData=calibration');const html=run('operationsCalibrationView()');assert(html.includes('尚无有效实绩样本'));assert(!html.includes('480'));assert(html.includes('缺少有效报工'));});
test('commercial amounts parse independently and stay explicit',()=>{const {c,run}=fixture();c.values={amount:'1500',estimated_cost:''};c.fakeForm={querySelectorAll:()=>[{value:'t1'}]};const result=run("operationsCommercialPayload('change',values,fakeForm)");assert.equal(result.amount,1500);assert.equal(result.estimated_cost,null);assert.deepEqual(Array.from(result.task_ids),['t1']);});
(async()=>{let failed=0;for(const [name,fn] of tests){try{await fn();console.log('PASS',name)}catch(error){failed++;console.error('FAIL',name,error.stack)}}console.log(`${tests.length-failed}/${tests.length} operations frontend checks passed`);if(failed)process.exitCode=1;})();
