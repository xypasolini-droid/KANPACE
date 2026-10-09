const fs = require('fs'), path = require('path'), vm = require('vm');
const assert = require('node:assert/strict');
const test = require('node:test');
const appSource = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
const sharedSource = appSource.slice(appSource.indexOf('function projectWorkflowContext('), appSource.indexOf('function projectHead(')) + appSource.slice(appSource.indexOf('function processBasisIsCurrent('),appSource.indexOf('function uploadDocSummary('));
const source = fs.readFileSync(path.join(__dirname, '../static/factory-home.js'), 'utf8');
function boot() {
  const context = {console, URLSearchParams, Date, Map, Set, Promise,
    state:{projects:[],documents:[],parts:[],tasks:[]}, workspaceType:'cabinet', page:'overview',
    document:{addEventListener(){}}, icon:()=>'<svg></svg>',
    esc:value=>String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
    button:(label, action)=>`<button data-action="${action}">${label}</button>`, render(){},
    workspaceProfile:()=>({name:'展柜工厂'}),
  };
  context.workspaceProjects = ()=>context.state.projects.filter(p=>(p.factory_type || 'cabinet')===context.workspaceType);
  vm.createContext(context);
  vm.runInContext(appSource.split('\n').find(line=>line.startsWith('function historicalDemoIsComplete(')),context);
  vm.runInContext(sharedSource, context); vm.runInContext(source, context); return context;
}
function project(overrides={}) { return {id:'p1', name:'一号门店', revision:2, status:'draft', factory_type:'cabinet', ...overrides}; }
function snapshot(p, overrides={}) { return {projects:[p],documents:[],parts:[],tasks:[],...overrides}; }
function task(overrides={}) { return {id:'t1',project_id:'p1',revision:2,status:'ready',title:'铣槽',...overrides}; }

