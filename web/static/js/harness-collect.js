/* SPDX-License-Identifier: BUSL-1.1 */
/* ==========================================================================
   Harness · 采集工作台（D 模块）
   --------------------------------------------------------------------------
   职责边界（严格）：
     1. 左栏采集上下文：真实 /api/status.topics 列表 + 真实状态筛选；
     2. 中栏：把真实 #p-inspire 面板重排进采集工作区，保留全部真实按钮
        与 onclick 链路，不复制业务逻辑；
     3. 右栏：注册「采集分析」页签，展示选中话题的真实字段；原型有、
        系统没有的拆解 / 素材能力只给「未接入」空态，不伪造数据。
   只在 body[data-shell="harness"] 下工作；classic / v2 零影响。
   ========================================================================== */
(function () {
  "use strict";

  var DOC = document;
  var WIN = window;

  function shellOk() {
    return DOC.body && DOC.body.getAttribute("data-shell") === "harness";
  }
  if (!shellOk()) return;

  /* ------------------------------ 本地工具 ------------------------------ */
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function trim(s, n) {
    s = String(s == null ? "" : s);
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  }
  function byId(id) { return DOC.getElementById(id); }
  function tryFn(fn) { try { fn(); } catch (e) { /* 模块异常不阻断业务 */ } }

  /* 图标：优先走 core 注入的 HX.ico；本地保留一份精简路径兜底。 */
  var ICON_PATHS = {
    globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.3 2.3 3.5 5.2 3.5 8.5s-1.2 6.2-3.5 8.5c-2.3-2.3-3.5-5.2-3.5-8.5S9.7 5.8 12 3.5z"/>',
    lock: '<rect x="5" y="10.5" width="14" height="9.5" rx="2"/><path d="M8 10.5V8a4 4 0 018 0v2.5"/>',
    check: '<path d="M5.5 12.5l4 4 9-9.5"/>',
    bolt: '<path d="M13 2.5L4.5 13.5H11L10 21.5l8.5-11H12z"/>',
    user: '<circle cx="12" cy="8.5" r="3.6"/><path d="M4.8 20c1-3.7 3.8-5.6 7.2-5.6s6.2 1.9 7.2 5.6"/>',
    panel: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M14.5 4.5v15"/>',
    sparkles: '<path d="M12 3.5l1.9 4.9 4.9 1.9-4.9 1.9L12 17.1l-1.9-4.9L5.2 10.3l4.9-1.9z"/>',
    image: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><circle cx="9" cy="9.5" r="1.6"/><path d="M4.5 17.5l4.5-4.5 3 3 3.5-3.5 4 4.5"/>',
    refresh: '<path d="M20 12a8 8 0 11-2.3-5.6M20 4.5v5h-5"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    layers: '<path d="M12 3l8.5 4.5L12 12 3.5 7.5z"/><path d="M3.5 12L12 16.5 20.5 12M3.5 16.5L12 21l8.5-4.5"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    doc: '<path d="M6.5 3.5h7l4.5 4.5v13h-11.5z"/><path d="M13.5 3.5V8h4.5M9 12.5h6M9 16h4"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>'
  };
  function ico(name, cls) {
    if (WIN.HX && typeof WIN.HX.ico === "function") {
      var h = WIN.HX.ico(name, cls || "hx-ico");
      if (h) return h;
    }
    var d = ICON_PATHS[name] || ICON_PATHS.doc;
    return '<svg class="' + (cls || "hx-ico") + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + d + "</svg>";
  }

  /* --------------------------- 真实话题字段映射 -------------------------- */
  var SRC_MAP = {
    weibo: ["微博热搜", "hx-thumb-wb"],
    douyin: ["抖音热榜", "hx-thumb-dy"],
    toutiao: ["今日头条", "hx-thumb-tt"],
    baidu: ["百度热搜", "hx-thumb-bd"],
    xhs: ["小红书", "hx-thumb-xhs"],
    wechat_mp: ["公众号", "hx-thumb-wx"],
    dailyhotapi: ["综合热榜", "hx-thumb-zg"],
    manual: ["人工录入", "hx-thumb-zg"],
    custom: ["人工录入", "hx-thumb-zg"],
    paste: ["粘贴文案", "hx-thumb-zg"]
  };
  function sourceLabel(src) {
    var m = SRC_MAP[src];
    return m ? m[0] : (src ? String(src) : "未知来源");
  }
  function thumbClass(src) {
    var m = SRC_MAP[src];
    return m ? m[1] : "hx-thumb-zg";
  }
  var STATUS_LABEL = {
    pending: "待拆解",
    preview: "待审",
    approved: "已通过",
    drafted: "已成稿",
    published: "已发布",
    rejected: "已拒绝",
    blocked: "已拦截"
  };
  function statusLabel(st) { return STATUS_LABEL[st] || st || "未知"; }
  function statusKind(st) {
    if (st === "drafted" || st === "published" || st === "approved") return "done";
    if (st === "blocked" || st === "rejected") return "off";
    return "wait";
  }

  var FILTERS = [
    { key: "all", label: "全部", match: function () { return true; } },
    { key: "pending", label: "待拆解", match: function (t) { return t.status === "pending" || t.status === "preview"; } },
    { key: "archived", label: "已入库", match: function (t) { return t.status === "drafted" || t.status === "published" || t.status === "approved"; } }
  ];

  /* 中栏真实面板 #p-inspire 的 6 个二级入口；选中态跟随真实 switchSubTab，
     这里只做读取与中栏标题/面包屑同步，不重复实现切换逻辑。 */
  var INSPIRE_TABS = [
    { sp: "sp-oneshot", label: "一句话成爆款" },
    { sp: "sp-extract", label: "万能爆款链接采集" },
    { sp: "sp-hot", label: "实时热榜抓取" },
    { sp: "sp-search", label: "爆款搜索仿写" },
    { sp: "sp-paste", label: "粘贴文案改编" },
    { sp: "sp-batch", label: "批量矩阵生产" }
  ];
  function inspireMeta(sp) {
    for (var i = 0; i < INSPIRE_TABS.length; i++) {
      if (INSPIRE_TABS[i].sp === sp) return INSPIRE_TABS[i];
    }
    return INSPIRE_TABS[0];
  }

  function topicsOf(ctx) {
    var use = ctx || state.lastCtx || {};
    var status = use.status || (WIN.HX && WIN.HX.state && WIN.HX.state.status) || {};
    return status.topics || [];
  }
  function pickTopic(ctx) {
    var list = topicsOf(ctx);
    var id = WIN.HX && WIN.HX.state ? WIN.HX.state.topicId : null;
    if (id) {
      for (var i = 0; i < list.length; i++) { if (String(list[i].id) === String(id)) return list[i]; }
    }
    if (ctx && ctx.topic) return ctx.topic;
    return list[0] || null;
  }

  /* 读取真实面板当前选中的二级页签（.sub-tab.on），兜底第一个。 */
  function readActiveSp() {
    var p = panelEl();
    var on = p && p.querySelector(".sub-tab.on");
    var sp = on ? on.getAttribute("data-sp") : null;
    return inspireMeta(sp).sp;
  }

  /* 二级切换后回读真实面板状态，同步中栏标题与面包屑；不改动面板内部。 */
  function syncActiveSp() {
    state.activeSp = readActiveSp();
    renderThreadHead();
  }

  /* ------------------------------ 模块状态 ------------------------------ */
  var state = {
    filter: "all",
    mounted: false,
    lastCtx: null,
    activeSp: "sp-oneshot",
    panelHome: null,
    panelEl: null,
    bodyRoot: null,
    railSlot: null,
    railList: null,
    railFilterBar: null,
    threadHead: null,
    threadBody: null,
    stagePane: null,
    stageTopic: null,
    _drawStage: null
  };

  /* --------------------------- 真实面板挂载/归还 -------------------------- */
  function panelEl() {
    if (!state.panelEl) state.panelEl = byId("p-inspire");
    return state.panelEl;
  }

  /* 自有根节点：#hxThreadBody 被别的模块 innerHTML 清空后，下次进入可重建。 */
  function ensureBodyRoot() {
    var slot = byId("hxThreadBody");
    if (slot) state.threadBody = slot;
    if (!state.threadBody) return null;
    if (state.bodyRoot && state.bodyRoot.parentNode === state.threadBody) return state.bodyRoot;
    var root = DOC.createElement("div");
    root.className = "hx-collect-body";
    root.setAttribute("data-owner", "collect");
    state.threadBody.appendChild(root);
    state.bodyRoot = root;
    return root;
  }

  function activatePanel(p) {
    tryFn(function () {
      DOC.querySelectorAll(".panel").forEach(function (x) { x.classList.remove("on"); });
      p.classList.add("on");
    });
  }

  /* 幂等重挂：面板已在自有容器内则跳过；脱落到 fragment / 被移走 / 根节点被
     清空时，用缓存引用重新 append 回容器。不 clone、不重复 append。 */
  function remountPanel() {
    var p = panelEl();
    var root = ensureBodyRoot();
    if (!p || !root) return;
    if (!state.panelHome) state.panelHome = { parent: p.parentElement, next: p.nextSibling };
    if (p.parentElement !== root) root.appendChild(p);
    p.classList.add("hx-collect-panel");
    activatePanel(p);
    state.activeSp = readActiveSp();
  }

  function unmountPanel() {
    var p = panelEl();
    if (!p) return;
    var home = state.panelHome;
    p.classList.remove("on");
    p.style.display = "";
    if (home && home.parent) {
      if (home.next && home.next.parentNode === home.parent) {
        home.parent.insertBefore(p, home.next);
      } else {
        home.parent.appendChild(p);
      }
    }
  }

  /* ------------------------------ 左栏上下文 ----------------------------- */
  function buildRail(slot) {
    state.railSlot = slot;
    slot.innerHTML =
      '<div class="hx-col-ctx">' +
      '  <div class="hx-col-head"><span>采集记录</span></div>' +
      '  <div class="hx-col-filter" role="tablist" aria-label="采集状态筛选"></div>' +
      '  <div class="hx-col-list"></div>' +
      "</div>";
    state.railFilterBar = slot.querySelector(".hx-col-filter");
    state.railList = slot.querySelector(".hx-col-list");

    state.railFilterBar.addEventListener("click", function (ev) {
      var b = ev.target.closest ? ev.target.closest("[data-hx-filter]") : null;
      if (!b) return;
      state.filter = b.getAttribute("data-hx-filter");
      renderRail();
    });
    state.railList.addEventListener("click", function (ev) {
      var row = ev.target.closest ? ev.target.closest("[data-hx-topic]") : null;
      if (!row) return;
      var id = row.getAttribute("data-hx-topic");
      if (WIN.HX && WIN.HX.state) WIN.HX.state.topicId = id;
      state.stageTopic = null;
      renderRail();
      refreshStage();
    });
  }

  function renderRail(ctx) {
    var rail = byId("hxRailCtx");
    if (rail) state.railSlot = rail;
    if (state.railSlot && (!state.railList || state.railList.parentNode !== state.railSlot)) {
      buildRail(state.railSlot);
    }
    if (!state.railList) return;
    state.lastCtx = ctx || state.lastCtx;
    var all = topicsOf(state.lastCtx);
    var counts = { all: all.length, pending: 0, archived: 0 };
    FILTERS.forEach(function (f) {
      if (f.key !== "all") counts[f.key] = all.filter(f.match).length;
    });
    var activeId = WIN.HX && WIN.HX.state ? WIN.HX.state.topicId : null;

    var chips = FILTERS.map(function (f) {
      var on = state.filter === f.key ? " is-active" : "";
      return '<button type="button" class="hx-col-chip' + on + '" data-hx-filter="' + f.key + '">' +
        esc(f.label) + " <b>" + (counts[f.key] || 0) + "</b></button>";
    }).join("");
    state.railFilterBar.innerHTML = chips;

    var f = FILTERS.filter(function (x) { return x.key === state.filter; })[0] || FILTERS[0];
    var list = all.filter(f.match).slice(0, 500);

    if (!list.length) {
      state.railList.innerHTML = '<div class="hx-col-empty">当前筛选条件下暂无采集记录，可在中栏抓取热榜或粘贴链接。</div>';
      return;
    }

    var html = list.map(function (t) {
      var on = String(t.id) === String(activeId) ? " is-active" : "";
      var meta = sourceLabel(t.source) + " · " + esc(statusLabel(t.status));
      if (t.matched) meta += " · 命中关键词";
      var reason = trim(t.reason || "", 16);
      if (reason) meta += " · " + esc(reason);
      return '<button type="button" class="hx-col-row' + on + '" data-hx-topic="' + esc(t.id) + '">' +
        '<span class="hx-col-thumb ' + thumbClass(t.source) + '">' + esc(trim(sourceLabel(t.source), 4)) + "</span>" +
        '<span class="hx-col-main">' +
          '<span class="hx-col-title">' + esc(trim(t.title || "未命名选题", 22)) + "</span>" +
          '<span class="hx-col-meta">' + meta + "</span>" +
        "</span>" +
        '<span class="hx-col-more">' + ico("arrow") + "</span>" +
      "</button>";
    }).join("");
    state.railList.innerHTML = html;
  }

  /* ------------------------------ 中栏工作台 ----------------------------- */
  function renderThreadHead(ctx) {
    var head = byId("hxThreadHead");
    if (head) state.threadHead = head;
    if (!state.threadHead) return;
    state.lastCtx = ctx || state.lastCtx;
    var all = topicsOf(state.lastCtx);
    var meta = inspireMeta(state.activeSp);
    var canStage = WIN.HX && (typeof WIN.HX.openStage === "function" || typeof WIN.HX.closeStage === "function");
    var toggleStage = canStage
      ? '<button type="button" class="hx-icon-btn" data-tip="展开 / 收起分析" data-hx-act="stage">' + ico("panel") + "</button>"
      : "";
    state.threadHead.innerHTML =
      '<div class="hx-thread-head">' +
        '<div class="hx-thread-title">' +
          '<div class="hx-crumb">采集工作台 <svg class="hx-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9 6l6 6-6 6"/></svg> ' + esc(meta.label) + "</div>" +
          '<div class="hx-title-line"><h1>' + esc(meta.label) + "</h1>" +
          '<span class="hx-state-pill static">在库 ' + all.length + " 条</span></div>" +
        "</div>" +
        '<div class="hx-thread-actions">' + toggleStage + "</div>" +
      "</div>";

    var stageBtn = state.threadHead.querySelector("[data-hx-act='stage']");
    if (stageBtn) {
      stageBtn.onclick = function () {
        tryFn(function () {
          var open = !(WIN.HX.state && WIN.HX.state.stageOpen);
          if (open && typeof WIN.HX.openStage === "function") WIN.HX.openStage();
          if (!open && typeof WIN.HX.closeStage === "function") WIN.HX.closeStage();
        });
      };
    }
  }

  function buildThreadHead(el, ctx) {
    state.threadHead = el;
    renderThreadHead(ctx);
  }

  function buildThreadBody(el, ctx) {
    state.threadBody = el;
    remountPanel();
    syncActiveSp();
  }

  /* ------------------------------ 右栏：采集分析 -------------------------- */
  function renderSourcePane(t) {
    if (!t) {
      return '<div class="hx-analysis-empty"><div class="hx-analysis-empty-ico">' + ico("doc") + "</div>" +
        "<b>暂未选中话题</b><span>在左栏点击一条采集记录，这里展示原文与拆解摘要。</span></div>";
    }
    var body = trim(t.content || "", 600);
    var bodyHtml = body
      ? '<div class="hx-source-text"><p>' + esc(body).replace(/\n/g, "</p><p>") + "</p></div>"
      : '<div class="hx-analysis-empty"><b>原文快照尚未入库</b><span>该话题仅保存了标题与抓取摘要，正文需要在中栏完成链接提取后回看。</span></div>';
    var reason = t.reason ? esc(trim(t.reason, 60)) : "暂无热度 / 排名信息";
    var matchedTag = t.matched ? '<span class="hx-source-tag">命中关键词</span>' : "";
    return (
      '<div class="hx-source-head">' +
        '<div class="hx-source-badges"><span class="hx-source-logo ' + thumbClass(t.source) + '">' + esc(sourceLabel(t.source)) + "</span>" +
        '<span class="hx-source-type">' + esc(statusLabel(t.status)) + "</span>" + matchedTag + "</div>" +
        '<h2 class="hx-source-title">' + esc(trim(t.title || "未命名选题", 60)) + "</h2>" +
        '<div class="hx-source-byline"><span class="hx-source-avatar">' + esc(trim(sourceLabel(t.source), 1)) + "</span>" +
        "<div><b>" + reason + "</b><span>来源：" + esc(sourceLabel(t.source)) + "</span></div></div>" +
      "</div>" + bodyHtml +
      '<div class="hx-source-stats"><span><b>' + esc(statusLabel(t.status)) + "</b>状态</span>" +
      "<span><b>" + (t.matched ? "命中" : "未命中") + "</b>关键词</span></div>"
    );
  }

  function renderGenePane() {
    return '<div class="hx-analysis-empty"><div class="hx-analysis-empty-ico">' + ico("sparkles") + "</div>" +
      "<b>爆款基因拆解 · 未接入</b><span>当前话题尚未生成结构化基因分析（钩子 / 结构 / 情绪触发）。拆解任务完成后，这里会展示真实拆解结果。</span></div>";
  }

  function renderMediaPane() {
    return '<div class="hx-analysis-empty"><div class="hx-analysis-empty-ico">' + ico("layers") + "</div>" +
      "<b>提取素材 · 未接入</b><span>封面原图、正文文件与互动数据清单待采集入库后生成，当前不展示占位素材。</span></div>";
  }

  function buildStage(pane) {
    state.stagePane = pane;
    pane.innerHTML =
      '<div class="hx-analysis-tabs" role="tablist">' +
        '<button type="button" class="hx-analysis-tab is-active" data-hx-pane="source">原文</button>' +
        '<button type="button" class="hx-analysis-tab" data-hx-pane="gene">爆款基因</button>' +
        '<button type="button" class="hx-analysis-tab" data-hx-pane="media">素材</button>' +
      "</div>" +
      '<div class="hx-analysis-body"></div>';

    var body = pane.querySelector(".hx-analysis-body");
    var tabs = pane.querySelectorAll(".hx-analysis-tab");
    var current = "source";

    function draw() {
      tabs.forEach(function (b) { b.classList.toggle("is-active", b.getAttribute("data-hx-pane") === current); });
      var t = state.stageTopic;
      if (current === "source") body.innerHTML = renderSourcePane(t);
      else if (current === "gene") body.innerHTML = renderGenePane();
      else body.innerHTML = renderMediaPane();
    }
    pane.querySelector(".hx-analysis-tabs").addEventListener("click", function (ev) {
      var b = ev.target.closest ? ev.target.closest("[data-hx-pane]") : null;
      if (!b) return;
      current = b.getAttribute("data-hx-pane");
      draw();
    });
    state._drawStage = draw;
    draw();
  }

  function refreshStage(ctx) {
    if (!state.stagePane) return;
    state.lastCtx = ctx || state.lastCtx;
    state.stageTopic = pickTopic(state.lastCtx);
    if (typeof state._drawStage === "function") state._drawStage();
  }

  /* ------------------------------ 生命周期 ------------------------------ */
  function mountAll() {
    if (!state.mounted) state.mounted = true;
    remountPanel();
  }
  function cleanup() {
    if (!state.mounted) return;
    state.mounted = false;
    unmountPanel();
    /* 只移除自己创建的根节点，不清空整个插槽。 */
    if (state.bodyRoot && state.bodyRoot.parentNode) {
      state.bodyRoot.parentNode.removeChild(state.bodyRoot);
    }
    state.bodyRoot = null;
  }

  function register() {
    if (!WIN.HX) return;

    if (typeof WIN.HX.registerRailCtx === "function") {
      WIN.HX.registerRailCtx("collect", function (slot, ctx) {
        buildRail(slot);
        renderRail(ctx);
      });
    }

    if (typeof WIN.HX.registerThread === "function") {
      WIN.HX.registerThread("collect", {
        head: function (el, ctx) { buildThreadHead(el, ctx); },
        body: function (el, ctx) { buildThreadBody(el, ctx); },
        refresh: function (ctx) {
          renderRail(ctx);
          renderThreadHead(ctx);
          refreshStage(ctx);
        }
      });
    }

    if (typeof WIN.HX.registerStageTab === "function") {
      WIN.HX.registerStageTab("collect", {
        key: "analysis",
        title: "采集分析",
        count: function (ctx) { return topicsOf(ctx || {}).length; },
        mount: function (pane, ctx) { buildStage(pane); refreshStage(ctx); },
        refresh: function (pane, ctx) { state.stagePane = pane; refreshStage(ctx); }
      });
    }

    if (typeof WIN.HX.on === "function") {
      WIN.HX.on("workspace", function (ctx) {
        var ws = ctx && ctx.state && ctx.state.workspace;
        if (ws === "collect") { mountAll(ctx); } else { cleanup(); }
      });
      WIN.HX.on("state", function (ctx) {
        if (ctx && ctx.state && ctx.state.workspace !== "collect") return;
        remountPanel();
        state.activeSp = readActiveSp();
        renderRail(ctx);
        renderThreadHead(ctx);
        refreshStage(ctx);
      });
      WIN.HX.on("drafts", function (ctx) {
        if (ctx && ctx.state && ctx.state.workspace !== "collect") return;
        remountPanel();
        refreshStage(ctx);
      });
    }

    /* 真实面板内二级页签点击后（既有 onclick 已切换视图），回读选中态同步中栏。 */
    DOC.addEventListener("click", function (ev) {
      var tab = ev.target && ev.target.closest ? ev.target.closest("#p-inspire .sub-tab") : null;
      if (!tab) return;
      tryFn(function () { syncActiveSp(); });
    });
  }

  /* core 在 DOMContentLoaded 才 boot；注册本身提前完成。HX 若稍后就绪，短轮询兜底。 */
  if (WIN.HX) {
    register();
  } else {
    var tries = 0;
    var timer = setInterval(function () {
      tries += 1;
      if (WIN.HX) { clearInterval(timer); register(); }
      else if (tries > 40) { clearInterval(timer); }
    }, 50);
  }
})();
