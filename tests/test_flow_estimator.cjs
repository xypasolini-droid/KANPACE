const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(path.join(__dirname,'../static/flow-estimator.js'),'utf8');
const handlers={},context={console,Map,Set,Date,Number,JSON,URL,Blob,setTimeout,esc:v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),icon:()=>'',button:(label,action,i,cls='',extra='')=>`<button data-action="${action}" ${extra}>${label}</button>`,document:{addEventListener:(event,handler)=>{handlers[event]=handler;}}};
vm.createContext(context);const run=s=>vm.runInContext(s,context),plain=value=>JSON.parse(JSON.stringify(value));run(source);
function estimate(nodes,start='2026-09-07'){context.fixture=nodes;context.start=start;return plain(run('flowEstimate(fixture,start)'));}
const node=(id,days,predecessors=[],enabled=true)=>({id,label:id,days,predecessors,enabled});

// Joins take the longest parallel branch, never the sum of department times.
let result=estimate([node('a',2),node('b',3,['a']),node('c',7,['a']),node('d',1,['b','c'])]);
assert.equal(result.total_days,10);assert.equal(result.end_date,'2026-09-17T00:00:00.000Z');
assert.equal(result.nodes.find(n=>n.id==='b').slack,4);assert.equal(result.nodes.find(n=>n.id==='c').critical,true);
assert.equal(result.nodes.find(n=>n.id==='b').critical,false);
result=estimate([node('a',2),node('b',3,['a']),node('c',3,['a']),node('d',0,['b','c'])]);
assert(result.nodes.every(n=>n.critical));assert.equal(result.total_days,5);

// Unknown durations block dependent completion, while independent branches remain inspectable.
result=estimate([node('a',1),node('b',null,['a']),node('c',2,['a']),node('d',1,['b','c'])]);
assert(result.valid&&!result.complete);assert.equal(result.total_days,null);assert.equal(result.end_date,null);
assert.equal(result.nodes.find(n=>n.id==='b').earliest_start,1);assert.equal(result.nodes.find(n=>n.id==='c').earliest_finish,3);
assert.equal(result.nodes.find(n=>n.id==='d').earliest_start,null);assert(!result.nodes.some(n=>n.critical));
assert.equal(estimate([]).total_days,null);

// Zero is an explicit duration, never a substitute for missing data or 等通知.
assert.equal(estimate([node('shipping',0)]).total_days,0);
assert.equal(run('flowDayText(0)'),'当天');assert.equal(run('flowDayText(null)'),'待估');
for(const stat of [{n:0,p50:0},{n:0,p50:8},{n:-1,p50:8},{n:1,p50:-1},{n:1,p50:null},{n:1,p50:'2'},{n:1.5,p50:2},{n:true,p50:2},{n:1,p50:Infinity}]){context.stat=stat;assert.equal(run('flowStatDays(stat)'),null);}
context.stat={n:1,p50:0};assert.equal(run('flowStatDays(stat)'),0);
for(const days of [-1,NaN,Infinity,'4',undefined,36501])assert(!estimate([node('bad',days)]).valid);
assert(!estimate([node('a',1,['a'])]).valid);
assert(!estimate([node('a',1,['b']),node('b',1,['a'])]).valid);
assert(!estimate([node('a',1,['b']),node('b',1,['a']),node('c',1,['b'])]).errors[0].includes('c'));
assert(!estimate([node('a',1,['missing'])]).valid);
assert(!estimate([node('a',1),node('a',2)]).valid);
assert(!estimate([node('a',1,['disabled']),node('disabled',1,[],false)]).valid);
assert(!estimate([node('a',1)],'2026-02-30').valid);
assert.equal(estimate([node('a',1)],'').end_date,null);
assert.equal(estimate([node('a',.5)],'2026-09-07').end_date,'2026-09-07T12:00:00.000Z');
assert.equal(estimate([node('a',1)],'2026-03-08').end_date,'2026-03-09T00:00:00.000Z');

