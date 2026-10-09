'use strict';
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');
const project={id:'closed-project',name:'订单 <A>',fulfillment_status:'shipped',is_closed:true};
const elements={
  '#modal':{open:false,close(){this.open=false;}},
  '#modal .dialog-error':{textContent:''},
  '#confirm-reopen-pause':{checked:false},
  '#confirm-unfinished':{checked:false},
  '#project-fulfillment':{}
};
const calls=[];
const context={console,JSON,Object,Map,Set,Array,Boolean,encodeURIComponent,
  state:{projects:[project],tasks:[],people:[{id:'worker',name:'张工'}]},
  fulfillmentDialog:null,fulfillmentNames:{active:'进行中',completed:'已完成',shipped:'已发货'},
  statusText:{in_progress:'进行中'},num:String,executionQueueById:new Map(),deviceTaskId:'',deviceDialogTaskId:'',
  $:selector=>elements[selector],button:(label,action)=>`<button data-action="${action}">${label}</button>`,
  openModal(title,body,footer){context.shown={title,body,footer};elements['#modal'].open=true;elements['#modal .dialog-error'].textContent='';elements['#confirm-reopen-pause'].checked=false;elements['#confirm-unfinished'].checked=false;},
  executionRequest:async(url,payload)=>{calls.push(JSON.parse(JSON.stringify({url,payload})));return context.reply(url,payload);},
  ensureDevicePolling(){},refresh:async()=>{context.refreshes++;},refreshes:0,
  render(){},toast:message=>{context.notice=message;},showError:()=>{throw Error('unexpected generic error');}
};
vm.createContext(context);const run=text=>vm.runInContext(text,context);
run(source.split('\n').find(line=>line.startsWith('const esc =')));
for(const name of ['projectIsClosed','fulfillmentModal','saveFulfillment','closeModal'])run(source.split('\n').find(line=>line.startsWith(`function ${name}(`)||line.startsWith(`async function ${name}(`)));
const conflict={code:'reopen_conflicts',conflicting_tasks:[],reopening_tasks:[{id:'task-1',title:'柜体开料',trade:'木工',assignee:'worker',status:'in_progress',remaining_quantity:1,execution_version:7,reasons:['当前已调岗 <木工>']} ]};
const failure=details=>Object.assign(new Error('需要重新安排'),{status:409,details});
const button=()=>({disabled:false,textContent:'重新打开',isConnected:true});
(async()=>{
  run("fulfillmentModal('closed-project','active')");
  assert.equal(calls.length,0);assert(context.shown.body.includes('订单 &lt;A&gt;'));
  context.reply=async()=>{throw failure(conflict);};context.actionButton=button();
  await run('saveFulfillment(actionButton)');assert.equal(calls.length,1);
  assert.deepEqual(calls[0].payload,{status:'active'});
  assert(context.shown.body.includes('1 项任务需要重新安排'));
  assert(context.shown.body.includes('当前已调岗 &lt;木工&gt;'));
  assert(context.shown.footer.includes('重新开启并暂停任务'));
  assert(!context.shown.body.includes('confirm-unfinished'));
  await run('saveFulfillment(actionButton)');assert.equal(calls.length,1);
  assert(elements['#modal .dialog-error'].textContent.includes('请确认'));
  run('closeModal()');assert.equal(calls.length,1);assert.equal(elements['#modal'].open,false);
  assert.equal(context.state.projects[0].fulfillment_status,'shipped');

  // A stale review opens the latest conflict list with unchecked confirmation.
  context.initialConflict=conflict;run("fulfillmentModal('closed-project','active',initialConflict)");
  elements['#confirm-reopen-pause'].checked=true;
  const changed={...conflict,reopening_tasks:[...conflict.reopening_tasks,{id:'task-2',title:'玻璃加工',trade:'玻璃',execution_version:3,reasons:['负责人正在执行其他订单']}]};
  context.reply=async()=>{throw failure(changed);};context.actionButton=button();
  await run('saveFulfillment(actionButton)');
  assert.deepEqual(calls.at(-1).payload,{status:'active',confirm_reopen_pause:true,reopen_task_versions:{'task-1':7}});
  assert(context.shown.body.includes('2 项任务需要重新安排'));
  assert.equal(elements['#confirm-reopen-pause'].checked,false);
  const before=calls.length;await run('saveFulfillment(actionButton)');assert.equal(calls.length,before);

  // Only a fresh, explicit confirmation may pause the shown tasks.
  elements['#confirm-reopen-pause'].checked=true;context.actionButton=button();
  context.reply=async()=>({project:{...project,is_closed:false,fulfillment_status:'active'},paused_task_ids:['task-1','task-2']});
  await run('saveFulfillment(actionButton)');
  assert.deepEqual(calls.at(-1).payload,{status:'active',confirm_reopen_pause:true,reopen_task_versions:{'task-1':7,'task-2':3}});
  assert.equal(context.state.projects[0].fulfillment_status,'active');assert.equal(elements['#modal'].open,false);
  assert.equal(context.refreshes,1);assert.equal(context.notice,'项目已重新打开，2 项任务已暂停待安排');

  // Existing unfinished-order confirmation keeps its original request contract.
  context.closeConflict={code:'unfinished_tasks',unfinished_task_count:1,unfinished_tasks:conflict.reopening_tasks};
  run("fulfillmentModal('closed-project','completed',closeConflict)");
  assert(context.shown.body.includes('confirm-unfinished'));assert(!context.shown.body.includes('confirm-reopen-pause'));
  context.actionButton=button();let count=calls.length;await run('saveFulfillment(actionButton)');assert.equal(calls.length,count);
  elements['#confirm-unfinished'].checked=true;
  let resolve;context.reply=()=>new Promise(r=>{resolve=r;});
  const pending=run('saveFulfillment(actionButton)');await run('saveFulfillment(actionButton)');assert.equal(calls.length,count+1);
  assert.deepEqual(calls.at(-1).payload,{status:'completed',confirm_unfinished:true});
  resolve({project:{...project,fulfillment_status:'completed'}});await pending;
  console.log('PASS: explicit reopen pause confirmation, cancellation without writes, escaped conflict reasons, stale-list reapproval, exact reviewed versions, preserved close confirmation, and duplicate click guard.');
})().catch(error=>{console.error(error);process.exitCode=1;});
