/* SPDX-License-Identifier: BUSL-1.1 */
/* ==========================================================================
   Harness 外壳 · core（A 外壳底座）
   --------------------------------------------------------------------------
   职责：window.HX 命名空间 / 全局状态 / 工作区路由 / 模块注册表 / 骨架挂载 /
         持久化 / 风格切换 / 全局工具与 API。
   边界：不改 index.html；中栏内容归 thread，右栏舞台归 stage，采集/设置归 D。
   非 body[data-shell="harness"] 下整模块零副作用退出。
   ========================================================================== */
(function () {
  'use strict';

  var DOC = document;
  var WIN = window;

  /* 非 Harness 作用域：零副作用退出（classic / v2 / legacy 不受影响）。 */
  if (!DOC.body || DOC.body.getAttribute('data-shell') !== 'harness') return;

  /* ------------------------------ 常量 ------------------------------ */
  var WS_PAGE = { tasks: 'lite', content: 'drafts', collect: 'inspire', settings: 'console' };
  var PAGE_WS = { lite: 'tasks', drafts: 'content', inspire: 'collect', console: 'settings' };
  var LS = {
    workspace: 'yimu.hx.workspace',
    railMini: 'yimu.hx.railMini',
    stageOpen: 'yimu.hx.stageOpen',
    stageTab: 'yimu.hx.stageTab',
    style: 'yimu.shell.style'
  };
  var WS_LABEL = { tasks: '任务', content: '内容工作台', collect: '采集工作台', settings: '系统设置' };
  /* 「更多」分组的真实业务面板：不属于四工作区，但仍需在中栏露出真实面板。 */
  var MORE_PAGES = { dashboard: '操盘大屏', studio: '影音工坊', pricing: '套餐与价格', profile: '个人中心' };

  /* ------------------------------ 内部状态 ------------------------------ */
  var state = {
    workspace: 'tasks',
    page: 'lite',
    moreKey: null,
    draftId: null,
    topicId: null,
    stageTab: 'assets',
    stageOpen: true,
    railMini: false,
    drafts: [],
    status: {},
    tasks: [],
    data: {}
  };

  var listeners = {};
  var reg = { railChrome: null, railActive: null, railCtx: {}, thread: {}, stageTabs: {} };
  var booted = false;
  var readyResolve = null;
  var readyPromise = new Promise(function (resolve) { readyResolve = resolve; });

  /* ------------------------------ 小工具 ------------------------------ */
  function $(id) { return DOC.getElementById(id); }

  function el(tag, cls) {
    var e = DOC.createElement(tag);
    if (cls) e.className = cls;
    return e;
  }

  function storeGet(k) {
    try { return WIN.localStorage.getItem(k); } catch (e) { return null; }
  }
  function storeSet(k, v) {
    try { WIN.localStorage.setItem(k, v); } catch (e) { /* 隐私模式等场景静默 */ }
  }

  function fire(evt, payload) {
    var arr = listeners[evt];
    if (!arr) return;
    arr.slice().forEach(function (fn) {
      try { fn(payload !== undefined ? payload : state); }
      catch (e) { console.warn('[HX] listener error:', evt, e); }
    });
    /* 更多页模式下，线程模块的晚到事件回调可能回填自己的头/骨架；
       监听器跑完后按更多页口径复核一次，剥掉残留、恢复真实面板与兜底头。 */
    if (state.moreKey) { try { renderMorePanel(); } catch (e) { console.warn('[HX] more 页复核失败:', e); } }
  }

  /* ------------------------------ 对外工具 ------------------------------ */
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function trim(s, n) {
    s = String(s == null ? '' : s);
    n = n || 24;
    return s.length > n ? s.slice(0, n - 1) + '…' : s;
  }

  /* 从占位文案（“—”“— Token”“6,336,957 Token”）里提取真实数字；取不到返回 null。 */
  function parseAmount(v) {
    if (v == null) return null;
    var m = String(v).replace(/[¥￥\s]/g, '').match(/\d[\d,]*/);
    if (!m) return null;
    var n = Number(m[0].replace(/,/g, ''));
    return isNaN(n) ? null : n;
  }

  /* 余额取值优先级：真实导航节点 → billing 接口缓存 → 总额-已用 → 大盘节点。 */
  function readBalance() {
    var billing = state.data.billing || {};
    var n = parseAmount($('nav-token-bal') && $('nav-token-bal').textContent);
    if (n == null) n = billing.credits_left != null ? Number(billing.credits_left) : null;
    if (n == null && billing.credits_total != null && billing.credits_used != null) {
      n = Number(billing.credits_total) - Number(billing.credits_used);
    }
    if (n == null) n = parseAmount($('dash-billing-balance') && $('dash-billing-balance').textContent);
    return n;
  }

  function fmtTime(v) {
    if (!v) return '';
    var d;
    if (typeof v === 'number') {
      d = new Date(v < 1e12 ? v * 1000 : v);
    } else {
      d = new Date(String(v).replace(' ', 'T'));
      if (isNaN(d.getTime())) return String(v).slice(0, 16);
    }
    if (isNaN(d.getTime())) return '';
    var p = function (n) { return n < 10 ? '0' + n : '' + n; };
    var now = new Date();
    var sameDay = d.getFullYear() === now.getFullYear() &&
      d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
    if (sameDay) return '今天 ' + p(d.getHours()) + ':' + p(d.getMinutes());
    return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  }

  function ico(name, cls) {
    return '<svg class="icon' + (cls ? ' ' + cls : '') + '"><use href="#hx-i-' + name + '"/></svg>';
  }

  function toast(msg) {
    if (typeof WIN.toast === 'function') {
      try { WIN.toast(String(msg == null ? '' : msg)); return; } catch (e) { /* 回落自有 toast */ }
    }
    var t = $('hx-toast');
    if (!t) {
      t = el('div', 'hx-toast'); t.id = 'hx-toast'; DOC.body.appendChild(t);
    }
    t.textContent = String(msg == null ? '' : msg);
    t.classList.add('on');
    if (t._tm) clearTimeout(t._tm);
    t._tm = setTimeout(function () { t.classList.remove('on'); }, 3200);
  }

  /* fetch → json；失败返回 null 并 toast，绝不抛出。 */
  function api(path, opts) {
    opts = opts || {};
    var headers = Object.assign({}, opts.headers || {});
    if (opts.body && typeof opts.body === 'string' && !(opts.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
    }
    if (typeof WIN.csrfHeaders === 'function') {
      try { Object.assign(headers, WIN.csrfHeaders()); } catch (e) { /* 忽略 */ }
    }
    var fetchOpts = Object.assign({}, opts, { headers: headers });
    return fetch(path, fetchOpts).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      var ct = r.headers.get('content-type') || '';
      return ct.indexOf('application/json') >= 0 ? r.json() : r.text();
    }).then(function (data) { return data; })
      .catch(function (err) {
        toast((err && err.message) || '请求失败');
        return null;
      });
  }

  /* ------------------------------ 注册表 ------------------------------ */
  function registerRailCtx(ws, fn) {
    if (WS_PAGE[ws] && typeof fn === 'function') {
      reg.railCtx[ws] = fn;
      /* boot 之后晚到注册：仅重绘当前工作区的上下文槽，不整页 rebuild。 */
      if (booted && ws === state.workspace) renderRailCtx();
    }
  }
  function registerThread(ws, impl) {
    if (WS_PAGE[ws] && impl) {
      /* 线程实现不重复覆盖：collect/settings 由 D 模块在 eval 期先注册真实实现，
         B 的骨架兜底在其后（DOMContentLoaded）补注 tasks/content；已存在的实现优先保留。 */
      if (!reg.thread[ws]) {
        reg.thread[ws] = impl;
        if (booted && ws === state.workspace) renderThread();
      }
    }
  }
  function registerStageTab(ws, tab) {
    if (WS_PAGE[ws] && tab && tab.key) {
      if (!reg.stageTabs[ws]) reg.stageTabs[ws] = [];
      reg.stageTabs[ws].push(tab);
      if (booted && ws === state.workspace) renderStage();
    }
  }
  /* 内部挂载钩子：rail 模块注册整栏 chrome（brand/菜单/底部）。 */
  function registerRailChrome(fn) {
    if (typeof fn === 'function') reg.railChrome = fn;
  }
  /* rail 模块注册「菜单/更多项高亮」纯同步函数，供路由在渲染中栏前先写好激活态。 */
  function registerRailActive(fn) {
    if (typeof fn === 'function') reg.railActive = fn;
  }

  function ctx() {
    return {
      state: state,
      status: state.status,
      drafts: state.drafts,
      draft: state.draftId,
      topic: state.topicId,
      data: state.data
    };
  }

  /* ------------------------------ 路由搭桥 ------------------------------ */
  function callReal(fnName, args) {
    var fn = WIN[fnName];
    if (typeof fn !== 'function') return false;
    try { fn.apply(null, args || []); return true; }
    catch (e) { console.warn('[HX] ' + fnName + ' 调用失败:', e); return false; }
  }

  function syncNavActive() {
    var page = state.page;
    DOC.querySelectorAll('.nav-item[data-p]').forEach(function (n) {
      n.classList.toggle('on', n.getAttribute('data-p') === page);
    });
  }

  function renderRail() {
    var root = $('hxRail');
    if (!root) return;
    if (typeof reg.railChrome === 'function') {
      try { reg.railChrome(root, ctx()); } catch (e) { console.warn('[HX] rail chrome 渲染失败:', e); }
    }
    renderRailCtx();
  }

  function renderRailCtx() {
    var slot = $('hxRailCtx');
    if (!slot) return;
    var fn = reg.railCtx[state.workspace];
    slot.innerHTML = '';
    if (typeof fn === 'function') {
      try { fn(slot, ctx()); } catch (e) { console.warn('[HX] rail ctx 渲染失败:', e); }
    } else {
      slot.innerHTML = '<div class="hx-rail-empty">暂无内容</div>';
    }
  }

  /* 「更多」分组：把对应真实业务面板搬入中栏槽，保留原型式头部；不重写面板内部。 */
  function morePanelHome(panel) {
    if (!panel._hxHome) panel._hxHome = { parent: panel.parentElement, next: panel.nextSibling };
  }

  function renderMorePanel() {
    var head = $('hxThreadHead'), body = $('hxThreadBody');
    if (!head || !body) return;
    var key = state.moreKey;
    var panel = key ? $('p-' + key) : null;
    var label = MORE_PAGES[key] || '';
    var title = label;
    if (panel) {
      var h = panel.querySelector('h1, h2, .panel-title, .header-title');
      if (h && h.textContent.trim()) title = h.textContent.trim();
    }
    head.innerHTML = '<div class="hx-thread-fallback"><span class="hx-thread-fallback-title">' +
      esc(title || '工作台') + '</span></div>';
    if (!panel) {
      body.innerHTML = '<div class="hx-stage-empty"><div class="hx-stage-empty-art">' + ico('panel', 'lg') + '</div>' +
        '<p class="hx-stage-empty-title">面板未接入</p><p class="hx-stage-empty-desc">' + esc(label) + ' 面板暂未找到。</p></div>';
      return;
    }
    morePanelHome(panel);
    /* 清空中栏槽内其他骨架/空态节点，仅保留目标面板。 */
    Array.prototype.slice.call(body.children).forEach(function (c) {
      if (c !== panel) body.removeChild(c);
    });
    DOC.querySelectorAll('.panel').forEach(function (p) { p.classList.remove('on'); });
    panel.classList.add('on');
    if (panel.parentElement !== body) body.appendChild(panel);
  }

  function restoreMorePanel() {
    var key = state.moreKey;
    if (!key) return;
    var panel = $('p-' + key);
    if (panel && panel._hxHome) {
      var h = panel._hxHome;
      if (h.parent) h.parent.insertBefore(panel, h.next);
    }
    state.moreKey = null;
  }

  /* 更多页模式下，线程模块的轮询 / 草稿观察等异步回调可能晚到回填自己的头或骨架；
     观察中栏头/正文子树，一旦 moreKey 仍在，按更多页口径复核清扫（幂等）。 */
  function observeMoreSweep() {
    var body = $('hxThreadBody'), head = $('hxThreadHead');
    if (!body || !head || typeof WIN.MutationObserver !== 'function') return;
    var sweep = function () {
      if (!state.moreKey) return;
      var panel = $('p-' + state.moreKey);
      var stray = Array.prototype.some.call(body.children, function (c) { return c !== panel; });
      var headOk = head.children.length === 1 && head.querySelector('.hx-thread-fallback');
      /* 已处于更多页目标态：早退，避免观察器自写自触发形成回环。 */
      if (!stray && headOk) return;
      try { renderMorePanel(); } catch (e) { console.warn('[HX] more 观察清扫失败:', e); }
    };
    new WIN.MutationObserver(sweep).observe(body, { childList: true, subtree: true });
    new WIN.MutationObserver(sweep).observe(head, { childList: true, subtree: true });
  }

  /* 余额晚到兜底：观察真实导航节点，拿到非占位数字即同步并断开；不做重复轮询。 */
  function watchBalance() {
    if (typeof WIN.MutationObserver !== 'function') return;
    var obs = null;
    var sync = function () {
      if (readBalance() == null) return false;
      try { syncTopbarStatus(); } catch (e) { /* 忽略 */ }
      return true;
    };
    var attach = function () {
      var node = $('nav-token-bal');
      if (!node) return false;
      if (obs) obs.disconnect();
      obs = new WIN.MutationObserver(function () { if (sync()) obs.disconnect(); });
      obs.observe(node, { childList: true, characterData: true, subtree: true, attributes: true, attributeFilter: ['title'] });
      return sync();
    };
    if (!attach()) {
      setTimeout(function () { if (!attach()) setTimeout(attach, 800); }, 300);
    }
    /* 一次性晚到复核，避免观察器未覆盖的回填路径。 */
    setTimeout(function () { try { syncTopbarStatus(); } catch (e) { /* 忽略 */ } }, 1500);
  }

  function renderThread() {
    var head = $('hxThreadHead'), body = $('hxThreadBody');
    if (!head || !body) return;
    /* 更多分组优先：直接展示真实面板，不进入工作区线程实现。 */
    if (state.moreKey) { renderMorePanel(); return; }
    var impl = reg.thread[state.workspace];
    if (impl) {
      try {
        if (typeof impl.head === 'function') impl.head(head, ctx());
        if (typeof impl.body === 'function') impl.body(body, ctx());
      } catch (e) { console.warn('[HX] thread 渲染失败:', e); }
    }
    /* 未注册工作区：保留真实业务面板原样展示，给出安全兜底头。 */
    if (!impl) {
      head.innerHTML = '<div class="hx-thread-fallback"><span class="hx-thread-fallback-title">' +
        esc(WS_LABEL[state.workspace] || '') + '</span></div>';
    }
  }

  function renderStage() {
    var tabsWrap = $('hxStageTabs'), body = $('hxStageBody');
    if (!tabsWrap || !body) return;
    var tabs = reg.stageTabs[state.workspace] || [];
    if (!tabs.length) {
      /* 当前工作区暂无注册页签：保留已有 DOM（不清空页签、不隐藏舞台），
         等待晚到注册或资产台填充；仅当全局确实没有任何舞台实现时才给空态文案。 */
      var anyStage = false;
      for (var k in reg.stageTabs) {
        if (reg.stageTabs[k] && reg.stageTabs[k].length) { anyStage = true; break; }
      }
      if (!anyStage) {
        tabsWrap.innerHTML = '';
        body.style.display = '';
        body.innerHTML = '<div class="hx-stage-empty"><div class="hx-stage-empty-art">' + ico('panel', 'lg') + '</div>' +
          '<p class="hx-stage-empty-title">暂无舞台内容</p><p class="hx-stage-empty-desc">选中任务或稿件后，成稿 / 图片 / 视频会显示在这里。</p></div>';
      }
      return;
    }
    tabsWrap.innerHTML = '';
    body.style.display = '';
    var active = null;
    tabs.forEach(function (tab) {
      var btn = el('button', 'hx-stage-tab' + (tab.key === state.stageTab ? ' is-active' : ''));
      btn.type = 'button';
      btn.setAttribute('data-tab', tab.key);
      var count = '';
      try { if (typeof tab.count === 'function') count = tab.count(ctx()); } catch (e) { count = ''; }
      btn.innerHTML = '<span>' + esc(tab.title || tab.key) + '</span>' +
        (count ? '<em class="hx-tab-count">' + esc(count) + '</em>' : '');
      btn.addEventListener('click', function () { HX.setStageTab(tab.key); });
      tabsWrap.appendChild(btn);
      if (tab.key === state.stageTab) active = tab;
    });
    if (!active) { active = tabs[0]; state.stageTab = active.key; }
    body.innerHTML = '';
    var pane = el('div', 'hx-stage-pane is-active');
    body.appendChild(pane);
    try {
      if (typeof active.mount === 'function') active.mount(pane, ctx());
      if (typeof active.refresh === 'function') active.refresh(pane, ctx());
    } catch (e) { console.warn('[HX] stage pane 渲染失败:', e); }
  }

  function renderAll() { renderRail(); renderThread(); renderStage(); }

  function applyAttrs() {
    DOC.documentElement.setAttribute('data-rail', state.railMini ? 'mini' : 'full');
    DOC.body.setAttribute('data-rail', state.railMini ? 'mini' : 'full');
    DOC.body.setAttribute('data-stage', state.stageOpen ? 'open' : 'closed');
  }

  /* ------------------------------ 对外动作 ------------------------------ */
  function openWorkspace(key) {
    if (!WS_PAGE[key]) return;
    restoreMorePanel();
    state.workspace = key;
    state.page = WS_PAGE[key];
    storeSet(LS.workspace, key);
    callReal('switchToPage', [WS_PAGE[key]]);
    applyAttrs();
    /* 先把顶栏分段 / 左栏菜单 / 更多项高亮同步写好，再渲染中栏，避免高亮滞后或错位。 */
    syncActive();
    fire('workspace', ctx());
    fire('state', ctx());
    renderAll();
    /* 幂等复核：下一帧再按 state 校一遍高亮，拦截异步渲染回写旧值。 */
    requestAnimationFrame(function () { try { syncActive(); } catch (e) { console.warn('[HX] 高亮复核失败:', e); } });
  }

  function openMorePage(key) {
    if (!MORE_PAGES[key]) return;
    /* 先归还上一个更多面板，避免切换时把旧面板剥离成游离节点。 */
    restoreMorePanel();
    state.moreKey = key;
    state.page = key;
    callReal('switchToPage', [key]);
    applyAttrs();
    /* 更多页：顶栏工作区分段全部去高亮，左栏仅对应更多项激活；先写高亮再渲染中栏。 */
    syncActive();
    fire('workspace', ctx());
    fire('state', ctx());
    renderAll();
    requestAnimationFrame(function () { try { syncActive(); } catch (e) { console.warn('[HX] 高亮复核失败:', e); } });
    /* B 线程模块会在 workspace/state 事件回调里回填自己的头/骨架；更多页不属于四工作区，
       事件循环末尾再清扫一次，剥掉晚到写入的线程残留。 */
    setTimeout(function () { try { renderMorePanel(); } catch (e) { console.warn('[HX] more 页清扫失败:', e); } }, 0);
  }

  function openDraft(id) {
    if (!id) return;
    state.draftId = String(id);
    openWorkspace('content');
    var ok = false;
    if (typeof WIN.selectDraft === 'function') { ok = callReal('selectDraft', [id]); }
    if (!ok) {
      var box = $('draft-list-container');
      if (box) {
        var chk = box.querySelector('[data-id="' + id + '"]');
        var card = chk && chk.closest ? chk.closest('.draft-card') : null;
        if (card) card.click();
      }
    }
    fire('draft', ctx());
    fire('state', ctx());
    renderRail(); renderStage();
  }

  function newTask(text) {
    var ws = state.workspace;
    if (typeof text === 'string' && text.trim()) state.topicId = text.trim();
    if (ws === 'content') { callReal('openNewDraftModal'); return; }
    if (typeof WIN.newLiteDraft === 'function') { callReal('newLiteDraft'); }
    else { callReal('openNewDraftModal'); }
  }

  function refresh() {
    return Promise.all([api('/api/status'), api('/api/tasks')]).then(function (res) {
      var st = res[0] || {};
      var tk = res[1] || {};
      state.status = st;
      state.drafts = st.drafts || [];
      state.tasks = (tk && tk.tasks) || [];
      /* 额度/套餐：优先读真实顶栏节点（业务侧 loadBillingStatus 已回填），再补拉账单接口。 */
      api('/api/billing/ui/me').then(function (b) {
        var d = (b && b.data) || b || {};
        state.data.billing = d;
        syncTopbarStatus();
        fire('state', ctx());
      });
      fire('drafts', ctx());
      fire('state', ctx());
      renderRail(); renderStage();
      syncTopbarStatus();
    });
  }

  function setStageTab(tab) {
    var key = tab && typeof tab === 'object' ? tab.key : tab;
    if (!key) return;
    state.stageTab = key;
    storeSet(LS.stageTab, key);
    fire('stage', ctx());
    renderStage();
  }

  function toggleStage() {
    state.stageOpen = !state.stageOpen;
    storeSet(LS.stageOpen, state.stageOpen ? '1' : '0');
    applyAttrs();
    syncStageBtn();
    fire('stage', ctx());
  }

  function toggleRail() {
    state.railMini = !state.railMini;
    storeSet(LS.railMini, state.railMini ? '1' : '0');
    applyAttrs();
    fire('state', ctx());
    renderRail();
  }

  /* ------------------------------ 顶栏 ------------------------------ */
  function syncTopbarStatus() {
    var bal = $('nav-token-bal'), tier = $('nav-tier-badge');
    var balEl = $('hx-tb-balance'), tierEl = $('hx-tb-tier'), taskEl = $('hx-tb-tasks');
    var billing = state.data.billing || {};
    var n = readBalance();
    if (balEl) balEl.textContent = n != null ? n.toLocaleString() : '—';
    if (tierEl) tierEl.textContent = tier && tier.textContent.trim() ? tier.textContent.trim() : (billing.tier_display || '基础版');
    if (taskEl) {
      var active = state.tasks.filter(function (t) {
        return t && t.status && !(/done|success|failed|cancelled|canceled|completed/.test(String(t.status)));
      }).length;
      var b = taskEl.querySelector('b');
      if (b) b.textContent = String(active);
      taskEl.style.display = active > 0 ? '' : 'none';
      taskEl.classList.toggle('has', active > 0);
    }
    var accName = $('hxTbAccount') && $('hxTbAccount').querySelector('.hx-tb-account-name');
    var accAvatar = $('hxTbAccount') && $('hxTbAccount').querySelector('.hx-tb-avatar');
    var realName = ($('profile-user-display-name') || {}).textContent ||
      ($('side-user-title') || {}).textContent || ($('top-auth-text') || {}).textContent || '个人中心';
    realName = String(realName).trim() || '个人中心';
    if (accName) accName.textContent = trim(realName, 12);
    if (accAvatar) {
      var realAvatar = $('top-auth-avatar-img') || $('profile-user-avatar-img');
      if (realAvatar && realAvatar.src) {
        accAvatar.innerHTML = '<img src="' + esc(realAvatar.src) + '" alt="">';
      } else {
        accAvatar.textContent = realName.charAt(0) || '曹';
      }
    }
  }

  function shellStyleOptions() {
    return [
      { key: 'harness', label: 'Harness 三栏' },
      { key: 'v2', label: 'V11 工作台' },
      { key: 'classic', label: '经典版' }
    ];
  }

  function setShellStyle(style) {
    if (['harness', 'v2', 'classic'].indexOf(style) < 0) return;
    storeSet(LS.style, style);
    var u = new URL(location.href);
    if (style === 'classic') {
      u.searchParams.set('legacy', '1');
      u.searchParams.delete('ui'); u.searchParams.delete('shell');
    } else {
      u.searchParams.set('ui', style);
      u.searchParams.delete('legacy'); u.searchParams.delete('classic');
    }
    location.href = u.toString();
  }

  function buildTopbar() {
    var bar = $('hxTopbar');
    if (!bar) return;
    var seg = ['tasks', 'content', 'collect', 'settings'].map(function (k) {
      return '<button type="button" class="hx-tb-seg-btn" data-ws="' + k + '">' + esc(WS_LABEL[k]) + '</button>';
    }).join('');
    bar.innerHTML =
      '<div class="hx-tb-brand">' +
        '<img class="hx-logo" src="/static/img/logo-icon.png" srcset="/static/img/logo-icon.png 1x, /static/img/logo.png 2x" alt="一幕·YIMU">' +
        '<span class="hx-tb-name">一幕·YIMU</span>' +
        '<span class="hx-tb-badge">爆款工作室</span>' +
      '</div>' +
      '<div class="hx-tb-seg" role="group" aria-label="工作区切换">' + seg + '</div>' +
      '<button type="button" class="hx-tb-search" id="hxTbSearch">' +
        ico('search') + '<span>搜索任务、资产…</span><kbd>⌘K</kbd>' +
      '</button>' +
      '<div class="hx-tb-status">' +
        '<button type="button" class="hx-tb-pill" id="hxTbBilling" title="套餐与算力余额">' +
          ico('bolt', 'sm') + '<span class="hx-tb-pill-label">算力</span><b id="hx-tb-balance">—</b>' +
        '</button>' +
        '<span class="hx-tb-pill hx-tb-tier" id="hx-tb-tier">基础版</span>' +
        '<span class="hx-tb-pill hx-tb-tasks" id="hx-tb-tasks" title="后台任务数">' + ico('chart', 'sm') + '<b>0</b></span>' +
      '</div>' +
      '<div class="hx-tb-acts">' +
        '<button type="button" class="hx-tb-theme" id="hxTbTheme" title="切换外观：浅色 / 深色 / 跟随系统">' +
          '<span class="hx-tb-theme-icon" id="hxTbThemeIcon" aria-hidden="true">🌓</span>' +
          '<span class="hx-tb-theme-label">外观</span>' +
        '</button>' +
        '<button type="button" class="hx-tb-stage" id="hxTbStage" aria-pressed="true" title="收起舞台">' +
          ico('panel', 'sm') + '<span class="hx-tb-stage-label">舞台</span>' +
        '</button>' +
        '<button type="button" class="hx-tb-account" id="hxTbAccount" title="账号与个人中心">' +
          '<span class="hx-tb-avatar">曹</span><span class="hx-tb-account-name">个人中心</span>' + ico('chevron-down', 'sm') +
        '</button>' +
        '<div class="hx-tb-style" id="hxTbStyle">' +
          '<button type="button" class="hx-tb-style-btn" title="切换界面风格">' + ico('panel', 'sm') + '<span>风格</span></button>' +
          '<div class="hx-tb-style-menu" id="hxTbStyleMenu"></div>' +
        '</div>' +
      '</div>';

    bar.querySelectorAll('[data-ws]').forEach(function (btn) {
      btn.addEventListener('click', function () { openWorkspace(btn.getAttribute('data-ws')); });
    });
    var search = $('hxTbSearch');
    if (search) search.addEventListener('click', function () { callReal('toggleCmdK'); });
    var billing = $('hxTbBilling');
    if (billing) billing.addEventListener('click', function () { callReal('openBillingModal'); });
    var account = $('hxTbAccount');
    if (account) account.addEventListener('click', function () {
      if (typeof WIN.switchToProfileCenter === 'function') callReal('switchToProfileCenter');
      else callReal('openProfileModal');
    });
    /* 舞台开合常驻入口：所有页面可见，右栏收起后仍是唯一入口；状态共用 state.stageOpen，
       与任务页/内容页页头的舞台按钮同一本账，不各自记账。 */
    var stageBtn = $('hxTbStage');
    if (stageBtn) stageBtn.addEventListener('click', function () { toggleStage(); });
    var styleBtn = bar.querySelector('.hx-tb-style-btn');
    var styleMenu = $('hxTbStyleMenu');
    if (styleBtn && styleMenu) {
      styleMenu.innerHTML = shellStyleOptions().map(function (o) {
        return '<button type="button" data-style="' + o.key + '">' + esc(o.label) + '</button>';
      }).join('');
      styleBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        styleMenu.classList.toggle('open');
      });
      styleMenu.addEventListener('click', function (e) {
        var b = e.target.closest ? e.target.closest('[data-style]') : null;
        if (!b) return;
        setShellStyle(b.getAttribute('data-style'));
      });
      DOC.addEventListener('click', function () { styleMenu.classList.remove('open'); });
    }

    /* 外观入口：循环 light → dark → system，复用站点既有 cycleThemeMode()，
       不另写切换逻辑、不新增存储键；按钮图标随当前模式实时回显。 */
    var themeBtn = $('hxTbTheme');
    if (themeBtn) {
      themeBtn.addEventListener('click', function () {
        if (typeof WIN.cycleThemeMode === 'function') callReal('cycleThemeMode', []);
        syncThemeBtn();
      });
      syncThemeBtn();
      /* 设置页 / 下拉等既有控件切换主题后，同步回显本按钮。 */
      if (typeof WIN.MutationObserver === 'function') {
        var mo = new WIN.MutationObserver(function () { syncThemeBtn(); });
        mo.observe(DOC.documentElement, { attributes: true, attributeFilter: ['data-theme-mode', 'data-theme'] });
      }
    }
  }

  /* 读取站点既有偏好（getThemeMode 优先，回落 localStorage），回显外观按钮。 */
  function currentThemeMode() {
    if (typeof WIN.getThemeMode === 'function') { try { return WIN.getThemeMode(); } catch (e) { /* 回落 */ } }
    return storeGet('yimu_ui_theme_mode') || 'system';
  }

  function syncThemeBtn() {
    var icon = $('hxTbThemeIcon');
    var btn = $('hxTbTheme');
    if (!icon || !btn) return;
    var mode = currentThemeMode();
    var map = { light: '☀️', dark: '🌙', system: '🌓' };
    icon.textContent = map[mode] || '🌓';
    btn.setAttribute('data-mode', mode);
    btn.title = mode === 'light' ? '当前：浅色（点击切换深色）' :
      mode === 'dark' ? '当前：深色（点击切换跟随系统）' : '当前：跟随系统（点击切换浅色）';
  }

  /* 顶栏舞台按钮状态回显：唯一判据 state.stageOpen（与页头舞台按钮共享）。 */
  function syncStageBtn() {
    var btn = $('hxTbStage');
    if (!btn) return;
    var open = !!state.stageOpen;
    btn.classList.toggle('is-active', open);
    btn.setAttribute('aria-pressed', open ? 'true' : 'false');
    btn.title = open ? '收起舞台' : '展开舞台';
  }

  function syncTopbarActive() {
    var bar = $('hxTopbar');
    if (!bar) return;
    bar.querySelectorAll('[data-ws]').forEach(function (btn) {
      btn.classList.toggle('is-active', !state.moreKey && btn.getAttribute('data-ws') === state.workspace);
    });
  }

  /* 顶栏分段 + 左栏菜单 + 更多项高亮的统一同步入口；路由在渲染中栏前同步调用，
     并在 rAF 内幂等复核，防止异步渲染把激活态写回旧工作区。 */
  function syncActive() {
    syncNavActive();
    syncTopbarActive();
    if (typeof reg.railActive === 'function') {
      try { reg.railActive(ctx()); } catch (e) { console.warn('[HX] rail 高亮同步失败:', e); }
    }
  }

  /* ------------------------------ 骨架挂载 ------------------------------ */
  function buildSkeleton() {
    var body = DOC.body;
    var side = body.querySelector('aside.side');
    var main = body.querySelector('.main-wrapper');
    var assets = DOC.getElementById('assetsPanel');

    var railWrap = el('div', 'hx-rail'); railWrap.id = 'hxRail';

    var threadWrap = el('div', 'hx-thread'); threadWrap.id = 'hxThread';
    var threadHead = el('div', 'hx-thread-head-slot'); threadHead.id = 'hxThreadHead';
    var threadBody = el('div', 'hx-thread-body-slot'); threadBody.id = 'hxThreadBody';
    threadWrap.appendChild(threadHead);
    threadWrap.appendChild(threadBody);

    var stageWrap = el('div', 'hx-stage'); stageWrap.id = 'hxStage';
    var stageTabs = el('div', 'hx-stage-tabs-slot'); stageTabs.id = 'hxStageTabs';
    var stageBody = el('div', 'hx-stage-body-slot'); stageBody.id = 'hxStageBody';
    stageWrap.appendChild(stageTabs);
    stageWrap.appendChild(stageBody);

    var topbar = el('header', 'hx-topbar'); topbar.id = 'hxTopbar';

    body.insertBefore(topbar, body.firstChild);
    body.insertBefore(railWrap, side || main || assets || null);
    body.insertBefore(threadWrap, main || assets || null);
    body.insertBefore(stageWrap, assets || null);

    if (side) railWrap.appendChild(side);
    /* 真实 main-wrapper 作为线程槽的兄弟节点保留：thread 模块重写 #hxThreadBody
       的 innerHTML 不会销毁业务面板与旧节点；需要露出的面板由 B/D 搬入各自宿主。 */
    if (main) threadWrap.appendChild(main);
    if (assets) stageWrap.appendChild(assets);
  }

  /* 反向同步：业务侧选稿（真实卡片 .on 变化）时跟随更新外壳 state，避免镜像行与
     业务选中各走各的。同值不广播，避免与 openDraft 形成回环抖动。 */
  function observeDraftSelection() {
    var box = $('draft-list-container');
    if (!box) return;
    var read = function () {
      var on = box.querySelector('.draft-card.on');
      var chk = on && on.querySelector('input[data-id]');
      var id = chk ? chk.dataset.id : null;
      if (!id) return;
      id = String(id);
      if (id === String(state.draftId || '')) return;
      state.draftId = id;
      fire('draft', ctx());
      fire('state', ctx());
      renderRail();
    };
    var mo = new MutationObserver(read);
    mo.observe(box, { subtree: true, attributes: true, attributeFilter: ['class'] });
    setInterval(read, 600);
  }

  function observeRealNav() {
    DOC.addEventListener('click', function (e) {      var t = e.target && e.target.closest ? e.target.closest('.nav-item[data-p]') : null;
      if (!t) return;
      var key = t.getAttribute('data-p');
      var ws = PAGE_WS[key];
      if (ws) {
        restoreMorePanel();
        state.workspace = ws; state.page = key;
        storeSet(LS.workspace, ws);
        syncTopbarActive();
        fire('workspace', ctx()); fire('state', ctx());
        renderAll();
      } else if (MORE_PAGES[key]) {
        /* 真实导航冒泡进入更多分组：去重后走统一 more 路由。 */
        if (state.moreKey !== key) openMorePage(key);
      }
    });
  }

  function bindKeyboard() {
    DOC.addEventListener('keydown', function (e) {
      if (!(e.metaKey || e.ctrlKey)) return;
      var k = (e.key || '').toLowerCase();
      var t = e.target;
      var editable = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' ||
        t.tagName === 'SELECT' || t.isContentEditable);
      if (k === 'k') {
        e.preventDefault();
        callReal('toggleCmdK');
        return;
      }
      if (k === 'n' && !editable) {
        e.preventDefault();
        newTask();
      }
    });
  }

  function restorePersisted() {
    var ws = storeGet(LS.workspace);
    if (WS_PAGE[ws]) state.workspace = ws;
    state.page = WS_PAGE[state.workspace];
    state.railMini = storeGet(LS.railMini) === '1';
    state.stageOpen = storeGet(LS.stageOpen) !== '0';
    var tab = storeGet(LS.stageTab);
    if (tab) state.stageTab = tab;
  }

  /* ------------------------------ 图标 sprite ------------------------------ */
  var SPRITE = [
    ['plus', '<path d="M12 5v14M5 12h14"/>'],
    ['search', '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4 4"/>'],
    ['sliders', '<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>'],
    ['tasks', '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 9h8M8 13h5M8 17h3"/>'],
    ['layers', '<path d="M12 4l8 4-8 4-8-4 8-4z"/><path d="M4 12l8 4 8-4M4 16l8 4 8-4"/>'],
    ['grid', '<rect x="4" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5"/>'],
    ['settings', '<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1.1l2-1.5-2-3.4-2.3.9a7 7 0 0 0-1.9-1.1L14.3 3h-4.6l-.4 2.8a7 7 0 0 0-1.9 1.1L5 6l-2 3.4 2 1.5A7 7 0 0 0 5 12a7 7 0 0 0 .1 1.1l-2 1.5 2 3.4 2.3-.9a7 7 0 0 0 1.9 1.1l.4 2.8h4.6l.4-2.8a7 7 0 0 0 1.9-1.1l2.3.9 2-3.4-2-1.5A7 7 0 0 0 19 12z"/>'],
    ['sparkles', '<path d="M12 3l1.4 4.6L18 9l-4.6 1.4L12 15l-1.4-4.6L6 9l4.6-1.4L12 3z"/><path d="M18.5 15l.7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.3z"/>'],
    ['message', '<path d="M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H9l-4 3v-3H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z"/><path d="M8 10h8M8 13h5"/>'],
    ['file', '<path d="M7 3h7l4 4v14H7V3z"/><path d="M14 3v5h5M9.5 12h5M9.5 15h5M9.5 18h3"/>'],
    ['image', '<rect x="3.5" y="4" width="17" height="16" rx="2.5"/><circle cx="9" cy="9" r="1.6"/><path d="M5 18l5-5 3.5 3 2.5-2 3 3"/>'],
    ['video', '<rect x="3.5" y="5" width="12.5" height="14" rx="2.5"/><path d="M16 9l4.5-2v10L16 15"/>'],
    ['chart', '<path d="M4 19h16"/><path d="M6 16V10M10 16V7M14 16v-4M18 16V4"/>'],
    ['globe', '<circle cx="12" cy="12" r="8"/><path d="M4 12h16M12 4a13 13 0 0 1 0 16M12 4a13 13 0 0 0 0 16"/>'],
    ['book', '<path d="M5 4h6a2 2 0 0 1 2 2v14a2 2 0 0 0-2-2H5V4z"/><path d="M19 4h-6a2 2 0 0 0-2 2v14a2 2 0 0 1 2-2h6V4z"/>'],
    ['share', '<circle cx="18" cy="5.5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="18.5" r="2.5"/><path d="M8.2 10.8l7.6-4M8.2 13.2l7.6 4"/>'],
    ['pin', '<path d="M9 4h6l-1 5 3 3v1H7v-1l3-3-1-5z"/><path d="M12 13v7"/>'],
    ['panel', '<rect x="3.5" y="4" width="17" height="16" rx="2.5"/><path d="M15 4v16M15 9h4M15 13h4"/>'],
    ['more', '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>'],
    ['user', '<circle cx="12" cy="8" r="3.2"/><path d="M5 20c1.5-4 4-6 7-6s5.5 2 7 6"/>'],
    ['ellipsis', '<circle cx="6" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="18" cy="12" r="1.2"/>'],
    ['chevron-down', '<path d="M6 9l6 6 6-6"/>'],
    ['chevron-right', '<path d="M9 5l7 7-7 7"/>'],
    ['arrow-up-right', '<path d="M7 17L17 7M8 7h9v9"/>'],
    ['check', '<path d="M5 12.5l4.5 4.5L19 7"/>'],
    ['clock', '<circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/>'],
    ['expand', '<path d="M9 4H4v5M15 4h5v5M9 20H4v-5M15 20h5v-5"/>'],
    ['x', '<path d="M6 6l12 12M18 6l-12 12"/>'],
    ['send', '<path d="M20 4L10 14"/><path d="M20 4l-6 16-4-6-6-4 16-6z"/>'],
    ['paperclip', '<path d="M9 12.5l6-6a3.2 3.2 0 0 1 4.5 4.5l-8 8a5 5 0 0 1-7-7l8-8"/><path d="M7 15l7-7"/>'],
    ['mic', '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M6 11a6 6 0 0 0 12 0M12 17v4"/>'],
    ['code', '<path d="M8 8L4 12l4 4M16 8l4 4-4 4M14 5l-4 14"/>'],
    ['hash', '<path d="M9 4L7 20M17 4l-2 16M5 9h15M4 15h15"/>'],
    ['play', '<circle cx="12" cy="12" r="8"/><path d="M10 8.5l6 3.5-6 3.5v-7z"/>'],
    ['lock', '<rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>'],
    ['refresh', '<path d="M20 12a8 8 0 1 1-2.34-5.66"/><path d="M20 4v5h-5"/>'],
    ['download', '<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5"/><path d="M5 19h14"/>'],
    ['command', '<path d="M9 6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6z"/>'],
    ['bolt', '<path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z"/>'],
    ['edit', '<path d="M4 20h4l12-12-4-4L4 16v4z"/><path d="M13 6l4 4"/>'],
    ['eye', '<path d="M3 12s3-5 9-5 9 5 9 5-3 5-9 5-9-5-9-5z"/><circle cx="12" cy="12" r="2.2"/>'],
    ['copy', '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>'],
    ['rocket', '<path d="M5 15l-2 6 6-2c3-1 6-3 8-6l3-5-5 0-5 3-2 1-3 3z"/><path d="M14 10l3 3"/><circle cx="11" cy="9" r="1.2"/>'],
    ['folder', '<path d="M3.5 7a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2V7z"/>'],
    ['notes', '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h3"/>']
  ];

  function injectSprite() {
    if ($('hx-sprite')) return;
    /* 经 innerHTML 解析 <svg>：HTML 解析器会把 svg 及其子节点放入 SVG 命名空间，
       避免 createElement('svg') 落到 XHTML 命名空间导致 <circle/>/<rect/> 不自闭合、
       path 被嵌套进图形节点、<use> 引用失效。 */
    var holder = DOC.createElement('div');
    holder.innerHTML = '<svg class="hx-sprite" id="hx-sprite" aria-hidden="true">' +
      SPRITE.map(function (s) {
        return '<symbol id="hx-i-' + s[0] + '" viewBox="0 0 24 24">' + s[1] + '</symbol>';
      }).join('') + '</svg>';
    DOC.body.appendChild(holder.firstChild);
  }

  /* ------------------------------ boot ------------------------------ */
  function boot() {
    if (booted) return;
    booted = true;
    try {
      restorePersisted();
      injectSprite();
      buildSkeleton();
      buildTopbar();
      observeMoreSweep();
      applyAttrs();
      syncStageBtn();
      HX.on('stage', syncStageBtn);
      HX.on('state', syncStageBtn);
      observeRealNav();
      observeDraftSelection();
      bindKeyboard();
      callReal('switchToPage', [WS_PAGE[state.workspace]]);
      syncNavActive();
      syncTopbarActive();
      refresh();
      watchBalance();
      renderAll();
      /* 晚到注册兜底：部分模块在自身 DOMContentLoaded 回调里才注册线程/舞台/上下文，
         本轮事件循环末尾再增量重绘一次，避免永久停留在兜底空态。 */
      setTimeout(function () {
        try { renderAll(); } catch (e) { console.warn('[HX] 晚到注册重绘失败:', e); }
      }, 0);
      fire('ready', ctx());
      if (readyResolve) readyResolve(state);
    } catch (e) {
      console.warn('[HX] boot 异常:', e);
      if (readyResolve) readyResolve(state);
    }
  }

  /* ------------------------------ 暴露 HX ------------------------------ */
  var HX = {
    state: state,
    ready: readyPromise,
    on: function (evt, fn) {
      if (!listeners[evt]) listeners[evt] = [];
      listeners[evt].push(fn);
    },
    off: function (evt, fn) {
      var arr = listeners[evt];
      if (!arr) return;
      var i = arr.indexOf(fn);
      if (i >= 0) arr.splice(i, 1);
    },
    esc: esc,
    trim: trim,
    fmtTime: fmtTime,
    ico: ico,
    api: api,
    toast: toast,
    openWorkspace: openWorkspace,
    openDraft: openDraft,
    openMorePage: openMorePage,
    newTask: newTask,
    refresh: refresh,
    setStageTab: setStageTab,
    toggleStage: toggleStage,
    toggleRail: toggleRail,
    registerRailCtx: registerRailCtx,
    registerThread: registerThread,
    registerStageTab: registerStageTab,
    /* 内部桥接（rail 模块注册整栏 chrome 与菜单高亮）。 */
    _registerRailChrome: registerRailChrome,
    _registerRailActive: registerRailActive,
    _ctx: ctx,
    _reg: reg,
    _renderAll: renderAll,
    _syncTopbarActive: syncTopbarActive,
    _syncTopbarStatus: syncTopbarStatus
  };

  WIN.HX = HX;

  if (DOC.readyState === 'loading') {
    DOC.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
