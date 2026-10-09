'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '../static');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const app = read('app.js'), access = read('access-control.js');
const tests = [], test = (name, fn) => tests.push([name, fn]);
const plain = value => JSON.parse(JSON.stringify(value));
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const appLine = prefix => {
  const matches = app.split('\n').filter(line => line.startsWith(prefix));
  assert.equal(matches.length, 1, 'One real app entry point: ' + prefix);
  return matches[0];
};
const accessGuard = access.slice(access.indexOf('function accessGuardPage('), access.indexOf('\nfunction accessDecorateNavigation('));
function fixture({financial=true, mobile=false}={}) {
  const handlers = [], elements = new Map(), storage = new Map();
  const media = {matches:mobile, addEventListener(_type, fn) { this.changed = fn; }};
  const c = {
    console, URLSearchParams, URL, Date, Number, String, Array, JSON, Map, Set, Object, Math,
    window:{}, location:{hash:'#page=overview',pathname:'/',search:''},
    document:{readyState:'loading', addEventListener(type, fn, options){handlers.push({type, fn, capture:options===true});},
      querySelector:selector=>elements.get(selector)||null, querySelectorAll:()=>[], getElementById:id=>elements.get('#'+id)||null},
    localStorage:{getItem:key=>storage.get(key)||'', setItem:(key,value)=>storage.set(key,value)},
    sessionStorage:{getItem:key=>storage.get('session:'+key)||'', setItem:(key,value)=>storage.set('session:'+key,value)},
    history:{replaceState(_state,_title,url){c.location.hash=String(url).slice(String(url).indexOf('#'));}},
    matchMedia:()=>media, page:'overview', projectId:'cab-a', tab:'parts', pendingTaskDeepLink:'',
    accessState:{enabled:true,user:{id:financial?'admin':'worker',role:financial?'admin':'worker'},financial_access:financial},
    state:{projects:[
      {id:'cab-a',name:'进行中柜项目',factory_type:'cabinet',revision:1,status:'released',fulfillment_status:'active'},
      {id:'cab-b',name:'另一柜项目',factory_type:'cabinet',revision:1,status:'released',fulfillment_status:'active'},
      {id:'cab-done',name:'完成待发货柜项目',factory_type:'cabinet',fulfillment_status:'completed',is_closed:true},
      {id:'cab-shipped',name:'已发货柜项目',factory_type:'cabinet',fulfillment_status:'shipped',is_closed:true},
      {id:'mach-a',name:'设备项目',factory_type:'machinery',fulfillment_status:'active'},
    ],tasks:[],people:[]},
    projectStatusFilter:'active', executionFocus:'all', search:'', tradeFilter:'', statusFilter:'',
    referenceMode:'departments',trades:['木工','五金'],executionPauseNames:{material:'缺料'},
    executionSorted:rows=>rows,executionPriority:task=>task.priority||0,executionPerson:()=>null,
    executionCompleted:task=>task.completed_quantity??0,executionRemaining:task=>(task.quantity||0)-(task.completed_quantity||0),
    executionPriorityTag:task=>escape(task.priority||0),executionStatusTag:task=>escape(task.status),
    projectHead:()=>'',empty:title=>escape(title),
    planningExecutionView:()=>'<section>真实工序排产入口</section>',referenceFlowView:()=>'<section>工序关系入口</section>',referenceView:()=>'<section>部门排程入口</section>',
    requests:[], renders:0, writes:[], modals:[],
    esc:escape, num:value=>value==null?'—':String(value), money:value=>value==null?'待核对':'¥ '+value,
    icon:()=>'', button:(label,action,_icon,_class,attrs='')=>`<button data-action="${action}" ${attrs}>${escape(label)}</button>`,
    date:value=>value||'待确认', localTimestamp:value=>value||'—', tag:value=>escape(value),
    fulfillmentNames:{active:'进行中',completed:'已完成 · 待发货',shipped:'已发货'},
    fulfillmentBadge:p=>escape(p.fulfillment_status), projectLifecycleActions:()=>'',
    planningReset(){}, openModal(...args){c.modals.push(args);}, closeModal(){},
    render(){c.renders++;}, showError(error){c.error=error;},
    navigate(page, tab='parts', project=c.projectId){c.location.hash='#'+new URLSearchParams({page,tab,project});},
    executionRequest:async(url,data)=>{c.requests.push({url,data});if(data!==undefined)c.writes.push({url,data});return {};},
    fetch:async(url,options)=>{c.requests.push({url,options});return {ok:true,json:async()=>({enabled:false})};},
  };
  c.$ = c.document.querySelector;
  vm.createContext(c);
  const run = code => vm.runInContext(code,c);
  run(read('workspace.js'));
  for(const prefix of ['const storedProject=', 'function parseHash(', 'function currentProject(', 'function projectIsClosed(', 'function historicalDemoIsComplete(', 'function fulfillmentStatus(', 'function activeProjects(', 'function taskProjectIsClosed(', 'function tasks(', 'function projectList(']) run(appLine(prefix));
  run(app.slice(app.indexOf('function projectWorkflowContext('),app.indexOf('function projectHead(')));
  run(app.slice(app.indexOf('function taskView('),app.indexOf('function projectList(')));
  const referenceSource=read('schedule-reference.js');
  run(referenceSource.slice(referenceSource.indexOf('function planningView('),referenceSource.indexOf('async function ensureScheduleReference(')));
  for(const file of ['operations.js','operations-production.js','operations-finance.js','operations-commercial.js']) run(read(file));
  run(read('navigation-data.js'));
  run(read('navigation.js'));
  run(accessGuard);
  c.production = {projects:c.state.projects, materials:[
    {id:'mat-a',name:'甲项目板材',project_id:'cab-a',required_quantity:3,accepted_quantity:1,unit:'块'},
    {id:'mat-b',name:'乙项目玻璃',project_id:'cab-b',required_quantity:1,accepted_quantity:0,unit:'块'},
    {id:'mat-mach',name:'设备专用轴',project_id:'mach-a',required_quantity:1,accepted_quantity:0,unit:'根'},
  ],issues:[{id:'issue-a',project_id:'cab-a',title:'甲任务缺板',type:'material',status:'open'}],checks:[],inspections:[],costs:[],financials:[],deliveries:[],tasks:[]};
  c.resources={factories:[{id:'f-cab',name:'展柜一厂',factory_type:'cabinet'}],people:[{id:'person-a',name:'测试木工',skills:['木工'],factory_id:'f-cab',capacity_minutes:480}],teams:[{id:'team-a',name:'测试木工班',factory_id:'f-cab'}],workcenters:[{id:'center-a',name:'测试开料工位',kind:'station',factory_id:'f-cab'}]};
  run('operationsProductionData=production;operationsData=resources');
  const apply = hash => {c.location.hash=hash;run('parseHash();syncWorkspaceProject();page=accessGuardPage(page);kanpaceNavigationApplyRoute(true)');};
  const dispatch = (type,event) => {for(const entry of handlers.filter(h=>h.type===type).sort((a,b)=>Number(b.capture)-Number(a.capture)))entry.fn(event);};
  return {c,run,elements,media,storage,handlers,apply,dispatch};
}

