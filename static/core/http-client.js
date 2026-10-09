/* KANPACE JSON transport. No DOM, business state, authentication policy or retries. */
(function (root, factory) {
  'use strict';
  const transport = factory();
  if (typeof module === 'object' && module.exports) module.exports = transport;
  else {
    // Resolve fetch when called: loading this script does not start a request.
    const client = transport.createClient((...args) => root.fetch(...args));
    root.KanpaceHttp = Object.freeze({...transport, ...client});
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const isAbortError = error => error?.name === 'AbortError';
  const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);

  function failure(message, code, cause, status) {
    const error = new Error(message);
    error.code = code;
    if (cause !== undefined) error.cause = cause;
    if (status !== undefined) error.status = status;
    return error;
  }

  function checkAborted(signal) {
    if (!signal?.aborted) return;
    if (isAbortError(signal.reason)) throw signal.reason;
    const error = new Error('请求已取消');
    error.name = 'AbortError';
    error.cause = signal.reason;
    throw error;
  }

  function createClient(fetchImpl) {
    if (typeof fetchImpl !== 'function') throw new TypeError('createClient requires fetch');

    async function requestJson(path, data, options = {}) {
      const signal = options.signal;
      checkAborted(signal);
      // Serialization failures are caller errors, not connection failures.
      const requestOptions = {
        method: data === undefined ? 'GET' : 'POST',
        credentials: 'same-origin',
        headers: data === undefined ? {} : {'Content-Type': 'application/json'},
        body: data === undefined ? undefined : JSON.stringify(data),
        ...(signal ? {signal} : {}),
      };
      let response;
      try {
        // Exactly one attempt. A disconnected POST may already have committed.
        response = await fetchImpl(path, requestOptions);
      } catch (cause) {
        if (isAbortError(cause)) throw cause;
        checkAborted(signal);
        throw failure('服务器未连接，请点击重新连接。', 'NETWORK_UNAVAILABLE', cause);
      }
      checkAborted(signal);
      let result;
      try {
        result = await response.json();
      } catch (cause) {
        if (isAbortError(cause)) throw cause;
        checkAborted(signal);
        if (cause?.name === 'TypeError') {
          throw failure('服务器未连接，请点击重新连接。', 'NETWORK_UNAVAILABLE', cause, response.status);
        }
        throw failure(`服务器响应异常（HTTP ${response.status}），请重新连接。`, 'INVALID_RESPONSE', cause, response.status);
      }
      checkAborted(signal);
      if (!isObject(result)) {
        throw failure('服务器返回的数据无效，请重新连接。', 'INVALID_RESPONSE', undefined, response.status);
      }
      return {response, result};
    }

    async function request(path, data, options = {}) {
      const {response, result} = await requestJson(path, data, options);
      if (!response.ok) {
        const error = new Error(result.error || options.errorMessage || '操作失败，请重试');
        error.status = response.status;
        error.details = result.details;
        throw error;
      }
      return result;
    }

    return Object.freeze({requestJson, request});
  }

  return Object.freeze({createClient, isAbortError});
});