test('effect images and unrelated project files do not satisfy engineering source step', () => {
  const c=boot(), p=project();
  const summary=c.factoryProjectSummary(p,snapshot(p,{documents:[{id:'render',project_id:p.id,purpose:'render'},{id:'other',project_id:'p2',status:'parsed',part_count:4}]}));
  assert.equal(summary.stage,0); assert.equal(summary.documents.length,0); assert.equal(summary.label,'准备资料');
});
test('engineering import needs explicit part review and source verification', () => {
  const c=boot(),p=project();
  let result=c.factoryProjectSummary(p,snapshot(p,{documents:[{id:'d1',project_id:p.id,status:'parsed',part_count:0}],parts:[{project_id:p.id,review_status:'pending'}]}));
  assert.equal(result.stage,1);assert.match(result.reason,/1 项构件待复核/);
  result=c.factoryProjectSummary(p,snapshot(p,{documents:[{id:'d1',project_id:p.id,status:'needs_conversion',part_count:0}],parts:[{project_id:p.id,review_status:'approved'}]}));
  assert.match(result.reason,/工程资料待核验/);
});
test('current released version is required; old or invalidated tasks do not imply execution', () => {
  const c=boot(),p=project({status:'released',released_revision:1});
  const result=c.factoryProjectSummary(p,snapshot(p,{parts:[{project_id:p.id,review_status:'approved'}],tasks:[task({revision:1,status:'in_progress'}),task({id:'t2',status:'invalidated'})]}));
  assert.equal(result.published,false);assert.equal(result.running.length,0);assert.equal(result.stage,1);assert.equal(result.stale.length,2);
});
test('absence of material data never claims ready and server shortages stay scoped', () => {
  const c=boot(),p=project({status:'released',released_revision:2}),s=snapshot(p,{tasks:[task()]});
  let result=c.factoryProjectSummary(p,s);
  assert.equal(result.productionAvailable,false);assert.doesNotMatch(result.reason,/已齐套|可以开工/);
  result=c.factoryProjectSummary(p,s,{projects:[p],materials:[{id:'m',project_id:p.id,shortage_quantity:2},{id:'other',project_id:'p2',shortage_quantity:9}],checks:[]});
  assert.equal(result.shortages.length,1);assert.match(result.reason,/1 项物料有缺口/);assert.match(result.href,/opTab=materials&opProject=p1/);
});
test('partial execution and pause point to exact task; all completed points to delivery', () => {
  const c=boot(),p=project({status:'released',released_revision:2});
  const result=c.factoryProjectSummary(p,snapshot(p,{tasks:[task({status:'blocked',pause_note:'缺玻璃'}),task({id:'t2',status:'in_progress'})]}));
  assert.equal(result.stage,3);assert.equal(result.label,'处理暂停');assert.match(result.href,/task=t1/);assert.match(result.reason,/缺玻璃/);
  const done=c.factoryProjectSummary(p,snapshot(p,{tasks:[task({status:'done'})]}));
  assert.equal(done.stage,4);assert.equal(done.label,'核对验收');assert.match(done.href,/opTab=inspections/);
});
test('forced closed project never enters priorities or gets falsely completed stage rail', () => {
  const c=boot(),p=project({fulfillment_status:'shipped',due_date:'2020-01-01'}),s=snapshot(p,{tasks:[task({status:'blocked'})]});
  const result=c.factoryProjectSummary(p,s);assert.equal(result.stage,-1);assert.equal(result.label,'查看项目记录');
  assert.equal(c.factoryHomePriorities([result],'2026-09-07').length,0);
  c.state=s;assert.equal(c.factoryProjectMainline(p),'');
});
test('demo jobs and out-of-scope factories stay out of daily priorities', () => {
  const c=boot(),real=project(),demo=project({id:'demo',demo:true}),other=project({id:'other',factory_type:'site'});
  c.state={projects:[real,demo,other],tasks:[],parts:[],documents:[]};
  const summaries=[real,demo].map(p=>c.factoryProjectSummary(p,snapshot(p,{tasks:[task({project_id:p.id,status:'blocked'})]})));
  assert.equal(c.factoryHomePriorities(summaries,'2026-09-07').length,1);
  const html=c.factoryHomeView();assert.match(html,/查看演示项目/);assert.doesNotMatch(html,/project=other/);
});
test('historical case stays browseable after shipment without counting as live overdue work', () => {
  const c=boot(),historical=project({id:'history',name:'历史案例',demo_dataset:true,historical_order:true,due_date:'2020-01-01'});
  c.state=snapshot(historical,{tasks:[task({id:'historical-task',project_id:'history',status:'blocked'})]});
  let summary=c.factoryProjectSummary(historical,c.state);
  assert.equal(c.factoryHomePriorities([summary],'2026-09-29').length,0);
  let html=c.factoryHomeView();
  assert.match(html,/先准备一张真实订单/);
  assert.match(html,/查看演示项目 · 1 个/);
  assert.match(html,/历史案例/);
  assert.match(html,/历史已完成 · 演示复盘/);
  assert.doesNotMatch(html,/交付 未设置/);
  assert.match(html,/data-factory-home-filter="due"[^>]*><strong>0<\/strong><span>交期待核对/);
  assert.doesNotMatch(html,/先推进这 1 单|已完成 \/ 已发货项目/);

  historical.fulfillment_status='shipped';historical.is_closed=true;
  summary=c.factoryProjectSummary(historical,c.state);
  assert.equal(summary.closed,true);
  html=c.factoryHomeView();
  assert.match(html,/查看演示项目 · 1 个/);
  assert.match(html,/历史案例/);
  assert.match(html,/查看项目记录/);
  assert.doesNotMatch(html,/已完成 \/ 已发货项目/);
});
test('empty home opens the same first-order form instead of sending users into factory setup', () => {
  const c=boot();c.state.projects=[project({id:'demo',demo:true})];
  const html=c.factoryHomeView();
  assert.match(html,/先准备一张真实订单/);
  assert.match(html,/data-action="new-project"/);
  assert.doesNotMatch(html,/href="\/factory-setup\/index\.html"/);
  assert.match(html,/查看演示项目/);
});
test('factory name, source content and URLs are escaped; no platform provisioning or research links', () => {
  const c=boot(),p=project({name:'<img src=x onerror=alert(1)>',client:'<script>alert(1)</script>'});
  c.state=snapshot(p);c.kanpaceInstanceContext={instance:{name:'A & B 工厂'}};
  const html=c.factoryHomeView();assert.match(html,/A &amp; B 工厂/);assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<script>|<img src=x/);assert.doesNotMatch(html,/control\/|industry-map|open-source|factory-instances/);
  const mainline=c.factoryProjectMainline(p);assert.match(mainline,/aria-label="项目工作步骤"/);assert.match(mainline,/aria-current="step"/);assert.match(mainline,/project=p1/);
});
test('production refresh discards stale result after factory scope changes and errors are retryable', async () => {
  const c=boot();let resolveFirst,resolveSecond,rendered=0;
  c.render=()=>rendered++; c.api=()=>new Promise(resolve=>{if(!resolveFirst)resolveFirst=resolve;else resolveSecond=resolve;});
  const first=c.factoryHomeAfterRender();c.workspaceType='site';const second=c.factoryHomeAfterRender();
  resolveSecond({projects:[],materials:[{id:'second'}]});await second;
  resolveFirst({projects:[],materials:[{id:'stale'}]});await first;
  assert.equal(vm.runInContext('factoryHomeProduction.materials[0].id',c),'second');assert.equal(rendered,1);
  c.api=async()=>{throw new Error('offline');};await c.factoryHomeAfterRender(true);
  assert.match(c.factoryHomeView(),/data-factory-home-retry/);
});
test('installed factory workflow is directly reachable from the project confirmation step', () => {
  const c=boot(),p=project({factory_id:'f1'});c.state=snapshot(p,{parts:[{project_id:p.id,review_status:'pending'}]});
  c.kanpaceInstanceContext={profile:{status:'installed',factory_type:'cabinet',factory_id:'f1',template_id:'tpl1'}};
  assert.match(c.factoryProjectMainline(p),/page=templates&amp;tab=parts&amp;project=p1/);
  assert.match(c.factoryHomeView(),/按本厂流程拆解/);
  c.kanpaceInstanceContext.profile.factory_id='foreign';
  assert.doesNotMatch(c.factoryProjectMainline(p),/page=templates/);
  p.workflow_id='existing-workflow';
  assert.match(c.factoryProjectMainline(p),/page=templates/);
});

