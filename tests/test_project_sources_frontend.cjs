const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(path.join(__dirname,'../static/project-visual.js'),'utf8').split("document.addEventListener('click'")[0];
const project={id:'project-a',name:'整体装配'};
const overall={id:'overall',project_id:project.id,filename:'whole.step',purpose:'drawing',revision:2,sha256:'a'.repeat(64)};
const part={...overall,id:'part',filename:'last-part.step',sha256:'b'.repeat(64)};
const context={console,Map,Set,Math,Array,state:{projects:[project],documents:[overall,part]},currentProject:()=>project,projectIsClosed:p=>Boolean(p.is_closed),esc:s=>String(s??''),icon:()=>'',button:(text,action)=>`<button data-action="${action}">${text}</button>`,accessCan:()=>true};
vm.createContext(context);vm.runInContext(source,context);const run=s=>vm.runInContext(s,context);
assert.equal(run('projectVisualModelDocument()'),undefined,'Multiple model uploads need an explicit overall selection');
context.state.documents=[overall];assert.equal(run('projectVisualModelDocument()'),undefined,'Even one file may only be a part');
assert(run('projectVisualModelChoice()').includes('指定整体模型'));
Object.assign(project,{main_model_document_id:'overall',main_model_source:{document_sha256:overall.sha256,document_revision:2,role:'assembly'}});
context.state.documents.push(part);assert.equal(run('projectVisualModelDocument().id'),'overall');
assert(run('projectVisualModelChoice()').includes('whole.step · R2'));assert(run('projectVisualModelURL()').includes('document=overall'));
const original={...overall};
for(const patch of [{project_id:'other'},{superseded:true},{purpose:'render'},{shared_reference:true},{source_role:'shared_reference'},{revision:3},{sha256:'c'.repeat(64)}]){
  Object.assign(overall,original,patch);assert.equal(run('projectVisualModelDocument()'),undefined,JSON.stringify(patch));assert.equal(run('projectVisualModelURL()'),'');
  for(const key of Object.keys(overall))delete overall[key];Object.assign(overall,original);
}
project.main_model_source.role='appearance';assert.equal(run('projectVisualModelRole()'),'整体外观模型');
context.accessCan=()=>false;assert(!run('projectVisualModelChoice()').includes('data-action='));context.accessCan=()=>true;
project.is_closed=true;assert(!run('projectVisualModelChoice()').includes('data-action='));project.is_closed=false;
context.state.documents=[part];assert(run('projectVisualModelChoice()').includes('整体模型需要重新指定'));assert.equal(run('projectVisualModelDocument()'),undefined);
console.log('PASS: explicit whole-project model, no latest-file fallback, pinned revision, reference isolation, and closed/role read-only selector.');
