'use strict';
// Execute the complete production module in an isolated DOM/API environment.
// The only source instrumentation exposes closure state/functions for fixtures;
// no production function body is replaced and no customer HTTP API is contacted.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const production = fs.readFileSync(path.join(__dirname, '../static/intelligence.js'), 'utf8');
const marker = 'return {engineeringButtons,launcher,packingButton,reset,openEngineering};';
assert(production.includes(marker), 'Update the fixture export hook when the public module return changes');
const instrumented = production.replace(marker, `return {engineeringButtons,launcher,packingButton,reset,openEngineering,
  __test:{loadJob,poll,savePart,cutTreeCSV,cadArea,cadView,renderJob,draftCadProposal,loadCadProposals,loadDrawingMatches,drawingMatchView,setup(c,d,draft){context=c;dialog=d;evidenceDraft=draft;token++;},
    inspect(){return {context,evidenceDraft,token};}}};`);

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}

function fixture() {
  const feedback = {textContent: '', hidden: true}, result = {innerHTML: ''}, error = {textContent: ''};
  const mainModal = {open: true};
  const heading = {textContent: ''};
  function makeForm() {
    const field = value => ({value, required: false, checked: false, focus() {}});
    return {dataset: {}, elements: {
      name: field(''), material: field(''), category: field(''), finish: field(''), notes: field(''),
      quantity: field(''), length_mm: field(''), width_mm: field(''), thickness_mm: field(''),
      quantity_confirmed: field(''), manufacturing_dimensions_confirmed: field(''),
    }, inserted: [], insertAdjacentHTML(where, html) { this.inserted.push([where, html]); }, reportValidity: () => true};
  }
  let form = makeForm(), project = {id: 'prj_a', revision: 1}, serial = 0;
  const calls = [], timers = new Map(), effects = {close: 0, refresh: 0, toasts: [], engineeringClose: 0};
  const dialog = {open: true, querySelector(selector) {
    if (selector === '#intel-result') return result;
    if (selector === '.intel-jobs') return null;
    if (selector === '#intel-feedback') return feedback;
    throw new Error('Unexpected engineering selector: ' + selector);
  }, close() { this.open = false; effects.engineeringClose++; }};
  const scope = {
    window: {addEventListener() {}},
    document: {addEventListener() {}, querySelector(selector) {
      if (selector === '#part-form') return form;
      if (selector === '#modal') return mainModal;
      if (selector === '#modal .dialog-error') return error;
      if (selector === '#modal .dialog-head h2') return heading;
      throw new Error('Unexpected document selector: ' + selector);
    }, querySelectorAll(selector) {
      if (selector !== '#modal [data-action="save-part"]') throw new Error('Unexpected document selector: ' + selector);
      return [{dataset: {}, classList: {add() {}}, removeAttribute() {}, remove() {}}];
    }},
    num: value => Number(value).toLocaleString('zh-CN'),
    esc: value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])),
    currentProject: () => project,
    projectIsClosed: () => false,
    accessCan: () => true,
    formValues: () => ({name: '待审核侧板', material: '多层板', category: 'wood', quantity: '2', length_mm: '600', width_mm: '400', thickness_mm: '18'}),
    api(url, data) { const request = {...deferred(), url, data}; calls.push(request); return request.promise; },
    closeModal() { mainModal.open = false; effects.close++; },
    partModal() { mainModal.open = true; effects.partModal = (effects.partModal || 0) + 1; },
    refresh: async () => { effects.refresh++; },
    toast: message => effects.toasts.push(message),
    setTimeout(callback) { const id = ++serial; timers.set(id, callback); return id; },
    clearTimeout(id) { timers.delete(id); },
  };
  vm.runInNewContext(instrumented, scope, {filename: 'static/intelligence.js'});
  const api = scope.window.KanpaceIntelligence, testApi = api.__test;
  function setup(pid = 'prj_a', draft = null) {
    project = {id: pid, revision: 1}; form = makeForm();
    mainModal.open = true; dialog.open = true;
    testApi.setup({pid, revision: 1, selected: new Set(), jobs: []}, dialog, draft);
  }
  setup();
  return {api, testApi, calls, feedback, result, error, effects, mainModal, heading,
    setup, currentForm: () => form,
    logout() { api.reset(); project = null; },
    nextTimer() {
      const [id, callback] = timers.entries().next().value || [];
      assert(callback, 'Expected a production polling timer'); timers.delete(id); return callback();
    },
    lastRequest: () => calls.at(-1),
  };
}

