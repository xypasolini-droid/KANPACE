'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {createClient} = require('../static/core/http-client.js');
const response = (result, status = 200) => ({ok: status >= 200 && status < 300, status, json: async () => result});
const fixture = reply => {
  const calls = [];
  const client = createClient(async (url, options) => {calls.push({url, options});return reply(url, options);});
  return {client, calls};
};

test('browser registration starts no requests and resolves injected fetch lazily', async () => {
  const c = {calls: [], fetch: async (url, options) => {c.calls.push({url, options});return response({ok:true});}};
  vm.runInNewContext(fs.readFileSync(require.resolve('../static/core/http-client.js'), 'utf8'), c);
  assert.equal(c.calls.length, 0);
  assert.equal(typeof c.KanpaceHttp.createClient, 'function');
  await c.KanpaceHttp.request('/api/state');
  assert.equal(c.calls.length, 1);
  assert.equal(c.calls[0].url, '/api/state');
});

test('GET and POST have explicit same-origin credentials and exact JSON payload', async () => {
  const f = fixture(() => response({saved:true}));
  assert.deepEqual(await f.client.request('/api/state'), {saved:true});
  await f.client.request('/api/tasks/task_a/progress', {completed_quantity:3, expected_execution_version:7});
  assert.equal(f.calls[0].options.method, 'GET');
  assert.equal(f.calls[0].options.body, undefined);
  assert.deepEqual(f.calls[0].options.headers, {});
  assert.equal(f.calls[1].options.method, 'POST');
  assert.deepEqual(f.calls[1].options.headers, {'Content-Type':'application/json'});
  assert.deepEqual(JSON.parse(f.calls[1].options.body), {completed_quantity:3,expected_execution_version:7});
  assert(f.calls.every(call => call.options.credentials === 'same-origin'));
});

test('explicit null is a POST and serialization errors do not start a request', async () => {
  const f = fixture(() => response({}));
  await f.client.request('/api/action', null);
  assert.equal(f.calls[0].options.body, 'null');
  const cyclic = {};cyclic.self = cyclic;
  await assert.rejects(f.client.request('/api/action', cyclic), error => error.name === 'TypeError' && !error.code);
  assert.equal(f.calls.length, 1);
});

test('raw response allows a device adapter to inspect details before raising HTTP errors', async () => {
  const details = {device:{wifi:{connected:true}},ports:['test-port']};
  const raw = response({error:'任务已变化',details}, 409);
  const f = fixture(() => raw);
  const result = await f.client.requestJson('/api/device/send', {});
  assert.equal(result.response, raw);
  assert.equal(result.result.details, details);
  assert.equal(f.calls.length, 1);
});

for (const status of [401, 403, 409, 500]) {
  test(`HTTP ${status} retains the business message and structured details without retries`, async () => {
    const details = {code:'specific-business-code', tasks:[{id:'task_a',version:7}]};
    const f = fixture(() => response({error:'请核对当前记录',details}, status));
    await assert.rejects(f.client.request('/api/action', {}), error => error.status === status && error.message === '请核对当前记录' && error.details === details && error.code !== 'NETWORK_UNAVAILABLE');
    assert.equal(f.calls.length, 1);
  });
}

test('HTTP fallback messages are caller-owned and have no endpoint or body disclosure', async () => {
  const f = fixture(() => response({}, 400));
  await assert.rejects(f.client.request('/api/access/login', {password:'never-print-this'}, {errorMessage:'登录未完成'}), error => error.status === 400 && error.message === '登录未完成' && !JSON.stringify(error).includes('never-print-this'));
});

test('network failures preserve cause and never replay a possibly committed POST', async () => {
  const cause = new TypeError('Failed to fetch');
  const f = fixture(() => {throw cause;});
  await assert.rejects(f.client.request('/api/tasks/task_a/progress', {}), error => error.code === 'NETWORK_UNAVAILABLE' && error.cause === cause && error.message === '服务器未连接，请点击重新连接。');
  assert.equal(f.calls.length, 1);
});

test('malformed JSON preserves HTTP status for login and business recovery', async () => {
  for (const status of [200, 401, 503]) {
    const cause = new SyntaxError('HTML instead of JSON');
    const f = fixture(() => ({ok:status===200,status,json:async()=>{throw cause;}}));
    await assert.rejects(f.client.request('/api/state'), error => error.code === 'INVALID_RESPONSE' && error.status === status && error.cause === cause && error.message.includes(`HTTP ${status}`));
    assert.equal(f.calls.length, 1);
  }
});

test('connection interruption while reading JSON remains a network failure with HTTP status', async () => {
  const cause = new TypeError('stream closed');
  const f = fixture(() => ({ok:true,status:200,json:async()=>{throw cause;}}));
  await assert.rejects(f.client.request('/api/state'), error => error.code === 'NETWORK_UNAVAILABLE' && error.cause === cause && error.status === 200);
});

test('unexpected JSON primitives and arrays cannot pass as a business response', async () => {
  for (const value of [null, undefined, [], true, 0, 'ok']) {
    const f = fixture(() => response(value));
    await assert.rejects(f.client.request('/api/state'), error => error.code === 'INVALID_RESPONSE' && error.status === 200);
  }
});

test('a pre-aborted request does not access the network', async () => {
  const controller = new AbortController();controller.abort();
  const f = fixture(() => response({}));
  await assert.rejects(f.client.request('/api/state', undefined, {signal:controller.signal}), error => error === controller.signal.reason && error.name === 'AbortError');
  assert.equal(f.calls.length, 0);
});

test('AbortError identity survives both fetch and response decoding', async () => {
  const cancelled = new Error('cancelled');cancelled.name = 'AbortError';
  for (const reply of [() => {throw cancelled;}, () => ({ok:true,status:200,json:async()=>{throw cancelled;}})]) {
    const f = fixture(reply);
    await assert.rejects(f.client.request('/api/state'), error => error === cancelled && !error.code);
    assert.equal(f.calls.length, 1);
  }
});

test('a late response cannot revive a cancelled request even if the transport ignores cancellation', async () => {
  const controller = new AbortController();let finish;
  const f = fixture(() => new Promise(resolve => {finish = resolve;}));
  const pending = f.client.request('/api/agent/message', {message:'query'}, {signal:controller.signal});
  controller.abort();finish(response({private:'old response'}));
  await assert.rejects(pending, error => error.name === 'AbortError');
  assert.equal(f.calls[0].options.signal, controller.signal);
  assert.equal(f.calls.length, 1);
});

test('cancellation during JSON parsing cannot return the decoded object', async () => {
  const controller = new AbortController();
  const f = fixture(() => ({ok:true,status:200,json:async()=>{controller.abort('closed');return {private:'old response'};}}));
  await assert.rejects(f.client.request('/api/agent/message', {}, {signal:controller.signal}), error => error.name === 'AbortError' && !error.code);
});

test('independent clients do not share requests or mutable application state', async () => {
  const a = fixture(() => response({factory:'a'})), b = fixture(() => response({factory:'b'}));
  assert.deepEqual(await Promise.all([a.client.request('/api/state'),b.client.request('/api/state')]), [{factory:'a'},{factory:'b'}]);
  assert.equal(a.calls.length, 1);assert.equal(b.calls.length, 1);
  assert(Object.isFrozen(a.client));
});
