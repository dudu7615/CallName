/**
 * 滚轮引擎：条带自下而上滚动，赢家停在正中高亮带。
 *
 * 所有几何量都从 getBoundingClientRect() 测量得到，不写死像素，
 * 否则 125% DPI 或窗口缩放时赢家会偏离高亮带中心。
 *
 * 层级（style.css 里固定）：.band(z0) -> .strip(z1) -> .fade(z3)。
 */

const ABOVE = 26;   // 赢家上方假名数量
const BELOW = 5;    // 赢家下方假名数量，保证静止时下半格不露白

// 手动停模式：条带是一段假名周期重复多份，靠取模实现无缝循环。
// 点「停」时只前进到最近的下一格（≤1 格），所以周期长度只要够覆盖
// 「当前偏移 + 一个视口」即可。
const MANUAL_PATTERN = 24;      // 一个周期的格数
const MANUAL_REPEATS = 4;       // 周期重复份数，要覆盖停止时可能落到的下标
const MANUAL_CELL_MS = 26;      // 匀速阶段每格耗时

/** @typedef {{ id: number, name: string, weight: number }} Winner */

export class Reel {
  /**
   * @param {HTMLElement} clip  .clip 容器
   * @param {HTMLElement} strip .strip 条带
   */
  constructor(clip, strip) {
    this.clip = clip;
    this.strip = strip;
    this.timer = null;
    /** @type {HTMLElement | null} */
    this.winnerEl = null;
    this.reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // 手动停模式的 rAF 循环状态
    /** @type {number} */
    this._raf = 0;
    this._offset = 0;
    this._lastTs = 0;
    this._periodPx = 0;
    this._speed = 0;
    this._cellH = 0;
    this._spinning = false;
    /** @type {string | null} 手动停模式下待揭晓的赢家名字 */
    this._pendingWinner = null;
  }

  /** 用名字数组构建条带，winIndex 位置是赢家（先不加高亮，由 reveal() 揭开）。 */
  build(names, winIndex) {
    const frag = document.createDocumentFragment();
    let winner = /** @type {HTMLElement | null} */ (null);
    names.forEach((name, index) => {
      const cell = document.createElement('div');
      cell.className = 'cell';
      cell.textContent = name;
      if (index === winIndex) winner = cell;
      frag.appendChild(cell);
    });
    this.strip.replaceChildren(frag);
    this.winnerEl = winner;
  }

  /** 给赢家格加金色高亮。滚动过程中不调用，避免提前泄露结果。 */
  reveal({ pop = true } = {}) {
    if (!this.winnerEl) return;
    this.winnerEl.classList.add('win');
    if (!pop) return;
    this.winnerEl.classList.add('pop');
    window.setTimeout(() => {
      if (this.winnerEl) this.winnerEl.classList.remove('pop');
    }, 740);
  }

  /** 静止时（无动画）把赢家格摆到高亮带中心。 */
  settle() {
    const winner = this.winnerEl;
    if (!winner) return;
    this.strip.style.transition = 'none';
    this.strip.style.transform = `translate3d(0, ${this._restY(winner)}, 0)`;
    // 强制 reflow，确保后续过渡从当前位置开始
    void this.strip.offsetHeight;
  }

  /**
   * 播放抽签动画。赢家全程不加高亮，停稳后才由 reveal() 点亮。
   * @param {string[]} decoys 假名池
   * @param {Winner} winner 赢家
   * @param {number} duration 动画时长 ms
   * @returns {Promise<void>} 动画结束（含兜底超时）
   */
  async spin(decoys, winner, duration) {
    this._cancelLoop();
    const above = this._pick(decoys, ABOVE);
    const below = this._pick(decoys, BELOW);
    const winIndex = above.length;
    this.build([...above, winner.name, ...below], winIndex);

    const winnerEl = this.winnerEl;
    if (!winnerEl) return;

    if (this.reduced) {
      this.settle();
      this.reveal();
      return;
    }

    const h = winnerEl.getBoundingClientRect().height;
    const H = this.clip.clientHeight;
    const restY = this._restY(winnerEl, h, H);

    // 起点在下方：一段可观的位移，让“自下而上”明确可读
    const startY = restY + H * 0.6 + h * 8;
    this.clip.classList.remove('is-kicking');
    this.strip.style.transition = 'none';
    this.strip.style.transform = `translate3d(0, ${startY}px, 0)`;
    void this.strip.offsetHeight;

    await new Promise((resolve) => {
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        this.strip.removeEventListener('transitionend', onEnd);
        window.clearTimeout(this.timer);
        resolve();
      };
      const onEnd = (event) => {
        if (event.target === this.strip && event.propertyName === 'transform') finish();
      };
      this.strip.addEventListener('transitionend', onEnd);
      // 窗口被遮挡时 QtWebEngine 可能丢 transitionend
      this.timer = window.setTimeout(finish, duration + 400);

      this.strip.style.transition = `transform ${duration}ms cubic-bezier(.08,.82,.06,1)`;
      this.strip.style.transform = `translate3d(0, ${restY}px, 0)`;
    });

