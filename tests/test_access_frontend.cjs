const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createClient} = require('../static/core/http-client.js');

const accessSource = fs.readFileSync(path.join(__dirname, '../static/access-control.js'), 'utf8');
const appSource = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
// Execute the app's own entry points, without starting device polling or rendering unrelated pages.
function appLine(prefix) {
  const matches = appSource.split('\n').filter(line => line.startsWith(prefix));
  assert.equal(matches.length, 1, `App entry point is present exactly once: ${prefix}`);
  return matches[0];
}
const requestStart = appSource.indexOf('async function requestJson(');
const requestEnd = appSource.indexOf('function connectionBanner(', requestStart);
assert(requestStart >= 0 && requestEnd > requestStart);
const appEntries = [
  appSource.slice(requestStart, requestEnd),
  appLine('function showError('),
  appLine('function stepApprovalFields('),
  appLine('function partModal('),
  appLine('async function refresh('),
  appLine('async function readWorkspaceState('),
  `async function savePartThroughHandler(b) { const a='save-part'; const p=currentProject(); ${appLine("if(a==='save-part')")} }`,
].join('\n');
const tests = [];
const test = (name, run) => tests.push([name, run]);
const roles = [
  {id:'admin', label:'管理员', permissions:['*']},
  {id:'technical', label:'技术', permissions:['projects', 'parts', 'planning']},
  {id:'owner', label:'老板查看', permissions:[]},
  {id:'supervisor', label:'主管', permissions:['costs', 'parts']},
];
const auth = role => ({enabled:true, user:{id:role, name:role, role}, roles, financial_access:['admin','owner','supervisor'].includes(role)});
const plain = value => JSON.parse(JSON.stringify(value));
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
}

