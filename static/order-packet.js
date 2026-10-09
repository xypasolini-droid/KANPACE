'use strict';
// A single next action inside the drawing workspace; no additional main menu.
function orderPacketToolbar(){
  const p=currentProject();if(!p||projectIsClosed(p)||p.industry_id||p.workflow_id||(p.factory_type&&p.factory_type!=='cabinet'))return '';
  const available=docs().filter(d=>!d.superseded&&d.purpose!=='process'&&/\.xlsx$/i.test(d.filename||''));
  if(!available.length)return '';
  const info=p.order_packet,stale=info&&info.revision!==p.revision,canEdit=typeof accessCan!=='function'||accessCan('engineering');
  const questions=parts().reduce((n,p)=>n+(p.review_questions?.length||0),0)+(p.order_draft?.issues?.length||0);
  const review=info&&!stale?button(questions?`核对 ${questions} 项疑问`:'查看任务草稿','tab','arrow','primary',`data-tab="${questions?'draft-review':'tasks'}"`):'';
  return `<section class="order-packet-bar" aria-label="订单拆单操作"><div><strong>${stale?'资料已更新，请重新拆单':info?`${info.quantity_total} 套（组） · ${info.scope_count} 项工种草稿`:'按订单资料拆任务'}</strong><p>${info?'按柜号看效果、查工程页、核对分工':'选择下单清单，按柜号关联工程图和工种'}</p></div><div class="packet-actions">${review}<button type="button" class="btn ${!info||stale?'primary':''}" data-packet-action="open" ${canEdit?'':'disabled'}>${info?'更新订单拆解':'按订单资料拆任务'}</button>${button('AI 帮我核对','agent-open','search','',`data-agent-prompt="检查当前订单的拆单依据" data-agent-project="${esc(p.id)}"`)}</div></section>`;
}
const packetOriginalToolbar=projectDrawingToolbar;
projectDrawingToolbar=function(...args){return orderPacketToolbar()||packetOriginalToolbar(...args);};