test('the six work stages have direct links and preserve every detailed destination',()=>{
  const f=fixture(), groups=plain(f.c.window.KANPACE_MENU), items=groups.flatMap(group=>group.items);
  assert.equal(new Set(items.map(item=>item.id)).size,items.length);
  const html=f.run('kanpaceMenuMarkup()');
  assert(html.includes('aria-label="功能菜单"'));
  for(const group of groups) {
    assert(html.includes(`data-nav-group="${group.id}"`));
    assert(html.includes(`<span>${group.label}</span>`));
    for(const item of group.items)assert(html.includes(`data-nav-item="${item.id}"`),item.label+' has a direct sidebar link');
  }
  for(const id of ['exchange','materials','issues','inspections','deliveries','costs','commercial'])assert(items.some(item=>item.id===id));
  assert.deepEqual(groups.filter(group=>Number.isInteger(group.step)).map(group=>group.step),[0,1,2,3,4,5]);
  assert(groups.some(group=>group.id==='order-workflow'&&group.direct));
  assert.deepEqual(groups.map(group=>group.label),['订单工作流','选工厂','订单与资料','工程与计划','任务与人员','生产协同','总看板']);
  assert.equal((html.match(/data-nav-primary=/g)||[]).length,6);
  assert.equal((html.match(/data-nav-item="overview"/g)||[]).length,1);
  assert(html.includes('<span class="nav-step" aria-hidden="true">00</span>'));
  assert.equal((html.match(/class="nav-group"[^>]* open/g)||[]).length,0);
  assert(!/<summary[^>]+tabindex="-1"/.test(html));
  assert(!/<a\b[^>]+tabindex="-1"/.test(html));
  assert.equal(f.c.writes.length,0);
});

