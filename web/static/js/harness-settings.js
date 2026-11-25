/* SPDX-License-Identifier: BUSL-1.1 */
/* ==========================================================================
   Harness · 系统设置（D 模块）
   --------------------------------------------------------------------------
   职责边界（严格）：
     1. 左栏设置导航：分组项全部来自真实 #p-console 的子视图；原型有、
        系统没有的分组标「未接入」，不伪造开关 / 滑块；
     2. 中栏：把真实 #p-console 面板重排进设置工作区，保留全部真实控件
        与 onclick 链路；未接入分组只显示说明空态；
     3. 右栏：注册「配置检查」页签，用真实 /api/status.capabilities 展示
        文本 / 图像 / 视频三类引擎的 provider、model 与可用状态。
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
    film: '<rect x="3.5" y="4.5" width="17" height="15" rx="2.2"/><path d="M8 4.5v15M16 4.5v15M3.5 12h17"/>',
    gear: '<path d="M4 7.5h8M16.5 7.5H20M4 16.5h3.5M12 16.5h8"/><circle cx="14.2" cy="7.5" r="2.3"/><circle cx="9.8" cy="16.5" r="2.3"/>',
    doc: '<path d="M6.5 3.5h7l4.5 4.5v13h-11.5z"/><path d="M13.5 3.5V8h4.5M9 12.5h6M9 16h4"/>'
  };
  function ico(name, cls) {
    if (WIN.HX && typeof WIN.HX.ico === "function") {
      var h = WIN.HX.ico(name, cls || "hx-ico");
      if (h) return h;
    }
    var d = ICON_PATHS[name] || ICON_PATHS.doc;
    return '<svg class="' + (cls || "hx-ico") + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + d + "</svg>";
  }

  /* 服务商 id → 友好名（仅做展示兜底；未收录时回退原始 id）。 */
  var PROVIDER_NAME = {
    yimu_official: "一幕·YIMU 官方",
    deepseek: "DeepSeek",
    openai: "OpenAI",
    xiaomi: "小米 MiMo",
    qwen: "通义千问",
    minimax: "MiniMax",
    zhipu: "智谱 GLM",
    doubao: "豆包",
    custom: "自定义聚合网关"
  };
  function providerName(id) {
    if (!id) return "";
    return PROVIDER_NAME[id] || String(id);
  }

  /* --------------------- 分组：原型分组 ↔ 真实 console 子视图 ---------------- */
  /* connected=true 时 tab 指向 #p-console 内真实子视图；false 表示原型有、
     系统未提供对应设置入口，只渲染「未接入」说明，不生成假控件。 */
  var GROUPS = [
    { key: "model", label: "模型与密钥", ico: "sparkles", tab: "sp-settings", connected: true,
      hint: "模型服务 / API Key / 默认写作风格" },
    { key: "accounts", label: "发布账号", ico: "globe", tab: null, connected: false,
      hint: "公众号 / 小红书 / 头条 / 知乎账号授权" },
    { key: "quality", label: "内容与质量", ico: "bolt", tab: "sp-skills", connected: true,
      hint: "技能库 / 名家文风 / 质量考核" },
    { key: "team", label: "团队与权限", ico: "user", tab: "sp-user-admin", connected: true,
      hint: "用户与会员管理 / 角色额度" },
    { key: "security", label: "安全与合规", ico: "lock", tab: "sp-health", connected: true,
      hint: "服务健康自检 / 内容安全闸" },
    { key: "appearance", label: "外观与快捷键", ico: "panel", tab: null, connected: false,
      hint: "主题切换 / 快捷键清单" }
  ];
  /* #p-console 内真实存在、但原型六分组未单列的子视图，一并挂进左栏。 */
  var EXTRA = [
    { tab: "sp-ticket", label: "每日工单自动化", ico: "clock" },
    { tab: "sp-agent-config", label: "Agent 配置", ico: "sparkles" },
    { tab: "sp-gateway", label: "API 网关服务", ico: "globe" },
    { tab: "sp-video-config", label: "视频合成配置", ico: "film" }
  ];
  function statusOf(ctx) {
    var use = ctx || state.lastCtx || {};
    return use.status || (WIN.HX && WIN.HX.state && WIN.HX.state.status) || {};
  }
  function capsOf(ctx) { return statusOf(ctx).capabilities || {}; }

  /* 真实面板 #p-console 的 8 个二级入口 → 左栏分组 / 中栏标题映射。
     connected=false 的分组只渲染「未接入」占位，不生成假控件。 */
  var TAB_META = {};
  GROUPS.forEach(function (g) {
    if (g.tab) TAB_META[g.tab] = { label: g.label, connected: g.connected, groupKey: g.key };
  });
  EXTRA.forEach(function (e) {
    TAB_META[e.tab] = { label: e.label, connected: true, groupKey: "extra:" + e.tab };
  });

  /* ------------------------------ 模块状态 ------------------------------ */
  var state = {
    mounted: false,
    lastCtx: null,
    panelHome: null,
    panelEl: null,
    bodyRoot: null,
    activeGroup: null,
    railSlot: null,
    threadHead: null,
    threadBody: null,
    placeholder: null,
    stagePane: null,
    _drawStage: null
  };

  /* --------------------------- 真实面板挂载/归还 -------------------------- */
  function panelEl() {
    if (!state.panelEl) state.panelEl = byId("p-console");
    return state.panelEl;
  }

  /* 自有根节点：#hxThreadBody 被别的模块 innerHTML 清空后，下次进入可重建。 */
  function ensureBodyRoot() {
    var slot = byId("hxThreadBody");
    if (slot) state.threadBody = slot;
    if (!state.threadBody) return null;
    if (state.bodyRoot && state.bodyRoot.parentNode === state.threadBody) return state.bodyRoot;
    var root = DOC.createElement("div");
    root.className = "hx-settings-body";
    root.setAttribute("data-owner", "settings");
    state.threadBody.appendChild(root);
    state.bodyRoot = root;
    return root;
  }

  function ensurePlaceholder() {
    var root = ensureBodyRoot();
    if (!root) return null;
    if (!state.placeholder || state.placeholder.parentNode !== root) {
      state.placeholder = DOC.createElement("div");
      state.placeholder.className = "hx-setting-placeholder";
      root.appendChild(state.placeholder);
    }
    return state.placeholder;
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
    p.classList.add("hx-settings-panel");
    activatePanel(p);
    ensurePlaceholder();
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

  /* ------------------------------ 左栏导航 ------------------------------- */
  function buildRail(slot) {
    state.railSlot = slot;
    slot.innerHTML =
      '<div class="hx-set-ctx">' +
      '  <div class="hx-set-head"><span>设置导航</span></div>' +
      '  <div class="hx-set-nav"></div>' +
      '  <div class="hx-set-extra-label">系统其他配置</div>' +
      '  <div class="hx-set-extra"></div>' +
      '  <div class="hx-set-hint">设置按工作区生效，修改后保存即同步到所有任务。</div>' +
      "</div>";
    renderRail();

    slot.querySelector(".hx-set-nav").addEventListener("click", function (ev) {
      var b = ev.target.closest ? ev.target.closest("[data-hx-group]") : null;
      if (!b) return;
      activateGroup(b.getAttribute("data-hx-group"));
    });
    slot.querySelector(".hx-set-extra").addEventListener("click", function (ev) {
      var b = ev.target.closest ? ev.target.closest("[data-hx-tab]") : null;
      if (!b) return;
      activateTab(b.getAttribute("data-hx-tab"));
    });
  }

  function activateGroup(key) {
    var g = GROUPS.filter(function (x) { return x.key === key; })[0];
    if (!g) return;
    if (g.tab) {
      tryFn(function () { if (WIN.switchSubTab) WIN.switchSubTab("console", g.tab); });
      syncFromPanel();
    } else {
      /* 未接入分组：真实面板没有对应入口，只展示占位空态，不按面板回读覆盖。 */
      state.activeGroup = key;
      renderRail();
      renderHead();
      syncPlaceholder();
    }
  }

  function activateTab(tab) {
    tryFn(function () { if (WIN.switchSubTab) WIN.switchSubTab("console", tab); });
    syncFromPanel();
  }

  function currentGroup() {
    return GROUPS.filter(function (x) { return x.key === state.activeGroup; })[0] || null;
  }

  /* 读取真实面板当前选中的二级页签（.sub-tab.on）。 */
  function readActiveTab() {
    var p = panelEl();
    var on = p && p.querySelector(".sub-tab.on");
    return on ? on.getAttribute("data-sp") : null;
  }

  /* 回读真实面板选中态，同步左栏高亮、中栏标题与占位显隐。 */
  function syncFromPanel() {
    var tab = readActiveTab();
    var meta = TAB_META[tab];
    state.activeGroup = meta ? meta.groupKey : null;
    renderRail();
    renderHead();
    syncPlaceholder();
  }

  function renderRail() {
    var rail = byId("hxRailCtx");
    if (rail) state.railSlot = rail;
    if (state.railSlot && (!state.railSlot.querySelector(".hx-set-nav"))) {
      buildRail(state.railSlot);
    }
    if (!state.railSlot) return;
    var nav = state.railSlot.querySelector(".hx-set-nav");
    nav.innerHTML = GROUPS.map(function (g) {
      var on = state.activeGroup === g.key ? " is-active" : "";
      var dot = g.connected ? '<span class="hx-set-dot ok"></span>' : '<span class="hx-set-dot warn"></span>';
      return '<button type="button" class="hx-set-item' + on + '" data-hx-group="' + g.key + '">' +
        ico(g.ico) + "<span>" + esc(g.label) + "</span>" + dot + "</button>";
    }).join("");

    var extra = state.railSlot.querySelector(".hx-set-extra");
    extra.innerHTML = EXTRA.map(function (e) {
      var on = state.activeGroup === "extra:" + e.tab ? " is-active" : "";
      return '<button type="button" class="hx-set-item hx-set-extra-item' + on + '" data-hx-tab="' + e.tab + '">' +
        ico(e.ico) + "<span>" + esc(e.label) + "</span><span class='hx-set-dot ok'></span></button>";
    }).join("");
  }

  /* ------------------------------ 中栏 ---------------------------------- */
  function renderHead() {
    var head = byId("hxThreadHead");
    if (head) state.threadHead = head;
    if (!state.threadHead) return;
    var g = currentGroup();
    var meta = TAB_META[readActiveTab()];
    var title, connected;
    if (g) { title = g.label; connected = g.connected; }
    else if (meta) { title = meta.label; connected = true; }
    else { title = "系统设置"; connected = true; }
    var pill = connected
      ? '<span class="hx-state-pill static good"><i></i>配置可用</span>'
      : '<span class="hx-state-pill static danger"><i></i>未接入</span>';
    var refreshBtn = WIN.HX && typeof WIN.HX.refresh === "function"
      ? '<button type="button" class="hx-icon-btn" data-tip="重新加载状态" data-hx-act="refresh">' + ico("refresh") + "</button>"
      : "";
    state.threadHead.innerHTML =
      '<div class="hx-thread-head">' +
        '<div class="hx-thread-title">' +
          '<div class="hx-crumb">系统设置 <svg class="hx-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9 6l6 6-6 6"/></svg> 工作区配置</div>' +
          '<div class="hx-title-line"><h1>' + esc(title) + "</h1>" + pill + "</div>" +
        "</div>" +
        '<div class="hx-thread-actions">' + refreshBtn + "</div>" +
      "</div>";
    var rb = state.threadHead.querySelector("[data-hx-act='refresh']");
    if (rb) rb.onclick = function () { tryFn(function () { WIN.HX.refresh(); }); };
  }

  function syncPlaceholder() {
    var p = panelEl();
    var g = currentGroup();
    var ph = ensurePlaceholder();
    if (!ph) return;
    state.placeholder = ph;
    var showPlaceholder = !!(g && !g.connected);
    ph.style.display = showPlaceholder ? "" : "none";
    if (p) p.style.display = showPlaceholder ? "none" : "";
    if (showPlaceholder) {
      ph.innerHTML =
        '<div class="hx-setting-empty"><div class="hx-setting-empty-ico">' + ico(g.ico) + "</div>" +
        "<b>" + esc(g.label) + " · 未接入</b>" +
        "<span>" + esc(g.hint) + "。当前系统设置面板（#p-console）未提供该入口，此处不生成占位开关或假控件；接入后将在此展示真实配置。</span></div>";
    }
  }

  function buildThreadBody(el) {
    state.threadBody = el;
    remountPanel();
    syncFromPanel();
  }

  /* --------------------------- 右栏：配置检查 ---------------------------- */
  var ENGINE_ROWS = [
    { cat: "text", label: "文本引擎", ico: "sparkles", desc: "驱动 Agent 与成稿的默认大模型" },
    { cat: "image", label: "图像引擎", ico: "image", desc: "配图 / 封面 / 卡片出图模型" },
    { cat: "video", label: "视频引擎", ico: "film", desc: "图文转视频的视频生成模型" }
  ];

  function capabilityRow(row, cap, gateway) {
    var entry = cap && typeof cap === "object" ? cap : {};
    var provider = entry.provider_id || "";
    var model = entry.model || entry.model_tag || "";
    var configured = !!(provider && model);
    var ok = configured;
    var stateCls = "ok";
    var stateText = "正常";
    var sub;

    if (configured) {
      sub = esc(providerName(provider)) + (model ? " · " + esc(model) : "");
      if (row.cat === "text" && gateway && gateway.llm_ok === false) {
        ok = false; stateCls = "warn"; stateText = "待验证";
        sub += " · 通道未通过自检";
      }
    } else {
      stateCls = "warn"; stateText = "未配置";
      sub = "尚未配置该能力线模型，可在「模型与密钥」中接入";
    }
    return '<div class="hx-config-row' + (ok ? "" : " warn") + '">' +
      '<span class="hx-config-icon ' + (ok ? "ok" : "warn") + '">' + ico(row.ico) + "</span>" +
      "<div><b>" + esc(row.label) + "</b><span>" + sub + "</span></div>" +
      '<span class="hx-config-state ' + stateCls + '">' + stateText + "</span></div>";
  }

  function buildStage(pane, ctx) {
    state.stagePane = pane;
    pane.innerHTML =
      '<div class="hx-config-body">' +
      '  <div class="hx-config-health"></div>' +
      '  <div class="hx-config-list"></div>' +
      '  <div class="hx-config-tip"></div>' +
      '  <button type="button" class="hx-config-run" data-hx-act="refresh">' + ico("refresh") + "重新检测</button>" +
      '  <div class="hx-config-foot"><span>检查只读，不会修改配置</span></div>' +
      "</div>";
    pane.querySelector("[data-hx-act='refresh']").onclick = function () {
      tryFn(function () { if (WIN.HX && WIN.HX.refresh) WIN.HX.refresh(); });
    };
    drawStage(ctx);
    state._drawStage = drawStage;
  }

  function drawStage(ctx) {
    if (!state.stagePane) return;
    state.lastCtx = ctx || state.lastCtx;
    var status = statusOf(state.lastCtx);
    var caps = capsOf(state.lastCtx);
    var gateway = status.gateway || {};

    var rowsHtml = ENGINE_ROWS.map(function (row) {
      return capabilityRow(row, caps[row.cat], gateway);
    }).join("");
    /* 原型有、但 /api/status 未回传的能力线：如实标未接入，不编账号 / 席位数据。 */
    rowsHtml +=
      '<div class="hx-config-row warn">' +
        '<span class="hx-config-icon warn">' + ico("globe") + "</span>" +
        "<div><b>发布账号</b><span>接口未回传账号授权状态，暂无真实数据</span></div>" +
        '<span class="hx-config-state warn">未接入</span></div>' +
      '<div class="hx-config-row warn">' +
        '<span class="hx-config-icon warn">' + ico("user") + "</span>" +
        "<div><b>团队席位</b><span>接口未回传席位 / 成员数据，暂无真实数据</span></div>" +
        '<span class="hx-config-state warn">未接入</span></div>';

    var ready = ENGINE_ROWS.filter(function (row) {
      var e = caps[row.cat] || {};
      return !!(e.provider_id && e.model);
    }).length;
    var total = ENGINE_ROWS.length;
    var ringPct = total ? Math.round((ready / total) * 100) : 0;
    var healthTitle = ready === total ? "三类引擎均已就绪" : "部分引擎尚未配置";
    var healthDesc = ready + " / " + total + " 条能力线解析到可用模型；未配置项请在模型与密钥中接入。";

    state.stagePane.querySelector(".hx-config-health").innerHTML =
      '<div class="hx-config-ring" style="--hx-ring:' + ringPct + '%"><b>' + ringPct + "</b><span>健康度</span></div>" +
      "<div><h3>" + esc(healthTitle) + "</h3><p>" + esc(healthDesc) + "</p></div>";
    state.stagePane.querySelector(".hx-config-list").innerHTML = rowsHtml;

    var missing = ENGINE_ROWS.filter(function (row) {
      var e = caps[row.cat] || {};
      return !(e.provider_id && e.model);
    });
    var tip = state.stagePane.querySelector(".hx-config-tip");
    if (missing.length) {
      tip.innerHTML = ico("lock") + "<div><b>尚未配置：" + missing.map(function (r) { return esc(r.label); }).join("、") + "</b>" +
        "<span>未配置的能力线会走免 Key 保底或提示接入，不会影响已配置通道。</span></div>";
      tip.style.display = "";
    } else {
      tip.style.display = "none";
    }
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
    /* 只移除自己创建的根节点（含占位 DOM），不清空整个插槽。 */
    if (state.bodyRoot && state.bodyRoot.parentNode) {
      state.bodyRoot.parentNode.removeChild(state.bodyRoot);
    }
    state.bodyRoot = null;
    state.placeholder = null;
  }

  function register() {
    if (!WIN.HX) return;

    if (typeof WIN.HX.registerRailCtx === "function") {
      WIN.HX.registerRailCtx("settings", function (slot) { buildRail(slot); });
    }

    if (typeof WIN.HX.registerThread === "function") {
      WIN.HX.registerThread("settings", {
        head: function (el) { state.threadHead = el; renderHead(); },
        body: function (el) { buildThreadBody(el); },
        refresh: function (ctx) { renderHead(); drawStage(ctx); }
      });
    }

    if (typeof WIN.HX.registerStageTab === "function") {
      WIN.HX.registerStageTab("settings", {
        key: "checks",
        title: "配置检查",
        count: function () { return 0; },
        mount: function (pane, ctx) { buildStage(pane, ctx); },
        refresh: function (pane, ctx) { state.stagePane = pane; drawStage(ctx); }
      });
    }

    if (typeof WIN.HX.on === "function") {
      WIN.HX.on("workspace", function (ctx) {
        var ws = ctx && ctx.state && ctx.state.workspace;
        if (ws === "settings") { mountAll(); } else { cleanup(); }
      });
      WIN.HX.on("state", function (ctx) {
        if (ctx && ctx.state && ctx.state.workspace !== "settings") return;
        remountPanel();
        syncFromPanel();
        drawStage(ctx);
      });
      WIN.HX.on("drafts", function (ctx) {
        if (ctx && ctx.state && ctx.state.workspace !== "settings") return;
        remountPanel();
        drawStage(ctx);
      });
    }

    /* 真实面板内二级页签点击后（既有 onclick 已切换视图），回读选中态同步左栏与中栏。 */
    DOC.addEventListener("click", function (ev) {
      var tab = ev.target && ev.target.closest ? ev.target.closest("#p-console .sub-tab") : null;
      if (!tab) return;
      tryFn(function () { syncFromPanel(); });
    });
  }

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
