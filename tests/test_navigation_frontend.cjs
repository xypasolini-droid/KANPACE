'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createClient} = require('../static/core/http-client.js');
const base = path.join(__dirname, '../static');
const navigationDataSource = fs.readFileSync(path.join(base, 'navigation-data.js'), 'utf8');
const navigationSource = fs.readFileSync(path.join(base, 'navigation.js'), 'utf8');
const assistantSource = fs.readFileSync(path.join(base, 'agent-assistant.js'), 'utf8');
const html = fs.readFileSync(path.join(base, 'index.html'), 'utf8');
const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const plain = value => JSON.parse(JSON.stringify(value));
const escape = value => String(value ?? '').replace(/[&<>"']/g, x => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
function deferred() { let resolve, reject; const promise = new Promise((a,b)=>{resolve=a;reject=b;}); return {promise,resolve,reject}; }

function fixture() {
  const elements = new Map(), listeners = {}, timers = new Map(); let timerId = 0;
  class Element {
    constructor(id='') { this.id=id; this.innerHTML=''; this.textContent=''; this.value=''; this.open=false; this.disabled=false; this.dataset={}; this.attrs={}; this.isConnected=true; this.listeners={}; }
    setAttribute(k,v) { this.attrs[k]=v; }
    addEventListener(k,fn) { (this.listeners[k]??=[]).push(fn); }
    querySelector(selector) { return elements.get(selector) || null; }
    querySelectorAll() { return []; }
    getClientRects() { return this.isConnected ? [{width:100,height:20}] : []; }
    showModal() { this.open=true; }
    close() { if (!this.open) return; this.open=false; for(const fn of this.listeners.close||[])fn(); }
    focus() { c.document.activeElement=this; }
    append(el) { elements.set('#'+el.id,el); }
  }
  for (const id of ['ka-transcript','ka-input','ka-form','ka-project','ka-status']) elements.set('#'+id,new Element(id));
  const c = {
    console, URLSearchParams, AbortController, Error, TypeError, Object, Promise, Map, Set,
    window:{}, location:{hash:'',pathname:'/',search:''}, history:{replaceState(){}},
    state:{projects:[{id:'prj_a',name:'台湾珠宝柜',factory_type:'cabinet'},{id:'prj_b',name:'另一项目',factory_type:'cabinet'},{id:'prj_closed',name:'已发货项目',is_closed:true}],tasks:[{id:'task_a',project_id:'prj_a',title:'侧板封边',status:'ready',execution_version:7}]},
    projectId:'prj_a', workspaceType:'cabinet', page:'tasks', tab:'parts',
    accessState:{enabled:true,user:{id:'admin_a',role:'admin'},financial_access:true},
    workspaceProjects:()=>c.state?.projects || [], workspaceProfile:()=>({name:'展柜工厂'}), workspaceSelector:()=>'<select id="workspace-type"></select>',
    currentProject:()=>c.state?.projects.find(p=>p.id===c.projectId), projectIsClosed:p=>!!p?.is_closed,
    icon:()=>'', esc:escape,
    document:{body:new Element('body'),activeElement:null,querySelector:s=>elements.get(s)||null,querySelectorAll:s=>s==='dialog[open]'?[...elements.values()].filter(e=>e.open):[],createElement:()=>new Element(),addEventListener:(k,fn)=>(listeners[k]??=[]).push(fn)},
    setTimeout(fn,ms){timers.set(++timerId,{fn,ms});return timerId;},clearTimeout(id){timers.delete(id);},
    reads:[],writes:[],navigations:[],refreshes:0,logins:0,
    fetch:async(url,options)=>{c.reads.push({url,options,data:JSON.parse(options.body)});return c.readReply?c.readReply(url,options):{ok:true,status:200,json:async()=>({mode:'local_commands',message:'找到任务。',results:[],actions:[]})};},
    executionRequest:async(url,data)=>{c.writes.push({url,data});return c.writeReply?c.writeReply(url,data):{};},
    refresh:async()=>{c.refreshes++;}, navigate:(...args)=>c.navigations.push(args),
    taskModal:async id=>{c.openedTask=id;}, newProjectModal:async()=>{c.createdForm=true;}, importModal:()=>{c.uploadForm=true;},
    accessRequireLogin:()=>{c.logins++;c.window.KanpaceAgent.reset();c.state=null;elements.set('#access-login-overlay',new Element('access-login-overlay'));},
  };
  c.KanpaceHttp = createClient(c.fetch);
  vm.createContext(c);
  vm.runInContext(navigationDataSource,c);
  vm.runInContext(navigationSource,c);
  // Expose only to this isolated VM: no production file or browser state is changed.
  const marker='window.KanpaceAgent = Object.freeze({open,close,afterRender,reset});';
  assert(assistantSource.includes(marker),'Expected assistant registration point');
  vm.runInContext(assistantSource.replace(marker,marker+'\nwindow.testAgent={ask,execute,writePayload,actionMarkup,checkedRoute,openBusiness,entries:()=>entries};'),c);
  const agent=c.window.testAgent;
  c.window.KanpaceAgent.afterRender();
  c.window.KanpaceAgent.open();
  const card=(values={})=>{
    const result=new Element();const controls=[new Element()];
    return {result,controls,elements:{namedItem:key=>Object.hasOwn(values,key)?{value:values[key]}:null},reportValidity:()=>true,querySelector:()=>result,querySelectorAll:()=>controls};
  };
  const run=source=>vm.runInContext(source,c);
  return {c,run,elements,listeners,timers,agent,card};
}
const startAction = extra => ({type:'task_start',label:'确认开工',description:'台湾珠宝柜 · 侧板封边',taskId:'task_a',projectId:'prj_a',payload:{expected_execution_version:7,status:'in_progress',...extra}});
const response = actions => ({ok:true,status:200,json:async()=>({mode:'local_commands',message:'请核对操作。',results:[],actions})});
async function propose(f, action=startAction()) { f.c.readReply=async()=>response([action]); await f.agent.ask('开工 task_a');return f.agent.entries().at(-1); }

test('six ordered work stages keep business and settings reachable through clear second-level links',()=>{
  const f=fixture();assert.deepEqual(plain(f.run('kanpaceNavigation.map(x=>x.label)')),['订单工作流','选工厂','订单与资料','工程与计划','任务与人员','生产协同','总看板']);
  for(const [page,module] of [['drawing','review'],['quote','dashboard'],['tasks','dispatch'],['readiness','review'],['scheduling','review'],['people','factory'],['exchange','import'],['templates','factory']]){f.c.page=page;assert.equal(f.run('kanpaceModule().id'),module);}
  f.c.page='overview';
  const content=f.run("kanpaceNavigationShell('<h1>业务内容</h1>')");assert(content.includes('业务内容'));assert(content.includes('aria-label="功能菜单"'));assert(content.includes('data-action="agent-open"'));assert(!content.includes('开源技术选型'));assert(content.includes('AI 工作助手'));assert(!content.includes('全部功能地图'));assert(f.run('kanpaceManagementView()').includes('全部功能地图'));assert.equal((content.match(/data-workflow-stage=/g)||[]).length,6);
  for(const id of ['materials','issues','inspections','deliveries','costs','commercial','exchange'])assert(content.includes(`data-nav-item="${id}"`));
});
test('navigation preserves project IDs and cost tabs; arbitrary labels remain escaped',()=>{
  const f=fixture();assert.equal(f.run("kanpacePageHref('quote','prj_a')"),'#page=quote&tab=quote&project=prj_a');
  f.c.workspaceProfile=()=>({name:'<img src=x onerror=alert(1)>'});assert(f.run("kanpaceNavigationShell('')").includes('&lt;img'));assert(!f.run("kanpaceNavigationShell('')").includes('<img src=x'));
  f.c.accessState.financial_access=false;assert(!f.run('kanpaceManagementView()').includes('工艺与计价</strong>'));assert(f.run('kanpaceManagementView()').includes('使用帮助'));
});
test('script dependency order uses deferred local assets including cache parameters',()=>{
  const scripts=[...html.matchAll(/<script\b([^>]*)\bsrc="([^"]+)"([^>]*)>/g)].map(m=>({url:m[2].split('?')[0],defer:(m[1]+m[3]).includes('defer')}));
  for(const file of ['/core/http-client.js','/workspace.js','/navigation-data.js','/navigation.js','/app.js','/access-control.js','/agent-assistant.js'])assert(scripts.some(s=>s.url===file&&s.defer));
  for(const file of ['/app.js','/access-control.js','/agent-assistant.js'])assert(scripts.findIndex(s=>s.url==='/core/http-client.js')<scripts.findIndex(s=>s.url===file));
  assert(scripts.findIndex(s=>s.url==='/navigation-data.js')<scripts.findIndex(s=>s.url==='/navigation.js'));
  assert(scripts.findIndex(s=>s.url==='/navigation.js')<scripts.findIndex(s=>s.url==='/app.js'));
  assert(scripts.findIndex(s=>s.url==='/access-control.js')<scripts.findIndex(s=>s.url==='/agent-assistant.js'));
});
test('opening and asking never writes; request carries selected factory/project and no credential override',async()=>{
  const f=fixture();await f.agent.ask('今天先做什么');assert.equal(f.c.writes.length,0);assert.equal(f.c.reads[0].url,'/api/agent/message');assert.equal(f.c.reads[0].options.credentials,'same-origin');
  assert.equal(f.c.reads[0].data.project_id,'prj_a');assert.equal(f.c.reads[0].data.factory_type,'cabinet');assert.equal(f.c.reads[0].data.role,undefined);
});
test('unsupported navigation is refused while quote and existing project route work',()=>{
  const f=fixture();assert.equal(f.agent.checkedRoute({page:'quote',projectId:'prj_a'}).page,'quote');
  assert.throws(()=>f.agent.checkedRoute({page:'javascript:alert(1)'}));assert.throws(()=>f.agent.checkedRoute({page:'tasks',projectId:'prj_foreign'}));
});
test('confirmation payload only accepts fixed task fields and version',()=>{
  const f=fixture();const data=f.agent.writePayload(startAction({actor:'admin',url:'/api/device/flash',completed_quantity:999}),f.card());
  assert.deepEqual(plain(data),{expected_execution_version:7,status:'in_progress'});
  assert.throws(()=>f.agent.writePayload(startAction({expected_execution_version:undefined}),f.card()));
  assert.throws(()=>f.agent.writePayload({...startAction(),taskId:'../../api/admin'},f.card()));
});
test('pause reason is editable but validated and handover remains mandatory',()=>{
  const f=fixture();const action={...startAction(),type:'task_pause',payload:{expected_execution_version:7,reason:'other'}};
  assert.equal(f.agent.writePayload(action,f.card({reason:'material',note:'板材未到',handover_note:'已完成两块'})).reason,'material');
  assert.throws(()=>f.agent.writePayload(action,f.card({reason:'unsafe',note:'a',handover_note:'b'})));
  assert.throws(()=>f.agent.writePayload(action,f.card({reason:'material',note:'板材未到'})));
});
test('source text remains inert in answers, action labels, fields and results',async()=>{
  const f=fixture();const bad='<img src=x onerror="alert(1)">';const action={...startAction(),label:bad,description:bad};
  f.c.readReply=async()=>({ok:true,status:200,json:async()=>({mode:'local_commands',message:bad,results:[{kind:'task',id:'task_a',title:bad,detail:bad}],actions:[action]})});
  await f.agent.ask(bad);const markup=f.elements.get('#ka-transcript').innerHTML;assert(markup.includes('&lt;img'));assert(!markup.includes('<img src=x'));assert.equal(f.c.writes.length,0);
});
test('double confirmation causes one versioned write and retires all old proposal cards',async()=>{
  const f=fixture(),held=deferred();const entry=await propose(f);const card=f.card();f.c.writeReply=()=>held.promise;
  const first=f.agent.execute(entry,0,card);await f.agent.execute(entry,0,card);assert.equal(f.c.writes.length,1);
  held.resolve({});await first;await f.agent.execute(entry,0,card);assert.equal(f.c.writes.length,1);assert.equal(f.c.refreshes,1);assert(entry.expired);assert(entry.completed[0]);assert.equal(f.c.writes[0].url,'/api/tasks/task_a/status');
});
test('stale version conflict retires proposal without retrying write',async()=>{
  const f=fixture();const entry=await propose(f),card=f.card();f.c.writeReply=async()=>{const e=new Error('任务版本已更新');e.status=409;throw e;};
  await f.agent.execute(entry,0,card);await f.agent.execute(entry,0,card);assert.equal(f.c.writes.length,1);assert(entry.expired);assert(!entry.completed);assert.match(card.result.textContent,/未保存.*任务版本已更新/);
});
test('unknown save result cannot be replayed or presented as definitely unsaved',async()=>{
  const f=fixture();const entry=await propose(f),card=f.card();f.c.writeReply=async()=>{throw new TypeError('connection lost');};
  await f.agent.execute(entry,0,card);await f.agent.execute(entry,0,card);assert.equal(f.c.writes.length,1);assert.match(card.result.textContent,/未能确认保存结果/);assert(!entry.completed);assert(entry.expired);
});
test('new query expires old action even when subsequent query fails',async()=>{
  const f=fixture();const old=await propose(f);f.c.readReply=async()=>{throw new TypeError('offline');};await f.agent.ask('找新的任务');await f.agent.execute(old,0,f.card());assert.equal(f.c.writes.length,0);assert(old.expired);
});
test('logout clears conversation and ignores a late response from old account',async()=>{
  const f=fixture(),held=deferred();f.c.readReply=()=>held.promise;const pending=f.agent.ask('老板项目');f.c.window.KanpaceAgent.reset();
  held.resolve({ok:true,status:200,json:async()=>({mode:'local_commands',message:'old-account-secret',results:[],actions:[]})});await pending;
  assert.equal(f.agent.entries().length,0);assert(!f.elements.get('#ka-transcript').innerHTML.includes('old-account-secret'));assert.equal(f.elements.get('#kanpace-agent').open,false);
});
test('late write completion after logout cannot refresh or restore previous-account actions',async()=>{
  const f=fixture(),held=deferred();const entry=await propose(f);f.c.writeReply=()=>held.promise;
  const pending=f.agent.execute(entry,0,f.card());f.c.window.KanpaceAgent.reset();held.resolve({});await pending;
  assert.equal(f.c.writes.length,1);assert.equal(f.c.refreshes,0);assert.equal(f.agent.entries().length,0);assert(!entry.completed);assert.equal(f.elements.get('#kanpace-agent').open,false);
});
test('factory or account changes clear both pending and completed conversation',async()=>{
  const f=fixture();await f.agent.ask('当前任务');f.c.workspaceType='site';f.c.window.KanpaceAgent.afterRender();assert.equal(f.agent.entries().length,0);
  f.c.window.KanpaceAgent.open();await f.agent.ask('新的任务');f.c.accessState.user={id:'worker_b',role:'worker'};f.c.window.KanpaceAgent.afterRender();assert.equal(f.agent.entries().length,0);
});
test('closed project upload cannot start and business dialogs prevent nested assistant',async()=>{
  const f=fixture();await assert.rejects(f.agent.openBusiness({type:'open_upload',projectId:'prj_closed'}));assert(!f.c.uploadForm);
  f.c.window.KanpaceAgent.close();f.elements.set('#modal',{open:true});assert.equal(f.c.window.KanpaceAgent.open(),false);
});
test('unauthorized read clears session and opens established login flow',async()=>{
  const f=fixture();await f.agent.ask('当前任务');f.c.readReply=async()=>({ok:false,status:401,json:async()=>({error:'请先登录'})});await f.agent.ask('查看任务');assert.equal(f.c.logins,1);assert.equal(f.agent.entries().length,0);assert.equal(f.elements.get('#kanpace-agent').open,false);
});
test('unauthorized write clears session without retry or failed-operation card',async()=>{
  const f=fixture();const entry=await propose(f);f.c.writeReply=async()=>{const e=new Error('请先登录');e.status=401;throw e;};await f.agent.execute(entry,0,f.card());
  assert.equal(f.c.writes.length,1);assert.equal(f.c.logins,1);assert.equal(f.c.refreshes,0);assert.equal(f.agent.entries().length,0);assert.equal(f.elements.get('#kanpace-agent').open,false);
});

(async()=>{let failed=0;for(const [name,fn] of tests){try{await fn();console.log('PASS',name);}catch(error){failed++;console.error('FAIL',name,error.stack);}}console.log(`${tests.length-failed}/${tests.length} navigation and assistant frontend checks passed`);if(failed)process.exitCode=1;})();