test('the real home shell shows one large entry for each stage before daily content',()=>{
  const f=fixture();
  const html=f.run('kanpaceNavigationShell("<p>今日工作明细</p>")');
  assert.equal((html.match(/data-workflow-stage=/g)||[]).length,6);
  for(let step=0;step<=5;step++)assert(html.includes(`data-workflow-stage="${step}"`));
  assert(html.indexOf('kanpace-workflow-entry')<html.indexOf('今日工作明细'));
  assert(html.includes('data-select-factory="true"'));
  assert.equal(f.c.writes.length,0);
});

test('home stage entries use only enabled destinations',()=>{
  const f=fixture({financial:false});
  f.c.window.kanpaceInstanceContext={profile:{enabled_modules:['overview','projects','drawing','readiness','deliveries','device']}};
  const html=f.run('kanpaceWorkflowEntry()');
  assert.equal((html.match(/data-workflow-stage=/g)||[]).length,6);
  assert(html.includes('data-workflow-stage="4"'));
  assert(html.includes('step=return'));
  assert(!html.includes('page=owner'));
});

test('all project links retain the selected project and encode unusual identifiers safely',()=>{
  const f=fixture(), items=f.c.window.KANPACE_MENU.flatMap(group=>group.items), id='cab & <当前> / 项目';
  for(const item of items.filter(item=>item.page)) {
    const href=f.c.window.kanpaceMenuHref(item,{projectId:id});
    assert.equal(new URLSearchParams(href.slice(1)).get('project'),id);
    assert(!href.includes('<当前>'));
  }
  const model={path:'/model/index.html',projectScoped:true};
  assert.equal(new URL('http://127.0.0.1'+f.c.window.kanpaceMenuHref(model,{projectId:id})).searchParams.get('project'),id);
});

test('daily stage navigation preserves the selected working date',()=>{
  const f=fixture();f.apply('#page=daily&step=planning&date=2026-09-18&project=cab-a');
  for(const item of f.c.window.KANPACE_MENU.flatMap(group=>group.items).filter(item=>item.dailyStep)) {
    const href=f.c.window.kanpaceMenuHref(item,{projectId:'cab-a'});
    assert.equal(new URLSearchParams(href.slice(1)).get('date'),'2026-09-18');
    assert.equal(new URLSearchParams(href.slice(1)).get('step'),item.dailyStep);
  }
  assert.equal(f.c.writes.length,0);
});

test('visible production subviews open the real tab and preserve current project scope',()=>{
  const f=fixture(), items=f.c.window.KANPACE_MENU.flatMap(group=>group.items).filter(item=>item.opTab);
  assert.deepEqual(plain(items.map(item=>item.opTab).sort()),['materials','issues','inspections','costs','commercial','deliveries'].sort());
  for(const item of items) {
    f.apply(f.c.window.kanpaceMenuHref(item,{projectId:'cab-a'}));
    assert.equal(f.c.page,'readiness');
    assert.equal(f.run('operationsProductionTab'),item.opTab);
    assert.equal(f.run('operationsProductionProject'),'cab-a');
    const html=f.run('operationsReadinessView()');
    if(f.run('operationsProductionViewContext().tabs.length')===1)assert(!html.includes('role="tablist"'));
    else assert(html.includes(`aria-selected="true" class="active" data-action="ops-production-tab" data-id="${item.opTab}"`));
    assert.equal(f.run('kanpaceActiveMenuItem()'),item.id);
  }
  assert.equal(f.c.writes.length,0);
  assert.equal(f.c.modals.length,0);
});

test('material direct links really filter business rows, including explicit all-project scope',()=>{
  const f=fixture();f.apply('#page=readiness&opTab=materials&project=cab-a&opProject=cab-a');
  assert.deepEqual(plain(f.run('operationsProductionRows("materials").map(row=>row.id)')),['mat-a']);
  let html=f.run('operationsReadinessView()');assert(html.includes('甲项目板材'));assert(!html.includes('乙项目玻璃'));assert(!html.includes('设备专用轴'));
  f.apply('#page=readiness&opTab=materials&project=cab-a&opProject=');
  assert.deepEqual(plain(f.run('operationsProductionRows("materials").map(row=>row.id)')),['mat-a','mat-b']);
  assert.equal(f.c.projectId,'cab-a');
});