async function fixture(role='technical') {
  const elements = new Map();
  const listeners = {};
  function node(id='') {
    return {
      id, innerHTML:'', textContent:'', inert:false, hidden:false, open:false, attrs:{}, dataset:{},
      setAttribute(key, value) { this.attrs[key] = value; },
      removeAttribute(key) { delete this.attrs[key]; },
      getAttribute(key) { return this.attrs[key]; },
      replaceChildren() { this.innerHTML = ''; this.textContent = ''; },
      remove() { elements.delete('#' + this.id); },
      close() { this.open = false; },
      querySelector(selector) { return selector === 'input' ? {focus(){}} : null; },
      append(child) { if (child.id) elements.set('#' + child.id, child); },
    };
  }
  const app = node('app'); app.innerHTML = '<section>老板合同金额 918273</section>';
  const modal = node('modal'); modal.open = true; modal.innerHTML = '<form>单价 918273</form>';
  const partForm = {dataset:{id:'part1', add:'false'}, reportValidity:()=>true};
  elements.set('#app', app); elements.set('#modal', modal); elements.set('#part-form', partForm);
  const links = ['#page=quote&tab=quote', '#page=settings', '#page=owner', '/bi/index.html', '#page=tasks'].map(href => {
    const link = node(); link.attrs.href = href; return link;
  });
  const financialButtons = [node(), node()];
  const resetNames = ['operationsReset','operationsReadinessReset','operationsSchedulingReset','operationsExchangeReset','planningReset'];
  const project = {id:'project1', name:'测试订单', revision:3};
  const c = {
    console, URLSearchParams, Map, Set, location:{hash:"#page=drawing"},
    document:{
      querySelector:selector => elements.get(selector) || null,
      querySelectorAll:selector => selector === 'a[href]' ? links : selector.includes('project-costs') ? financialButtons : [],
      createElement:() => node(), body:node('body'),
      addEventListener:(type, handler) => (listeners[type] ||= []).push(handler),
    },
    requests:[], resetCalls:[], toasts:[], notices:[], values:{}, renders:0, agentResets:0,
    window:{KanpaceAgent:{reset(){c.agentResets++;}}},
    state:{projects:[project], people:[], tasks:[]}, quote:{total:918273}, refreshToken:1, stateRefreshInFlight:0, lastStateRefreshAt:0,
    operationsCalibrationData:{secret:918273}, operationsCalibrationKey:'old-financial-key',
    executionQueueById:new Map([['old',{contract:918273}]]),
    page:'drawing', tab:'parts', projectId:project.id, workspaceType:'cabinet', trades:[],
    pendingTaskDeepLink:'', selectedPart:'', connectionMessage:'本地服务未连接',
    localStorage:{setItem(){}}, history:{replaceState(){}},
    authReply:auth(role),
    stateReply:{projects:[project], people:[], tasks:[]},
    quoteReply:{total:1000},
    partRows:[{id:'part1', name:'柜体侧板', material:'木板', category:'wood', quantity:2, unit_price:918273, pricing_unit:'piece'}],
    categoryText:{wood:'木作'},
    esc:value => String(value ?? '').replace(/[&<>"]/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;'}[char])),
    icon:()=>'', button:(label, action)=>`<button data-action="${action}">${label}</button>`,
    $:selector => elements.get(selector) || null,
    currentProject:()=>c.state?.projects?.[0] || project,
    parts:()=>c.partRows,
    openModal:(title, body, footer) => { c.modalContent = {title, body, footer}; },
    formValues:()=>({...c.values}),
    submitOperation:async(_button, operation)=>operation(),
    syncWorkspaceProject(){},
    render:()=>{ c.renders++; },
    clearConnectionNotice(){},
    showConnectionNotice:error=>c.notices.push(error.message),
    toast:message=>c.toasts.push(message),
    fetch:async(url, options={})=>{
      c.requests.push({url, options, data:options.body ? JSON.parse(options.body) : undefined});
      if (c.fetchReply) { const result = await c.fetchReply(url, options); if (result) return result; }
      const result = url === '/api/access' ? c.authReply : url === '/api/state' ? c.stateReply : url.endsWith('/quote') ? c.quoteReply : {};
      return {ok:true, status:200, json:async()=>result};
    },
  };
  for (const name of resetNames) c[name] = () => c.resetCalls.push(name);
  c.KanpaceHttp = createClient(c.fetch);
  vm.createContext(c);
  vm.runInContext(accessSource + '\n' + appEntries, c);
  const run = source => vm.runInContext(source, c);
  await run('ensureAccessState()');
  c.requests.length = 0;
  return {c, run, elements, listeners, links, financialButtons, resetNames};
}

test('HTTP 401 from the actual API path opens login, never the network failure view', async()=>{
  const {c, run, elements} = await fixture();
  c.fetchReply = async url => url === '/api/state' ? {ok:false, status:401, json:async()=>({error:'请先登录'})} : null;
  await run("api('/api/state').catch(showError)");
  assert.match(elements.get('#access-login-overlay').innerHTML, /登录工作空间/);
  assert.match(elements.get('#access-login-overlay').innerHTML, /data-access-form="login"/);
  assert.equal(elements.get('#app').innerHTML, '');
  assert.equal(elements.get('#app').inert, true);
  assert.equal(elements.get('#app').attrs['aria-hidden'], 'true');
  assert.equal(elements.get('#modal').open, false);
  assert.equal(elements.get('#modal').innerHTML, '');
  assert.equal(c.agentResets, 1);
  assert.deepEqual(c.notices, []);
  assert.deepEqual(c.toasts, []);
});

test('technical role clears quote tabs, blocks financial routes, and hides financial navigation', async()=>{
  const {run, links, financialButtons} = await fixture();
  for (const page of ['quote','settings','owner']) {
    run("tab='quote'");
    assert.equal(run(`accessGuardPage('${page}')`), 'overview');
    assert.equal(run('tab'), 'parts');
  }
  assert.equal(run("accessGuardPage('drawing')"), 'drawing');
  run('accessDecorateNavigation()');
  assert(links.slice(0,4).every(link=>link.hidden));
  assert.equal(links[4].hidden, false);
  assert(financialButtons.every(button=>button.hidden));
});

test('refresh clears a stale quote tab before issuing any financial request', async()=>{
  const {c, run} = await fixture();
  run("page='drawing';tab='quote'");
  await run('refresh()');
  assert.equal(run('tab'), 'parts');
  assert.equal(run('page'), 'drawing');
  assert.deepEqual(c.requests.map(request=>request.url), ['/api/state','/api/workspace']);
  assert.equal(c.renders, 1);
});

test('logout click clears project, finance, production, schedule and modal data before login', async()=>{
  const {c, run, elements, listeners, resetNames} = await fixture('owner');
  c.authReply = {enabled:true, user:null, roles, financial_access:false};
  const button = {dataset:{accessAction:'logout'}, disabled:false};
  await listeners.click[0]({target:{closest:selector=>selector==='[data-access-action]' ? button : null}});
  assert.deepEqual(c.requests.map(request=>request.url), ['/api/access/logout','/api/access']);
  assert.equal(c.requests[0].options.method, 'POST');
  assert.equal(c.requests[0].options.credentials, 'same-origin');
  assert.deepEqual(c.requests[0].data, {});
  assert.equal(run('state'), null);
  assert.equal(run('quote'), null);
  assert.equal(run('operationsCalibrationData'), null);
  assert.equal(run('operationsCalibrationKey'), '');
  assert.equal(run('executionQueueById.size'), 0);
  assert.equal(run('refreshToken'), 2);
  assert.equal(c.agentResets, 1);
  assert.deepEqual(c.resetCalls, resetNames);
  assert.equal(elements.get('#app').innerHTML, '');
  assert.equal(elements.get('#modal').innerHTML, '');
  assert(elements.has('#access-login-overlay'));
  assert.equal(button.disabled, false);
});

test('technical construct editor omits prices and strips injected price fields on save', async()=>{
  const {c, run} = await fixture();
  run("partModal('part1')");
  assert(!c.modalContent.body.includes('name="unit_price"'));
  assert(!c.modalContent.body.includes('name="pricing_unit"'));
  assert(!c.modalContent.body.includes('918273'));
  assert(c.modalContent.body.includes('name="length_mm"'));
  c.values = {name:'柜体侧板', material:'木板', length_mm:'800', width_mm:'600', thickness_mm:'18', quantity:'2', unit_price:'99999', pricing_unit:'piece'};
  c.saveButton = {dataset:{approved:'true'}};
  await run('savePartThroughHandler(saveButton)');
  assert.equal(c.requests[0].url, '/api/parts/part1/review');
  assert.deepEqual(c.requests[0].data, {approved:true, edits:{name:'柜体侧板', material:'木板', length_mm:800, width_mm:600, thickness_mm:18, quantity:2}});
});

test('authorized cost editor retains entered unit price, including a legitimate zero', async()=>{
  const {c, run} = await fixture('supervisor');
  run("partModal('part1')");
  assert(c.modalContent.body.includes('name="unit_price"'));
  c.values = {name:'赠送标准件', quantity:'1', unit_price:'0', pricing_unit:'piece'};
  c.saveButton = {dataset:{approved:'false'}};
  await run('savePartThroughHandler(saveButton)');
  assert.equal(c.requests[0].data.edits.unit_price, 0);
  assert.equal(c.requests[0].data.edits.pricing_unit, 'piece');
});

test('STEP candidate approval requires a fresh quantity and dimension check with an audit note', async()=>{
  const {c, run, elements} = await fixture();
  c.partRows[0].source = {step_proposal:{id:'sp_a1',definition_id:'side-panel'}};
  const form = elements.get('#part-form');
  const focus = {count:0};
  form.elements = {
    quantity_confirmed:{checked:false,focus(){focus.count++;}},
    manufacturing_dimensions_confirmed:{checked:false,focus(){focus.count++;}},
    review_note:{focus(){focus.count++;}},
  };
  elements.set('#modal .dialog-error',{textContent:''});
  run("partModal('part1')");
  assert.match(c.modalContent.body, /工程构件审批/);
  assert.match(c.modalContent.body, /订单数量已核对/);
  assert.match(c.modalContent.body, /加工尺寸已核对/);
  assert.match(c.modalContent.body, /name="review_note"/);
  c.values = {name:'柜体侧板',material:'木板',category:'wood',length_mm:'800',width_mm:'600',thickness_mm:'18',quantity:'2',quantity_confirmed:'on',manufacturing_dimensions_confirmed:'on',review_note:'已核对施工图 A-01'};
  c.saveButton = {dataset:{approved:'true'}};
  await run('savePartThroughHandler(saveButton)');
  assert.equal(c.requests.length,0);
  assert.match(elements.get('#modal .dialog-error').textContent,/订单数量/);
  form.elements.quantity_confirmed.checked = true;
  await run('savePartThroughHandler(saveButton)');
  assert.equal(c.requests.length,0);
  form.elements.manufacturing_dimensions_confirmed.checked = true;
  c.values.review_note = '   ';
  await run('savePartThroughHandler(saveButton)');
  assert.equal(c.requests.length,0);
  assert.equal(focus.count,3);
  c.values.review_note = '已核对施工图 A-01';
  await run('savePartThroughHandler(saveButton)');
  assert.equal(c.requests.length,1);
  assert.equal(c.requests[0].url,'/api/parts/part1/review');
  assert.deepEqual(c.requests[0].data.engineering_confirmation,{quantity_confirmed:true,manufacturing_dimensions_confirmed:true});
  assert.equal(c.requests[0].data.review_note,'已核对施工图 A-01');
  assert.equal(c.requests[0].data.edits.length_mm,800);
  assert.equal(c.requests[0].data.edits.quantity,2);
  assert.equal('quantity_confirmed' in c.requests[0].data.edits,false);
  assert.equal('review_note' in c.requests[0].data.edits,false);
});

test('STEP candidate can remain pending without the approval confirmations', async()=>{
  const {c, run, elements} = await fixture();
  c.partRows[0].source = {step_proposal:{id:'sp_a1'}};
  elements.get('#part-form').elements = {quantity_confirmed:{checked:false},manufacturing_dimensions_confirmed:{checked:false},review_note:{}};
  c.values = {name:'柜体侧板',material:'木板',category:'wood',length_mm:'800',width_mm:'600',thickness_mm:'18',quantity:'2'};
  c.saveButton = {dataset:{approved:'false'}};
  await run('savePartThroughHandler(saveButton)');
  assert.equal(c.requests[0].url,'/api/parts/part1/review');
  assert.equal(c.requests[0].data.approved,false);
  assert.equal('engineering_confirmation' in c.requests[0].data,false);
});

test('read-only owner may read finance without gaining cost editing permission', async()=>{
  const {c, run, links, financialButtons} = await fixture('owner');
  assert.equal(run("accessCan('costs')"), false);
  assert.equal(run('accessState.financial_access'), true);
  for (const page of ['quote','owner','settings']) assert.equal(run(`accessGuardPage('${page}')`), page);
  run("page='quote';tab='quote'");
  await run('refresh()');
  assert.equal(run('tab'), 'quote');
  assert.deepEqual(c.requests.map(request=>request.url), ['/api/state','/api/workspace','/api/projects/project1/quote']);
  assert.deepEqual(plain(run('quote')), {total:1000});
  assert.equal(c.renders, 1);
  assert(links.every(link=>!link.hidden));
  assert(financialButtons.every(button=>!button.hidden));
  run("partModal('part1')");
  assert(!c.modalContent.body.includes('name="unit_price"'));
});

test('a financial response finishing after logout cannot restore the old quote cache', async()=>{
  const {c, run, listeners, elements} = await fixture('owner');
  const held = deferred();
  const started = deferred();
  c.fetchReply = async url => {
    if (url.endsWith('/quote')) { started.resolve(); return held.promise; }
    return null;
  };
  run("page='quote';tab='quote'");
  const pending = run('refresh()');
  await started.promise;
  c.authReply = {enabled:true, user:null, roles, financial_access:false};
  const button = {dataset:{accessAction:'logout'}};
  await listeners.click[0]({target:{closest:()=>button}});
  held.resolve({ok:true, status:200, json:async()=>({total:918273})});
  await pending;
  assert.equal(run('state'), null);
  assert.equal(run('quote'), null);
  assert.equal(c.renders, 0);
  assert.equal(elements.get('#app').innerHTML, '');
});

(async()=>{
  let failed = 0;
  for (const [name, run] of tests) {
    try { await run(); console.log('PASS', name); }
    catch (error) { failed++; console.error('FAIL', name, error.stack); }
  }
  console.log(`${tests.length - failed}/${tests.length} access frontend checks passed`);
  if (failed) process.exitCode = 1;
})();
