/**
 * 转盘音效：逐格 tick 与落格揭晓音。
 *
 * 用 Web Audio 而不是 HTMLAudioElement：tick 需要重叠播放、亚帧延迟，
 * 并且要按最小间隔节流；HTMLAudioElement 会把同一元素的多次 play()
 * 打断成一次，且往 DOM 里塞节点没有任何好处。
 *
 * 所有公开方法都可能被抽签流程同步调用，因此内部一律吞掉异常：
 * 解码失败、AudioContext 被自动播放策略挂起、音频设备消失，都只是
 * 「没声音」，绝不能让异常冒到抽签流程里。失败原因记在 `failed` 上，
 * 由 main.js 的 `__state()` 暴露给 --auto 自测，不往控制台刷日志。
 */

/** tick 的最小间隔（ms）：手动停模式 26ms 一格，抽稀到约 13 次/秒。 */
const MIN_TICK_GAP = 70;

/** finish 的最小间隔（ms）：连续快抽时不要让两个结束音叠在一起。 */
const MIN_FINISH_GAP = 250;

/** 主音量。课堂音响上 1.0 的确认音会刺耳，压到一半左右。 */
const MASTER_GAIN = 0.55;

/** resume() 的等待上限（ms）：被自动播放策略扣住时不要永远挂着。 */
const RESUME_TIMEOUT_MS = 400;

/** 解码连续失败几次后彻底放弃：确定性失败不值得每次抽签都重试一遍。 */
const MAX_FAILURES = 2;

/** 没拿到手势时的重试间隔（ms）：否则每次点击都会建一个被拒绝的 AudioContext。 */
const RETRY_COOLDOWN_MS = 1000;

export class Sfx {
  /**
   * @param {{ tickUrl?: string, finishUrl?: string }} [options]
   */
  constructor({ tickUrl = 'tick.ogg', finishUrl = 'finish.ogg' } = {}) {
    /** @type {string} */
    this._tickUrl = tickUrl;
    /** @type {string} */
    this._finishUrl = finishUrl;

    /** @type {AudioContext | null} */
    this._ctx = null;
    /** @type {GainNode | null} */
    this._master = null;
    /** @type {AudioBuffer | null} */
    this._tickBuffer = null;
    /** @type {AudioBuffer | null} */
    this._finishBuffer = null;
    /** @type {Promise<void> | null} 只解锁/解码一次，并发调用共用同一个承诺 */
    this._unlocking = null;
    /** @type {number} 解码失败的次数：到上限后不再重试，免得每次抽签都报错 */
    this._failures = 0;
    /** @type {number} 上次「没拿到手势」的时刻，用于冷却，避免每次都建 AudioContext */
    this._retryAt = 0;

    /** @type {boolean} */
    this.enabled = true;
    /** @type {string | null} 解锁/解码失败的原因，成功时为 null */
    this.failed = null;
    /** @type {number} */
    this._lastTick = 0;
    /** @type {number} */
    this._lastFinish = 0;
  }

  /** 设置是否播放；不影响已解码的 buffer，也不建 AudioContext。 */
  setEnabled(enabled) {
    this.enabled = Boolean(enabled);
  }