test('cross-factory project and stale filters never leak rows from another factory',()=>{
  const f=fixture();f.apply('#page=readiness&opTab=materials&project=cab-a&opProject=mach-a');
  assert.equal(f.run('operationsProductionProject'),'');
  assert(!f.run('operationsReadinessView()').includes('设备专用轴'));
  f.apply('#page=readiness&opTab=materials&project=mach-a&opProject=mach-a');
  assert.equal(f.run('workspaceType'),'machinery');
  assert.deepEqual(plain(f.run('operationsProductionRows("materials").map(row=>row.id)')),['mat-mach']);
});

test('resource deep links select the real people, team, equipment and factory tables',()=>{
  const f=fixture();
  for(const [view,text] of [['people','测试木工'],['teams','测试木工班'],['workcenters','测试开料工位'],['factories','展柜一厂']]) {
    f.apply('#page=people&resTab='+view+'&project=cab-a');
    assert.equal(f.run('operationsResourceTab'),view);
    const html=f.run('operationsPeopleView()');
    assert(html.includes(`aria-selected="true" class="active" data-action="ops-resource-tab" data-id="${view}"`));
    assert(html.includes(text));
  }
});

test('project status deep links show only the selected real order state',()=>{
  const f=fixture();
  for(const [status,expected] of [['active',['cab-a','cab-b']],['completed',['cab-done']],['shipped',['cab-shipped']],['all',['cab-a','cab-b','cab-done','cab-shipped']]]) {
    f.apply('#page=projects&projectStatus='+status+'&project=cab-a');
    assert.equal(f.c.projectStatusFilter,status);
    const cards=[...f.run('projectList()').matchAll(/class="project-card-open" data-action="project" data-id="([^"]+)"/g)].map(match=>match[1]);
    assert.deepEqual(cards,expected);
    assert.equal(f.c.projectId,'cab-a');
  }
});
test('historical demo case link opens the same project after its fulfillment status changes',()=>{
  const f=fixture(),historical={id:'historical-case',name:'历史演示订单',factory_type:'cabinet',demo_dataset:true,historical_order:true,fulfillment_status:'active'};
  f.c.state.projects.push(historical);
  for(const status of ['active','completed','shipped']){
    historical.fulfillment_status=status;historical.is_closed=status!=='active';
    f.c.projectStatusFilter=status==='active'?'shipped':'active';
    f.apply('#page=projects&projectStatus=all');
    assert.equal(f.c.projectStatusFilter,'all');
    assert.match(f.run('projectList()'),/data-id="historical-case"/);
  }
});

test('task focus direct links clear stale text filters and select the actual queue cards',()=>{
  const f=fixture();f.c.state.tasks=[
    {id:'ready-a',project_id:'cab-a',title:'开料',status:'ready',trade:'木工',revision:1},
    {id:'paused-a',project_id:'cab-a',title:'缺板暂停',status:'blocked',trade:'木工',revision:1},
    {id:'active-a',project_id:'cab-a',title:'正在封边',status:'in_progress',trade:'木工',revision:1},
    {id:'urgent-a',project_id:'cab-a',title:'加急开料',status:'ready',trade:'木工',priority:2,revision:1},
    {id:'done-a',project_id:'cab-a',title:'已完工',status:'done',trade:'木工',priority:3,revision:1},
    {id:'other-project',project_id:'cab-b',title:'别单急单',status:'ready',priority:3,revision:1},
  ];
  for(const [focus,expected] of [['paused',['paused-a']],['active',['active-a']],['urgent',['urgent-a']]]) {
    f.c.search='上次不匹配的关键词';f.c.tradeFilter='玻璃';f.c.statusFilter='done';
    f.apply('#page=tasks&taskFocus='+focus+'&project=cab-a');
    assert.equal(f.c.executionFocus,focus);assert.equal(f.c.search,'');assert.equal(f.c.tradeFilter,'');assert.equal(f.c.statusFilter,'');
    const cards=[...f.run('taskView()').matchAll(/data-action="task" data-id="([^"]+)"/g)].map(match=>match[1]);
    assert.deepEqual(cards,expected);
  }
  f.apply('#page=tasks&taskFocus=__proto__&project=cab-a');assert.equal(f.c.executionFocus,'all');
  assert.equal(f.c.writes.length,0);
});

