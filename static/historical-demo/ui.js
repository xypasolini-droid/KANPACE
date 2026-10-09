'use strict';
// Injected only by launch_historical_demo.py. The normal factory Web never loads this file.
(() => {
  if (document.getElementById('kanpace-historical-demo-banner')) return;

  const style = document.createElement('style');
  style.textContent = `
    body { padding-top: var(--kanpace-historical-demo-height, 0px); }
    .shell > .sidebar { top: var(--kanpace-historical-demo-height, 0px); }
    #kanpace-historical-demo-banner {
      position: fixed; inset: 0 0 auto; z-index: 4000;
      box-sizing: border-box; display: flex; align-items: center;
      justify-content: center; flex-wrap: wrap; gap: .35rem 1.1rem;
      min-height: 3rem; padding: .55rem 1rem;
      background: #12364a; color: #fff; text-align: center;
      box-shadow: 0 2px 12px #0003;
      font: 600 .95rem/1.5 -apple-system, BlinkMacSystemFont, "Microsoft YaHei", sans-serif;
    }
    #kanpace-historical-demo-banner a { color: #fff; text-decoration: underline; text-underline-offset: .2em; }
    #kanpace-historical-demo-banner a:focus-visible { outline: 3px solid #fff; outline-offset: 3px; }
    .historical-personnel-snapshot {
      display: flex; align-items: center; justify-content: space-between;
      flex-wrap: wrap; gap: .75rem 1.5rem; margin: 1rem 0;
      padding: 1rem 1.25rem; border: 1px solid #cfdae1;
      border-radius: .75rem; background: #f4f8fa; color: #173749;
    }
    .historical-personnel-snapshot h2 { margin: 0 0 .25rem; font-size: 1rem; line-height: 1.5; }
    .historical-personnel-snapshot p { margin: 0; font-size: .875rem; line-height: 1.5; }
    .historical-personnel-snapshot a { color: #185f82; font-weight: 600; text-underline-offset: .2em; }
    .historical-personnel-snapshot a:focus-visible { outline: 3px solid #185f82; outline-offset: 3px; }
  `;
  document.head.append(style);

  const banner = document.createElement('aside');
  banner.id = 'kanpace-historical-demo-banner';
  banner.setAttribute('aria-label', '历史订单演示环境');
  const label = document.createElement('span');
  label.textContent = '历史订单演示副本 · 仅本机 · 未经客户/技术复核，禁止派工与加工 · 实体胸牌已禁用';
  const link = document.createElement('a');
  link.href = '/factory/index.html#page=projects&projectStatus=all';
  link.textContent = '查看历史订单案例';
  banner.append(label, link);
  document.body.prepend(banner);

  const reserve = () => {
    document.documentElement.style.setProperty(
      '--kanpace-historical-demo-height', `${Math.ceil(banner.getBoundingClientRect().height)}px`
    );
  };
  reserve();
  if ('ResizeObserver' in window) new ResizeObserver(reserve).observe(banner);
  else window.addEventListener('resize', reserve);

  let personnelSnapshot = null;
  const mountPersonnelSnapshot = () => {
    if (!personnelSnapshot || !location.hash.includes('page=exchange')) return;
    const page = document.querySelector('.ops-exchange-page');
    if (!page || page.querySelector('.historical-personnel-snapshot')) return;
    const panel = document.createElement('section');
    panel.className = 'historical-personnel-snapshot';
    const copy = document.createElement('div');
    const heading = document.createElement('h2');
    heading.textContent = '人员名册快照';
    const note = document.createElement('p');
    note.textContent = `${personnelSnapshot.count} 条待核对；未加入派工人员`;
    copy.append(heading, note);
    const download = document.createElement('a');
    download.href = personnelSnapshot.download_url;
    download.textContent = '下载原始名册';
    download.setAttribute('download', 'KANPACE-personnel-snapshot.xlsx');
    panel.append(copy, download);
    const pageHead = page.querySelector('.page-head');
    if (pageHead) pageHead.after(panel);
    else page.prepend(panel);
  };
  const showAllHistoricalProjects = () => {
    // The ordinary factory menu opens active orders. Historical demo projects
    // are archived, so this one destination must open the complete archive.
    const item = window.KANPACE_MENU?.flatMap(group => group.items || [])
      .find(entry => entry.id === 'projects');
    if (item && item.projectStatus !== 'all') item.projectStatus = 'all';
    const link = document.querySelector('.sidebar a[data-nav-item="projects"]');
    if (link && /([&#])projectStatus=active(?=&|$)/.test(link.getAttribute('href') || '')) {
      link.setAttribute('href', link.getAttribute('href')
        .replace(/([&#])projectStatus=active(?=&|$)/, '$1projectStatus=all'));
    }
  };
  const refreshDemoUi = () => {
    showAllHistoricalProjects();
    mountPersonnelSnapshot();
  };
  fetch('/api/demo-info', { credentials: 'same-origin' })
    .then(response => response.ok ? response.json() : null)
    .then(info => {
      if (Number.isInteger(info?.personnel_snapshot?.count)
          && info.personnel_snapshot.count > 0
          && info.personnel_snapshot.status === 'pending_confirmation'
          && info.personnel_snapshot.download_url === '/api/demo-sources/personnel-roster') {
        personnelSnapshot = info.personnel_snapshot;
        refreshDemoUi();
      }
    }).catch(() => {});
  refreshDemoUi();
  window.addEventListener('hashchange', refreshDemoUi);
  new MutationObserver(refreshDemoUi).observe(document.body, { childList: true, subtree: true });
})();