function orderPacketOpen(){
  const p=currentProject();if(!p)return;
  const ds=docs().filter(d=>!d.superseded&&d.purpose!=='process'&&/\.xlsx$/i.test(d.filename||''));
  const preferred=p.order_packet?.master_document_id||ds.find(d=>/下单清单/.test(d.filename))?.id;
  openModal('按订单资料拆任务',`<form id="order-packet-form" data-project="${esc(p.id)}" data-revision="${p.revision}"><p>${esc(p.name)}</p><label class="field" for="packet-master">本次数量依据<select id="packet-master" name="master_document_id">${ds.map(d=>`<option value="${esc(d.id)}" ${d.id===preferred?'selected':''}>${esc(d.relative_path||d.filename)}</option>`).join('')}</select></label><p class="muted">读取清单数量，关联本项目工程图；先生成可核对的任务草稿。</p><div id="packet-sheet-choice"></div><div id="packet-progress" role="status" aria-live="polite"></div></form>`,button('取消','close')+'<button type="button" class="btn primary" data-packet-action="build">生成拆单草稿</button>');
}
async function orderPacketBuild(buttonElement){
  const form=document.getElementById('order-packet-form');if(!form)return;
  const pid=form.dataset.project, revision=Number(form.dataset.revision), master=document.getElementById('packet-master').value;
  const status=document.getElementById('packet-progress');buttonElement.disabled=true;status.textContent='正在读取清单、匹配工程图并核对重复页…';
  const closeButtons=Array.from(document.querySelectorAll('#modal [data-action="close"]'));closeButtons.forEach(b=>b.disabled=true);
  try{
    const payload={expected_revision:revision,master_document_id:master};const sheet=document.getElementById('packet-sheet');if(sheet)payload.sheet=sheet.value;
    const res=await fetch(`/api/projects/${encodeURIComponent(pid)}/order-packet`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const data=await res.json();
    if(!res.ok){
      const sheets=data.details?.sheets;
      if(sheets?.length)document.getElementById('packet-sheet-choice').innerHTML=`<label class="field" for="packet-sheet">订单工作表<select id="packet-sheet">${sheets.map(s=>`<option>${esc(s)}</option>`).join('')}</select></label>`;
      throw new Error(data.error||'拆单未完成，请重试');
    }
    if(typeof draftMediaCache!=='undefined')draftMediaCache.delete(pid);
    if(typeof invalidateProjectVisuals==='function')invalidateProjectVisuals(pid,true);
    await refresh();closeModal();navigate('drawing','parts',pid);toast(data.unchanged?'资料未变化，已保留当前拆单草稿':`已生成 ${data.parts.length} 项柜体、${data.tasks.length} 项工种草稿`);
  }catch(e){status.textContent=e.message||'连接中断，刷新后查看拆单结果再重试';}
  finally{if(buttonElement.isConnected)buttonElement.disabled=false;closeButtons.forEach(b=>b.disabled=false);}
}
function orderPacketSource(evidence){
  const page=Number(evidence?.page),doc=docs().find(d=>d.id===evidence?.document_id);
  if(!doc||doc.superseded||doc.archived||!uploadDocIsPdf(doc)||!Number.isSafeInteger(page)||page<1||evidence.sha256!==doc.sha256)return null;
  return {doc,page,thumb:`/api/documents/${encodeURIComponent(doc.id)}/preview-image?page=${page}&thumb=1`};
}
function orderPacketSourceCell(row){
  const source=orderPacketSource(row.evidence);
  if(!source)return '<span class="packet-source-unavailable">来源图已更新，请重新核对</span>';
  return `<span class="packet-source"><img src="${esc(source.thumb)}" alt="${esc(source.doc.filename)} 第 ${source.page} 页整页缩略图" loading="lazy"><button type="button" class="link-button" data-packet-action="source" data-document="${esc(source.doc.id)}" data-page="${source.page}">查看原图第 ${source.page} 页 · ${esc(row.parent||source.doc.filename)}</button></span>`;
}
function orderPacketBom(p){
  const rows=p.engineering_bom||[];if(!rows.length)return '';
  const cover=rows.map(r=>orderPacketSource(r.evidence)).find(Boolean);
  return `<details class="packet-bom"><summary>${cover?`<img src="${esc(cover.thumb)}" alt="${esc(cover.doc.filename)} 原图整页缩略图" loading="lazy">`:''}<span>构件清单 · ${rows.length} 项图纸依据</span></summary><p>缩略图是工程图整页。点击查看原图，核对尺寸、材料和单柜用量后再分工。</p><div class="packet-table-scroll"><table><caption>${esc(p.name)} · 原图明细</caption><thead><tr><th scope="col">部件</th><th scope="col">规格原文</th><th scope="col">材料 / 做法原文</th><th scope="col">图示用量</th><th scope="col">对应原图</th></tr></thead><tbody>${rows.map(r=>`<tr><th scope="row">${esc(r.name)}${r.questions?.length?'<small>材质待核对</small>':''}</th><td>${esc(r.specification||'见工程图')}</td><td>${esc(r.note||'见原图')}</td><td>${esc(r.per_assembly_quantity)}</td><td>${orderPacketSourceCell(r)}</td></tr>`).join('')}</tbody></table></div></details>`;
}
const packetOriginalCard=draftCard;
draftCard=function(p){let html=packetOriginalCard(p);if(p.packet_generated&&p.review_questions?.length)html=html.replace('<details class="draft-questions">','<details class="draft-questions" open>');return html.replace('</article>',orderPacketBom(p)+'</article>');};

document.addEventListener('click',e=>{const b=e.target.closest('[data-packet-action]');if(!b||b.disabled)return;const a=b.dataset.packetAction;if(a==='open')orderPacketOpen();else if(a==='build')orderPacketBuild(b);else if(a==='source')previewUploadedDocument(b.dataset.document,Number(b.dataset.page));});
document.addEventListener('change',e=>{
  if(e.target.id!=='import-folder')return;
  const files=Array.from(e.target.files||[]), isEffect=f=>/\/(效果|效果图|渲染图)\//.test('/'+f.webkitRelativePath)&&/\.(jpe?g|png|webp)$/i.test(f.name);
  const allowed=files.filter(f=>!/(^|\/)(~\$|\._)|Thumbs\.db|\.bak$/i.test(f.webkitRelativePath||f.name)&&(/\.(pdf|xlsx|xls|csv|json|dxf|dwg|sldasm|sldprt|slddrw|step|stp|iges|igs|brep|stl|obj|glb)$/i.test(f.name)||isEffect(f)));
  selectUploadFiles(allowed);
  uploadQueue.forEach(q=>{if(isEffect(q.file))q.purpose='render';});
  if(files.length!==allowed.length)document.getElementById('upload-queue').insertAdjacentHTML('afterbegin',`<p class="muted">已选择 ${allowed.length} 份图纸、清单和效果图，跳过 ${files.length-allowed.length} 个其他图片、压缩包或临时文件。</p>`);
});