test('industry first order guidance uses its process evidence and uninstalled route stays visible',()=>{
  const c=boot(),p=project({industry_id:'food',factory_type:'machinery',factory_id:'f1'});
  let result=c.factoryProjectSummary(p,snapshot(p));assert.match(result.reason,/中台核对并启用本厂流程/);assert.match(result.href,/page=templates/);
  const profile={status:'installed',factory_type:'machinery',factory_id:'f1',industry_id:'food'};
  result=c.factoryProjectSummary(p,snapshot(p),null,profile);assert.match(result.reason,/本行业工艺资料/);assert.doesNotMatch(result.reason,/施工图/);
});
test('home does not apply an installed industry profile to an unbound legacy project',()=>{
  const c=boot(),p=project();c.state=snapshot(p);c.kanpaceInstanceContext={profile:{status:'installed',factory_type:'cabinet',factory_id:'f1',industry_id:'rattan'}};
  assert.equal(c.factoryHomeProfileFor(p),null);assert.doesNotMatch(c.factoryProjectMainline(p),/page=templates/);
});

test('due orders lead the queue and take their real next step instead of jumping to shipment',()=>{
 const c=boot(),due=project({id:'due',due_date:'2026-09-08'}),later=project({id:'later',due_date:'2026-10-01',status:'released',released_revision:2});
 const ds=c.factoryProjectSummary(due,snapshot(due,{parts:[{project_id:'due',review_status:'pending'}]}));
 const ls=c.factoryProjectSummary(later,snapshot(later,{tasks:[task({project_id:'later',status:'blocked'})]}));
 const rows=c.factoryHomePriorities([ls,ds],'2026-09-08');
 assert.equal(rows[0].project.id,'due');assert.match(rows[0].href,/page=drawing/);assert.doesNotMatch(rows[0].href,/deliveries/);
 assert.equal(rows[1].project.id,'later');assert.match(rows[1].href,/task=t1/);
});
test('multiple holds on one due order produce one prioritized action with its current blocker',()=>{
 const c=boot(),p=project({due_date:'2026-09-01',status:'released',released_revision:2});
 const summary=c.factoryProjectSummary(p,snapshot(p,{tasks:[task({status:'blocked',pause_note:'等玻璃'})]}),{projects:[p],materials:[{id:'m1',project_id:p.id,shortage_quantity:2}],issues:[{id:'i1',project_id:p.id,status:'open'}]});
 const rows=c.factoryHomePriorities([summary],'2026-09-08');assert.equal(rows.length,1);assert.match(rows[0].detail,/等玻璃/);assert.match(rows[0].href,/task=t1/);
});
test('invalid or unknown due dates are not treated as late and filters follow actual states',()=>{
 const c=boot(),p=project({due_date:'2026-02-31'}),summary=c.factoryProjectSummary(p,snapshot(p));
 assert.equal(c.factoryHomeDue(p,'2026-09-08').known,false);assert.equal(c.factoryHomeMatches(summary,'due','2026-09-08'),false);assert.equal(c.factoryHomeMatches(summary,'review','2026-09-08'),true);
 const ready=project({status:'released',released_revision:2});const done=c.factoryProjectSummary(ready,snapshot(ready,{tasks:[task({status:'done'})]}));
 assert.equal(c.factoryHomeMatches(done,'delivery','2026-09-08'),true);assert.equal(c.factoryHomeMatches(done,'review','2026-09-08'),false);
});
test('global home assistant explicitly uses the entire factory instead of the last opened project',()=>{
 const c=boot(),p=project();c.state=snapshot(p);const html=c.factoryHomeView();
 assert.match(html,/data-agent-project=""/);assert.match(html,/data-factory-home-filter="review"/);assert.match(html,/订单推进/);
 const rail=c.factoryProjectMainline(p);assert.match(rail,/验收发货/);assert.match(rail,/opTab=inspections/);
});