test('planning direct links select department, process relationship and execution views',()=>{
  const f=fixture();
  for(const [mode,text] of [['departments','部门排程入口'],['reference-flow','工序关系入口'],['execution','真实工序排产入口']]) {
    const href=f.c.window.kanpaceMenuHref({page:'planning',referenceMode:mode},{projectId:'cab-a'});
    f.apply(href);assert.equal(f.c.referenceMode,mode);
    const html=f.run('planningView()');
    if(mode!=='reference-flow')assert(html.includes(`class="active" role="tab" aria-selected="true" data-action="reference-mode" data-mode="${mode}"`));
    else assert(!html.includes('data-mode="reference-flow"'));
    assert(html.includes(text));
  }
  f.apply('#page=planning&referenceMode=__proto__&project=cab-a');assert.equal(f.c.referenceMode,'departments');
  f.apply('#page=planning&referenceMode=departments&project=mach-a');
  assert.equal(f.run('planningView()'),'<section>真实工序排产入口</section>');
  assert.equal(f.c.writes.length,0);
});

test('helper preserves only declared resource, project, task and planning view options',()=>{
  const f=fixture();
  for(const [name,value] of [['resTab','teams'],['projectStatus','shipped'],['referenceMode','reference-flow'],['taskFocus','paused']]) {
    const href=f.c.window.kanpaceMenuHref({page:'overview',[name]:value},{projectId:'cab-a'});
    assert.equal(new URLSearchParams(href.slice(1)).get(name),value);
    const bad=f.c.window.kanpaceMenuHref({page:'overview',[name]:'action=save'},{projectId:'cab-a'});
    assert.equal(new URLSearchParams(bad.slice(1)).get(name),null);
  }
});

test('unauthorized users cannot expose financial tabs through direct URLs or menu groups',()=>{
  const f=fixture({financial:false});
  const menu=f.run('kanpaceMenuMarkup()');
  for(const id of ['quote','owner','bi','costs','commercial','settings'])assert(!menu.includes(`data-nav-item="${id}"`));
  assert(menu.includes('data-nav-primary="overview"'));
  assert(!menu.includes('data-nav-group="dashboard"'));
  for(const tab of ['costs','commercial']) {
    f.apply('#page=readiness&opTab='+tab+'&project=cab-a');
    assert.equal(f.run('operationsProductionTab'),'materials');
    const html=f.run('operationsReadinessView()');
    assert(!html.includes('data-id="costs"'));assert(!html.includes('data-id="commercial"'));
    assert(!html.includes('登记成本'));
  }
  assert.equal(f.c.writes.length,0);
});

test('unknown view values and action-like URL text remain inert and use safe defaults',()=>{
  const f=fixture();
  f.apply('#page=readiness&opTab=%3Cimg%20src%3Dx%20onerror%3Dalert(1)%3E&action=ops-record-save&project=cab-a');
  assert.equal(f.run('operationsProductionTab'),'materials');
  assert(!f.run('operationsReadinessView()').includes('<img src=x'));
  f.apply('#page=people&resTab=__proto__&action=ops-resource-save&project=cab-a');
  assert.equal(f.run('operationsResourceTab'),'people');
  f.apply('#page=projects&projectStatus=shipped%26action%3Dsave-fulfillment&project=cab-a');
  assert.equal(f.c.projectStatusFilter,'active');
  assert.equal(f.c.writes.length,0);assert.equal(f.c.modals.length,0);
});

test('model helper remains available inside drawing without a standalone menu',()=>{
  const f=fixture(), model={path:'/model/index.html',projectScoped:true};
  assert.equal(f.c.window.kanpaceMenuHref(model,{projectId:'cab-a'}),'/model/index.html?project=cab-a');
  assert.equal(f.c.window.kanpaceMenuHref(model,{projectId:'',prefix:'/'}),'/#page=projects&tab=parts');
  f.c.state.projects=[];f.c.projectId='old-removed-project';
  assert.equal(f.run('kanpaceNavProject()'),'');
  const html=f.run('kanpaceMenuMarkup()');
  assert(!html.includes('/model/index.html?project=old-removed-project'));
  assert(!html.includes('data-nav-item="model"'));
});

test('page-internal production tab changes update URL and active sidebar together',()=>{
  const f=fixture();f.apply('#page=readiness&opTab=materials&project=cab-a');
  const button={disabled:false,dataset:{action:'ops-production-tab',id:'issues'}};
  f.dispatch('click',{target:{closest:selector=>selector==='[data-action]'?button:null}});
  assert.equal(new URLSearchParams(f.c.location.hash.slice(1)).get('opTab'),'issues');
  assert.equal(f.run('operationsProductionTab'),'issues');
  f.run('kanpaceNavigationBeforeRender()');
  assert.equal(f.run('kanpaceActiveMenuItem()'),'issues');
  assert.equal(f.c.writes.length,0);
});

