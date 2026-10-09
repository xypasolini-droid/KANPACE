'use strict';
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const {createClient}=require('../static/core/http-client.js');
const source=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');
class Element {
  constructor(){this.children=[];this.dataset={};this.className='';this.textContent='';this.innerHTML='';this.open=false;this.isConnected=true;this.value='';this.attributes={};this.classList={add(){},remove(){}};}
  setAttribute(name,value){this.attributes[name]=value;}
  append(child){child.parent=this;this.children.push(child);}
  prepend(child){child.parent=this;this.children.unshift(child);}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(x=>x!==this);this.isConnected=false;}
  querySelector(selector){return this.children.find(x=>selector==='.connection-banner'?x.className.includes('connection-banner'):selector==='.error-banner:not(.connection-banner)'?x.className==='error-banner':false)||null;}
}
const elements=Object.fromEntries(['#app','#main','#modal','#modal .dialog-body','#modal .dialog-error','#toast'].map(key=>[key,new Element()]));
const requests=[];
const c={trades:[],location:{hash:"#page=drawing"},console,Error,TypeError,SyntaxError,URLSearchParams,JSON,Array,Promise,document:{addEventListener(){},createElement:()=>new Element(),querySelectorAll(selector){return selector==='.connection-banner'?[...elements['#main'].children,...elements['#modal .dialog-body'].children].filter(x=>x.className.includes('connection-banner')):[];}},$:key=>elements[key]||null,esc:String,button:(label,action)=>`<button data-action="${action}">${label}</button>`,state:null,projectId:'wanted',refreshToken:0,page:'drawing',tab:'parts',quote:null,pendingTaskDeepLink:'',localStorage:{getItem(){return '';},setItem(k,v){c.savedProject=v;}},toast:message=>{c.toastMessage=message;},render(){c.rendered++;elements['#app'].innerHTML='restored';elements['#main'].children=[];},rendered:0,taskModal:async()=>{c.openedTask=true;},deviceStatus:null,deviceWifi:null,devicePorts:[],fetch:async(path,options)=>{requests.push({path,...options});return c.reply(path,options);}};
c.window=c;c.KanpaceHttp=createClient(c.fetch);vm.createContext(c);const run=code=>vm.runInContext(code,c),fn=name=>source.split('\n').find(line=>line.startsWith(`function ${name}(`)||line.startsWith(`async function ${name}(`));
run(fs.readFileSync(path.join(__dirname,'../static/workspace.js'),'utf8'));
run(source.slice(source.indexOf('let connectionError=null'),source.indexOf('\nfunction toast(')));
  run(source.slice(source.indexOf('let focusRefreshTimer='),source.indexOf('function canRefreshOnFocus(')));
  for(const name of ['currentProject','showError','deviceApi'])run(fn(name));
