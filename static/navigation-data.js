/* Shared, declarative destinations for the sidebar and the full feature map. */
'use strict';
window.KANPACE_MENU = [
  {id:'order-workflow',label:'订单工作流',icon:'layers',primary:'workflow',direct:true,items:[
    {id:'workflow',label:'订单工作流',page:'workflow',module:'projects',projectScoped:true}
  ]},
  {id:'factory',label:'选工厂',step:0,icon:'home',primary:'factory-setup',items:[
    {id:'factory-setup',label:'选择生产类型',path:'/factory-setup/index.html'},
    {id:'factory-onboarding',label:'开通独立工厂空间',path:'/factory-setup/index.html'},
    {id:'manage',label:'工厂设置',page:'manage'},
    {id:'people',label:'人员与班组',page:'people',resTab:'people'},
    {id:'workcenters',label:'设备与工位',page:'people',resTab:'workcenters'},
    {id:'templates',label:'流程模板',page:'templates'},
    {id:'settings',label:'人工与材料单价',page:'settings',financial:true},
    {id:'calibration',label:'工时参考',page:'calibration'},
    {id:'access',label:'账号权限',page:'access'}
  ]},
  {id:'import',label:'订单与资料',step:1,icon:'folder',primary:'daily-import',items:[
    {id:'daily-import',label:'录资料',page:'daily',dailyStep:'import',module:'projects'},
    {id:'projects',label:'项目订单',page:'projects',projectStatus:'active'},
    {id:'exchange',label:'Excel 导入导出',page:'exchange'}
  ]},
  {id:'review',label:'工程与计划',step:2,icon:'clock',primary:'drawing',items:[
    {id:'drawing',label:'拆与核对',page:'drawing',tab:'parts',projectScoped:true},
    {id:'draft-tasks',label:'任务草稿复核',page:'drawing',tab:'tasks',projectScoped:true},
    {id:'history',label:'图纸版本记录',page:'drawing',tab:'history',projectScoped:true},
    {id:'planning',label:'生产排程表',page:'planning'},
    {id:'materials',label:'物料需求与采购',page:'readiness',opTab:'materials'}
  ]},
  {id:'dispatch',label:'任务与人员',step:3,icon:'bolt',primary:'tasks',items:[
    {id:'tasks',label:'生产任务',page:'tasks',module:'tasks',projectScoped:true,taskFocus:'all'},
    {id:'daily-dispatch',label:'任务派工',page:'daily',dailyStep:'dispatch',module:'device'},
    {id:'device',label:'胸牌连接设置',page:'device'}
  ]},
  {id:'field',label:'生产协同',step:4,icon:'tasks',primary:'issues',fallback:'daily-return',items:[
    {id:'daily-execution',label:'现场回收',page:'daily',dailyStep:'execution',module:'tasks'},
    {id:'issues',label:'异常与任务切换',page:'readiness',opTab:'issues'},
    {id:'daily-labels',label:'准备标签 / 确认贴标',page:'daily',dailyStep:'labels',module:'tasks'},
    {id:'inspections',label:'质量验收',page:'readiness',opTab:'inspections'},
    {id:'deliveries',label:'发货与交付',page:'readiness',opTab:'deliveries'},
    {id:'daily-return',label:'归还与交接记录',page:'daily',dailyStep:'return',module:'device'}
  ]},
  {id:'dashboard',label:'总看板',step:5,icon:'money',primary:'overview',items:[
    {id:'overview',label:'总看板',page:'overview'},
    {id:'owner',label:'老板工作台',page:'owner',financial:true},
    {id:'bi',label:'经营报表',path:'/bi/index.html',financial:true},
    {id:'quote',label:'成本报价',page:'quote',tab:'quote',projectScoped:true,financial:true},
    {id:'costs',label:'成本与款项',page:'readiness',opTab:'costs',financial:true},
    {id:'commercial',label:'变更与收款',page:'readiness',opTab:'commercial',financial:true}
  ]}
];
window.kanpaceMenuHref = function(item,options={}) {
  const project=String(options.projectId||''),prefix=options.prefix||'';
  if(item.path){
    if(item.path==='/model/index.html')return project?item.path+'?'+new URLSearchParams({project}):prefix+'#page=projects&tab=parts';
    return item.path;
  }
  const params=new URLSearchParams({page:item.page||'overview',tab:item.tab||'parts'});
  if(project)params.set('project',project);
  if(item.dailyStep)params.set('step',item.dailyStep);
  const workDate=options.date||(typeof location!=='undefined'?new URLSearchParams((location.hash||'').slice(1)).get('date'):'');
  if(/^\d{4}-\d{2}-\d{2}$/.test(workDate||''))params.set('date',workDate);
  if(item.opTab){params.set('opTab',item.opTab);params.set('opProject',options.opProject??project);}
  if(item.section==='badge-media-panel')params.set('section',item.section);
  if(['people','teams','workcenters','factories'].includes(item.resTab))params.set('resTab',item.resTab);
  if(['active','completed','shipped','all'].includes(item.projectStatus))params.set('projectStatus',item.projectStatus);
  if(['departments','reference-flow','execution'].includes(item.referenceMode))params.set('referenceMode',item.referenceMode);
  if(['all','active','paused','urgent'].includes(item.taskFocus))params.set('taskFocus',item.taskFocus);
  return prefix+'#'+params.toString();
};
