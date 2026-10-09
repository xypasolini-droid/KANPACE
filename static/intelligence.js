'use strict';

// Contextual tools use registered project sources and local, durable job records.
const KanpaceIntelligence = (() => {
  let dialog, context=null, token=0, timer=null, trigger=null, evidenceDraft=null;
  const labels={queued:'等待处理',running:'正在本机处理',completed:'处理完成',failed:'处理失败'};
  const can=(p)=>typeof accessCan!=='function'||accessCan(p);
  const e=(s)=>esc(s??'');
  function reset(){token++;clearTimeout(timer);timer=null;context=null;evidenceDraft=null;if(dialog?.open)dialog.close();}
  function surface(title,body){
    if(!dialog){dialog=document.createElement('dialog');dialog.id='intel-dialog';dialog.setAttribute('aria-labelledby','intel-title');document.body.append(dialog);
      dialog.addEventListener('close',()=>{token++;clearTimeout(timer);if(trigger?.isConnected)trigger.focus();});}
    dialog.innerHTML=`<div class="dialog-head"><h2 id="intel-title">${e(title)}</h2><button type="button" class="icon-button" data-intel="close" aria-label="关闭">${icon('close')}</button></div><div class="dialog-body intel-body">${body}</div>`;
    if(!dialog.open)dialog.showModal();
  }
  function valid(t,pid){return token===t&&context?.pid===pid&&currentProject()?.id===pid&&dialog?.open;}
  function alert(message){message=String(message||'').replace(/\n\{[\s\S]*$/,'');const el=dialog?.querySelector('#intel-feedback');if(el){el.textContent=message;el.hidden=!message;}}
  function engineeringButtons(d){
    if(d?.superseded||d?.purpose==='render')return '';
    const cad=/\.(step|stp)$/i.test(d?.filename||''),ocr=/\.(pdf|png|jpe?g|webp|tiff?|bmp)$/i.test(d?.filename||'');
    return cad||ocr?`<button class="btn" data-intel="engineering" data-source="doc:${e(d.id)}" data-kind="${cad?'cad':'ocr'}">${cad?'核对模型':'识别图纸'}</button>`:'';
  }
  function launcher(){return `<button class="btn" data-intel="engineering">识别图纸 / 核对模型</button>`;}
  function packingButton(){return can('costs')?'<button class="btn full" data-intel="packing">板材排料</button>':'';}
  async function openEngineering(source='',kind='ocr'){
    const project=currentProject();if(!project)return;
    const t=++token,pid=project.id;clearTimeout(timer);
    context={pid,revision:project.revision,type:'engineering',sources:[],jobs:[],selected:new Set(),candidateLimit:30};
    surface('图纸识别与模型核对','<p role="status">正在读取本项目资料…</p>');
    try{const data=await api(`/api/projects/${encodeURIComponent(pid)}/engineering`);if(!valid(t,pid))return;
      Object.assign(context,data);context.kind=kind;context.source=source;
      renderEngineering();return t;
    }catch(err){if(valid(t,pid))surface('图纸识别与模型核对',`<p role="alert">${e(err.message)}</p><button class="btn" data-intel="engineering">重新读取</button>`);}
  }
  async function openEvidence(b){
    const part=parts().find(p=>p.id===b.dataset.id),jobId=b.dataset.job;
    if(!part||part.project_id!==currentProject()?.id)return;
    const ticket=await openEngineering();if(ticket!==token)return;
    await loadJob(jobId);if(ticket!==token||context?.job?.id!==jobId)return;
    const entries=part.source?.entries||[];
    for(const page of context.job.result?.pages||[])page.regions.forEach((r,i)=>{if(entries.some(e=>e.page===page.page&&e.text===r.text&&JSON.stringify(e.bbox)===JSON.stringify(r.bbox)))context.selected.add(`${page.page}:${i}`);});
    renderJob();
  }
  function renderEngineering(){
    const {sources,jobs,kind,source}=context;
    const selected=sources.find(s=>s.id===source)||sources.find(s=>s.kind===kind)||sources[0];
    context.source=selected?.id;
    surface('图纸识别与模型核对',`<p class="intel-lead">${e(currentProject()?.name)} · 选择资料，在原图旁核对结果。</p>
      ${sources.length?`<form id="intel-engineering-form" class="intel-form"><label class="field">本项目资料<select name="source_id">${sources.map(s=>`<option value="${e(s.id)}" ${s.id===selected?.id?'selected':''}>${s.kind==='cad'?'模型':'图纸'} · ${e(s.display_name||s.filename)}</option>`).join('')}</select></label><label class="field intel-pages">PDF 页码<input name="pages" value="1" inputmode="numeric" pattern="[0-9,， ]+" placeholder="例如 1,2,3"><small>一次最多 12 页；图片直接识别整张。</small></label><button class="btn primary" type="submit" ${!can('engineering')||projectIsClosed(currentProject())?'disabled':''}>${selected?.kind==='cad'?'核对工程模型':'开始识别'}</button></form>`:'<div class="intel-empty">本项目尚无可识别的施工图或 STEP 模型。请在“上传资料”中添加文件。</div>'}
      <p id="intel-feedback" class="intel-feedback" role="alert" hidden></p>
      <div class="intel-job-head"><h3>处理记录</h3><button class="link-button" data-intel="engineering">刷新记录</button></div>
      <div class="intel-jobs">${jobs.length?jobs.map(j=>`<button class="intel-job" data-intel="job" data-id="${e(j.id)}"><span><strong>${j.kind==='cad'?'模型核对':'图纸识别'} · ${e(j.metadata?.source_label||j.source?.filename)}</strong><small>${e(j.created_at?.replace('T',' ').slice(0,16))}${j.metadata?.source_page?' · 原图第 '+e(j.metadata.source_page)+' 页':''}</small></span><span>${labels[j.status]||e(j.status)}</span></button>`).join(''):'<p class="muted">还没有处理记录。</p>'}</div><div id="intel-result"></div>`);
    sourceChanged();
  }
  function sourceChanged(){const select=dialog.querySelector('[name="source_id"]');if(!select)return;
    const source=context.sources.find(s=>s.id===select.value);context.source=source?.id;
    dialog.querySelector('.intel-pages').hidden=!/\.pdf$/i.test(source?.filename||'');
    dialog.querySelector('#intel-engineering-form button[type="submit"]').textContent=source?.kind==='cad'?'核对工程模型':'开始识别';}
  async function submitEngineering(form){
    if(context.busy||!form.reportValidity())return;
    const s=context.sources.find(s=>s.id===form.elements.source_id.value);if(!s)return;
    let options={};if(/\.pdf$/i.test(s.filename)){
      const raw=form.elements.pages.value.trim();if(!/^[0-9]+(?:\s*[,，]\s*[0-9]+)*$/.test(raw)){alert('页码请按 1,2,3 填写。');return;}
      options={pages:raw.split(/[,，]/).map(Number)};
    }
    const t=token,pid=context.pid,request=context.jobRequest=(context.jobRequest||0)+1;context.busy=true;const submit=form.querySelector('[type="submit"]');submit.disabled=true;alert('');
    try{const r=await api(`/api/projects/${encodeURIComponent(pid)}/engineering`,{source_id:s.id,kind:s.kind,options,expected_revision:context.revision});if(!valid(t,pid)||context.jobRequest!==request)return;
      context.jobs.unshift(r.job);context.job=r.job;context.selected.clear();renderJob();poll(r.job.id,t,pid,request);
    }catch(err){if(valid(t,pid)&&context.jobRequest===request)alert(err.message);}finally{if(valid(t,pid)){context.busy=false;submit.disabled=false;}}
  }
  async function loadJob(id){const t=token,pid=context.pid,request=context.jobRequest=(context.jobRequest||0)+1;clearTimeout(timer);alert('');context.job=null;context.proposalJobId=null;context.cadProposals=null;context.drawingMatchJobId=null;context.drawingMatches=null;context.drawingMatchMap=null;context.candidateLimit=30;dialog.querySelector('#intel-result').innerHTML='<p role="status">正在读取所选记录…</p>';
    try{const r=await api(`/api/projects/${encodeURIComponent(pid)}/engineering/${encodeURIComponent(id)}`);if(!valid(t,pid)||context.jobRequest!==request)return;context.job=r.job;context.selected.clear();context.page=0;renderJob();if(['queued','running'].includes(r.job.status))poll(id,t,pid,request);
    }catch(err){if(valid(t,pid)&&context.jobRequest===request)alert(err.message);}}
  function poll(id,t,pid,request){clearTimeout(timer);timer=setTimeout(async()=>{if(!valid(t,pid))return;
    try{const r=await api(`/api/projects/${encodeURIComponent(pid)}/engineering/${encodeURIComponent(id)}`);if(!valid(t,pid)||context.jobRequest!==request||context.job?.id!==id)return;context.job=r.job;renderJob();if(['queued','running'].includes(r.job.status))poll(id,t,pid,request);
    }catch(err){if(valid(t,pid)&&context.jobRequest===request&&context.job?.id===id)alert('读取处理进度失败：'+err.message+'。可从处理记录重新打开。');}
  },1500);}
  function renderJob(){
    const host=dialog.querySelector('#intel-result'),j=context.job;if(!host||!j)return;
    const jobIndex=context.jobs.findIndex(v=>v.id===j.id);if(jobIndex>=0)context.jobs[jobIndex]=j;else context.jobs.unshift(j);
    const list=dialog.querySelector('.intel-jobs');if(list)list.innerHTML=context.jobs.map(v=>`<button class="intel-job" data-intel="job" data-id="${e(v.id)}"><span><strong>${v.kind==='cad'?'模型核对':'图纸识别'} · ${e(v.metadata?.source_label||v.source?.filename)}</strong><small>${e(v.created_at?.replace('T',' ').slice(0,16))}${v.metadata?.source_page?' · 原图第 '+e(v.metadata.source_page)+' 页':''}</small></span><span>${labels[v.status]||e(v.status)}</span></button>`).join('');
    const title=e(j.metadata?.source_label||j.source?.filename);
    if(j.status!=='completed'){
      host.innerHTML=`<section class="intel-work-state" role="status"><h3>${labels[j.status]||e(j.status)}</h3><p>${title}</p><p>${j.status==='failed'?e(j.error?.message||'请重试'):j.progress?.total?`已处理 ${e(j.progress.completed)} / ${e(j.progress.total)} 页`:'正在本地计算，可以关闭窗口，稍后从处理记录查看。'}</p></section>`;return;
    }
    host.innerHTML=`<div class="intel-result-heading"><h3>${j.kind==='cad'?'工程模型核对':'原图与识别文字'}</h3><span>${title}</span></div>${j.kind==='ocr'?ocrView(j):cadView(j)}`;
  }
  function ocrView(j){
    const ps=j.result?.pages||[],idx=Math.min(context.page||0,ps.length-1),p=ps[idx];if(!p)return '<p>未提取到页面。</p>';context.page=idx;
    const url=`/api/projects/${encodeURIComponent(context.pid)}/engineering/${encodeURIComponent(j.id)}/pages/${p.page}`;
    const selected=p.regions.filter((_,i)=>context.selected.has(`${p.page}:${i}`));
    return `<p class="intel-note">选中原文可定位原图，并带入构件复核。识别结果尚未审核。</p><div class="intel-ocr-toolbar"><label>当前页 <select id="intel-page">${ps.map((a,i)=>`<option value="${i}" ${i===idx?'selected':''}>第 ${e(a.source_page||a.page)} 页</option>`).join('')}</select></label><a class="btn" target="_blank" rel="noopener" href="${url}">放大原图</a><button class="btn primary" data-intel="draft-part" ${!context.selected.size||!can('engineering')||projectIsClosed(currentProject())?'disabled':''}>用选中文字建构件（${context.selected.size}）</button></div>
      <div class="intel-ocr-grid"><div class="intel-page-image"><img src="${url}" alt="${e(j.metadata?.source_label||j.source.filename)} 原图第 ${e(p.source_page||p.page)} 页"><svg viewBox="0 0 ${Number(p.width)||1} ${Number(p.height)||1}" aria-hidden="true">${selected.map(r=>`<rect x="${Number(r.bbox[0])}" y="${Number(r.bbox[1])}" width="${Number(r.bbox[2]-r.bbox[0])}" height="${Number(r.bbox[3]-r.bbox[1])}"/>`).join('')}</svg></div>
      <fieldset class="intel-regions"><legend>识别文字 · ${p.regions.length} 处</legend>${p.regions.length?p.regions.map((r,i)=>`<label class="intel-region"><input type="checkbox" data-region="${p.page}:${i}" ${context.selected.has(`${p.page}:${i}`)?'checked':''}><span>${e(r.text)}<small>识别置信度 ${Number.isFinite(r.score)?Math.round(r.score*100)+'%':'待核对'}</small></span></label>`).join(''):'<p>没有识别到文字，请尝试更清晰的施工图。</p>'}</fieldset></div>`;
  }
  function cadArea(value){return !Number.isFinite(value)?'待核对':value>0&&value<1e6?num(value)+' mm²':num(value/1e6)+' m²';}
  function cadSize(values){return Array.isArray(values)&&values.length===3&&values.every(v=>Number.isFinite(v))?values.map(v=>num(v)).join(' × ')+' mm':'待核对';}
  function assemblyContextView(proposal){
    const contexts=Array.isArray(proposal.assembly_contexts)?proposal.assembly_contexts:[];
    const parents=new Map();let unresolved=0;
    for(const row of contexts){
      const parent=row?.nearest_parent;
      if(!parent||typeof parent.instance_path!=='string'||!parent.instance_path){unresolved++;continue;}
      const known=parents.get(parent.instance_path)||{path:parent.instance_path,name:parent.name||'',count:0};
      known.count++;parents.set(parent.instance_path,known);
    }
    if(!parents.size)return '<p class="intel-cad-assembly-muted">直接上级装配：模型未提供可核对的父级记录。</p>';
    const entries=[...parents.values()];
    const label=entry=>`${entry.name?`<strong>${e(entry.name)}</strong> · `:''}<code>${e(entry.path)}</code>${entries.length>1?`（${entry.count} 个实例）`:''}`;
    const missing=unresolved?`<p class="intel-cad-assembly-muted">另有 ${unresolved} 个实例缺少直接父装配记录，请对照原模型核对。</p>`:'';
    if(entries.length===1)return `<p class="intel-cad-assembly">直接上级装配：${label(entries[0])}</p>${missing}`;
    return `<div class="intel-cad-assembly-multiple"><p class="intel-cad-warning">涉及多个柜组/装配，请核对归属。</p><ul>${entries.slice(0,6).map(entry=>`<li>${label(entry)}</li>`).join('')}</ul>${entries.length>6?`<p>另有 ${entries.length-6} 个直接父装配路径。</p>`:''}</div>${missing}`;
  }
  function drawingImageUrl(proof){
    const page=Number(proof?.page);
    if(!proof?.job_id||!Number.isInteger(page)||page<1)return '';
    return `/api/projects/${encodeURIComponent(context.pid)}/engineering/${encodeURIComponent(proof.job_id)}/pages/${page}`;
  }
  function drawingRegionOverlay(proof){
    const box=proof?.bbox,width=Number(proof?.page_width),height=Number(proof?.page_height);
    if(!Array.isArray(box)||box.length!==4||!Number.isFinite(width)||!Number.isFinite(height)||width<=0||height<=0||!box.every(Number.isFinite))return '';
    const [x1,y1,x2,y2]=box;if(x1<0||y1<0||x2<=x1||y2<=y1||x2>width||y2>height)return '';
    return `<svg viewBox="0 0 ${width} ${height}" aria-hidden="true"><rect x="${x1}" y="${y1}" width="${x2-x1}" height="${y2-y1}"/></svg>`;
  }
  function drawingEvidenceItem(proof,kind='candidate'){
    const url=drawingImageUrl(proof),page=proof.source_page||proof.page||'待核',source=proof.source_file||'图纸来源待核';
    const raw=(proof.dimension_candidates||[]).map(item=>item.raw).filter(Boolean);
    const location=Array.isArray(proof.bbox)&&proof.bbox.length===4&&proof.bbox.every(Number.isFinite)?`图中文字位置 ${proof.bbox.map(value=>Math.round(value)).join(' / ')}`:'位置待核';
    return `<article class="intel-match-evidence ${kind==='conflict'?'intel-match-evidence-conflict':''}">
      ${url?`<a class="intel-match-image" href="${url}" target="_blank" rel="noopener" aria-label="放大原图：${e(source)}第 ${e(page)} 页"><img src="${url}" alt="${e(source)}第 ${e(page)} 页图纸" loading="lazy" width="160" height="120">${drawingRegionOverlay(proof)}</a>`:''}
      <div class="intel-match-copy"><p class="intel-match-source">${e(source)} · 第 ${e(page)} 页</p><p class="intel-match-text">${e(proof.text||'未保留识别原文')}</p><p class="intel-match-location">${e(location)}${Number.isFinite(proof.score)?` · OCR ${Math.round(proof.score*100)}%`:''}</p>
      ${raw.length?`<p class="intel-match-dimensions">图纸尺寸候选：${raw.slice(0,3).map(e).join('；')}${raw.length>3?'…':''} <small>未填入生产尺寸</small></p>`:''}
      ${url?`<a class="intel-match-open" href="${url}" target="_blank" rel="noopener">放大原图</a>`:''}</div></article>`;
  }
  function drawingMatchSummaryView(){
    const state=context.drawingMatchState;
    if(state==='loading')return '<div class="intel-match-summary" role="status">正在关联施工图文字…</div>';
    if(state==='error')return `<div class="intel-match-summary" role="alert"><p>图纸证据暂未读到：${e(context.drawingMatchError||'请重试')}</p><button type="button" class="btn" data-intel="drawing-match-retry">重新关联</button></div>`;
    if(!context.drawingMatches?.ocr_job_count){const excluded=(context.drawingMatches?.excluded_stale_ocr_job_count||0)+(context.drawingMatches?.excluded_unbound_ocr_job_count||0);
      return state==='ready'?`<div class="intel-match-summary"><p>${excluded?'没有可比对的当前施工图识别记录；旧版或来源未绑定的记录已排除。':'还没有施工图识别记录。'}请先选择当前施工图“开始识别”，再返回模型核对。</p></div>`:'';}
    return '';
  }
  function drawingMatchView(proposal){
    if(context.drawingMatchState!=='ready'||!context.drawingMatches?.ocr_job_count)return '';
    const match=context.drawingMatchMap?.get(proposal.id)||context.drawingMatches.matches?.find(item=>item.proposal_id===proposal.id);
    const proof=match?.drawing_evidence||[],conflicts=match?.conflicting_drawing_evidence||[];
    const status={matched:'找到疑似对应图纸',conflict:'图纸信息有冲突',ambiguous:'多处图纸可能对应',unmatched:'未找到对应标注',generic_name:'模型名称过泛'}[match?.match_status]||'需核对图纸';
    const signal=match?.match_status==='conflict'?'conflict':match?.match_status==='matched'?'matched':'review';
    return `<section class="intel-matches" aria-label="施工图核对"><div class="intel-match-heading"><strong>施工图核对</strong><span class="intel-match-status intel-match-status-${signal}">${status}</span></div>
      ${proof.slice(0,2).map(item=>drawingEvidenceItem(item)).join('')}${proof.length>2?`<details class="intel-match-more"><summary>另有 ${proof.length-2} 处图纸线索</summary>${proof.slice(2).map(item=>drawingEvidenceItem(item)).join('')}</details>`:''}
      ${conflicts.length?`<div class="intel-match-conflicts"><strong>冲突标注 · ${conflicts.length} 处</strong>${conflicts.slice(0,2).map(item=>drawingEvidenceItem(item,'conflict')).join('')}${conflicts.length>2?`<details class="intel-match-more"><summary>另有 ${conflicts.length-2} 处冲突</summary>${conflicts.slice(2).map(item=>drawingEvidenceItem(item,'conflict')).join('')}</details>`:''}</div>`:''}
      ${(match?.issues||[]).length?`<ul class="intel-match-issues">${match.issues.map(issue=>`<li>${e(issue)}</li>`).join('')}</ul>`:''}
      <p class="intel-match-disclaimer">以上为 OCR 关联线索，尺寸和材料仍须按原图人工确认。</p></section>`;
  }
  async function loadDrawingMatches(id,t,pid,jobRequest){
    const request=context.drawingMatchRequest=(context.drawingMatchRequest||0)+1;
    try{const data=await api(`/api/projects/${encodeURIComponent(pid)}/engineering/${encodeURIComponent(id)}/drawing-matches`);
      if(!valid(t,pid)||context.job?.id!==id||context.jobRequest!==jobRequest||context.drawingMatchRequest!==request)return;
      if(data.project_id!==pid||data.cad_job_id!==id||data.cad_source_sha256!==context.job.source?.sha256||data.status!=='evidence_only'||data.manufacturing_release!==false||!Array.isArray(data.matches))throw new Error('图纸证据与当前工程模型不一致');
      context.drawingMatches=data;context.drawingMatchMap=new Map(data.matches.map(item=>[item.proposal_id,item]));context.drawingMatchState='ready';renderJob();
    }catch(err){if(valid(t,pid)&&context.job?.id===id&&context.jobRequest===jobRequest&&context.drawingMatchRequest===request){context.drawingMatchError=err.message;context.drawingMatchState='error';renderJob();}}
  }
  function cadView(j){
    const r=j.result||{};
    if(context.proposalJobId!==j.id){
      context.proposalJobId=j.id;context.proposalState='loading';context.cadProposals=null;context.candidateLimit=30;
      void loadCadProposals(j.id,token,context.pid,context.jobRequest);
    }
    const state=context.proposalState,snapshot=context.cadProposals;
    if(state==='ready'&&context.drawingMatchJobId!==j.id){context.drawingMatchJobId=j.id;context.drawingMatchState='loading';context.drawingMatches=null;context.drawingMatchMap=null;void loadDrawingMatches(j.id,token,context.pid,context.jobRequest);}
    const proposals=snapshot?.proposals||[],visible=proposals.slice(0,context.candidateLimit||30);
    const sourceUnits=Array.isArray(snapshot?.source_length_units)?snapshot.source_length_units:[];
    const sourceUnitLabel=state==='ready'?(snapshot.units_confirmed===true&&sourceUnits.length===1?`源单位 ${sourceUnits[0]}（已识别）`:`源单位未明确${sourceUnits.length?`（已识别 ${sourceUnits.join('、')}，仍需核对）`:''}`):'源单位核对中';
    const unitWarning=state==='ready'&&snapshot.units_confirmed!==true?'<p class="intel-cad-unit-alert" role="alert">源单位未明确，几何尺寸仅参考，按施工图填加工尺寸。</p>':'';
    const content=state==='loading'?'<p class="intel-cad-state" role="status">正在按模型定义和实例名称整理候选…</p>':
      state==='error'?`<div class="intel-cad-state" role="alert"><p>${e(context.proposalError||'候选读取失败')}</p><button type="button" class="btn" data-intel="cad-retry">重新读取</button></div>`:
      `<div class="intel-cad-result-head"><h4>待核对构件 · ${proposals.length} 组</h4><p>实例数仅是建议数量；订单数量、材料和加工尺寸由技术员核对后填写。</p></div>
       ${drawingMatchSummaryView()}${proposals.length?`<ol class="intel-cad-candidates">${visible.map(p=>`<li class="intel-cad-candidate"><div class="intel-cad-candidate-main"><div><h5>${e(p.name||'未命名模型实例')}</h5><p>定义 ${e(p.definition_id)}</p></div><span class="intel-cad-count">模型中 ${e(p.suggested_quantity)} 个实例</span></div><dl><div><dt>世界轴向外包参考</dt><dd>${e(cadSize(p.bbox_extents_mm_sample))}</dd></div>${p.oriented_bbox_extents_mm_sample?`<div><dt>定向外包参考（短/中/长）</dt><dd>${e(cadSize(p.oriented_bbox_extents_mm_sample))}</dd></div>`:''}<div><dt>几何状态</dt><dd class="${p.geometry_valid?'intel-cad-valid':'intel-cad-warning'}">${p.geometry_valid?'实体有效':'需检查实体'}</dd></div></dl>${p.bbox_extents_mm_samples?.length>1?'<p class="intel-cad-warning">同组轴向外包不同，可能存在旋转或变体</p>':''}${p.oriented_bbox_extents_mm_samples?.length>1?'<p class="intel-cad-warning">同组定向外包不同，需核对变体</p>':''}${p.geometry_form_candidate_count>0?`<p class="intel-cad-form-hint">${e(p.geometry_form_candidate_count)} 个实例呈薄板形态，仅供几何核对；不能据此确定板材、工艺或加工尺寸。</p>`:''}${drawingMatchView(p)}<details><summary>核对提示、装配归属与实例位置</summary>${assemblyContextView(p)}<ul>${(p.issues||[]).map(issue=>`<li>${e(issue)}</li>`).join('')}</ul><p>${(p.instance_paths||[]).slice(0,8).map(path=>e(path)).join('；')}${p.instance_paths?.length>8?'；其余见模型记录':''}</p></details><button type="button" class="btn primary" data-intel="cad-proposal" data-id="${e(p.id)}" ${!can('engineering')||projectIsClosed(currentProject())?'disabled':''}>核对并建构件</button></li>`).join('')}</ol>${proposals.length>visible.length?`<button type="button" class="btn intel-cad-more" data-intel="cad-more">继续显示（还剩 ${proposals.length-visible.length} 组）</button>`:''}`:'<p class="intel-cad-state">模型中没有可供核对的构件组。</p>'}
       ${(snapshot?.warnings||[]).map(w=>`<p class="intel-note">${e(w)}</p>`).join('')}`;
    return `<p class="intel-cad-source">STEP 工程模型 · ${e(j.metadata?.source_label||j.source?.filename||'来源待核')} · 计算输出 ${e(r.output_length_unit||'单位待核')} · ${e(sourceUnitLabel)}</p>${unitWarning}<div class="intel-metrics"><span>装配实例 <strong>${e(r.instance_count)}</strong></span><span>独立定义 <strong>${e(r.unique_definition_count)}</strong></span><span>表面积 <strong>${cadArea(r.totals?.surface_area_mm2)}</strong></span></div><p class="intel-note">轴向与定向外包只用于模型核对，不是加工或下料尺寸。</p>${content}${(r.warnings||[]).map(w=>`<p class="intel-note">${e(w)}</p>`).join('')}`;
  }
  async function loadCadProposals(id,t,pid,jobRequest){
    const request=context.proposalRequest=(context.proposalRequest||0)+1;
    try{const data=await api(`/api/projects/${encodeURIComponent(pid)}/engineering/${encodeURIComponent(id)}/proposals`);
      if(!valid(t,pid)||context.job?.id!==id||context.jobRequest!==jobRequest||context.proposalRequest!==request)return;
      if(data.project_id!==pid||data.job_id!==id||data.source_sha256!==context.job.source?.sha256||data.manufacturing_release!==false||!Array.isArray(data.proposals))throw new Error('候选与当前模型来源不一致，请重新核对');
      context.cadProposals=data;context.proposalState='ready';renderJob();
    }catch(err){if(valid(t,pid)&&context.job?.id===id&&context.jobRequest===jobRequest&&context.proposalRequest===request){context.proposalError=err.message;context.proposalState='error';renderJob();}}
  }
  function draftPart(){const j=context.job,pid=context.pid;let refs,notes,name='';
    if(j.kind!=='ocr')return;
    const regions=[...context.selected].map(s=>{const [page,index]=s.split(':').map(Number);return {page,index};});
    if(!regions.length||regions.length>30){alert('请选 1—30 处原文。');return;}
    refs={job_id:j.id,regions};notes=regions.map(r=>{const p=j.result.pages.find(p=>p.page===r.page);return `第 ${p.source_page||p.page} 页：${p.regions[r.index].text}`;}).join('\n');
    dialog.close();partModal('',true);evidenceDraft={pid,revision:currentProject().revision,refs};
    const form=document.querySelector('#part-form');form.dataset.intelligence='true';form.elements.name.value=name;form.elements.quantity.value='';form.elements.notes.value=notes;
    document.querySelector('#modal .dialog-head h2').textContent='依据识别结果建立构件';
    form.insertAdjacentHTML('beforebegin','<p class="intel-note">填写已核对的名称、材质、尺寸与数量。原图位置和模型实例会随构件保存。</p>');
    document.querySelectorAll('#modal [data-action="save-part"]').forEach((b,i)=>{if(i){b.remove();return;}b.removeAttribute('data-action');b.dataset.intel='save-part';b.classList.add('primary');b.textContent='保存待复核构件';});
    form.elements.name.focus();
  }
  function draftCadProposal(id){
    const j=context?.job,pid=context?.pid,snapshot=context?.cadProposals;
    if(!j||j.kind!=='cad'||j.status!=='completed'||snapshot?.job_id!==j.id||snapshot?.source_sha256!==j.source?.sha256||currentProject()?.id!==pid)return;
    const proposal=snapshot.proposals?.find(p=>p.id===id);if(!proposal)return;
    const drawingMatch=context.drawingMatchMap?.get(proposal.id)||context.drawingMatches?.matches?.find(item=>item.proposal_id===proposal.id);
    const firstDrawing=drawingMatch?.drawing_evidence?.[0]||drawingMatch?.conflicting_drawing_evidence?.[0];
    const drawingUrl=firstDrawing?drawingImageUrl(firstDrawing):'';
    const drawingHint=drawingUrl?`<p>${drawingMatch.match_status==='conflict'||drawingMatch.match_status==='ambiguous'?'图纸对应关系有疑问，请先核对：':'施工图线索：'}${e(firstDrawing.source_file||'施工图')} · 第 ${e(firstDrawing.source_page||firstDrawing.page)} 页 · <a href="${drawingUrl}" target="_blank" rel="noopener">放大原图</a>。图纸文字未作为生产参数。</p>`:'';
    const refs={job_id:j.id,proposal_id:proposal.id,part_indices:proposal.instance_indices.slice()};
    dialog.close();partModal('',true);evidenceDraft={pid,revision:currentProject().revision,refs,kind:'cad-proposal'};
    const form=document.querySelector('#part-form');form.dataset.intelligence='true';
    form.elements.name.value=proposal.name||'';
    for(const key of ['quantity','length_mm','width_mm','thickness_mm']){form.elements[key].value='';form.elements[key].required=true;}
    form.elements.material.value='';form.elements.category.value='';form.elements.category.required=true;
    form.elements.notes.value='';
    document.querySelector('#modal .dialog-head h2').textContent='核对模型构件';
    form.insertAdjacentHTML('beforebegin',`<div class="intel-cad-form-note"><strong>${e(proposal.name)}</strong><p>STEP 定义 ${e(proposal.definition_id)} · 模型中 ${e(proposal.suggested_quantity)} 个实例</p><p>轴向外包参考 ${e(cadSize(proposal.bbox_extents_mm_sample))}。${proposal.oriented_bbox_extents_mm_sample?`定向外包参考 ${e(cadSize(proposal.oriented_bbox_extents_mm_sample))}（短/中/长）。`:''}请按订单核数量，按施工图核加工尺寸。</p>${drawingHint}</div>`);
    form.insertAdjacentHTML('beforeend','<fieldset class="intel-cad-confirm span2"><legend>保存前确认</legend><label><input type="checkbox" name="quantity_confirmed" required>订单数量已核对</label><label><input type="checkbox" name="manufacturing_dimensions_confirmed" required>加工尺寸已核对</label></fieldset>');
    document.querySelectorAll('#modal [data-action="save-part"]').forEach((b,i)=>{if(i){b.remove();return;}b.removeAttribute('data-action');b.dataset.intel='save-part';b.classList.add('primary');b.textContent='保存待复核构件';});
    form.elements.name.focus();
  }
  async function savePart(b){const form=document.querySelector('#part-form'),draft=evidenceDraft;const stillEditing=()=>evidenceDraft===draft&&currentProject()?.id===draft?.pid&&document.querySelector('#part-form')===form&&document.querySelector('#modal')?.open;if(!evidenceDraft||!form?.reportValidity())return;
    if(currentProject()?.id!==evidenceDraft.pid){toast('项目已切换，请重新选择依据');return;}
    const values=formValues('#part-form');for(const k of ['length_mm','width_mm','thickness_mm','quantity','unit_price'])if(k in values)values[k]=values[k]===''?null:Number(values[k]);
    if(!can('costs')){delete values.unit_price;delete values.pricing_unit;}
    const refs={...draft.refs};
    if(draft.kind==='cad-proposal'){
      if(!form.elements.quantity_confirmed?.checked||!form.elements.manufacturing_dimensions_confirmed?.checked)return;
      if(!Number.isInteger(values.quantity)||values.quantity<=0||!['length_mm','width_mm','thickness_mm'].every(k=>Number.isFinite(values[k])&&values[k]>0))return;
      refs.quantity_confirmed=true;refs.manufacturing_dimensions_confirmed=true;
    }
    b.disabled=true;try{await api('/api/parts',{...values,project_id:evidenceDraft.pid,expected_revision:evidenceDraft.revision,engineering_evidence:refs});if(!stillEditing())return;evidenceDraft=null;closeModal();await refresh();toast('构件与原图依据已保存，等待复核');}
    catch(err){if(stillEditing()){const error=document.querySelector('#modal .dialog-error');if(error)error.textContent=err.message;}}finally{b.disabled=false;}
  }
  async function openPacking(){const project=currentProject();if(!project)return;const t=++token,pid=project.id;clearTimeout(timer);
    context={type:'packing',pid,revision:project.revision};
    surface('板材排料',`<p class="intel-lead">${e(project.name)} · 同一材质与厚度分组计算。</p><form id="intel-packing-form" class="intel-form intel-packing-form">
      <label class="field">材质<input name="material" required placeholder="例如：18mm 多层板"></label><label class="field">厚度 mm<input name="thickness_mm" type="number" min="0.01" step="0.01" required></label>
      <label class="field">原板宽 mm<input name="stock_width" type="number" min="1" step="0.01" value="1220" required></label><label class="field">原板长 mm<input name="stock_height" type="number" min="1" step="0.01" value="2440" required></label>
      <label class="field">可用原板数<input name="stock_quantity" type="number" min="1" max="500" value="20" required></label><label class="field">每张单价（选填）<input name="cost_per_sheet" type="number" min="0" step="0.01"></label>
      <label class="field">锯缝 mm<input name="kerf_mm" type="number" min="0" step="0.01" value="3" required></label><label class="field">每边裁边 mm<input name="trim_mm" type="number" min="0" step="0.01" value="10" required></label>
      <label class="field">纹理方向<select name="grain"><option value="none">无方向限制，可旋转</option><option value="height">沿板长，不可旋转</option><option value="width">沿板宽，不可旋转</option></select></label><label class="field">原方案用了几张（选填）<input name="baseline_sheet_count" type="number" min="1" step="1"></label>
      <div class="span2"><div class="intel-job-head"><h3>已复核的下料清单</h3><button class="btn" type="button" data-intel="packing-row">添加一行</button></div><p class="intel-note">填写加工后的下料尺寸；成品外形、未展开钣金尺寸不能直接排料。</p><div class="table-wrap"><table class="intel-table"><thead><tr><th>部件名称</th><th>宽 mm</th><th>长 mm</th><th>数量</th><th></th></tr></thead><tbody id="intel-packing-rows">${packingRow()}</tbody></table></div></div>
      <label class="intel-check span2"><input type="checkbox" name="confirmed" required>我已核对下料尺寸、数量、材质、厚度、纹理和裁边要求</label><button class="btn primary" type="submit" ${can('costs')&&!projectIsClosed(project)?'':'disabled'}>计算排料方案</button></form><p id="intel-feedback" class="intel-feedback" role="alert" hidden></p><div id="intel-packing-result"></div><div id="intel-packing-history"></div>`);
    try{const r=await api(`/api/projects/${encodeURIComponent(pid)}/packing`);if(!valid(t,pid))return;context.previews=r.previews||[];
      renderPackingHistory();
    }catch(err){if(valid(t,pid))alert(err.message);}
  }
  function renderPackingHistory(){dialog.querySelector('#intel-packing-history').innerHTML=context.previews.length?`<h3>历史排料方案</h3>${context.previews.slice().reverse().map(p=>`<button class="intel-job" data-intel="packing-history" data-id="${e(p.id)}">${e(p.config.material)} · ${e(p.config.thickness_mm)} mm · ${e(p.created_at.slice(0,16).replace('T',' '))}<span>${p.result.summary.sheet_count} 张</span></button>`).join('')}`:'<p class="muted">还没有排料记录。</p>';}
  function packingRow(){return `<tr><td><input name="label" aria-label="部件名称" placeholder="例如：侧板" required maxlength="100"></td><td><input name="width_mm" aria-label="下料宽 mm" type="number" min="0.01" step="0.01" required></td><td><input name="height_mm" aria-label="下料长 mm" type="number" min="0.01" step="0.01" required></td><td><input name="quantity" aria-label="零件数量" type="number" min="1" max="1000" value="1" required></td><td><button type="button" class="link-button" data-intel="packing-remove">删除</button></td></tr>`;}
  async function submitPacking(form){if(context.busy||!form.reportValidity())return;const f=new FormData(form),pid=context.pid,t=token;
    const items=[...form.querySelectorAll('#intel-packing-rows tr')].map((tr,i)=>{const value=k=>tr.querySelector(`[name="${k}"]`).value;return {id:'cut_'+(i+1),label:value('label'),width_mm:Number(value('width_mm')),height_mm:Number(value('height_mm')),quantity:Number(value('quantity')),allow_rotate:f.get('grain')==='none'};});
    const data={expected_revision:context.revision,dimensions_confirmed:f.get('confirmed')==='on',material:f.get('material'),thickness_mm:Number(f.get('thickness_mm')),grain:f.get('grain'),kerf_mm:Number(f.get('kerf_mm')),trim_mm:Number(f.get('trim_mm')),stock:{width_mm:Number(f.get('stock_width')),height_mm:Number(f.get('stock_height')),quantity:Number(f.get('stock_quantity')),cost_per_sheet:f.get('cost_per_sheet')===''?null:Number(f.get('cost_per_sheet'))},items,time_limit_seconds:5,baseline_sheet_count:f.get('baseline_sheet_count')===''?null:Number(f.get('baseline_sheet_count'))};
    context.busy=true;const b=form.querySelector('[type="submit"]');b.disabled=true;b.textContent='正在计算…';alert('');
    try{const r=await api(`/api/projects/${encodeURIComponent(pid)}/packing`,data);if(!valid(t,pid))return;context.previews=context.previews||[];context.previews.push(r.preview);renderPackingHistory();renderPacking(r.preview);}
    catch(err){if(valid(t,pid))alert(err.message);}finally{if(valid(t,pid)){context.busy=false;b.disabled=false;b.textContent='计算排料方案';}}
  }
  function renderPacking(record){context.packingRecord=record;const r=record.result,s=r.summary,c=r.baseline_comparison||{};
    dialog.querySelector('#intel-packing-result').innerHTML=`<section class="intel-packing-output"><h3>排料方案 · ${s.sheet_count} 张原板</h3><div class="intel-metrics"><span>已排 <strong>${s.placed_quantity} 件</strong></span><span>利用率 <strong>${num(s.utilization_percent)}%</strong></span><span>原板金额 <strong>${s.material_cost==null?'未填单价':money(s.material_cost)}</strong></span></div><p>${c.sheets_saved==null?'填写原方案板数后可对比用料。':`比原方案${c.sheets_saved>=0?'少':'多'}用 ${Math.abs(c.sheets_saved)} 张${c.material_cost_saved==null?'':'，原板金额差 '+money(c.material_cost_saved)}`}</p><p class="intel-note">已校验数量、边界与重叠；加工前按切割顺序复核。求解结果为可行方案，尚未证明最优。</p><div class="intel-layouts">${r.layouts.map((l,i)=>packingSVG(l,i,record.config.stock)).join('')}</div><details><summary>查看零件位置与切割依据</summary><p class="intel-note">零件坐标从原板左下角计算。切割树按毫米导出，记录父子板关系，供工艺人员核对；不直接下发机床。</p><button class="btn" data-intel="packing-certificate">下载切割树 CSV</button><div class="table-wrap"><table class="intel-table"><thead><tr><th>板号</th><th>部件</th><th>左下角 X / Y mm</th><th>宽 × 长 mm</th></tr></thead><tbody>${r.layouts.flatMap((l,i)=>l.pieces.map(p=>`<tr><td>${i+1}</td><td>${e(p.label)}</td><td>${num(p.x_mm)} / ${num(p.y_mm)}</td><td>${num(p.width_mm)} × ${num(p.height_mm)}</td></tr>`)).join('')}</tbody></table></div></details></section>`;
    const result=dialog.querySelector('#intel-packing-result');result.scrollIntoView({block:'start',behavior:'instant'});
  }
  function cutTreeCSV(record){
    const rows=[['板号','节点','父节点','切割层级','X毫米','Y毫米','宽毫米','长毫米','类型','部件']];
    const trim=Number(record.config.trim_mm)||0;
    record.result.layouts.forEach((layout,i)=>layout.cut_nodes.forEach(n=>rows.push([i+1,n.node_id,n.parent_id??'',n.depth,n.x/100+trim,n.y/100+trim,n.width/100,n.height/100,n.parent_id==null?'板内有效区':n.type>=0?'零件':n.type===-3?'剩余板':'切割区',n.parent_id!=null&&n.type>=0?record.config.items[n.type]?.label||'':''])));
    const cell=v=>{let value=String(v??'');if(/^[\s]*[=+@-]/.test(value))value="'"+value;return '"'+value.replaceAll('"','""')+'"';};
    return '\ufeff'+rows.map(row=>row.map(cell).join(',')).join('\r\n');
  }
  function packingSVG(layout,index,stock){const w=Number(stock.width_mm),h=Number(stock.height_mm);return `<figure><figcaption>第 ${index+1} 张 · ${w} × ${h} mm</figcaption><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="第 ${index+1} 张原板排料，${layout.pieces.length} 件"><rect width="${w}" height="${h}" fill="#f1f4f6" stroke="#778894" stroke-width="3"/>${layout.pieces.map((p,i)=>`<g><rect x="${p.x_mm}" y="${h-p.y_mm-p.height_mm}" width="${p.width_mm}" height="${p.height_mm}" fill="${['#DBE8FF','#DDF0E6','#F9E7C9','#E9E3F7'][i%4]}" stroke="#385776" stroke-width="2"/><text x="${p.x_mm+p.width_mm/2}" y="${h-p.y_mm-p.height_mm/2}" text-anchor="middle" dominant-baseline="middle" font-size="${Math.min(w/25,p.width_mm/Math.max(4,[...p.label].length),p.height_mm/4)}" fill="#163345">${e(p.label)}</text></g>`).join('')}</svg></figure>`;}
  document.addEventListener('submit',event=>{if(event.target.id==='intel-engineering-form'){event.preventDefault();submitEngineering(event.target);}if(event.target.id==='intel-packing-form'){event.preventDefault();submitPacking(event.target);}});
  document.addEventListener('change',event=>{if(!dialog?.open||!context)return;if(event.target.name==='source_id')sourceChanged();if(event.target.id==='intel-page'){context.page=Number(event.target.value);renderJob();}if(event.target.dataset.region){const key=event.target.dataset.region;if(event.target.checked)context.selected.add(key);else context.selected.delete(key);const scroll=dialog.querySelector('.intel-regions')?.scrollTop||0;renderJob();const list=dialog.querySelector('.intel-regions');if(list)list.scrollTop=scroll;dialog.querySelector(`[data-region="${key}"]`)?.focus({preventScroll:true});}});
  document.addEventListener('click',event=>{const b=event.target.closest('[data-intel]');if(!b||b.disabled)return;const a=b.dataset.intel;
    if(['engineering','packing','evidence'].includes(a)&&!dialog?.contains(b))trigger=b;
    if(a==='close')return dialog.close();if(a==='engineering')return openEngineering(b.dataset.source,b.dataset.kind);if(a==='job')return loadJob(b.dataset.id);
    if(a==='evidence')return openEvidence(b);if(a==='draft-part')return draftPart();if(a==='cad-proposal')return draftCadProposal(b.dataset.id);if(a==='save-part')return savePart(b);
    if(a==='cad-more'&&context?.cadProposals){context.candidateLimit+=30;return renderJob();}
    if(a==='cad-retry'&&context?.job?.kind==='cad'){context.proposalState='loading';renderJob();return loadCadProposals(context.job.id,token,context.pid,context.jobRequest);}
    if(a==='drawing-match-retry'&&context?.job?.kind==='cad'){context.drawingMatchState='loading';renderJob();return loadDrawingMatches(context.job.id,token,context.pid,context.jobRequest);}
    if(a==='packing')return openPacking();if(a==='packing-row')return dialog.querySelector('#intel-packing-rows').insertAdjacentHTML('beforeend',packingRow());
    if(a==='packing-remove'){if(dialog.querySelectorAll('#intel-packing-rows tr').length>1)b.closest('tr').remove();else alert('至少保留一项下料零件。');}
    if(a==='packing-certificate'){const record=context.packingRecord;if(!record?.result?.certificate_csv)return;const url=URL.createObjectURL(new Blob([cutTreeCSV(record)],{type:'text/csv;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download='KANPACE-'+record.id+'-cut-tree-mm.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
    if(a==='packing-history'){const record=context.previews?.find(p=>p.id===b.dataset.id);if(record)renderPacking(record);}
  });
  window.addEventListener('hashchange',()=>{if(context&&currentProject()?.id!==context.pid)reset();});
  return {engineeringButtons,launcher,packingButton,reset,openEngineering};
})();
window.KanpaceIntelligence=KanpaceIntelligence;
