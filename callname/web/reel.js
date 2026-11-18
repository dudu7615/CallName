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
    this.reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  /** 用名字数组构建条带，winIndex 位置是赢家。 */
  build(names, winIndex) {
    const frag = document.createDocumentFragment();
    names.forEach((name, index) => {
      const cell = document.createElement('div');
      cell.className = index === winIndex ? 'cell win' : 'cell';
      cell.textContent = name;
      frag.appendChild(cell);
    });
    this.strip.replaceChildren(frag);
  }

  /** 静止时（无动画）把赢家格摆到高亮带中心。 */
  settle() {
    const winner = this.strip.querySelector('.cell.win');
    if (!winner) return;
    this.strip.style.transition = 'none';
    this.strip.style.transform = `translate3d(0, ${this._restY(winner)}, 0)`;
    // 强制 reflow，确保后续过渡从当前位置开始
    void this.strip.offsetHeight;
  }

  /**
   * 播放抽签动画。
   * @param {string[]} decoys 假名池
   * @param {Winner} winner 赢家
   * @param {number} duration 动画时长 ms
   * @returns {Promise<void>} 动画结束（含兜底超时）
   */
  async spin(decoys, winner, duration) {
    const above = this._pick(decoys, ABOVE);
    const below = this._pick(decoys, BELOW);
    const winIndex = above.length;
    this.build([...above, winner.name, ...below], winIndex);

    const winnerEl = this.strip.querySelector('.cell.win');
    if (!winnerEl) return;

    if (this.reduced) {
      this.settle();
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

    winnerEl.classList.add('pop');
    window.setTimeout(() => winnerEl.classList.remove('pop'), 460);
  }

  /** 下一次抽签前的“跳变”：换内容并瞬间归位，用户看不到中间静止帧。 */
  kick(decoys, winner) {
    const above = this._pick(decoys, ABOVE);
    const below = this._pick(decoys, BELOW);
    this.build([...above, winner.name, ...below], above.length);
    this.settle();
    this.clip.classList.add('is-kicking');
    window.setTimeout(() => this.clip.classList.remove('is-kicking'), 140);
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
