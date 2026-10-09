/* Shared two-level navigation. Existing business views keep their own behavior. */
'use strict';
const kanpaceNavigation = window.KANPACE_MENU;
const kanpacePageNames = {workflow:'订单工作流',overview:'总看板',daily:'每日工作',projects:'项目订单',drawing:'图纸拆单',quote:'成本报价',planning:'生产排程表',tasks:'生产任务',readiness:'生产协同',scheduling:'产能与插单',owner:'老板工作台',device:'工牌与派发',manage:'设置总览',people:'人员与班组',templates:'流程模板',exchange:'Excel 导入导出',access:'账号权限',calibration:'工时参考',settings:'人工与材料单价'};
const kanpaceProductionTabs = new Set(['materials','issues','checks','inspections','costs','commercial','deliveries']);
const kanpaceResourceTabs = new Set(['people','teams','workcenters','factories']);
let kanpaceMenuState = {},kanpaceMobileMenuOpen=false,kanpaceLastGroup='',kanpaceLastRoute='',kanpaceLastSection='',kanpaceNavScroll=0,kanpaceLastActive='',kanpacePendingSection='',kanpaceFocusAfterNavigation=false,kanpaceLastMenuEntry='';
try {kanpaceMenuState=JSON.parse(sessionStorage.getItem('kanpace-navigation-groups-v3')||'{}');if(!kanpaceMenuState||typeof kanpaceMenuState!=='object'||Array.isArray(kanpaceMenuState))kanpaceMenuState={};} catch {kanpaceMenuState={};}
const kanpaceNavEscape = value => String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function kanpaceNavIcon(name){if(typeof icon==='function')return icon(name);return '<span class="nav-plain-icon" aria-hidden="true">'+({home:'⌂',folder:'▱',tasks:'☷',money:'¥',bolt:'↗',settings:'⚙',grid:'▦',search:'⌕',down:'⌄'}[name]||'›')+'</span>';}
function kanpaceFinancialAllowed(){return typeof accessState==='undefined'||!accessState?.enabled||!!accessState.financial_access;}
function kanpaceNavProject(){if(typeof workspaceProjects!=='function'||typeof projectId==='undefined')return '';return workspaceProjects().find(p=>p.id===projectId)?.id||'';}
function kanpacePageHref(target,project=typeof projectId==='undefined'?'':projectId){return window.kanpaceMenuHref({page:target,tab:target==='quote'?'quote':'parts'},{projectId:project});}
function kanpaceActiveMenuItem(){
  if(typeof page==='undefined')return 'bi';
  const h=new URLSearchParams(location.hash.slice(1));
  if(page==='daily'){const step=h.get('step');return step==='planning'?'planning':'daily-'+(['import','dispatch','execution','labels','return'].includes(step)?step:'import');}
  if(page==='people'&&typeof operationsResourceTab!=='undefined'&&operationsResourceTab==='workcenters')return 'workcenters';
  if(page==='readiness')return typeof operationsProductionTab==='undefined'||operationsProductionTab==='checks'?'materials':operationsProductionTab;
  if(page==='device')return 'device';
  if(page==='scheduling')return 'planning';
  if(page==='drawing'&&tab==='history')return 'history';
  if(page==='drawing'&&tab==='quote')return 'quote';
  if(page==='drawing'&&tab==='tasks'){
    const project=typeof currentProject==='function'?currentProject():null;
    return project?.status==='released'&&project.released_revision===project.revision?'tasks':'draft-tasks';
  }
  return page;
}
function kanpaceModule(){const active=kanpaceActiveMenuItem();return kanpaceNavigation.find(group=>group.items.some(item=>item.id===active))||kanpaceNavigation[0];}
function kanpaceRememberMenu(){try{sessionStorage.setItem('kanpace-navigation-groups-v3',JSON.stringify(kanpaceMenuState));}catch{}}
function kanpaceGroupOpen(group){return kanpaceMenuState[group.id]===true;}
function kanpaceConfiguredMenuItem(item){
  const profile=window.kanpaceInstanceContext?.profile;if(!profile)return true;
  if(['factory-setup','factory-onboarding','manage','access','settings'].includes(item.id))return true;
  const map={model:'drawing',history:'drawing','draft-tasks':'drawing',materials:'readiness','badge-media':'device',workcenters:'people',bi:'owner'};
  return (profile.enabled_modules||[]).includes(item.module||map[item.id]||item.id);
}
function kanpaceMenuMarkup({active=kanpaceActiveMenuItem(),project=kanpaceNavProject(),prefix='',financial=kanpaceFinancialAllowed()}={}){
  const module=kanpaceNavigation.find(group=>group.items.some(item=>item.id===active))||kanpaceNavigation[0];
  // A newly selected function opens its own stage; avoid restoring every old menu open.
  if(active!==kanpaceLastMenuEntry){for(const group of kanpaceNavigation)kanpaceMenuState[group.id]=group.id===module.id&&active!==group.primary;kanpaceLastMenuEntry=active;kanpaceRememberMenu();}
  const activeItem=module.items.find(item=>item.id===active&&(!item.financial||financial)&&kanpaceConfiguredMenuItem(item)),narrow=typeof matchMedia==='function'&&matchMedia('(max-width: 680px)').matches;
  const href=item=>kanpaceNavEscape(window.kanpaceMenuHref(item,{projectId:project,prefix}));
  const groups=kanpaceNavigation.map(group=>{
    const children=group.items.filter(item=>(!item.financial||financial)&&kanpaceConfiguredMenuItem(item));if(!children.length)return '';
    if(group.direct){const item=children[0];return `<a class="nav-today ${active===item.id?'active':''}" data-nav-group="${group.id}" data-nav-item="${item.id}" href="${href(item)}" ${active===item.id?'aria-current="page"':''}>${kanpaceNavIcon(group.icon)}<span>${kanpaceNavEscape(group.label)}</span></a>`;}
    const primary=children.find(item=>item.id===group.primary)||children.find(item=>item.id===group.fallback)||children[0],secondary=children.filter(item=>item.id!==primary.id),open=kanpaceGroupOpen(group),current=group.id===module.id;
    // Link and native disclosure are separate controls: one click opens work, one expands choices.
    return `<section class="nav-stage ${current?'is-current-group':''} ${group.secondary?'nav-secondary':''}"><a class="nav-stage-main" data-nav-primary="${primary.id}" data-nav-item="${primary.id}" ${primary.id==='factory-setup'?'data-select-factory="true"':''} href="${href(primary)}" aria-label="${kanpaceNavEscape(group.label+' · '+primary.label)}" ${active===primary.id?'aria-current="page"':''}>${Number.isInteger(group.step)?`<span class="nav-step" aria-hidden="true">${String(group.step).padStart(2,'0')}</span>`:kanpaceNavIcon(group.icon)}<span>${kanpaceNavEscape(group.label)}</span></a>${secondary.length?`<details class="nav-group" data-nav-group="${group.id}" ${open?'open':''}><summary aria-label="${kanpaceNavEscape(group.label)}的更多功能" title="展开或收起${kanpaceNavEscape(group.label)}">${kanpaceNavIcon('down')}</summary><div class="nav-children">${secondary.map(item=>`<a class="nav-child ${active===item.id?'active':''}" data-nav-item="${item.id}" ${item.id==='factory-setup'?'data-select-factory="true"':''} ${item.financial?'data-financial="true"':''} href="${href(item)}" ${active===item.id?'aria-current="page"':''}>${kanpaceNavEscape(item.label)}</a>`).join('')}</div></details>`:''}</section>`;
  }).join('');
  return `<details class="nav-menu-disclosure" ${!narrow||kanpaceMobileMenuOpen?'open':''}><summary>${kanpaceNavIcon('grid')}<strong>工作菜单</strong><span class="nav-current-label">${kanpaceNavEscape(activeItem?.label||module.label)}</span><span class="nav-mobile-state"><span class="when-closed">展开</span><span class="when-open">收起</span></span>${kanpaceNavIcon('down')}</summary><nav class="kanpace-menu-body" aria-label="功能菜单">${groups}</nav></details>`;
}
function kanpaceSubnavigation(){return '';}
const kanpaceWorkflowNotes = ['选择展柜、机械或现场','管理订单与资料','核对构件、物料与计划','安排任务与负责人','处理异常、检验与交付','查看进度与经营'];
function kanpaceWorkflowEntry({project=kanpaceNavProject(),financial=kanpaceFinancialAllowed()}={}){
  const stages=kanpaceNavigation.filter(group=>Number.isInteger(group.step)).sort((a,b)=>a.step-b.step);
  return `<section class="kanpace-workflow-entry" aria-labelledby="kanpace-workflow-title"><div class="kanpace-workflow-heading"><p>工厂工作 0—5</p><h2 id="kanpace-workflow-title">从这里开始</h2></div><ol>${stages.map(group=>{
    const choices=group.items.filter(item=>(!item.financial||financial)&&kanpaceConfiguredMenuItem(item));
    const primary=choices.find(item=>item.id===group.primary)||choices.find(item=>item.id===group.fallback)||choices[0];
    if(!primary)return '';
    const href=kanpaceNavEscape(window.kanpaceMenuHref(primary,{projectId:project}));
    return `<li><a href="${href}" data-workflow-stage="${group.step}" ${primary.id==='factory-setup'?'data-select-factory="true"':''}><span class="kanpace-workflow-number" aria-hidden="true">${group.step}</span><span class="kanpace-workflow-copy"><strong>${kanpaceNavEscape(group.label)}</strong><small>${kanpaceNavEscape(kanpaceWorkflowNotes[group.step])}</small></span>${kanpaceNavIcon('arrow')}</a></li>`;
  }).join('')}</ol></section>`;
}
function kanpaceNavigationShell(content){
  const module=kanpaceModule(),active=kanpaceActiveMenuItem(),entry=kanpaceNavigation.flatMap(group=>group.items).find(item=>item.id===active),name=entry?.label||kanpacePageNames[page]||'工作台';
  return `<div class="shell simplified-shell hierarchical-shell"><aside class="sidebar"><div class="sidebar-head"><a class="brand kanpace-brand" href="#page=workflow" aria-label="KANPACE · 工作台"><img class="kanpace-wordmark" src="/brand/KANPACE-Handoff-Black.svg" alt="KANPACE" width="240" height="29"></a>${workspaceSelector()}<div class="nav-shortcuts"><button type="button" class="agent-launch" data-action="agent-open">${icon('search')}<span>AI 工作助手</span></button></div></div>${kanpaceMenuMarkup()}<div class="sidebar-foot"><div class="user"><span class="avatar">K</span><div><strong>工厂端</strong><small>${esc(workspaceProfile().name)}</small></div></div></div></aside><div class="main-shell"><header class="topbar"><div class="breadcrumbs">${module.label===name?`<span>${esc(name)}</span>`:`<span>${Number.isInteger(module.step)?module.step+' · ':''}${esc(module.label)}</span>${icon('chevron')}<span>${esc(name)}</span>`}</div><div class="top-actions">${!window.kanpaceInstanceContext?.isolated&&(typeof accessState==='undefined'||!accessState?.enabled||accessState?.user?.role==='admin')?'<a class="btn" href="/control/index.html">配置中台</a>':''}<button class="mobile-agent-button" type="button" data-action="agent-open">${icon('search')}AI 工作助手</button><button class="icon-button" data-action="refresh" aria-label="刷新数据">${icon('refresh')}</button></div></header><main id="main" tabindex="-1">${page==='overview'?kanpaceWorkflowEntry():''}${content}</main></div></div>`;
}
function kanpaceNavigationApplyRoute(force=false){
  const key=location.hash;if(!force&&key===kanpaceLastRoute)return;kanpaceLastRoute=key;
  const h=new URLSearchParams(key.slice(1));
  if(typeof page!=='undefined'&&page==='readiness'&&typeof operationsProductionTab!=='undefined'){
    const requested=h.get('opTab')||'materials';operationsProductionTab=kanpaceProductionTabs.has(requested)&&(!['costs','commercial'].includes(requested)||kanpaceFinancialAllowed())?requested:'materials';
    if(typeof operationsProductionProject!=='undefined'){
      const requestedProject=h.has('opProject')?h.get('opProject'):h.get('project')||'';
      operationsProductionProject=typeof workspaceProjects==='function'&&workspaceProjects().some(p=>p.id===requestedProject)?requestedProject:'';
    }
  }
  if(typeof page!=='undefined'&&page==='exchange'&&typeof operationsExchangeType!=='undefined'&&['projects','people','materials','progress'].includes(h.get('exchangeType')))operationsExchangeType=h.get('exchangeType');
  if(typeof page!=='undefined'&&page==='planning'&&typeof referenceMode!=='undefined'&&h.has('referenceMode'))referenceMode=['departments','reference-flow','execution'].includes(h.get('referenceMode'))?h.get('referenceMode'):'departments';
  if(typeof page!=='undefined'&&page==='tasks'&&typeof executionFocus!=='undefined'&&h.has('taskFocus')){executionFocus=['all','active','paused','urgent'].includes(h.get('taskFocus'))?h.get('taskFocus'):'all';if(typeof search!=='undefined')search='';if(typeof tradeFilter!=='undefined')tradeFilter='';if(typeof statusFilter!=='undefined')statusFilter='';}
  if(typeof page!=='undefined'&&page==='people'&&typeof operationsResourceTab!=='undefined'&&h.has('resTab'))operationsResourceTab=kanpaceResourceTabs.has(h.get('resTab'))?h.get('resTab'):'people';
  if(typeof page!=='undefined'&&page==='projects'&&typeof projectStatusFilter!=='undefined'&&h.has('projectStatus'))projectStatusFilter=['active','completed','shipped','all'].includes(h.get('projectStatus'))?h.get('projectStatus'):'active';
}
function kanpaceNavigationBeforeRender(){const menu=document.querySelector('.nav-menu-disclosure');if(menu)kanpaceNavScroll=menu.scrollTop;kanpacePendingSection=new URLSearchParams(location.hash.slice(1)).get('section')==='badge-media-panel'?'badge-media-panel':'';kanpaceNavigationApplyRoute();}
function kanpaceNavigationAfterRender(){
  const menu=document.querySelector('.nav-menu-disclosure');if(menu){menu.scrollTop=kanpaceNavScroll;menu.addEventListener('scroll',()=>{kanpaceNavScroll=menu.scrollTop;},{passive:true});}
  const active=document.querySelector('[data-nav-item][aria-current="page"]'),id=active?.dataset.navItem||'';
  if(menu&&active&&id!==kanpaceLastActive&&!(typeof matchMedia==='function'&&matchMedia('(max-width: 680px)').matches)){
    const parent=active.getBoundingClientRect(),viewport=menu.getBoundingClientRect();if(parent.top<viewport.top||parent.bottom>viewport.bottom)menu.scrollTop+=parent.top-viewport.top-16;
  }kanpaceLastActive=id;
  if(kanpaceFocusAfterNavigation){kanpaceFocusAfterNavigation=false;document.getElementById('main')?.focus({preventScroll:true});if(typeof window.scrollTo==='function')window.scrollTo({top:0,behavior:'auto'});}
  const h=new URLSearchParams(location.hash.slice(1));if(typeof page!=='undefined'&&page==='device'&&kanpacePendingSection&&!h.has('section')){h.set('section',kanpacePendingSection);history.replaceState(null,'','#'+h.toString());}const section=h.get('section');
  if(typeof page!=='undefined'&&page==='device'&&section==='badge-media-panel'&&kanpaceLastSection!==location.hash){
    const node=document.getElementById(section);if(node){kanpaceLastSection=location.hash;node.scrollIntoView({block:'start',behavior:'auto'});const heading=node.querySelector('h2');if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});}}
  }else if(section!=='badge-media-panel')kanpaceLastSection='';
}
function kanpaceSetRouteParam(name,value){const h=new URLSearchParams(location.hash.slice(1));h.set(name,value);history.replaceState(null,'','#'+h.toString());}
document.addEventListener('toggle',event=>{
  const el=event.target;if(el.matches?.('.nav-group')){kanpaceMenuState[el.dataset.navGroup]=el.open;kanpaceRememberMenu();}
  else if(el.matches?.('.nav-menu-disclosure')&&typeof matchMedia==='function'&&matchMedia('(max-width: 680px)').matches)kanpaceMobileMenuOpen=el.open;
},true);
document.addEventListener('click',event=>{
  const selectFactory=event.target.closest?.('[data-select-factory]');
  if(selectFactory){const selector=document.getElementById('workspace-type');if(selector){event.preventDefault();if(typeof matchMedia==='function'&&matchMedia('(max-width: 680px)').matches){kanpaceMobileMenuOpen=false;const menu=document.querySelector('.nav-menu-disclosure');if(menu)menu.open=false;}selector.scrollIntoView?.({block:'center',behavior:'smooth'});selector.focus();if(typeof selector.showPicker==='function'){try{selector.showPicker();}catch{}}return;}}
  const link=event.target.closest?.('[data-nav-item]')||event.target.closest?.('[data-nav-primary]');
  if(link&&typeof page!=='undefined'){
    if(link.getAttribute('href')?.startsWith('#'))kanpaceFocusAfterNavigation=true;
    if(typeof matchMedia==='function'&&matchMedia('(max-width: 680px)').matches){kanpaceMobileMenuOpen=false;const menu=document.querySelector('.nav-menu-disclosure');if(menu)menu.open=false;}
    const href=link.getAttribute('href');if(href===location.hash){event.preventDefault();kanpaceLastSection='';kanpaceNavigationApplyRoute(true);if(typeof render==='function')render();}
  }
  const action=event.target.closest?.('[data-action]');if(!action||action.disabled)return;
  if(action.dataset.action==='ops-production-tab'&&kanpaceProductionTabs.has(action.dataset.id))kanpaceSetRouteParam('opTab',action.dataset.id);
  if(action.dataset.action==='task-focus'&&['all','active','paused','urgent'].includes(action.dataset.focus))kanpaceSetRouteParam('taskFocus',action.dataset.focus);
  if(action.dataset.action==='project-filter'&&['active','completed','shipped','all'].includes(action.dataset.status))kanpaceSetRouteParam('projectStatus',action.dataset.status);
  if(action.dataset.action==='reference-mode'&&['departments','reference-flow','execution'].includes(action.dataset.mode))kanpaceSetRouteParam('referenceMode',action.dataset.mode);
  if(action.dataset.action==='ops-resource-tab'&&kanpaceResourceTabs.has(action.dataset.id))kanpaceSetRouteParam('resTab',action.dataset.id);
},true);
document.addEventListener('change',event=>{if(event.target.id==='ops-production-project')kanpaceSetRouteParam('opProject',event.target.value);},true);
if(typeof matchMedia==='function')matchMedia('(max-width: 680px)').addEventListener('change',event=>{const menu=document.querySelector('.nav-menu-disclosure');if(menu)menu.open=!event.matches||kanpaceMobileMenuOpen;});
function kanpaceMountStandaloneNavigation(){
  const mount=document.querySelector('[data-kanpace-menu]');if(!mount)return;
  let financial=false;const draw=()=>{mount.innerHTML=kanpaceMenuMarkup({active:mount.dataset.kanpaceMenu,project:document.querySelector('#project')?.value||'',prefix:'/',financial});kanpaceNavigationAfterRender();};
  draw();fetch('/api/access').then(response=>response.ok?response.json():null).then(access=>{financial=!!access&&(!access.enabled||!!access.financial_access);draw();}).catch(()=>{});
  document.querySelector('#project')?.addEventListener('change',draw);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',kanpaceMountStandaloneNavigation,{once:true});else kanpaceMountStandaloneNavigation();
function kanpaceManagementView() {
  const groups=[
    {name:'工厂配置',items:[['people','people','人员与班组','人员、工种、班次和工作中心'],['templates','layers','流程模板','按工厂配置工序与放行条件'],['settings','money','人工与材料单价','材料单价、工时与报价参数'],['calibration','clock','工时参考','用真实报工调整工时参考']]},
    {name:'数据与账号',items:[['exchange','upload','表格导入导出','Excel 导入、字段映射与导出'],['access','shield','账号与权限','登录账号和岗位权限']]}
  ];
  const resources=`<details class="settings-resources"><summary>使用帮助 ${icon('down')}</summary><div><a href="/navigation-map/index.html${kanpaceNavProject()?'?'+new URLSearchParams({project:kanpaceNavProject()}):''}">全部功能地图 ${icon('arrow')}</a><button type="button" data-action="capabilities">图纸与模型支持说明 ${icon('arrow')}</button></div></details>`;
  return `<div class="page-head"><div><h1>工厂管理</h1><p>配置工厂流程、数据和账号。</p></div></div><div class="settings-directory">${groups.map(group=>`<section><h2>${esc(group.name)}</h2><div class="settings-directory-list">${group.items.filter(([id])=>id!=='settings'||typeof accessState==='undefined'||!accessState?.enabled||accessState.financial_access).map(([id,symbol,name,description])=>`<a href="${esc(kanpacePageHref(id))}" class="settings-directory-link">${icon(symbol)}<span><strong>${esc(name)}</strong><small>${esc(description)}</small></span>${icon('chevron')}</a>`).join('')}</div></section>`).join('')}</div>${resources}`;
}
