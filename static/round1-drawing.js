'use strict';
// Contextual reader for a teammate's first-round model drawings. These files
// establish scope and outline only; no result here can release production.
globalThis.KanpaceRound1 = (() => {
  const records = new Map();
  const uploads = new Map();
  const endpoint = projectId => `/api/projects/${encodeURIComponent(projectId)}/drawing-pipeline`;

  function assetURL(value, projectId, kind = '') {
    if (typeof value !== 'string' || !value.startsWith('/')) return '';
    try {
      const url = new URL(value, location.origin);
      const prefix = endpoint(projectId) + '/assets/';
      const match = /^dpr_[0-9a-f]{12}\/(preview|svg|dxf)$/.exec(url.pathname.slice(prefix.length));
      if (url.origin !== location.origin || !url.pathname.startsWith(prefix) ||
          !match || kind && match[1] !== kind || url.search || url.hash) return '';
      return url.pathname;
    } catch { return ''; }
  }

  function normalize(raw, projectId) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw) ||
        raw.project_id && raw.project_id !== projectId) throw new Error('核对结果与当前项目不一致，请刷新项目');
    const value = raw.review || raw.result || raw;
    const catalog = Array.isArray(value.candidates) ? value.candidates :
      Array.isArray(value.catalog?.items) ? value.catalog.items : [];
    const selected = Array.isArray(value.selection?.items) ? value.selection.items :
      Array.isArray(value.selected_items) ? value.selected_items : [];
    const output = Array.isArray(value.outputs) ? value.outputs[0] : null;
    const files = value.artifacts || value.output || output || {};
    const selectedIds = new Set(selected.map(item => String(item.id || '')));
    const candidates = catalog.filter(item => item && typeof item === 'object').slice(0, 100).map(item => ({
      id: String(item.id || '').slice(0, 80), name: String(item.name || item.label || item.id || '待命名柜体').slice(0, 160),
      objectCount: Number.isInteger(item.object_count) ? item.object_count : Array.isArray(item.node_ids) ? item.node_ids.length : null,
      selected: selectedIds.has(String(item.id || '')) || item.selected === true,
      quantity: Number.isInteger(item.quantity) ? item.quantity : null,
      dimensionBasis: String(item.dimension_basis || ''),
      confirmed: item.confirmed === true,
    }));
    const artifacts = {
      preview: assetURL(files.preview_url || files.png_url || value.preview_url, projectId, 'preview'),
      svg: assetURL(files.svg_url, projectId, 'svg'),
      dxf: assetURL(files.dxf_url, projectId, 'dxf'),
    };
    const status = String(value.status || raw.status || 'empty');
    return {
      projectId, status, source: String(value.source?.archive_filename || value.source?.filename || value.source_filename || '').slice(0, 240),
      sourceLinked: value.source_linked === true && value.source?.source_match === true,
      candidateCount: Number.isInteger(value.source?.candidate_count) ? value.source.candidate_count : candidates.length,
      candidates,
      selected: (selected.length ? selected : catalog.filter(item => item?.selected)).filter(item => item && typeof item === 'object').slice(0, 100).map(item => ({
        id: String(item.id || '').slice(0, 80), quantity: Number.isInteger(item.quantity) ? item.quantity : null,
        objectCount: Number.isInteger(item.object_count) ? item.object_count : Array.isArray(item.node_ids) ? item.node_ids.length : null,
        scopeConfirmed: item.scope_confirmed === true || item.confirmed === true,
        dimensionBasis: String(item.dimension_basis || ''),
      })),
      outputLabel: String(output?.label || '').slice(0, 160),
      artifacts,
      warnings: (Array.isArray(value.warnings) ? value.warnings : value.warning ? [value.warning] : [])
        .filter(item => typeof item === 'string').slice(0, 6).map(item => item.slice(0, 500)),
      coverage: String(value.source?.coverage || value.coverage || value.coverage_note || '').slice(0, 500),
    };
  }

  function visible(projectId) {
    return typeof currentProject === 'function' && currentProject()?.id === projectId &&
      (typeof page === 'undefined' || page === 'drawing') && (typeof tab === 'undefined' || tab === 'parts');
  }

  function replacePanel(projectId) {
    if (!visible(projectId)) return;
    const host = [...document.querySelectorAll('.round1-panel')].find(node => node.dataset.project === projectId);
    if (!host) return;
    const action = document.activeElement?.dataset?.round1Action;
    const template = document.createElement('template');
    template.innerHTML = renderData(currentProject(), records.get(projectId));
    host.replaceWith(template.content.firstElementChild);
    if (action) [...document.querySelectorAll('.round1-panel [data-round1-action]')]
      .find(node => node.dataset.round1Action === action)?.focus();
  }

  async function load(project, force = false) {
    if (!project?.id) return;
    const prior = records.get(project.id);
    if (!force && prior?.revision === project.revision && ['loading', 'ready', 'error'].includes(prior.phase)) return;
    const entry = {phase:'loading', revision:project.revision, data:prior?.data || null, error:''};
    records.set(project.id, entry); replacePanel(project.id);
    try {
      const response = await api(endpoint(project.id));
      if (records.get(project.id) !== entry) return;
      entry.data = normalize(response, project.id);
      entry.phase = 'ready';
    } catch (error) {
      if (records.get(project.id) !== entry) return;
      entry.phase = 'error';
      entry.error = error.message || '读取失败';
    }
    replacePanel(project.id);
  }

  function renderData(project, record) {
    if (!project?.id) return '';
    const item = record?.data, busy = uploads.get(project.id),
      canEdit = !projectIsClosed(project) && (typeof accessCan !== 'function' || accessCan('engineering'));
    const state = record?.phase || 'loading';
    const selected = item?.selected || [], first = selected[0];
    const preview = item?.artifacts?.preview;
    const fileLinks = item?.artifacts || {};
    const source = item?.source ? `<p class="round1-source">出图包：${esc(item.source)}</p>` : '';
    const details = first ? `<div class="round1-selection"><div class="round1-selection-head"><strong>${esc(first.id)} · 已选柜体范围</strong><span>${selected.length} 组</span></div>
      <p>${first.objectCount == null ? '' : `${first.objectCount} 个模型对象 · `}${first.quantity == null ? '归档数量待核对' : `归档记载 ${first.quantity} 组`}</p>
      <p>${first.scopeConfirmed ? '归档记录：范围已选' : '柜体范围待核对'} · ${first.dimensionBasis === 'model_only' ? '仅模型尺寸，实物尺寸未核验' : '尺寸依据待工程核验'}</p></div>` : '';
    const files = [['svg','下载 SVG 核对图'],['dxf','下载 DXF 线图']]
      .filter(([key]) => fileLinks[key]).map(([key,label]) => `<a class="btn" href="${esc(fileLinks[key])}" download>${esc(label)}</a>`).join('');
    let body = '';
    if (state === 'loading' && !item) body = '<div class="round1-message" role="status">正在读取这个项目的核对图…</div>';
    else if (state === 'error' && !item) body = `<div class="round1-message" role="alert"><strong>核对图暂时无法读取</strong><p>${esc(record.error)}</p><button type="button" class="btn" data-round1-action="retry">重新读取</button></div>`;
    else if (item && (preview || selected.length || item.candidates.length)) {
      body = `<div class="round1-provenance ${item.sourceLinked ? 'is-linked' : 'is-unlinked'}" role="status"><strong>${item.sourceLinked ? '源模型指纹已匹配' : '未与本项目源模型核对，仅供参考'}</strong><span>${item.sourceLinked ? '仍须按原件核对模型版本与工程尺寸。' : '此出图包尚不能视为本订单的工程依据。'}</span></div>
        <div class="round1-content">${preview ? `<figure class="round1-preview"><a href="${esc(preview)}" target="_blank" rel="noopener" aria-label="查看早期外形核对图"><img src="${esc(preview)}" alt="${esc(first?.id || '柜体')}早期外形核对草稿预览" width="1200" height="800" loading="lazy" decoding="async"></a><figcaption>${esc(item.outputLabel || '早期外形核对草稿')} · 只供看形状</figcaption></figure>` : '<div class="round1-no-preview">这份核对包没有可用的 PNG 预览</div>'}
        <div class="round1-information">${details}<div class="round1-info-actions">${files}${preview ? `<a class="btn" href="${esc(preview)}" target="_blank" rel="noopener">放大看图</a>` : ''}</div>${source}
        ${item.candidates.length ? `<details class="round1-candidates"><summary>查看候选柜体 · ${item.candidateCount} 组</summary><ol>${item.candidates.map(candidate => `<li><span><strong>${esc(candidate.id)}</strong> ${esc(candidate.name)}</span><span>${candidate.selected ? '已选范围' : '待核对'}${candidate.objectCount == null ? '' : ` · ${candidate.objectCount} 个对象`}</span></li>`).join('')}</ol></details>` : ''}
        </div></div>
        ${item.warnings.length ? `<details class="round1-warnings"><summary>查看核验提示 · ${item.warnings.length} 条</summary><ul>${item.warnings.map(message => `<li>${esc(message)}</li>`).join('')}</ul></details>` : ''}`;
    } else body = `<div class="round1-message"><strong>${['queued','running','processing'].includes(item?.status) ? '核对包正在处理' : '这个项目还没有第一轮核对图'}</strong><p>${['queued','running','processing'].includes(item?.status) ? '处理完成后刷新这里查看结果。' : '导入 ZIP 核对包，先核对柜体范围和尺寸依据。'}</p></div>`;
    return `<section class="panel round1-panel" data-project="${esc(project.id)}" aria-label="选柜与外形核对">
      <div class="round1-head"><div><h2>选柜与外形核对</h2><p>核对模型范围和外形</p></div><span class="round1-boundary">不可下料 · 不可派工</span></div>
      <div class="round1-body">${body}<p class="round1-note">此处只核对柜体范围与外形；材料、孔槽、五金和加工尺寸要以施工图及技术员复核结果为准。</p>
      ${state === 'error' && item ? `<p class="round1-error" role="alert">更新失败：${esc(record.error)}。以上显示上次读取的结果。</p>` : ''}
      ${busy?.error ? `<p class="round1-error" role="alert">${esc(busy.error)}</p>` : ''}
      <div class="round1-footer">${canEdit ? `<button type="button" class="btn" data-round1-action="upload" ${busy?.busy ? 'aria-disabled="true"' : ''}>导入模型核对包</button><input class="round1-file" type="file" accept=".zip,application/zip" aria-label="选择 ZIP 模型核对包" hidden>` : ''}
      <button type="button" class="btn" data-round1-action="retry" ${busy?.busy ? 'aria-disabled="true"' : ''}>刷新核对图</button></div>
      ${busy?.busy ? `<div class="round1-upload-state" role="status"><span>${esc(busy.message || '正在上传核对包…')}</span><progress max="100" value="${Math.max(0, Math.min(100, busy.progress || 0))}">${busy.progress || 0}%</progress></div>` : ''}
      </div></section>`;
  }

  function panel(project) {
    if (!project?.id) return '';
    // Loading is local to this section; the rest of the drawing page stays usable.
    void load(project);
    return renderData(project, records.get(project.id));
  }

  function uploadFile(file, project) {
    if (!file || !project || !visible(project.id)) return;
    const state = {busy:false, error:'', message:'', progress:0};
    uploads.set(project.id, state);
    if (!/\.zip$/i.test(file.name)) state.error = '请选择 ZIP 模型核对包';
    else if (!file.size || file.size > 12 * 1024 * 1024) state.error = '出图包必须非空，且不超过 12 MB';
    else if (projectIsClosed(project) || typeof accessCan === 'function' && !accessCan('engineering')) state.error = '当前项目不能导入出图包';
    if (state.error) { replacePanel(project.id); return; }
    state.busy = true; state.message = '正在读取出图包…'; replacePanel(project.id);
    file.arrayBuffer().then(buffer => {
      if (!visible(project.id)) throw new Error('项目已切换，请返回原项目重试');
      const bytes = new Uint8Array(buffer); let binary = '';
      for (let offset = 0; offset < bytes.length; offset += 8192)
        binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
      return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', endpoint(project.id) + '/import');
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.timeout = 180000;
        xhr.upload.onprogress = event => { if (!event.lengthComputable) return; state.progress = Math.round(event.loaded / event.total * 100); state.message = `正在上传 ${state.progress}%`; replacePanel(project.id); };
        xhr.onload = () => {
          let data; try { data = JSON.parse(xhr.responseText); } catch { reject(new Error('服务器响应无效，请重新读取当前项目')); return; }
          if (xhr.status < 200 || xhr.status >= 300) reject(new Error(data.error || '导入失败'));
          else resolve(data);
        };
        xhr.onerror = () => reject(new Error('连接中断，请检查本地服务后重试'));
        xhr.ontimeout = () => reject(new Error('处理时间较长，请先刷新核对图，确认是否已经导入'));
        xhr.send(JSON.stringify({filename:file.name, content_base64:btoa(binary), expected_revision:project.revision}));
      });
    }).then(() => { state.message = '出图包已提交，正在读取结果…'; return load(project, true); })
      .catch(error => { state.error = error.message || '导入失败，请重试'; })
      .finally(() => { state.busy = false; replacePanel(project.id); });
  }

  document.addEventListener('click', event => {
    const button = event.target.closest?.('[data-round1-action]');
    if (!button || button.getAttribute('aria-disabled') === 'true') return;
    const project = typeof currentProject === 'function' ? currentProject() : null;
    if (!project || !visible(project.id) || button.closest('.round1-panel')?.dataset.project !== project.id) return;
    if (button.dataset.round1Action === 'retry') void load(project, true);
    if (button.dataset.round1Action === 'upload') button.closest('.round1-panel')?.querySelector('.round1-file')?.click();
  });
  document.addEventListener('change', event => {
    if (!event.target.matches?.('.round1-file')) return;
    const project = typeof currentProject === 'function' ? currentProject() : null;
    if (project?.id === event.target.closest('.round1-panel')?.dataset.project)
      uploadFile(event.target.files?.[0], project);
  });
  return {panel, load, normalize, assetURL, renderData};
})();
