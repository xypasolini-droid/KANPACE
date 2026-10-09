'use strict';
// Run the production controller IIFE with a small DOM/fetch seam. Browser layout
// is verified separately; these tests exercise actual state transitions/payloads.
const fs=require('fs'),path=require('path'),vm=require('vm');
const test=require('node:test'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../static/control/app.js'),'utf8');
const clone=value=>JSON.parse(JSON.stringify(value));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const reply=(data,status=200)=>({ok:status>=200&&status<300,status,json:async()=>data});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const factory=(id='A')=>({id:'inst_'+id,target_id:'inst_'+id,factory_id:'factory_'+id,name:id+'工厂',factory_type:'cabinet',url:'http://127.0.0.1:12345'});
const node=(id='one')=>({id,name:id+'加工',trade:'木工',predecessors:[],start_checks:['材料齐套'],acceptance:['尺寸合格'],instructions:'保留工艺要求',estimated_minutes:null,quality_gate:false,workcenter_id:null});
function catalog(f=factory()) {return {factory:f,active_profile:null,plans:[],receipts:[],defaults:{object_label:'柜号',object_unit:'件',source_requirements:['engineering','bom'],enabled_modules:['overview','projects','drawing','tasks'],default_page:'overview'},references:[{id:'builtin_cabinet_v1',nodes:[node('one'),node('two')]}],source_types:[{id:'engineering',label:'工程依据'},{id:'bom',label:'制造清单'}],available_modules:['overview','projects','drawing','planning','tasks']};}
const access=()=>({enabled:true,user:{id:'admin',name:'主管',role:'admin'}});
function element(){return {innerHTML:'',hidden:false,disabled:false,classList:{add(){},remove(){}},listeners:{},addEventListener(type,fn){this.listeners[type]=fn;}};}
class FormValues {constructor(form){this.rows=form.fields||[];}get(key){return this.rows.find(row=>row[0]===key)?.[1]??null;}getAll(key){return this.rows.filter(row=>row[0]===key).map(row=>row[1]);}[Symbol.iterator](){return this.rows[Symbol.iterator]();}}
function boot(){
 const elements=new Map(['#notice','#content','#refresh','#logout'].map(k=>[k,element()])),events={},calls=[];
 let fetcher=async()=>reply({}),uuid=0;
 const document={querySelector:s=>elements.get(s)||null,addEventListener(type,fn,options){(events[type]??=[]).push({fn,options});}};
 const ctx={console,document,URL,URLSearchParams,AbortController,setTimeout,clearTimeout,structuredClone,FormData:FormValues,crypto:{randomUUID:()=>`request-${++uuid}-abcdefgh`},fetch:async(url,options)=>{calls.push({url,options});return fetcher(url,options);}};
 const keys=['access','space','overview','catalog','target','plan','draft','preview','receipt','busy','epoch','screen','installRequest','provisionRequest'];
 const injection=`globalThis.__qa={${['esc','factoryURL','load','run','request','clear','newDraft','readForm','save','render','editor','previewView','factoryDetail','refreshCatalog'].join(',')},set:values=>{${keys.map(k=>`if('${k}' in values)${k}=values.${k};`).join('')}},get:()=>({${keys.join(',')}})};`;
 const code=source.replace(/load\(\);\s*\}\)\(\);\s*$/,injection+'\n})();');
 assert.notEqual(code,source,'Test seam must replace only the final auto-load call');
 vm.createContext(ctx);vm.runInContext(code,ctx);
 const h={qa:ctx.__qa,ctx,elements,events,calls,setFetch:fn=>{fetcher=fn;}};
 h.seed=(f=factory(),cat=catalog(f))=>{h.qa.set({access:access(),space:{isolated:false,can_provision:true},overview:{factories:[f]},target:f,catalog:cat});return cat;};
 h.form=(d,overrides={})=>{
   const fields=['name','object_label','object_unit','default_page','note'].map(k=>[k,overrides[k]??d[k]??'']);
   for(const k of ['enabled_modules','source_requirements'])for(const v of overrides[k]??d[k]??[])fields.push([k,v]);
   const items=(overrides.nodes??d.nodes).map(n=>({dataset:{node:n.id},querySelector(selector){const name=selector.match(/name="([^\"]+)"/)?.[1];if(name==='quality_gate')return {checked:n.quality_gate};return {value:({'node-name':n.name,trade:n.trade,estimated_minutes:n.estimated_minutes??'',start_checks:n.start_checks.join('\n'),acceptance:n.acceptance.join('\n')})[name]??''};},querySelectorAll(){return n.predecessors.map(value=>({value}));}}));
   const form={id:'plan-form',fields,reportValidity:()=>true,querySelectorAll:()=>items};elements.set('#plan-form',form);return form;
 };
 h.emit=async(type,event)=>{for(const listener of events[type]||[])listener.fn(event);await tick();await tick();};
 return h;
}

