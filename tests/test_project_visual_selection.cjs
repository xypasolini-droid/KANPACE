const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const root=path.join(__dirname,'../static');
const draft=fs.readFileSync(path.join(root,'order-drafts.js'),'utf8');
const listeners={};let html='',renders=0,focused='';
const context={URL,Map,Set,location:{origin:'http://127.0.0.1:8776'},uploadBusy:false,
  state:{projects:[{id:'a',name:'订单 A'},{id:'b',name:'订单 B'}],documents:[]},projectId:'a',
  draftMediaCache:new Map(),ensureDraftMedia:()=>{},projectIsClosed:()=>false,
  esc:s=>String(s??''),icon:()=>'',button:(label,action,icon,cls,attrs)=>`<button data-action="${action}" ${attrs||''}>${label}</button>`,
  document:{addEventListener:(name,fn)=>listeners[name]=fn,querySelector:selector=>({focus:()=>focused=selector})},
  currentProject:()=>context.state.projects.find(p=>p.id===context.projectId),
  draftRenderPreserving:()=>{renders++;html=run('projectVisualPanel()');}
};
vm.createContext(context);const run=s=>vm.runInContext(s,context);
run(draft.slice(draft.indexOf('function draftMediaUnique('),draft.indexOf('function draftRenderPreserving(')));
run(fs.readFileSync(path.join(root,'project-visual.js'),'utf8'));
const entries=[{title:'靠墙柜台',kind:'效果图',url:'/api/drawing-media/assets/counter.png'},
  {title:'收银台',kind:'效果图',url:'/api/drawing-media/assets/cashier.png'},
  {title:'形象板',kind:'效果图',url:'/api/drawing-media/assets/sign.png'}];
const data={project_id:'a',renders:entries,sources:[]};
context.draftMediaCache.set('a',{status:'ready',data});
const click=index=>listeners.click({target:{closest:()=>({dataset:{action:'project-visual-select',index:String(index)}})}});
const selected=()=>run('projectVisualEntries()[projectVisualSelected(currentProject(),projectVisualEntries())]?.title');

// Actual delegated click handler + rendered large image, with legacy WPS entries that have no id.
assert.equal(selected(),'靠墙柜台');
for(const index of [2,1,0,2]){
  click(index);
  assert.equal(selected(),entries[index].title,'thumbnail click must select its own image, including id-less Excel images');
  assert(html.replace(/>\s+</g,'><').includes(`aria-label="放大查看${entries[index].title}"><img src="${entries[index].url}"`));
  assert(html.includes(`aria-pressed="true" aria-label="${entries[index].title}"`));
  assert(focused.includes(`data-index="${index}"`));
}
assert.equal(renders,4);
// Selection follows the resource through a list refresh/reorder, never its old index.
data.renders=[entries[2],entries[0],entries[1]];assert.equal(selected(),'形象板');
data.renders=data.renders.map((e,i)=>({...e,id:'new-server-id-'+i}));assert.equal(selected(),'形象板');
data.renders=entries.map((e,i)=>({...e,id:i===0?null:i===1?'':undefined}));click(1);assert.equal(selected(),'收银台');
run("projectVisualSelection.set('a',undefined)");assert.equal(selected(),'靠墙柜台');

// Existing stable ids and aliases from content deduplication remain supported.
data.renders=entries.map((e,i)=>({...e,id:'image-'+i}));click(2);
data.renders=[data.renders[2],data.renders[0]];assert.equal(selected(),'形象板');
data.renders=[{...entries[0],id:'primary',content_hash:'a'.repeat(64)},
  {...entries[1],id:'alias',content_hash:'a'.repeat(64)},entries[2]];
run("projectVisualSelection.set('a','alias')");assert.equal(selected(),'靠墙柜台');
// Id-less alias selection also survives a deduplication change after media reload.
data.renders=[entries[0],entries[1]];click(1);
data.renders=data.renders.map(e=>({...e,content_hash:'b'.repeat(64)}));assert.equal(selected(),'靠墙柜台');
context.projectId='b';context.draftMediaCache.set('b',{status:'ready',data:{project_id:'b',renders:entries.slice(0,2)}});
assert.equal(selected(),'靠墙柜台');click(1);assert.equal(selected(),'收银台');
context.projectId='a';assert.equal(selected(),'靠墙柜台');
data.renders=[];assert.equal(selected(),undefined);click(10);

// Missing ids must not collapse different engineering pages into a single page.
data.sources=[1,2,3].map(page=>({kind:'工程图',source_file:'加工图.pdf',page,url:`/api/documents/doc-a/preview-image?page=${page}`}));
assert.equal(run('projectEngineeringGroups()[0].entries.length'),3);
data.sources.push({...data.sources[1]});assert.equal(run('projectEngineeringGroups()[0].entries.length'),3);
console.log('PASS: real thumbnail click updates the large image for id-less/empty-id media; resource selection survives reorder, dedupe aliases and project switching; engineering pages remain distinct.');