const job = (id, status = 'failed') => ({job: {id, status, kind: 'ocr', source: {filename: id + '.pdf'},
  metadata: {source_label: id}, error: {message: '测试处理记录'}, result: {pages: []}}});
const draft = (pid = 'prj_a', id = 'job_A') => ({pid, revision: 1, refs: {job_id: id, regions: [{page: 1, index: 0}]}});
const sha = 'a'.repeat(64);
const cadJob = (id = 'eng_' + 'b'.repeat(32)) => ({id, status: 'completed', kind: 'cad',
  source: {filename: '柜体.step', sha256: sha}, metadata: {source_label: '柜体.step'},
  result: {format: 'STEP', output_length_unit: 'mm', instance_count: 5, unique_definition_count: 1,
    totals: {surface_area_mm2: 4000}, parts: []}});
const cadSnapshot = (id, overrides = {}) => ({project_id: 'prj_a', job_id: id, source_sha256: sha,
  status: 'needs_review', manufacturing_release: false, source_length_units: ['mm'], units_confirmed: true, warnings: [], proposals: [{
    id: 'sp_alpha', name: '<侧板>', definition_id: 'def_A', instance_indices: [0, 1, 2, 3, 4],
    instance_paths: ['柜体/侧板1', '柜体/侧板2'], suggested_quantity: 5,
    bbox_extents_mm_sample: [600, 400, 18], bbox_extents_mm_samples: [[600, 400, 18]],
    oriented_bbox_extents_mm_sample: [18, 400, 600], oriented_bbox_extents_mm_samples: [[18, 400, 600]],
    geometry_form_candidates: [{instance_index: 0, kind: 'thin_plate_shape', thinness_ratio: .03, basis: 'oriented_bbox', review_required: true}],
    geometry_form_candidate_count: 3,
    geometry_valid: true, review_status: 'pending', issues: ['订单数量需要核对'],
  }], ...overrides});
const drawingSnapshot = (id, overrides = {}) => ({project_id: 'prj_a', cad_job_id: id, cad_source_sha256: sha,
  status: 'evidence_only', manufacturing_release: false, ocr_job_count: 1, warnings: [], matches: [{
    proposal_id: 'sp_alpha', name: '<侧板>', match_status: 'matched', issues: ['尺寸必须核对'],
    drawing_evidence: [{job_id: 'eng_ocr1', source_sha256: 'b'.repeat(64), source_file: '施工图<P-01>.pdf',
      page: 1, source_page: 7, region_index: 2, bbox: [12, 25, 100, 70], page_width: 200, page_height: 150,
      text: '柜体侧板 600×400×18mm', score: .92,
      dimension_candidates: [{raw:'600×400×18mm', values:[600,400,18], unit:'mm', meaning:'OCR 尺寸候选'}], match_method:'exact_normalized_name'}],
    conflicting_drawing_evidence: []
  }], ...overrides});
const tests = [];
const test = (name, body) => tests.push([name, body]);

test('a current record response is actually rendered by the production function', async () => {
  const f = fixture(), pending = f.testApi.loadJob('B');
  f.lastRequest().resolve(job('B')); await pending;
  assert.equal(f.testApi.inspect().context.job.id, 'B');
  assert(f.result.innerHTML.includes('<p>B</p>'));
});

test('late record A success cannot replace the more recently selected record B', async () => {
  const f = fixture(), a = f.testApi.loadJob('A'), requestA = f.lastRequest();
  const b = f.testApi.loadJob('B'); f.lastRequest().resolve(job('B')); await b;
  const shown = f.result.innerHTML;
  requestA.resolve(job('A')); await a;
  assert.equal(f.testApi.inspect().context.job.id, 'B'); assert.equal(f.result.innerHTML, shown);
});

test('late record A failure cannot put an error beside the new record B', async () => {
  const f = fixture(), a = f.testApi.loadJob('A'), requestA = f.lastRequest();
  const b = f.testApi.loadJob('B'); f.lastRequest().resolve(job('B')); await b;
  requestA.reject(new Error('obsolete A failure')); await a;
  assert.equal(f.testApi.inspect().context.job.id, 'B');
  assert.equal(f.feedback.textContent, ''); assert.equal(f.feedback.hidden, true);
});