test('page-internal task, resource, order and planning filters preserve shareable navigation state',()=>{
  const f=fixture();
  const cases=[
    {hash:'#page=tasks&taskFocus=paused&project=cab-a',data:{action:'task-focus',focus:'all'},key:'taskFocus',value:'all',state:'executionFocus'},
    {hash:'#page=people&resTab=people&project=cab-a',data:{action:'ops-resource-tab',id:'workcenters'},key:'resTab',value:'workcenters',state:'operationsResourceTab'},
    {hash:'#page=projects&projectStatus=shipped&project=cab-a',data:{action:'project-filter',status:'active'},key:'projectStatus',value:'active',state:'projectStatusFilter'},
    {hash:'#page=planning&referenceMode=departments&project=cab-a',data:{action:'reference-mode',mode:'execution'},key:'referenceMode',value:'execution',state:'referenceMode'},
  ];
  for(const entry of cases) {
    f.apply(entry.hash);const button={disabled:false,dataset:entry.data};
    f.dispatch('click',{target:{closest:selector=>selector==='[data-action]'?button:null}});
    assert.equal(new URLSearchParams(f.c.location.hash.slice(1)).get(entry.key),entry.value);
    f.run('kanpaceNavigationBeforeRender()');assert.equal(f.run(entry.state),entry.value);
    assert.equal(f.c.projectId,'cab-a');
  }
  assert.equal(f.c.writes.length,0);
});

test('mobile menu disclosure keeps all child destinations and collapses after navigation',()=>{
  const f=fixture({mobile:true});let html=f.run('kanpaceMenuMarkup()');
  assert(/<details class="nav-menu-disclosure"\s*>/.test(html));
  assert(html.includes('data-nav-item="materials"'));assert(html.includes('data-nav-item="deliveries"'));
  const node={open:true,scrollTop:0};f.elements.set('.nav-menu-disclosure',node);
  f.dispatch('toggle',{target:{matches:selector=>selector==='.nav-menu-disclosure',open:true}});
  assert.equal(f.run('kanpaceMobileMenuOpen'),true);
  html=f.run('kanpaceMenuMarkup()');assert(/<details class="nav-menu-disclosure" open>/.test(html));
  const link={getAttribute:()=> '#page=planning&tab=parts'};
  f.dispatch('click',{target:{closest:selector=>selector==='[data-nav-item]'?link:null},preventDefault(){}});
  assert.equal(f.run('kanpaceMobileMenuOpen'),false);assert.equal(node.open,false);
  assert.equal(f.c.writes.length,0);
});

test('group disclosure remembers manual choice and opens the group of a newly selected function',()=>{
  const f=fixture();f.apply('#page=overview');f.run('kanpaceMenuMarkup()');
  f.dispatch('toggle',{target:{matches:selector=>selector==='.nav-group',dataset:{navGroup:'review'},open:false}});
  assert.equal(f.run('kanpaceMenuState.review'),false);
  assert.equal(JSON.parse(f.storage.get('session:kanpace-navigation-groups-v3')).review,false);
  f.apply('#page=readiness&opTab=inspections&project=cab-a');
  const html=f.run('kanpaceMenuMarkup()');
  assert(/data-nav-group="field" open/.test(html));
  assert(!/data-nav-group="review" open/.test(html));
  assert.equal((html.match(/class="nav-group"[^>]* open/g)||[]).length,1);
});

test('stage primary links select the intended work view and clear stale task filters',()=>{
  const f=fixture(),groups=f.c.window.KANPACE_MENU;
  for(const [groupId,page,step,active] of [['import','daily','import','daily-import'],['review','drawing',null,'drawing'],['dispatch','tasks',null,'tasks'],['field','readiness',null,'issues'],['dashboard','overview',null,'overview']]){
    const group=groups.find(group=>group.id===groupId),item=group.items.find(item=>item.id===group.primary);
    f.c.executionFocus='paused';f.c.search='陈旧搜索';f.c.tradeFilter='不存在的工种';f.c.statusFilter='done';
    f.apply(f.c.window.kanpaceMenuHref(item,{projectId:'cab-a'}));
    assert.equal(f.c.page,page);assert.equal(new URLSearchParams(f.c.location.hash.slice(1)).get('step'),step);assert.equal(f.run('kanpaceActiveMenuItem()'),active);
    if(page==='tasks'){assert.equal(f.c.executionFocus,'all');assert.equal(f.c.search,'');assert.equal(f.c.tradeFilter,'');assert.equal(f.c.statusFilter,'');}
    assert.equal(f.c.projectId,'cab-a');
  }
  assert.equal(f.c.writes.length,0);
});

