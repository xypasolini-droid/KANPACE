'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

const source = fs.readFileSync(path.join(__dirname, '../static/historical-demo/ui.js'), 'utf8');

function harness(hash = '#page=projects', snapshot = null) {
  const byId = new Map();
  const makeElement = tag => ({
    tag, id: '', className: '', textContent: '', href: '', children: [], attributes: {}, parent: null,
    setAttribute(name, value) { this.attributes[name] = value; if (name === 'href') this.href = value; },
    getAttribute(name) { return this.attributes[name] ?? (name === 'href' ? this.href : null); },
    append(...children) { for (const child of children) { child.parent = this; this.children.push(child); } },
    prepend(child) { child.parent = this; this.children.unshift(child); if (child.id) byId.set(child.id, child); },
    after(child) {
      const at = this.parent.children.indexOf(this);
      child.parent = this.parent;
      this.parent.children.splice(at + 1, 0, child);
    },
    querySelector(selector) {
      if (selector === '.historical-personnel-snapshot')
        return this.children.find(child => child.className === 'historical-personnel-snapshot') || null;
      if (selector === '.page-head')
        return this.children.find(child => child.className === 'page-head') || null;
      return null;
    },
    getBoundingClientRect() { return {height: 52}; },
  });
  const page = () => {
    const element = makeElement('main');
    element.className = 'ops-exchange-page';
    const head = makeElement('div');
    head.className = 'page-head';
    element.append(head);
    return element;
  };
  let exchangePage = page();
  const projectLink = () => {
    const link = makeElement('a');
    link.setAttribute('href', '#page=projects&tab=parts&projectStatus=active');
    return link;
  };
  let sidebarProjectLink = projectLink();
  const unrelatedLink = makeElement('a');
  unrelatedLink.setAttribute('href', '#page=tasks&projectStatus=active');
  const document = {
    head: {append(element) { this.style = element; }},
    body: makeElement('body'),
    documentElement: {style: {setProperty(name, value) { this[name] = value; }}},
    getElementById(id) { return byId.get(id) || null; },
    createElement: makeElement,
    querySelector(selector) {
      if (selector === '.ops-exchange-page') return exchangePage;
      if (selector === '.sidebar a[data-nav-item="projects"]') return sidebarProjectLink;
      return null;
    },
  };
  let observer;
  class MutationObserver {
    constructor(callback) { observer = callback; }
    observe() {}
  }
  const menu = [{items: [{id: 'projects', projectStatus: 'active'},
                          {id: 'tasks', projectStatus: 'active'}]}];
  const context = {
    document, location: {hash},
    window: {KANPACE_MENU: menu, addEventListener() {}},
    MutationObserver,
    fetch: async () => ({ok: true, json: async () => ({personnel_snapshot: snapshot})}),
  };
  return {
    context, document, menu, unrelatedLink,
    projectLink: () => sidebarProjectLink,
    page: () => exchangePage,
    rerender() { sidebarProjectLink = projectLink(); exchangePage = page(); observer(); },
  };
}

test('historical demo banner is visible at the top and links to its cases', () => {
  const scene = harness();
  vm.runInNewContext(source, scene.context);
  const banner = scene.document.getElementById('kanpace-historical-demo-banner');
  assert.equal(banner.tag, 'aside');
  assert.match(banner.children[0].textContent, /历史订单演示副本 · 仅本机/);
  assert.match(banner.children[0].textContent, /未经客户\/技术复核，禁止派工与加工/);
  assert.match(banner.children[0].textContent, /实体胸牌已禁用/);
  assert.equal(banner.children[1].href, '/factory/index.html#page=projects&projectStatus=all');
  assert.equal(scene.document.documentElement.style['--kanpace-historical-demo-height'], '52px');
  assert.match(scene.document.head.style.textContent, /position: fixed; inset: 0 0 auto/);
  vm.runInNewContext(source, scene.context);
  assert.equal(scene.document.body.children.filter(element => element.id === banner.id).length, 1);
});

test('personnel snapshot appears on Excel page and remains read-only after rerender', async () => {
  const scene = harness('#page=exchange', {count: 98, status: 'pending_confirmation',
    download_url: '/api/demo-sources/personnel-roster'});
  vm.runInNewContext(source, scene.context);
  await new Promise(setImmediate);
  let panel = scene.page().querySelector('.historical-personnel-snapshot');
  assert.equal(panel.children[0].children[0].textContent, '人员名册快照');
  assert.equal(panel.children[0].children[1].textContent, '98 条待核对；未加入派工人员');
  assert.equal(panel.children[1].href, '/api/demo-sources/personnel-roster');
  scene.rerender();
  panel = scene.page().querySelector('.historical-personnel-snapshot');
  assert.ok(panel);
  assert.equal(scene.page().children.filter(item => item.className === panel.className).length, 1);
});

test('only demo sidebar project-orders link opens all cases after SPA rerenders', () => {
  const scene = harness();
  vm.runInNewContext(source, scene.context);
  assert.equal(scene.menu[0].items[0].projectStatus, 'all');
  assert.equal(scene.projectLink().href, '#page=projects&tab=parts&projectStatus=all');
  assert.equal(scene.menu[0].items[1].projectStatus, 'active');
  assert.equal(scene.unrelatedLink.href, '#page=tasks&projectStatus=active');
  scene.rerender();
  assert.equal(scene.projectLink().href, '#page=projects&tab=parts&projectStatus=all');
});