test('an already in-flight old poll failure cannot overwrite feedback for record B', async () => {
  const f = fixture(), a = f.testApi.loadJob('A'); f.lastRequest().resolve(job('A', 'running')); await a;
  const polling = f.nextTimer(), requestA = f.lastRequest();
  const b = f.testApi.loadJob('B'); f.lastRequest().resolve(job('B')); await b;
  requestA.reject(new Error('obsolete poll failure')); await polling;
  assert.equal(f.testApi.inspect().context.job.id, 'B'); assert.equal(f.feedback.textContent, '');
});

test('successful save of the current draft closes and refreshes once', async () => {
  const f = fixture(), original = draft(); f.setup('prj_a', original);
  const button = {disabled: false}, pending = f.testApi.savePart(button), request = f.lastRequest();
  assert.equal(button.disabled, true); assert.equal(request.url, '/api/parts');
  assert.equal(request.data.project_id, 'prj_a'); assert.equal(request.data.expected_revision, 1);
  assert.equal(request.data.engineering_evidence.job_id, 'job_A');
  request.resolve({part: {id: 'part_A', review_status: 'pending'}}); await pending;
  assert.equal(f.testApi.inspect().evidenceDraft, null);
  assert.equal(f.effects.close, 1); assert.equal(f.effects.refresh, 1); assert.equal(f.effects.toasts.length, 1);
});

test('late save success preserves a new project draft and never closes its modal', async () => {
  const f = fixture(); f.setup('prj_a', draft());
  const pending = f.testApi.savePart({disabled: false}), request = f.lastRequest();
  const next = draft('prj_b', 'job_B'); f.setup('prj_b', next); const nextForm = f.currentForm();
  request.resolve({part: {id: 'part_A'}}); await pending;
  assert.equal(f.testApi.inspect().evidenceDraft, next); assert.equal(f.currentForm(), nextForm);
  assert.equal(f.mainModal.open, true); assert.equal(f.effects.close, 0); assert.equal(f.effects.refresh, 0);
  assert.equal(f.effects.toasts.length, 0);
});

test('late save failure cannot replace the message of another draft in the same project', async () => {
  const f = fixture(); f.setup('prj_a', draft());
  const pending = f.testApi.savePart({disabled: false}), request = f.lastRequest();
  const next = draft('prj_a', 'job_B'); f.setup('prj_a', next); f.error.textContent = 'new draft feedback';
  request.reject(new Error('obsolete save failure')); await pending;
  assert.equal(f.testApi.inspect().evidenceDraft, next); assert.equal(f.error.textContent, 'new draft feedback');
  assert.equal(f.effects.close, 0); assert.equal(f.effects.refresh, 0);
});

test('logout reset ignores a late successful save instead of restoring old account UI', async () => {
  const f = fixture(); f.setup('prj_a', draft());
  const pending = f.testApi.savePart({disabled: false}), request = f.lastRequest(); f.logout();
  request.resolve({part: {id: 'part_private'}}); await pending;
  assert.equal(f.testApi.inspect().evidenceDraft, null); assert.equal(f.testApi.inspect().context, null);
  assert.equal(f.effects.close, 0); assert.equal(f.effects.refresh, 0); assert.equal(f.effects.toasts.length, 0);
});

test('logout reset ignores a late failed save and does not write into a new login screen', async () => {
  const f = fixture(); f.setup('prj_a', draft());
  const pending = f.testApi.savePart({disabled: false}), request = f.lastRequest(); f.logout();
  request.reject(new Error('old account private failure')); await pending;
  assert.equal(f.error.textContent, ''); assert.equal(f.effects.refresh, 0); assert.equal(f.effects.toasts.length, 0);
});

test('logout reset ignores both late record success and late record failure', async () => {
  for (const fail of [false, true]) {
    const f = fixture(), pending = f.testApi.loadJob('A'), request = f.lastRequest(); f.logout();
    const shown = f.result.innerHTML;
    if (fail) request.reject(new Error('old account private failure')); else request.resolve(job('A'));
    await pending;
    assert.equal(f.testApi.inspect().context, null); assert.equal(f.result.innerHTML, shown);
    assert.equal(f.feedback.textContent, '');
  }
});