test('select factory entry focuses the available workspace selector',()=>{
  const f=fixture();let focused=0,scrolled=0,opened=0,prevented=0;
  f.elements.set('#workspace-type',{focus(){focused++;},scrollIntoView(){scrolled++;},showPicker(){opened++;}});
  f.dispatch('click',{target:{closest:selector=>selector==='[data-select-factory]'?{}:null},preventDefault(){prevented++;}});
  assert.equal(focused,1);assert.equal(scrolled,1);assert.equal(opened,1);assert.equal(prevented,1);
  assert(f.run('kanpaceWorkflowEntry()').includes('选择展柜、机械或现场'));
  assert(f.run('kanpaceMenuMarkup()').includes('data-nav-item="factory-onboarding"'));
});

test('draft review stays under step two while published tasks stay in field execution',()=>{
  const f=fixture();f.c.state.projects[0].status='draft';
  f.apply('#page=drawing&tab=tasks&project=cab-a');
  assert.equal(f.run('kanpaceActiveMenuItem()'),'draft-tasks');
  assert.equal(f.run('kanpaceModule().id'),'review');
  assert.match(f.run("kanpaceNavigationShell('<h1>任务草稿</h1>')"),/2 · 工程与计划[\s\S]*任务草稿复核/);
  f.c.state.projects[0].status='released';f.c.state.projects[0].released_revision=1;
  assert.equal(f.run('kanpaceActiveMenuItem()'),'tasks');
  assert.equal(f.run('kanpaceModule().id'),'dispatch');
});

test('configured modules keep independent permissions and select an available stage entry',()=>{
  const f=fixture({financial:false});
  f.c.window.kanpaceInstanceContext={profile:{enabled_modules:['overview','projects','drawing','readiness','deliveries','device']}};
  const html=f.run('kanpaceMenuMarkup()');
  for(const id of ['materials','deliveries','device','drawing','history'])assert(html.includes(`data-nav-item="${id}"`));
  for(const id of ['planning','checks','inspections','issues','tasks','owner','bi','costs','commercial','quote'])assert(!html.includes(`data-nav-item="${id}"`));
  assert(html.includes('data-nav-primary="drawing"'));assert(html.includes('data-nav-primary="daily-return"'));assert(html.includes('data-nav-primary="daily-dispatch"'));
  assert(!html.includes('data-nav-primary="owner"'));
  assert.equal(f.c.writes.length,0);
});

test('direct stage links also collapse the mobile menu and move focus after rendering',()=>{
  const f=fixture({mobile:true}),node={open:true,scrollTop:0};let focus=0;
  f.elements.set('.nav-menu-disclosure',node);f.elements.set('#main',{focus(){focus++;}});
  const link={getAttribute:()=> '#page=planning&tab=parts&project=cab-a'};
  f.dispatch('click',{target:{closest:selector=>selector==='[data-nav-primary]'?link:null},preventDefault(){}});
  assert.equal(node.open,false);assert.equal(f.run('kanpaceFocusAfterNavigation'),true);
  f.elements.delete('.nav-menu-disclosure');f.run('kanpaceNavigationAfterRender()');assert.equal(focus,1);
});

test('only the declared badge media section may scroll or focus a hardware panel',()=>{
  const f=fixture();let scrolled=0,focused=0;
  f.elements.set('#badge-media-panel',{scrollIntoView(){scrolled++;},querySelector:()=>({focus(){focused++;}})});
  f.apply('#page=device&section=badge-media-panel&project=cab-a');f.run('kanpaceNavigationAfterRender()');
  assert.equal(scrolled,1);assert.equal(focused,1);
  f.apply('#page=device&section=access-login-overlay&project=cab-a');f.run('kanpaceNavigationAfterRender()');
  assert.equal(scrolled,1);assert.equal(focused,1);
  assert.equal(f.c.writes.length,0);
});

