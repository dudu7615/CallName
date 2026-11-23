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

// 手动停模式：条带由「一个周期」重复多份组成，靠取模实现无缝循环。
// 周期越短，能停下的赢家位置越密，减速等待越短；这里 9 格一组最顺手。
const MANUAL_ABOVE = 6;
const MANUAL_BELOW = 2;
const MANUAL_PERIOD = MANUAL_ABOVE + 1 + MANUAL_BELOW;
const MANUAL_REPEATS = 5;
const MANUAL_CELL_MS = 34;      // 匀速阶段每格耗时
const STOP_SNAP_MS = 170;       // 点「停」后滑到下一个赢家格的时长：要“立刻停住”

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
    this._stopping = false;
    /** @type {HTMLElement[]} */
    this._winnerCells = [];
    /** @type {(() => void) | null} */
    this._stopResolve = null;
    /** @type {Promise<void> | null} */
    this._stopPromise = null;
    this._stopGen = 0;
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

  /* ---------- 手动停模式：持续旋转 + 减速停止 ---------- */

  /**
   * 开始持续旋转，赢家已由后端确定、但全程不点亮。
   * 周期条带重复 4 份，靠取模换行；停止时再挑最近的一个赢家格落脚。
   * @param {string[]} decoys 假名池
   * @param {Winner} winner 赢家
   * @returns {boolean} false = prefers-reduced-motion，已直接停稳点亮，调用方按普通模式收尾
   */
  startInfinite(decoys, winner) {
    this._cancelLoop();
    const pool = decoys.length ? decoys : [winner.name];
    const pattern = [
      ...this._pick(pool, MANUAL_ABOVE),
      winner.name,
      ...this._pick(pool, MANUAL_BELOW),
    ];
    const names = [];
    /** @type {HTMLElement[]} */
    const winnerCells = [];
    for (let repeat = 0; repeat < MANUAL_REPEATS; repeat += 1) {
      pattern.forEach((name, index) => {
        const cell = document.createElement('div');
        cell.className = 'cell';
        cell.textContent = name;
        if (index === MANUAL_ABOVE) winnerCells.push(cell);
        names.push(cell);
      });
    }
    const frag = document.createDocumentFragment();
    names.forEach((cell) => frag.appendChild(cell));
    this.strip.replaceChildren(frag);
    this._winnerCells = winnerCells;
    this.winnerEl = winnerCells[0] ?? null;

    if (this.reduced) {
      this.strip.style.transition = 'none';
      this.strip.style.transform = 'translate3d(0, 0, 0)';
      void this.strip.offsetHeight;
      this._settleCell(this.winnerEl);
      this.reveal();
      return false;
    }

    const h = names[0].getBoundingClientRect().height;
    this._cellH = h;
    this._periodPx = MANUAL_PERIOD * h;
    this._speed = h / MANUAL_CELL_MS;
    this._offset = 0;
    this._lastTs = 0;
    this.strip.style.transition = 'none';
    this.strip.style.transform = 'translate3d(0, 0, 0)';
    void this.strip.offsetHeight;

    this._spinning = true;
    this._lastTs = 0;
    this._raf = requestAnimationFrame((ts) => this._tick(ts));
    return true;
  }

  /**
   * 立即刹住，只滑到**下一个**赢家格（最多一个周期）。
   * 不做长减速：老师点「停」就是当下要结果，多转一秒都是干扰。
   */
  async stopInfinite() {
    // 已经在停就等它结束，别当成空操作（否则调用方的 await 会立刻返回）
    if (this._stopping) return this._stopPromise;
    if (!this._spinning || this._periodPx <= 0) return;
    this._stopping = true;
    const gen = ++this._stopGen;
    const offset = this._offset;
    const h = this._cellH;
    const H = this.clip.clientHeight;
    const period = this._periodPx;

    // 第 m 个赢家格：目标偏移 = 格顶对齐高亮带中心所需位移 + m 个周期。
    // cellTop = index*h - offset，令 cellTop + h/2 = H/2。
    const base = MANUAL_ABOVE * h + h / 2 - H / 2;
    // 取当前偏移之后最近的那一个赢家格；正好停在格上时再前进一格，
    // 保证「点停」总有一次可见的位移，而不是像卡住。
    let target = base + Math.ceil((offset - base) / period) * period;
    if (target - offset < h * 0.5) target += period;

    const distance = target - offset;
    const index = Math.round((target - base) / period);
    const winnerEl = this._winnerCells[index] ?? this.winnerEl;

    // 立刻停掉匀速循环
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = 0;

    this._stopPromise = new Promise((resolve) => {
      this._stopResolve = resolve;
      const start = performance.now();
      const step = (now) => {
        const progress = Math.min((now - start) / STOP_SNAP_MS, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        this.strip.style.transform = `translate3d(0, ${-(offset + distance * eased)}px, 0)`;
        if (progress < 1) {
          this._raf = requestAnimationFrame(step);
          return;
        }
        this._raf = 0;
        this._stopResolve = null;
        resolve();
      };
      this._raf = requestAnimationFrame(step);
    });
    await this._stopPromise;

    // 停止途中被 kick()/startInfinite() 打断时，别用旧目标去 settle 新条带
    if (gen !== this._stopGen) return;
    this._stopPromise = null;

    this._offset = target % period;
    this.winnerEl = winnerEl ?? null;
    this._settleCell(this.winnerEl);
    this._spinning = false;
    this._stopping = false;
    this.reveal();
  }

  /** @private 匀速阶段：每帧推进 offset，取模换行（内容周期重复所以无缝）。 */
  _tick(ts) {
    if (!this._spinning || this._stopping) return;
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
    this._stopping = false;
    this._stopGen += 1;   // 让仍在等待的 stopInfinite 知道自己被作废了
    this._resumeStop();
  }

  /** @private 外部打断减速时，别让 stopInfinite 的 Promise 永远挂着。 */
  _resumeStop() {
    const resolve = this._stopResolve;
    this._stopResolve = null;
    if (resolve) resolve();
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