// Defaults are suggested DAGs, not a serial chain based on spreadsheet column order.
context.stats=[['technical',1],['wood',4],['paint',2],['metal',9],['outsourcing',6],['assembly',2],['packing',1],['shipping',0]].map(([node_id,p50])=>({node_id,n:4,p25:p50,p50,p75:p50+2,basis:'测试夹具，不是客户统计'}));
run("var fixtureDraft=flowDraftForContext({project_id:'qa-a',project_name:'QA A',start_date:'2026-09-07',stats});");
assert.equal(run('flowEstimate(fixtureDraft.nodes,fixtureDraft.start_date).total_days'),13);
assert(!run("fixtureDraft.nodes.some(n=>n.id==='photography')"));
assert.deepEqual(plain(run("fixtureDraft.nodes.find(n=>n.id==='packing').predecessors")),['assembly']);
assert.deepEqual(plain(run("fixtureDraft.nodes.find(n=>n.id==='shipping').predecessors")),['packing']);
run('flowApplyOptions(fixtureDraft,{...fixtureDraft.options,metalPaint:true})');
assert.deepEqual(plain(run("fixtureDraft.nodes.find(n=>n.id==='paint').predecessors")),['wood','metal']);
assert.equal(run('flowEstimate(fixtureDraft.nodes,fixtureDraft.start_date).total_days'),15);
run('flowApplyOptions(fixtureDraft,{...fixtureDraft.options,skipPaint:true,metalPaint:false})');
assert.equal(run("fixtureDraft.nodes.find(n=>n.id==='paint').enabled"),false);
assert(run("fixtureDraft.nodes.find(n=>n.id==='assembly').predecessors.includes('wood')"));
assert(!run("fixtureDraft.nodes.find(n=>n.id==='assembly').predecessors.includes('paint')"));
assert.equal(run('flowEstimate(fixtureDraft.nodes,fixtureDraft.start_date).total_days'),13);
run('flowApplyOptions(fixtureDraft,{...fixtureDraft.options,metalPaint:true})');
assert.equal(run("fixtureDraft.nodes.find(n=>n.id==='paint').enabled"),true);
assert.deepEqual(plain(run("fixtureDraft.nodes.find(n=>n.id==='paint').predecessors")),['metal']);
assert.equal(run('flowEstimate(fixtureDraft.nodes,fixtureDraft.start_date).total_days'),15);
assert(!run('fixtureDraft.nodes.some(n=>/玻璃|灯光/.test(n.label))'));

// Missing, late-loaded, and refreshed statistics must not leak between orders or override manual edits.
run("var emptyDraft=flowDraftForContext({project_id:'qa-empty',stats:[]})");
assert(run('emptyDraft.nodes.every(n=>n.days===null)'));
run("var late=flowDraftForContext({project_id:'qa-late',stats:[]});flowDraftForContext({project_id:'qa-late',start_date:'2026-09-09',stats:[{node_id:'photography',n:2,p50:3}]})");
assert.equal(run('late.start_date'),'2026-09-09');
assert(!run("late.nodes.some(n=>n.id==='photography')"));
assert(!run("JSON.stringify(flowExportDraft(late)).includes('photography')"));
run("fixtureDraft.nodes[0].days=7;fixtureDraft.nodes[0].manual=true;flowDraftForContext({project_id:'qa-a',stats:[{node_id:'technical',n:8,p50:3}]})");
assert.equal(run('fixtureDraft.nodes[0].days'),7);
run("var second=flowDraftForContext({project_id:'qa-b',project_name:'QA A',stats:[{node_id:'technical',n:8,p50:3}]})");
assert.equal(run('second.nodes[0].days'),3);assert.equal(run('emptyDraft.nodes[0].days'),null);

