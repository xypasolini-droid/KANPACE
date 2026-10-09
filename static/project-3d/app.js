import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { buildOverview } from './scene-data.mjs';

const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const params = new URLSearchParams(location.search), projectId = params.get('project');
if (params.get('embed') === '1') document.body.classList.add('embedded');
let overview, scene, renderer, camera, controls, objects = [], floor, grid, selected = '', view = 'iso', pointer, resizeObserver;
const format = n => Number(n).toLocaleString('zh-CN', {maximumFractionDigits: 1});

function notice(title, text = '', retry = false) {
  $('#status-panel').hidden = false;
  $('#status-panel').innerHTML = `<strong>${esc(title)}</strong>${text ? `<p>${esc(text)}</p>` : ''}${retry ? '<button id="retry">重新连接</button>' : ''}`;
  $('#retry')?.addEventListener('click', () => location.reload());
}
function render() { if (renderer) renderer.render(scene, camera); }
function initialiseScene() {
  scene = new THREE.Scene(); scene.background = new THREE.Color('#edf0f4');
  camera = new THREE.PerspectiveCamera(38, 1, .001, 10000);
  renderer = new THREE.WebGLRenderer({antialias: true});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.1;
  $('#canvas').appendChild(renderer.domElement);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = false; controls.maxPolarAngle = Math.PI * .92;
  controls.addEventListener('change', render);
  controls.addEventListener('start', () => {
    document.querySelectorAll('[data-view]').forEach(b => b.setAttribute('aria-pressed', 'false'));
    view = 'free';
  });
  scene.add(new THREE.HemisphereLight('#ffffff', '#9ba5b3', 3));
  const sun = new THREE.DirectionalLight('#ffffff', 3); sun.position.set(4, 8, 6); scene.add(sun);
  const fill = new THREE.DirectionalLight('#d7e6ff', 1.5); fill.position.set(-5, 3, -4); scene.add(fill);
  resizeObserver = new ResizeObserver(() => {
    const {clientWidth: width, clientHeight: height} = $('#canvas'); if (!width || !height) return;
    const nextAspect = width / height;
    if (objects.length && camera.aspect > 0) {
      const factor = Math.max(1, 1 / nextAspect) / Math.max(1, 1 / camera.aspect);
      camera.position.sub(controls.target).multiplyScalar(factor).add(controls.target);
      controls.maxDistance *= factor;
    }
    renderer.setSize(width, height, false); camera.aspect = nextAspect; camera.updateProjectionMatrix(); controls.update(); render();
  });
  resizeObserver.observe($('#canvas'));
  renderer.domElement.addEventListener('pointerdown', event => pointer = {x: event.clientX, y: event.clientY, button: event.button});
  renderer.domElement.addEventListener('pointerup', pick);
  renderer.domElement.addEventListener('webglcontextlost', event => {event.preventDefault(); notice('3D 画面已暂停', '重新打开可恢复模型。', true);});
}
function label(text, width) {
  const canvas = document.createElement('canvas'); canvas.width = 512; canvas.height = 80;
  const context = canvas.getContext('2d'); context.clearRect(0, 0, 512, 80);
  context.fillStyle = '#445569'; context.font = '500 28px -apple-system, "PingFang SC", sans-serif';
  context.textAlign = 'center'; context.textBaseline = 'middle';
  context.fillText(text.length > 19 ? text.slice(0, 18) + '…' : text, 256, 40, 488);
  const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({map: texture, depthTest: false, transparent: true}));
  sprite.scale.set(width, width * 80 / 512, 1); sprite.renderOrder = 8; return sprite;
}
function buildScene(items) {
  // Each order row is represented once, regardless of its quantity; this is a catalogue, not a floor plan.
  const columns = Math.min(5, Math.ceil(Math.sqrt(items.length)));
  const widths = [], depths = [], heights = items.map(i => i.dimensions.y / 1000);
  const maxHeight = Math.max(...heights, 1), gap = Math.max(.65, maxHeight * .32);
  items.forEach((item, i) => {const col = i % columns, row = Math.floor(i / columns); widths[col] = Math.max(widths[col] || 0, item.dimensions.x / 1000); depths[row] = Math.max(depths[row] || 0, item.dimensions.z / 1000);});
  const totalWidth = widths.reduce((a, b) => a + b, 0) + (columns - 1) * gap;
  const totalDepth = depths.reduce((a, b) => a + b, 0) + (depths.length - 1) * gap;
  for (const [i, item] of items.entries()) {
    const {x: xm, y: ym, z: zm, shape} = item.dimensions, x = xm / 1000, y = ym / 1000, z = zm / 1000;
    const col = i % columns, row = Math.floor(i / columns);
    const px = -totalWidth / 2 + widths.slice(0, col).reduce((a, b) => a + b, 0) + col * gap + widths[col] / 2;
    const pz = -totalDepth / 2 + depths.slice(0, row).reduce((a, b) => a + b, 0) + row * gap + depths[row] / 2;
    const group = new THREE.Group(); group.position.set(px, 0, pz); group.userData.item = item;
    const geometry = shape === 'cylinder' ? new THREE.CylinderGeometry(x / 2, x / 2, y, 48) : new THREE.BoxGeometry(x, y, z);
    // These translucent envelopes show only known overall dimensions, without inventing doors or internal parts.
    const material = new THREE.MeshStandardMaterial({color: item.appearance.color, metalness: .12, roughness: .48, transparent: true, opacity: item.outlinePending ? .34 : .72, depthWrite: true});
    const mesh = new THREE.Mesh(geometry, material); mesh.position.y = y / 2; mesh.userData.item = item;
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 25), new THREE.LineBasicMaterial({color: '#64788b', transparent: true, opacity: .65}));
    edges.position.copy(mesh.position); group.add(mesh, edges);
    const title = label(item.name, Math.min(3.5, Math.max(1.5, widths[col] * .85)));
    title.position.set(0, -.08, z / 2 + gap * .3); group.add(title);
    group.userData.mesh = mesh; group.userData.edges = edges; group.userData.label = title;
    objects.push(group); scene.add(group);
  }
  const size = Math.max(totalWidth, totalDepth, 5) * 1.6;
  floor = new THREE.Mesh(new THREE.PlaneGeometry(size, size), new THREE.MeshStandardMaterial({color: '#edf0f4', roughness: 1}));
  floor.rotation.x = -Math.PI / 2; floor.position.y = -.12; scene.add(floor);
  grid = new THREE.GridHelper(Math.ceil(size), Math.min(Math.ceil(size), 100), '#d2dbe4', '#e0e6ec');
  grid.position.y = -.115; scene.add(grid);
  $('#status-panel').hidden = true;
  setView('iso');
}
function visibleBounds() {
  scene.updateMatrixWorld(true);
  const box = new THREE.Box3();
  for (const group of objects.filter(g => g.visible)) box.expandByObject(group.userData.mesh);
  return box;
}
function setView(next = 'iso') {
  if (!objects.length) return;
  view = next; const box = visibleBounds(), centre = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3());
  const radius = Math.max(.1, size.length() / 2);
  const width = $('#canvas').clientWidth || 700, height = $('#canvas').clientHeight || 420; camera.aspect = width / height;
  const directions = {iso: [1, .78, 1.2], front: [0, .06, 1], back: [0, .06, -1], right: [1, .06, 0], top: [0, 1, .0001]};
  const direction = new THREE.Vector3(...(directions[next] || directions.iso)).normalize();
  const right = new THREE.Vector3(0, 1, 0).cross(direction).normalize(), up = direction.clone().cross(right).normalize();
  const tangentY = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)), tangentX = tangentY * camera.aspect;
  let distance = radius;
  for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
    const corner = new THREE.Vector3(x, y, z).sub(centre), depth = corner.dot(direction);
    distance = Math.max(distance, depth + Math.abs(corner.dot(right)) / tangentX, depth + Math.abs(corner.dot(up)) / tangentY);
  }
  distance *= 1.12;
  camera.position.copy(centre).add(direction.multiplyScalar(distance));
  camera.near = Math.max(.0001, radius / 10000); camera.far = distance + radius * 60; camera.updateProjectionMatrix();
  controls.target.copy(centre); controls.minDistance = Math.max(radius * .1, .1); controls.maxDistance = distance * 8; controls.update();
  document.querySelectorAll('[data-view]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === next)));
  render();
}
function select(id, focus = true) {
  selected = id; $('#cabinet-select').value = id;
  for (const group of objects) {group.visible = !id || group.userData.item.id === id; group.userData.label.visible = !id;}
  const item = overview.items.find(i => i.id === id); $('#selection').hidden = !item;
  if (item) {
    const d = item.dimensions;
    $('#selection').innerHTML = `<strong>${esc(item.name)}</strong><p>${esc(item.specification || `${format(d.x)} × ${format(d.z)} × ${format(d.y)}`)} · ${esc(item.quantity == null ? '数量待确认' : format(item.quantity) + ' ' + item.quantityUnit)}</p>${item.outlinePending ? '<small>外形包络 · 具体轮廓待建模</small>' : ''}`;
    $('#basis').innerHTML = `<span class="source-title">${esc(item.source)}</span>${item.reference ? '<br>' + esc(item.reference) : ''}<br>${esc(item.appearance.label)}；清单三轴按原记录显示，方向与内部结构需工程模型确认。`;
  } else $('#basis').textContent = '按清单外形尺寸展示，每种柜型显示一件。排列仅便于浏览，颜色为示意；未重建内部结构和现场布局。';
  if (focus) setView('iso'); else render();
}
function pick(event) {
  if (!pointer || pointer.button !== 0 || Math.hypot(pointer.x - event.clientX, pointer.y - event.clientY) > 5) return;
  pointer = null; const rect = renderer.domElement.getBoundingClientRect();
  const ray = new THREE.Raycaster(); ray.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, 1 - (event.clientY - rect.top) / rect.height * 2), camera);
  const hit = ray.intersectObjects(objects.filter(g => g.visible).map(g => g.userData.mesh), false)[0];
  if (hit) select(hit.object.userData.item.id);
}
$('#cabinet-select').addEventListener('change', event => select(event.target.value));
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => setView(button.dataset.view)));
$('#fit').addEventListener('click', () => setView(view === 'free' ? 'iso' : view));
$('#stage').addEventListener('keydown', event => {
  if (event.target !== $('#stage') || !controls) return;
  if (event.key === 'Escape') {select(''); return;}
  if (event.key.toLowerCase() === 'f') {setView('iso'); return;}
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
  view = 'free'; document.querySelectorAll('[data-view]').forEach(button => button.setAttribute('aria-pressed', 'false'));
  event.preventDefault(); const offset = camera.position.clone().sub(controls.target), spherical = new THREE.Spherical().setFromVector3(offset);
  if (event.key === 'ArrowLeft') spherical.theta -= .18; if (event.key === 'ArrowRight') spherical.theta += .18;
  if (event.key === 'ArrowUp') spherical.phi -= .14; if (event.key === 'ArrowDown') spherical.phi += .14;
  spherical.phi = THREE.MathUtils.clamp(spherical.phi, .05, Math.PI * .92); camera.position.copy(controls.target).add(new THREE.Vector3().setFromSpherical(spherical)); controls.update(); render();
});
window.addEventListener('pagehide', event => {
  if (event.persisted) return;
  resizeObserver?.disconnect(); controls?.dispose();
  scene?.traverse(node => {node.geometry?.dispose(); for (const material of Array.isArray(node.material) ? node.material : node.material ? [node.material] : []) {material.map?.dispose(); material.dispose();}});
  renderer?.dispose();
});