run(source.slice(source.indexOf('async function executionRequest('),source.indexOf('async function executionLoadQueue(')));
const fresh={projects:[{id:'other'},{id:'wanted'}],parts:[],tasks:[],documents:[]};
const success=result=>({ok:true,status:200,json:async()=>result});
(async()=>{
  c.reply=async()=>{throw new TypeError('Failed to fetch');};
  await assert.rejects(run("api('/api/state')"),error=>error.code==='NETWORK_UNAVAILABLE'&&error.message==='服务器未连接，请点击重新连接。');
  assert(elements['#app'].innerHTML.includes('服务器未连接'));assert(elements['#app'].innerHTML.includes('data-action="reconnect"'));assert(!elements['#app'].innerHTML.includes('Failed to fetch'));
  assert.equal(c.projectId,'wanted');assert.equal(requests.length,1);
  c.reply=async()=>success(fresh);await run('reconnect()');assert.equal(c.projectId,'wanted');assert.equal(c.savedProject,'wanted');assert.equal(c.rendered,1);assert.equal(run('connectionError'),null);

  // A write failure creates a reconnect notice without replaying the write or replacing the form.
  elements['#modal'].open=true;elements['#modal .dialog-body'].innerHTML='<input value="现场交接草稿">';c.pendingTaskDeepLink='some-old-deep-link';
  c.reply=async()=>{throw new TypeError('Load failed');};const before=requests.length;
  await assert.rejects(run("executionRequest('/api/tasks/t/progress',{completed_quantity:3})"),error=>error.code==='NETWORK_UNAVAILABLE');
  assert.equal(requests.length,before+1);assert.equal(requests.at(-1).method,'POST');
  assert.equal(elements['#main'].querySelector('.connection-banner').children[0].dataset.action,'reconnect');
  assert(elements['#modal .dialog-body'].querySelector('.connection-banner'));assert.equal(elements['#modal'].open,true);assert(elements['#modal .dialog-body'].innerHTML.includes('现场交接草稿'));
  elements['#modal .dialog-error'].textContent='服务器未连接，请点击重新连接。';
  c.reply=async()=>success(fresh);await run('reconnect()');assert.equal(requests.at(-1).method,'GET');assert.deepEqual(requests.slice(-2).map(r=>r.path),['/api/state','/api/workspace']);assert.equal(requests.length,before+3);
  assert.equal(elements['#modal'].open,true);assert(elements['#modal .dialog-body'].innerHTML.includes('现场交接草稿'));assert.equal(c.openedTask,undefined);assert.equal(c.pendingTaskDeepLink,'some-old-deep-link');
  assert.equal(elements['#modal .dialog-body'].querySelector('.connection-banner'),null);assert.equal(elements['#main'].querySelector('.connection-banner'),null);assert.equal(elements['#modal .dialog-error'].textContent,'');assert.equal(c.projectId,'wanted');

  // Business errors keep HTTP status, structured details and original wording.
  c.reply=async()=>({ok:false,status:400,json:async()=>({error:'缺少材料',details:['板材规格未填写']})});
  await assert.rejects(run("api('/api/parts',{})"),error=>error.status===400&&error.message==='缺少材料\n板材规格未填写'&&error.details[0]==='板材规格未填写'&&!error.code);
  c.reply=async()=>({ok:false,status:409,json:async()=>({error:'还有未完成的任务',details:{code:'unfinished_tasks',unfinished_task_count:2}})});
  await assert.rejects(run("executionRequest('/api/projects/p/fulfillment',{})"),error=>error.status===409&&error.details.code==='unfinished_tasks'&&error.message==='还有未完成的任务');assert.equal(run('connectionError'),null);
  c.reply=async()=>({ok:false,status:409,json:async()=>({error:'设备任务已变化',details:{device:{wifi:{connected:true}},ports:['test-port']}})});
  await assert.rejects(run("deviceApi('/api/device/send',{})"),error=>error.status===409&&error.details.device.wifi.connected&&error.message==='设备任务已变化');assert.equal(c.deviceWifi.connected,true);assert.deepEqual(c.devicePorts,['test-port']);
  c.reply=async()=>({ok:false,status:503,json:async()=>{throw new SyntaxError('Unexpected token <');}});
  await assert.rejects(run("api('/api/state')"),error=>error.code==='INVALID_RESPONSE'&&error.status===503&&error.message.includes('HTTP 503')&&!error.message.includes('Unexpected token'));
  assert.equal(run('connectionError'),null);
  c.reply=async()=>success(null);await assert.rejects(run("api('/api/state')"),error=>error.code==='INVALID_RESPONSE');
  c.reply=async()=>({ok:true,status:200,json:async()=>{throw new TypeError('network stream closed');}});
  await assert.rejects(run("deviceApi('/api/device/status')"),error=>error.code==='NETWORK_UNAVAILABLE');
  c.reply=async()=>{throw new TypeError('Failed to fetch');};c.retryButton=new Element();await run('reconnect(retryButton)');assert.equal(c.retryButton.disabled,false);assert.equal(c.retryButton.textContent,'重新连接');assert.equal(elements['#modal'].open,true);
  c.reply=async()=>success(fresh);await run('reconnect()');assert.equal(run('connectionError'),null);
  assert(source.includes("if(a==='reconnect')return await reconnect(b)"));assert(source.includes("window.addEventListener('DOMContentLoaded',startKanpaceApp,{once:true})"));
  console.log('PASS: readable offline boot, GET-only reconnect, existing project/form preservation, banner recovery, HTTP business errors, invalid JSON, stream failures, execution/device parity.');
})().catch(error=>{console.error(error);process.exitCode=1;});
