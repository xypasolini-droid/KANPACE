/* Local, read-only drawing study. This page never creates production tasks. */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const state = { study: null, cabinet: '', trade: '', pageByPackage: new Map(), viewerPackage: null, viewerIndex: 0, zoom: 1, printDetails: [], noticeTimer: null };
  const list = (value) => Array.isArray(value) ? value : [];
  const hasValue = (value) => value !== undefined && value !== null && value !== '';
  const readable = (value, fallback = '待核') => {
    if (!hasValue(value)) return fallback;
    if (Array.isArray(value)) return value.length ? value.map(item => readable(item)).join('；') : fallback;
    if (typeof value === 'object') return hasValue(value.name) ? readable(value.name) : hasValue(value.label) ? readable(value.label) : JSON.stringify(value);
    return String(value);
  };
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function button(text, className, handler, label) {
    const node = element('button', className, text);
    node.type = 'button';
    if (label) node.setAttribute('aria-label', label);
    node.addEventListener('click', handler);
    return node;
  }
  function localUrl(value) {
    if (typeof value !== 'string' || !value.trim()) return null;
    try {
      const url = new URL(value, window.location.href);
      return url.origin === window.location.origin && ['http:', 'https:'].includes(url.protocol) ? url.href : null;
    } catch { return null; }
  }
  function sourceText(evidence) {
    const parts = [readable(evidence.source_file, '来源待核')];
    if (hasValue(evidence.page)) parts.push(`PDF 第 ${readable(evidence.page)} 页`);
    if (hasValue(evidence.printed_page)) parts.push(`图内页码 ${readable(evidence.printed_page)}`);
    return parts.join(' · ');
  }
  const packages = () => list(state.study?.work_packages);
  const cabinetTypes = () => list(state.study?.cabinet_types);
  const visiblePackages = () => packages().filter(pkg => (!state.cabinet || String(pkg.cabinet_id) === state.cabinet) && (!state.trade || readable(pkg.trade) === state.trade));
  const cabinetName = (id) => readable(cabinetTypes().find(item => String(item.id) === String(id))?.name, '柜型待核');

  function renderOverview() {
    const data = state.study;
    $('study-title').textContent = readable(data.title, '图纸分工 · 空白模板');
    document.title = `${$('study-title').textContent} — KANPACE`;
    $('summary').textContent = `${readable(data.summary, '根据施工图与部件拆解图整理分工。').replace(/[。\s]+$/, '')}。未产生生产派工。`;
    const counts = $('counts');
    counts.replaceChildren();
    [['files', '份文件'], ['pdfs', '份 PDF'], ['pages', '页图纸'], ['variants', '种柜型'], ['cabinets', '台柜体']].forEach(([key, label]) => {
      const item = element('span');
      item.append(element('strong', '', readable(data.counts?.[key])), document.createTextNode(label));
      counts.append(item);
    });
    const issues = list(data.issues);
    $('issues-section').hidden = !issues.length;
    $('issue-count').textContent = `${issues.length} 项`;
    $('issues').replaceChildren();
    issues.forEach(issue => {
      const item = element('article', 'issue');
      item.append(element('h3', '', readable(issue.title)), element('p', '', readable(issue.detail)));
      if (hasValue(issue.source)) item.append(element('small', '', readable(issue.source)));
      $('issues').append(item);
    });
    const flow = list(data.flow);
    $('flow-section').hidden = !flow.length;
    $('flow').replaceChildren();
    const flowLabels = new Map(flow.map(step => [String(step.id), readable(step.label)]));
    flow.forEach(step => {
      const node = element('div', 'flow-item');
      node.append(element('strong', '', readable(step.label)));
      const dependencies = list(step.depends_on);
      node.append(element('p', '', dependencies.length ? `前序：${dependencies.map(id => flowLabels.get(String(id)) || readable(id)).join('、')}` : '无列明前序'));
      $('flow').append(node);
    });
  }

  function renderFilters() {
    const wrapper = $('cabinet-filters');
    wrapper.replaceChildren();
    const choices = [{ id: '', name: '全部柜型', quantity: state.study.counts?.cabinets }, ...cabinetTypes()];
    choices.forEach(item => {
      const id = String(item.id ?? '');
      const node = button('', 'cabinet-filter', () => { state.cabinet = id; renderFilters(); renderPackages(); });
      node.setAttribute('aria-pressed', String(state.cabinet === id));
      node.append(element('strong', '', readable(item.name)), element('span', '', `${readable(item.quantity)} 台`));
      wrapper.append(node);
    });
    const tradeSelect = $('trade-filter');
    tradeSelect.replaceChildren(element('option', '', '全部工种'));
    tradeSelect.firstElementChild.value = '';
    [...new Set(packages().map(pkg => readable(pkg.trade)))].forEach(trade => {
      const option = element('option', '', trade);
      option.value = trade;
      tradeSelect.append(option);
    });
    tradeSelect.value = state.trade;
    $('clear-filter').hidden = !(state.cabinet || state.trade);
  }

  function quantityItem(label, value, unit) {
    const item = element('div');
    item.append(element('dt', '', label));
    const dd = element('dd', '', readable(value));
    if (hasValue(value)) dd.append(element('span', '', readable(unit, '件')));
    item.append(dd);
    return item;
  }
  function infoBlock(label, value) {
    const block = element('div', 'info-block');
    block.append(element('strong', '', label), element('p', '', readable(value)));
    return block;
  }
  function listBlock(label, values, className) {
    const block = element('div', 'info-block');
    block.append(element('strong', '', label));
    const ul = element('ul', className);
    values.forEach(value => ul.append(element('li', '', readable(value))));
    block.append(ul);
    return block;
  }
  function renderEvidence(pkg, container) {
    const evidence = list(pkg.evidence);
    const key = String(pkg.id);
    const index = Math.min(state.pageByPackage.get(key) || 0, Math.max(0, evidence.length - 1));
    const page = evidence[index];
    container.replaceChildren();
    if (!page) {
      container.append(element('p', 'image-missing', '待补充部件图'));
      return;
    }
    const imageUrl = localUrl(page.image);
    if (imageUrl) {
      const open = button('', 'image-button', () => openViewer(pkg, index), `放大：${readable(pkg.title)}，${readable(page.label, '图纸')}`);
      const image = element('img');
      image.src = imageUrl;
      image.alt = `${readable(pkg.title)} · ${readable(page.label, '部件图')}`;
      image.loading = 'lazy';
      image.decoding = 'async';
      image.addEventListener('error', () => {
        open.replaceChildren(element('span', 'image-missing', '图纸图片暂未就绪'));
        open.disabled = true;
      }, { once: true });
      open.append(image, element('span', 'enlarge-hint', '放大查看 ↗'));
      container.append(open);
    } else {
      container.append(element('p', 'image-missing', '待补充图纸图片'));
    }
    const bar = element('div', 'evidence-bar');
    const label = element('div', 'evidence-label');
    label.append(element('strong', '', readable(page.label, '图纸依据')), document.createTextNode(sourceText(page)));
    bar.append(label);
    if (evidence.length > 1) {
      const paging = element('div', 'paging');
      const previous = button('←', 'button', () => { state.pageByPackage.set(key, index - 1); renderEvidence(pkg, container); }, `查看 ${readable(pkg.title)} 的上一张图纸`);
      const next = button('→', 'button', () => { state.pageByPackage.set(key, index + 1); renderEvidence(pkg, container); }, `查看 ${readable(pkg.title)} 的下一张图纸`);
      previous.disabled = index === 0;
      next.disabled = index === evidence.length - 1;
      paging.append(previous, element('span', '', `${index + 1} / ${evidence.length}`), next);
      bar.append(paging);
    }
    container.append(bar);
  }

  function packageCard(pkg) {
    const card = element('article', 'package-card');
    card.dataset.packageId = readable(pkg.id, '');
    const heading = element('div', 'package-heading');
    heading.append(element('span', 'trade-tag', readable(pkg.trade)), element('h3', '', readable(pkg.title)), element('span', 'station', readable(pkg.station, '岗位待核')));
    const body = element('div', 'package-body');
    const evidence = element('div', 'evidence');
    renderEvidence(pkg, evidence);
    const info = element('div', 'package-info');
    const quantity = element('dl', 'quantity-grid');
    quantity.append(quantityItem('单柜数量', pkg.quantity_per_cabinet, pkg.unit), quantityItem('本项目数量', pkg.project_quantity, pkg.unit));
    info.append(quantity, infoBlock('物料 / 工艺', pkg.material));
    const instructions = list(pkg.instructions);
    if (instructions.length) info.append(listBlock('工作内容', instructions, 'instruction-list'));
    const questions = list(pkg.review_questions);
    if (questions.length) {
      const review = element('div', 'review-box');
      review.append(element('strong', '', '待技术确认'));
      const questionList = element('ul', 'review-list');
      questions.forEach(question => questionList.append(element('li', '', readable(question))));
      review.append(questionList);
      info.append(review);
    }
    const details = element('details', 'package-details');
    details.append(element('summary', '', '分工依据与前序'));
    const detailsContent = element('div');
    detailsContent.append(infoBlock('分工依据', pkg.basis));
    const dependencies = list(pkg.dependencies);
    const packageLabels = new Map(packages().map(item => [String(item.id), `${cabinetName(item.cabinet_id)} · ${readable(item.title)}`]));
    if (dependencies.length) detailsContent.append(listBlock('前序工作', dependencies.map(id => packageLabels.get(String(id)) || readable(id)), 'dependency-list'));
    else detailsContent.append(infoBlock('前序工作', '无列明前序，开工条件待复核'));
    const sources = new Map();
    list(pkg.evidence).forEach(page => {
      const url = localUrl(page.source_url);
      if (url && !sources.has(url.split('#')[0])) sources.set(url.split('#')[0], { ...page, firstUrl: url });
    });
    sources.forEach((page, url) => {
      const link = element('a', 'source-link', `打开原 PDF：${readable(page.source_file, '图纸原文件')} ↗`);
      link.href = page.firstUrl || url;
      link.target = '_blank';
      link.rel = 'noopener';
      detailsContent.append(link);
    });
    details.append(detailsContent);
    info.append(details);
    body.append(evidence, info);
    card.append(heading, body);
    return card;
  }

  function renderPackages() {
    const visible = visiblePackages();
    $('packages').replaceChildren();
    $('empty').hidden = visible.length > 0;
    $('result-count').textContent = `${visible.length} 个工作包 / 共 ${packages().length} 个`;
    $('clear-filter').hidden = !(state.cabinet || state.trade);
    $('print-filter').textContent = `${state.cabinet ? cabinetName(state.cabinet) : '全部柜型'} · ${state.trade || '全部工种'} · ${visible.length} 个工作包 · 待技术复核`;
    const groups = new Map();
    cabinetTypes().forEach(type => groups.set(String(type.id), []));
    visible.forEach(pkg => {
      const id = String(pkg.cabinet_id);
      if (!groups.has(id)) groups.set(id, []);
      groups.get(id).push(pkg);
    });
    groups.forEach((items, id) => {
      if (!items.length) return;
      const type = cabinetTypes().find(item => String(item.id) === id);
      const section = element('section', 'cabinet-group');
      const heading = element('div', 'cabinet-heading');
      heading.append(element('h2', '', cabinetName(id)), element('p', '', `${readable(type?.quantity)} 台 · 尺寸 ${readable(type?.size)}`));
      const listNode = element('div', 'package-list');
      items.forEach(pkg => listNode.append(packageCard(pkg)));
      section.append(heading, listNode);
      $('packages').append(section);
    });
    $('print-button').disabled = !visible.length;
  }

  function resetFilters() {
    state.cabinet = '';
    state.trade = '';
    renderFilters();
    renderPackages();
  }
  function updateZoom() {
    $('viewer-canvas').classList.toggle('zoomed', state.zoom > 1);
    $('viewer-image').style.width = `${state.zoom * 100}%`;
    $('zoom-reset').textContent = state.zoom === 1 ? '适合窗口' : `${Math.round(state.zoom * 100)}%`;
    $('zoom-out').disabled = state.zoom === 1;
    $('zoom-in').disabled = state.zoom >= 4;
  }
  function renderViewer() {
    const evidence = list(state.viewerPackage?.evidence);
    const page = evidence[state.viewerIndex];
    if (!page) return;
    $('viewer-title').textContent = `${readable(state.viewerPackage.title)} · ${readable(page.label, '图纸')}`;
    $('viewer-source').textContent = sourceText(page);
    $('viewer-position').textContent = `${state.viewerIndex + 1} / ${evidence.length}`;
    $('viewer-prev').disabled = state.viewerIndex === 0;
    $('viewer-next').disabled = state.viewerIndex === evidence.length - 1;
    const url = localUrl(page.image);
    $('viewer-image').hidden = !url;
    $('viewer-missing').hidden = Boolean(url);
    $('viewer-image').alt = `${readable(state.viewerPackage.title)} · ${readable(page.label, '图纸')}`;
    $('viewer-image').removeAttribute('src');
    if (url) $('viewer-image').src = url;
    const originalUrl = localUrl(page.source_url);
    $('viewer-original').hidden = !originalUrl;
    $('viewer-original').removeAttribute('href');
    if (originalUrl) $('viewer-original').href = originalUrl;
    state.zoom = 1;
    updateZoom();
    $('viewer-canvas').scrollTo(0, 0);
  }
  function openViewer(pkg, index) {
    state.viewerPackage = pkg;
    state.viewerIndex = index;
    renderViewer();
    $('image-viewer').showModal();
  }
  function turnViewer(delta) {
    const next = state.viewerIndex + delta;
    if (next < 0 || next >= list(state.viewerPackage?.evidence).length) return;
    state.viewerIndex = next;
    renderViewer();
  }
  function notify(message) {
    clearTimeout(state.noticeTimer);
    $('notice').textContent = message;
    $('notice').hidden = false;
    state.noticeTimer = setTimeout(() => { $('notice').hidden = true; }, 4500);
  }
  function downloadData() {
    if (!state.study) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(state.study, null, 2)], { type: 'application/json;charset=utf-8' }));
    const link = element('a');
    link.href = url;
    link.download = 'KANPACE-图纸分工模板.json';
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    notify('已生成全部柜型的分工数据文件');
  }
  function preparePrint() {
    state.printDetails = [...document.querySelectorAll('.package-details')].map(node => [node, node.open]);
    state.printDetails.forEach(([node]) => { node.open = true; });
  }
  function restorePrint() {
    state.printDetails.forEach(([node, open]) => { node.open = open; });
    state.printDetails = [];
  }
  async function printPackages() {
    const target = $('print-button');
    target.disabled = true;
    target.textContent = '正在准备图纸…';
    const images = [...document.querySelectorAll('#packages img')];
    images.forEach(image => { image.loading = 'eager'; });
    await Promise.all(images.map(image => image.decode().catch(() => {})));
    target.textContent = '打印当前清单';
    target.disabled = false;
    window.print();
  }
  async function load() {
    $('loading').hidden = false;
    $('error').hidden = true;
    $('empty').hidden = true;
    try {
      const response = await fetch('study.json', { cache: 'no-cache' });
      if (!response.ok) throw new Error(`资料文件暂不可用（${response.status}）`);
      const data = await response.json();
      if (!data || !Array.isArray(data.work_packages) || !Array.isArray(data.cabinet_types)) throw new Error('资料格式不完整，请检查分工清单。');
      state.study = data;
      renderOverview();
      renderFilters();
      renderPackages();
      $('filters').hidden = false;
      $('download-button').disabled = false;
    } catch (error) {
      $('error-message').textContent = error instanceof TypeError ? '无法连接本地资料，请确认 KANPACE 服务仍在运行。' : readable(error.message, '读取失败，请稍后重试。');
      $('error').hidden = false;
    } finally {
      $('loading').hidden = true;
    }
  }
  $('trade-filter').addEventListener('change', event => { state.trade = event.target.value; renderPackages(); });
  $('clear-filter').addEventListener('click', resetFilters);
  $('empty-reset').addEventListener('click', resetFilters);
  $('retry-button').addEventListener('click', load);
  $('download-button').addEventListener('click', downloadData);
  $('print-button').addEventListener('click', printPackages);
  $('close-viewer').addEventListener('click', () => $('image-viewer').close());
  $('viewer-prev').addEventListener('click', () => turnViewer(-1));
  $('viewer-next').addEventListener('click', () => turnViewer(1));
  $('zoom-in').addEventListener('click', () => { state.zoom = Math.min(4, state.zoom + .5); updateZoom(); });
  $('zoom-out').addEventListener('click', () => { state.zoom = Math.max(1, state.zoom - .5); updateZoom(); });
  $('zoom-reset').addEventListener('click', () => { state.zoom = 1; updateZoom(); $('viewer-canvas').scrollTo(0, 0); });
  $('viewer-image').addEventListener('error', () => { $('viewer-image').hidden = true; $('viewer-missing').hidden = false; });
  $('image-viewer').addEventListener('keydown', event => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); turnViewer(event.key === 'ArrowLeft' ? -1 : 1); }
  });
  window.addEventListener('beforeprint', preparePrint);
  window.addEventListener('afterprint', restorePrint);
  load();
})();