try {
  if (!projectId) throw new Error('请从项目的图纸拆单页进入 清单尺寸示意。');
  let response; try {response = await fetch('/api/state');} catch {throw new Error('本地服务未连接，请重新连接。');}
  if (!response.ok) throw new Error('项目数据读取失败，请重新连接。');
  let data; try {data = await response.json();} catch {throw new Error('项目数据响应无效，请重新连接。');}
  overview = buildOverview(data, projectId);
  document.title = overview.project.name + ' · 清单尺寸示意 · KANPACE';
  $('#project-name').textContent = overview.project.name;
  $('#back').href = '/#' + new URLSearchParams({page: 'drawing', tab: 'parts', project: projectId});
  $('#upload').href = '/model/index.html?' + new URLSearchParams({project: projectId});
  if (overview.project.closed) $('#upload').textContent = '查看工程模型 ↗';
  $('#cabinet-select').innerHTML = '<option value="">全部柜型</option>' + overview.items.map(item => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join('');
  $('#coverage').textContent = `${overview.items.length} / ${overview.total} 项外形可预览 · 每种展示一件`;
  if (overview.missing.length) {
    $('#pending').hidden = false; $('#pending').innerHTML = `<details><summary>${overview.missing.length} 项缺完整外形尺寸</summary><ul>${overview.missing.map(item => `<li>${esc(item.name)}${item.specification ? ' · ' + esc(item.specification) : ''}</li>`).join('')}</ul></details>`;
  }
  if (!overview.items.length) {
    notice('暂无可用的清单尺寸', overview.project.demo ? '这是演示项目，可在 工程模型中查看示例模型。' : '此页仅表示清单外形尺寸。查看真实设计请打开工程模型。');
    $('#status-panel').insertAdjacentHTML('beforeend', `<a href="${esc($('#upload').href)}" target="_top">打开 工程模型 ↗</a>`);
    document.querySelectorAll('.toolbar button,.toolbar select').forEach(control => control.disabled = true);
  } else {initialiseScene(); buildScene(overview.items);}
} catch (error) {notice('清单尺寸示意暂时无法显示', error.message, true);}
