'use strict';

// A read-only front door. Production approval, material and assignment checks
// remain server operations; these summaries are navigation, never authorization.
const factoryHomeStages = ['接单建档', '看图拆单', '备料排产', '车间执行', '验收发货'];
let factoryHomeSnapshot = null, factoryHomeScope = '', factoryHomeProduction = null;
let factoryHomeReadState = 'idle', factoryHomeReadError = '', factoryHomeReadToken = 0;
const factoryHomeDisclosures = {priorities:false, demos:false};
let factoryHomeFilter = 'all', factoryHomeFilterScope = '';
const factoryHomeFilters = {all:'全部在做订单', due:'交期待核对', review:'等拆单确认', blocked:'现场有卡点', delivery:'待验收发货'};

function factoryHomeRows(value) { return Array.isArray(value) ? value : []; }
function factoryHomeClosed(project) {
  return Boolean(project?.archived || project?.is_closed || ['completed', 'shipped'].includes(project?.fulfillment_status));
}
function factoryHomeHref(pageName, project, extra = {}) {
  const params = new URLSearchParams({page:pageName, tab:'parts'});
  if (project?.id) params.set('project', project.id);
  for (const [key, value] of Object.entries(extra)) if (value !== undefined) params.set(key, String(value));
  return '#' + params.toString();
}
function factoryHomeProductionHref(tabName, project) {
  return factoryHomeHref('readiness', project, {opTab:tabName, opProject:project?.id || ''});
}
function factoryProjectSummary(project, snapshot, production = null, profile = null) {
  const workflowContext = projectWorkflowContext(project, profile);
  const rows = key => factoryHomeRows(snapshot?.[key]).filter(row => row.project_id === project.id && !row.archived);
  const documents = rows('documents').filter(row => row.purpose !== 'render' && row.purpose !== 'reference');
  const parts = rows('parts');
  const taskRows = rows('tasks');
  const tasks = taskRows.filter(row => row.status !== 'invalidated' && row.revision === project.revision);
  const pendingParts = parts.filter(row => row.review_status !== 'approved');
  const unresolved = documents.filter(row => !row.superseded && (row.purpose === 'process' ? !processBasisIsCurrent(row) : !row.resolved &&
    (['needs_conversion', 'error'].includes(row.status) || !Number(row.part_count))));
  const stale = taskRows.filter(row => row.status === 'invalidated' || row.revision !== project.revision);
  const published = project.status === 'released' && project.released_revision === project.revision;
  const remaining = tasks.filter(row => row.status !== 'done');
  const paused = remaining.filter(row => row.status === 'blocked');
  const running = remaining.filter(row => row.status === 'in_progress');
  const unassigned = remaining.filter(row => !row.assignee && !row.assignee_id);
  const done = tasks.filter(row => row.status === 'done');
  const productionAvailable = Boolean(production && factoryHomeRows(production.projects).some(row => row.id === project.id));
  const productionRows = key => productionAvailable ? factoryHomeRows(production[key]).filter(row => row.project_id === project.id && !row.archived) : [];
  const materials = productionRows('materials');
  const shortages = materials.filter(row => Number(row.shortage_quantity ?? Math.max(0, Number(row.required_quantity) - Number(row.accepted_quantity))) > 0);
  const issues = productionRows('issues').filter(row => row.status !== 'resolved');
  const remainingIds = new Set(remaining.map(row => row.id));
  const blockedChecks = productionRows('checks').filter(row => remainingIds.has(row.task_id) && row.revision === project.revision && factoryHomeRows(row.items).some(item => item.status !== 'ready'));
  const closed = factoryHomeClosed(project);
  const deliveryPending = !project.archived && project.fulfillment_status === 'completed';
  let stage = 0, label = '准备资料', reason = workflowContext.industryId ? '上传本行业工艺资料与订单表' : '上传施工图、料单或 BOM', href = factoryHomeHref('drawing', project), urgency = 0;
  const hasScope = documents.length > 0 || parts.length > 0 || Boolean(project.workflow_id);
  if (hasScope) {
    stage = 1; label = '核对拆单';
    reason = pendingParts.length ? `${pendingParts.length} 项构件待复核` : unresolved.length ? `${unresolved.length} 份工程资料待核验` : stale.length ? `${stale.length} 道工序需要按当前版本核对` : tasks.length ? `工程 R${project.revision || 1} 尚未发布` : '确认工作对象和工艺，生成工序';
  }
  if (hasScope && !published && workflowContext.useWorkflow) {
    label = project.workflow_id ? '核对工作包' : '按本厂流程拆解';
    href = factoryHomeHref('templates', project);
    reason = stale.length ? `${stale.length} 道工序需要按当前工作包版本核对` : unresolved.length ? `${unresolved.length} 份工艺资料待核验` : '核对工作对象、资料版本和工序要求';
  }
  if (!published && workflowContext.needsConfiguration) {
    stage = 1; label = '查看本厂流程'; reason = '已选择行业，请管理员先在中台核对并启用本厂流程';
    href = factoryHomeHref('templates', project);
  }
  if (published) {
    stage = 2; label = '检查齐套'; reason = productionAvailable ? (materials.length ? '核对物料、前置工序与排程' : '核对物料需求与开工条件') : '核对物料和排程后派工';
    href = factoryHomeProductionHref('materials', project);
    if (shortages.length) { reason = `${shortages.length} 项物料有缺口`; urgency = 2; }
    else if (blockedChecks.length) { label = '核对开工条件'; reason = `${blockedChecks.length} 道工序的检查尚未满足`; href = factoryHomeProductionHref('checks', project); }
    else if (unassigned.length) { label = '安排负责人'; reason = `${unassigned.length} 道工序未分配`; href = factoryHomeHref('tasks', project); }
    else if (remaining.length) { label = '查看排程'; reason = `${remaining.length} 道工序待安排或执行`; href = factoryHomeHref('planning', project, {referenceMode:'execution'}); }
    if (running.length || done.length) { stage = 3; label = '查看任务'; reason = `${running.length} 道进行中 · ${done.length} / ${tasks.length} 道完工`; href = factoryHomeHref('tasks', project); }
    if (tasks.length && done.length === tasks.length) { stage = 4; label = '核对验收'; reason = '工序已报完工，核对质量验收与发货条件'; href = factoryHomeProductionHref('inspections', project); }
    if (paused.length) { stage = 3; label = '处理暂停'; reason = `${paused.length} 道暂停 · ${paused[0].pause_note || paused[0].title || paused[0].name || '待安排恢复'}`; href = factoryHomeHref('tasks', project, {task:paused[0].id}); urgency = 3; }
  }
  // Keep known blockers visible even after another operation has started.
  if (published && !paused.length && remaining.length) {
    if (issues.length) { label = '处理异常'; reason = `${issues.length} 项异常待处理`; href = factoryHomeProductionHref('issues', project); urgency = 3; }
    else if (shortages.length) { label = '处理缺料'; reason = `${shortages.length} 项物料有缺口`; href = factoryHomeProductionHref('materials', project); urgency = 2; }
    else if (blockedChecks.length) { label = '核对开工条件'; reason = `${blockedChecks.length} 道工序的检查尚未满足`; href = factoryHomeProductionHref('checks', project); }
  }
  if (closed) {
    stage = -1; urgency = 0; label = '查看项目记录';
    reason = project.fulfillment_status === 'shipped' ? '已发货' : '已完成';
    href = factoryHomeHref('drawing', project);
  }
  if (deliveryPending) {
    stage = 4; label = '安排发货'; reason = '已完成，待确认交付与整单发货'; href = factoryHomeProductionHref('deliveries', project);
  }
  const stageNotes = [
    documents.length ? `${documents.length} 份工程资料` : parts.length ? '已录入构件，核对依据' : project.workflow_id ? '已登记工作范围' : '待准备工程资料',
    published ? `已发布 R${project.revision || 1}` : workflowContext.needsConfiguration ? '本厂流程待启用' : workflowContext.useWorkflow ? tasks.length ? `${tasks.length} 道工序待核对` : '待确认工作包' : pendingParts.length ? `${pendingParts.length} 项待复核` : tasks.length ? `${tasks.length} 道工序待核对` : '待确认工序',
    shortages.length ? `${shortages.length} 项缺料` : blockedChecks.length ? `${blockedChecks.length} 道待检查` : '查看物料与排程',
    paused.length ? `${paused.length} 道暂停` : running.length ? `${running.length} 道进行中` : done.length ? `${done.length} / ${tasks.length} 道完工` : unassigned.length ? `${unassigned.length} 道待分配` : '查看任务与交接',
    tasks.length && done.length === tasks.length ? '工序已完工，待验收交付' : '完工后验收并记录发货'
  ];
  return {project, documents, parts, tasks, pendingParts, unresolved, stale, published, remaining, paused, running, unassigned, done, productionAvailable, shortages, issues, blockedChecks, closed, deliveryPending, stage, label, reason, href, urgency, stageNotes};
}
// Earliest contractual due date first; unknown due dates stay unknown. This
// queue is an explainable triage order, not a computed production schedule.
function factoryHomeDue(project, today) {
  const parse = value => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return null;
    const n = Date.parse(value + 'T00:00:00Z');
    return Number.isFinite(n) && new Date(n).toISOString().slice(0,10) === value ? n : null;
  };
  const due = parse(project.due_date), now = parse(today);
  if (due === null || now === null) return {known:false,days:null,rank:4};
  const days = Math.round((due-now)/86400000);
  return {known:true,days,rank:days<0?0:days===0?1:days<=3?2:3};
}
function factoryHomeHasBlock(summary) { return !summary.closed && Boolean(summary.paused.length || summary.shortages.length || summary.issues.length || summary.blockedChecks.length); }
function factoryHomeCompare(a, b, today) {
  const ad=factoryHomeDue(a.project,today), bd=factoryHomeDue(b.project,today);
  return ad.rank-bd.rank || (ad.known&&bd.known?ad.days-bd.days:0) || Number(factoryHomeHasBlock(b))-Number(factoryHomeHasBlock(a)) || String(a.project.id).localeCompare(String(b.project.id));
}
function factoryHomePriorities(summaries, today) {
  const items = [];
  for (const summary of summaries.filter(row => (!row.closed || row.deliveryPending) && !row.project.demo && !row.project.demo_dataset)) {
    const p = summary.project, due = factoryHomeDue(p,today);
    const pause=summary.paused[0], issue=summary.issues[0], material=summary.shortages[0];
    let item;
    if(due.known&&due.days<=0) item={id:'due:'+p.id,label:due.days<0?'交期已过':'今天到交期',title:p.name,detail:`交期 ${p.due_date} · ${summary.reason}`,href:summary.href,action:summary.label};
    else if(summary.deliveryPending) item={id:'delivery:'+p.id,label:'已完成待发货',title:p.name,detail:summary.reason,href:summary.href,action:summary.label};
    else if(pause) item={id:'pause:'+pause.id,label:'暂停待处理',title:p.name,detail:`${pause.title||pause.name||'生产任务'} · ${pause.pause_note||pause.handover_note||'查看暂停原因与交接'}`,href:factoryHomeHref('tasks',p,{task:pause.id}),action:'处理暂停'};
    else if(issue) item={id:'issue:'+issue.id,label:'异常待处理',title:p.name,detail:issue.title||'明确负责人和处理时间',href:factoryHomeProductionHref('issues',p),action:'处理异常'};
    else if(material) item={id:'material:'+material.id,label:'物料有缺口',title:p.name,detail:`${material.name||'生产物料'} · ${material.expected_date?'预计到货 '+material.expected_date:'待确认到货时间'}`,href:factoryHomeProductionHref('materials',p),action:'处理缺料'};
    else if(summary.blockedChecks.length) item={id:'check:'+p.id,label:'开工条件未齐',title:p.name,detail:summary.reason,href:factoryHomeProductionHref('checks',p),action:'核对开工条件'};
    if(item)items.push({...item,project:p,summary,rank:due.rank,action:item.action || summary.label});
  }
  return items.sort((a,b)=>factoryHomeCompare(a.summary,b.summary,today)||a.id.localeCompare(b.id));
}
function factoryHomeMatches(summary, filter, today) {
  if(filter==='due'){const due=factoryHomeDue(summary.project,today);return due.known&&due.days<=0;}
  if(filter==='review')return summary.stage===0||summary.stage===1;
  if(filter==='blocked')return factoryHomeHasBlock(summary);
  if(filter==='delivery')return summary.stage===4;
  return true;
}
function factoryHomeDate() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}
function factoryHomeCurrentProduction() {
  return factoryHomeSnapshot === state && factoryHomeScope === workspaceType ? factoryHomeProduction : null;
}
function factoryHomeProfileFor(project) {
  return projectWorkflowContext(project).profile;
}
function factoryProjectMainline(project) {
  if (!project) return '';
  const profile = factoryHomeProfileFor(project);
  const summary = factoryProjectSummary(project, state, factoryHomeCurrentProduction(), profile);
  if (summary.closed) return '';
  if (typeof dailyWorkflowRail==='function') return dailyWorkflowRail('import',project);
  const links = [factoryHomeHref('projects', project), projectWorkflowContext(project, profile).useWorkflow ? factoryHomeHref('templates', project) : factoryHomeHref('drawing', project), factoryHomeHref('planning', project, {referenceMode:'execution'}), factoryHomeHref('tasks', project), factoryHomeProductionHref('inspections', project)];
  return `<nav class="factory-mainline" aria-label="项目工作步骤"><ol>${factoryHomeStages.map((label, index) => `<li><a href="${esc(links[index])}" ${summary.stage === index ? 'aria-current="step"' : ''}><span class="factory-mainline-number">${index + 1}</span><span><strong>${label}</strong><small>${esc(summary.stageNotes[index])}</small></span>${summary.stage === index ? '<span class="factory-mainline-current">当前</span>' : ''}</a></li>`).join('')}</ol></nav>`;
}
function factoryHomeProjectRow(summary) {
  const p = summary.project;
  const historical = typeof historicalDemoIsComplete === 'function' && historicalDemoIsComplete(p);
  return `<article class="factory-project-row"><div class="factory-project-name"><a href="${esc(factoryHomeHref('drawing', p))}">${esc(p.name || '未命名项目')}</a><p>${p.client && p.client !== p.name ? esc(p.client) : ''}${historical ? '' : '<span>交付 '+esc(p.due_date || '未设置')+'</span>'}${historical ? '<span class="badge green">历史已完成 · 演示复盘</span>' : p.demo_dataset ? '<span class="badge amber">历史资料演示</span>' : p.demo ? '<span class="badge amber">演示</span>' : ''}</p></div><div class="factory-project-next"><span class="factory-stage-label">${esc(factoryHomeStages[summary.stage] || summary.reason)}</span><p>${esc(summary.reason)}</p></div><a class="btn factory-project-action" href="${esc(summary.href)}">${esc(summary.label)}${icon('arrow')}</a></article>`;
}
function factoryHomePriorityRows(items) {
  return items.map(item => `<li><a href="${esc(item.href)}"><span class="factory-priority-label">${esc(item.label)}</span><span class="factory-priority-content"><strong>${esc(item.title)}</strong><small>${esc(item.title === item.project.name ? item.detail : item.project.name + ' · ' + item.detail)}</small></span><span class="factory-priority-go">${esc(item.action || '去处理')} ${icon('arrow')}</span></a></li>`).join('');
}
function factoryHomeView() {
  const all = (typeof workspaceProjects === 'function' ? workspaceProjects() : factoryHomeRows(state?.projects)).filter(project => !project.archived);
  const production = factoryHomeCurrentProduction(), today=factoryHomeDate();
  const summaries = all.map(project => factoryProjectSummary(project, state, production, factoryHomeProfileFor(project)));
  const active = summaries.filter(row => (!row.closed || row.deliveryPending) && !row.project.demo && !row.project.demo_dataset).sort((a,b)=>factoryHomeCompare(a,b,today));
  // Imported historical cases remain browseable after completion or shipment,
  // but never appear as current production, overdue work or archive totals.
  const demos = summaries.filter(row => row.project.demo_dataset || (row.project.demo && (!row.closed || row.deliveryPending)));
  const closedCount = summaries.filter(row => row.closed && !row.deliveryPending && !row.project.demo && !row.project.demo_dataset).length;
  const priorities = factoryHomePriorities(summaries, today);
  const context = globalThis.kanpaceInstanceContext;
  const pendingIndustry = context?.instance?.industry_id && context?.profile?.status !== 'installed';
  const industryName = context?.profile?.industry_name || context?.instance?.industry_name || '';
  const factoryName = context?.instance?.name || (typeof workspaceProfile === 'function' ? workspaceProfile().name : '工厂');
  const viewScope=(context?.instance?.id||'local')+':'+workspaceType;
  if(factoryHomeFilterScope!==viewScope){factoryHomeFilter='all';factoryHomeFilterScope=viewScope;}
  const snapshotMatches = factoryHomeSnapshot === state && factoryHomeScope === workspaceType;
  const loading = !snapshotMatches || factoryHomeReadState === 'loading' || factoryHomeReadState === 'idle';
  const failed = snapshotMatches && factoryHomeReadState === 'error';
  const status = failed ? `<div class="factory-read-status is-error" role="alert"><span>物料与异常暂时未读到，请重新核对。</span><button type="button" class="btn" data-factory-home-retry>重新读取</button></div>` : loading && active.length ? '<p class="factory-read-status" role="status">正在核对物料与异常…</p>' : '';
  const filtered=active.filter(row=>factoryHomeMatches(row,factoryHomeFilter,today));
  const metrics=['due','review','blocked','delivery'].map(key=>({key,label:factoryHomeFilters[key],count:active.filter(row=>factoryHomeMatches(row,key,today)).length}));
  return `<div class="factory-home"><header class="page-head"><div><p class="factory-context">${esc(factoryName)} · ${esc(today)}</p><h1>总看板</h1></div><div class="head-actions"><a class="btn" href="${esc(factoryHomeHref('planning',null,{referenceMode:'execution'}))}">${icon('clock')}查看排程</a>${button(active.length?'新建订单':'新建第一张订单','new-project','plus',active.length?'':'primary')}</div></header>
    <section class="factory-today-counts" aria-label="按待办筛选订单">${metrics.map(metric=>`<button type="button" data-factory-home-filter="${metric.key}" aria-pressed="${factoryHomeFilter===metric.key}"><strong>${metric.key==='blocked'&&(loading||failed)?'—':metric.count}</strong><span>${metric.label}</span>${icon('arrow')}</button>`).join('')}</section>
    <div class="factory-home-tools"><button type="button" data-action="agent-open" data-agent-project="" data-agent-prompt="今天先做什么">${icon('search')}AI 工作助手<span class="factory-assistant-example">查拆单缺项 · 比较排程 · 找现场卡点</span>${icon('arrow')}</button><a href="${esc(factoryHomeHref('exchange'))}">导入 Excel</a></div>${status}
    ${priorities.length&&factoryHomeFilter==='all'?`<section class="factory-priorities" aria-labelledby="factory-priority-title"><div class="factory-section-head"><h2 id="factory-priority-title">先推进这 ${Math.min(2,priorities.length)} 单</h2><span>按交期与当前卡点排序</span></div><ol>${factoryHomePriorityRows(priorities.slice(0,2))}</ol></section>`:''}
    <section class="factory-projects" aria-labelledby="factory-projects-title"><div class="factory-section-head"><h2 id="factory-projects-title">${factoryHomeFilter==='all'?'订单推进':esc(factoryHomeFilters[factoryHomeFilter])}<span>${filtered.length} 单</span></h2><div class="factory-list-actions">${factoryHomeFilter!=='all'?'<button class="link-button" type="button" data-factory-home-filter="all">显示全部</button>':''}<a href="${esc(factoryHomeHref('projects'))}">订单档案 ${icon('arrow')}</a></div></div>
    ${filtered.length?`<div class="factory-list-columns" aria-hidden="true"><span>订单 / 交期</span><span>当前步骤 / 卡在哪里</span><span>下一步</span></div>`+filtered.map(factoryHomeProjectRow).join(''):active.length?'<div class="factory-home-empty"><h3>这类待办暂无订单</h3><button class="btn" type="button" data-factory-home-filter="all">查看全部在做订单</button></div>':`<div class="factory-home-empty"><h3>${pendingIndustry?'先启用本厂行业流程':'先准备一张真实订单'}</h3><p>${pendingIndustry?'已选择'+esc(industryName||'行业')+'，请管理员在中台核对并启用本厂流程。':industryName?'上传订单表与本行业工艺资料，按已启用流程创建工作包。':'从订单表、客户确认的效果图和施工图开始。'}</p>${pendingIndustry?'<a class="btn" href="/control/index.html">查看配置中台'+icon('arrow')+'</a>':button('新建第一张订单','new-project','plus','primary')}</div>`}</section>
    ${demos.length?`<details class="factory-demo-projects" data-factory-home-disclosure="demos" ${factoryHomeDisclosures.demos?'open':''}><summary>查看演示项目 · ${demos.length} 个</summary>${demos.map(factoryHomeProjectRow).join('')}</details>`:''}
    ${closedCount?`<p class="factory-archive-link"><a href="${esc(factoryHomeHref('projects',null,{projectStatus:'all'}))}">${closedCount} 个已完成 / 已发货项目，查看记录 ${icon('arrow')}</a></p>`:''}</div>`;
}
async function factoryHomeAfterRender(force = false) {
  if (!['overview', 'projects', 'drawing', 'tasks', 'quote'].includes(page) || !state) return;
  const snapshot = state, scope = workspaceType;
  if (!force && factoryHomeSnapshot === snapshot && factoryHomeScope === scope) return;
  const token = ++factoryHomeReadToken;
  factoryHomeSnapshot = snapshot; factoryHomeScope = scope; factoryHomeProduction = null;
  factoryHomeReadState = 'loading'; factoryHomeReadError = '';
  try {
    const data = await api('/api/production?' + new URLSearchParams({factory_type:scope, include_demo:'0'}));
    if (token !== factoryHomeReadToken || state !== snapshot || workspaceType !== scope) return;
    factoryHomeProduction = data; factoryHomeReadState = 'ready';
  } catch (error) {
    if (token !== factoryHomeReadToken || state !== snapshot || workspaceType !== scope) return;
    factoryHomeReadState = 'error'; factoryHomeReadError = error.message;
  } finally {
    if (token === factoryHomeReadToken && state === snapshot && workspaceType === scope && ['overview', 'projects', 'drawing', 'tasks', 'quote'].includes(page)) render();
  }
}
document.addEventListener('toggle', event => {
  const key = event.target?.dataset?.factoryHomeDisclosure;
  if (Object.hasOwn(factoryHomeDisclosures, key)) factoryHomeDisclosures[key] = event.target.open;
}, true);
document.addEventListener('click', event => {
  const filter=event.target.closest('[data-factory-home-filter]');
  if(filter && Object.hasOwn(factoryHomeFilters,filter.dataset.factoryHomeFilter)){
    factoryHomeFilter=filter.dataset.factoryHomeFilter;render();
    document.querySelector(`[data-factory-home-filter="${factoryHomeFilter}"]`)?.focus({preventScroll:true});return;
  }
  const retry = event.target.closest('[data-factory-home-retry]');
  if (!retry || retry.disabled) return;
  retry.disabled = true; retry.textContent = '正在读取…';
  factoryHomeAfterRender(true);
});
globalThis.KanpaceFactoryHome = {summarize:factoryProjectSummary, priorities:factoryHomePriorities, view:factoryHomeView, mainline:factoryProjectMainline, afterRender:factoryHomeAfterRender};
