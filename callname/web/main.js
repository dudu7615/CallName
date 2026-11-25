/**
 * 主窗口逻辑：按钮、HUD、⚙、状态轮询，以及 --auto 自测入口。
 *
 * 与 Python 的契约见 callname/schemas.py：
 *   status() -> ApiResponse<StatusResult>
 *   draw()   -> ApiResponse<DrawResult>
 *   reset()  -> ApiResponse<StatusResult>
 *   open_manage() -> ApiResponse<LaunchResult>
 *   get_settings() -> ApiResponse<SettingsResult>
 *   set_draw_mode(mode) -> ApiResponse<SettingsResult>
 *   set_sound_enabled(enabled) -> ApiResponse<SettingsResult>
 */

import { Reel } from './reel.js';
import { Sfx } from './sfx.js';

const SPIN_MS = 3000;
const POLL_MS = 1500;
const IDLE_DECOY_POOL = ['点名', '准备开始', '点击开始'];

/**
 * @typedef {{ status: any, busy: boolean, rosterVersion: number, idle: boolean,
 *             manual: boolean, spinning: boolean, starting: boolean }} State
 */

/** @type {State} */
const state = {
  status: null,
  busy: false,
  rosterVersion: -1,
  idle: true,
  manual: false,
  spinning: false,
  starting: false,
};

const sfx = new Sfx();

/** --auto 自测用：回调次数与真正发声次数分开计数。
 *  两者之差就是 Sfx 的节流效果，无手势时前者有值、后者为 0。 */
let tickTotal = 0;
let finishTotal = 0;
let tickPlayed = 0;
let finishPlayed = 0;

const reel = new Reel(
  /** @type {HTMLElement} */ (document.getElementById('clip')),
  /** @type {HTMLElement} */ (document.getElementById('strip')),
  {
    onTick: () => { tickTotal += 1; if (sfx.tick()) tickPlayed += 1; },
    onFinish: () => { finishTotal += 1; if (sfx.finish()) finishPlayed += 1; },
  },
);

const startBtn = /** @type {HTMLButtonElement} */ (document.getElementById('start'));
const startLabel = /** @type {HTMLElement} */ (document.getElementById('start-label'));
const modeBtn = /** @type {HTMLButtonElement} */ (document.getElementById('mode'));
const soundBtn = /** @type {HTMLButtonElement} */ (document.getElementById('sound'));
const soundOnIcon = /** @type {SVGElement} */ (document.getElementById('sound-on'));
const soundOffIcon = /** @type {SVGElement} */ (document.getElementById('sound-off'));
const resetBtn = /** @type {HTMLButtonElement} */ (document.getElementById('reset'));
const manageBtn = /** @type {HTMLButtonElement} */ (document.getElementById('manage'));
const hudCycle = /** @type {HTMLElement} */ (document.getElementById('hud-cycle'));
const hudRemaining = /** @type {HTMLElement} */ (document.getElementById('hud-remaining'));
const hudDrawn = /** @type {HTMLElement} */ (document.getElementById('hud-drawn'));
const hudFill = /** @type {HTMLElement} */ (document.getElementById('hud-fill'));
const hudTrack = /** @type {HTMLElement} */ (document.getElementById('hud-track'));
const toast = /** @type {HTMLElement} */ (document.getElementById('toast'));

let toastTimer = 0;
/** 手动停模式下「抽完自动进下一轮」的提示延后到停稳再弹，避免干扰转动。 */
/** @type {number | null} */
let pendingAutoReset = null;

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
 * 主按钮的文案与禁用状态都从这里出：手动停模式下它同时是「开始」和「停」。
 * 旋转期间不能禁用「停」，否则第二个点击落空。
 */
function syncButton() {
  // 手动停模式下只要名单非空就保持可点：旋转中必须先能点「停」，
  // 名单被管理窗口清空时也要能停住转盘。
  const empty = state.status ? state.status.active === 0 : false;
  const stopLabel = state.manual && (state.spinning || state.starting);
  startLabel.textContent = stopLabel ? '停' : state.manual ? '开始' : '开始点名';
  startBtn.classList.toggle('is-stop', stopLabel);
  // starting 期间按钮短暂禁用：draw() 还没回来，此时点「停」没有可停的动画
  startBtn.disabled = state.busy || state.starting
    || (empty && !(state.manual && state.spinning));
  resetBtn.disabled = state.busy || state.spinning || state.starting || empty;
  modeBtn.disabled = state.busy || state.spinning || state.starting;
  syncSoundButton();
}

