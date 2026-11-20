/* ============================================================
 * yimu-net.js — 一幕·YIMU 爆款工作室 前端网络/轮询公共工具
 *
 * 为什么单独抽这个文件：index.html 主脚本已超过 1.4 万行内联 JS，
 * 全站 500+ 处 api() 调用与 20+ 处手写 while(true) 任务轮询各自为政，
 * 超时、取消、页面隐藏节流这类横切逻辑无法统一治理。
 * 本文件只放纯 JS 工具（无 DOM 依赖、无初始化副作用），
 * 必须在 index.html 主脚本之前引入，供内联 onkeydown / 主脚本随时调用。
 * ============================================================ */
(function(global) {
  'use strict';

  /**
   * 中文输入法守卫：Enter 键提交前必须过这道闸。
   * 为什么：拼音/五笔等 IME 组词过程中按 Enter 是「确认候选词」，
   * keydown 事件里 e.isComposing === true（旧内核用 keyCode 229），
   * 直接当成「发送」会把半截拼音发出去（经典误发送 bug）。
   * @param {KeyboardEvent} e
   * @returns {boolean} true = 不是输入法组词回车，可以安全提交
   */
  function imeSafeEnter(e) {
    if (!e) return false;
    return !(e.isComposing || e.keyCode === 229);
  }
  global.imeSafeEnter = imeSafeEnter;

  /**
   * 任务终态判定：唯一真源，轮询的 `done` 标志一律由它算出。
   *
   * 为什么需要它（v15.9.9 实测事故）：后端任务状态的「成功」有 done 与
   * completed 两代写法——core.task_queue 落库并对外一律用 completed，
   * 而 web.admin.JOBS 历史条目与大量业务路由写的是 done。全站 40+ 处轮询
   * 各自写 `j.status === 'done'` 判断，只要一侧改了词，另一侧就永远等不到
   * 终态，一路轮询到 maxMs 超时才报「任务仍在后台执行」，用户看到的是
   * 「合成完成但界面不动」。这里把两代词汇收成一个集合，调用方不再关心
   * 具体拼写。
   *
   * @param {string} status 任务状态原值
   * @returns {boolean} true = 终态（完成/失败/取消/中断），轮询可以停
   */
  var TERMINAL_STATUSES = { completed: 1, done: 1, failed: 1, cancelled: 1, interrupted: 1 };

  function isTerminalStatus(status) {
    return !!TERMINAL_STATUSES[String(status == null ? '' : status).trim().toLowerCase()];
  }

  /**
   * 任务是否「成功完成」——终态里排除失败/取消/中断。
   * @param {string} status
   * @returns {boolean}
   */
  function isSuccessStatus(status) {
    var s = String(status == null ? '' : status).trim().toLowerCase();
    return s === 'completed' || s === 'done';
  }

  global.isTerminalStatus = isTerminalStatus;
  global.isSuccessStatus = isSuccessStatus;

  /**
   * 统一任务轮询器：收拢全站手写 while(true) 轮询。
   *
   * 约定：
   *  - fn 由调用方提供（内部调 api() 查任务状态），返回 { done: boolean, data: any }。
   *    done 表示任务到达终态（完成/失败/取消都算终态），data 原样透传给回调。
   *  - 网络异常/临时错误：连续 tolerate 次以内自动重试不判失败（后端重启、
   *    弱网抖动不该把一个还在跑的后台任务判死）；超过 tolerate 才走 onFail。
   *  - 总时长 maxMs 上限：到点后走 onFail，但错误文案是「任务仍在后台执行…」，
   *    绝不裸抛（轮询挂了不代表后台任务死了，用户仍可在草稿箱找到结果）。
   *  - 页面不可见（document.hidden）时拉长轮询间隔做节流，省请求省电。
   *  - 返回 { cancel() }：切草稿/切舞台/关抽屉时必须取消旧轮询，
   *    避免旧任务回调把新界面的按钮/列表改掉（状态串台）。
   *
   * @param {Object} opts
   * @param {Function} opts.fn          async () => ({ done, data })
   * @param {number}  [opts.intervalMs=1500]   基础轮询间隔
   * @param {number}  [opts.maxMs=600000]      总时长上限（默认 10 分钟）
   * @param {number}  [opts.tolerate=4]        连续容忍的临时错误次数
   * @param {Function} [opts.onStep]           每次轮询成功回调 (data)，用于刷新步骤文案
   * @param {Function} [opts.onDone]           终态回调 (data)
   * @param {Function} [opts.onFail]           失败/超时回调 (Error)，message 为中文
   * @param {Function} [opts.onCancel]         被 cancel() 打断时回调（不传 onFail，
   *                                            取消是用户切换页面等主动行为，不该报错）
   * @returns {{ cancel: Function }}
   */
  // 存活轮询注册表：切草稿/切页面/关抽屉时统一取消旧轮询，
  // 防止旧任务的 onDone 回调改写新界面（按钮文案/列表/草稿选择串台）。
  // 终态（done/fail/cancel）都会从表里摘除，注册表只反映「真正还活着」的轮询。
  const _livePolls = new Set();

  function pollJob(opts) {
    const o = opts || {};
    const fn = o.fn;
    const intervalMs = typeof o.intervalMs === 'number' && o.intervalMs > 0 ? o.intervalMs : 1500;
    const maxMs = typeof o.maxMs === 'number' && o.maxMs > 0 ? o.maxMs : 600000;
    const tolerate = typeof o.tolerate === 'number' && o.tolerate >= 0 ? o.tolerate : 4;
    const onStep = typeof o.onStep === 'function' ? o.onStep : null;
    const onDone = typeof o.onDone === 'function' ? o.onDone : null;
    const onFail = typeof o.onFail === 'function' ? o.onFail : null;
    const onCancel = typeof o.onCancel === 'function' ? o.onCancel : null;

    const startedAt = Date.now();
    let cancelled = false;
    let settled = false;
    let failStreak = 0;
    let timer = null;
    let handle = null; // 在文件末尾赋值；tick 首轮经 setTimeout 异步触发，届时必已赋值

    function unregister() {
      if (handle) _livePolls.delete(handle);
    }

    function clearTimer() {
      if (timer !== null) { clearTimeout(timer); timer = null; }
    }

    function settleFail(err) {
      if (settled || cancelled) return;
      settled = true;
      clearTimer();
      unregister();
      if (onFail) onFail(err instanceof Error ? err : new Error(String(err || '任务轮询失败')));
    }

    function scheduleNext() {
      if (cancelled || settled) return;
      // 页面不可见时降频节流：后台任务不着急刷，把间隔放大 3 倍且至少 4.5s
      let iv = intervalMs;
      if (global.document && document.hidden) iv = Math.max(intervalMs * 3, 4500);
      timer = setTimeout(tick, iv);
    }

    async function tick() {
      if (cancelled || settled) return;
      if (Date.now() - startedAt >= maxMs) {
        // 超时不裸抛：轮询有上限，但后台任务可能仍在跑，引导用户去草稿箱查看
        settleFail(new Error('任务仍在后台执行，可稍后在草稿箱查看结果'));
        return;
      }
      let r;
      try {
        r = await fn();
        failStreak = 0; // 本次成功，重置临时错误计数
      } catch (e) {
        failStreak += 1;
        if (failStreak <= tolerate) { scheduleNext(); return; }
        settleFail(e);
        return;
      }
      if (cancelled || settled) return;
      const data = (r && r.data !== undefined) ? r.data : r;
      const done = Boolean(r && r.done);
      if (done) {
        settled = true;
        clearTimer();
        unregister();
        if (onDone) onDone(data);
        return;
      }
      if (onStep) { try { onStep(data); } catch (_e) { /* 步骤回调异常不影响轮询本身 */ } }
      scheduleNext();
    }

    // 首轮立即探一次（调用方通常刚提交任务，等满一个间隔反而拖慢首反馈）
    timer = setTimeout(tick, 0);

    handle = {
      cancel: function() {
        if (settled) return;
        cancelled = true;
        clearTimer();
        unregister();
        if (onCancel) onCancel();
      }
    };
    _livePolls.add(handle);
    return handle;
  }

  /**
   * pollJob 的 Promise 版：await 等到终态（完成/失败/超时/被取消）才继续往下走。
   * 为什么需要它：全站改造点都是「提交任务 → await 轮询 → finally 解锁按钮」的
   * 既有结构，直接用回调式 pollJob 会让 finally 提前执行、按钮秒解锁。
   * 返回 { ok, data?, error?, cancelled? }，绝不 reject（失败语义由 onFail 处理）。
   *
   * @param {Object} opts 与 pollJob 相同
   * @returns {Promise<{ok: boolean, data?: any, error?: Error, cancelled?: boolean}>}
   */
  function pollJobAsync(opts) {
    let resolveFn = null;
    const promise = new Promise(resolve => { resolveFn = resolve; });
    pollJob(Object.assign({}, opts, {
      onDone: function(d) {
        try { if (opts && typeof opts.onDone === 'function') opts.onDone(d); }
        finally { resolveFn({ ok: true, data: d }); }
      },
      onFail: function(e) {
        try { if (opts && typeof opts.onFail === 'function') opts.onFail(e); }
        finally { resolveFn({ ok: false, error: e }); }
      },
      onCancel: function() {
        resolveFn({ ok: false, cancelled: true });
      }
    }));
    return promise;
  }

  /**
   * 取消当前全部存活轮询。在 selectDraft（切草稿）与主导航切换入口调用。
   * @returns {number} 本次取消的轮询数量
   */
  function cancelAllPolls() {
    const n = _livePolls.size;
    Array.from(_livePolls).forEach(p => p.cancel());
    _livePolls.clear();
    return n;
  }
  global.cancelAllPolls = cancelAllPolls;
  global.pollJobAsync = pollJobAsync;
  global.pollJob = pollJob;
})(window);