test('initial authenticated load selects a registered factory and reads only its catalog',async()=>{
 const h=boot(),f=factory();h.setFetch(async url=>reply(url==='/api/access'?access():url==='/api/factory-instances/status'?{isolated:false,can_provision:true}:url==='/api/control'?{factories:[f]}:catalog(f)));
 await h.qa.load();assert.equal(h.qa.get().target?.factory_id,f.factory_id);assert.ok(h.calls.some(c=>c.url.includes('/inst_A/config?factory_id=factory_A')));assert.match(h.elements.get('#content').innerHTML,/配置这家工厂的流程/);
});

test('HTML text is escaped and factory links are limited to loopback HTTP',()=>{
 const h=boot(),f=factory();f.name='<img src=x onerror=alert(1)>';h.seed(f);h.qa.newDraft();let html=h.qa.editor();assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<img src=x/);assert.equal(h.qa.esc('"<&\''),'&quot;&lt;&amp;&#39;');
 for(const url of ['javascript:alert(1)','https://example.com','http://127.0.0.1.evil.test:123'])assert.equal(h.qa.factoryURL({url}),null);
 assert.equal(h.qa.factoryURL({url:'http://127.0.0.1:12345/anything'}),'http://127.0.0.1:12345/factory/index.html');assert.doesNotMatch(h.qa.factoryURL({url:'http://user:secret@localhost:12345'}),/secret|user/);
});

test('form reads nodes in their own scope, keeps unknown time and mandatory modules/sources',()=>{
 const h=boot();h.seed();h.qa.newDraft();const d=h.qa.get().draft;
 const nodes=[{...node('one'),name:'开料',estimated_minutes:null,start_checks:['板材确认'],acceptance:['长度']},{...node('two'),name:'钻孔',trade:'五金',estimated_minutes:12.5,predecessors:['one'],start_checks:['刀具确认'],acceptance:['孔位'],quality_gate:true}];
 h.form(d,{nodes,enabled_modules:[],source_requirements:[],default_page:'planning'});h.qa.readForm();const result=clone(h.qa.get().draft);
 assert.deepEqual(result.nodes.map(n=>[n.name,n.trade,n.estimated_minutes,n.predecessors,n.acceptance]),[['开料','木工',null,[],['长度']],['钻孔','五金',12.5,['one'],['孔位']]]);
 assert.equal(result.nodes[1].quality_gate,true);assert.equal(result.nodes[0].instructions,'保留工艺要求');
 for(const m of ['projects','drawing','tasks','planning'])assert.ok(result.enabled_modules.includes(m));assert.deepEqual(result.source_requirements,['engineering']);
});

test('save draft returns its ID/version and subsequent save updates that exact record',async()=>{
 const h=boot();h.seed();h.qa.newDraft();h.form(h.qa.get().draft);let version=0;
 h.setFetch(async(_url,options)=>reply({plan:{...JSON.parse(options.body),id:'plan_A',status:'draft',version:++version}}));
 await h.qa.save(false);assert.equal(h.qa.get().plan.version,1);h.form(h.qa.get().draft);await h.qa.save(false);
 assert.match(h.calls[0].url,/\/config\/plans$/);assert.match(h.calls[1].url,/\/config\/plans\/plan_A$/);assert.equal(JSON.parse(h.calls[1].options.body).expected_version,1);assert.equal(h.qa.get().plan.version,2);
});

test('unconfirmed create response blocks repeat saves until an explicit reload',async()=>{
 const h=boot();h.seed();h.qa.newDraft();h.form(h.qa.get().draft);h.setFetch(async()=>{throw new Error('connection lost after write');});
 await h.qa.run(()=>h.qa.save(false));assert.equal(h.calls.length,1);await h.qa.run(()=>h.qa.save(false));assert.equal(h.calls.length,1,'A timed-out create must not silently create another draft');assert.match(h.elements.get('#notice').innerHTML,/刷新|核对/);
});

test('stale access response after logout cannot restore the previous user in memory',async()=>{
 const h=boot(),old=deferred();h.setFetch(()=>old.promise);const pending=h.qa.load();h.qa.clear();h.qa.set({access:null,screen:'login'});old.resolve(reply(access()));await pending;assert.equal(h.qa.get().access,null);assert.equal(h.qa.get().screen,'login');
});