  /**
   * 在用户手势的同步调用链里解锁：创建/恢复 AudioContext 并预取两个音效。
   *
   * 只有一次真正解码；失败后静默。注意「被自动播放策略挡下」和「解码失败」
   * 要区别对待：前者可重试（--auto 的程序化点击就会走到这条路径，随后真实
   * 点击仍应有声），后者是确定性的，不再反复建 AudioContext。
   * @returns {Promise<void>}
   */
  async unlock() {
    if (this._unlocking) return this._unlocking;
    if (this._tickBuffer && this._finishBuffer) return;
    if (this._failures >= MAX_FAILURES) return;
    if (performance.now() < this._retryAt) return;
    this._unlocking = (async () => {
      let ctx = null;
      try {
        const Ctor = window.AudioContext
          || /** @type {any} */ (window).webkitAudioContext;
        if (!Ctor) return;
        ctx = new Ctor();
        this._ctx = ctx;
        // 自动播放策略下首次是 suspended，必须在手势栈里 resume。
        // 没有手势时 resume() 会一直挂着，所以给它设个上限，超时当作
        // 「这次不算数」，下次真实点击再试。
        if (ctx.state === 'suspended') {
          await Promise.race([
            ctx.resume(),
            new Promise((resolve) => { window.setTimeout(resolve, RESUME_TIMEOUT_MS); }),
          ]);
        }
        if (ctx.state !== 'running') {
          // --auto 的程序化点击会走到这里：不记失败，只冷却一下等真实手势
          this._ctx = null;
          this._retryAt = performance.now() + RETRY_COOLDOWN_MS;
          void ctx.close().catch(() => {});
          return;
        }
        const master = ctx.createGain();
        master.gain.value = MASTER_GAIN;
        master.connect(ctx.destination);
        this._master = master;

        const [tick, finish] = await Promise.all([
          this._load(ctx, this._tickUrl),
          this._load(ctx, this._finishUrl),
        ]);
        this._tickBuffer = tick;
        this._finishBuffer = finish;
        this.failed = null;
      } catch (error) {
        this._failures += 1;
        this._ctx = null;
        this._master = null;
        // 音效是锦上添花，失败时只记原因，不影响抽签
        this.failed = error instanceof Error ? error.message : String(error);
        if (ctx) void ctx.close().catch(() => {});
      } finally {
        this._unlocking = null;
      }
    })();
    return this._unlocking;
  }

  /** 两个音效都已解码完成，可以随时播放。 */
  get ready() {
    return this._tickBuffer !== null && this._finishBuffer !== null;
  }

  /**
   * 每跨一格调用一次；内部按 MIN_TICK_GAP 节流。
   * @returns {boolean} 是否真的发出了一声（自测与调试用）
   */
  tick() {
    if (!this._canPlay(this._tickBuffer)) return false;
    const now = performance.now();
    if (now - this._lastTick < MIN_TICK_GAP) return false;
    this._lastTick = now;
    // 速率与音量都轻微抖动：几十次完全相同的采样听起来像机械故障
    this._play(this._tickBuffer, { rate: 0.96 + Math.random() * 0.08, gain: 0.9 + Math.random() * 0.1 });
    return true;
  }

  /**
   * 停稳、赢家点亮时调用一次。
   * @returns {boolean} 是否真的发出了一声
   */
  finish() {
    if (!this._canPlay(this._finishBuffer)) return false;
    const now = performance.now();
    if (now - this._lastFinish < MIN_FINISH_GAP) return false;
    this._lastFinish = now;
    this._play(this._finishBuffer, { rate: 1, gain: 1 });
    return true;
  }

  /**
   * @param {AudioBuffer | null} buffer
   * @returns {boolean}
   */
  _canPlay(buffer) {
    return this.enabled && buffer !== null && this._ctx !== null && this._master !== null;
  }

  /**
   * 每次播放都新建 source node：AudioBufferSourceNode 是一次性的，
   * 复用同一个节点会静默无声。
   * @param {AudioBuffer} buffer
   * @param {{ rate: number, gain: number }} shape
   */
  _play(buffer, { rate, gain }) {
    const ctx = this._ctx;
    const master = this._master;
    if (!ctx || !master) return;
    try {
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.playbackRate.value = rate;
      if (gain === 1) {
        source.connect(master);
      } else {
        const envelope = ctx.createGain();
        envelope.gain.value = gain;
        source.connect(envelope);
        envelope.connect(master);
      }
      source.start();
    } catch (error) {
      this.failed = error instanceof Error ? error.message : String(error);
    }
  }

  /**
   * 取回并解码一个音效。用 fetch + arrayBuffer，而不是把 URL 直接交给
   * decodeAudioData：那条路径由浏览器内部发请求，绕开页面自己的缓存与错误处理。
   * @param {AudioContext} ctx
   * @param {string} url
   * @returns {Promise<AudioBuffer>}
   */
  async _load(ctx, url) {
    const response = await fetch(new URL(url, import.meta.url));
    if (!response.ok) throw new Error(`sfx ${url}: HTTP ${response.status}`);
    const data = await response.arrayBuffer();
    return ctx.decodeAudioData(data);
  }
}