test('small CAD areas remain measurable rather than rounding to zero square metres', () => {
  const f=fixture();assert.equal(f.testApi.cadArea(4400),'4,400 mm²');assert.equal(f.testApi.cadArea(null),'待核对');
});

test('completed STEP job loads grouped proposals and escapes model names without drafting manufacturing dimensions', async () => {
  const f = fixture(), j = cadJob(), context = f.testApi.inspect().context;
  context.job = j; context.jobs = [j]; context.jobRequest = 1;
  f.testApi.renderJob();
  const request = f.lastRequest();
  assert.equal(request.url, `/api/projects/prj_a/engineering/${j.id}/proposals`);
  assert.match(f.result.innerHTML, /正在按模型定义和实例名称整理候选/);
  request.resolve(cadSnapshot(j.id)); await new Promise(setImmediate);
  assert.match(f.result.innerHTML, /待核对构件 · 1 组/);
  assert.match(f.result.innerHTML, /模型中 5 个实例/);
  assert.match(f.result.innerHTML, /源单位 mm（已识别）/);
  assert.doesNotMatch(f.result.innerHTML, /源单位未明确，几何尺寸仅参考/);
  assert.match(f.result.innerHTML, /600 × 400 × 18 mm/);
  assert.match(f.result.innerHTML, /定向外包参考（短\/中\/长）/);
  assert.match(f.result.innerHTML, /18 × 400 × 600 mm/);
  assert.match(f.result.innerHTML, /3 个实例呈薄板形态/);
  assert.match(f.result.innerHTML, /不能据此确定板材、工艺或加工尺寸/);
  assert.match(f.result.innerHTML, /&lt;侧板&gt;/);
  assert.doesNotMatch(f.result.innerHTML, /<侧板>/);
  assert.match(f.result.innerHTML, /不是加工或下料尺寸/);
});

test('STEP candidate opens a blank manufacturing form and only saves full-group evidence after both confirmations', async () => {
  const f = fixture(), j = cadJob(), context = f.testApi.inspect().context;
  context.job = j; context.jobs = [j]; context.jobRequest = 1; context.proposalJobId = j.id;
  context.proposalState = 'ready'; context.cadProposals = cadSnapshot(j.id);
  f.testApi.draftCadProposal('sp_alpha');
  const form = f.currentForm();
  assert.equal(f.effects.partModal, 1);
  assert.equal(form.elements.name.value, '<侧板>');
  for (const key of ['quantity','length_mm','width_mm','thickness_mm']) {
    assert.equal(form.elements[key].value, ''); assert.equal(form.elements[key].required, true);
  }
  assert.equal(form.elements.quantity_confirmed.checked, false);
  assert.equal(form.elements.manufacturing_dimensions_confirmed.checked, false);
  assert.match(form.inserted.map(row => row[1]).join(''), /订单数量已核对/);
  assert.match(form.inserted.map(row => row[1]).join(''), /加工尺寸已核对/);
  assert.match(form.inserted.map(row => row[1]).join(''), /定向外包参考 18 × 400 × 600 mm/);
  await f.testApi.savePart({disabled: false}); assert.equal(f.calls.length, 0);
  form.elements.quantity_confirmed.checked = true;
  await f.testApi.savePart({disabled: false}); assert.equal(f.calls.length, 0);
  form.elements.manufacturing_dimensions_confirmed.checked = true;
  const pending = f.testApi.savePart({disabled: false}), request = f.lastRequest();
  assert.equal(request.url, '/api/parts');
  assert.equal(request.data.quantity, 2);
  assert.equal(request.data.engineering_evidence.proposal_id, 'sp_alpha');
  assert.deepEqual(Array.from(request.data.engineering_evidence.part_indices), [0, 1, 2, 3, 4]);
  assert.equal(request.data.engineering_evidence.quantity_confirmed, true);
  assert.equal(request.data.engineering_evidence.manufacturing_dimensions_confirmed, true);
  assert.equal(request.data.length_mm, 600);
  request.resolve({part: {id: 'part_B', review_status: 'pending'}}); await pending;
  assert.equal(f.effects.refresh, 1);
});

