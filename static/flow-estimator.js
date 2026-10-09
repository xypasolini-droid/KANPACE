'use strict';

// This module makes local forecast drafts only. It never calls a task or planning API.
const flowNodeDefinitions = [
  {id:'technical',label:'技术拆单'}, {id:'wood',label:'木作'},
  {id:'paint',label:'油漆'}, {id:'metal',label:'五金'},
  {id:'outsourcing',label:'外协配套'}, {id:'assembly',label:'安装总装'},
  {id:'packing',label:'包装'}, {id:'shipping',label:'发货'}
];
const flowEstimatorDrafts = new Map();
function flowValidDays(value){return typeof value==='number'&&Number.isFinite(value)&&value>=0&&value<=36500;}
function flowStatDays(stat){return stat&&Number.isInteger(stat.n)&&stat.n>0&&flowValidDays(stat.p50)?stat.p50:null;}
function flowDayText(value){return value==null?'待估':value===0?'当天':`${Number(value.toFixed(2))} 天`;}
function flowDateValue(value){if(!/^\d{4}-\d{2}-\d{2}$/.test(value||''))return null;const d=new Date(value+'T00:00:00Z');return Number.isFinite(d.getTime())&&d.toISOString().slice(0,10)===value?d:null;}
function flowDateAt(start,days){const date=flowDateValue(start);if(!date||days==null||!Number.isFinite(days))return null;return new Date(date.getTime()+Math.round(days*86400000)).toISOString();}
function flowDisplayDate(value){if(!value)return '—';const time=value.slice(11,16);return value.slice(0,10)+(time==='00:00'?'':` ${time}`);}