// HTML uses project/source escaping and distinguishes estimates from work hours and production saves.
context.htmlContext={project_id:'qa-html',project_name:'<img src=x onerror=alert(1)>',stats:[{node_id:'technical',n:2,p25:1,p50:2,p75:3,basis:'<script>bad</script>',source_examples:['<b>单元格</b>']} ]};
const html=run('flowEstimatorView(htmlContext)');
assert(!html.includes('<img src=x'));assert(html.includes('&lt;img'));assert(!html.includes('<script>bad'));
assert(html.includes('日历天'));assert(html.includes('不会写入生产任务或排程'));assert(html.includes('导出推算草案'));
assert(html.includes('aria-label="工序关系图，可左右滚动"'));assert(html.includes('data-flow-predecessor="technical" data-node="technical"  disabled'));
assert(!html.includes('0 天</strong>'));assert(!html.includes('保存排程'));assert(!html.includes('拍摄'));
context.sourceExample={filename:'17.xlsx',sheet:'排程会议 0813',row:12,start:'2025-08-01',end:'2025-08-03',days:2,start_cell:'G12',end_cell:'K12',source_id:'internal-id',date_trusted:true,key_basis:'internal-field',shop:'商场 A'};
const renderedExample=run('flowSourceExample(sourceExample)');
for(const label of ['17.xlsx','排程会议 0813','第 12 行','2025-08-01 → 2025-08-03','日历间隔：2 天','单元格：G12 → K12'])assert(renderedExample.includes(label));
assert(!/source_id|internal-id|key_basis|internal-field|date_trusted/.test(renderedExample));
context.sourceExample.is_historical_fallback=true;context.sourceExample.latest_snapshot_date='2026-08-13';
assert(run('flowSourceExample(sourceExample)').includes('历史计划 · 非最新计划（最新快照 2026-08-13）'));
assert(!/\b(fetch|api|executionRequest)\s*\(/.test(source));
const exported=plain(run('flowExportDraft(emptyDraft)'));
assert.equal(exported.kind,'forecast_draft');assert.equal(exported.unit,'calendar_elapsed_days');assert.equal(exported.estimate.total_days,null);
assert(exported.nodes.every(n=>n.duration_source==='unknown'));

// Delegated controls operate only on their local draft and immediately recompute cycle errors.
run('var refreshed=[];flowRefresh=(draft,focus)=>refreshed.push({key:draft.key,focus})');
function change(dataset,value='',checked=false,key='qa-empty'){
  handlers.change({target:{dataset,value,checked,closest:()=>({dataset:{flowKey:key}})}});
}
change({flowField:'days',node:'technical'},'2');assert.equal(run('emptyDraft.nodes[0].days'),2);assert(run('emptyDraft.nodes[0].manual'));
handlers.input({target:{dataset:{flowField:'days',node:'technical'},value:'3',closest:()=>({dataset:{flowKey:'qa-empty'}})}});assert.equal(run('emptyDraft.nodes[0].days'),3);
change({flowField:'days',node:'technical'},'');assert.equal(run('emptyDraft.nodes[0].days'),null);
change({flowField:'start_date'},'2026-09-11');assert.equal(run('emptyDraft.start_date'),'2026-09-11');assert(run('emptyDraft.manualStart'));
change({flowPredecessor:'wood',node:'technical'},'',true);assert(!run('flowEstimate(emptyDraft.nodes).valid'));
change({flowPredecessor:'wood',node:'technical'},'',false);assert(run('flowEstimate(emptyDraft.nodes).valid'));
change({flowOption:'metalPaint'},'',true);assert(run('emptyDraft.options.metalPaint'));
const click=(action,node)=>handlers.click({target:{closest:()=>({dataset:{action,node},disabled:false,closest:()=>({dataset:{flowKey:'qa-empty'}})})}});
click('flow-select','wood');assert.equal(run('emptyDraft.selected'),'wood');
click('flow-reset-route');assert(run('flowEstimate(emptyDraft.nodes).valid'));
assert(run('refreshed.length')>=8);
console.log('PASS: flow CPM longest path, no photography stage, unknown/zero safety, date math, cycle/self validation, route toggles, source-backed estimates, isolated local drafts, HTML escaping and delegated editing.');
