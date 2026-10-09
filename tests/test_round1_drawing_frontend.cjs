'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

const staticDir = path.join(__dirname, '../static');
const script = fs.readFileSync(path.join(staticDir, 'round1-drawing.js'), 'utf8');
const app = fs.readFileSync(path.join(staticDir, 'app.js'), 'utf8');
const drafts = fs.readFileSync(path.join(staticDir, 'order-drafts.js'), 'utf8');
const index = fs.readFileSync(path.join(staticDir, 'index.html'), 'utf8');
const origin = 'http://127.0.0.1:8765';
const assets = name => `/api/projects/p1/drawing-pipeline/assets/dpr_012345abcdef/${name}`;
function snapshot(projectId = 'p1') {
  return {
    project_id: projectId, status: 'review_only', review_only: true,
    manufacturing_release: false, can_dispatch: false, source_linked: false,
    source: { archive_filename: 'drawing-pipeline.zip', source_match: false,
      candidate_count: 15, coverage: '原模型的局部展示布置' },
    candidates: Array.from({length: 15}, (_, i) => ({
      id: i === 0 ? 'CQ-01' : `CQ-${String(i + 1).padStart(2, '0')}`,
      label: i === 0 ? '重庆珠宝柜' : '候选柜体', object_count: i === 0 ? 15 : 4,
      selected: i === 0, quantity: i === 0 ? 1 : null,
      dimension_basis: i === 0 ? 'model_only' : null,
      confirmed: i === 0, engineering_approved: false,
    })),
    outputs: [{id:'CQ-01', label:'CQ-01 早期外形核对草稿',
      preview_url:assets('preview'), svg_url:assets('svg'), dxf_url:assets('dxf'), review_only:true}],
    warnings:['未关联来源的参考资料', '实物尺寸尚未完成核对'],
  };
}
function boot(data = snapshot()) {
  const project = {id:'p1', revision:3, name:'测试珠宝柜'};
  const listeners = {};
  const context = {
    console, URL, Map, Set, Promise, Uint8Array, Math, Number, Array,
    location:{origin}, document:{addEventListener(type,handler){listeners[type]=handler;},querySelectorAll(){return [];},activeElement:null},
    page:'drawing', tab:'parts', currentProject:()=>project, projectIsClosed:p=>!!p.is_closed,
    accessCan:()=>true, api:async()=>data,
    btoa:binary=>Buffer.from(binary,'binary').toString('base64'),
    esc:value=>String(value ?? '').replace(/[&<>"']/g, char=>({
      '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;',
    }[char])),
  };
  vm.createContext(context);
  vm.runInContext(script, context);
  return {api:context.KanpaceRound1, project, context, listeners};
}

test('review-only package shows real CQ-01 output, candidate scope and source mismatch', async () => {
  const {api, project} = boot();
  await api.load(project);
  const html = api.panel(project);
  assert.match(html, /未与本项目源模型核对，仅供参考/);
  assert.match(html, /不可下料 · 不可派工/);
  assert.match(html, /CQ-01 · 已选柜体范围/);
  assert.match(html, /查看候选柜体 · 15 组/);
  assert.match(html, /实物尺寸未核验/);
  assert.match(html, /CQ-01 早期外形核对草稿/);
  assert.match(html, /dpr_012345abcdef\/preview/);
  assert.match(html, /dpr_012345abcdef\/svg/);
  assert.match(html, /dpr_012345abcdef\/dxf/);
  assert.doesNotMatch(html, /下载 PDF|<iframe|<svg|>可下料<|已工程签审|选择后自动出图/);
  assert.match(html, /导入模型核对包/);
});

test('only linked source can show a fingerprint-match notice; no production approval is inferred', () => {
  const data = snapshot(); data.source_linked = true; data.source.source_match = true;
  const {api, project} = boot(data);
  const result = api.normalize(data, 'p1');
  const html = api.renderData(project, {phase:'ready', data:result});
  assert.match(html, /源模型指纹已匹配/);
  assert.match(html, /仍须按原件核对模型版本与工程尺寸/);
  assert.match(html, /不可下料 · 不可派工/);
  assert.doesNotMatch(html, /已工程签审|可生产/);
});

test('foreign project result and foreign asset URLs cannot enter the project panel', () => {
  const {api} = boot();
  assert.throws(() => api.normalize(snapshot('p2'), 'p1'), /当前项目不一致/);
  for (const url of [
    'https://other.example/x.png',
    '/api/projects/p2/drawing-pipeline/assets/dpr_012345abcdef/preview',
    'javascript:alert(1)',
    '/api/projects/p1/drawing-pipeline/assets/../other',
  ]) assert.equal(api.assetURL(url, 'p1'), '');
  const bad = snapshot(); bad.outputs[0].preview_url = 'https://other.example/private.png';
  bad.outputs[0].svg_url = '/api/projects/p2/drawing-pipeline/assets/x/svg';
  const html = api.renderData({id:'p1'}, {phase:'ready', data:api.normalize(bad, 'p1')});
  assert.doesNotMatch(html, /other\.example|\/api\/projects\/p2\//);
});

test('closed projects and read-only users can inspect but cannot import a package', () => {
  const {api, project, context} = boot();
  const data = api.normalize(snapshot(), 'p1');
  project.is_closed = true;
  assert.doesNotMatch(api.renderData(project, {phase:'ready',data}), /导入模型核对包/);
  project.is_closed = false; context.accessCan = () => false;
  assert.doesNotMatch(api.renderData(project, {phase:'ready',data}), /导入模型核对包/);
  assert.match(api.renderData(project, {phase:'ready',data}), /CQ-01/);
});

test('ZIP import sends only the current project and expected revision; invalid files stop locally', async () => {
  const {api, project, context, listeners} = boot();
  let sent = null;
  context.XMLHttpRequest = class {
    constructor(){this.upload={};this.status=201;this.responseText=JSON.stringify(snapshot());}
    open(method,url){sent={method,url};}
    setRequestHeader(name,value){sent.headers={[name]:value};}
    send(body){sent.body=JSON.parse(body);this.onload();}
  };
  const event = file => ({target:{
    matches:selector=>selector==='.round1-file',
    closest:()=>({dataset:{project:'p1'}}),
    files:[file],
  }});
  listeners.change(event({name:'wrong.max',size:3}));
  assert.equal(sent, null);
  assert.match(api.renderData(project, {phase:'ready',data:api.normalize(snapshot(),'p1')}), /请选择 ZIP 模型核对包/);
  listeners.change(event({name:'drawing-pipeline.zip',size:3,
    arrayBuffer:async()=>Uint8Array.from([80,75,3]).buffer}));
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(sent.method,'POST');
  assert.equal(sent.url,'/api/projects/p1/drawing-pipeline/import');
  assert.equal(sent.body.filename,'drawing-pipeline.zip');
  assert.equal(sent.body.expected_revision,3);
  assert.equal(sent.body.content_base64,'UEsD');
});

test('entry stays within both project drawing views and adds no navigation item', () => {
  assert.match(index, /round1-drawing\.css/);
  assert.match(index, /round1-drawing\.js/);
  assert.match(app, /<details class="drawing-optional"><summary>外形模型核对（可选）<\/summary>/);
  assert.match(drafts, /<details class="drawing-optional"><summary>外形模型核对（可选）<\/summary>/);
  assert.match(app, /KanpaceRound1\.panel\(currentProject\(\)\)/);
  assert.match(drafts, /KanpaceRound1\.panel\(currentProject\(\)\)/);
  assert.doesNotMatch(index, /round1.*nav-link|nav-link.*round1/);
});
