/* Local interaction model only. Never writes task state or invokes device APIs. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.BadgePreview=factory();})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  function create(tasks){return {tasks:tasks.map(t=>({...t,labelTotal:Number.isInteger(t.quantity)&&t.quantity>0?t.quantity:1,labelledUnits:t.labelConfirmed?(Number.isInteger(t.quantity)&&t.quantity>0?t.quantity:1):0,labelConfirmed:!!t.labelConfirmed})),active:0,returned:false};}
  function current(s){return s.tasks[s.active]||null;}
  function pending(s){return s.tasks.filter(t=>t.status!=='done'||!t.labelConfirmed);}
  function act(s,action,value){
    const t=current(s);if(s.returned)throw new Error('胸牌已归还，请重新体验。');
    if(action==='select'){const index=s.tasks.findIndex(x=>x.id===value);if(index<0)throw new Error('任务不存在。');if(t?.status==='in_progress'&&index!==s.active)throw new Error('请先暂停当前任务，再切换。');s.active=index;return s;}
    if(action==='return'){if(pending(s).length)throw new Error('还有任务或标签未完成。');s.returned=true;return s;}
    if(!t)throw new Error('暂无任务。');
    if(action==='start'){if(!['ready','paused'].includes(t.status))throw new Error('当前不能开工。');t.status='in_progress';}
    else if(action==='pause'){if(t.status!=='in_progress')throw new Error('当前没有正在进行的任务。');if(!value)throw new Error('请选择暂停原因。');t.status='paused';t.reason=value;}
    else if(action==='finish'){if(t.status!=='in_progress')throw new Error('请先开工。');t.status='done';}
    else if(action==='label'){if(t.status!=='done')throw new Error('完成后才能确认贴标。');const id=typeof value==='string'?value:value?.task_id,sequence=typeof value==='string'?1:value?.sequence;if(id!==t.id)throw new Error('标签与当前任务不匹配。');if(!Number.isInteger(sequence)||sequence<1||sequence>t.labelTotal||sequence>t.labelledUnits+1)throw new Error('请核对当前标签序号。');t.labelledUnits=Math.max(t.labelledUnits,sequence);t.labelConfirmed=t.labelledUnits===t.labelTotal;}
    else throw new Error('未知操作。');return s;
  }
  return {create,current,pending,act};
});