/** 音效按钮的图标与按下态；静音时换成带斜杠的喇叭。 */
function syncSoundButton() {
  const on = sfx.enabled;
  soundBtn.setAttribute('aria-pressed', String(on));
  soundBtn.title = on ? '音效：开（点击静音）' : '音效：关（点击开启）';
  soundBtn.classList.toggle('is-off', !on);
  soundOnIcon.style.display = on ? '' : 'none';
  soundOffIcon.style.display = on ? 'none' : '';
}

/** 切换模式开关的视觉与状态；调用方负责持久化。 */
function applyMode(manual) {
  state.manual = manual;
  // 标签固定写设置名，开/关只看 aria-pressed 的点亮位置
  modeBtn.setAttribute('aria-pressed', String(manual));
  syncButton();
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
  syncButton();
  if (status.active === 0) {
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

async function refreshStatus({ force = false, keepResult = false } = {}) {
  if (state.busy) return;
  const status = await unwrap(window.pywebview.api.status());
  renderStatus(status);
  if (status.roster_version !== state.rosterVersion || force) {
    const changed = state.rosterVersion !== -1;
    state.rosterVersion = status.roster_version;
    // 旋转中绝不能重画条带：paintIdle 会换内容并打断 rAF。
    // keepResult 用于「刚抽出结果」的刷新，别把刚点亮的赢家抹回待机画面。
    if (!keepResult && !state.spinning && !state.starting
        && (state.idle || changed)) {
      paintIdle();
    }
  }
}

/** 自动停模式：点一次 → 抽签 + 定长动画。 */
async function doDraw() {
  if (state.busy) return;
  state.busy = true;
  syncButton();
  let settled = false;
  try {
    const result = await unwrap(window.pywebview.api.draw());
    state.idle = false;
    await reel.spin(result.decoys, { id: result.id, name: result.name, weight: result.weight }, SPIN_MS);
    settled = true;
    if (result.auto_reset) {
      showToast(`本轮已抽完，已自动进入第 ${result.cycle} 轮`);
    }
    state.busy = false;
    syncButton();
    await refreshStatus({ keepResult: true });
  } catch (error) {
    state.busy = false;
    syncButton();
    if (error instanceof ApiFailure && error.code === 'EMPTY_ROSTER') {
      showToast(error.message, 4000, true);
    } else if (settled) {
      // 抽签本身成功了，只是收尾的状态刷新失败：别把已经点亮的名字抹掉
      showToast(`状态刷新失败：${error instanceof Error ? error.message : String(error)}`, 4000, true);
    } else {
      showToast(`出错了：${error instanceof Error ? error.message : String(error)}`, 4000, true);
    }
    await refreshStatus({ force: true, keepResult: true }).catch(() => {});
  }
}

/** 手动停模式第一步：抽签（先落库）并开始持续旋转。 */
async function startManual() {
  if (state.starting || state.spinning) return;
  state.starting = true;   // 同步置位，防双击；busy 保持 false，轮询继续
  pendingAutoReset = null;
  syncButton();
  try {
    const result = await unwrap(window.pywebview.api.draw());
    state.idle = false;
    if (result.auto_reset) pendingAutoReset = result.cycle;
    const animated = reel.startInfinite(
      result.decoys,
      { id: result.id, name: result.name, weight: result.weight },
    );
    if (!animated) {
      // prefers-reduced-motion：直接停稳，按自动模式收尾
      state.starting = false;
      showPendingAutoReset();
      syncButton();
      await refreshStatus({ force: true, keepResult: true });
      return;
    }
    state.starting = false;
    state.spinning = true;
    syncButton();
    await refreshStatus({ force: true, keepResult: true }).catch(() => {});   // 立刻刷新 HUD
  } catch (error) {
    state.starting = false;
    state.spinning = false;
    pendingAutoReset = null;
    syncButton();
    if (error instanceof ApiFailure && error.code === 'EMPTY_ROSTER') {
      showToast(error.message, 4000, true);
    } else {
      showToast(`出错了：${error instanceof Error ? error.message : String(error)}`, 4000, true);
    }
    await refreshStatus({ force: true }).catch(() => {});
  }
}

/** 手动停模式第二步：立即落到下一格并点亮结果（无补间动画）。 */
async function stopManual() {
  if (!state.spinning || state.starting) return;
  // 同步落位：reel.stopInfinite 内部取消 rAF 并一次性摆好，不 await 任何动画
  reel.stopInfinite();
  state.spinning = false;
  showPendingAutoReset();
  syncButton();
  await refreshStatus({ force: true, keepResult: true }).catch(() => {});
}

/** 手动停模式下「本轮已抽完」的提示延后到停稳再弹，免得干扰转动。 */
function showPendingAutoReset() {
  if (pendingAutoReset === null) return;
  showToast(`本轮已抽完，已自动进入第 ${pendingAutoReset} 轮`);
  pendingAutoReset = null;
}

/** 主按钮（以及空格/回车）的唯一入口，按模式分流。 */
async function doPrimary() {
  // AudioContext 必须在用户手势的同步调用栈里解锁；等 await draw() 回来就晚了
  void sfx.unlock();
  const action = nextAction();
  if (action === 'start') await startManual();
  else if (action === 'stop') await stopManual();
  else if (action === 'draw') await doDraw();
}

/** @returns {'draw' | 'start' | 'stop' | null} */
function nextAction() {
  if (state.busy || state.starting) return null;
  if (!state.manual) return 'draw';
  return state.spinning ? 'stop' : 'start';
}

async function doReset() {
  if (state.busy || state.spinning || state.starting) return;
  state.busy = true;
  syncButton();
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
    syncButton();
    showToast(`出错了：${error instanceof Error ? error.message : String(error)}`, 4000, true);
    await refreshStatus({ force: true }).catch(() => {});
  }
}

async function doToggleMode() {
  if (state.busy || state.spinning || state.starting) return;
  const next = !state.manual;
  applyMode(next);   // 乐观切换
  try {
    await unwrap(window.pywebview.api.set_draw_mode(next ? 'manual' : 'auto'));
  } catch (error) {
    applyMode(!next);
    showToast(`无法保存模式设置：${error instanceof Error ? error.message : String(error)}`, 4000, true);
  }
}

async function doToggleSound() {
  const next = !sfx.enabled;
  sfx.setEnabled(next);   // 乐观切换
  syncSoundButton();
  try {
    await unwrap(window.pywebview.api.set_sound_enabled(next));
  } catch (error) {
    sfx.setEnabled(!next);
    syncSoundButton();
    showToast(`无法保存音效设置：${error instanceof Error ? error.message : String(error)}`, 4000, true);
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
  startBtn.addEventListener('click', () => { void doPrimary(); });
  modeBtn.addEventListener('click', () => { void doToggleMode(); });
  soundBtn.addEventListener('click', () => { void doToggleSound(); });
  resetBtn.addEventListener('click', () => { void doReset(); });
  manageBtn.addEventListener('click', () => { void doOpenManage(); });
  document.addEventListener('keydown', (event) => {
    if (event.repeat) return;
    if (event.code === 'Space' || event.code === 'Enter') {
      event.preventDefault();
      void doPrimary();
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
  try {
    const settings = await unwrap(window.pywebview.api.get_settings());
    applyMode(settings.draw_mode === 'manual');
    sfx.setEnabled(settings.sound_enabled !== false);
    syncSoundButton();
  } catch (error) {
    applyMode(false);
    showToast(`读取设置失败：${error instanceof Error ? error.message : String(error)}`, 4000, true);
  }
}

// --auto 自测钩子（main.py --auto N 通过 evaluate_js 调用）
window.clickStart = () => { void doPrimary(); };
window.clickStop = () => {
  if (state.manual && state.spinning) void stopManual();
};window.__state = () => ({
  busy: state.busy,
  idle: state.idle,
  manual: state.manual,
  starting: state.starting,
  spinning: state.spinning,
  sound: sfx.enabled,
  sound_ready: sfx.ready,
  sound_error: sfx.failed,
  ticks: tickTotal,
  finishes: finishTotal,
  ticks_played: tickPlayed,
  finishes_played: finishPlayed,
  cycle: state.status ? state.status.cycle : null,
  remaining: state.status ? state.status.remaining : null,
  active: state.status ? state.status.active : null,
});

window.addEventListener('pywebviewready', () => { void boot(); });
