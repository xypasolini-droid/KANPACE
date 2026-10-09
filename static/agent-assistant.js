/* KANPACE local command assistant. Business writes use fixed, versioned task APIs. */
(() => {
  'use strict';
  const pages = new Set(['overview','projects','drawing','tasks','quote','planning','readiness','owner','people','device','exchange','settings','templates','scheduling','calibration','access','manage']);
  const readActions = new Set(['navigate','open_upload','open_project','workflow_continue','schedule_preview']);
  const taskEndpoints = Object.freeze({task_start:'status',task_pause:'pause',task_resume:'resume',task_priority:'priority',task_assign:'assign'});
  const taskFields = Object.freeze({task_start:['note'],task_pause:['reason','note','handover_note'],task_resume:['note','handover_note'],task_priority:['reason'],task_assign:[]});
  function contextPrompts(){
    if(scopeProject && ['drawing','quote','templates'].includes(typeof page==='string'?page:'')) return ['检查当前订单的拆单依据','检查这单的漏项','下一步做什么'];
    if(['planning','scheduling'].includes(typeof page==='string'?page:''))return ['分析延期原因并比较排程','哪些任务缺料','今天先做什么'];
    if(typeof page==='string'&&page==='tasks')return ['哪些任务缺料','查看暂停任务','分析延期原因并比较排程'];
    return ['今天先做什么','检查当前订单的拆单依据','分析延期原因并比较排程'];
  }
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const symbol = name => typeof icon === 'function' ? icon(name) : '';
  const validId = value => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,128}$/.test(value);
  let dialog, transcript, input, form, scopeSelect, statusLine, trigger, entries = [], sequence = 0;
  let busy = false, scopeProject = '', scopeFactory = '', wholeFactory = false, pendingRead = null, session = 0, identity = '';

  function currentFactory() { return typeof workspaceType === 'string' ? workspaceType : 'cabinet'; }
  function projects() { return typeof workspaceProjects === 'function' ? workspaceProjects() : []; }
  function projectFor(id) { return projects().find(project => project.id === id); }
  function entryById(id) { return entries.find(entry => String(entry.id) === String(id)); }
  function businessDialogOpen() { return [...document.querySelectorAll('dialog[open]')].some(el => el !== dialog); }

  function mount() {
    if (dialog) return;
    dialog = document.createElement('dialog');
    dialog.id = 'kanpace-agent';
    dialog.className = 'ka-dialog';
    dialog.setAttribute('aria-labelledby', 'ka-title');
    dialog.innerHTML = `<div class="ka-layout"><header class="ka-head"><div><h2 id="ka-title">AI 工作助手</h2><span class="ka-mode">拆单 · 排产 · 现场</span></div><button type="button" class="ka-icon-button" data-ka="close" aria-label="关闭 AI 工作助手">${symbol('close')}</button></header><div class="ka-scope"><label for="ka-project">范围</label><select id="ka-project" aria-label="助手查询范围"></select><button type="button" class="ka-icon-button ka-reset" data-ka="clear" aria-label="开始新对话" title="开始新对话">${symbol('plus')}</button></div><div id="ka-transcript" class="ka-transcript" tabindex="0" aria-label="助手对话"></div><div class="ka-composer"><p id="ka-status" class="ka-status" role="status" aria-live="polite"></p><form id="ka-form"><label class="ka-input-label" for="ka-input">告诉助手你想做什么</label><textarea id="ka-input" rows="2" maxlength="1000" placeholder="例如：检查这张订单的拆单依据和漏项" aria-describedby="ka-input-help"></textarea><div class="ka-compose-foot"><small id="ka-input-help">Enter 发送 · Shift + Enter 换行</small><button type="submit" class="ka-send" aria-label="发送指令">发送 ${symbol('arrow')}</button></div></form></div></div>`;
    document.body.append(dialog);
    transcript = dialog.querySelector('#ka-transcript');
    input = dialog.querySelector('#ka-input');
    form = dialog.querySelector('#ka-form');
    scopeSelect = dialog.querySelector('#ka-project');
    statusLine = dialog.querySelector('#ka-status');
    dialog.addEventListener('click', onClick);
    dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
    dialog.addEventListener('close', restoreFocus);
    form.addEventListener('submit', event => { event.preventDefault(); ask(input.value); });
    input.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault(); ask(input.value);
      }
    });
    scopeSelect.addEventListener('change', () => {
      scopeProject = scopeSelect.value; wholeFactory = !scopeProject;
      entries = []; render(); announce(scopeProject ? '已切换到所选项目' : '已切换到当前工厂'); input.focus();
    });
  }

  function syncScope() {
    const options = projects();
    if (scopeProject && !options.some(project => project.id === scopeProject)) scopeProject = '';
    const factoryName = typeof workspaceProfile === 'function' ? workspaceProfile().name : '当前工厂';
    scopeSelect.innerHTML = `<option value="">${escape(factoryName)} · 全部项目</option>` + options.map(project => `<option value="${escape(project.id)}">${escape(project.name)}${project.is_closed || ['shipped','completed'].includes(project.fulfillment_status) ? ' · 已结束' : ''}</option>`).join('');
    scopeSelect.value = scopeProject;
  }

  function open(options = {}) {
    if (businessDialogOpen() || !state || document.querySelector('#access-login-overlay')) return false;
    const explicit=Object.hasOwn(options,'projectId');
    if(explicit&&options.projectId!==''&&(!validId(options.projectId)||!projectFor(options.projectId)))return false;
    mount();
    if (dialog.open) { input.focus(); return true; }
    trigger = document.activeElement;
    const factory = currentFactory();
    const selected = typeof currentProject === 'function' ? currentProject()?.id || '' : '';
    const globalPage=typeof page==='string'&&['overview','projects','owner','people','exchange','manage'].includes(page);
    const nextProject = explicit?options.projectId:(globalPage?'':selected);
    if (scopeFactory !== factory || scopeProject !== nextProject) entries = [];
    scopeFactory = factory; scopeProject = nextProject;
    if(explicit)wholeFactory=!nextProject;
    syncScope(); render(); dialog.showModal(); input.focus();
    if (typeof options.prompt === 'string' && options.prompt.trim()) input.value = options.prompt.slice(0,1000);
    return true;
  }

  function close() {
    if (pendingRead) pendingRead.abort();
    dialog?.close();
  }

  function restoreFocus() {
    if (businessDialogOpen()) return;
    const usable = node => node?.isConnected && node !== document.body && node.getClientRects().length > 0;
    const target = usable(trigger) ? trigger : [...document.querySelectorAll('[data-action="agent-open"]')].find(usable);
    target?.focus({preventScroll:true}); trigger = null;
  }

  function announce(text) { if (statusLine) statusLine.textContent = text; }
  function setBusy(value, label = '') {
    busy = value;
    if (!dialog) return;
    dialog.setAttribute('aria-busy', String(value));
    scopeSelect.disabled = value;
    for (const control of dialog.querySelectorAll('button, .ka-action-card input, .ka-action-card textarea, .ka-action-card select')) {
      if (control.dataset.ka !== 'close') control.disabled = value || control.dataset.locked === 'true';
    }
    announce(label);
  }

  function introduction() {
    return `<section class="ka-welcome"><h3>想先处理哪件事？</h3><p>检查本单缺项、比较排程，带着依据到下一步。</p><div class="ka-prompts">${contextPrompts().map(text => `<button type="button" data-ka="prompt" data-prompt="${escape(text)}"><span>${escape(text)}</span>${symbol('arrow')}</button>`).join('')}</div></section>`;
  }

  function fieldMarkup(field, action, entry, index) {
    if (!taskFields[action.type]?.includes(field.key)) return '';
    const id = `ka-field-${entry.id}-${index}-${field.key}`;
    const value = typeof field.value === 'string' ? field.value : '';
    const required = field.required ? 'required' : '';
    const label = `<label for="${id}">${escape(field.label || field.key)}${field.required ? '<span class="ka-required">必填</span>' : ''}</label>`;
    if (field.type === 'select') return `<div class="ka-field">${label}<select id="${id}" name="${escape(field.key)}" ${required}>${(field.options || []).slice(0,30).map(option => `<option value="${escape(option.value)}" ${String(option.value) === value ? 'selected' : ''}>${escape(option.label)}</option>`).join('')}</select></div>`;
    if (field.type === 'text') return `<div class="ka-field">${label}<input id="${id}" name="${escape(field.key)}" value="${escape(value)}" maxlength="1000" ${required}></div>`;
    return `<div class="ka-field">${label}<textarea id="${id}" name="${escape(field.key)}" rows="2" maxlength="${field.key === 'handover_note' ? 2000 : 1000}" ${required}>${escape(value)}</textarea></div>`;
  }

  function actionMarkup(action, entry, index) {
    if (!readActions.has(action.type) && !Object.hasOwn(taskEndpoints, action.type)) return '';
    const isWrite = Object.hasOwn(taskEndpoints, action.type);
    const finished = entry.completed?.[index];
    const locked = entry.expired || finished;
    const project = projectFor(action.projectId);
    const task = typeof state !== 'undefined' ? state?.tasks?.find(task => task.id === action.taskId) : null;
    const detail = [project?.name, task?.title || task?.name].filter(Boolean).join(' · ');
    const assignee = typeof state !== 'undefined' ? state?.people?.find(person => person.id === action.payload?.person_id)?.name : '';
    const consequence = ({task_start:'开始这项工序，并记录执行工时。',task_pause:'暂停这项任务，保留已完成数量和本次交接。',task_resume:'恢复为进行中，保留已完成数量。',task_priority:`优先级改为${['普通','优先','加急','特急'][action.payload?.priority] || '紧急'}，正在执行的任务继续进行。`,task_assign:assignee ? `改由${assignee}负责这项任务。` : '更新这项任务的负责人。'})[action.type];
    if (!isWrite) return `<button type="button" class="ka-shortcut" data-ka="action" data-entry="${entry.id}" data-index="${index}" ${locked || entry.schedule ? 'disabled data-locked="true"' : ''}><span><strong>${escape(finished || action.label)}</strong>${action.description ? `<small>${escape(action.description)}</small>` : ''}</span>${symbol('arrow')}</button>`;
    return `<form class="ka-action-card" data-entry="${entry.id}" data-index="${index}"><div class="ka-action-heading"><span class="ka-action-tag">${finished ? '已执行' : '待确认'}</span><h4>${escape(String(action.label).replace(/^确认/,''))}</h4></div>${detail ? `<p class="ka-action-target">${escape(detail)}</p>` : ''}<p class="ka-action-consequence">${escape(consequence)}</p>${!locked ? (action.fields || []).slice(0,8).map(field => fieldMarkup(field, action, entry, index)).join('') : ''}<div class="ka-action-result" role="status">${finished ? escape(finished) : entry.expired ? '请重新查询，获取最新操作。' : ''}</div>${locked ? '' : `<button type="submit" class="ka-confirm">${escape(String(action.label).startsWith('确认') ? action.label : '确认'+action.label)}</button>`}</form>`;
  }

  function workflowMarkup(workflow, entry) {
    if (!workflow || !Array.isArray(workflow.steps)) return '';
    return `<div class="ka-workflow"><p class="ka-caption">本地生产分析</p><ol class="ka-steps">${workflow.steps.slice(0,8).map(step => `<li><strong>${escape(step.title)}</strong><p>${escape(step.detail)}</p></li>`).join('')}</ol>${workflow.model_summary ? `<p class="ka-caption">本机模型整理（供参考）：${escape(workflow.model_summary)}</p>` : ''}${workflow.causes?.length ? `<details class="ka-evidence" open><summary>任务依据 · ${workflow.causes.length} 项</summary>${workflow.causes.slice(0,12).map(item => `<article><strong>${escape(item.title)}</strong><ul>${(item.evidence || []).map(line => `<li>${escape(line)}</li>`).join('')}</ul></article>`).join('')}${workflow.causes.length > 12 ? `<p>另有 ${workflow.causes.length-12} 项，可进入任务页查看。</p>` : ''}</details>` : ''}${workflow.candidates?.length ? `<div class="ka-candidates">${workflow.candidates.slice(0,2).map(candidate => `<article><h4>${escape(candidate.label)}</h4><details class="ka-evidence"><summary>计算依据</summary><p class="ka-caption">${escape(candidate.method)}</p></details><p>可排 <b>${Number(candidate.summary?.scheduled) || 0}</b> 项 · 未排 <b>${Number(candidate.summary?.unplaced) || 0}</b> 项 · 预计逾期 <b>${Number(candidate.summary?.late_tasks) || 0}</b> 项</p><p>预计完工：${escape(candidate.summary?.finish_date || '待确认')}</p>${candidate.error ? `<p class="ka-error">${escape(candidate.error)}</p>` : ''}${scheduleRows(candidate.rows)}${unplacedRows(candidate.unplaced)}</article>`).join('')}</div>` : ''}${workflow.sources?.length ? `<details class="ka-evidence"><summary>查看来源 · ${workflow.sources.length} 条</summary><div class="ka-source-links">${workflow.sources.slice(0,60).map((source,index) => `<button type="button" class="ka-text-button" data-ka="source" data-entry="${entry.id}" data-index="${index}" ${entry.expired ? 'disabled data-locked="true"' : ''}>${escape(source.label)}</button>`).join('')}</div></details>` : ''}</div>`;
  }

  function scheduleRows(rows = []) {
    if (!rows.length) return '';
    return `<div class="ka-table-wrap"><table><thead><tr><th>工序</th><th>开始</th><th>完成</th></tr></thead><tbody>${rows.slice(0,10).map(row => `<tr><td>${escape(row.title)}</td><td>${escape(String(row.start_at||'').replace('T',' '))}</td><td>${escape(String(row.ready_at||'').replace('T',' '))}</td></tr>`).join('')}</tbody></table>${rows.length > 10 ? `<p>另有 ${rows.length-10} 道工序。</p>` : ''}</div>`;
  }

  function unplacedRows(rows = []) {
    return rows.length ? `<details class="ka-evidence"><summary>未排原因 · ${rows.length} 项</summary>${rows.slice(0,30).map(row => `<p><b>${escape(row.title)}</b>：${escape((row.blockers || []).join('；'))}</p>`).join('')}</details>` : '';
  }

  function scheduleMarkup(entry) {
    const scenario = entry.schedule;
    if (!scenario) return '';
    const locked = entry.expired || entry.scheduleResult;
    return `<section class="ka-schedule"><h4>排程预览：${escape(scenario.name)}</h4><p>可排 ${Number(scenario.summary?.scheduled)||0} 项 · 未排 ${Number(scenario.summary?.unplaced)||0} 项 · 已冻结 ${Number(scenario.summary?.frozen_plans)||0} 项</p>${scheduleRows(scenario.rows)}${unplacedRows(scenario.unplaced)}${scenario.impact?.length ? `<details class="ka-evidence" open><summary>调整影响 · ${scenario.impact.length} 项</summary>${scenario.impact.slice(0,30).map(row => `<p>${escape(row.title)}：${escape(row.before_end || '未排')} → ${escape(row.after_end || '未排')}</p>`).join('')}</details>` : '<p>本次预览没有登记额外改期差异。</p>'}<form class="ka-schedule-form" data-entry="${entry.id}">${!locked && scenario.rows?.length ? '<label>采用说明<textarea name="note" rows="2" maxlength="1000" required placeholder="说明采用依据或现场安排"></textarea></label><button type="submit" class="ka-confirm">确认采用这份排程</button>' : ''}<p class="ka-schedule-result" role="status">${escape(entry.scheduleResult || (entry.expired ? '请重新分析最新资料。' : '确认采用后写入排程，不会自动开工。'))}</p></form></section>`;
  }

  function renderEntry(entry) {
    const response = entry.response;
    return `<section class="ka-turn" data-turn="${entry.id}"><p class="ka-user-message">${escape(entry.question)}</p>${entry.error ? `<div class="ka-error" role="alert"><p>${escape(entry.error)}</p><button type="button" class="ka-text-button" data-ka="retry" data-entry="${entry.id}">重新查询</button></div>` : response ? `<div class="ka-answer"><p class="ka-answer-text">${escape(response.message)}</p>${workflowMarkup(response.workflow,entry)}${scheduleMarkup(entry)}${response.results?.length ? `<div class="ka-results">${response.results.slice(0,20).map((result,index) => `<button type="button" class="ka-result" data-ka="result" data-entry="${entry.id}" data-index="${index}" ${entry.expired ? 'disabled data-locked="true"' : ''}><span class="ka-result-kind">${({task:'任务',project:'订单',check:'待处理',source:'依据'})[result.kind] || '记录'}</span><span class="ka-result-body"><strong>${escape(result.title)}</strong><small>${escape(result.detail)}</small></span>${symbol('chevron')}</button>`).join('')}</div>` : ''}${response.truncated ? '<p class="ka-caption">结果较多，可补充项目名称或工种缩小范围。</p>' : ''}${(response.actions || []).slice(0,12).map((action,index) => actionMarkup(action,entry,index)).join('')}${response.suggestions?.length && !entry.expired ? `<div class="ka-followups">${response.suggestions.slice(0,4).map(text => `<button type="button" data-ka="prompt" data-prompt="${escape(text)}">${escape(text)}</button>`).join('')}</div>` : ''}</div>` : '<p class="ka-thinking">正在查询…</p>'}</section>`;
  }

  function render() {
    transcript.innerHTML = entries.length ? entries.map(renderEntry).join('') : introduction();
    setBusy(busy);
    transcript.scrollTop = transcript.scrollHeight;
  }

  async function readMessage(payload, signal) {
    const result = await globalThis.KanpaceHttp.request('/api/agent/message', payload, {signal,errorMessage:'查询未完成'});
    if (!result || result.mode !== 'local_commands' || typeof result.message !== 'string' || !Array.isArray(result.results) || !Array.isArray(result.actions)) throw new Error('助手响应格式不正确，请刷新软件后重试。');
    return result;
  }

  async function ask(text, retryEntry = null) {
    const question = String(text || '').trim();
    if (busy || !question || question.length > 1000) return;
    if (scopeFactory !== currentFactory()) { entries = []; scopeFactory = currentFactory(); scopeProject = ''; syncScope(); }
    const history = entries.flatMap(entry => [{role:'user',content:entry.question},...(entry.response ? [{role:'assistant',content:entry.response.message}] : [])]).slice(-8).map(item => ({...item,content:item.content.slice(0,1000)}));
    for (const item of entries) item.expired = true;
    const entry = {id:++sequence,question,request:retryEntry?.request || {message:question,project_id:scopeProject || undefined,factory_type:scopeFactory,context:{page:typeof page === 'string' ? page : 'overview'},history}};
    entries.push(entry); entries = entries.slice(-8);
    input.value = ''; busy = true; render(); announce('正在查询');
    const controller = new AbortController(); pendingRead = controller;
    const activeSession = session;
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; controller.abort(); },60000);
    try {
      const response = await readMessage(entry.request,controller.signal);
      if (pendingRead !== controller) return;
      entry.response = response;
    } catch (error) {
      if (error.status === 401 && typeof accessRequireLogin === 'function') { accessRequireLogin(); return; }
      entry.error = error.name === 'AbortError' ? timedOut ? '查询超时，请重新查询。' : '查询已取消。' : error.code === 'NETWORK_UNAVAILABLE' || error instanceof TypeError ? '无法连接本地服务，请确认服务启动后重新查询。' : error.code === 'INVALID_RESPONSE' ? '本地服务响应异常，请重新查询。' : error.message;
    } finally {
      clearTimeout(timeout);
      if (activeSession !== session) return;
      if (pendingRead === controller) pendingRead = null;
      busy = false; render(); announce(entry.error ? '查询未完成' : '查询完成');
      if (dialog.open) input.focus();
    }
  }

  function checkedRoute(route = {}) {
    if (!pages.has(route.page)) throw new Error('这个页面暂不支持从助手打开。');
    const targetProject = route.projectId || scopeProject;
    if (targetProject && !projectFor(targetProject)) throw new Error('项目已不在当前工厂中，请重新查询。');
    const target={page:route.page,tab:['parts','tasks','quote','history'].includes(route.tab)?route.tab:'parts',projectId:targetProject||''};
    if(route.page==='readiness'&&['materials','issues','checks','inspections','deliveries'].includes(route.opTab))target.opTab=route.opTab;
    if(route.page==='tasks'&&['all','active','paused','urgent'].includes(route.taskFocus))target.taskFocus=route.taskFocus;
    return target;
  }

  function go(route) {
    const target = checkedRoute(route); close();
    if(target.opTab||target.taskFocus){
      const hash=new URLSearchParams({page:target.page,tab:target.tab,project:target.projectId});
      if(target.opTab){hash.set('opTab',target.opTab);hash.set('opProject',target.projectId);}
      if(target.taskFocus)hash.set('taskFocus',target.taskFocus);
      location.hash=hash.toString();
    }else navigate(target.page,target.tab,target.projectId);
  }

  async function openBusiness(action) {
    if (action.type === 'navigate') return go(action.route);
    if (action.type === 'open_project') {
      close(); await newProjectModal(); return;
    }
    const project = projectFor(action.projectId);
    if (!project || (typeof projectIsClosed === 'function' && projectIsClosed(project))) throw new Error('请选择一个进行中的项目上传图纸。');
    projectId = project.id;
    close(); navigate('drawing','parts',project.id); importModal(action.payload?.purpose === 'render' ? 'render' : 'engineering');
  }

  function schedulePayload(action) {
    const raw = action?.payload || {};
    if (!['cabinet','machinery','site'].includes(raw.factory_type) || raw.factory_type !== scopeFactory) throw new Error('排程场景已变化，请重新分析。');
    if (!Array.isArray(raw.task_ids) || !raw.task_ids.length || raw.task_ids.length > 300 || raw.task_ids.some(id => !validId(id) || !state?.tasks?.some(t => t.id === id && projectFor(t.project_id)))) throw new Error('排程任务不在当前可见范围，请重新分析。');
    if (raw.rush_task_ids?.some(id => !raw.task_ids.includes(id)) || !/^\d{4}-\d{2}-\d{2}$/.test(raw.start_date) || !Number.isInteger(raw.horizon_days) || raw.horizon_days < 1 || raw.horizon_days > 180) throw new Error('排程参数无效，请重新分析。');
    return {name:String(raw.name || '助手排程预览').slice(0,120), start_date:raw.start_date, horizon_days:raw.horizon_days,
      factory_type:raw.factory_type,task_ids:[...raw.task_ids],rush_task_ids:raw.rush_task_ids || [],overrides:[],
      ...(raw.engine === 'ortools' ? {engine:'ortools',time_limit_seconds:10,allow_fallback:false} : {})};
  }

  async function previewSchedule(entry, index) {
    if (busy || entry.expired || entry.schedule || entry.completed?.[index]) return;
    const data = schedulePayload(entry.response.actions[index]);
    setBusy(true,'正在生成可核对的排程预览');
    const activeSession = session;
    try {
      const result = await executionRequest('/api/scheduling/preview',data);
      if (session !== activeSession) return;
      if (!validId(result?.scenario?.id) || !Number.isInteger(result.scenario.version) || !Array.isArray(result.scenario.rows)) throw new Error('排程预览格式异常，请重新分析。');
      entry.schedule = result.scenario;
      entry.completed ||= {}; entry.completed[index] = '已生成预览';
      render(); announce('请核对工序安排与调整影响，再确认采用');
    } catch (error) {
      if (session !== activeSession) return;
      if (error.status === 401 && typeof accessRequireLogin === 'function') { accessRequireLogin(); return; }
      entry.expired = true; entry.error = '排程预览未完成：' + (error.message || '请重新分析'); render();
    } finally { if (session === activeSession) setBusy(false); }
  }

  async function applySchedule(entry, card) {
    if (busy || entry.expired || entry.scheduleResult || !card.reportValidity()) return;
    const scenario = entry.schedule;
    if (!validId(scenario?.id) || !Number.isInteger(scenario.version)) return;
    const note = String(card.elements.namedItem('note')?.value || '').trim();
    if (!note) return;
    setBusy(true,'正在采用排程');
    const activeSession = session;
    try {
      await executionRequest(`/api/scheduling/${encodeURIComponent(scenario.id)}/apply`,{expected_version:scenario.version,note:note.slice(0,1000)});
      if (session !== activeSession) return;
      entry.scheduleResult = '排程已采用，可到生产排程查看；任务执行状态保持不变。';
      for (const item of entries) item.expired = true;
      try { await refresh(); } catch { entry.scheduleResult += ' 页面刷新未完成，请刷新查看。'; }
      render(); announce('排程已采用');
    } catch (error) {
      if (session !== activeSession) return;
      if (error.status === 401 && typeof accessRequireLogin === 'function') { accessRequireLogin(); return; }
      entry.expired = true;
      entry.scheduleResult = error.status ? '未采用：' + error.message + '。请按最新资料重新分析。' : '采用结果待确认，请到生产排程核对，勿重复提交。';
      render();
    } finally { if (session === activeSession) setBusy(false); }
  }

  function writePayload(action, card) {
    const payload = action.payload || {};
    if (!validId(action.taskId) || !validId(action.projectId)) throw new Error('操作对象不完整，请重新查询。');
    const task = state?.tasks?.find(task => task.id === action.taskId && task.project_id === action.projectId);
    if (!task || !projectFor(action.projectId)) throw new Error('任务已不可用，请重新查询。');
    if (!Number.isInteger(payload.expected_execution_version) || payload.expected_execution_version < 0) throw new Error('操作缺少版本信息，请重新查询。');
    const data = {expected_execution_version:payload.expected_execution_version};
    for (const key of taskFields[action.type]) {
      const control = card.elements.namedItem(key);
      if (control) data[key] = String(control.value).trim();
      else if (typeof payload[key] === 'string') data[key] = payload[key].slice(0,key === 'handover_note' ? 2000 : 1000);
    }
    if (action.type === 'task_start') data.status = 'in_progress';
    if (action.type === 'task_pause') {
      data.reason = data.reason || payload.reason;
      if (!['material','quality','equipment','urgent','other'].includes(data.reason)) throw new Error('请选择有效的暂停分类。');
      if (!data.note || !data.handover_note) throw new Error('请填写暂停原因和交接说明。');
    }
    if (action.type === 'task_resume' && !data.note) throw new Error('请填写解除暂停的依据。');
    if (action.type === 'task_priority') {
      if (!Number.isInteger(payload.priority) || payload.priority < 0 || payload.priority > 3) throw new Error('任务优先级无效。');
      data.priority = payload.priority;
      if (!data.reason) throw new Error('请填写调整依据。');
    }
    if (action.type === 'task_assign') {
      if (!validId(payload.person_id)) throw new Error('负责人不明确，请重新查询。');
      data.person_id = payload.person_id;
    }
    return data;
  }

  async function execute(entry, index, card) {
    if (busy || entry.expired || entry.completed?.[index]) return;
    const action = entry.response.actions[index];
    if (!Object.hasOwn(taskEndpoints,action?.type)) return;
    if (!card.reportValidity()) return;
    const resultBox = card.querySelector('.ka-action-result');
    let data;
    try { data = writePayload(action,card); } catch (error) { resultBox.textContent = error.message; return; }
    setBusy(true,'正在保存');
    const activeSession = session;
    let saved = false;
    try {
      await executionRequest(`/api/tasks/${encodeURIComponent(action.taskId)}/${taskEndpoints[action.type]}`,data);
      if (activeSession !== session) return;
      saved = true;
      entry.completed ||= {}; entry.completed[index] = ({task_start:'任务已开始',task_pause:'任务已暂停',task_resume:'任务已恢复',task_priority:'优先级已调整',task_assign:'负责人已分配'})[action.type];
      for (const item of entries) item.expired = true;
      try { await refresh(); } catch { entry.completed[index] += '；页面刷新失败，请刷新查看最新状态。'; }
      render(); announce(entry.completed[index]);
      if (dialog.open && activeSession === session) input.focus();
    } catch (error) {
      if (activeSession !== session) return;
      if (error.status === 401 && typeof accessRequireLogin === 'function') { accessRequireLogin(); return; }
      entry.expired = true;
      const uncertain = !error.status;
      resultBox.textContent = uncertain ? '未能确认保存结果。请重新查询任务状态，再决定下一步。' : `未保存：${error.message}。请重新查询后操作。`;
      resultBox.setAttribute('role','alert');
      for (const control of card.querySelectorAll('button,input,textarea,select')) { control.disabled = true; control.dataset.locked = 'true'; }
      announce(uncertain ? '保存结果待确认' : '操作未保存');
    } finally {
      if (activeSession === session) setBusy(false,saved ? entry.completed[index] : '请重新查询任务状态');
    }
  }

  async function onClick(event) {
    const button = event.target.closest('button[data-ka]');
    if (!button) return;
    const action = button.dataset.ka;
    if (action === 'close') return close();
    if (busy) return;
    try {
      if (action === 'clear') { entries = []; render(); input.focus(); return; }
      if (action === 'prompt') return ask(button.dataset.prompt);
      const entry = entryById(button.dataset.entry);
      if (!entry) return;
      if (action === 'retry') return ask(entry.question,entry);
      if (entry.expired) return;
      const index = Number(button.dataset.index);
      if (action === 'action') {
        const selected = entry.response.actions[index];
        if (selected.type === 'schedule_preview') return await previewSchedule(entry,index);
        if (selected.type === 'workflow_continue') {
          if (!/^wf_[a-f0-9]{32}$/.test(selected.payload?.id) || !['compare','refresh','cancel'].includes(selected.payload?.decision)) throw new Error('分析记录无效，请重新分析。');
          const resolved = entry.response.scope || {projectId:scopeProject,factoryType:scopeFactory};
          if (resolved.factoryType !== scopeFactory || (resolved.projectId && (!validId(resolved.projectId) || !projectFor(resolved.projectId)))) throw new Error('分析范围已变化，请重新分析。');
          return await ask('继续延期分析',{request:{message:'继续延期分析',project_id:resolved.projectId || undefined,
            factory_type:scopeFactory,workflow:{id:selected.payload.id,decision:selected.payload.decision}}});
        }
        return await openBusiness(selected);
      }
      if (action === 'source') {
        const source = entry.response.workflow?.sources?.[index];
        if (source) return go({page:source.page,projectId:source.project_id});
      }
      if (action === 'result') {
        const result = entry.response.results[index];
        if (result.followup) return ask(result.followup);
        if (result.kind === 'task' && validId(result.id) && state?.tasks?.some(task => task.id === result.id)) {
          const task = state.tasks.find(task => task.id === result.id);
          if (!projectFor(task.project_id)) throw new Error('任务不在当前工厂中，请重新查询。');
          projectId = task.project_id;
          close(); navigate('tasks','parts',projectId); await taskModal(result.id); return;
        }
        return go(result.route);
      }
    } catch (error) { announce(error.message); }
  }

  document.addEventListener('submit', event => {
    const scheduleCard = event.target.closest('#kanpace-agent .ka-schedule-form');
    if (scheduleCard) {
      event.preventDefault(); event.stopPropagation();
      const scheduleEntry = entryById(scheduleCard.dataset.entry);
      if (scheduleEntry) applySchedule(scheduleEntry,scheduleCard);
      return;
    }
    const card = event.target.closest('#kanpace-agent .ka-action-card');
    if (!card) return;
    event.preventDefault(); event.stopPropagation();
    const entry = entryById(card.dataset.entry);
    if (entry) execute(entry,Number(card.dataset.index),card);
  },true);
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-action="agent-open"]');
    if (!button) return;
    event.preventDefault();
    const options={prompt:button.dataset.agentPrompt || button.dataset.prompt};
    if(Object.hasOwn(button.dataset,'agentProject'))options.projectId=button.dataset.agentProject;
    open(options);
  });
  document.addEventListener('keydown', event => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== 'k' || event.isComposing || businessDialogOpen()) return;
    event.preventDefault(); open();
  });
  function reset() {
    session++; pendingRead?.abort(); pendingRead = null; entries = []; scopeProject = ''; scopeFactory = ''; wholeFactory = false; busy = false;
    if (dialog) { dialog.close(); input.value = ''; render(); }
  }
  function afterRender() {
    const nextIdentity = typeof accessState !== 'undefined' && accessState?.enabled ? `${accessState.user?.id || 'signed-out'}:${accessState.user?.role || ''}` : 'local';
    if (identity && identity !== nextIdentity) reset();
    identity = nextIdentity;
    if (scopeFactory && scopeFactory !== currentFactory()) reset();
    if (!state || document.querySelector('#access-login-overlay')) return;
    const hash = new URLSearchParams(location.hash.slice(1));
    if (hash.get('assistant') === '1' && !businessDialogOpen()) {
      hash.delete('assistant'); history.replaceState(null,'',`${location.pathname}${location.search}#${hash}`);
      open();
    }
  }
  window.KanpaceAgent = Object.freeze({open,close,afterRender,reset});
})();
