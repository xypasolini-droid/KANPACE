'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
// Reuse the established isolated DOM/API fixture, with additional test-only exports.
const fixtureText=fs.readFileSync(path.join(__dirname,'test_navigation_frontend.cjs'),'utf8').split('const startAction =')[0]
  .replace('window.testAgent={ask,execute,writePayload,actionMarkup,checkedRoute,openBusiness,entries:()=>entries};',
           'window.testAgent={ask,execute,writePayload,actionMarkup,checkedRoute,openBusiness,workflowMarkup,schedulePayload,previewSchedule,applySchedule,onClick,entries:()=>entries};');
const context={require,__dirname,module:{exports:null},console,URLSearchParams,AbortController};
vm.runInNewContext(fixtureText+'\nmodule.exports=fixture;',context);
const fixture=context.module.exports,plain=x=>JSON.parse(JSON.stringify(x)),tests=[];
const test=(name,fn)=>tests.push([name,fn]);
const reply=data=>({ok:true,status:200,json:async()=>data});
const workflow={id:'wf_'+'a'.repeat(32),status:'review',engine:'LangGraph',steps:[{title:'核对项目交期',detail:'1 个延期项目'},{title:'核对原因',detail:'缺料与暂停'}],causes:[{title:'侧板',evidence:['缺少木板']}],sources:[{id:'task_a',project_id:'prj_a',page:'tasks',label:'侧板原记录'}]};
const base={mode:'local_commands',message:'已核对',results:[],actions:[],workflow};
const config={name:'候选',start_date:'2026-09-07',horizon_days:30,factory_type:'cabinet',task_ids:['task_a'],rush_task_ids:[],engine:'ortools',time_limit_seconds:10000,allow_fallback:true,actor:'admin',url:'/api/device/flash'};
const previewAction={type:'schedule_preview',label:'核对并生成预览',payload:config};
const scenario={id:'scenario_a',version:1,name:'候选',rows:[{task_id:'task_a',title:'侧板',start_at:'2026-09-07T08:00',ready_at:'2026-09-07T09:00'}],summary:{scheduled:1,unplaced:0,frozen_plans:0},unplaced:[],impact:[]};
async function propose(f,actions=[previewAction]){f.c.readReply=async()=>reply({...base,actions});await f.agent.ask('分析延期原因并比较排程');return f.agent.entries().at(-1);}
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return{resolve,promise};}

