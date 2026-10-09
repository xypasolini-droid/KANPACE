import assert from 'node:assert/strict';
import {buildOverview, previewDimensions} from '../static/project-3d/scene-data.mjs';

const project = {id: 'a', name: '真实项目', fulfillment_status: 'active'};
const item = {id: 'cabinet-a', project_id: 'a', name: '高柜', item_level: 'assembly', unit: 'mm', quantity: 3, overall_dimensions: {length_mm: 1600, width_mm: 600, height_mm: 2300}};
const data = {projects: [project, {id: 'b', name: '另一项目'}], parts: [item,
  {...item, id: 'other', project_id: 'b'}, {...item, id: 'archived', archived: true},
  {...item, id: 'procurement', procurement_reference_only: true},
  {...item, id: 'board', item_level: 'material'},
  {...item, id: 'missing', overall_dimensions: {length_mm: 1500, width_mm: 600, height_mm: null}},
  {...item, id: 'round', specification: 'φ1300*1600', overall_dimensions: {}},
  {...item, id: 'curved', name: '弧形柜', specification: '1600*600*2300'}]};
const before = JSON.stringify(data), result = buildOverview(data, 'a');
assert.deepEqual(result.items.map(i => i.id), ['cabinet-a','round','curved']);
assert.deepEqual(result.missing.map(i => i.id), ['missing']);
assert.equal(result.total, 4);
assert.equal(result.items[0].quantity, 3); // No quantity duplication or multiplying project quantity.
assert.deepEqual(result.items[0].dimensions, {x:1600,y:2300,z:600,shape:'box',basis:'清单三轴外形'});
assert.equal(result.items[1].dimensions.shape, 'cylinder');
assert.equal(result.items[1].dimensions.x, 1300);
assert.equal(result.items[1].dimensions.y, 1600);
assert(result.items[2].outlinePending);
assert.equal(JSON.stringify(data), before); // Projection must never mutate engineering data.
assert.throws(() => buildOverview(data, 'missing'), /未找到/);
assert.equal(buildOverview({projects:[{...project,fulfillment_status:'shipped'}],parts:[item]}, 'a').items.length, 1);
for (const value of [0,-1,Infinity,NaN,'1200',60000,null]) {
  assert.equal(previewDimensions({...item, overall_dimensions:{...item.overall_dimensions, height_mm:value}}), null);
}
assert.equal(previewDimensions({name:'圆柱柜', specification:'弧长1300×1600', overall_dimensions:{}}), null);
assert.equal(previewDimensions({length_mm:1800,width_mm:600,thickness_mm:18}), null); // Cut-stock dims must not become cabinets.
assert.deepEqual(previewDimensions({unit:'mm', specification:'6010*690*3990=1组\n玻璃顶罩'}), {x:6010,y:3990,z:690,shape:'box',basis:'清单三轴外形'});
assert.equal(previewDimensions({specification:'6010*690*3990=1组'}), null); // Unknown units remain unknown.
assert.equal(previewDimensions({unit:'mm',specification:'（2670+1150）*200*500'}), null);
assert.equal(previewDimensions({unit:'mm',specification:'弧长1682*550*950'}), null);
assert.equal(buildOverview({projects:[project],parts:[]}, 'a').items.length, 0);
console.log('PASS: project-scoped 3D geometry, closed project viewing, missing axes, explicit diameter, unknown curves, no BOM mutation, no quantity multiplication.');