test('a second refresh is serialized while the first request is pending',async()=>{
 const h=boot(),old=deferred();h.setFetch(()=>old.promise);
 const first=h.qa.load();await h.qa.load();assert.equal(h.calls.length,1);assert.equal(h.elements.get('#refresh').disabled,true);assert.equal(h.elements.get('#logout').disabled,true);
 old.resolve(reply({error:'会话到期'},401));await first;assert.equal(h.qa.get().screen,'login');assert.equal(h.qa.get().busy,false);
});

test('factory interaction is blocked while a background catalog refresh is pending',async()=>{
 const h=boot(),a=factory('A'),b=factory('B'),old=deferred();h.seed(a);
 h.setFetch(async url=>url==='/api/access'?reply(access()):url==='/api/factory-instances/status'?reply({isolated:false,can_provision:true}):url==='/api/control'?reply({factories:[a,b]}):old.promise);
 const loading=h.qa.load();await tick();let changed=false;await h.qa.run(async()=>{changed=true;h.qa.set({target:b,catalog:catalog(b)});});assert.equal(changed,false);old.resolve(reply(catalog(a)));await loading;
 assert.equal(h.qa.get().target.factory_id,a.factory_id);assert.equal(h.qa.get().catalog.factory.factory_id,a.factory_id);
});

test('install retry reuses the same request ID and normalized preview objects',async()=>{
 const h=boot();h.seed();h.qa.newDraft();const p={...clone(h.qa.get().draft),id:'plan_A',version:1},objects=[{code:'SAMPLE-01',name:'样例',quantity:1,unit:'件',location:'',instructions:'',document_ids:[],batch_code:'',delivery_group:''}];h.qa.set({draft:null,plan:p,preview:{plan:p,preview_token:'hash',objects}});
 const form={id:'install-form',fields:[['reviewed','on'],['reviewer','主管'],['review_note','已核对']]};let installCalls=0;
 h.setFetch(async(url,options)=>{if(url.endsWith('/install')){installCalls++;if(installCalls===1)throw new Error('lost ack');return reply({profile:{...p,id:'profile_A',version:1,template_id:'template_A'},receipt:{id:'receipt_A'}});}return reply(catalog());});
 const event={target:form,preventDefault(){}};await h.emit('submit',event);await h.emit('submit',event);
 const calls=h.calls.filter(c=>c.url.endsWith('/install')).map(c=>JSON.parse(c.options.body));assert.equal(calls.length,2);assert.equal(calls[0].request_id,calls[1].request_id);assert.deepEqual(calls[0].objects,objects);
});

test('invalid controls open enclosing details and credentials never use browser storage',async()=>{
 const h=boot(),details={open:false,parentElement:{closest:()=>null}};await h.emit('invalid',{target:{closest:s=>s==='details'?details:null}});assert.equal(details.open,true);
 assert.doesNotMatch(source,/localStorage|sessionStorage|indexedDB|document\.cookie\s*=/);assert.doesNotMatch(source,/password[^\n]*console\.|console\.[^\n]*password/);
});


test('failed reconciliation after an uncertain create keeps repeat save blocked',async()=>{
 const h=boot();h.seed();h.qa.newDraft();h.form(h.qa.get().draft);h.setFetch(async()=>{throw new Error('write response lost');});await h.qa.run(()=>h.qa.save(false));
 h.setFetch(async url=>{if(url==='/api/access')return reply(access());throw new Error('catalog cannot be reloaded');});await h.qa.load();const before=h.calls.filter(c=>c.options.method==='POST').length;await h.qa.run(()=>h.qa.save(false));assert.equal(h.calls.filter(c=>c.options.method==='POST').length,before);
});

test('a confirmed install still renders its receipt when later catalog refresh fails',async()=>{
 const h=boot();h.seed();h.qa.newDraft();const p={...clone(h.qa.get().draft),id:'plan_A',version:1};h.qa.set({draft:null,plan:p,preview:{plan:p,preview_token:'hash',objects:[]}});
 h.elements.get('#content').innerHTML='<form id="install-form">old preview</form>';
 h.setFetch(async url=>{if(url.endsWith('/install'))return reply({profile:{...p,id:'profile_A',template_id:'template_A'},receipt:{id:'receipt_A'}});throw new Error('catalog offline');});
 await h.emit('submit',{target:{id:'install-form',fields:[['reviewed','on'],['reviewer','主管'],['review_note','核对完毕']]},preventDefault(){}});
 assert.match(h.elements.get('#content').innerHTML,/配置已启用/);assert.doesNotMatch(h.elements.get('#content').innerHTML,/id="install-form"/);assert.equal(h.qa.get().receipt.profile.id,'profile_A');
});