test('multi-step result shows evidence and sources without making writes',async()=>{
 const f=fixture();await propose(f);const html=f.elements.get('#ka-transcript').innerHTML;
 for(const label of ['核对项目交期','核对原因','缺少木板','侧板原记录'])assert(html.includes(label));
 assert.equal(f.c.writes.length,0);
});
test('continuing graph calls the original read endpoint and cannot inject tool execution',async()=>{
 const f=fixture();const entry=await propose(f,[{type:'workflow_continue',label:'继续',payload:{id:workflow.id,decision:'compare',tool:'flash'}}]);
 await f.agent.onClick({target:{closest:()=>({dataset:{ka:'action',entry:String(entry.id),index:'0'}})}});
 assert.equal(f.c.writes.length,0);assert.equal(f.c.reads.length,2);
 assert.deepEqual(plain(f.c.reads[1].data.workflow),{id:workflow.id,decision:'compare'});
});
test('continuation preserves the project or whole-factory scope resolved by the server',async()=>{
 for(const projectId of ['prj_b',null]) {
  const f=fixture();f.c.readReply=async()=>reply({...base,scope:{projectId,factoryType:'cabinet'},
   actions:[{type:'workflow_continue',label:'继续',payload:{id:workflow.id,decision:'compare'}}]});
  await f.agent.ask('分析另一项目的延期原因');const entry=f.agent.entries().at(-1);
  await f.agent.onClick({target:{closest:()=>({dataset:{ka:'action',entry:String(entry.id),index:'0'}})}});
  assert.equal(f.c.reads[1].data.project_id,projectId || undefined);assert.equal(f.c.writes.length,0);
 }
});
test('preview payload restricts engine, scope, inputs and solver budget',async()=>{
 const f=fixture();await propose(f);const data=plain(f.agent.schedulePayload(previewAction));
 assert.equal(data.engine,'ortools');assert.equal(data.time_limit_seconds,10);assert.equal(data.allow_fallback,false);
 assert.equal(data.actor,undefined);assert.equal(data.url,undefined);assert.deepEqual(data.overrides,[]);
 assert.throws(()=>f.agent.schedulePayload({...previewAction,payload:{...config,task_ids:['task_foreign']}}));
 assert.throws(()=>f.agent.schedulePayload({...previewAction,payload:{...config,factory_type:'site'}}));
});
test('explicit preview and separate apply use existing versioned scheduling APIs',async()=>{
 const f=fixture(),entry=await propose(f);f.c.writeReply=async()=>({scenario});
 await f.agent.previewSchedule(entry,0);assert.equal(f.c.writes.length,1);assert.equal(f.c.writes[0].url,'/api/scheduling/preview');
 assert(f.elements.get('#ka-transcript').innerHTML.includes('确认采用这份排程'));
 await f.agent.applySchedule(entry,f.card({note:'工位已核对'}));
 assert.equal(f.c.writes.length,2);assert.equal(f.c.writes[1].url,'/api/scheduling/scenario_a/apply');
 assert.deepEqual(plain(f.c.writes[1].data),{expected_version:1,note:'工位已核对'});assert(entry.expired);
});
test('double preview and repeated apply cannot duplicate writes',async()=>{
 const f=fixture(),entry=await propose(f),wait=deferred();f.c.writeReply=()=>wait.promise;
 const pending=f.agent.previewSchedule(entry,0);await f.agent.previewSchedule(entry,0);assert.equal(f.c.writes.length,1);
 wait.resolve({scenario});await pending;await f.agent.previewSchedule(entry,0);assert.equal(f.c.writes.length,1);
 await f.agent.applySchedule(entry,f.card({note:'采用'}));await f.agent.applySchedule(entry,f.card({note:'采用'}));assert.equal(f.c.writes.length,2);
});
test('stale apply retires preview and never retries automatically',async()=>{
 const f=fixture(),entry=await propose(f);f.c.writeReply=async()=>({scenario});await f.agent.previewSchedule(entry,0);
 f.c.writeReply=async()=>{const error=new Error('生产资料变化');error.status=409;throw error;};
 await f.agent.applySchedule(entry,f.card({note:'采用'}));assert(entry.expired);assert.match(entry.scheduleResult,/未采用.*生产资料变化/);
 await f.agent.applySchedule(entry,f.card({note:'再试'}));assert.equal(f.c.writes.length,2);
});
test('logout during preview cannot restore old account data',async()=>{
 const f=fixture(),entry=await propose(f),wait=deferred();f.c.writeReply=()=>wait.promise;
 const pending=f.agent.previewSchedule(entry,0);f.c.window.KanpaceAgent.reset();wait.resolve({scenario});await pending;
 assert.equal(f.agent.entries().length,0);assert(!entry.schedule);assert.equal(f.c.refreshes,0);
});
test('untrusted workflow, model and source text is escaped',async()=>{
 const f=fixture(),bad='<img src=x onerror=alert(1)>';
 f.c.readReply=async()=>reply({...base,workflow:{...workflow,model_summary:bad,steps:[{title:bad,detail:bad}],causes:[{title:bad,evidence:[bad]}],sources:[{label:bad}]}});
 await f.agent.ask('分析延期原因');const html=f.elements.get('#ka-transcript').innerHTML;assert(!html.includes('<img src=x'));assert(html.includes('&lt;img'));assert.equal(f.c.writes.length,0);
});
(async()=>{let failed=0;for(const[name,fn]of tests){try{await fn();console.log('PASS',name);}catch(error){failed++;console.error('FAIL',name,error.stack);}}console.log(`${tests.length-failed}/${tests.length} workflow frontend checks passed`);if(failed)process.exitCode=1;})();