test('STEP candidate shows source drawing, OCR position and dimension clue without prefilling manufacturing fields', () => {
  const f = fixture(), j = cadJob(), context = f.testApi.inspect().context;
  context.job = j; context.proposalJobId = j.id; context.proposalState = 'ready';
  context.cadProposals = cadSnapshot(j.id); context.drawingMatchJobId = j.id;
  context.drawingMatchState = 'ready'; context.drawingMatches = drawingSnapshot(j.id);
  const markup = f.testApi.cadView(j);
  assert.match(markup, /找到疑似对应图纸/);
  assert.match(markup, /施工图&lt;P-01&gt;\.pdf · 第 7 页/);
  assert.match(markup, /柜体侧板 600×400×18mm/);
  assert.match(markup, /图中文字位置 12 \/ 25 \/ 100 \/ 70/);
  assert.match(markup, /viewBox="0 0 200 150"/);
  assert.match(markup, /engineering\/eng_ocr1\/pages\/1/);
  assert.match(markup, /放大原图/);
  assert.match(markup, /图纸尺寸候选：600×400×18mm/);
  assert.match(markup, /未填入生产尺寸/);
  f.testApi.draftCadProposal('sp_alpha');
  const form = f.currentForm();
  for (const key of ['length_mm', 'width_mm', 'thickness_mm']) assert.equal(form.elements[key].value, '');
  assert.match(form.inserted.map(row=>row[1]).join(''), /施工图线索：施工图&lt;P-01&gt;\.pdf · 第 7 页/);
  assert.match(form.inserted.map(row=>row[1]).join(''), /放大原图/);
});

