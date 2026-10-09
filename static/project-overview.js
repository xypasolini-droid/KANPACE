'use strict';
let projectOverviewContext=null;
function projectOverviewCanEdit(project=currentProject()){return project&&!projectIsClosed(project)&&(typeof accessCan!=='function'||accessCan('engineering'));}
function projectOverviewPageGrid(){
  const context=projectOverviewContext,form=document.querySelector('#project-overview-form');if(!context||!form)return;
  const doc=context.candidates.find(d=>d.id===form.elements.document_id.value),grid=form.querySelector('.overview-page-grid');
  if(!doc){grid.innerHTML='';return;}
  const selected=new Set((context.project.overview_sources||[]).filter(s=>s.document_id===doc.id&&s.document_sha256===doc.sha256).map(s=>s.page));
  grid.innerHTML=Array.from({length:doc.page_count},(_,i)=>{const page=i+1;return `<div class="overview-page"><button type="button" data-overview-action="preview" data-page="${page}" aria-label="放大预览第 ${page} 页"><img loading="lazy" src="/api/documents/${encodeURIComponent(doc.id)}/preview-image?page=${page}&thumb=1" alt="第 ${page} 页"></button><label><input type="checkbox" name="pages" value="${page}" ${selected.has(page)?'checked':''}>第 ${page} 页</label></div>`;}).join('');
}
async function openProjectOverviewPDF(){
  const project=currentProject();if(!projectOverviewCanEdit(project))return;
  const request={projectId:project.id};projectOverviewContext=request;
  openModal('从 PDF 选择整体效果图','<p id="project-overview-loading" role="status">正在读取本项目 PDF…</p>');
  const loading=document.querySelector('#project-overview-loading');
  try{
    const result=await api(`/api/projects/${encodeURIComponent(project.id)}/overview`);
    if(projectOverviewContext!==request||currentProject()?.id!==project.id||!document.querySelector('#modal')?.open||document.querySelector('#project-overview-loading')!==loading)return;
    result.candidates.sort((a,b)=>Number(!/效果|基装|深化/.test(a.relative_path||a.filename))-Number(!/效果|基装|深化/.test(b.relative_path||b.filename)));
    projectOverviewContext={...request,...result};
    const docs=result.candidates;
    openModal('从 PDF 选择整体效果图',docs.length?`<form id="project-overview-form"><label class="overview-file-label">方案文件<select name="document_id">${docs.map(d=>`<option value="${esc(d.id)}">${esc(d.relative_path||d.filename)} · ${d.page_count} 页</option>`).join('')}</select></label><p>勾选展示整体空间的效果页，点击图片可放大核对。</p><div class="overview-page-grid"></div></form>`:'<p>先上传本项目的效果方案 PDF，再选择需要展示的页面。</p>',button('取消','close')+(docs.length?button('保存整体效果图','project-overview-save',null,'primary'):button('上传方案 PDF','import','upload','primary')));
    projectOverviewPageGrid();document.querySelector('#project-overview-form select')?.focus();
  }catch(error){if(projectOverviewContext===request&&currentProject()?.id===project.id&&document.querySelector('#modal')?.open&&document.querySelector('#project-overview-loading')===loading)openModal('从 PDF 选择整体效果图',`<p role="alert">${esc(error.message)}</p>`,button('重新读取','project-overview-choose'));}
}
function openProjectOverviewLink(){
  const project=currentProject();if(!projectOverviewCanEdit(project))return;
  projectOverviewContext={projectId:project.id,version:project.overview_version||0};
  openModal('关联 360° 整体全景',`<form id="project-overview-link-form"><label class="overview-file-label">原始全景链接<input name="panorama_url" type="url" value="${esc(projectVisualPanorama(project))}" placeholder="https://vr.3d66.com/vr/index_detail_编号.html"></label></form>`,button('取消','close')+button('保存全景链接','project-overview-link-save',null,'primary'));
  document.querySelector('#project-overview-link-form input')?.focus();
}
async function saveProjectOverview(button,data,context=projectOverviewContext){
  const project=currentProject();if(!context||project?.id!==context.projectId||!projectOverviewCanEdit(project)||context.saving)return;
  const form=document.querySelector('#project-overview-form,#project-overview-link-form');
  const controls=form?[...form.querySelectorAll('input,select,button'),button]:[button],prior=controls.map(c=>c.disabled);
  context.saving=true;controls.forEach(c=>c.disabled=true);
  try{
    const result=await api(`/api/projects/${encodeURIComponent(project.id)}/overview`,{expected_version:context.version,...data});
    const index=state.projects.findIndex(p=>p.id===project.id);if(index>=0)state.projects[index]=result.project;
    invalidateProjectVisuals(project.id,!data.cover_id);
    if(currentProject()?.id===project.id){if(form&&document.querySelector('#project-overview-form,#project-overview-link-form')===form)closeModal();draftRenderPreserving();}
    toast(data.cover_id?'已设为项目封面':'已更新整体效果');
  }catch(error){if(form&&document.querySelector('#project-overview-form,#project-overview-link-form')===form&&document.querySelector('#modal')?.open){const target=document.querySelector('#modal .dialog-error');if(target)target.textContent=error.message;}else toast(error.message);}
  finally{context.saving=false;controls.forEach((c,i)=>c.disabled=prior[i]);}
}
document.addEventListener('change',event=>{if(event.target.matches?.('#project-overview-form select'))projectOverviewPageGrid();});
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-action],[data-overview-action]');if(!button||button.disabled)return;
  const action=button.dataset.action;
  if(action==='project-overview-choose')return openProjectOverviewPDF();
  if(action==='project-overview-link')return openProjectOverviewLink();
  if(action==='project-overview-save'){
    const form=document.querySelector('#project-overview-form'),context=projectOverviewContext;if(!form||!context)return;
    const doc=context.candidates.find(d=>d.id===form.elements.document_id.value);if(!doc)return;
    return saveProjectOverview(button,{document_id:doc.id,document_sha256:doc.sha256,pages:[...form.querySelectorAll('input[name="pages"]:checked')].map(c=>Number(c.value))});
  }
  if(action==='project-overview-link-save'){
    const form=document.querySelector('#project-overview-link-form');if(form?.reportValidity())return saveProjectOverview(button,{panorama_url:form.elements.panorama_url.value.trim()});
  }
  if(action==='project-overview-cover'){
    const project=currentProject(),entry=projectVisualEntries(project)[Number(button.dataset.index)];if(!entry)return;
    return saveProjectOverview(button,{cover_id:entry.id},{projectId:project.id,version:project.overview_version||0});
  }
  if(button.dataset.overviewAction==='preview'){
    const form=document.querySelector('#project-overview-form'),context=projectOverviewContext;if(!form||!context)return;
    const doc=context.candidates.find(d=>d.id===form.elements.document_id.value),page=Number(button.dataset.page);if(!doc)return;
    openProjectVisualViewer([{title:`${doc.filename} · 第 ${page} 页`,source_file:doc.filename,page,kind:'PDF 原页',url:`/api/documents/${encodeURIComponent(doc.id)}/preview-image?page=${page}`}],0,button);
  }
});
