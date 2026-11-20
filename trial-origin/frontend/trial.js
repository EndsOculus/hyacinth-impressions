'use strict';

const siteKey = '0x4AAAAAAGKw29vkqfaCjPkU';
const apiPath = '/_cf-trial/api';
const historyKey = 'cf-trial:history:1';
const attemptKey = 'cf-trial:pending:1';
const direct = location.hostname === 'vote.ends0culus.com';
const alternate = direct ? 'https://cf-test.ends0culus.com/' : 'https://vote.ends0culus.com/_cf-trial/';
const routeLabel = direct ? '香港直连' : '橙云';
const labels = {wifi: 'Wi‑Fi', cellular: '蜂窝', other: '其他'};
const byId = id => document.getElementById(id);
const format = ms => Number.isFinite(ms) ? (ms / 1000).toFixed(2) + ' s' : '—';
byId('route-label').textContent = routeLabel;
byId('privacy-route').textContent = direct
  ? '当前页面直连香港源站。同意后才会连接 Cloudflare Turnstile。'
  : '本页流量经过 Cloudflare 代理。点击同意后才会加载 Turnstile 验证组件。';
const queryNetwork = new URLSearchParams(location.search).get('network');
if (Object.hasOwn(labels, queryNetwork)) {
  document.querySelector('input[value="'+queryNetwork+'"]').checked = true;
}
const run = {id: crypto.randomUUID(), network: Object.hasOwn(labels, queryNetwork) ? queryNetwork : '', open: performance.now(), assets: null, verify: null, post: null, state: ''};
byId('open').textContent = format(run.open);

function readStore(store, key, fallback) {
  try { return JSON.parse(window[store].getItem(key)) ?? fallback; } catch { return fallback; }
}
function writeStore(store, key, value) {
  try {
    if (value === null) window[store].removeItem(key);
    else window[store].setItem(key, JSON.stringify(value));
  } catch { /* The comparison still works in this tab. */ }
}
let historyRows = readStore('localStorage', historyKey, []);
if (!Array.isArray(historyRows)) historyRows = [];
function saveRun(state) {
  run.state = state;
  if (!run.network) return;
  historyRows = [{...run}, ...historyRows.filter(row => row.id !== run.id)].slice(0, 12);
  writeStore('localStorage', historyKey, historyRows);
  drawHistory();
}
function drawHistory() {
  const table = byId('history');
  table.hidden = !historyRows.length;
  byId('empty').hidden = Boolean(historyRows.length);
  const body = table.tBodies[0];
  body.replaceChildren();
  for (const row of historyRows) {
    const tr = body.insertRow();
    for (const val of [labels[row.network], format(row.open), format(row.assets), format(row.verify), format(row.post), row.state]) {
      tr.insertCell().textContent = val;
    }
  }
}
drawHistory();

const status = msg => { byId('status').textContent = msg; };
let sampleFinished = false, sampleFailed = false, locked = false, token = '', widgetId;
let generation = 0, challengeTimer, scriptPromise, verifying = false, sending = false, complete = false;
function selected() { return document.querySelector('input[name="network"]:checked')?.value || ''; }
function updateControls() {
  const link = byId('compare');
  const next = new URL(alternate);
  if (selected()) next.searchParams.set('network', selected());
  link.href = next.href;
  link.textContent = '用当前网络测试' + (direct ? '橙云' : '香港直连');
  link.hidden = !selected() || sending;
  byId('begin').disabled = !selected() || !sampleFinished || verifying || sending || Boolean(token) || complete;
  byId('begin').hidden = Boolean(token) || complete;
  byId('send').hidden = !token || complete;
  byId('send').disabled = sending;
  byId('networks').disabled = locked;
  byId('restart').disabled = sending;
}
byId('networks').addEventListener('change', () => {
  run.network = selected();
  if (sampleFailed) saveRun('资源失败');
  status(sampleFinished ? '可以开始人机验证。' : '正在下载问卷资源…');
  updateControls();
});

async function measureSamples() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 25000);
  const start = performance.now();
  try {
    const sizes = await Promise.all(['survey.js','survey.css'].map(async name => {
      const response = await fetch('./samples/' + name, {
        cache: 'no-store', credentials: 'omit', signal: controller.signal
      });
      const type = response.headers.get('content-type') || '';
      if (!response.ok || /html|json/i.test(type)) throw new Error('asset');
      const size = (await response.arrayBuffer()).byteLength;
      if (size < (name.endsWith('.js') ? 100000 : 3000)) throw new Error('size');
      return size;
    }));
    run.assets = performance.now() - start;
    byId('assets').textContent = format(run.assets);
    byId('sample-note').textContent = '正式问卷的 JS 和 CSS 合计 ' + Math.round((sizes[0]+sizes[1])/1024) + ' KiB（解压后）。并行下载，不执行问卷代码。页面打开计时截止到本页可操作。';
  } catch {
    sampleFailed = true;
    byId('assets').textContent = '下载失败';
    byId('sample-note').textContent = '问卷资源未能完整下载，仍可单独测试验证和提交。';
    saveRun('资源失败');
  } finally {
    controller.abort();
    clearTimeout(timer); sampleFinished = true; updateControls();
    if (selected()) status('可以开始人机验证。');
  }
}
measureSamples();