test('completed but unshipped orders remain in delivery todo without reopening production',()=>{
 const c=boot(),p=project({fulfillment_status:'completed',is_closed:true,due_date:'2026-09-01'});
 c.state=snapshot(p,{tasks:[task({status:'done'})]});
 const s=c.factoryProjectSummary(p,c.state);
 assert.equal(s.closed,true);assert.equal(s.deliveryPending,true);assert.equal(s.stage,4);
 assert.match(s.href,/opTab=deliveries/);assert.equal(s.label,'安排发货');
 assert.equal(c.factoryHomeMatches(s,'delivery','2026-09-08'),true);
 assert.equal(c.factoryHomePriorities([s],'2026-09-08')[0].action,'安排发货');
 const html=c.factoryHomeView();assert.match(html,/订单推进/);assert.match(html,/安排发货/);assert.doesNotMatch(html,/page=tasks/);
 p.due_date='2027-01-01';c.state.tasks=[task({status:'blocked'})];
 const future=c.factoryProjectSummary(p,c.state);assert.equal(c.factoryHomeHasBlock(future),false);assert.match(c.factoryHomePriorities([future],'2026-09-08')[0].href,/opTab=deliveries/);
 p.fulfillment_status='shipped';const sent=c.factoryProjectSummary(p,c.state);
 assert.equal(sent.deliveryPending,false);assert.equal(c.factoryHomePriorities([sent],'2026-09-08').length,0);
});
test('partly completed production preserves material and issue blockers with matching actions',()=>{
 const c=boot(),p=project({status:'released',released_revision:2,due_date:'2026-12-01'}),s=snapshot(p,{tasks:[task({status:'done'}),task({id:'t2',assignee:'张师傅'})]});
 const production={projects:[p],materials:[{id:'glass',project_id:p.id,shortage_quantity:2}],issues:[]};
 let summary=c.factoryProjectSummary(p,s,production);
 assert.equal(summary.stage,3);assert.equal(summary.label,'处理缺料');assert.match(summary.reason,/物料有缺口/);assert.match(summary.href,/opTab=materials/);
 let priority=c.factoryHomePriorities([summary],'2026-09-08')[0];assert.equal(priority.action,'处理缺料');assert.match(priority.href,/opTab=materials/);
 production.issues=[{id:'issue',project_id:p.id,status:'open',title:'尺寸冲突'}];
 summary=c.factoryProjectSummary(p,s,production);priority=c.factoryHomePriorities([summary],'2026-09-08')[0];
 assert.equal(summary.label,'处理异常');assert.equal(priority.action,'处理异常');assert.match(priority.href,/opTab=issues/);
});
