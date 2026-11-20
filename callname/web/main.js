/**
 * 主窗口逻辑：按钮、HUD、⚙、状态轮询，以及 --auto 自测入口。
 *
 * 与 Python 的契约见 callname/schemas.py：
 *   status() -> ApiResponse<StatusResult>
 *   draw()   -> ApiResponse<DrawResult>
 *   reset()  -> ApiResponse<StatusResult>
 *   open_manage() -> ApiResponse<LaunchResult>
 */

import { Reel } from './reel.js';

const SPIN_MS = 2600;
const POLL_MS = 1500;
const IDLE_DECOY_POOL = ['点名', '准备开始', '点击开始'];

/** @type {{ status: any, busy: boolean, rosterVersion: number, idle: boolean }} */
const state = {
  status: null,
  busy: false,
  rosterVersion: -1,
  idle: true,
};

const reel = new Reel(
  /** @type {HTMLElement} */ (document.getElementById('clip')),
  /** @type {HTMLElement} */ (document.getElementById('strip')),
);

const startBtn = /** @type {HTMLButtonElement} */ (document.getElementById('start'));
const resetBtn = /** @type {HTMLButtonElement} */ (document.getElementById('reset'));
const manageBtn = /** @type {HTMLButtonElement} */ (document.getElementById('manage'));
const hudCycle = /** @type {HTMLElement} */ (document.getElementById('hud-cycle'));
const hudRemaining = /** @type {HTMLElement} */ (document.getElementById('hud-remaining'));
const hudDrawn = /** @type {HTMLElement} */ (document.getElementById('hud-drawn'));
const hudFill = /** @type {HTMLElement} */ (document.getElementById('hud-fill'));
const hudTrack = /** @type {HTMLElement} */ (document.getElementById('hud-track'));
const toast = /** @type {HTMLElement} */ (document.getElementById('toast'));

let toastTimer = 0;

/** @param {string} message @param {number} [ms] @param {boolean} [isError] */
function showToast(message, ms = 2600, isError = false) {
  toast.textContent = message;
  toast.classList.toggle('is-error', isError);
  toast.classList.add('show');
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove('show'), ms);
}

/** 后端统一信封。 */
class ApiFailure extends Error {
  /** @param {{code: string, message: string}} error */
  constructor(error) {
    super(error.message);
    this.code = error.code;
  }
}

/** @param {Promise<any>} promise */
async function unwrap(promise) {
  const response = await promise;
  if (!response || response.ok !== true) {
    throw new ApiFailure((response && response.error) || { code: 'UNKNOWN', message: '未知错误' });
  }
  return response.data;
}

/**
 * @param {import('./main.js').StatusResult} status
 */
function renderStatus(status) {
  state.status = status;
  hudCycle.textContent = String(status.cycle);
  hudRemaining.textContent = String(status.remaining);
  hudDrawn.textContent = `${status.drawn} / ${status.active}`;
  const ratio = status.active > 0 ? status.drawn / status.active : 0;
  hudFill.style.width = `${Math.round(ratio * 100)}%`;
  hudTrack.setAttribute('aria-valuemax', String(status.active));
  hudTrack.setAttribute('aria-valuenow', String(status.drawn));
  const empty = status.active === 0;
  startBtn.disabled = empty || state.busy;
  resetBtn.disabled = empty || state.busy;
  if (empty) {
    showToast('名单为空，点击右侧齿轮添加名字', 4000);
  }
}

/** 静止时展示的假名池。 */
function idlePool() {
  const names = state.status && state.status.names.length ? state.status.names : IDLE_DECOY_POOL;
  return names;
}

function paintIdle() {
  const pool = idlePool();
  reel.kick(pool, { id: 0, name: pool[0], weight: 1 });
  state.idle = true;
}

async function refreshStatus({ force = false } = {}) {
  if (state.busy) return;
  const status = await unwrap(window.pywebview.api.status());
  renderStatus(status);
  if (status.roster_version !== state.rosterVersion || force) {
    const changed = state.rosterVersion !== -1;
    state.rosterVersion = status.roster_version;
    if (state.idle || changed) paintIdle();
  }
}

async function doDraw() {
  if (state.busy) return;
  state.busy = true;
  startBtn.disabled = true;
  resetBtn.disabled = true;
  try {
    const result = await unwrap(window.pywebview.api.draw());
    state.idle = false;
    await reel.spin(result.decoys, { id: result.id, name: result.name, weight: result.weight }, SPIN_MS);
    if (result.auto_reset) {
      showToast(`本轮已抽完，已自动进入第 ${result.cycle} 轮`);
    }
    state.busy = false;
    await refreshStatus();
  } catch (error) {
    state.busy = false;
    if (error instanceof ApiFailure && error.code === 'EMPTY_ROSTER') {
      showToast(error.message, 4000, true);
    } else {
      showToast(`出错了：${error instanceof Error ? error.message : String(error)}`, 4000, true);
    }
    await refreshStatus({ force: true }).catch(() => {});
  }
}

async function doReset() {
  if (state.busy) return;
  state.busy = true;
  startBtn.disabled = true;
  resetBtn.disabled = true;
  try {
    const status = await unwrap(window.pywebview.api.reset());
    state.busy = false;
    state.idle = true;
    renderStatus(status);
    state.rosterVersion = status.roster_version;
    paintIdle();
    showToast('已重新开始一轮（累计次数保持不变）');
  } catch (error) {
    state.busy = false;
    showToast(`出错了：${error instanceof Error ? error.message : String(error)}`, 4000, true);
    await refreshStatus({ force: true }).catch(() => {});
  }
}

async function doOpenManage() {
  try {
    await unwrap(window.pywebview.api.open_manage());
  } catch (error) {
    showToast(`无法打开名单管理：${error instanceof Error ? error.message : String(error)}`, 4000, true);
  }
}

function bindEvents() {
  startBtn.addEventListener('click', () => { void doDraw(); });
  resetBtn.addEventListener('click', () => { void doReset(); });
  manageBtn.addEventListener('click', () => { void doOpenManage(); });
  document.addEventListener('keydown', (event) => {
    if (event.repeat) return;
    if (event.code === 'Space' || event.code === 'Enter') {
      event.preventDefault();
      void doDraw();
    }
  });
  window.setInterval(() => {
    void refreshStatus().catch(() => {});
  }, POLL_MS);
}

async function boot() {
  bindEvents();
  try {
    await refreshStatus({ force: true });
  } catch (error) {
    showToast(`初始化失败：${error instanceof Error ? error.message : String(error)}`, 4000, true);
  }
}

// --auto 自测钩子（main.py --auto N 通过 evaluate_js 调用）
window.clickStart = () => { void doDraw(); };
window.__state = () => ({
  busy: state.busy,
  idle: state.idle,
  cycle: state.status ? state.status.cycle : null,
  remaining: state.status ? state.status.remaining : null,
  active: state.status ? state.status.active : null,
});

window.addEventListener('pywebviewready', () => { void boot(); });
