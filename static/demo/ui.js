'use strict';
// Loaded by DemoHandler only; regular production HTML never includes this file.
if (!location.pathname.startsWith('/demo/')) {
  const link = document.createElement('a');
  link.href='/demo/index.html';
  link.textContent='独立演示 · 返回体验入口';
  link.setAttribute('aria-label','独立演示，当前为合成资料，返回体验入口');
  link.style.cssText='position:fixed;bottom:12px;left:12px;z-index:3000;padding:10px 14px;background:#203c28;color:#fff;border-radius:6px;font:14px/1.4 -apple-system,BlinkMacSystemFont,"Microsoft YaHei",sans-serif;box-shadow:0 2px 10px #0002;text-decoration:none';
  document.body.append(link);
}
