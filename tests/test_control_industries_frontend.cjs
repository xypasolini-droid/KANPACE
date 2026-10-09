'use strict';
// Exercise the production controller's public selection and reviewed-draft
// transitions; synthetic reference nodes deliberately cannot become live tasks.
const fs=require('fs'),path=require('path'),vm=require('vm');
const test=require('node:test'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../static/control/app.js'),'utf8');
const research=JSON.parse(fs.readFileSync(path.join(__dirname,'../static/industry-map/industries.json'),'utf8'));
const copy=x=>JSON.parse(JSON.stringify(x));
const node=(id,name,predecessors=[])=>({id,name,predecessors,trade:'样例工种',estimated_minutes:null,start_checks:['按确认资料准备'],acceptance:['按已确认要求核对'],instructions:'保留技术要求',quality_gate:false,workcenter_id:null});
const industries=research.map(i=>({...i,variants:(i.routeVariants||[{name:'标准生产类型'}]).map((v,n)=>({id:'variant_'+n,name:v.name}))}));
const templates=industries.flatMap(i=>i.variants.map(v=>({industry_id:i.id,industry_name:i.name,variant_id:v.id,name:v.name,factory_type:'machinery',hash:'sha-'+i.id+'-'+v.id,object_label:i.id+'工作对象',object_unit:'批',object_fields:[{id:'weight',label:'样例用量',type:'decimal',unit:'kg',required:true}],source_requirements:['engineering','acceptance'],source_requirements_display:[i.input],scope:'仅限样例范围',note:'由本厂核对后启用',sources:i.sources,nodes:[node('start','确认-'+i.id+'-'+v.id),node('a','分支A',['start']),node('b','分支B',['start']),node('end','汇合验收',['a','b'])]})));
const fixtureFactory={id:'inst_example',target_id:'inst_example',factory_id:'factory_example',factory_type:'machinery',name:'样例食品厂',industry_id:'food',variant_id:'variant_0',industry_name:'食品',url:'http://127.0.0.1:1234'};
const factoryCatalog=()=>({factory:fixtureFactory,active_profile:null,plans:[],defaults:{object_label:'设备',object_unit:'台',source_requirements:['engineering'],enabled_modules:['overview','projects','drawing','tasks'],default_page:'overview'},references:[{id:'builtin_machinery_v1',nodes:[node('legacy','旧参考工序')]}],source_types:[{id:'engineering',label:'工艺依据'},{id:'acceptance',label:'验收要求'}],available_modules:['overview','projects','drawing','tasks']});
const response=(data,status=200)=>({status,ok:status<400,json:async()=>data});
const tick=()=>new Promise(r=>setImmediate(r));
function el(){return {innerHTML:'',disabled:false,hidden:false,classList:{add(){},remove(){}},addEventListener(){}};}
class Values{constructor(form){this.rows=form.fields||[];}get(key){return this.rows.find(x=>x[0]===key)?.[1]??null;}getAll(key){return this.rows.filter(x=>x[0]===key).map(x=>x[1]);}[Symbol.iterator](){return this.rows[Symbol.iterator]();}}
function boot(search=''){
 const elements=new Map(['#notice','#content','#refresh','#logout','#industry-library','#industry-matches'].map(k=>[k,el()])),events={},calls=[];let fetcher=async()=>response({}),counter=0;
 const document={querySelector:s=>elements.get(s)||null,addEventListener:(name,fn)=>(events[name]??=[]).push(fn)};
 const ctx={document,console,location:{search},URL,URLSearchParams,FormData:Values,AbortController,setTimeout,clearTimeout,structuredClone,crypto:{randomUUID:()=>String(++counter)+'-request-1234567'},fetch:async(url,options)=>{calls.push({url,...options});return fetcher(url,options);}};
 const keys=['access','space','overview','catalog','target','plan','draft','preview','receipt','busy','industryCatalog','industryReferences','industryId','variantId','industrySearch','industryFamily','pendingIndustry','screen'];
 const code=source.replace(/load\(\);\s*\}\)\(\);\s*$/,`globalThis.qa={${['load','renderIndustryLibrary','chooseIndustry','selectedReference','libraryMatches','industryStages','draftFromIndustry','newDraft','editor','save','readForm','render'].join(',')},set:x=>{${keys.map(k=>`if('${k}' in x)${k}=x.${k};`).join('')}},get:()=>({${keys.join(',')}})};})();`);
 assert.notEqual(code,source);vm.createContext(ctx);vm.runInContext(code,ctx);
 const h={qa:ctx.qa,elements,calls,setFetch:f=>fetcher=f,emit:async(name,e)=>{for(const fn of events[name]||[])fn(e);await tick();await tick();}};
 h.seed=(authed=true)=>h.qa.set({industryCatalog:copy(industries),industryReferences:copy(templates),industryId:industries[0].id,variantId:industries[0].variants[0].id,access:authed?{enabled:true,user:{name:'管理者'}}:{enabled:false,setup_required:true},space:authed?{can_provision:true,isolated:false}:null,overview:authed?{factories:[fixtureFactory]}:null,target:authed?fixtureFactory:null,catalog:authed?factoryCatalog():null});
 h.click=action=>h.emit('click',{target:{closest:()=>({dataset:{action}})}});
 h.form=()=>{const d=h.qa.get().draft,fields=['name','object_label','object_unit','default_page','note'].map(k=>[k,d[k]||'']);for(const key of ['source_requirements','enabled_modules'])for(const v of d[key])fields.push([key,v]);const f={id:'plan-form',fields,reportValidity:()=>true,querySelectorAll:()=>d.nodes.map(n=>({dataset:{node:n.id},querySelector:s=>{const key=s.match(/name="([^"]+)"/)[1];return key==='quality_gate'?{checked:n.quality_gate}:{value:({'node-name':n.name,trade:n.trade,estimated_minutes:n.estimated_minutes??'',start_checks:n.start_checks.join('\n'),acceptance:n.acceptance.join('\n')})[key]??''};},querySelectorAll:()=>n.predecessors.map(value=>({value}))}))};h.elements.set('#plan-form',f);return f;};return h;
}

test('all 19 industry names and variants are available before administrator setup without protected reads',async()=>{
 const h=boot();h.setFetch(async url=>{if(url==='/api/access')return response({enabled:false,setup_required:true});if(url==='/api/industry-templates')return response({industries,templates,catalog_version:1});throw new Error('Unexpected protected read '+url);});
 await h.qa.load();assert.equal(h.qa.get().industryCatalog.length,19);for(const i of industries)assert.ok(h.elements.get('#industry-library').innerHTML.includes(i.name));assert.match(h.elements.get('#content').innerHTML,/设置中台管理员/);assert.equal(h.calls.length,2);assert.doesNotMatch(h.elements.get('#industry-library').innerHTML,/data-action="industry-apply"/);
});

test('each production variant selects its own exact route; choosing never overwrites the current form',()=>{
 const h=boot();h.seed();h.elements.get('#content').innerHTML='unsaved-form-sentinel';for(const i of industries)for(const v of i.variants){h.qa.chooseIndustry(i.id,v.id);const ref=h.qa.selectedReference();assert.equal(ref.industry_id,i.id);assert.equal(ref.variant_id,v.id);const html=h.elements.get('#industry-library').innerHTML;assert.ok(html.includes('确认-'+i.id+'-'+v.id));assert.equal(h.elements.get('#content').innerHTML,'unsaved-form-sentinel');}
});

test('search and family filters compose and produce an empty state',()=>{
 const h=boot();h.seed();h.qa.set({industrySearch:'藤铁'});assert.deepEqual(copy(h.qa.libraryMatches().map(i=>i.id)),['rattan']);h.qa.set({industryFamily:'不存在'});assert.equal(h.qa.libraryMatches().length,0);h.qa.renderIndustryLibrary();assert.match(h.elements.get('#industry-library').innerHTML,/没有找到/);h.qa.set({industrySearch:'',industryFamily:''});assert.equal(h.qa.libraryMatches().length,19);
});

test('dependency preview preserves parallel branches and waits for both before the join',()=>{
 const h=boot(),ref=templates[0];assert.deepEqual(copy(h.qa.industryStages(ref.nodes).map(stage=>stage.map(n=>n.id))),[['start'],['a','b'],['end']]);
});

test('replacing a draft requires explicit confirmation; cancellation preserves its edited nodes',async()=>{
 const h=boot();h.seed();const old={...h.qa.draftFromIndustry(templates[0]),name:'工厂已经修改的流程',nodes:[node('custom','本厂特殊工序')]};h.qa.set({draft:copy(old)});h.qa.chooseIndustry('food','variant_0');await h.click('industry-apply');assert.equal(h.qa.get().draft.nodes[0].id,'custom');assert.match(h.elements.get('#content').innerHTML,/未保存的调整会被替换/);await h.click('industry-cancel');assert.equal(h.qa.get().draft.name,old.name);assert.equal(h.qa.get().pendingIndustry,null);
 await h.click('industry-apply');await h.click('industry-confirm');assert.equal(h.qa.get().draft.industry_id,'food');assert.notEqual(h.qa.get().draft.nodes[0].id,'custom');assert.equal(h.qa.get().plan,null);
});

test('new factory drafts use their saved industry rather than the last publicly browsed industry',()=>{
 const h=boot();h.seed();h.qa.chooseIndustry('stone','variant_0');h.qa.newDraft();assert.equal(h.qa.get().draft.industry_id,'food');assert.equal(h.qa.get().draft.object_unit,'批');assert.equal(h.qa.get().draft.nodes[0].name,'确认-food-variant_0');assert.doesNotMatch(h.qa.editor(),/旧参考工序/);
});

test('saving industry draft carries origin hash and decimal object fields without supplying forged provenance',async()=>{
 const h=boot();h.seed();h.qa.set({draft:h.qa.draftFromIndustry(templates.find(r=>r.industry_id==='food'))});h.form();h.setFetch(async(url,options)=>response({plan:{...JSON.parse(options.body),id:'draft_1',version:1,status:'draft'}}));await h.qa.save(false);const data=JSON.parse(h.calls[0].body);assert.equal(data.industry_id,'food');assert.equal(data.source_industry_hash,'sha-food-variant_0');assert.equal(data.object_fields[0].type,'decimal');assert.equal(data.nodes[0].estimated_minutes,null);for(const k of ['industry_origin','scope','measurement_note','source_requirements_display'])assert.equal(data[k],undefined);
});

test('public browse cannot apply an industry to a factory',async()=>{
 const h=boot();h.seed(false);await h.click('industry-apply');assert.equal(h.calls.length,0);assert.equal(h.qa.get().draft,null);assert.match(h.elements.get('#notice').innerHTML,/先选择/);
});

test('reference source links and names are escaped and reject executable URLs',()=>{
 const h=boot();h.seed();const bad=copy(templates[0]);bad.sources=[{title:'<script>alert(1)</script>',url:'javascript:alert(1)'}];bad.nodes[0].name='<img onerror=alert(1)>';h.qa.set({industryReferences:[bad]});h.qa.renderIndustryLibrary();const html=h.elements.get('#industry-library').innerHTML;assert.match(html,/&lt;script&gt;/);assert.match(html,/&lt;img/);assert.doesNotMatch(html,/href="javascript:|<script>alert|<img onerror/);
});

test('industry provisioning carries industry and variant IDs and returns to that exact factory draft',async()=>{
 const h=boot();h.seed();h.qa.chooseIndustry('stone','variant_0');
 h.setFetch(async(url,options)=>{if(url==='/api/factory-instances/provision')return response({instance:{id:fixtureFactory.id}});if(url==='/api/control')return response({factories:[fixtureFactory]});return response(factoryCatalog());});
 const form={id:'provision-form',fields:[['name','样例食品厂'],['factory_type','machinery'],['industry_id','food'],['variant_id','variant_0'],['product','样例范围'],['admin_name','测试负责人'],['admin_username','test_only'],['admin_password','synthetic-only-pass']]};
 await h.emit('submit',{target:form,preventDefault(){}});const data=JSON.parse(h.calls[0].body);assert.equal(data.industry_id,'food');assert.equal(data.variant_id,'variant_0');assert.ok(data.request_id);assert.equal(h.qa.get().draft.industry_id,'food');assert.equal(h.qa.get().draft.nodes[0].name,'确认-food-variant_0');
});

test('bundled research catalog renders all 30 resolved production routes with readable scope labels',()=>{
 const {execFileSync}=require('node:child_process');
 const real=JSON.parse(execFileSync('python3',['-c','import json,industry_templates as it; c=it.catalog(); print(json.dumps({"industries":c,"templates":[it.resolve(i["id"],v["id"]) for i in c for v in i["variants"]]},ensure_ascii=False))'],{cwd:path.join(__dirname,'..'),encoding:'utf8',maxBuffer:4*1024*1024}));
 assert.equal(real.industries.length,19);assert.equal(real.templates.length,30);const h=boot();h.seed(false);h.qa.set({industryCatalog:real.industries,industryReferences:real.templates});
 for(const ref of real.templates){h.qa.chooseIndustry(ref.industry_id,ref.variant_id);assert.equal(h.qa.selectedReference().id,ref.id);const html=h.elements.get('#industry-library').innerHTML;assert.ok(html.includes('查看 '+ref.nodes.length+' 道工序与串并行'));assert.ok(html.includes(ref.nodes[0].name.replaceAll('&','&amp;')));assert.doesNotMatch(html,/>discrete_handoff<|>batch_coordination<|>continuous_coordination<|>controlled_system_handoff</);}
});

test('industry query parameters initialize the selected route and invalid variants fall back safely',async()=>{
 for(const [query,expected] of [['?industry=food&variant=variant_2','variant_2'],['?industry=food&variant=unknown','variant_0']]){
  const h=boot(query);h.setFetch(async url=>response(url==='/api/access'?{enabled:false,setup_required:true}:{industries,templates}));await h.qa.load();assert.equal(h.qa.get().industryId,'food');assert.equal(h.qa.get().variantId,expected);
 }
});