async function mapFixture({isolated=true, financial=false, project='cab-a', pending=false}={}) {
  const elements=new Map();
  for(const id of ['map-search','map-tree','map-result','map-global','map-help','map-clear','map-changes'])elements.set('#'+id,{value:'',innerHTML:'',textContent:'',handlers:{},addEventListener(type,fn){this.handlers[type]=fn;},focus(){this.focused=true;}});
  const requests=[];
  const c={window:{},console,URLSearchParams,location:{search:'?'+new URLSearchParams({project})},document:{querySelector:selector=>elements.get(selector)},fetch:(url,options)=>{requests.push({url,options});return pending?new Promise(()=>{}):Promise.resolve({ok:true,json:async()=>url.endsWith('/status')?{isolated}:{enabled:true,financial_access:financial}});}};
  vm.createContext(c);
  for(const file of ['navigation-data.js','navigation-map/features.js','navigation-map/app.js'])vm.runInContext(read(file),c);
  await new Promise(resolve=>setImmediate(resolve));
  return {c,elements,requests};
}

test('complete feature map covers every shared menu and exposes only read navigation',async()=>{
  const f=await mapFixture({isolated:false,financial:true}),items=f.c.window.KANPACE_MENU.flatMap(group=>group.items);
  for(const item of items) {
    assert(f.c.window.KANPACE_FEATURES[item.id]?.length>0,item.label+' has an explanation');
    assert(f.elements.get('#map-tree').innerHTML.includes('>'+item.label+'</a>'),item.label+' is present');
  }
  const html=['#map-tree','#map-global','#map-help'].map(id=>f.elements.get(id).innerHTML).join('');
  for(const match of html.matchAll(/href="([^"]+)"/g)) {
    const url=new URL(match[1].replaceAll('&amp;','&'),'http://127.0.0.1:8765');
    assert.equal(url.origin,'http://127.0.0.1:8765');assert(!url.pathname.startsWith('/api/'));
    assert(!new URLSearchParams(url.hash.slice(1)).has('action'));
  }
  assert.deepEqual(f.requests.map(request=>request.url).sort(),['/api/access','/api/factory-instances/status']);
  assert(f.requests.every(request=>!request.options.method||request.options.method==='GET'));
});

test('feature map never shows private controller links before status or inside a customer instance',async()=>{
  for(const pending of [true,false]) {
    const f=await mapFixture({isolated:true,pending});
    const help=f.elements.get('#map-help').innerHTML;
    assert(!help.includes('/studies/'));assert(!help.includes('/open-source/'));assert(!help.includes('/integrations/'));
    assert(help.includes('文件导入能力说明'));
    const tree=f.elements.get('#map-tree').innerHTML;
    assert(!/href="[^"]*(?:page=quote|page=owner|opTab=costs|opTab=commercial)/.test(tree));
    assert(tree.includes('map-disabled'));
  }
});

test('map search and unknown project values stay escaped without injecting actions',async()=>{
  const hostile='missing-project&opTab=costs\"><img src=x onerror=alert(1)>',f=await mapFixture({project:hostile,financial:true});
  const html=f.elements.get('#map-tree').innerHTML;
  assert(!html.includes('<img src=x'));
  const drawing=[...html.matchAll(/href="([^"]+)"/g)].map(match=>match[1].replaceAll('&amp;','&')).find(href=>href.includes('page=drawing'));
  assert.equal(new URLSearchParams(drawing.split('#')[1]).get('project'),hostile);
  f.elements.get('#map-search').value='采购';f.elements.get('#map-search').handlers.input();
  assert(f.elements.get('#map-tree').innerHTML.includes('物料需求与采购'));assert(f.elements.get('#map-result').textContent.includes('找到'));
  f.elements.get('#map-search').value='<script>alert(1)</script>';f.elements.get('#map-search').handlers.input();
  assert(f.elements.get('#map-tree').innerHTML.includes('没有找到'));assert(!f.elements.get('#map-tree').innerHTML.includes('<script>'));
  f.elements.get('#map-clear').handlers.click();assert.equal(f.elements.get('#map-search').value,'');assert(f.elements.get('#map-search').focused);
  assert(f.requests.every(request=>!request.options.method||request.options.method==='GET'));
});

(async()=>{let failed=0;for(const [name,fn] of tests){try{await fn();console.log('PASS',name);}catch(error){failed++;console.error('FAIL',name,error.stack);}}console.log(`${tests.length-failed}/${tests.length} hierarchy route and business-view checks passed`);if(failed)process.exitCode=1;})();
