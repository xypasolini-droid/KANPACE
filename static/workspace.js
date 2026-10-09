'use strict';
const workspaceProfiles={
  cabinet:{name:'展柜工厂',flow:'订单 → 设计拆单 → 部件生产 → 装配质检 → 包装发货',example:'例如：深圳门店 · 综合展示柜'},
  machinery:{name:'机械设备工厂',flow:'订单 → 工程设计 → 采购加工 → 装配调试 → 验收交付',example:'例如：客户 A · 自动化设备'},
  site:{name:'工程现场',flow:'项目 → 施工深化 → 材料进场 → 施工协同 → 现场验收',example:'例如：上海门店 · 展陈安装'}
};
let workspaceType=(()=>{try{const value=localStorage.getItem('kanpace-workspace-type');return workspaceProfiles[value]?value:'cabinet';}catch{return 'cabinet';}})();
function workspaceProjectType(project){return workspaceProfiles[project?.factory_type]?project.factory_type:'cabinet';}
function workspaceProfile(){const c=globalThis.kanpaceInstanceContext,p=c?.profile,industry=p?.factory_type===workspaceType?p:null;const name=industry?.industry_name||(c?.isolated?c.instance?.industry_name:null);return name?{...workspaceProfiles[workspaceType],name,flow:'订单资料 → 本厂流程拆解 → 齐套排产 → 任务交接 → 验收交付',example:'填写本厂订单或生产批次名称'}:workspaceProfiles[workspaceType];}
function workspaceProjects(){return (state?.projects||[]).filter(p=>workspaceProjectType(p)===workspaceType);}
function workspacePersist(type){const fixed=globalThis.kanpaceInstanceContext?.isolated?globalThis.kanpaceInstanceContext.instance?.factory_type:null;workspaceType=fixed||type;try{localStorage.setItem('kanpace-workspace-type',workspaceType);}catch{}}
function syncWorkspaceProject(){const requested=state?.projects.find(p=>p.id===projectId);if(requested)workspacePersist(workspaceProjectType(requested));}
function workspaceSelector(){const c=globalThis.kanpaceInstanceContext;if(c?.isolated)return `<div class="workspace-switch factory-space-name">${icon('home')}<span><strong>${esc(c.instance.name)}</strong><small>${esc(workspaceProfile().name)}${c.profile?' · 流程 V'+esc(c.profile.version):''}</small></span></div>`;return `<label class="workspace-switch">${icon('home')}<select id="workspace-type" aria-label="工厂与工作场景">${Object.entries(workspaceProfiles).map(([value,p])=>`<option value="${value}" ${value===workspaceType?'selected':''}>${esc(c?.profile?.status==='installed'&&c.profile.factory_type===value&&c.profile.industry_name?c.profile.industry_name:p.name)}</option>`).join('')}</select></label>`;}
document.addEventListener('change',event=>{
  if(event.target.id!=='workspace-type')return;
  const type=event.target.value;if(!workspaceProfiles[type])return;
  workspacePersist(type);const remembered=storedProject();projectId=workspaceProjects().find(p=>p.id===remembered)?.id||workspaceProjects()[0]?.id||'';projectStatusFilter='active';
  try{localStorage.setItem('kanpace-project-'+workspaceType,projectId);}catch{}
  if(typeof planningReset==='function')planningReset();
  navigate('projects','parts',projectId);
});
