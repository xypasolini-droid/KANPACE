const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const code=fs.readFileSync(path.join(__dirname,'../static/project-overview.js'),'utf8');
let current={id:'a'},dialog={open:false},loading=null,form=null,errorBox={},requests=[],calls=[];
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};};
const context={console,Set,Number,Array,state:{projects:[current]},currentProject:()=>current,projectIsClosed:p=>p.closed,accessCan:()=>true,
  document:{addEventListener:()=>{},querySelector:s=>s==='#modal'?dialog:s==='#project-overview-loading'?loading:s==='#modal .dialog-error'?errorBox:s==='#project-overview-form,#project-overview-link-form'?form:null},
  openModal:(title,body,foot)=>{calls.push({title,body,foot});dialog.open=true;loading=body.includes('project-overview-loading')?{}:null;},
  closeModal:()=>{dialog.open=false;form=null;},api:(url,data)=>{const pending=deferred();requests.push({url,data,...pending});return pending.promise;},
  esc:s=>String(s??''),button:(label,action)=>`<button data-action="${action}">${label}</button>`,
  invalidateProjectVisuals:()=>{},draftRenderPreserving:()=>{},toast:s=>calls.push({toast:s})};
vm.createContext(context);vm.runInContext(code,context);const run=s=>vm.runInContext(s,context);
const empty={project:{id:'a'},version:0,candidates:[]};
(async()=>{
  let pending=run('openProjectOverviewPDF()');current={id:'b'};requests.at(-1).resolve(empty);await pending;
  assert.equal(calls.length,1,'late response must not open a different project');
  current={id:'a'};pending=run('openProjectOverviewPDF()');dialog.open=false;requests.at(-1).resolve(empty);await pending;
  assert.equal(calls.length,2,'closing the dialog cancels late rendering');
  pending=run('openProjectOverviewPDF()');context.openModal('上传','another form');const count=calls.length;
  requests.at(-1).reject(new Error('network'));await pending;assert.equal(calls.length,count,'late failure must not replace another modal');
  pending=run('openProjectOverviewPDF()');requests.at(-1).resolve(empty);await pending;
  assert(calls.at(-1).body.includes('先上传本项目的效果方案 PDF'));assert(calls.at(-1).foot.includes('上传方案 PDF'));
  pending=run('openProjectOverviewPDF()');requests.at(-1).reject(new Error('读取失败'));await pending;
  assert(calls.at(-1).body.includes('读取失败'));assert(calls.at(-1).foot.includes('重新读取'));
  current.closed=true;const before=requests.length;await run('openProjectOverviewPDF()');assert.equal(requests.length,before);delete current.closed;
  // Repeated save is coalesced and server conflicts remain actionable in the same form.
  form={querySelectorAll:()=>[]};dialog.open=true;errorBox={};context.control={disabled:false};
  run("projectOverviewContext={projectId:'a',version:2}");
  pending=run("saveProjectOverview(control,{panorama_url:''})");await run("saveProjectOverview(control,{panorama_url:''})");
  assert.equal(requests.length,before+1);assert(context.control.disabled);
  requests.at(-1).reject(new Error('整体效果设置已变化，请重新打开后选择'));await pending;
  assert(errorBox.textContent.includes('已变化'));assert.equal(context.control.disabled,false);
  console.log('PASS: overview request isolation, closed/replaced dialogs, empty and failed reads, closed projects, duplicate save guard and recoverable conflict.');
})().catch(e=>{console.error(e);process.exitCode=1});
