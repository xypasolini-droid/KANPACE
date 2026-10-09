/* Local instance accounts. Works before /api/state is available. */
let accessState = null;
let accessLoading = null;
const accessEscape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
function accessCan(permission) {
  if (!accessState || !accessState.enabled) return true;
  const role = accessState.roles.find(item => item.id === accessState.user?.role);
  return !!role && (role.permissions.includes('*') || role.permissions.includes(permission));
}
async function accessRequest(path, data) {
  return globalThis.KanpaceHttp.request(path, data);
}
function accessRoleLabel(role) { return accessState?.roles?.find(item => item.id === role)?.label || role; }
function accessLoginForm() {
  return `<form data-access-form="login"><label>账号<input name="username" autocomplete="username" required maxlength="64" autofocus></label><label>密码<input name="password" type="password" autocomplete="current-password" required maxlength="256"></label><p class="access-form-error" role="alert"></p><button class="access-primary" type="submit">登录</button></form>`;
}
function accessClearSessionData() {
  window.KanpaceDailyWorkflow?.reset();
  window.KanpaceOrderWorkflow?.reset();
  window.KanpaceAgent?.reset();
  window.KanpaceIntelligence?.reset();
  if (typeof refreshToken !== 'undefined') refreshToken++;
  if (typeof badgeMediaReset === 'function') badgeMediaReset();
  if (typeof taskReferencesReset === 'function') taskReferencesReset();
  if (typeof state !== 'undefined') state = null;
  if (typeof quote !== 'undefined') quote = null;
  if (typeof operationsReset === 'function') operationsReset();
  if (typeof operationsReadinessReset === 'function') operationsReadinessReset();
  if (typeof operationsSchedulingReset === 'function') operationsSchedulingReset();
  if (typeof operationsExchangeReset === 'function') operationsExchangeReset();
  if (typeof planningReset === 'function') planningReset();
  if (typeof operationsCalibrationData !== 'undefined') operationsCalibrationData = null;
  if (typeof operationsCalibrationKey !== 'undefined') operationsCalibrationKey = '';
  if (typeof executionQueueById !== 'undefined') executionQueueById.clear();
  document.querySelector('#app')?.replaceChildren();
}
function accessGuardPage(requestedPage) {
  if (!accessState?.enabled || !accessState.user) return requestedPage;
  if (requestedPage === 'workflow' && ['worker','quality'].includes(accessState.user.role)) return 'tasks';
  if (!accessState.financial_access && typeof tab !== 'undefined' && tab === 'quote') tab = 'parts';
  if (!accessState.financial_access && ['quote','settings','owner'].includes(requestedPage)) return 'overview';
  return requestedPage;
}
function accessDecorateNavigation() {
  if (!accessState?.enabled || !accessState.user) return;
  const financial = accessState.financial_access;
  document.querySelectorAll('a[href]').forEach(link => {
    const href = link.getAttribute('href');
    if (['worker','quality'].includes(accessState.user.role) && /(?:#|&)page=workflow(?:&|$)/.test(href)) link.hidden = true;
    if (!financial && (href === '/bi/index.html' || /(?:#|&)page=(?:quote|settings|owner)(?:&|$)/.test(href))) link.hidden = true;
  });
  document.querySelectorAll('[data-action="tab"][data-tab="quote"],[data-action="project-costs"]').forEach(button => { button.hidden = !financial; });
  const userBox = document.querySelector('.sidebar-foot .user');
  if (userBox) userBox.innerHTML = `<span class="avatar">${accessEscape(accessState.user.name.slice(0,1))}</span><div><strong>${accessEscape(accessState.user.name)}</strong><small>${accessEscape(accessRoleLabel(accessState.user.role))}</small></div>`;
}
function accessRequireLogin() {
  if (document.querySelector('#access-login-overlay')) return;
  accessClearSessionData();
  const modal = document.querySelector('#modal');
  if (modal?.open) modal.close();
  modal?.replaceChildren();
  const app = document.querySelector('#app');
  if (app) { app.inert = true; app.setAttribute('aria-hidden', 'true'); }
  const overlay = document.createElement('main'); overlay.id = 'access-login-overlay';
  overlay.innerHTML = `<section class="access-login-card" aria-label="登录 KANPACE"><div class="access-brand">KANPACE</div><h1>登录工作空间</h1><p class="access-muted">使用这台服务器配置的账号</p>${accessLoginForm()}</section>`;
  document.body.append(overlay);
  overlay.querySelector('input')?.focus();
}
function accessCloseLogin() {
  document.querySelector('#access-login-overlay')?.remove();
  const app = document.querySelector('#app');
  if (app) { app.inert = false; app.removeAttribute('aria-hidden'); }
}
async function ensureAccessState(force = false) {
  if (accessState && !force) return accessState;
  if (accessLoading && !force) return accessLoading;
  accessLoading = accessRequest('/api/access').then(result => {
    accessState = result;
    if (result.enabled && !result.user) accessRequireLogin();
    else accessDecorateNavigation();
    return result;
  }).finally(() => { accessLoading = null; });
  return accessLoading;
}
function accessControlView() {
  if (!accessState) { ensureAccessState().then(() => { if (typeof render === 'function') render(); }).catch(() => {}); return '<section class="access-panel">正在读取账号设置…</section>'; }
  const s = accessState;
  if (!s.enabled) return `<section class="access-panel"><div class="access-eyebrow">账号与权限</div><h2>本机单操作者</h2><p>启用账号后，可按岗位分配操作权限，工人账号关联本人任务。</p><p class="access-muted">项目与原始文件在同一实例内共享，不按工厂隔离。尚未启用账号权限。</p><button class="access-primary" data-access-action="setup">创建管理员并启用</button></section>`;
  if (!s.user) { accessRequireLogin(); return '<section class="access-panel">请先登录工作空间。</section>'; }
  const admin = s.user.role === 'admin';
  return `<section class="access-panel"><div class="access-page-heading"><div><div class="access-eyebrow">账号与权限</div><h2>${accessEscape(s.user.name)} <span class="access-role">${accessEscape(accessRoleLabel(s.user.role))}</span></h2><p class="access-muted">${accessEscape(s.notice)}</p></div><button class="access-secondary" data-access-action="logout">退出登录</button></div></section>${admin ? `<section class="access-panel"><div class="access-page-heading"><h3>本机账号</h3><button class="access-primary" data-access-action="create-user">添加账号</button></div><div class="access-table-wrap"><table class="access-table"><thead><tr><th>人员 / 账号</th><th>角色</th><th>关联人员</th><th>状态</th><th></th></tr></thead><tbody>${(s.users || []).map(user => `<tr><td><strong>${accessEscape(user.name)}</strong><div class="access-muted">${accessEscape(user.username)}</div></td><td>${accessEscape(accessRoleLabel(user.role))}</td><td>${accessEscape(s.people?.find(p => p.id === user.person_id)?.name || '—')}</td><td>${user.active ? '启用' : '停用'}</td><td><button class="access-secondary" data-access-action="edit-user" data-access-id="${accessEscape(user.id)}">编辑</button></td></tr>`).join('')}</tbody></table></div></section>` : ''}<section class="access-panel"><h3>岗位操作范围</h3><div class="access-roles">${s.roles.map(role => `<article><strong>${accessEscape(role.label)}</strong><p>${accessEscape(({admin:'账号管理与全部业务操作',supervisor:'生产安排、资源、质量、成本与交付',technical:'图纸工艺、项目流程、排产与任务安排',warehouse:'物料、开工条件、异常与分批交付',quality:'质量检验、返工及本人任务报工',worker:'仅分派给本人的任务报工',owner:'只读查看，包含经营与财务数据'})[role.id])}</p></article>`).join('')}</div><p class="access-muted">结构化成本与财务仅管理员、主管和老板查看角色可读。共享原文件仍可能包含价格信息。</p></section>`;
}
function accessShowAccountForm(user = null, setup = false) {
  const dialog = document.createElement('dialog'); dialog.className = 'access-dialog';
  dialog.innerHTML = `<form data-access-form="${setup ? 'setup' : 'user'}"${user ? ` data-access-id="${accessEscape(user.id)}"` : ''}><div class="access-page-heading"><h2>${setup ? '创建本机管理员' : user ? '编辑账号' : '添加账号'}</h2><button type="button" class="access-close" data-access-action="close-dialog" aria-label="关闭">×</button></div>${setup ? '<p class="access-muted">保存后启用登录，其他浏览器需要账号才能访问业务数据。</p>' : ''}<label>姓名<input name="name" value="${accessEscape(user?.name || '')}" autocomplete="name" required maxlength="100"></label><label>账号<input name="username" value="${accessEscape(user?.username || '')}" autocomplete="off" pattern="[A-Za-z0-9_.@-]{3,64}" required maxlength="64" ${user ? 'readonly' : ''}></label><label>${user ? '重置密码（留空保留）' : '密码'}<input name="password" type="password" autocomplete="new-password" minlength="10" maxlength="256" ${user ? '' : 'required'}></label>${setup ? '' : `<label>岗位角色<select name="role">${accessState.roles.map(role => `<option value="${role.id}" ${role.id === (user?.role || 'worker') ? 'selected' : ''}>${accessEscape(role.label)}</option>`).join('')}</select></label><label>关联人员<select name="person_id"><option value="">未关联</option>${(accessState.people || []).map(person => `<option value="${accessEscape(person.id)}" ${person.id === user?.person_id ? 'selected' : ''}>${accessEscape(person.name)}</option>`).join('')}</select></label><p class="access-muted">工人和质检账号必须关联人员档案。</p>${user ? `<label class="access-checkbox"><input name="active" type="checkbox" ${user.active ? 'checked' : ''}>启用账号</label>` : ''}`}
  <p class="access-form-error" role="alert"></p><button type="submit" class="access-primary">${setup ? '创建并启用' : '保存账号'}</button></form>`;
  document.body.append(dialog); dialog.addEventListener('close', () => dialog.remove(), {once:true}); dialog.showModal();
}
async function accessReloadAfterLogin() {
  accessClearSessionData();
  await ensureAccessState(true);
  if (!accessState.user) return;
  if (typeof page !== 'undefined') page = 'overview';
  if (typeof tab !== 'undefined') tab = 'parts';
  if (typeof projectId !== 'undefined') projectId = '';
  history.replaceState(null, '', '#page=overview&tab=parts');
  if (typeof refresh === 'function') await refresh();
  accessDecorateNavigation();
  accessCloseLogin();
}
document.addEventListener('submit', async event => {
  const form = event.target.closest('[data-access-form]'); if (!form) return;
  event.preventDefault();
  const button = form.querySelector('[type="submit"]'); if (button.disabled) return;
  button.disabled = true; const errorBox = form.querySelector('.access-form-error'); errorBox.textContent = '';
  const data = Object.fromEntries(new FormData(form)); const kind = form.dataset.accessForm;
  try {
    if (kind === 'login' || kind === 'setup') {
      await accessRequest('/api/access/' + kind, data);
      form.querySelector('[name="password"]').value = '';
      form.closest('dialog')?.close();
      await accessReloadAfterLogin();
    } else {
      const user = accessState.users.find(item => item.id === form.dataset.accessId);
      if (user) Object.assign(data, {id:user.id, expected_version:user.version, active:form.elements.active.checked});
      await accessRequest('/api/access/users', data);
      form.querySelector('[name="password"]').value = '';
      form.closest('dialog')?.close();
      await ensureAccessState(true);
      if (typeof render === 'function') render();
    }
  } catch (error) { errorBox.textContent = error.message; }
  finally { button.disabled = false; }
});
document.addEventListener('click', async event => {
  const button = event.target.closest('[data-access-action]'); if (!button) return;
  const action = button.dataset.accessAction;
  if (action === 'setup') return accessShowAccountForm(null, true);
  if (action === 'create-user') return accessShowAccountForm();
  if (action === 'edit-user') return accessShowAccountForm(accessState.users.find(user => user.id === button.dataset.accessId));
  if (action === 'close-dialog') return button.closest('dialog').close();
  if (action === 'logout') {
    button.disabled = true;
    try { await accessRequest('/api/access/logout', {}); accessState = null; accessRequireLogin(); await ensureAccessState(true); }
    catch (error) { if (typeof showError === 'function') showError(error); }
    finally { button.disabled = false; }
  }
});
ensureAccessState().catch(() => {});