function loadTurnstile() {
  if (window.turnstile) return Promise.resolve(window.turnstile);
  if (scriptPromise) return scriptPromise;
  const script = document.createElement('script');
  const request = new Promise((resolve, reject) => {
    const clean = () => { clearTimeout(timer); script.onload = script.onerror = null; };
    const fail = () => { clean(); script.remove(); reject(new Error('script')); };
    const timer = setTimeout(fail, 18000);
    script.onload = () => {
      if (!window.turnstile) { fail(); return; }
      clean(); resolve(window.turnstile);
    };
    script.onerror = fail;
    script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
    script.async = true;
    document.head.appendChild(script);
  });
  scriptPromise = request.catch(error => { scriptPromise = null; throw error; });
  return scriptPromise;
}

function resetWidget() {
  generation++;
  clearTimeout(challengeTimer);
  if (widgetId !== undefined && window.turnstile) {
    window.turnstile.remove(widgetId); widgetId = undefined;
  }
  verifying = false;
  token = '';
}
function challengeFailed(message) {
  if (sending || complete) return;
  resetWidget();
  byId('begin').textContent = '重新验证';
  byId('verify').textContent = '未完成';
  status(message);
  saveRun('验证未完成');
  updateControls();
}
byId('begin').addEventListener('click', async () => {
  if (byId('begin').disabled) return;
  resetWidget();
  run.network = selected();
  locked = true; verifying = true;
  const thisGeneration = generation;
  const start = performance.now();
  byId('verify').textContent = '验证中';
  status('等待 Cloudflare 验证，请按页面提示操作。');
  saveRun('验证中'); updateControls();
  challengeTimer = setTimeout(() => challengeFailed('验证等待超时，可以重新验证。'), 120000);
  try {
    const widget = await loadTurnstile();
    if (generation !== thisGeneration) return;
    widgetId = widget.render(byId('challenge'), {
      sitekey: siteKey, action: 'cf_trial', cData: run.id, size: 'flexible', language: 'zh-CN',
      callback: value => {
        if (generation !== thisGeneration || !value) return;
        clearTimeout(challengeTimer); verifying = false; token = value;
        run.verify = performance.now() - start; byId('verify').textContent = format(run.verify);
        status('人机验证已完成，可以提交这次测试。');
        saveRun('待提交'); updateControls();
      },
      'error-callback': () => {
        if (generation === thisGeneration) challengeFailed('验证未通过或资源未加载，可以重新验证。');
        return true;
      },
      'expired-callback': () => {
        if (generation === thisGeneration) challengeFailed('验证已过期，请重新验证后提交。');
      },
      'timeout-callback': () => {
        if (generation === thisGeneration) challengeFailed('验证超时，可以重新验证。');
      }
    });
  } catch {
    if (generation === thisGeneration) challengeFailed('Cloudflare 验证组件未加载，可以重新验证。');
  }
});

byId('send').addEventListener('click', async () => {
  if (sending || !token || complete) return;
  sending = true;
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 25000);
  const start = performance.now();
  writeStore('sessionStorage', attemptKey, {id: run.id, network:run.network});
  status('正在向独立测试服务提交…'); byId('submit-time').textContent = '提交中';
  saveRun('提交中'); updateControls();
  try {
    const res = await fetch(apiPath, {method:'POST', credentials:'same-origin', cache:'no-store',
      signal:controller.signal, headers:{'Content-Type':'application/json'},
      body:JSON.stringify({attempt:run.id, network:run.network, token})});
    const body = await res.json();
    if (res.status !== 200 || body.ok !== true || body.attempt !== run.id) throw new Error(body.error || 'unconfirmed');
    run.post = performance.now() - start; byId('submit-time').textContent = format(run.post);
    complete = true; writeStore('sessionStorage', attemptKey, null); resetWidget();
    saveRun(sampleFailed ? '已提交·资源失败' : '已提交');
    status(body.duplicate ? '已确认先前的测试回执，重试没有重复写入。' : '测试回执已写入。可以切换网络，重新打开页面对照。');
  } catch (error) {
    run.post = performance.now() - start;
    byId('submit-time').textContent = '未确认 · '+format(run.post);
    const rejected = error.message === 'verification-rejected';
    resetWidget(); byId('begin').textContent = '重新验证并重试';
    status(rejected ? '服务端未接受验证，请重新验证。' : '暂未收到有效回执。重新验证后可用同一测试编号重试。');
    saveRun('提交未确认');
  } finally { clearTimeout(timer); sending = false; updateControls(); }
});

// On an ordinary reload after an unconfirmed submit, keep its id and network.
// An explicit new measurement always starts a fresh navigation and attempt.
const pending = readStore('sessionStorage', attemptKey, null);
if (pending && (!run.network || pending.network === run.network) && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(pending.id) && Object.hasOwn(labels,pending.network)) {
  run.id = pending.id; run.network = pending.network; locked = true;
  document.querySelector('input[value="'+pending.network+'"]').checked = true;
  status('上次提交尚未确认。继续验证可重试同一回执；换网请重新测。');
  updateControls();
}
updateControls();
byId('restart').addEventListener('click', () => {
  if (sending) return;
  writeStore('sessionStorage', attemptKey, null);
  const url = new URL(location.pathname, location.origin);
  url.searchParams.set('run', crypto.randomUUID());
  location.replace(url.href);
});
