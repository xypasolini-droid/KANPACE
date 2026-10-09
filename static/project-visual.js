'use strict';
// Project appearance and engineering evidence are separate, scoped collections.
const projectVisualSelection=new Map(),projectVisualMode=new Map();
let projectModelChoiceContext=null;
function projectVisualData(project=currentProject()){
  const data=draftMediaCache.get(project?.id)?.data;
  return data&&(!data.project_id||data.project_id===project?.id)?data:null;
}
function projectVisualEntries(project=currentProject(),includeCabinet=false){
  const entries=draftMediaUnique((projectVisualData(project)?.renders||[]).filter(entry=>{
    if(!['空间效果图','柜体效果图','效果图'].includes(entry.kind)||!draftMediaURL(entry.url))return false;
    if(entry.project_id&&entry.project_id!==project?.id)return false;
    const document=entry.document_id&&state.documents.find(doc=>doc.id===entry.document_id);
    if(document&&(document.superseded||document.archived||document.demo))return false;
    return !document||document.project_id===project?.id&&(document.purpose==='render'||entry.source_role==='order_cell_image'&&/\.xlsx$/i.test(document.filename||'')||entry.source_role==='overview_pdf_page'&&entry.document_sha256===document.sha256&&/\.pdf$/i.test(document.filename||''));
  }));
  return includeCabinet?entries:entries.filter(entry=>!projectVisualIsCabinet(entry));
}
function projectVisualIsCabinet(entry){return entry.source_role==='order_cell_image'||entry.kind==='柜体效果图'||['cabinet','part','component'].includes(entry.scope);}
function projectVisualPanorama(project=currentProject()){const url=project?.overview_panorama||'';return /^https:\/\/vr\.3d66\.com\/vr\/index_detail_\d+\.html$/.test(url)?url:'';}
function projectVisualCardImage(project){
  const entry=projectVisualEntries(project)[0];
  const doc=(state.documents||[]).filter(item=>item.project_id===project.id&&item.purpose==='render'&&item.render_scope!=='cabinet'&&!item.archived&&!item.superseded&&!item.demo&&/\.(png|jpe?g|webp)$/i.test(item.filename||'')).at(-1);
  const saved=project.overview_cover,source=saved&&state.documents.find(d=>d.id===saved.document_id&&d.project_id===project.id&&!d.superseded&&!d.archived&&!d.demo&&(!saved.document_sha256||saved.document_sha256===d.sha256));
  const cover=source?saved:null;
  const url=cover?draftMediaURL(cover.thumb_url||cover.url):entry?draftMediaURL(entry.thumb_url||entry.url):doc?`/api/documents/${encodeURIComponent(doc.id)}/image`:'';
  return url?`<span class="factory-order-image"><img src="${esc(url)}" alt="${esc(project.name)} · ${esc(cover?.title||'整体效果图')}" loading="lazy"></span>`:'<span class="factory-order-image is-empty">'+icon('cube')+'<span>'+(projectVisualPanorama(project)?'360° 全景':'待补整体效果')+'</span></span>';
}
function projectVisualKey(entry){
  if(typeof entry?.id==='string'&&entry.id.trim())return entry.id;
  const url=draftMediaURL(entry?.url);return url?'url:'+url:'';
}
function projectVisualSelected(project,entries){
  const key=projectVisualSelection.get(project.id);if(!key)return 0;
  // Older Excel media had no id. Keep their URL selection through reloads,
  // including when the server supplies an id or merges identical images.
  const matches=entry=>projectVisualKey(entry)===key||'url:'+draftMediaURL(entry?.url)===key;
  return Math.max(0,entries.findIndex(entry=>matches(entry)||entry.evidence_sources?.some(matches)));
}
function invalidateProjectVisuals(projectId,resetSelection=false){draftMediaCache.delete(projectId);if(resetSelection){projectVisualSelection.delete(projectId);projectVisualMode.set(projectId,'effects');}}
function projectRelatedOrders(project=currentProject()){
  const found=new Map();
  for(const document of state.documents.filter(doc=>doc.project_id===project?.id&&doc.purpose!=='render'&&!doc.superseded)){
    for(const related of document.existing_drafts||[]){if(related.project_id!==project.id&&state.projects.some(p=>p.id===related.project_id))found.set(related.project_id,related);}
  }
  return [...found.values()];
}
function projectVisualModelCandidates(project=currentProject()){
  return (state?.documents||[]).filter(doc=>doc.project_id===project?.id&&!doc.demo&&!doc.superseded&&!doc.archived&&['drawing','engineering','model'].includes(doc.purpose||'drawing')&&!doc.reference_only&&!doc.shared_reference&&!doc.is_reference&&!['reference','shared_reference','render'].includes(doc.source_role)&&/\.(glb|obj|stl|step|stp|iges|igs|brep)$/i.test(doc.filename||''));
}
function projectVisualModelDocument(project=currentProject()){
  if(!project?.main_model_document_id)return undefined;
  const pin=project.main_model_source,doc=projectVisualModelCandidates(project).find(doc=>doc.id===project.main_model_document_id);
  return doc&&pin&&pin.document_sha256===doc.sha256&&pin.document_revision===doc.revision&&['assembly','appearance'].includes(pin.role)?doc:undefined;
}
function projectVisualModelRole(project=currentProject()){return project?.main_model_source?.role==='appearance'?'整体外观模型':'装配结构模型';}
function projectVisualCanSelectModel(project=currentProject()){return !projectIsClosed(project)&&(typeof accessCan!=='function'||accessCan('engineering'));}
function projectVisualModelChoice(project=currentProject()){
  const doc=projectVisualModelDocument(project),candidates=projectVisualModelCandidates(project),canSelect=projectVisualCanSelectModel(project);
  if(!candidates.length&&!project?.main_model_document_id)return '';
  return `<div class="project-model-choice"><div>${doc?`<strong>${esc(projectVisualModelRole(project))}</strong><span>${esc(doc.filename)}${doc.revision?' · R'+esc(doc.revision):''}</span>`:`<strong>${project.main_model_document_id?'整体模型需要重新指定':'尚未指定整体模型'}</strong><span>${candidates.length?'从本项目文件中选择整套装配或整体场景':'请上传当前版本的模型文件'}</span>`}</div>${canSelect?button(doc?'更换模型':'指定整体模型','project-visual-model-choose','cube'):''}</div>`;
}
function projectVisualModelURL(project=currentProject(),embed=true){
  const doc=projectVisualModelDocument(project);if(!doc)return '';
  return `/model/index.html?project=${encodeURIComponent(project.id)}&document=${encodeURIComponent(doc.id)}${embed?'&embed=1':''}`;
}
function projectVisualPanel(){
  const project=currentProject();if(!project)return '';ensureDraftMedia(project);
  const cache=draftMediaCache.get(project.id),entries=projectVisualEntries(project),selected=projectVisualSelected(project,entries),entry=entries[selected];
  const closed=projectIsClosed(project),canEdit=!closed&&(typeof accessCan!=='function'||accessCan('engineering'));
  const cabinets=projectVisualEntries(project,true).filter(projectVisualIsCabinet),panorama=projectVisualPanorama(project);
  const hasModel=Boolean(projectVisualModelDocument(project)),mode=hasModel&&projectVisualMode.get(project.id)==='model'?'model':'effects';
  const modelURL=projectVisualModelURL(project),fullURL=projectVisualModelURL(project,false);
  const original=entry?.document_id?`/api/documents/${encodeURIComponent(entry.document_id)}/download`:'';
  const editActions=canEdit?button('添加整体效果图','import-render','plus')+button('从 PDF 选图','project-overview-choose','file')+button('全景链接','project-overview-link','cube'):'';
  const effects=entry?`
    <figure class="project-visual-figure">
      <button class="project-visual-image" data-action="project-visual-open" data-index="${selected}" aria-label="放大查看${esc(entry.title||entry.kind)}">
        <img src="${esc(draftMediaURL(entry.url))}" alt="${esc(entry.title||entry.kind)}" decoding="async" fetchpriority="high">
        <span class="project-image-failure" hidden>图片加载失败，请重新加载</span>
      </button>
      <figcaption><div><strong>${esc(entry.title||entry.kind)}</strong><span>${esc(draftMediaSource(entry))}</span></div>
        <div class="project-overview-tools">${original?`<a class="btn" href="${esc(original)}" target="_blank" rel="noopener">查看原文件</a>`:''}${canEdit?button(project.overview_cover?.id===entry.id?'当前封面':'设为封面','project-overview-cover',null,'',`data-index="${selected}" ${project.overview_cover?.id===entry.id?'disabled':''}`):''}</div>
      </figcaption>
    </figure>
    ${entries.length>1?`<div class="project-visual-thumbs" aria-label="切换项目效果图">${entries.map((item,i)=>`<button class="${i===selected?'active':''}" aria-pressed="${i===selected}" aria-label="${esc(item.title||item.kind)}" data-action="project-visual-select" data-index="${i}"><img src="${esc(draftMediaURL(item.thumb_url||item.url))}" alt="" loading="lazy"><span>${esc(item.title||item.kind)}</span></button>`).join('')}</div>`:''}`
    :panorama?`<div class="project-panorama-launch">${icon('cube')}<h3>360° 整体全景</h3><p>旋转查看店面整体与各个角度</p><a class="btn primary" href="${esc(panorama)}" target="_blank" rel="noopener noreferrer">在新窗口打开 360° 全景 ${icon('arrow')}</a></div>`
    :`<div class="project-visual-empty" role="status">${icon('cube')}<h3>${cache?.status==='loading'?'正在加载整体效果图…':cache?.status==='error'?'整体效果图暂时无法加载':'添加项目整体效果图'}</h3>${cache?.status==='error'?button('重新加载','project-visual-retry','refresh'):cache?.status!=='loading'?editActions:''}</div>`;
  return `<section class="panel project-visual-panel" data-project="${esc(project.id)}" data-mode="${mode}" aria-label="项目总览">
    <div class="panel-head"><h2>${icon('cube')}整体效果图</h2><div class="project-visual-actions" data-view-actions="effects" ${mode==='effects'?'':'hidden'}>${entries.length||panorama?editActions:''}${entry?button('放大看图','project-visual-open','expand','',`data-index="${selected}"`):''}</div>${hasModel?`<div class="project-visual-actions" data-view-actions="model" ${mode==='model'?'':'hidden'}><a class="btn" href="${esc(fullURL)}" target="_blank" rel="noopener">${icon('expand')}全屏查看</a></div>`:''}</div>
    ${hasModel?`<div class="project-visual-mode" role="tablist" aria-label="项目查看方式"><button role="tab" id="project-effects-tab" aria-controls="project-effects-view" aria-selected="${mode==='effects'}" tabindex="${mode==='effects'?0:-1}" data-action="project-visual-mode" data-mode="effects">整体效果图</button><button role="tab" id="project-model-tab" aria-controls="project-model-view" aria-selected="${mode==='model'}" tabindex="${mode==='model'?0:-1}" data-action="project-visual-mode" data-mode="model">${esc(projectVisualModelRole(project))}</button></div><div class="project-model-view" id="project-model-view" role="tabpanel" aria-labelledby="project-model-tab" ${mode==='model'?'':'hidden'}><div class="project-model-slot" data-src="${esc(modelURL)}" data-title="${esc(project.name)} · ${esc(projectVisualModelRole(project))}"></div></div>`:''}
    <div class="project-effects-view" id="project-effects-view" ${hasModel?'role="tabpanel" aria-labelledby="project-effects-tab"':''} ${mode==='effects'?'':'hidden'}>${effects}
      ${entry&&cache?.status==='error'?`<div class="project-visual-error">效果图列表更新失败 ${button('重新加载','project-visual-retry','refresh')}</div>`:''}
      <div class="project-image-recovery" hidden>${button('重新加载图片','project-visual-retry','refresh')}</div>
      ${cabinets.length||panorama&&entries.length?`<div class="project-overview-footer">${cabinets.length?button(`柜体参考 · ${cabinets.length} 张`,'project-visual-cabinets','layers'):''}${panorama&&entries.length?`<a class="btn" href="${esc(panorama)}" target="_blank" rel="noopener noreferrer">360° 整体全景</a>`:''}</div>`:''}
    </div>${projectVisualModelChoice(project)}</section>`;
}
function renderAppWithProjectVisual(html){
  const app=document.querySelector('#app'),frame=app.querySelector('.project-model-frame'),oldSlot=frame?.parentElement;
  if(!frame||!oldSlot?.classList.contains('project-model-slot')){app.innerHTML=html;return;}
  const incoming=document.createElement('div');incoming.innerHTML=html;const nextSlot=incoming.querySelector('.project-model-slot');
  const oldProject=oldSlot.closest('.project-visual-panel')?.dataset.project,nextProject=nextSlot?.closest('.project-visual-panel')?.dataset.project;
  if(!nextSlot||!oldProject||oldProject!==nextProject||frame.getAttribute('src')!==nextSlot.dataset.src){app.innerHTML=html;return;}
  const branch=(leaf,root)=>{const nodes=[];for(let node=leaf;node;node=node.parentElement){nodes.unshift(node);if(node===root)return nodes;}return [];};
  const oldPath=branch(oldSlot,app),nextPath=branch(nextSlot,incoming);
  if(oldPath.length!==nextPath.length||oldPath.some((node,i)=>node.tagName!==nextPath[i].tagName)){app.innerHTML=html;return;}
  // Keep the connected ancestor chain in place. Only replace surrounding siblings.
  // This also preserves browsing contexts on browsers without Element.moveBefore.
  for(let i=0;i<oldPath.length;i++){
    const current=oldPath[i],next=nextPath[i];
    if(i){for(const attr of [...current.attributes])if(!next.hasAttribute(attr.name))current.removeAttribute(attr.name);for(const attr of [...next.attributes])current.setAttribute(attr.name,attr.value);}
    if(i===oldPath.length-1)break;
    const preserved=oldPath[i+1],nextPreserved=nextPath[i+1];
    for(const child of [...current.childNodes])if(child!==preserved)child.remove();
    let after=false;
    for(const child of next.childNodes){if(child===nextPreserved){after=true;continue;}const copy=child.cloneNode(true);if(after)current.append(copy);else current.insertBefore(copy,preserved);}
  }
}
function captureProjectVisualFrame(){
  const frame=document.querySelector('.project-model-frame');
  if(!frame||typeof document.body.moveBefore!=='function')return null;
  // Connected moves preserve the iframe browsing context, GPU scene and camera.
  frame.hidden=true;document.body.moveBefore(frame,null);return frame;
}
function restoreProjectVisualFrame(retained){
  const slot=document.querySelector('.project-model-slot');
  if(!slot){retained?.remove();return;}
  const url=slot.dataset.src;
  if(retained&&retained.getAttribute('src')===url&&typeof slot.moveBefore==='function'){
    slot.moveBefore(retained,null);retained.hidden=false;return;
  }
  retained?.remove();
  if(slot.closest('.project-visual-panel')?.dataset.mode!=='model')return;
  mountProjectVisualFrame(slot);
}
function mountProjectVisualFrame(slot){
  if(!slot||slot.querySelector('iframe'))return;
  const frame=document.createElement('iframe');frame.className='project-model-frame';frame.src=slot.dataset.src;frame.title=slot.dataset.title;frame.setAttribute('loading','eager');slot.append(frame);
}
function setProjectVisualMode(mode,panel=document.querySelector('.project-visual-panel')){
  if(!panel||!['model','effects'].includes(mode)||mode==='model'&&!panel.querySelector('.project-model-slot')?.dataset.src)return;
  projectVisualMode.set(panel.dataset.project,mode);panel.dataset.mode=mode;
  panel.querySelectorAll('[data-action="project-visual-mode"]').forEach(button=>{const active=button.dataset.mode===mode;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;});
  panel.querySelectorAll('[data-view-actions]').forEach(actions=>actions.hidden=actions.dataset.viewActions!==mode);
  const modelView=panel.querySelector('#project-model-view');if(modelView)modelView.hidden=mode!=='model';panel.querySelector('#project-effects-view').hidden=mode!=='effects';
  if(mode==='model')mountProjectVisualFrame(panel.querySelector('.project-model-slot'));
}
function projectEngineeringGroups(project=currentProject()){
  const groups=new Map();
  for(const entry of projectVisualData(project)?.sources||[]){
    if(!['施工图','工程图','来源料单'].includes(entry.kind)||!draftMediaURL(entry.url))continue;
    const key=entry.source_file||entry.id;if(!groups.has(key))groups.set(key,{title:key,entries:[]});
    const group=groups.get(key);if(!group.entries.some(old=>projectVisualKey(old)===projectVisualKey(entry)))group.entries.push(entry);
  }
  for(const group of groups.values())group.entries.sort((a,b)=>(a.page||0)-(b.page||0));
  return [...groups.values()];
}
function projectGeometryDocument(id=''){return docs().filter(doc=>!doc.superseded&&doc.geometry?.length&&(!id||doc.id===id)).at(-1);}
function projectGeometryContent(id){return `<div class="project-geometry-content" data-document="${esc(id)}">${drawingPanel(id).replaceAll('data-action="zoom-','data-action="project-geometry-zoom-')}</div>`;}
function openProjectGeometry(id){const doc=projectGeometryDocument(id);if(!doc)return;openModal('二维工程几何 · '+doc.filename,projectGeometryContent(doc.id),'<button class="btn" data-action="close">关闭</button>');}
function projectVisualNativeCAD(doc){return /\.(dwg|sldasm|sldprt|slddrw)$/i.test(doc?.filename||'');}
function projectVisualCompanions(source,documents){
  if(!projectVisualNativeCAD(source)||!source.sha256)return [];
  return documents.filter(doc=>doc.id!==source.id&&doc.project_id===source.project_id&&!doc.superseded&&!doc.archived&&
    (doc.companion_for||[]).some(link=>link.document_id===source.id&&link.sha256===source.sha256));
}
function projectVisualCompanionLabel(doc){
  if(uploadDocIsPdf(doc))return '配套核对图 PDF';
  if(/\.dxf$/i.test(doc.filename||''))return '配套二维图 DXF';
  if(uploadDocIsModel(doc))return '配套三维模型';
  return '配套 BOM 清单';
}
function projectVisualCompanionCard(doc){
  const pdf=uploadDocIsPdf(doc),dxf=Boolean(doc.geometry?.length);
  const action=pdf?'preview-upload':dxf?'project-geometry':'';
  const image=pdf?`<img src="${esc(uploadPreviewSrc(doc,true))}" alt="${esc(doc.filename)} 第 1 页缩略图" loading="lazy">`:icon(uploadDocIsModel(doc)?'cube':'file');
  return `<div class="project-engineering-companion">${action?`<button type="button" class="project-engineering-companion-thumb" data-action="${action}" data-id="${esc(doc.id)}" aria-label="查看${esc(doc.filename)}">${image}</button>`:`<span class="project-engineering-companion-thumb">${image}</span>`}<div><small>${projectVisualCompanionLabel(doc)}</small><strong>${esc(doc.filename)}</strong><div class="project-engineering-links">${pdf?button('查看原图','preview-upload',null,'',`data-id="${esc(doc.id)}"`):dxf?button('查看二维图','project-geometry',null,'',`data-id="${esc(doc.id)}"`):uploadModelLink(doc)}<a class="btn" href="/api/documents/${encodeURIComponent(doc.id)}/download" download>下载</a></div></div></div>`;
}
function projectVisualEngineeringCard(doc,documents){
  const native=projectVisualNativeCAD(doc),pdf=uploadDocIsPdf(doc),companions=projectVisualCompanions(doc,documents),dxf=Boolean(doc.geometry?.length);
  const detached=!native&&Boolean(doc.companion_for?.length)&&!documents.some(source=>projectVisualCompanions(source,documents).includes(doc));
  const action=pdf?'preview-upload':dxf?'project-geometry':'';
  const image=pdf?`<img src="${esc(uploadPreviewSrc(doc,true))}" alt="${esc(doc.filename)} 第 1 页缩略图" loading="lazy">`:icon(uploadDocIsModel(doc)?'cube':'file');
  return `<article class="project-engineering-file${native?' is-native':''}${detached?' is-detached':''}">${action?`<button type="button" class="project-engineering-thumb" data-action="${action}" data-id="${esc(doc.id)}" aria-label="查看${esc(doc.filename)}">${image}</button>`:`<span class="project-engineering-thumb">${image}</span>`}<div><strong>${esc(doc.filename)}</strong><small>${native?'原始工程文件 · 网页不直接预览，可核对下方配套图':detached?'关联原件已更新 · 此文件尚未用于当前核对':projectVisualOriginalDocument(doc)?'原始工程文件 · 请下载查看':esc(uploadDocSummary(doc))}</small><div class="project-engineering-links">${pdf?button(doc.purpose==='process'?'查看工艺资料':'查看施工图','preview-upload',null,'',`data-id="${esc(doc.id)}"`):dxf?button('查看二维图','project-geometry',null,'',`data-id="${esc(doc.id)}"`):uploadModelLink(doc)}<a class="btn" href="/api/documents/${encodeURIComponent(doc.id)}/download" download>下载原文件</a>${uploadRelated(doc)}${globalThis.KanpaceIntelligence?.engineeringButtons(doc)||''}</div>${native?`<div class="project-engineering-companions">${companions.length?companions.map(projectVisualCompanionCard).join(''):'<p>尚无配套核对图。上传设计软件导出的 PDF、DXF、STEP 或 BOM。</p>'}${!projectIsClosed(currentProject())?button('上传配套核对图','upload-companion','upload','',`data-id="${esc(doc.id)}"`):''}</div>`:''}</div></article>`;
}
function projectEngineeringPanel(){
  const project=currentProject();if(!project)return '';
  const uploaded=docs().filter(doc=>!doc.demo&&!doc.superseded&&!doc.archived&&doc.purpose!=='render'&&!/^order-draft-.*\.json$/i.test(doc.filename));
  const attached=new Set(uploaded.filter(doc=>uploaded.some(source=>projectVisualCompanions(source,uploaded).includes(doc))).map(doc=>doc.id));
  const primary=uploaded.filter(doc=>!attached.has(doc.id));
  const packet=project.order_packet, cabinetNames=new Set((state.parts||[]).filter(p=>p.project_id===project.id&&!p.archived).map(p=>p.name));
  const score=doc=>doc.id===packet?.master_document_id?0:uploadDocIsPdf(doc)?(cabinetNames.has(doc.filename.replace(/\.pdf$/i,''))?1:/施工/.test(doc.filename)?2:3):4;
  const sorted=primary.slice().reverse();if(packet)sorted.sort((a,b)=>score(a)-score(b));
  const groups=projectEngineeringGroups(project).filter(group=>!uploaded.some(doc=>doc.filename===group.title)),recent=sorted.slice(0,4),visible=groups.slice(0,Math.max(0,4-recent.length));
  const count=uploaded.length+groups.length,models=uploaded.filter(uploadDocIsModel),geometryDoc=projectGeometryDocument();
  const sourceAction=project.order_draft?'tab':'documents',industry=typeof projectWorkflowContext==='function'?!!projectWorkflowContext(project).industryId:!!project.industry_id;
  return `<section class="panel project-engineering-panel"><div class="panel-head"><h2>${icon('file')}${industry?'生产依据与工艺资料':'加工图与清单'}</h2>${button('上传资料','import','upload','',projectIsClosed(project)?'disabled':'')}</div><div class="project-engineering-body">${recent.map(doc=>projectVisualEngineeringCard(doc,uploaded)).join('')}${visible.map(group=>`<article class="project-engineering-file"><button class="project-engineering-thumb" data-action="project-engineering-open" data-file="${esc(group.title)}" aria-label="查看${esc(group.title)}"><img src="${esc(draftMediaURL(group.entries[0].thumb_url||group.entries[0].url))}" alt="" loading="lazy"></button><div><strong>${esc(group.title)}</strong><small>${group.entries.length} 张 · ${esc(group.entries[0].kind)}</small><button class="link-button" data-action="project-engineering-open" data-file="${esc(group.title)}">查看图纸 ${icon('arrow')}</button></div></article>`).join('')}${!count?`<p class="project-engineering-empty">${draftMediaCache.get(project.id)?.status==='loading'?'正在加载工程资料…':industry?'上传本行业确认版工艺资料':'上传施工图、零件模型或 BOM'}</p>`:''}<div class="project-engineering-footer">${models.length?`<a class="btn" href="/model/index.html?project=${encodeURIComponent(project.id)}${models.length===1?'&document='+encodeURIComponent(models[0].id):''}">${icon('cube')}查看工程模型</a>`:''}${button(count?'全部工程资料':'来源文件',sourceAction,'folder','',sourceAction==='tab'?'data-tab="draft-sources"':'')}${geometryDoc?button('查看二维几何','project-geometry','ruler','',`data-id="${esc(geometryDoc.id)}"`):''}</div></div></section>`;
}
function projectVisualOriginalDocument(doc){return /\.(max|sldprt|sldasm|slddrw|dwg)$/i.test(doc.filename||'');}
async function openProjectModelChoice(){
  const project=currentProject();if(!project||!projectVisualCanSelectModel(project))return;
  const pending={projectId:project.id};projectModelChoiceContext=pending;
  openModal('指定项目整体模型','<p role="status">正在读取本项目模型…</p>');
  try{
    const result=await api(`/api/projects/${encodeURIComponent(project.id)}/sources`);
    if(projectModelChoiceContext!==pending||currentProject()?.id!==project.id||!projectVisualCanSelectModel(currentProject())||!document.querySelector('#modal')?.open)return;
    const selected=result.selection?.status==='selected'?result.selection.document_id:'',candidates=result.candidates||[];
    projectModelChoiceContext={...pending,...result};
    openModal('指定项目整体模型',`<form id="project-main-model-form"><p class="project-model-form-intro">选择能看清整套装配或整体场景的文件。</p>${result.selection?.reason?`<p class="project-model-form-notice">${esc(result.selection.reason)}</p>`:''}${candidates.length?`<label>模型文件<select name="document_id" required><option value="">请选择本项目的整体模型</option>${candidates.map(doc=>`<option value="${esc(doc.id)}" ${doc.id===selected?'selected':''}>${esc(doc.filename)}${doc.revision?' · R'+esc(doc.revision):''}</option>`).join('')}</select></label><label>模型用途<select name="role" required><option value="">请选择用途</option><option value="assembly" ${selected&&result.selection.role==='assembly'?'selected':''}>装配结构模型</option><option value="appearance" ${selected&&result.selection.role==='appearance'?'selected':''}>整体外观模型</option></select></label>`:`<p>本项目还没有可用模型。</p><a class="btn" href="/model/index.html?project=${encodeURIComponent(project.id)}">上传工程模型</a>`}<p class="project-model-form-note">加工任务仍关联已确认的图纸与清单。</p></form>`,`${result.selection?.document_id?button('清除选择','project-visual-model-clear'):''}${button('取消','close')}${candidates.length?button('保存主模型','project-visual-model-save',null,'primary',selected?'':'disabled'):''}`);
    document.querySelector('#project-main-model-form select')?.focus();
  }catch(error){if(projectModelChoiceContext===pending&&currentProject()?.id===project.id&&document.querySelector('#modal')?.open)openModal('指定项目整体模型',`<p role="alert">${esc(error.message||'模型列表读取失败')}</p>`,button('重新读取','project-visual-model-choose'));}
}
async function saveProjectModelChoice(button,clear=false){
  const context=projectModelChoiceContext,form=document.querySelector('#project-main-model-form'),project=currentProject();
  if(!context||!form||project?.id!==context.projectId||!projectVisualCanSelectModel(project)||context.saving)return;
  if(!clear&&!form.reportValidity())return;
  const doc=!clear&&context.candidates.find(item=>item.id===form.elements.document_id.value);
  if(!clear&&!doc)return;
  const data={expected_selection_version:context.selection_version,main_model_document_id:clear?null:doc.id,...(clear?{}:{document_sha256:doc.sha256,role:form.elements.role.value})};
  const controls=[...document.querySelectorAll('#modal button,#modal select')],prior=controls.map(item=>item.disabled);
  controls.forEach(item=>item.disabled=true);context.saving=true;
  const errors=document.querySelector('#modal .dialog-error');if(errors)errors.textContent='';
  try{
    const result=await api(`/api/projects/${encodeURIComponent(context.projectId)}/sources`,data);
    if(projectModelChoiceContext!==context)return;
    const existing=state.projects.findIndex(item=>item.id===context.projectId);if(existing>=0)state.projects[existing]=result.project;
    projectModelChoiceContext=null;projectVisualMode.set(context.projectId,clear?'effects':'model');
    if(document.querySelector('#project-main-model-form')===form)closeModal();
    draftRenderPreserving();toast(clear?'已清除项目主模型':'已保存项目主模型');
  }catch(error){if(projectModelChoiceContext===context&&document.querySelector('#project-main-model-form')===form&&errors)errors.textContent=error.message||'保存失败，请重试';}
  finally{context.saving=false;controls.forEach((item,i)=>item.disabled=prior[i]);}
}
function openProjectVisualViewer(entries,index,trigger){
  if(!entries.length)return;draftViewerTrigger=trigger;draftViewer={part:{name:currentProject().name},entries,index:Math.max(0,Math.min(index,entries.length-1)),scale:1,base:1};
  const dialog=draftViewerDialog();if(!dialog.open)dialog.showModal();draftViewerShow();
}
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-action]');if(!button||uploadBusy)return;
  const action=button.dataset.action;if(!action.startsWith('project-visual-')&&!action.startsWith('project-geometry')&&action!=='project-engineering-open')return;
  const project=currentProject();if(!project)return;
  if(action==='project-visual-model-choose'){openProjectModelChoice();return;}
  if(action==='project-visual-model-save'){saveProjectModelChoice(button);return;}
  if(action==='project-visual-model-clear'){saveProjectModelChoice(button,true);return;}
  if(action==='project-visual-mode'){setProjectVisualMode(button.dataset.mode,button.closest('.project-visual-panel'));return;}
  if(action==='project-visual-retry'){ensureDraftMedia(project,true);draftRenderPreserving();return;}
  if(action==='project-visual-open'){openProjectVisualViewer(projectVisualEntries(project),Number(button.dataset.index)||0,button);return;}
  if(action==='project-visual-cabinets'){openProjectVisualViewer(projectVisualEntries(project,true).filter(projectVisualIsCabinet),0,button);return;}
  if(action==='project-visual-select'){
    const entries=projectVisualEntries(project),index=Number(button.dataset.index)||0;if(!entries[index])return;
    projectVisualSelection.set(project.id,projectVisualKey(entries[index]));draftRenderPreserving();document.querySelector(`[data-action="project-visual-select"][data-index="${index}"]`)?.focus({preventScroll:true});return;
  }
  if(action==='project-engineering-open'){const group=projectEngineeringGroups(project).find(group=>group.title===button.dataset.file);if(group)openProjectVisualViewer(group.entries,0,button);return;}
  if(action==='project-geometry')return openProjectGeometry(button.dataset.id);
  if(action.startsWith('project-geometry-zoom-')){const content=button.closest('.project-geometry-content'),id=content?.dataset.document;if(!projectGeometryDocument(id))return;zoom=action==='project-geometry-zoom-reset'?1:Math.min(2,Math.max(.5,zoom+(action==='project-geometry-zoom-in'?.2:-.2)));content.outerHTML=projectGeometryContent(id);}
});
document.addEventListener('error',event=>{
  const image=event.target;if(!(image instanceof HTMLImageElement)||!image.closest('.project-visual-image'))return;
  image.hidden=true;const panel=image.closest('.project-visual-panel');panel.querySelector('.project-image-failure').hidden=false;panel.querySelector('.project-image-recovery').hidden=false;
},true);

document.addEventListener('keydown',event=>{const tab=event.target.closest?.('[data-action="project-visual-mode"]');if(!tab||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const mode=event.key==='Home'?'effects':event.key==='End'?'model':tab.dataset.mode==='model'?'effects':'model';setProjectVisualMode(mode,tab.closest('.project-visual-panel'));document.querySelector(`[data-action="project-visual-mode"][data-mode="${mode}"]`)?.focus();});
document.addEventListener('change',event=>{const form=event.target.closest?.('#project-main-model-form');if(!form||projectModelChoiceContext?.saving)return;const save=document.querySelector('[data-action="project-visual-model-save"]');if(save)save.disabled=!form.elements.document_id?.value||!form.elements.role?.value;});