    // 停稳之后才点亮赢家，滚动过程中不泄露结果
    this.reveal();
  }

  /** 下一次抽签前的“跳变”：换内容并瞬间归位，用户看不到中间静止帧。 */
  kick(decoys, winner) {
    this._cancelLoop();
    const above = this._pick(decoys, ABOVE);
    const below = this._pick(decoys, BELOW);
    this.build([...above, winner.name, ...below], above.length);
    this.settle();
    this.reveal({ pop: false });
    this.clip.classList.add('is-kicking');
    window.setTimeout(() => this.clip.classList.remove('is-kicking'), 140);
  }

  /* ---------- 手动停模式：持续旋转 + 立即停格 ---------- */

  /**
   * 开始持续旋转。条带全部是假名，赢家名字只在点「停」的那一刻写进落点格，
   * 所以转动过程中不会提前泄露结果。
   * @param {string[]} decoys 假名池
   * @param {Winner} winner 赢家
   * @returns {boolean} false = prefers-reduced-motion，已直接停稳点亮，调用方按普通模式收尾
   */
  startInfinite(decoys, winner) {
    this._cancelLoop();
    const pool = decoys.length ? decoys : [winner.name];
    const total = MANUAL_PATTERN * MANUAL_REPEATS;
    const frag = document.createDocumentFragment();
    for (let index = 0; index < total; index += 1) {
      const cell = document.createElement('div');
      cell.className = 'cell';
      cell.textContent = pool[index % pool.length];
      frag.appendChild(cell);
    }
    this.strip.replaceChildren(frag);
    this._pendingWinner = winner.name;
    this.winnerEl = null;
    this._offset = 0;
    this.strip.style.transition = 'none';
    this.strip.style.transform = 'translate3d(0, 0, 0)';
    void this.strip.offsetHeight;

    // 必须从 strip 里取：replaceChildren 之后 fragment 已被清空
    const first = this.strip.firstElementChild;
    const h = first instanceof HTMLElement ? first.getBoundingClientRect().height : 0;
    this._cellH = h;
    this._periodPx = MANUAL_PATTERN * h;

    if (this.reduced || h <= 0) {
      this._landNext();
      return false;
    }

    this._speed = h / MANUAL_CELL_MS;
    this._spinning = true;
    this._lastTs = 0;
    this._raf = requestAnimationFrame((ts) => this._tick(ts));
    return true;
  }

  /**
   * 立即停：不插播任何补间动画，直接落到当前偏移之后的最近一格并点亮结果。
   * 「最近的一格」= 下一个格中心与高亮带中心对齐的位置，最多前进不到一格。
   */
  stopInfinite() {
    if (!this._spinning) return;
    this._landNext();
  }

  /** @private 立刻停到下一格，把赢家名字写进那一格并点亮。 */
  _landNext() {
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = 0;
    this._spinning = false;

    const h = this._cellH;
    const H = this.clip.clientHeight;
    const cells = /** @type {HTMLElement[]} */ ([...this.strip.children]);
    if (!h || cells.length === 0) return;

    // 格 i 居中时需要的偏移 = i*h + h/2 - H/2；取比当前偏移大的最小 i。
    const phase = h / 2 - H / 2;
    const raw = Math.floor((this._offset - phase) / h) + 1;
    const index = Math.max(0, Math.min(raw, cells.length - 1));

    const cell = cells[index];
    if (this._pendingWinner !== null) cell.textContent = this._pendingWinner;
    this.winnerEl = cell;
    this._settleCell(cell);
    this.reveal();
  }

  /** @private 匀速阶段：每帧推进 offset，取模换行（内容周期重复所以无缝）。 */
  _tick(ts) {
    if (!this._spinning) return;
    // 窗口被遮挡时浏览器会把 rAF 降到 1Hz，夹住 dt 防止一帧跳过好几格
    const dt = this._lastTs ? Math.min(ts - this._lastTs, 64) : 16;
    this._lastTs = ts;
    this._offset = (this._offset + this._speed * dt) % this._periodPx;
    this.strip.style.transform = `translate3d(0, ${-this._offset}px, 0)`;
    this._raf = requestAnimationFrame((next) => this._tick(next));
  }

  /** @private 把指定格瞬间摆到高亮带中心（不减高亮，交给 reveal）。 */
  _settleCell(cell) {
    if (!cell) return;
    this.strip.style.transition = 'none';
    this.strip.style.transform = `translate3d(0, ${this._restY(cell)}px, 0)`;
    void this.strip.offsetHeight;
  }

  /** @private 取消 rAF 与待执行的 transition 兜底定时器。 */
  _cancelLoop() {
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = 0;
    window.clearTimeout(this.timer);
    this.timer = null;
    this._spinning = false;
  }

  /** @private */
  _pick(pool, count) {
    const list = [];
    for (let index = 0; index < count; index += 1) {
      list.push(pool[index % pool.length]);
    }
    return list;
  }

  /** @private 赢家格相对条带顶部的负偏移。 */
  _restY(winnerEl, h, H) {
    const height = h ?? winnerEl.getBoundingClientRect().height;
    const clipHeight = H ?? this.clip.clientHeight;
    const index = [...this.strip.children].indexOf(winnerEl);
    return Math.round(clipHeight / 2 - height / 2 - index * height);
  }
}
