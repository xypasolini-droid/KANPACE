'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const test=require('node:test'),assert=require('node:assert/strict');
const app=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');
const home=fs.readFileSync(path.join(__dirname,'../static/factory-home.js'),'utf8');
const visual=fs.readFileSync(path.join(__dirname,'../static/project-visual.js'),'utf8');
const drafts=fs.readFileSync(path.join(__dirname,'../static/order-drafts.js'),'utf8');
const range=(source,start,end)=>source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));
const one=(source,name)=>source.split('\n').find(line=>line.startsWith('function '+name+'('));
function boot(){
  const c={console,URLSearchParams,Date,Map,Set,Number,Array,Promise,encodeURIComponent,
    state:{projects:[{id:'p1',name:'珠宝柜 <A>',factory_type:'cabinet',revision:2,status:'draft',due_date:'2026-09-12'}],tasks:[],parts:[],documents:[],people:[]},
    page:'drawing',tab:'parts',projectStatusFilter:'active',workspaceType:'cabinet',
    executionFocus:'all',search:'',tradeFilter:'',statusFilter:'',trades:['木工'],executionPauseNames:{},
    fulfillmentNames:{active:'进行中',completed:'已完成 · 待发货',shipped:'已发货'},
    document:{addEventListener(){}},render(){},icon:()=>'<svg></svg>',num:v=>String(v??'—'),date:v=>v||'未填写',localTimestamp:v=>v||'',
    esc:v=>String(v??'').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x])),
    button:(label,action,icon,cls='',attrs='')=>`<button class="btn ${cls}" data-action="${action}" ${attrs}>${label}</button>`,
    fulfillmentBadge:()=>'',tag:()=>'',projectLifecycleActions:()=>'<details><summary>项目状态</summary></details>',projectReadOnlyNotice:()=>'',
    accessCan:()=>true,KanpaceIntelligence:{openEngineering(){throw new Error('View must not run recognition');}},
    api(){throw new Error('Rendering must not write or request production changes');},
    workspaceProfile:()=>({name:'展柜工厂'}),projectVisualEntries:()=>[],draftMediaURL:v=>String(v||'').startsWith('/api/')?v:'',
    executionSorted:rows=>rows,executionPriority:()=>0,executionStatusTag:task=>task.status,
    executionPerson:()=>null,executionCompleted:()=>0,executionRemaining:task=>task.quantity||1,
  };
  c.currentProject=()=>c.state.projects[0];
  c.parts=()=>c.state.parts.filter(p=>p.project_id==='p1');c.tasks=()=>c.state.tasks.filter(t=>t.project_id==='p1');c.docs=()=>c.state.documents.filter(d=>d.project_id==='p1'&&d.purpose!=='render');
  c.workspaceProjects=()=>c.state.projects.filter(p=>p.factory_type==='cabinet');
  vm.createContext(c);
  for(const name of ['projectIsClosed','historicalDemoIsComplete','fulfillmentStatus','fulfillmentBadge','projectLifecycleActions'])vm.runInContext(one(app,name),c);
  vm.runInContext(range(app,'function projectWorkflowContext(','function projectHead('),c);
  vm.runInContext(range(app,'function processBasisIsCurrent(','function uploadDocSummary('),c);
  vm.runInContext(range(app,'function projectHead(','function stageStrip('),c);
  vm.runInContext(range(app,'function documentConfirmationStages()','function taskView('),c);
  vm.runInContext(range(app,'function taskView(','function projectList('),c);
  vm.runInContext(home,c);
  vm.runInContext(one(app,'projectList'),c);
  vm.runInContext(one(visual,'projectVisualPanorama'),c);
  vm.runInContext(range(visual,'function projectVisualCardImage(','function projectVisualSelected('),c);
  c.run=code=>vm.runInContext(code,c);
  return c;
}
test('task heading promotes production context and distinguishes current publication from stale release',()=>{
  const c=boot();c.page='tasks';
  let html=c.projectHead();assert.match(html,/<h1>任务草稿<\/h1>/);assert.match(html,/查看任务图纸/);
  assert.doesNotMatch(html,/data-action="import"|\/model\/index/);
  Object.assign(c.currentProject(),{status:'released',released_revision:2});assert.match(c.projectHead(),/<h1>生产任务<\/h1>/);
  c.currentProject().released_revision=1;assert.match(c.projectHead(),/<h1>任务草稿<\/h1>/);
  c.currentProject().is_closed=true;assert.match(c.projectHead(),/<h1>生产记录<\/h1>/);
});
test('AI drawing action delegates to the existing evidence tool and only prefills the scoped assistant',()=>{
  const c=boot(),before=JSON.stringify(c.state);
  const html=c.projectDrawingToolbar();assert.match(html,/data-intel="engineering"/);
  assert.match(html,/data-agent-prompt="检查当前订单的拆单依据" data-agent-project="p1"/);
  assert.match(html,/AI 辅助拆单/);assert.doesNotMatch(html,/data-action="generate"|自动发布|已精准识别/);
  assert.equal(JSON.stringify(c.state),before);
  c.accessCan=()=>false;assert.match(c.projectDrawingToolbar(),/data-intel="engineering" disabled/);
  c.currentProject().is_closed=true;assert.equal(c.projectDrawingToolbar(),'');
});
test('next action follows current part review and never describes a draft as production',()=>{
  const c=boot();c.state.parts=[{id:'part1',project_id:'p1',review_status:'pending'}];
  assert.match(c.projectDrawingToolbar(),/data-action="review-next"/);
  assert.doesNotMatch(c.projectDrawingToolbar(),/data-action="generate"/);
  c.state.parts[0].review_status='approved';assert.match(c.projectDrawingToolbar(),/生成任务草稿/);
  c.state.tasks=[{id:'t1',project_id:'p1',status:'draft',revision:2}];assert.match(c.projectDrawingToolbar(),/核对任务草稿/);
  Object.assign(c.currentProject(),{status:'released',released_revision:2});assert.match(c.projectDrawingToolbar(),/查看生产任务/);
});
test('stale draft states the current engineering version and the exact recovery path',()=>{
  const c=boot();c.state.parts=[{id:'part1',project_id:'p1',review_status:'approved'}];
  c.state.tasks=[{id:'task-old',project_id:'p1',status:'invalidated',revision:1,title:'板材开料',quantity:1,trade:'木工'}];
  assert.match(c.projectDrawingToolbar(),/当前工程 R2，1 道旧任务待重审，不能派工/);
  const html=c.taskView(true);
  assert.match(html,/工程 R2 · 1 道任务待重审/);
  assert.match(html,/核对 R2 图纸/);
  assert.match(html,/按 R2 更新工序/);
  assert.doesNotMatch(html,/确认并发布任务/);
  c.currentProject().is_closed=true;
  assert.doesNotMatch(c.taskView(true),/task-version-notice|核对 R2 图纸/);
});
test('manual part form only offers current native engineering originals as review evidence',()=>{
  const c=boot();
  c.categoryText={wood:'木作板件'};
  c.openModal=(title,body,footer)=>{c.modal={title,body,footer};};
  for(const name of ['stepApprovalFields','manualPartSourceDocuments','manualPartSourceField','partModal'])vm.runInContext(one(app,name),c);
  c.partModal('',true);
  assert.match(c.modal.body,/请先上传本项目的 DWG、SLDASM、SLDPRT 或 SLDDRW 原件/);
  assert.match(c.modal.body,/data-action="import"[^>]*type="button"/);
  assert.match(c.modal.footer,/disabled title="请先上传工程原件"/);
  const base={project_id:'p1',purpose:'drawing',sha256:'a'.repeat(64),revision:2};
  c.state.documents=[
    {...base,id:'doc_dwg',filename:'柜体施工图.dwg'},
    {...base,id:'doc_asm',filename:'总装.SLDASM'},
    {...base,id:'doc_prt',filename:'边框.sldprt'},
    {...base,id:'doc_drw',filename:'图纸<危险>.slddrw'},
    {...base,id:'doc_pdf',filename:'核对图.pdf'},
    {...base,id:'doc_foreign',project_id:'p2',filename:'外厂.dwg'},
    {...base,id:'doc_old',filename:'旧图.dwg',superseded:true},
    {...base,id:'doc_archived',filename:'归档.dwg',archived:true},
    {...base,id:'doc_process',filename:'工艺.dwg',purpose:'process'},
    {...base,id:'doc_missing_hash',filename:'未存档.dwg',sha256:''},
    {...base,id:'legacy',filename:'旧编号.dwg'},
  ];
  assert.equal(c.manualPartSourceDocuments().map(d=>d.id).join(','),'doc_dwg,doc_asm,doc_prt,doc_drw');
  c.partModal('',true);
  assert.match(c.modal.body,/<select id="part-source-document" name="source_document_id" aria-describedby="part-source-help" required>/);
  assert.match(c.modal.body,/value="doc_dwg"/);
  assert.match(c.modal.body,/图纸&lt;危险&gt;\.slddrw/);
  assert.match(c.modal.body,/请对照原图核对材料、尺寸和数量；新增后仍需逐项复核/);
  assert.doesNotMatch(c.modal.body,/value="doc_pdf"|value="doc_foreign"|value="doc_old"|<危险>/);
  assert.doesNotMatch(c.modal.footer,/disabled/);
});
test('manual part submission sends selected source_document_id and rejects a stale selection',async()=>{
  const c=boot();let click,focused=false;const calls=[],error={textContent:''};
  c.document.addEventListener=(name,handler)=>{if(name==='click')click=handler;};
  c.closedProjectActions=new Set();c.uploadBusy=false;c.showError=e=>{throw e;};
  const form={dataset:{id:'',add:'true'},reportValidity:()=>true,elements:{source_document_id:{focus(){focused=true;}}}};
  c.$=selector=>selector==='#part-form'?form:selector==='#modal .dialog-error'?error:null;
  c.formValues=()=>({name:'侧板',material:'MDF',quantity:'2',source_document_id:'doc_native'});
  c.submitOperation=(_button,operation)=>operation();
  c.api=(url,payload)=>{calls.push({url,payload});return Promise.resolve({});};
  c.state.documents=[{id:'doc_native',project_id:'p1',purpose:'drawing',filename:'柜体.dwg',sha256:'b'.repeat(64)}];
  vm.runInContext(one(app,'manualPartSourceDocuments'),c);
  vm.runInContext(range(app,"document.addEventListener('click',async event=>","document.addEventListener('change',"),c);
  const button={dataset:{action:'save-part',approved:'false'}},event={target:{closest:()=>button}};
  await click(event);
  assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/parts');
  assert.equal(calls[0].payload.project_id,'p1');
  assert.equal(calls[0].payload.source_document_id,'doc_native');
  assert.equal(calls[0].payload.quantity,2);
  c.state.documents=[];
  await click(event);
  assert.equal(calls.length,1);assert.equal(focused,true);
  assert.match(error.textContent,/原件已更新/);
});
test('imported drawing draft keeps questions ahead of production and does not offer direct generation',()=>{
  const c=boot();c.currentProject().order_draft={issues:['柜号待核对']};c.state.parts=[{project_id:'p1',review_questions:['数量待核对']}];
  const html=c.projectDrawingToolbar(true);assert.match(html,/核对 2 项疑问/);assert.match(html,/data-tab="draft-review"/);
  assert.doesNotMatch(html,/data-action="generate"|data-action="release"/);
  c.run("let draftSelectionProject='',draftLevelFilter='',draftSearch='',draftTradeFilter='';");
  c.ensureDraftMedia=()=>{};c.projectVisualPanel=()=>'<div id="real-project-image"></div>';c.projectEngineeringPanel=()=>'<div id="engineering-sources"></div>';c.draftParts=()=>'<div id="part-review"></div>';
  c.factoryProjectMainline=()=>'';vm.runInContext(one(drafts,'orderDraftView'),c);
  const view=c.orderDraftView();assert(view.indexOf('AI 辅助拆单')<view.indexOf('id="real-project-image"'));
  assert.match(view,/任务草稿/);assert.doesNotMatch(view,/工种拆分/);
  c.currentProject().evidence_policy='staged';
  const staged=c.orderDraftView();
  assert.match(staged,/id="document-confirmations-title"/);
  assert(staged.indexOf('id="document-confirmations-title"')<staged.indexOf('id="real-project-image"'));
});
test('draft task deep link uses task context even when the retained URL tab is parts',()=>{
  const c=boot();c.page='tasks';c.tab='parts';c.currentProject().order_draft={issues:['材料待确认']};
  c.run("let draftSelectionProject='',draftLevelFilter='',draftSearch='',draftTradeFilter='';");
  c.ensureDraftMedia=()=>{};c.factoryProjectMainline=()=>'';c.draftScopes=()=>'<section id="draft-task-scope"></section>';
  vm.runInContext(one(drafts,'orderDraftView'),c);
  const html=c.orderDraftView('tasks');
  assert.match(html,/<h1>任务草稿<\/h1>/);assert.match(html,/珠宝柜 &lt;A&gt;/);
  assert.match(html,/class="btn primary" data-action="tab" data-tab="draft-review">核对待确认项/);
  assert.match(html,/查看任务图纸/);assert.match(html,/id="draft-task-scope"/);
  assert.doesNotMatch(html,/data-action="import"|data-action="release"|data-action="generate"/);
  c.currentProject().is_closed=true;
  const closed=c.orderDraftView('tasks');assert.match(closed,/<h1>任务草稿记录<\/h1>/);
  assert.doesNotMatch(closed,/核对待确认项|data-action="import"/);
});
test('project cards reuse the daily summary and keep shortage links scoped to the exact order',()=>{
  const c=boot(),p=c.currentProject();Object.assign(p,{status:'released',released_revision:2});
  c.state.tasks=[{id:'t1',project_id:'p1',revision:2,status:'ready',title:'开料'}];
  c.run("factoryHomeSnapshot=state;factoryHomeScope='cabinet';factoryHomeProduction={projects:state.projects,materials:[{id:'m1',project_id:'p1',shortage_quantity:2}]};");
  c.state.projects.push({id:'closed',factory_type:'cabinet',name:'已发货订单',fulfillment_status:'shipped'},{id:'foreign',factory_type:'site',name:'另一个场景'});
  const html=c.projectList();assert.match(html,/1 项物料有缺口/);assert.match(html,/opTab=materials&amp;opProject=p1/);
  assert.match(html,/珠宝柜 &lt;A&gt;/);assert.doesNotMatch(html,/另一个场景|<h2>已发货订单/);
  assert.doesNotMatch(html,/已齐套|可立即开工/);
  c.projectStatusFilter='shipped';assert.match(c.projectList(),/查看项目记录/);assert.doesNotMatch(c.projectList(),/opTab=materials/);
});
test('historical imported projects are visibly marked without implying review or approval',()=>{
  const c=boot(),p=c.currentProject();p.demo_dataset=true;
  assert.match(c.projectList(),/历史资料演示/);
  assert.match(c.projectHead(),/历史资料演示/);
  assert.doesNotMatch(c.projectList(),/客户已确认|技术已复核/);
});
test('historical completed case shows its replay status without a fictitious delivery date',()=>{
  const c=boot(),p=c.currentProject();p.demo_dataset=true;p.historical_order=true;p.due_date='';
  c.projectStatusFilter='active';assert.doesNotMatch(c.projectList(),/data-id="p1"/);
  c.projectStatusFilter='all';
  const card=c.projectList(),head=c.projectHead();
  assert.match(card,/历史已完成 · 演示复盘/);
  assert.match(head,/历史已完成 · 演示复盘/);
  assert.doesNotMatch(card,/未填写 交付|项目状态/);
  assert.doesNotMatch(head,/交付 未填写|历史资料演示/);
});
test('card image is an actual project render; another project or construction drawing cannot become the render',()=>{
  const c=boot(),p=c.currentProject();c.state.documents=[{id:'d1',project_id:'p1',purpose:'drawing',filename:'施工图.png'},{id:'d2',project_id:'other',purpose:'render',filename:'另一厂.jpg'}];
  assert.doesNotMatch(c.projectVisualCardImage(p),/<img/);assert.match(c.projectVisualCardImage(p),/待补整体效果/);
  c.state.documents.push({id:'r1',project_id:'p1',purpose:'render',filename:'批准效果图.jpg'});
  assert.match(c.projectVisualCardImage(p),/src="\/api\/documents\/r1\/image"/);
  c.state.documents.at(-1).superseded=true;assert.doesNotMatch(c.projectVisualCardImage(p),/<img/);
});
test('drawing and version pages keep one clear path without the old daily rail or quote tab',()=>{
  const c=boot();
  vm.runInContext(one(app,'tabs'),c);
  assert.doesNotMatch(c.tabs(),/成本报价/);
  c.historyView=()=>'<section id="version-files"></section>';
  vm.runInContext(one(app,'historyOnlyView'),c);
  vm.runInContext(one(app,'drawingView'),c);
  c.tab='history';
  const history=c.drawingView();
  assert.match(history,/图纸版本记录/);
  assert.match(history,/id="version-files"/);
  assert.match(history,/返回拆与核对/);
  assert.doesNotMatch(history,/项目工作区|每日工作六步骤|成本报价|任务草稿/);
  c.tab='parts';
  c.projectDrawingToolbar=()=>'<div id="review-tools"></div>';
  c.projectVisualPanel=()=>'<div id="effect-image"></div>';
  c.projectEngineeringPanel=()=>'<div id="drawing-files"></div>';
  c.partsTable=()=>'<div id="part-list"></div>';
  c.reviewPanel=()=>'<aside id="review-panel"></aside>';
  c.KanpaceRound1={panel:()=>'<section id="model-outline"></section>'};
  const drawing=c.drawingView();
  assert.match(drawing,/<details class="drawing-optional">/);
  assert.match(drawing,/id="part-list"/);
  assert.doesNotMatch(drawing,/每日工作六步骤|成本报价/);
});
test('customer confirmation appears only for real cabinet projects with staged evidence policy',()=>{
  const c=boot(),p=c.currentProject();
  assert.equal(c.documentConfirmationsPanel(),'');
  p.evidence_policy='staged';
  const html=c.documentConfirmationsPanel();
  assert.match(html,/客户确认/);
  assert.match(html,/效果图/);
  assert.match(html,/施工图/);
  assert.match(html,/工程图/);
  assert.match(html,/0 \/ 3/);
  assert.match(html,/data-action="document-confirmation-upload" data-stage="render"/);
  assert.match(html,/先记录效果图确认/);
  c.accessCan=()=>false;
  assert.match(c.documentConfirmationsPanel(),/data-action="document-confirmation-open" data-stage="render" disabled/);
  p.is_closed=true;
  assert.doesNotMatch(c.documentConfirmationsPanel(),/data-action="document-confirmation-upload"|data-action="document-confirmation-open"/);
  p.is_closed=false;
  p.workflow_id='workflow_reviewed';assert.equal(c.documentConfirmationsPanel(),'');
  p.workflow_id='';
  p.demo=true;assert.equal(c.documentConfirmationsPanel(),'');
  p.demo=false;p.factory_type='site';assert.equal(c.documentConfirmationsPanel(),'');
});
test('customer confirmation stays pinned to current project source bytes and full stage order',()=>{
  const c=boot(),p=c.currentProject(),sha='a'.repeat(64);
  p.evidence_policy='staged';
  c.state.documents=[
    {id:'doc_render',project_id:'p1',purpose:'render',filename:'确认效果.jpg',sha256:sha},
    {id:'doc_construction',project_id:'p1',purpose:'drawing',filename:'施工.dwg',sha256:'b'.repeat(64)},
    {id:'doc_engineering',project_id:'p1',purpose:'drawing',filename:'总装.sldasm',sha256:'c'.repeat(64),part_count:2},
  ];
  c.state.parts=[{id:'part_engineering',project_id:'p1',document_id:'doc_engineering',review_status:'approved',draft_only:false,archived:false}];
  p.document_confirmations={
    render:{document_id:'doc_render',document_sha256:sha,note:'客户微信确认'},
    construction:{document_id:'doc_construction',document_sha256:'b'.repeat(64),note:'确认施工图'},
  };
  const ready=c.documentConfirmationsPanel();
  assert.match(ready,/2 \/ 3/);
  assert.match(ready,/确认效果\.jpg/);
  assert.match(ready,/依据：客户微信确认/);
  assert.match(ready,/data-action="document-confirmation-open" data-stage="engineering"/);
  c.state.documents[0].superseded=true;
  const stale=c.documentConfirmationsPanel();
  assert.match(stale,/0 \/ 3/);
  assert.match(stale,/文件已换版/);
  assert.match(stale,/先记录效果图确认/);
  assert.doesNotMatch(stale,/依据：确认施工图/);
});
test('customer confirmation choices follow the server file rules and engineering review gate',()=>{
  const c=boot(),p=c.currentProject();p.evidence_policy='staged';
  const base={project_id:'p1',purpose:'drawing',sha256:'a'.repeat(64)};
  c.state.documents=[
    {...base,id:'doc_render',purpose:'render',filename:'效果.jpg'},
    {...base,id:'doc_dwg',filename:'施工.dwg'},
    {...base,id:'doc_pdf',filename:'施工.pdf'},
    {...base,id:'doc_image',filename:'施工.png'},
    {...base,id:'doc_asm',filename:'总装.sldasm'},
    {...base,id:'doc_step',filename:'结构.step',part_count:1},
    {...base,id:'doc_foreign',project_id:'other',filename:'外厂.dwg'},
    {...base,id:'doc_old',filename:'历史.dwg',superseded:true},
  ];
  assert.equal(c.documentConfirmationDocuments('render').map(d=>d.id).join(','),'doc_render');
  assert.equal(c.documentConfirmationDocuments('construction').map(d=>d.id).join(','),'doc_dwg,doc_pdf,doc_image');
  assert.equal(c.documentConfirmationDocuments('engineering').map(d=>d.id).join(','),'doc_dwg,doc_pdf,doc_asm,doc_step');
  assert.equal(c.documentConfirmationReadyDoc('engineering',c.state.documents[4]),false);
  assert.equal(c.documentConfirmationReadyDoc('engineering',c.state.documents[5]),false);
  c.state.parts=[{id:'part_step',project_id:'p1',document_id:'doc_step',review_status:'pending',archived:false}];
  assert.equal(c.documentConfirmationReadyDoc('engineering',c.state.documents[5]),false);
  assert.match(c.documentConfirmationEngineeringHint([c.state.documents[5]]),/先审核本文件的 1 项构件/);
  c.state.parts[0].review_status='approved';
  assert.equal(c.documentConfirmationReadyDoc('engineering',c.state.documents[5]),true);
  c.state.parts[0].draft_only=true;
  assert.equal(c.documentConfirmationReadyDoc('engineering',c.state.documents[5]),false);
  c.state.parts[0].draft_only=false;c.state.parts[0].archived=true;
  assert.equal(c.documentConfirmationReadyDoc('engineering',c.state.documents[5]),false);
  p.document_confirmations={render:{document_id:'doc_render',document_sha256:'a'.repeat(64)},construction:{document_id:'doc_dwg',document_sha256:'a'.repeat(64)}};
  assert.equal(c.documentConfirmationReadyDoc('engineering',c.state.documents[1]),false);
});
test('resolved engineering source needs current approved part lineage, not a saved count alone',()=>{
  const c=boot(),p=c.currentProject();p.evidence_policy='staged';
  const source={id:'doc_companion',project_id:'p1',purpose:'drawing',filename:'构件清单.pdf',sha256:'b'.repeat(64)};
  const drawing={id:'doc_engineering',project_id:'p1',purpose:'drawing',filename:'装配.sldasm',sha256:'a'.repeat(64),
    resolved:true,part_count:9,resolution_evidence:{document_id:'doc_engineering',document_sha256:'a'.repeat(64),project_id:'p1',
      parts:[{part_id:'part_1',source_document_id:'doc_companion',source_sha256:'b'.repeat(64)}]}};
  c.state.documents=[source,drawing];
  c.state.parts=[{id:'part_1',project_id:'p1',document_id:'doc_companion',review_status:'approved',archived:false,draft_only:false}];
  assert.equal(c.documentConfirmationReadyDoc('engineering',drawing),true);
  c.state.parts[0].review_status='pending';
  assert.equal(c.documentConfirmationReadyDoc('engineering',drawing),false);
  c.state.parts[0].review_status='approved';
  source.sha256='c'.repeat(64);
  assert.equal(c.documentConfirmationReadyDoc('engineering',drawing),false);
});
test('confirmation dialog asks for one current file and customer evidence, with optimistic version',()=>{
  const c=boot(),p=c.currentProject();p.evidence_policy='staged';p.document_confirmation_version=3;
  c.state.documents=[
    {id:'doc_r',project_id:'p1',purpose:'render',filename:'效果.jpg',sha256:'a'.repeat(64)},
    {id:'doc_c',project_id:'p1',purpose:'drawing',filename:'施工图.dwg',sha256:'b'.repeat(64)},
    {id:'doc_bad',project_id:'p1',purpose:'drawing',filename:'总装.sldasm',sha256:'c'.repeat(64)},
  ];
  p.document_confirmations={render:{document_id:'doc_r',document_sha256:'a'.repeat(64),note:'微信确认'}};
  c.openModal=(title,body,footer)=>{c.modal={title,body,footer};};
  c.toast=message=>{c.lastToast=message;};
  c.documentConfirmationModal('construction');
  assert.equal(c.modal.title,'施工图确认');
  assert.match(c.modal.body,/data-confirmation-version="3"/);
  assert.match(c.modal.body,/<select id="document-confirmation-file" name="document_id" required>/);
  assert.match(c.modal.body,/value="doc_c"/);
  assert.doesNotMatch(c.modal.body,/value="doc_bad"|value="doc_r"/);
  assert.match(c.modal.body,/name="note" maxlength="500" required/);
  assert.match(c.modal.footer,/type="submit" form="document-confirmation-form"/);
  c.documentConfirmationModal('engineering');
  assert.match(c.lastToast,/请先记录上一阶段/);
  p.document_confirmations.construction={document_id:'doc_c',document_sha256:'b'.repeat(64)};
  c.documentConfirmationModal('engineering');
  assert.match(c.modal.body,/先将工程图关联到当前构件或配套清单/);
  c.state.documents[2].part_count=2;
  c.documentConfirmationModal('engineering');
  assert.match(c.modal.body,/先将工程图关联到当前构件或配套清单/);
  c.state.parts=[{id:'part_bad',project_id:'p1',document_id:'doc_bad',review_status:'pending',archived:false}];
  c.documentConfirmationModal('engineering');
  assert.match(c.modal.body,/先审核本文件的 1 项构件/);
  c.state.parts[0].review_status='approved';
  c.documentConfirmationModal('engineering');
  assert.match(c.modal.body,/value="doc_bad"/);
  assert.doesNotMatch(c.modal.body,/value="doc_c"/);
});
test('confirmation submission sends pinned hash and version and rejects a stale choice',async()=>{
  const c=boot(),p=c.currentProject(),calls=[];
  p.evidence_policy='staged';
  c.state.documents=[{id:'doc_r',project_id:'p1',purpose:'render',filename:'效果.jpg',sha256:'a'.repeat(64)}];
  const error={textContent:''};c.$=()=>error;
  c.submitOperation=(_button,operation)=>operation();
  c.api=(url,payload)=>{calls.push({url,payload});return Promise.resolve({});};
  const form={dataset:{projectId:'p1',stage:'render',confirmationVersion:'4'},reportValidity:()=>true,elements:{
    document_id:{value:'doc_r',focus(){}},note:{value:' 客户微信确认 9月28日 ',focus(){}}
  }};
  await c.saveDocumentConfirmation(form,{disabled:false});
  assert.equal(calls.length,1);
  assert.equal(calls[0].url,'/api/projects/p1/document-confirmations');
  assert.equal(calls[0].payload.document_sha256,'a'.repeat(64));
  assert.equal(calls[0].payload.expected_confirmation_version,4);
  assert.equal(calls[0].payload.note,'客户微信确认 9月28日');
  c.state.documents[0].superseded=true;
  await c.saveDocumentConfirmation(form,{disabled:false});
  assert.equal(calls.length,1);
  assert.match(error.textContent,/文件已变化/);
});
