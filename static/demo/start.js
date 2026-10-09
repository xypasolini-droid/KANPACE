'use strict';
(async () => {
  const status = document.getElementById('status');
  try {
    const response = await fetch('/api/demo-info');
    if (!response.ok) throw new Error('请从独立演示启动器打开这个页面。');
    const info = await response.json();
    if (info.mode !== 'standalone_demo') throw new Error('这不是独立演示服务。');
    for (const link of document.querySelectorAll('[data-demo-project]')) {
      const id = info.project_ids?.[link.dataset.demoProject];
      if (!id) continue;
      link.href = '/factory/index.html#' + new URLSearchParams({page:link.dataset.page,tab:'parts',project:id});
      link.removeAttribute('aria-disabled');
    }
    status.textContent = '三个演示订单已准备好，选择下面任意一步开始。';
    for (const link of document.querySelectorAll('a[href^="/factory/"]')) {
      link.addEventListener('click', () => {
        try { localStorage.setItem('kanpace-workspace-type','cabinet'); } catch {}
      });
    }
  } catch (error) {
    status.textContent = error.message || '演示服务未连接，请重新双击启动演示。';
  }
})();
