const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(path.join(__dirname,'../static/project-visual.js'),'utf8').split("document.addEventListener('click'")[0];
const state={projects:[{id:'a',name:'项目 A'},{id:'b',name:'项目 B'}],documents:[]};
const context={console,Map,encodeURIComponent,state,projectId:'a',currentProject(){return state.projects.find(p=>p.id===context.projectId)},draftMediaCache:new Map(),ensureDraftMedia(){},projectIsClosed:p=>p.is_closed,esc:s=>String(s??''),icon:()=>'',button:(label,action)=>`<button data-action="${action}">${label}</button>`,draftMediaURL:s=>s,draftMediaUnique:entries=>entries,draftMediaSource:()=>'',document:{}};
vm.createContext(context);const run=s=>vm.runInContext(s,context);run(source);
assert.equal(run('projectVisualModelURL()'),'');
assert.equal(run('projectVisualModelURL(currentProject(),false)'),'');
assert(!run('projectVisualPanel()').includes('project-model-slot'));
assert(!run('projectVisualPanel()').includes('role="tablist"'));
state.projects[0].demo=true;
assert.equal(run('projectVisualModelURL()'),'');
assert(!run('projectVisualPanel()').includes('sample=1'));
state.projects[0].demo=false;
state.documents=[{id:'a-old',project_id:'a',filename:'old.STEP',superseded:true},{id:'b-model',project_id:'b',filename:'other.glb'},{id:'a-image',project_id:'a',filename:'render.stp',purpose:'render'},{id:'a-cad',project_id:'a',filename:'柜体&最新.step',sha256:'model-hash',revision:2},{id:'a-sample',project_id:'a',filename:'sample.glb',demo:true}];
// A candidate is not automatically the overall scene. The factory must select
// its role and bind the approved source hash/revision before the model appears.
assert.equal(run('projectVisualModelDocument()'),undefined);
Object.assign(state.projects[0],{main_model_document_id:'a-cad',main_model_source:{document_sha256:'model-hash',document_revision:2,role:'assembly'}});
assert.equal(run('projectVisualModelDocument().id'),'a-cad');
state.projects[0].main_model_source.document_sha256='old-hash';assert.equal(run('projectVisualModelDocument()'),undefined);
state.projects[0].main_model_source.document_sha256='model-hash';
state.projects[0].main_model_source.document_revision=1;assert.equal(run('projectVisualModelDocument()'),undefined);
state.projects[0].main_model_source.document_revision=2;
assert.equal(run('projectVisualModelURL()'),'/model/index.html?project=a&document=a-cad&embed=1');
assert(run('projectVisualPanel()').includes('data-mode="effects"'));assert(run('projectVisualPanel()').includes('aria-label="项目查看方式"'));
assert(run('projectVisualPanel()').indexOf('id="project-effects-tab"')<run('projectVisualPanel()').indexOf('id="project-model-tab"'));
run("projectVisualMode.set('a','model')");context.projectId='b';assert(run('projectVisualPanel()').includes('data-mode="effects"'));context.projectId='a';assert(run('projectVisualPanel()').includes('data-mode="model"'));
state.projects[0].is_closed=true;assert(!run('projectVisualPanel()').includes('上传模型</a>'));assert(run('projectVisualPanel()').includes('全屏查看'));state.projects[0].is_closed=false;
// Same URL preserves the same connected iframe node; a different project discards it.
let parked=0,moved=0,removed=0,created=0,appended=0;
const retained={hidden:false,getAttribute:()=>'/model/index.html?project=a&document=a-cad&embed=1',remove(){removed++}};
let slot={dataset:{src:retained.getAttribute(),title:'项目 A'},moveBefore(frame){assert.equal(frame,retained);moved++},closest:()=>({dataset:{mode:'model'}}),querySelector:()=>null,append(frame){assert.equal(frame.src,this.dataset.src);appended++}};
context.document={body:{moveBefore(frame){assert.equal(frame,retained);parked++}},querySelector:selector=>selector==='.project-model-frame'?retained:slot,createElement(){created++;return {setAttribute(){}}}};
assert.equal(run('captureProjectVisualFrame()'),retained);assert(retained.hidden);context.retained=retained;run('restoreProjectVisualFrame(retained)');assert.equal(parked,1);assert.equal(moved,1);assert.equal(created,0);assert.equal(retained.hidden,false);
slot.dataset.src='/model/index.html?project=b&document=b-model&embed=1';run('restoreProjectVisualFrame(retained)');assert.equal(removed,1);assert.equal(created,1);assert.equal(appended,1);
slot=null;run('restoreProjectVisualFrame(retained)');assert.equal(removed,2);
assert(!source.includes('/project-3d/'));assert(!source.includes('sample=1'));
console.log('PASS: real-image default, optional project-scoped uploaded models, no inferred/demo fallback, independent view tabs, closed upload controls, iframe identity retention and stale-project disposal.');
