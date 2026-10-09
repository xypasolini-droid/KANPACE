const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const lines = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8').split('\n');
const timers = new Map();
let nextTimer = 0;
const c = {
  console, Promise, Date: { now: () => c.now }, now: 100000,
  window: {}, location: { hash: '#page=drawing&project=p1' }, document: { hidden: false, activeElement: { closest: () => c.editing }, querySelector: () => c.dialog },
  localStorage: { setItem() {} }, editing: null, dialog: null, renders: 0, requests: 0, gate: null, failure: null,
  setTimeout(fn) { const id = ++nextTimer; timers.set(id, fn); return id; },
  clearTimeout(id) { timers.delete(id); },
};
vm.createContext(c);
vm.runInContext(`
let refreshToken=0, state={people:[],tasks:[]}, page='drawing',tab='parts',projectId='p1',pendingTaskDeepLink='',quote=null;
let kanpaceAppStarted=true,uploadBusy=false;const trades=[];
const $=()=>({open:false});
function currentProject(){return {id:'p1'};}function syncWorkspaceProject(){}function clearConnectionNotice(){}
function render(){renders++;}function refreshDevice(){deviceReads++;}let deviceReads=0;
async function api(path){requests++;if(gate)await gate;if(failure)throw failure;return path==='/api/state'?{people:[],tasks:[]}:{};}
`, c);
for (const prefix of ['let focusRefreshTimer=', 'async function refresh(){', 'async function readWorkspaceState(){', 'function canRefreshOnFocus(){', 'function queueFocusRefresh(){']) {
  const line = lines.find(s => s.startsWith(prefix));
  assert(line, `missing ${prefix}`); vm.runInContext(line, c);
}
const run = s => vm.runInContext(s, c);
async function fireTimers() {
  c.now += 300;
  const pending = [...timers.values()]; timers.clear(); pending.forEach(fn => fn());
  await new Promise(resolve => setImmediate(resolve));
}

(async () => {
  await run('refresh()');
  assert.equal(c.renders, 1);
  assert.equal(run('lastStateRefreshAt'), c.now);
  run('queueFocusRefresh();queueFocusRefresh();queueFocusRefresh()');
  assert.equal(timers.size, 0, 'fresh data should not reload just because the user returns to the browser');
  c.now += 31000;
  run('queueFocusRefresh();queueFocusRefresh();queueFocusRefresh()');
  assert.equal(timers.size, 1, 'rapid focus events should coalesce into one refresh');
  assert.equal(c.renders, 1, 'focus must leave the current controls in place for the initial click');
  await fireTimers(); assert.equal(c.renders, 2);

  // The user can open a drawing or start typing during the debounce interval.
  for (const field of ['dialog', 'editing']) {
    c.now += 31000; run('queueFocusRefresh()'); assert.equal(timers.size, 1);
    c[field] = {}; await fireTimers(); assert.equal(c.renders, 2, `${field} must not be interrupted`);
    run('queueFocusRefresh()'); assert.equal(timers.size, 0); c[field] = null;
  }
  c.document.hidden = true; run('queueFocusRefresh()'); assert.equal(timers.size, 0); c.document.hidden = false;
  run('uploadBusy=true;queueFocusRefresh()'); assert.equal(timers.size, 0); run('uploadBusy=false');

  let release; c.gate = new Promise(resolve => { release = resolve; });
  const pending = run('refresh()');
  assert.equal(run('stateRefreshInFlight'), 1);
  run('queueFocusRefresh()'); assert.equal(timers.size, 0, 'focus must not duplicate a navigation or manual refresh');
  release(); await pending; c.gate = null;
  assert.equal(run('stateRefreshInFlight'), 0); assert.equal(c.renders, 3);
  await run('refresh()'); assert.equal(c.renders, 4, 'explicit refresh remains immediate within the focus cooldown');

  const stamp = run('lastStateRefreshAt'); c.now += 31000; c.failure = new Error('offline');
  await assert.rejects(run('refresh()'), /offline/);
  assert.equal(run('stateRefreshInFlight'), 0); assert.equal(run('lastStateRefreshAt'), stamp);
  c.failure = null; run('queueFocusRefresh()'); await fireTimers(); assert.equal(c.renders, 5, 'failed reads must remain retryable');
  run("page='device';queueFocusRefresh()"); assert.equal(run('deviceReads'), 1, 'device status keeps its own refresh path');
  console.log('PASS: focus debounce, freshness, dialogs, editing, upload and in-flight guards, explicit refresh, error recovery, and device polling.');
})().catch(error => { console.error(error); process.exitCode = 1; });