test('drawing ambiguity, conflict and missing OCR are distinguishable; unsafe OCR text is escaped', () => {
  const f = fixture(), j = cadJob(), context = f.testApi.inspect().context;
  context.job = j; context.proposalJobId = j.id; context.proposalState = 'ready';
  context.cadProposals = cadSnapshot(j.id); context.drawingMatchJobId = j.id; context.drawingMatchState = 'ready';
  const suspicious = {...drawingSnapshot(j.id).matches[0].drawing_evidence[0], text:'<script>alert(1)</script>'};
  context.drawingMatches = drawingSnapshot(j.id, {matches:[{
    proposal_id:'sp_alpha', match_status:'conflict', drawing_evidence:[suspicious],
    conflicting_drawing_evidence:[{...suspicious, text:'其他型号 620×400×18mm'}], issues:['同件号对应不同名称']
  }]});
  let markup = f.testApi.cadView(j);
  assert.match(markup, /图纸信息有冲突/);
  assert.match(markup, /冲突标注 · 1 处/);
  assert.match(markup, /同件号对应不同名称/);
  assert.match(markup, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.doesNotMatch(markup, /<script>/);
  context.drawingMatches = drawingSnapshot(j.id, {matches:[{proposal_id:'sp_alpha', match_status:'ambiguous', drawing_evidence:[], conflicting_drawing_evidence:[], issues:['可能是多个构件']}]});
  assert.match(f.testApi.cadView(j), /多处图纸可能对应/);
  context.drawingMatches = drawingSnapshot(j.id, {ocr_job_count:0, matches:[]});
  assert.match(f.testApi.cadView(j), /还没有施工图识别记录/);
});

test('STEP detail shows only explicit direct assembly parents and flags cross-assembly ownership', () => {
  const f = fixture(), j = cadJob(), context = f.testApi.inspect().context;
  context.job = j; context.proposalJobId = j.id; context.proposalState = 'ready';
  context.drawingMatchJobId = j.id; context.drawingMatchState = 'ready';
  context.drawingMatches = drawingSnapshot(j.id, {ocr_job_count:0, matches:[]});
  const base = cadSnapshot(j.id).proposals[0];
  const occurrence = (index, path, name) => ({instance_index:index, instance_path:`${path}/侧板${index}`,
    nearest_parent:path?{instance_path:path, name, definition_id:'asm_1'}:null, ancestors:[], unresolved_parent_paths:[]});
  context.cadProposals = cadSnapshot(j.id, {proposals:[{...base,
    assembly_contexts:[occurrence(0, '总装/柜组A', '<柜组A>'), occurrence(1, '总装/柜组A', '<柜组A>')]}]});
  let markup = f.testApi.cadView(j);
  assert.match(markup, /核对提示、装配归属与实例位置/);
  assert.match(markup, /直接上级装配：<strong>&lt;柜组A&gt;<\/strong> · <code>总装\/柜组A<\/code>/);
  assert.doesNotMatch(markup, /涉及多个柜组\/装配/);
  context.cadProposals = cadSnapshot(j.id, {proposals:[{...base,
    assembly_contexts:[occurrence(0, '总装/柜组A', '柜组'), occurrence(1, '总装/柜组B', '柜组')]}]});
  markup = f.testApi.cadView(j);
  assert.match(markup, /涉及多个柜组\/装配，请核对归属/);
  assert.match(markup, /总装\/柜组A/);
  assert.match(markup, /总装\/柜组B/);
  context.cadProposals = cadSnapshot(j.id, {proposals:[{...base,
    assembly_contexts:[occurrence(0, '总装/柜组A', '柜组A'), occurrence(1, '', '')]}]});
  markup = f.testApi.cadView(j);
  assert.match(markup, /另有 1 个实例缺少直接父装配记录/);
  context.cadProposals = cadSnapshot(j.id, {proposals:[{...base, assembly_contexts:[]}]});
  assert.match(f.testApi.cadView(j), /模型未提供可核对的父级记录/);
});

test('drawing loading, error and no-OCR guidance appear once above multiple STEP candidates', () => {
  const f = fixture(), j = cadJob(), context = f.testApi.inspect().context;
  context.job = j; context.proposalJobId = j.id; context.proposalState = 'ready';
  context.drawingMatchJobId = j.id;
  const base = cadSnapshot(j.id).proposals[0];
  context.cadProposals = cadSnapshot(j.id, {proposals:[base,
    {...base,id:'sp_beta',name:'另一侧板'}, {...base,id:'sp_gamma',name:'底板'}]});
  context.drawingMatchState = 'loading';
  let markup = f.testApi.cadView(j);
  assert.equal((markup.match(/正在关联施工图文字/g)||[]).length, 1);
  assert(markup.indexOf('正在关联施工图文字') < markup.indexOf('<ol class="intel-cad-candidates">'));
  context.drawingMatchState = 'error'; context.drawingMatchError = '超时';
  markup = f.testApi.cadView(j);
  assert.equal((markup.match(/图纸证据暂未读到/g)||[]).length, 1);
  assert.equal((markup.match(/data-intel="drawing-match-retry"/g)||[]).length, 1);
  context.drawingMatchState = 'ready';
  context.drawingMatches = drawingSnapshot(j.id, {ocr_job_count:0,matches:[],excluded_unbound_ocr_job_count:2});
  markup = f.testApi.cadView(j);
  assert.equal((markup.match(/没有可比对的当前施工图识别记录/g)||[]).length, 1);
  assert.equal((markup.match(/class="intel-matches"/g)||[]).length, 0);
});

test('stale or mismatched cross-source response cannot appear on a different model or project', async () => {
  const f = fixture(), first = cadJob('eng_'+'1'.repeat(32)), second = cadJob('eng_'+'2'.repeat(32));
  const context = f.testApi.inspect().context;
  context.job = first; context.jobRequest = 1;
  const old = f.testApi.loadDrawingMatches(first.id, f.testApi.inspect().token, 'prj_a', 1);
  const oldRequest = f.lastRequest();
  context.job = second; context.jobRequest = 2;
  context.proposalJobId = second.id; context.proposalState = 'ready'; context.cadProposals = cadSnapshot(second.id);
  context.drawingMatchJobId = second.id;
  const current = f.testApi.loadDrawingMatches(second.id, f.testApi.inspect().token, 'prj_a', 2);
  const currentRequest = f.lastRequest();
  assert.equal(currentRequest.url, `/api/projects/prj_a/engineering/${second.id}/drawing-matches`);
  currentRequest.resolve(drawingSnapshot(second.id)); await current;
  oldRequest.resolve(drawingSnapshot(first.id)); await old;
  assert.equal(context.drawingMatches.cad_job_id, second.id);
  assert.equal(context.drawingMatchState, 'ready');
  const invalid = f.testApi.loadDrawingMatches(second.id, f.testApi.inspect().token, 'prj_a', 2);
  f.lastRequest().resolve(drawingSnapshot(second.id, {cad_source_sha256:'wrong'})); await invalid;
  assert.equal(context.drawingMatchState, 'error');
  assert.match(f.result.innerHTML, /图纸证据与当前工程模型不一致/);
});

test('STEP candidates without oriented geometry remain usable and show no thin-plate claim', () => {
  const f = fixture(), j = cadJob(), context = f.testApi.inspect().context;
  const proposal = {...cadSnapshot(j.id).proposals[0], oriented_bbox_extents_mm_sample: null,
    oriented_bbox_extents_mm_samples: [], geometry_form_candidates: [], geometry_form_candidate_count: 0};
  context.job = j; context.proposalJobId = j.id; context.proposalState = 'ready';
  context.cadProposals = cadSnapshot(j.id, {proposals:[proposal]});
  const markup = f.testApi.cadView(j);
  assert.match(markup,/世界轴向外包参考/);
  assert.doesNotMatch(markup,/定向外包参考（短\/中\/长）/);
  assert.doesNotMatch(markup,/实例呈薄板形态/);
});

test('unknown or conflicting STEP source units are conspicuous but do not block manual drawing review', () => {
  for (const units of [[], ['mm','inch']]) {
    const f = fixture(), j = cadJob(), context = f.testApi.inspect().context;
    context.job = j; context.proposalJobId = j.id; context.proposalState = 'ready';
    context.cadProposals = cadSnapshot(j.id, {source_length_units:units, units_confirmed:false});
    const markup = f.testApi.cadView(j);
    assert.match(markup,/源单位未明确，几何尺寸仅参考，按施工图填加工尺寸/);
    assert.match(markup,/role="alert"/);
    assert.match(markup,/data-intel="cad-proposal"/);
    assert.doesNotMatch(markup,/data-intel="cad-proposal"[^>]*disabled/);
    if (units.length) assert.match(markup,/已识别 mm、inch，仍需核对/);
  }
});

test('stale or mismatched STEP proposal response never becomes a clickable current-project candidate', async () => {
  const f = fixture(), first = cadJob('eng_' + '1'.repeat(32)), second = cadJob('eng_' + '2'.repeat(32));
  const context = f.testApi.inspect().context; context.job = first; context.jobs = [first]; context.jobRequest = 1;
  f.testApi.renderJob(); const stale = f.lastRequest();
  context.job = second; context.jobs = [second]; context.jobRequest = 2;
  f.testApi.renderJob(); const current = f.lastRequest();
  current.resolve(cadSnapshot(second.id)); await new Promise(setImmediate);
  stale.resolve(cadSnapshot(first.id)); await new Promise(setImmediate);
  assert.equal(context.cadProposals.job_id, second.id);
  assert.equal(context.proposalState, 'ready', context.proposalError);
  context.proposalJobId = null; f.testApi.renderJob();
  f.lastRequest().resolve(cadSnapshot(second.id, {source_sha256: 'wrong'}));
  await new Promise(setImmediate);
  assert.equal(context.proposalState, 'error');
  assert.match(f.result.innerHTML, /候选与当前模型来源不一致/);
  assert.doesNotMatch(f.result.innerHTML, /data-intel="cad-proposal"/);
});

test('cut-tree export uses millimetres and trim offset, and neutralizes formula labels', () => {
  const f=fixture();
  const csv=f.testApi.cutTreeCSV({config:{trim_mm:10,items:[{label:'=DANGER'}]},result:{layouts:[{cut_nodes:[
    {node_id:0,parent_id:null,depth:0,x:0,y:0,width:98000,height:98000,type:0},
    {node_id:1,parent_id:0,depth:1,x:48500,y:0,width:48000,height:48000,type:0}
  ]}]}});
  assert(csv.includes('"10","10","980","980","板内有效区",""'));
  assert(csv.includes('"495","10","480","480","零件","\'=DANGER"'));
});

(async () => {
  let failed = 0;
  for (const [name, body] of tests) {
    try { await body(); console.log('PASS', name); }
    catch (error) { failed++; console.error('FAIL', name, error.stack); }
  }
  console.log(`${tests.length - failed}/${tests.length} intelligence frontend checks passed`);
  if (failed) process.exitCode = 1;
})();