/** Calendar-time CPM: all predecessor branches must finish, so joins take max. */
function flowEstimate(input,startDate){
  const nodes=(Array.isArray(input)?input:[]).filter(n=>n.enabled!==false),byId=new Map(),errors=[];
  for(const node of nodes){if(!node.id||byId.has(node.id))errors.push('工序编号缺失或重复');else byId.set(node.id,node);if(node.days!==null&&!flowValidDays(node.days))errors.push(`${node.label||node.id}：工期须为 0 至 36500 的日历天数`);}
  for(const node of nodes)for(const id of new Set(node.predecessors||[])){
    if(id===node.id)errors.push(`${node.label||node.id}：不能以前序依赖自身`);
    else if(!byId.has(id))errors.push(`${node.label||node.id}：前置工序不存在或已停用`);
  }
  if(startDate&&!flowDateValue(startDate))errors.push('请选择有效的开始日期');
  const order=[],pending=new Set(nodes.map(n=>n.id));
  while(pending.size){const ready=[...pending].filter(id=>(byId.get(id)?.predecessors||[]).every(p=>order.includes(p)));if(!ready.length)break;for(const id of ready){order.push(id);pending.delete(id);}}
  if(pending.size&&!errors.length){
    const done=new Set(),stack=[];let cycle=[];
    const visit=id=>{if(cycle.length||done.has(id))return;const index=stack.indexOf(id);if(index>=0){cycle=stack.slice(index).concat(id);return;}stack.push(id);for(const p of byId.get(id).predecessors||[])visit(p);stack.pop();done.add(id);};
    for(const id of pending)visit(id);
    errors.push(`前后序形成循环：${cycle.map(id=>byId.get(id).label).join(' → ')}。请取消一条前置关系。`);
  }
  if(errors.length)return {valid:false,complete:false,errors:[...new Set(errors)],order,nodes:[],total_days:null,end_date:null};
  const calculated=new Map();
  for(const id of order){const node=byId.get(id),previous=(node.predecessors||[]).map(p=>calculated.get(p));const start=previous.some(p=>p.earliest_finish==null)?null:Math.max(0,...previous.map(p=>p.earliest_finish));const finish=start==null||node.days==null?null:start+node.days;calculated.set(id,{id,label:node.label,days:node.days,earliest_start:start,earliest_finish:finish,start_date:flowDateAt(startDate,start),end_date:flowDateAt(startDate,finish),latest_start:null,latest_finish:null,slack:null,critical:false});}
  const complete=nodes.length>0&&[...calculated.values()].every(n=>n.earliest_finish!=null),total=complete?Math.max(0,...[...calculated.values()].map(n=>n.earliest_finish)):null;
  if(complete)for(const id of [...order].reverse()){
    const node=calculated.get(id),next=nodes.filter(n=>(n.predecessors||[]).includes(id)).map(n=>calculated.get(n.id));
    node.latest_finish=next.length?Math.min(...next.map(n=>n.latest_start)):total;
    node.latest_start=node.latest_finish-node.days;node.slack=Math.max(0,node.latest_start-node.earliest_start);node.critical=Math.abs(node.slack)<1e-8;
  }
  return {valid:true,complete,errors:[],order,nodes:[...calculated.values()],total_days:total,end_date:flowDateAt(startDate,total)};
}
function flowSuggestedRoute(options={}){
  const paintEnabled=!options.skipPaint||options.metalPaint;
  return {technical:[],wood:['technical'],metal:['technical'],outsourcing:['technical'],paint:[...(!options.skipPaint?['wood']:[]),...(options.metalPaint?['metal']:[])],assembly:[...(paintEnabled?['paint']:[]),...(options.skipPaint?['wood']:[]),'metal','outsourcing'],packing:['assembly'],shipping:['packing']};
}
function flowApplyOptions(draft,next){
  const oldRoute=flowSuggestedRoute(draft.options),newRoute=flowSuggestedRoute(next),enabled=new Set(draft.nodes.filter(n=>n.id==='paint'?!next.skipPaint||next.metalPaint:true).map(n=>n.id));
  for(const node of draft.nodes){node.enabled=enabled.has(node.id);node.predecessors=[...new Set([...(node.predecessors||[]).filter(id=>!oldRoute[node.id].includes(id)),...newRoute[node.id]])].filter(id=>enabled.has(id));}
  draft.options={...next};if(!enabled.has(draft.selected))draft.selected='assembly';
}
function flowContextKey(context){return String(context.project_id||context.project_name||'schedule-reference');}
function flowDraftForContext(context={}){
  const key=flowContextKey(context),stats=Array.isArray(context.stats)?context.stats:[];
  let draft=flowEstimatorDrafts.get(key);
  if(!draft){
    const options={skipPaint:false,metalPaint:false},route=flowSuggestedRoute(options);
    draft={key,context,start_date:flowDateValue(context.start_date)?context.start_date:'',manualStart:false,selected:'technical',options,nodes:flowNodeDefinitions.map(n=>{const stat=stats.find(s=>s.node_id===n.id);return {...n,days:flowStatDays(stat),manual:false,enabled:true,predecessors:route[n.id].slice(),stat:stat||null};})};flowEstimatorDrafts.set(key,draft);
  }else{
    draft.context=context;
    for(const node of draft.nodes){node.stat=stats.find(s=>s.node_id===node.id)||null;if(!node.manual)node.days=flowStatDays(node.stat);}
    if(!draft.manualStart&&flowDateValue(context.start_date))draft.start_date=context.start_date;
  }
  return draft;
}
function flowExportDraft(draft){return {schema:'kanpace.flow-estimate.v1',kind:'forecast_draft',project_id:draft.context.project_id||null,project_name:draft.context.project_name||null,start_date:draft.start_date||null,unit:'calendar_elapsed_days',method:'CPM_longest_path',assumptions:['依赖关系为可编辑工厂建议，未由表格列顺序证明','时间为日历流转天数，非人工工时','未考虑人员、设备产能及排队'],options:{...draft.options},nodes:draft.nodes.map(n=>({id:n.id,label:n.label,enabled:n.enabled,days:n.days,predecessors:n.predecessors.slice(),duration_source:n.manual?'manual':flowStatDays(n.stat)!=null?'source_p50':'unknown',statistics:n.stat})),estimate:flowEstimate(draft.nodes,draft.start_date)};}
function flowGraphLayout(draft,result){
  const active=draft.nodes.filter(n=>n.enabled),rank=new Map();
  for(const id of result.valid?result.order:active.map(n=>n.id)){const node=active.find(n=>n.id===id);rank.set(id,result.valid?Math.max(0,...node.predecessors.map(p=>(rank.get(p)||0)+1)):['technical','wood','metal','outsourcing','paint','assembly','packing','shipping'].indexOf(id));}
  const columns=Math.max(1,...rank.values())+1,groups=Array.from({length:columns},()=>[]);for(const n of active)groups[rank.get(n.id)].push(n);
  const rows=Math.max(1,...groups.map(g=>g.length)),positions=new Map(groups.flatMap((group,col)=>group.map((n,i)=>[n.id,{col:col+1,row:rows-group.length+2*i+1}])));
  // Keep wood → paint on the upper branch; otherwise metal's long assembly edge
  // visually runs through the paint card and suggests a dependency that does not exist.
  if(result.valid&&positions.has('paint')&&positions.has('wood')&&groups[rank.get('paint')].length===1)positions.get('paint').row=positions.get('wood').row;
  return {columns,rows,positions};
}
function flowSourceText(node){if(node.manual)return '手动核定';return flowStatDays(node.stat)!=null?`原表参考 · ${node.stat.n} 个样本`:'暂无可靠工期';}
function flowSourceExample(example){
  if(typeof example==='string')return esc(example);
  if(!example||typeof example!=='object')return '';
  const location=[example.filename,example.sheet,Number.isInteger(example.row)?`第 ${example.row} 行`:null].filter(Boolean),order=[example.order_no,example.shop].filter(Boolean);
  const interval=[example.start&&example.end?`${example.start} → ${example.end}`:null,flowValidDays(example.days)?`日历间隔：${flowDayText(example.days)}`:null].filter(Boolean),cells=[example.start_cell,example.end_cell].filter(Boolean);
  const history=example.is_historical_fallback?`历史计划 · 非最新计划${example.latest_snapshot_date?`（最新快照 ${example.latest_snapshot_date}）`:''}`:'';
  return [history,location.join(' · '),order.length?`订单：${order.join(' · ')}`:'',interval.join(' · '),cells.length?`单元格：${cells.join(' → ')}`:''].filter(Boolean).map(line=>`<span>${esc(line)}</span>`).join('');
}
function flowStatDetails(node){
  const stat=node.stat,n=Number.isInteger(stat?.n)&&stat.n>0?stat.n:0,examples=Array.isArray(stat?.source_examples)?stat.source_examples:[];
  return `<details class="flow-source"><summary>工期依据${n?` · ${n} 个样本`:''}</summary><p>${esc(stat?.basis||'原表暂无可用于此节点的可靠工期，请手动核定。')}</p>${n?`<dl><div><dt>P25</dt><dd>${flowValidDays(stat.p25)?flowDayText(stat.p25):'—'}</dd></div><div><dt>中位数 P50</dt><dd>${flowStatDays(stat)!=null?flowDayText(stat.p50):'待估'}</dd></div><div><dt>P75</dt><dd>${flowValidDays(stat.p75)?flowDayText(stat.p75):'—'}</dd></div></dl>`:''}${node.days===0||flowStatDays(stat)===0?'<p>当天表示起止节点在同一日，并非零人工工时。</p>':''}${examples.length?`<ul>${examples.slice(0,5).map(e=>flowSourceExample(e)).filter(Boolean).map(text=>`<li>${text}</li>`).join('')}</ul>`:''}${node.id==='outsourcing'?'<p>外协配套是否含玻璃、灯光，需按工厂实际确认。</p>':''}</details>`;
}
function flowEstimatorView(context={}){
  const draft=flowDraftForContext(context),result=flowEstimate(draft.nodes,draft.start_date),layout=flowGraphLayout(draft,result),active=draft.nodes.filter(n=>n.enabled),selected=active.find(n=>n.id===draft.selected)||active[0],current=result.nodes.find(n=>n.id===selected.id),unknown=active.filter(n=>n.days==null),known=active.length-unknown.length;
  const html=`<section class="flow-estimator" data-flow-key="${esc(draft.key)}"><div class="flow-heading"><div><span class="eyebrow">工序关系与周期</span><h2>${esc(context.project_name||'推算生产周期')}</h2><p>调整前后序和工期，查看并行生产的预计完成时间。</p></div>${button('导出推算草案','flow-export','download','',result.valid?'':'disabled')}</div>
  <div class="flow-topline"><label class="flow-date-label">预计开始<input type="date" data-flow-field="start_date" aria-label="推算开始日期" value="${esc(draft.start_date)}"></label><div class="flow-metric"><span>预计流转周期</span><strong>${result.complete?flowDayText(result.total_days):'待估'}</strong></div><div class="flow-metric"><span>预计完成</span><strong class="flow-finish">${result.complete&&result.end_date?flowDisplayDate(result.end_date):'—'}</strong></div><div class="flow-metric"><span>已填工期</span><strong>${known}<small> / ${active.length}</small></strong></div></div>
  <div class="flow-options" aria-label="工艺选项"><span>建议工艺</span><label><input type="checkbox" data-flow-option="metalPaint" ${draft.options.metalPaint?'checked':''}>五金需要油漆</label><label><input type="checkbox" data-flow-option="skipPaint" ${draft.options.skipPaint?'checked':''}>木作免漆</label>${button('恢复建议关系','flow-reset-route','refresh')}</div>
  ${result.errors.length?`<div class="flow-error" role="alert">${result.errors.map(esc).join('<br>')}</div>`:unknown.length?`<p class="flow-pending" role="status">${esc(unknown.map(n=>n.label).join('、'))}工期待估，补齐后显示总周期。</p>`:''}
  <div class="flow-diagram-panel"><div class="flow-diagram-caption"><span>点击工序，修改工期和前置关系</span><span><i></i>关键路径 <b></b>待估</span></div><div class="flow-graph-scroll" tabindex="0" role="region" aria-label="工序关系图，可左右滚动"><div class="flow-graph" style="--flow-cols:${layout.columns};--flow-rows:${layout.rows*2};min-width:${Math.max(660,layout.columns*160+(layout.columns-1)*34)}px"><svg class="flow-lines" aria-hidden="true"><defs><marker id="flow-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7 Z" fill="context-stroke"></path></marker></defs></svg>${active.map(node=>{const item=result.nodes.find(n=>n.id===node.id),position=layout.positions.get(node.id);return `<button type="button" class="flow-node ${node.id===selected.id?'selected':''} ${item?.critical?'critical':''} ${node.days==null?'unknown':''}" style="grid-column:${position.col};grid-row:${position.row} / span 2" data-action="flow-select" data-node="${node.id}" aria-pressed="${node.id===selected.id}" aria-label="${esc(node.label)}，${esc(flowDayText(node.days))}，${esc(flowSourceText(node))}"><span class="flow-node-label">${esc(node.label)}${item?.critical?'<i title="关键路径"></i>':''}</span><strong>${flowDayText(node.days)}</strong><small>${esc(flowSourceText(node))}</small>${item?.start_date&&item?.end_date?`<em>${esc(flowDisplayDate(item.start_date).slice(5))} → ${esc(flowDisplayDate(item.end_date).slice(5))}</em>`:'<em>日历流转天数</em>'}</button>`;}).join('')}</div></div><p class="flow-legend-note">分支可并行，汇合处等待所有前序。连线为可编辑的工厂建议。</p></div>
  <div class="flow-editor"><div class="flow-editor-main"><div class="flow-editor-title"><h3>${esc(selected.label)}</h3><span>${esc(flowSourceText(selected))}</span></div><label class="flow-duration-label">工期 <span>日历天</span><div><input type="number" min="0" max="36500" step="any" inputmode="decimal" data-flow-field="days" data-node="${selected.id}" aria-label="${esc(selected.label)}工期（日历天）" value="${selected.days==null?'':esc(selected.days)}" placeholder="待估"><span>天</span>${selected.manual&&flowStatDays(selected.stat)!=null?button('采用原表参考','flow-source-reset',null,'',`data-node="${selected.id}"`):''}</div></label>${current?.start_date?`<p class="flow-node-dates">${esc(flowDisplayDate(current.start_date))} 开始${current.end_date?` · ${esc(flowDisplayDate(current.end_date))} 完成`:''}</p>`:''}${flowStatDetails(selected)}</div><fieldset class="flow-predecessors"><legend>必须先完成</legend><p>不勾选前序时，可从开始日启动。</p><div>${active.map(node=>`<label class="${node.id===selected.id?'self':''}"><input type="checkbox" data-flow-predecessor="${node.id}" data-node="${selected.id}" ${selected.predecessors.includes(node.id)?'checked':''} ${node.id===selected.id?'disabled':''}>${esc(node.label)}${node.id===selected.id?'<small>当前工序</small>':''}</label>`).join('')}</div></fieldset></div>
  <p class="flow-footnote">预测按日历连续流转，不含人员、设备产能与排队。草案不会写入生产任务或排程。</p></section>`;
  if(typeof requestAnimationFrame==='function')requestAnimationFrame(()=>flowDrawLines(draft.key));return html;
}
function flowRootForKey(key){return [...document.querySelectorAll('.flow-estimator')].find(el=>el.dataset.flowKey===key);}
function flowDrawLines(key){
  const root=flowRootForKey(key),draft=flowEstimatorDrafts.get(key);if(!root||!draft)return;
  const graph=root.querySelector('.flow-graph'),svg=graph?.querySelector('.flow-lines');if(!graph||!svg)return;
  const box=graph.getBoundingClientRect(),nodes=new Map([...graph.querySelectorAll('[data-node]')].map(el=>[el.dataset.node,el.getBoundingClientRect()])),result=flowEstimate(draft.nodes,draft.start_date);let paths='';
  for(const target of draft.nodes.filter(n=>n.enabled))for(const id of target.predecessors){const a=nodes.get(id),b=nodes.get(target.id);if(!a||!b)continue;const x1=a.right-box.left,y1=a.top+a.height/2-box.top,x2=b.left-box.left-5,y2=b.top+b.height/2-box.top,mid=x1+Math.max(16,(x2-x1)/2),from=result.nodes.find(n=>n.id===id),to=result.nodes.find(n=>n.id===target.id),critical=from?.critical&&to?.critical&&Math.abs(from.earliest_finish-to.earliest_start)<1e-8;paths+=`<path d="M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}" class="${critical?'critical':''}" marker-end="url(#flow-arrow)"></path>`;}
  svg.setAttribute('viewBox',`0 0 ${box.width} ${box.height}`);svg.querySelectorAll(':scope > path').forEach(el=>el.remove());svg.insertAdjacentHTML('beforeend',paths);
}
function flowRefresh(draft,focus){
  const root=flowRootForKey(draft.key);if(!root)return;const graphScroll=root.querySelector('.flow-graph-scroll')?.scrollLeft||0;
  root.outerHTML=flowEstimatorView(draft.context);const next=flowRootForKey(draft.key);if(next){next.querySelector('.flow-graph-scroll').scrollLeft=graphScroll;if(focus){const target=[...next.querySelectorAll(focus.selector)].find(el=>!focus.value||el.getAttribute(focus.attribute)===focus.value);target?.focus({preventScroll:true});}}
}
if(typeof document!=='undefined'){
  document.addEventListener('click',event=>{
    const b=event.target.closest('[data-action^="flow-"]'),root=b?.closest('.flow-estimator'),draft=root&&flowEstimatorDrafts.get(root.dataset.flowKey);if(!draft||b.disabled)return;
    if(b.dataset.action==='flow-select'){draft.selected=b.dataset.node;flowRefresh(draft,{selector:'[data-action="flow-select"]',attribute:'data-node',value:b.dataset.node});}
    if(b.dataset.action==='flow-source-reset'){const node=draft.nodes.find(n=>n.id===b.dataset.node);node.manual=false;node.days=flowStatDays(node.stat);flowRefresh(draft,{selector:'[data-flow-field="days"]'});}
    if(b.dataset.action==='flow-reset-route'){const route=flowSuggestedRoute(draft.options);for(const node of draft.nodes)node.predecessors=route[node.id].slice();flowRefresh(draft,{selector:'[data-action="flow-reset-route"]'});}
    if(b.dataset.action==='flow-export'){const data=flowExportDraft(draft);if(!data.estimate.valid)return;const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=`KANPACE-周期推算草案-${(draft.context.project_name||'工序方案').replace(/[\\/:*?"<>|]/g,'-').slice(0,80)}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  });
  document.addEventListener('change',event=>{
    const input=event.target,root=input.closest('.flow-estimator'),draft=root&&flowEstimatorDrafts.get(root.dataset.flowKey);if(!draft)return;let focus;
    if(input.dataset.flowField==='start_date'){draft.start_date=input.value;draft.manualStart=true;focus={selector:'[data-flow-field="start_date"]'};}
    else if(input.dataset.flowField==='days'){const node=draft.nodes.find(n=>n.id===input.dataset.node);node.days=input.value===''?null:Number(input.value);node.manual=true;focus={selector:'[data-flow-field="days"]'};}
    else if(input.dataset.flowOption){flowApplyOptions(draft,{...draft.options,[input.dataset.flowOption]:input.checked});focus={selector:'[data-flow-option]',attribute:'data-flow-option',value:input.dataset.flowOption};}
    else if(input.dataset.flowPredecessor){const node=draft.nodes.find(n=>n.id===input.dataset.node),id=input.dataset.flowPredecessor;node.predecessors=input.checked?[...new Set([...node.predecessors,id])]:node.predecessors.filter(p=>p!==id);focus={selector:'[data-flow-predecessor]',attribute:'data-flow-predecessor',value:id};}
    else return;flowRefresh(draft,focus);
  });
  // Capture typing immediately without replacing the focused input on every key.
  // This also keeps a draft intact if the surrounding workspace redraws while editing.
  document.addEventListener('input',event=>{
    const input=event.target;if(input.dataset.flowField!=='days')return;
    const root=input.closest('.flow-estimator'),draft=root&&flowEstimatorDrafts.get(root.dataset.flowKey),node=draft?.nodes.find(n=>n.id===input.dataset.node);
    if(node){node.days=input.value===''?null:Number(input.value);node.manual=true;}
  });
  if(typeof window!=='undefined')window.addEventListener('resize',()=>{for(const root of document.querySelectorAll('.flow-estimator'))flowDrawLines(root.dataset.flowKey);});
}
