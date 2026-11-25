/* SPDX-License-Identifier: BUSL-1.1 */
/* ==========================================================================
   Harness 外壳 · 右栏舞台（C 模块）
   --------------------------------------------------------------------------
   单主模式：core（harness-core.js）拥有 #hxStage 框架、#hxStageTabs 页签条
   与 #hxStageBody；本模块只通过 HX.registerStageTab 注册「资产 / 浏览器 /
   预览」三个页签，并在 mount(pane, ctx) / refresh(pane, ctx) 中向 core
   给出的空 pane 渲染内容。
     - 不自建页签条、不自管切换、不覆盖其他模块（采集 / 设置）的注册；
     - 资产 pane：既有 #assetsPanel 迁出舞台到持久隐藏持有节点（业务引用与
       shell 绑定链路保留）；pane 内用真实接口渲染成稿 / 图片 / 数据三组；
     - 浏览器 pane：按草稿来源 URL 尝试内嵌；站点禁止 iframe 时降级为
       明确的「外部打开」+ 原因说明，不静默失败、不白屏；
     - 预览 pane：用后端真实排版（/api/drafts/{id}/raw/{plat}）渲染当前
       草稿，不复制假 HTML、不写死示例文章；
     - tasks / content / collect / settings 四个工作区均注册三页签，与
       D 模块的「采集分析」「配置检查」共存。
   隔离：仅在 body[data-shell="harness"] 下工作；classic / v2 零副作用。
   纯 ES5 + IIFE，无构建步骤。
   ========================================================================== */
(function () {
  'use strict';

  var DOC = document;
  var WIN = window;

  function harnessOn() {
    return !!(DOC.body && DOC.body.getAttribute('data-shell') === 'harness');
  }
  if (!harnessOn()) return;

  /* ------------------------------ 小工具 ------------------------------ */

  function byId(id) { return DOC.getElementById(id); }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function trim(s, n) {
    s = String(s == null ? '' : s);
    return s.length > n ? s.slice(0, n - 1) + '…' : s;
  }

  function fmtTime(v) {
    if (!v) return '';
    var d;
    if (typeof v === 'number') d = new Date(v < 1e12 ? v * 1000 : v);
    else d = new Date(String(v).replace(' ', 'T'));
    if (isNaN(d.getTime())) return String(v).slice(5, 16).replace('T', ' ');
    var p = function (x) { return x < 10 ? '0' + x : '' + x; };
    return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  }

  function ico(name, cls) {
    if (WIN.HX && typeof WIN.HX.ico === 'function') {
      try { return WIN.HX.ico(name, cls || 'hx-ico'); } catch (e) { /* 落到本地 symbol */ }
    }
    return '<svg class="hx-ico ' + (cls || '') + '" viewBox="0 0 24 24" fill="none" ' +
      'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<use href="#hx-i-' + name + '"></use></svg>';
  }

  function api(path, opts) {
    if (WIN.HX && typeof WIN.HX.api === 'function') {
      try { return WIN.HX.api(path, opts); } catch (e) { /* 落到本地 fetch */ }
    }
    return fetch(path, {
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json' }
    }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).catch(function () { return null; });
  }

  function toast(msg) {
    if (WIN.HX && typeof WIN.HX.toast === 'function') {
      try { WIN.HX.toast(msg); return; } catch (e) {}
    }
    if (typeof WIN.toast === 'function') { try { WIN.toast(msg); } catch (e) {} }
  }

  function tryFn(fn) { try { fn(); } catch (e) { /* 模块异常不阻断业务 */ } }

  var PLAT_LABEL = { wechat_mp: '公众号', xhs: '小红书', toutiao: '头条', douyin: '抖音' };
  function platLabel(p) { return PLAT_LABEL[p] || p || '未知来源'; }

  /* ------------------------------ 上下文解析 ------------------------------ */
  /* core 的 ctx.draft 是草稿 ID 字符串；草稿对象需在 ctx.drafts 里按 id 匹配。
     真实草稿卡片由 workbench-shell 内部绑定，HX.state.draftId 不一定同步，
     因此提供 DOM 兜底：选中卡片 input[data-id] → 全局词法变量。 */

  function readActiveDraftId() {
    var on = DOC.querySelector('#draft-list-container .draft-card.on input[data-id]');
    if (on) return String(on.getAttribute('data-id'));
    try { if (typeof curDraft !== 'undefined' && curDraft) return String(curDraft); } catch (e) {}
    try { if (typeof currentLiteDraftId !== 'undefined' && currentLiteDraftId) return String(currentLiteDraftId); } catch (e) {}
    return null;
  }

  function ctxDraftId(ctx) {
    if (ctx && ctx.draft) return String(ctx.draft);
    if (ctx && ctx.state && ctx.state.draftId) return String(ctx.state.draftId);
    if (WIN.HX && WIN.HX.state && WIN.HX.state.draftId) return String(WIN.HX.state.draftId);
    return readActiveDraftId();
  }

  function readDraftCards() {
    var out = [];
    var cards = DOC.querySelectorAll('#draft-list-container .draft-card');
    Array.prototype.forEach.call(cards, function (card) {
      var chk = card.querySelector('input[data-id]');
      var title = card.querySelector('.dc-title');
      if (chk) out.push({ id: String(chk.getAttribute('data-id')), title: title ? title.textContent.trim() : '未命名' });
    });
    return out;
  }

  function draftsOf(ctx) {
    if (ctx && Array.isArray(ctx.drafts) && ctx.drafts.length) return ctx.drafts;
    if (WIN.HX && WIN.HX.state && Array.isArray(WIN.HX.state.drafts) && WIN.HX.state.drafts.length) {
      return WIN.HX.state.drafts;
    }
    return readDraftCards();
  }

  function findDraft(ctx) {
    var id = ctxDraftId(ctx);
    if (!id) return null;
    var list = draftsOf(ctx);
    for (var i = 0; i < list.length; i++) {
      if (list[i] && String(list[i].id) === id) return list[i];
    }
    return null;
  }

  function localCtx() {
    if (WIN.HX && typeof WIN.HX._ctx === 'function') {
      try { return WIN.HX._ctx(); } catch (e) { /* 落到本地兜底 */ }
    }
    return {
      state: (WIN.HX && WIN.HX.state) || {},
      drafts: draftsOf(null),
      draft: ctxDraftId(null)
    };
  }

  /* ------------------------------ 空态 / 按钮片段 ------------------------------ */

  function emptyArt(icon) {
    return '<div class="hx-empty-art" aria-hidden="true">' +
      '<span class="hx-ea-base"></span>' +
      '<span class="hx-ea-card">' + ico(icon || 'layers') + '</span>' +
      '<span class="hx-ea-dot">' + ico('sparkles') + '</span>' +
    '</div>';
  }

  function emptyHTML(icon, title, desc, actionsHTML) {
    return '<div class="hx-stage-empty">' + emptyArt(icon) +
      '<h3 class="hx-empty-title">' + esc(title) + '</h3>' +
      '<p class="hx-empty-desc">' + esc(desc) + '</p>' +
      (actionsHTML ? '<div class="hx-empty-actions">' + actionsHTML + '</div>' : '') +
    '</div>';
  }

  function primaryBtn(act, icon, label) {
    return '<button type="button" class="hx-btn-primary" data-hx-act="' + act + '">' + ico(icon) + esc(label) + '</button>';
  }
  function ghostBtn(act, icon, label) {
    return '<button type="button" class="hx-btn-ghost" data-hx-act="' + act + '">' + ico(icon) + esc(label) + '</button>';
  }

  /* ============================== 资产 pane ============================== */
  /* core 的 renderStage() 每次都会清空 #hxStageBody 并重建 pane，迁入的既有
     #assetsTabs/#assetsBody 会随旧 pane 一起被销毁，因此本 pane 不依赖既有
     节点存活：
       - 既有 #assetsPanel 迁出舞台到持久隐藏持有节点：业务引用保留、
         workbench-shell 的事件绑定 / 取数链路不受影响，但不再以隐藏空壳
         占舞台布局；
       - pane 内由本模块用真实接口渲染：成稿（drafts）/ 图片（assets
         library）/ 数据（成稿汇总 + 后台任务），点击成稿走 HX.openDraft，
         点击图片走既有灯箱或外部新页打开。 */

  var AS = {
    tab: 'doc',
    drafts: [],
    imgs: [],
    imgTotal: 0,
    tasks: [],
    draftsLoaded: false,
    imgsLoaded: false,
    tasksLoaded: false,
    seq: 0
  };

  function relocateLegacyPanel() {
    var panel = byId('assetsPanel');
    if (!panel) return;
    var stage = byId('hxStage');
    if (!stage || panel.parentNode !== stage) return;
    var holder = byId('hxLegacyHolder');
    if (!holder) {
      holder = DOC.createElement('div');
      holder.id = 'hxLegacyHolder';
      holder.className = 'hx-legacy-holder';
      DOC.body.appendChild(holder);
    }
    holder.appendChild(panel);
  }

  function fmtSize(n) {
    n = Number(n) || 0;
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1024 / 1024).toFixed(1) + ' MB';
  }

  function assetLabel(name) {
    if (name === 'cover') return '封面';
    var m = /^sec-(\d+)$/.exec(name || '');
    if (m) return '配图 ' + (Number(m[1]) + 1);
    return name || '素材';
  }

  function syncDrafts(ctx) {
    var ds = draftsOf(ctx);
    if (ds && ds.length) AS.drafts = ds;
  }

  function loadAssetsData(ctx, seq, pane) {
    if (!AS.draftsLoaded) {
      var ds = draftsOf(ctx);
      if (ds && ds.length) { AS.drafts = ds; AS.draftsLoaded = true; }
    }
    var jobs = [];
    if (!AS.draftsLoaded) {
      jobs.push(api('/api/status').then(function (s) {
        if (s && Array.isArray(s.drafts)) { AS.drafts = s.drafts; AS.draftsLoaded = true; }
      }));
    }
    if (!AS.imgsLoaded) {
      jobs.push(api('/api/assets/library?per_page=200').then(function (r) {
        if (r && Array.isArray(r.assets)) {
          AS.imgs = r.assets;
          AS.imgTotal = Number(r.total || r.assets.length);
        }
        AS.imgsLoaded = true;
      }));
    }
    if (!AS.tasksLoaded) {
      jobs.push(api('/api/tasks').then(function (r) {
        if (r && Array.isArray(r.tasks)) AS.tasks = r.tasks;
        AS.tasksLoaded = true;
      }));
    }
    var done = function () { if (seq === AS.seq && pane.isConnected) renderAssets(pane, ctx); };
    if (jobs.length) Promise.all(jobs).then(done, done); else done();
  }

  function mountAssets(pane, ctx) {
    pane.setAttribute('data-key', 'assets');
    relocateLegacyPanel();
    pane.innerHTML =
      '<div class="hx-assets">' +
        '<div class="hx-assets-bar">' +
          '<div class="hx-assets-tabs" role="tablist">' +
            '<button type="button" class="hx-a-tab is-active" data-at="doc"><span>成稿</span><em class="hx-a-count" data-count="doc"></em></button>' +
            '<button type="button" class="hx-a-tab" data-at="img"><span>图片</span><em class="hx-a-count" data-count="img"></em></button>' +
            '<button type="button" class="hx-a-tab" data-at="data"><span>数据</span><em class="hx-a-count" data-count="data"></em></button>' +
          '</div>' +
          '<button type="button" class="hx-icon-btn" data-role="refresh" title="刷新资产" aria-label="刷新资产">' + ico('refresh') + '</button>' +
        '</div>' +
        '<div class="hx-assets-list" data-role="list"><div class="hx-preview-loading">正在读取资产…</div></div>' +
      '</div>';
    refreshAssets(pane, ctx);
  }

  function refreshAssets(pane, ctx) {
    relocateLegacyPanel();
    AS.seq += 1;
    var seq = AS.seq;
    syncDrafts(ctx);
    loadAssetsData(ctx, seq, pane);
  }

  function reloadAssets(pane, ctx) {
    AS.imgsLoaded = false;
    AS.tasksLoaded = false;
    AS.draftsLoaded = false;
    refreshAssets(pane, ctx);
  }

  function setSubCount(pane, key, n) {
    var em = pane.querySelector('[data-count="' + key + '"]');
    if (!em) return;
    em.textContent = n ? String(n) : '';
  }

  function syncStageBadge() {
    var btn = DOC.querySelector('#hxStageTabs [data-tab="assets"]');
    if (!btn) return;
    var em = btn.querySelector('.hx-tab-count');
    var n = AS.imgTotal || AS.imgs.length || AS.drafts.length;
    if (n) {
      if (!em) {
        em = DOC.createElement('em');
        em.className = 'hx-tab-count';
        btn.appendChild(em);
      }
      em.textContent = String(n);
    } else if (em) {
      em.textContent = '';
    }
  }

  function renderAssets(pane, ctx) {
    var list = pane.querySelector('[data-role="list"]');
    if (!list || !pane.isConnected) return;
    var tabs = pane.querySelectorAll('.hx-a-tab');
    for (var i = 0; i < tabs.length; i++) {
      tabs[i].classList.toggle('is-active', tabs[i].getAttribute('data-at') === AS.tab);
    }
    setSubCount(pane, 'doc', AS.drafts.length);
    setSubCount(pane, 'img', AS.imgTotal || AS.imgs.length);
    setSubCount(pane, 'data', AS.drafts.length + AS.tasks.length);
    syncStageBadge();
    if (AS.tab === 'img') renderImgList(list);
    else if (AS.tab === 'data') renderDataList(list);
    else renderDocList(list);
  }

  function draftScore(d) {
    return (d.score != null && d.score !== '') ? Math.round(Number(d.score)) : null;
  }

  function renderDocList(list) {
    var drafts = AS.drafts.slice().sort(function (a, b) {
      return Number(b.created_at || 0) - Number(a.created_at || 0);
    });
    if (!drafts.length) {
      list.innerHTML = emptyHTML('file', '稿库还没有成稿',
        '本次会话还没有产出成稿。去采集工作台选定选题，Agent 写完后成稿、配图会自动出现在这里。',
        primaryBtn('open-inspire', 'search', '去采集工作台') + ghostBtn('open-drafts', 'file', '查看稿件库'));
      return;
    }
    list.innerHTML = drafts.map(function (d) {
      var score = draftScore(d);
      var plats = (d.platforms || []).map(platLabel).join(' · ');
      var meta = trim([plats, d.imgs ? d.imgs + ' 图' : '', d.cards ? d.cards + ' 卡' : '', fmtTime(d.created_at)].filter(Boolean).join(' · '), 42);
      return '<button type="button" class="hx-a-row" data-act="pick" data-id="' + esc(d.id) + '" title="点击载入并预览成稿">' +
        '<span class="hx-a-score">' + (score == null ? '·' : score) + '</span>' +
        '<span class="hx-a-main"><b>' + esc(d.title || '未命名') + '</b><i>' + esc(meta) + '</i></span>' +
      '</button>';
    }).join('');
  }

  function renderImgList(list) {
    if (!AS.imgs.length) {
      list.innerHTML = emptyHTML('image', '暂无配图素材',
        '当前还没有生成或保存的配图；成稿生成封面与章节配图后会列在这里。');
      return;
    }
    var items = AS.imgs.slice(0, 120);
    list.innerHTML = '<div class="hx-a-grid">' + items.map(function (a) {
      var title = trim(a.draft_title || '未命名', 18);
      return '<button type="button" class="hx-a-img" data-act="zoom" data-url="' + esc(a.url) + '" ' +
        'data-name="' + esc(assetLabel(a.name)) + '" data-title="' + esc(title) + '" title="点击放大预览">' +
        '<img src="' + esc(a.url) + '" alt="' + esc(title) + '" loading="lazy">' +
        '<span class="hx-a-img-meta"><b>' + esc(title) + '</b>' +
          '<span class="hx-a-img-sub"><span class="hx-a-img-type">' + esc(assetLabel(a.name)) + '</span><i>' + fmtSize(a.size) + '</i></span>' +
        '</span>' +
      '</button>';
    }).join('') + '</div>' +
      (AS.imgs.length > 120 ? '<div class="hx-a-more">其余 ' + (AS.imgs.length - 120) + ' 条素材未展开</div>' : '');
  }

  function renderDataList(list) {
    var parts = [];
    if (AS.tasks && AS.tasks.length) {
      parts.push('<div class="hx-a-label">后台任务</div>' + AS.tasks.map(function (t) {
        var st = t.status || '—';
        return '<div class="hx-a-row hx-a-data"><span class="hx-a-status">' + esc(st) + '</span>' +
          '<span class="hx-a-main"><b>' + esc(trim(t.id || t.title || '任务', 30)) + '</b><i>' + esc(t.title || '') + '</i></span></div>';
      }).join(''));
    }
    if (AS.drafts.length) {
      parts.push('<div class="hx-a-label">成稿汇总</div>' + AS.drafts.slice(0, 30).map(function (d) {
        var score = draftScore(d);
        var meta = (d.imgs || 0) + ' 图 · ' + (d.cards || 0) + ' 卡 · ' + esc(d.status || '');
        return '<div class="hx-a-row hx-a-data" data-act="pick" data-id="' + esc(d.id) + '">' +
          '<span class="hx-a-score">' + (score == null ? '·' : score) + '</span>' +
          '<span class="hx-a-main"><b>' + esc(trim(d.title || '未命名', 30)) + '</b><i>' + esc(meta) + '</i></span>' +
        '</div>';
      }).join(''));
    }
    if (!parts.length) {
      list.innerHTML = emptyHTML('chart', '暂无数据',
        '成稿评分、配图数量与后台任务状态会汇总在这里。');
    } else {
      list.innerHTML = parts.join('');
    }
  }

  function openDraftById(id) {
    if (!id) return;
    if (WIN.HX && typeof WIN.HX.openDraft === 'function') {
      try { WIN.HX.openDraft(id); } catch (e) { gotoPanel('drafts'); }
    } else {
      gotoPanel('drafts');
    }
    /* 载入成稿后落到预览 pane，右栏直接展示真实排版。 */
    if (WIN.HX && typeof WIN.HX.setStageTab === 'function') {
      try { WIN.HX.setStageTab('preview'); } catch (e) { /* 不阻断业务 */ }
    }
  }

  function openAssetImage(url, name) {
    if (!url) return;
    if (typeof WIN.openImageLightbox === 'function') {
      try { WIN.openImageLightbox(url, name || '图片预览'); return; } catch (e) { /* 落到新页 */ }
    }
    WIN.open(url, '_blank', 'noopener');
  }

  /* ============================== 浏览器 pane ============================== */

  var BLOCKED_HOSTS = [
    'mp.weixin.qq.com', 'weixin.qq.com', 'xiaohongshu.com', 'xhslink.com',
    'douyin.com', 'www.douyin.com', 'v.douyin.com', 'weibo.com', 'zhihu.com',
    'bilibili.com', 'toutiao.com', 'jinritemai.com', 'kuaishou.com'
  ];

  function hostOf(url) {
    try { return new URL(url).hostname; } catch (e) { return ''; }
  }
  function hostBlocked(url) {
    var h = hostOf(url);
    if (!h) return false;
    for (var i = 0; i < BLOCKED_HOSTS.length; i++) {
      var b = BLOCKED_HOSTS[i];
      if (h === b || h.slice(-(b.length + 1)) === '.' + b) return true;
    }
    return false;
  }

  function mountBrowser(pane, ctx) {
    pane.setAttribute('data-key', 'browser');
    pane.innerHTML =
      '<div class="hx-browser-card">' +
        '<div class="hx-browser-bar">' +
          '<span class="hx-b-dots"><i></i><i></i><i></i></span>' +
          '<span class="hx-b-url" data-role="url"></span>' +
          '<span class="hx-b-tools" data-role="tools"></span>' +
        '</div>' +
        '<div class="hx-browser-body" data-role="body"></div>' +
      '</div>';
    refreshBrowser(pane, ctx);
  }

  function refreshBrowser(pane, ctx) {
    var body = pane.querySelector('[data-role="body"]');
    if (!body) return;
    var draft = findDraft(ctx);
    var id = ctxDraftId(ctx);

    if (!id) {
      body.innerHTML = emptyHTML('globe', '未选择稿件',
        '先在左栏选中一篇创作稿；关联了原文链接的稿件可以在这里内嵌阅读。',
        ghostBtn('open-drafts', 'file', '去选稿件') + primaryBtn('open-inspire', 'search', '去采集'));
      return;
    }

    var url = draft && draft.source_url ? draft.source_url : '';
    if (url) { renderBrowserUrl(pane, body, draft, url); return; }

    body.innerHTML = '<div class="hx-preview-loading">正在读取稿件来源…</div>';
    api('/api/drafts/' + encodeURIComponent(id)).then(function (d) {
      if (!pane.isConnected) return;
      var b2 = pane.querySelector('[data-role="body"]');
      if (!b2) return;
      if (!d || !d.source_url) renderBrowserNoLink(b2, d || draft);
      else renderBrowserUrl(pane, b2, d, d.source_url);
    });
  }

  function renderBrowserNoLink(body, src) {
    src = src || {};
    var note = src.source_title ? ' 来源标题：' + trim(src.source_title, 24) : '';
    body.innerHTML = emptyHTML('globe', '这篇稿件没有原文链接',
      '内嵌阅读只对从采集库或链接改写生成的稿件可用；成稿、一键创作与手动导入的稿件没有外部来源。' + note,
      primaryBtn('open-inspire', 'search', '去采集工作台'));
  }

  function renderBrowserUrl(pane, body, detail, url) {
    var host = hostOf(url);
    var blocked = hostBlocked(url);

    var urlEl = pane.querySelector('[data-role="url"]');
    if (urlEl) urlEl.innerHTML = ico('lock') + '<span>' + esc(host || url) + '</span>';
    var tools = pane.querySelector('[data-role="tools"]');
    if (tools) {
      tools.innerHTML = '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer" ' +
        'title="外部打开" aria-label="外部打开">' + ico('arrow-up-right') + '</a>';
    }

    if (blocked) {
      body.className = 'hx-browser-body hx-browser-blocked';
      body.innerHTML =
        ico('globe', 'hx-blocked-ico') +
        '<h3 class="hx-blocked-title">该站点禁止内嵌阅读</h3>' +
        '<p class="hx-blocked-reason">该站点通过 X-Frame-Options 或 CSP frames-ancestors 禁止在第三方页面中打开。为避免白屏，已为你保留外部打开方式。</p>' +
        '<div class="hx-browser-meta">来源：' + esc(platLabel(detail.source_platform)) + ' · ' + esc(host) + '</div>' +
        '<div class="hx-browser-actions">' +
          '<a class="hx-btn-primary" href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + ico('arrow-up-right') + '外部打开</a>' +
          '<button type="button" class="hx-btn-ghost" data-hx-copy-url="' + esc(url) + '">' + ico('copy') + '复制链接</button>' +
        '</div>';
      return;
    }

    body.className = 'hx-browser-body';
    body.innerHTML =
      '<iframe class="hx-browser-frame" id="hxBrowserFrame" sandbox="allow-scripts allow-popups" ' +
        'referrerpolicy="no-referrer" loading="lazy" title="来源页面" src="' + esc(url) + '"></iframe>' +
      '<div class="hx-browser-note">' + ico('lock') + '<span>若上方页面被拦截或显示空白，说明该站点禁止内嵌，请用外部打开查看。</span></div>' +
      '<div class="hx-browser-actions">' +
        '<a class="hx-btn-ghost" href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + ico('arrow-up-right') + '外部打开</a>' +
      '</div>';

    var fr = byId('hxBrowserFrame');
    if (fr) {
      fr.addEventListener('load', function () { fr.setAttribute('data-loaded', '1'); });
      setTimeout(function () {
        if (fr && !fr.getAttribute('data-loaded')) fr.setAttribute('data-blocked-likely', '1');
      }, 1400);
    }
  }

  /* ============================== 预览 pane ============================== */

  function stripTags(h) {
    var d = DOC.createElement('div');
    d.innerHTML = String(h || '');
    return d.textContent || '';
  }

  function countWords(text) {
    var cjk = (text.match(/[\u4e00-\u9fa5]/g) || []).length;
    var lat = (text.replace(/[\u4e00-\u9fa5]/g, ' ').match(/[A-Za-z0-9]+/g) || []).length;
    return cjk + lat;
  }

  function sanitizeHtml(h) {
    var s = String(h || '');
    s = s.replace(/<!doctype[\s\S]*?>/gi, '');
    s = s.replace(/<!--[\s\S]*?-->/g, '');
    s = s.replace(/<head[\s\S]*?<\/head>/gi, '');
    /* 文档骨架 / 样式 / 框架标签不进预览纸面，避免浅色站点样式污染深色主题。 */
    s = s.replace(/<(meta|title|link|style|iframe|script|noscript)\b[^>]*>([\s\S]*?<\/\1>)?/gi, '');
    s = s.replace(/<script[\s\S]*?<\/script>/gi, '');
    s = s.replace(/\son\w+\s*=\s*"[^"]*"/gi, '').replace(/\son\w+\s*=\s*'[^']*'/gi, '');
    s = s.replace(/(href|src)\s*=\s*"javascript:[^"]*"/gi, '$1="#"');
    return s;
  }

  function mdToHtml(md) {
    var lines = String(md || '').split(/\n{2,}/);
    return lines.map(function (block) {
      var t = esc(block.trim());
      t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      t = t.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img src="$2" alt="$1">');
      t = t.replace(/\n/g, '<br>');
      return '<p>' + t + '</p>';
    }).join('');
  }

  function previewMetaHTML(draft, html) {
    draft = draft || {};
    var parts = [];
    if (draft.created_at) parts.push('<span>' + ico('clock') + esc(fmtTime(draft.created_at)) + '</span>');
    if (html) {
      var w = countWords(stripTags(html));
      if (w > 0) parts.push('<span>' + ico('file') + w + ' 字</span>');
    }
    if (draft.score != null && draft.score !== '') {
      parts.push('<span>' + ico('check') + '评分 ' + Math.round(Number(draft.score)) + '</span>');
    }
    return parts.join('');
  }

  /* ============================== 真实预览节点停靠（内容工作台） ==============================
     内容工作区 + 舞台展开时，把真实 #wb-preview-pane 节点搬进右栏预览挂载点；
     舞台折叠 / 切到其他工作区时归还 #hxPreviewHome（B 模块落地后），锚点缺失则
     兜底到搬运前记录的 parentNode + nextSibling。
     只搬运真实节点：不 clone、不重拉接口、不清空内部状态；业务控件（平台页签、
     拆解报告、7 维评分、历史版本、合规体检、复制、派生）随节点一起移动。 */

  var DOCK = {
    recorded: false,
    homeParent: null,
    homeNext: null,
    pane: null,
    savedPst: null,
    savedScroll: 0
  };

  function wbPane() {
    var fresh = byId('wb-preview-pane');
    if (fresh) DOCK.pane = fresh;
    return DOCK.pane;
  }
  function wbHome() { return byId('hxPreviewHome'); }

  function stageBodyEl() { return byId('hxStageBody'); }
  function stageTabsEl() { return byId('hxStageTabs'); }

  /* ------------------------------ 页签行收起控件（外观层） ------------------------------
     顶栏常驻展开入口 #hxTbStage 由外壳模块提供；这里只在页签行右侧放一个
     ghost 收起按钮，调用 core 的 toggleStage，状态与 body[data-stage] 实时
     同步。幂等：core 每次 renderStage 会清空 #hxStageTabs，ensure 时缺则重建，
     不叠加监听、不另建第二份常驻入口。 */
  function syncStageToggleState() {
    var btn = byId('hxStageCollapse');
    if (!btn) return;
    var open = DOC.body.getAttribute('data-stage') !== 'closed';
    btn.setAttribute('aria-expanded', String(open));
    btn.setAttribute('aria-pressed', String(open));
    btn.setAttribute('aria-label', open ? '收起右栏舞台' : '展开右栏舞台');
    btn.setAttribute('title', open ? '收起右栏舞台' : '展开右栏舞台');
    btn.classList.toggle('is-on', open);
  }

  function ensureStageToggle() {
    if (!harnessOn()) return;
    var tabs = stageTabsEl();
    if (!tabs) return;
    var btn = byId('hxStageCollapse');
    if (!btn) {
      btn = DOC.createElement('button');
      btn.type = 'button';
      btn.id = 'hxStageCollapse';
      btn.className = 'hx-stage-collapse';
      btn.setAttribute('data-hx-act', 'stage');
      btn.innerHTML = ico('panel');
      btn.addEventListener('click', function () {
        if (WIN.HX && typeof WIN.HX.toggleStage === 'function') {
          try { WIN.HX.toggleStage(); } catch (e) { /* 不阻断业务 */ }
        }
        syncStageToggleState();
      });
      tabs.appendChild(btn);
    }
    syncStageToggleState();
  }

  /* 持久挂载点：core 每次 renderStage 只重建激活页签 pane，挂载点由本模块
     直接持有在 #hxStageBody 下，避免切到资产 / 浏览器页签时真实预览节点被
     一并清出文档。 */
  function dockMount() {
    var body = stageBodyEl();
    if (!body) return null;
    var mount = byId('hxStagePreviewMount');
    if (!mount) {
      mount = DOC.createElement('div');
      mount.className = 'hx-stage-preview-mount';
      mount.id = 'hxStagePreviewMount';
      body.appendChild(mount);
    }
    return mount;
  }

  /* 挂载点随激活页签归位：预览页签激活时挂进该页签 pane 内可见；切到资产 /
     浏览器时退回 stage body 下隐藏，真实 pane 不归还中栏，中栏不出现第二份预览。 */
  function arrangeMountForActiveTab() {
    var body = stageBodyEl();
    var mount = byId('hxStagePreviewMount');
    if (!body || !mount) return;
    var activePane = body.querySelector('.hx-stage-pane.is-active');
    var activeKey = WIN.HX && WIN.HX.state && WIN.HX.state.stageTab;
    if (activePane && activeKey === 'preview') {
      if (mount.parentNode !== activePane) activePane.appendChild(mount);
      mount.classList.remove('is-hidden');
    } else {
      if (mount.parentNode !== body) body.appendChild(mount);
      mount.classList.add('is-hidden');
    }
  }

  function paneScrollEl(pane) { return pane ? (pane.querySelector('#wb-viewport') || pane) : null; }

  function recordHome(pane) {
    if (DOCK.recorded || !pane) return;
    DOCK.homeParent = pane.parentNode;
    DOCK.homeNext = pane.nextSibling;
    DOCK.recorded = true;
  }

  function savePaneState(pane) {
    if (!pane) return;
    var on = pane.querySelector('.wb-nav-tab.on');
    DOCK.savedPst = on ? on.getAttribute('data-pst') : null;
    var sc = paneScrollEl(pane);
    DOCK.savedScroll = sc ? sc.scrollTop : 0;
  }

  function restorePaneState(pane) {
    if (!pane) return;
    if (DOCK.savedPst) {
      var cur = pane.querySelector('.wb-nav-tab.on');
      if (!cur || cur.getAttribute('data-pst') !== DOCK.savedPst) {
        var target = pane.querySelector('.wb-nav-tab[data-pst="' + DOCK.savedPst + '"]');
        if (target) { tryFn(function () { target.click(); }); }
      }
    }
    var sc = paneScrollEl(pane);
    if (sc) {
      sc.scrollTop = DOCK.savedScroll;
      /* 节点刚搬入、尺寸尚未回流时再补一次，避免滚动位置被布局清零。 */
      setTimeout(function () { tryFn(function () { sc.scrollTop = DOCK.savedScroll; }); }, 0);
    }
  }

  function dockPreview() {
    var pane = wbPane();
    var mount = dockMount();
    if (!pane || !mount) return;
    recordHome(pane);
    savePaneState(pane);
    if (pane.parentNode !== mount) mount.appendChild(pane);
    DOC.body.setAttribute('data-preview-dock', 'stage');
    restorePaneState(pane);
  }

  function undockPreview() {
    var pane = wbPane();
    if (!pane) return;
    savePaneState(pane);
    /* 优先归还 B 模块的稳定锚点 #hxPreviewHome；锚点尚未落地 / 随内容栏
       一并隐藏时，兜底到搬运前记录的父节点（仅当其仍在文档内），否则保留
       节点引用，待家位可用后由 syncDock 复核归还。 */
    var home = wbHome();
    if (home) {
      home.appendChild(pane);
    } else if (DOCK.homeParent && DOC.body.contains(DOCK.homeParent)) {
      if (DOCK.homeNext && DOCK.homeNext.parentNode === DOCK.homeParent) {
        DOCK.homeParent.insertBefore(pane, DOCK.homeNext);
      } else {
        DOCK.homeParent.appendChild(pane);
      }
    }
    DOC.body.setAttribute('data-preview-dock', 'inline');
    restorePaneState(pane);
  }

  /* 停靠决策：仅内容工作台 + 舞台展开时进右栏；其余情况一律归还中栏，
     并清理可能残留的 stage 停靠标记。 */
  function syncDock() {
    if (!harnessOn()) return;
    arrangeMountForActiveTab();
    var pane = wbPane();
    var open = DOC.body.getAttribute('data-stage') === 'open';
    var shouldDock = currentWs() === 'content' && open;
    var mount = dockMount();
    var inMount = !!(mount && pane && mount.contains(pane));
    if (shouldDock) {
      if (mount) dockPreview();
    } else {
      if (inMount) undockPreview();
      if (DOC.body.getAttribute('data-preview-dock') === 'stage') {
        DOC.body.setAttribute('data-preview-dock', 'inline');
      }
    }
  }

  /* 线程侧锚点可能在异步渲染后把 pane 挪回 #hxPreviewHome；下一帧 + 短延时
     各复核一次，尽快收敛到应有停靠态，避免依赖 1.6s 兜底轮询。 */
  var dockRecheckScheduled = false;
  function recheckDockSoon() {
    if (dockRecheckScheduled) return;
    dockRecheckScheduled = true;
    var done = function () { dockRecheckScheduled = false; };
    tryFn(function () {
      if (WIN.requestAnimationFrame) WIN.requestAnimationFrame(function () { syncDock(); });
      WIN.setTimeout(function () { syncDock(); done(); }, 220);
    });
  }

  var PV = { plat: null };

  function cardsStrip(cards) {
    if (!cards || !cards.length) return '';
    return '<div class="hx-pv-cards">' + cards.map(function (c) {
      return '<img src="' + esc(c) + '" alt="卡片素材" loading="lazy">';
    }).join('') + '</div>';
  }

  function renderPlatPills(pane, plats, active) {
    var box = pane.querySelector('[data-role="plats"]');
    if (!box) return;
    box.innerHTML = plats.map(function (p) {
      return '<button type="button" class="hx-pill-plat' + (p === active ? ' is-active' : '') +
        '" data-plat="' + esc(p) + '">' + esc(platLabel(p)) + '</button>';
    }).join('');
  }

  function mountPreview(pane, ctx) {
    pane.setAttribute('data-key', 'preview');
    if (currentWs() === 'content') {
      /* 内容工作台：右栏只停靠真实 #wb-preview-pane；挂载点由持久逻辑持有，
         不在本页签 pane 内重建，避免切走页签时被 core 清出文档。 */
      pane.classList.add('hx-stage-pane--dock');
      arrangeMountForActiveTab();
      syncDock();
      recheckDockSoon();
      return;
    }
    pane.innerHTML =
      '<div class="hx-preview-doc" data-role="doc">' +
        '<div class="hx-preview-tools">' +
          '<span class="hx-version-pill">当前版本</span>' +
          '<span class="hx-preview-plats" data-role="plats"></span>' +
          '<span class="hx-spacer"></span>' +
          '<button type="button" class="hx-icon-btn" data-role="copy" title="复制全文" aria-label="复制全文">' + ico('copy') + '</button>' +
        '</div>' +
        '<h2 class="hx-preview-title" data-role="title"></h2>' +
        '<div class="hx-preview-meta" data-role="meta"></div>' +
        '<div class="hx-preview-rule"></div>' +
        '<div class="hx-preview-paper" data-role="paper"><div class="hx-preview-loading">排版渲染中…</div></div>' +
      '</div>';
    refreshPreview(pane, ctx);
  }

  function previewPlats(draft) {
    var ps = draft && Array.isArray(draft.platforms) && draft.platforms.length
      ? draft.platforms.slice() : ['wechat_mp'];
    return ps;
  }

  function refreshPreview(pane, ctx) {
    if (currentWs() === 'content') { syncDock(); return; }
    var draft = findDraft(ctx);
    var id = ctxDraftId(ctx);

    if (!id) {
      PV.plat = null;
      pane.innerHTML = emptyHTML('layers', '舞台待命',
        '当前任务还没有可预览的成稿。先让 Agent 写一版，排版预览会实时出现在这里。',
        primaryBtn('new-task', 'sparkles', '给我一个选题') + ghostBtn('open-drafts', 'file', '从草稿开始'));
      return;
    }

    var plats = previewPlats(draft);
    if (!PV.plat || plats.indexOf(PV.plat) < 0) PV.plat = plats[0];
    var plat = PV.plat;

    var doc = pane.querySelector('[data-role="doc"]');
    if (doc) {
      doc.setAttribute('data-plat', plat);
      var title = pane.querySelector('[data-role="title"]');
      if (title) title.textContent = (draft && draft.title) || '未命名稿件';
      renderPlatPills(pane, plats, plat);
      var meta = pane.querySelector('[data-role="meta"]');
      if (meta) meta.innerHTML = previewMetaHTML(draft);
    }
    /* 草稿对象缺失时（状态尚未同步）补拉一次详情，回填标题 / 元信息 / 平台列表。 */
    if (!draft) {
      api('/api/drafts/' + encodeURIComponent(id)).then(function (d) {
        if (!pane.isConnected) return;
        if (!d) return;
        draft = d;
        var plats2 = previewPlats(d);
        if (PV.plat == null || plats2.indexOf(PV.plat) < 0) PV.plat = plats2[0];
        var t2 = pane.querySelector('[data-role="title"]');
        if (t2 && (!t2.textContent || t2.textContent === '未命名稿件')) t2.textContent = d.title || '未命名稿件';
        renderPlatPills(pane, plats2, PV.plat);
        var m2 = pane.querySelector('[data-role="meta"]');
        if (m2) m2.innerHTML = previewMetaHTML(d);
      });
    }
    loadPreview(pane, id, plat, draft);
  }

  function loadPreview(pane, id, plat, draft) {
    api('/api/drafts/' + encodeURIComponent(id) + '/raw/' + encodeURIComponent(plat)).then(function (r) {
      var paper = pane.querySelector('[data-role="paper"]');
      if (!paper || !pane.isConnected) return;
      if (r == null) { showPreviewError(pane, id, plat, draft); return; }
      var html = r.html || '';
      var text = r.text || '';
      var cards = Array.isArray(r.cards) ? r.cards : [];
      if (html) {
        paper.innerHTML = sanitizeHtml(html) + cardsStrip(cards);
      } else if (text) {
        /* 部分平台（如小红书）后端只给纯文本 + 卡片数组：按 Markdown 轻排版渲染，不伪造 HTML。 */
        paper.innerHTML = mdToHtml(text) + cardsStrip(cards);
      } else {
        /* 后端未给排版 HTML：退回稿件正文 markdown 纯文本渲染（真实数据，不编造）。 */
        api('/api/drafts/' + encodeURIComponent(id)).then(function (d) {
          var md = (d && d.body_md) || '';
          var p2 = pane.querySelector('[data-role="paper"]');
          if (!p2 || !p2.isConnected) return;
          if (!md) { p2.innerHTML = '<div class="hx-preview-loading">暂无排版内容</div>'; return; }
          p2.innerHTML = mdToHtml(md);
        });
        return;
      }
      if (r.title) {
        var tEl = pane.querySelector('[data-role="title"]');
        if (tEl && (!tEl.textContent || tEl.textContent === '未命名稿件')) tEl.textContent = r.title;
      }
      var meta = pane.querySelector('[data-role="meta"]');
      if (meta) {
        var extra = cards.length ? '<span>' + ico('image') + cards.length + ' 卡</span>' : '';
        meta.innerHTML = previewMetaHTML(draft, paper.textContent) + extra;
      }
      var copy = pane.querySelector('[data-role="copy"]');
      if (copy) copy.onclick = function () { copyText(paper.textContent || ''); };
    }).catch(function () {
      showPreviewError(pane, id, plat, draft);
    });
  }

  function showPreviewError(pane, id, plat, draft) {
    var paper = pane.querySelector('[data-role="paper"]');
    if (!paper) return;
    paper.innerHTML = '<div class="hx-preview-error">预览加载失败，请稍后重试。' +
      '<button type="button" class="hx-btn-ghost hx-retry" data-hx-retry-preview>重试</button></div>';
    var rb = paper.querySelector('[data-hx-retry-preview]');
    if (rb) rb.onclick = function () { loadPreview(pane, id, plat, draft); };
  }

  function copyText(t) {
    t = String(t || '');
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(t).then(function () { toast('已复制'); }, function () { legacyCopy(t); });
    } else {
      legacyCopy(t);
    }
  }
  function legacyCopy(t) {
    var ta = DOC.createElement('textarea');
    ta.value = t;
    DOC.body.appendChild(ta);
    ta.select();
    try { DOC.execCommand('copy'); toast('已复制'); } catch (e) { toast('复制失败'); }
    DOC.body.removeChild(ta);
  }

  /* ============================== 计数 ============================== */

  function countAssets(ctx) {
    var n = AS.imgTotal || AS.imgs.length || AS.drafts.length || draftsOf(ctx).length;
    return n || '';
  }
  function countBrowser(ctx) {
    var n = draftsOf(ctx).filter(function (x) { return x && x.source_url; }).length;
    return n || '';
  }
  function countPreview(ctx) {
    return findDraft(ctx) ? 1 : '';
  }

  /* ============================== 舞台页签默认值与分工作区记忆 ============================== */
  /* core 的全局键 yimu.hx.stageTab 只存一个 key，跨工作区会串页签。本模块只用
     分工作区记忆 yimu.hx.stageTab.<ws>；旧全局键不参与解析（一次性迁移打标后
     即弃用）。默认：任务 / 内容 → 资产；采集 → 采集分析；设置 → 配置检查。 */

  var STAGE_TAB_WS_PREFIX = 'yimu.hx.stageTab.';
  var STAGE_TAB_MIGRATED = 'yimu.hx.stageTab.migrated';
  var WS_DEFAULT_TAB = { tasks: 'assets', content: 'preview', collect: 'analysis', settings: 'checks' };
  var WS_KEYS = ['tasks', 'content', 'collect', 'settings'];

  function memGet(k) { try { return WIN.localStorage.getItem(k); } catch (e) { return null; } }
  function memSet(k, v) { try { WIN.localStorage.setItem(k, v); } catch (e) { /* 隐私模式忽略 */ } }

  function wsRegisteredKeys(ws) {
    var reg = WIN.HX && WIN.HX._reg && WIN.HX._reg.stageTabs;
    var arr = (reg && reg[ws]) || [];
    var out = [];
    for (var i = 0; i < arr.length; i++) out.push(arr[i].key);
    return out;
  }
  function tabValid(ws, key) { return !!key && wsRegisteredKeys(ws).indexOf(key) >= 0; }

  /* 一次性迁移：仅在本次运行发现所有工作区都还没有自己的记忆键时打一次
     迁移标记；旧全局键 yimu.hx.stageTab 的页签值一律不继承（避免跨工区串值），
     此后解析只读分工作区键，缺失即落默认值。 */
  function runLegacyMigration() {
    if (memGet(STAGE_TAB_MIGRATED)) return;
    var anyWs = WS_KEYS.some(function (w) { return !!memGet(STAGE_TAB_WS_PREFIX + w); });
    if (!anyWs) memSet(STAGE_TAB_MIGRATED, '1');
  }

  function resolveStageTab(ws) {
    var per = memGet(STAGE_TAB_WS_PREFIX + ws);
    if (tabValid(ws, per)) return per;
    return WS_DEFAULT_TAB[ws] || 'assets';
  }

  function currentWs() {
    return (WIN.HX && WIN.HX.state && WIN.HX.state.workspace) || 'tasks';
  }

  function memorizeStageTab(ws, key) {
    if (ws && key) memSet(STAGE_TAB_WS_PREFIX + ws, key);
  }

  function syncStageTab() {
    if (!WIN.HX || !WIN.HX.state || typeof WIN.HX.setStageTab !== 'function') return;
    var ws = currentWs();
    var eff = resolveStageTab(ws);
    if (WIN.HX.state.stageTab !== eff) {
      try { WIN.HX.setStageTab(eff); } catch (e) { /* 不阻断业务 */ }
    }
  }

  /* ============================== 注册（单主模式） ============================== */

  var STAGE_TABS = [
    { key: 'assets',  title: '资产',  count: countAssets,  mount: mountAssets,  refresh: refreshAssets  },
    { key: 'browser', title: '浏览器', count: countBrowser, mount: mountBrowser, refresh: refreshBrowser },
    { key: 'preview', title: '预览',  count: countPreview, mount: mountPreview, refresh: refreshPreview }
  ];
  var WORKSPACES = ['tasks', 'content', 'collect', 'settings'];
  var KEY_TO_DEF = {};
  STAGE_TABS.forEach(function (d) { KEY_TO_DEF[d.key] = d; });

  /* 直接透传 core 的 HX.registerStageTab：不包第二层、不重复入列、
     也不覆盖 D 模块已注册的扩展页签。 */
  function registerAll() {
    if (!WIN.HX || typeof WIN.HX.registerStageTab !== 'function') return false;
    WORKSPACES.forEach(function (ws) {
      STAGE_TABS.forEach(function (def) {
        tryFn(function () { WIN.HX.registerStageTab(ws, def); });
      });
    });
    return true;
  }

  /* ------------------------------ 当前 pane 增量刷新 ------------------------------ */

  /* 内容工作区 + 舞台展开 + 已选中稿时，自动落到预览页签，让用户一选稿就在
     右栏看到真实预览；同一篇稿件不重复抢页签，用户手动切到资产 / 浏览器后，
     直到切换下一篇稿件不再被自动拉回。 */
  var autoPid = null;
  /* 启动 / 切回工区时先播种当前稿件 id：刷新或恢复记忆页签不被自动切换抢走，
     只有之后实际选中另一篇稿件才触发自动落预览。 */
  function seedAutoPid() { autoPid = ctxDraftId(null); }
  function autoPreviewWhenDraft() {
    if (currentWs() !== 'content') return;
    var open = DOC.body.getAttribute('data-stage') === 'open';
    if (!open) return;
    var id = ctxDraftId(null);
    if (!id) return;
    if (id === autoPid) return;
    autoPid = id;
    if (WIN.HX && WIN.HX.state && WIN.HX.state.stageTab !== 'preview') {
      try { WIN.HX.setStageTab('preview'); } catch (e) { /* 不阻断业务 */ }
    }
  }

  function refreshActivePane() {
    arrangeMountForActiveTab();
    ensureStageToggle();
    autoPreviewWhenDraft();
    syncDock();
    var body = byId('hxStageBody');
    if (!body) return;
    var pane = body.querySelector('.hx-stage-pane.is-active') || body.firstElementChild;
    if (!pane) return;
    var def = KEY_TO_DEF[pane.getAttribute('data-key')];
    if (!def) return; /* D 模块的扩展 pane 由其自身 refresh 负责 */
    tryFn(function () { def.refresh(pane, localCtx()); });
  }

  function subscribe() {
    if (!WIN.HX || typeof WIN.HX.on !== 'function') return;
    ['draft', 'drafts', 'state', 'ready'].forEach(function (ev) {
      tryFn(function () { WIN.HX.on(ev, function () { refreshActivePane(); }); });
    });
    /* 切换工作区：按该工作区自己的记忆 / 默认值校正页签，不串相邻工作区；
       同时按新工作区决定真实预览节点进右栏还是归还中栏。 */
    tryFn(function () { WIN.HX.on('workspace', function () { seedAutoPid(); syncStageTab(); syncDock(); recheckDockSoon(); }); });
    /* 用户手动切页签 / 舞台开合：记入分工作区记忆，并复核停靠位置。 */
    tryFn(function () { WIN.HX.on('stage', function () {
      memorizeStageTab(currentWs(), WIN.HX.state && WIN.HX.state.stageTab);
      ensureStageToggle();
      syncDock(); recheckDockSoon();
    }); });
    tryFn(function () { WIN.HX.on('ready', function () { syncStageTab(); ensureStageToggle(); syncDock(); recheckDockSoon(); }); });
  }

  /* ------------------------------ 动作委托 ------------------------------ */

  function currentPane() {
    var body = byId('hxStageBody');
    return body && (body.querySelector('.hx-stage-pane.is-active') || body.firstElementChild);
  }

  var delegated = false;
  function bindBody() {
    var body = byId('hxStageBody');
    if (!body || delegated) return;
    delegated = true;
    body.addEventListener('click', function (e) {
      var t = e.target;

      /* 预览 pane 平台切换（公众号 / 小红书 / 头条…） */
      var platPill = t.closest ? t.closest('.hx-pill-plat') : null;
      if (platPill) {
        PV.plat = platPill.getAttribute('data-plat') || PV.plat;
        var paneP = currentPane();
        if (paneP) refreshPreview(paneP, localCtx());
        return;
      }

      /* 资产 pane 子页签切换（成稿 / 图片 / 数据） */
      var subTab = t.closest ? t.closest('.hx-a-tab') : null;
      if (subTab) {
        AS.tab = subTab.getAttribute('data-at') || 'doc';
        var pane0 = currentPane();
        if (pane0) renderAssets(pane0, localCtx());
        return;
      }

      /* 资产 pane 刷新按钮 */
      var refreshBtn = t.closest ? t.closest('[data-role="refresh"]') : null;
      if (refreshBtn) {
        var pane1 = currentPane();
        if (pane1) reloadAssets(pane1, localCtx());
        return;
      }

      var actBtn = t.closest ? t.closest('[data-hx-act]') : null;
      if (actBtn) {
        var act = actBtn.getAttribute('data-hx-act');
        if (act === 'open-drafts') gotoPanel('drafts');
        else if (act === 'open-inspire') gotoPanel('inspire');
        else if (act === 'new-task') newTaskFlow();
        return;
      }

      /* 资产 pane 行内动作：载入成稿 / 放大图片 */
      var rowBtn = t.closest ? t.closest('[data-act]') : null;
      if (rowBtn) {
        var rowAct = rowBtn.getAttribute('data-act');
        if (rowAct === 'pick') openDraftById(rowBtn.getAttribute('data-id'));
        else if (rowAct === 'zoom') openAssetImage(rowBtn.getAttribute('data-url'), rowBtn.getAttribute('data-name'));
        return;
      }

      var copyBtn = t.closest ? t.closest('[data-hx-copy-url]') : null;
      if (copyBtn) copyText(copyBtn.getAttribute('data-hx-copy-url'));
    });
  }

  function gotoPanel(key) {
    var nav = DOC.querySelector('.side .nav-item[data-p="' + key + '"]');
    if (nav) { nav.click(); return; }
    if (typeof WIN.switchToPage === 'function') {
      try { WIN.switchToPage(key); } catch (e) {}
    }
  }

  function newTaskFlow() {
    if (WIN.HX && typeof WIN.HX.newTask === 'function') {
      try { WIN.HX.newTask(); return; } catch (e) {}
    }
    var inp = byId('copilot-input') || DOC.querySelector('#p-lite-mode textarea');
    if (inp && inp.focus) inp.focus();
    toast('写下主题发送后，Agent 生成成品会自动出现在这里');
  }

  /* ------------------------------ 启动 ------------------------------ */

  function boot() {
    if (!harnessOn()) return;
    relocateLegacyPanel();
    bindBody();
    subscribe();
    ensureStageToggle();
    runLegacyMigration();
    syncStageTab();
    syncDock();
    seedAutoPid();
    /* D 模块的扩展页签可能晚于本模块注册；延迟再校正几轮，确保默认页签落对。 */
    [300, 900, 1800].forEach(function (ms) { setTimeout(function () { syncStageTab(); syncDock(); }, ms); });
    if (WIN.HX && WIN.HX.ready && typeof WIN.HX.ready.then === 'function') {
      WIN.HX.ready.then(function () { relocateLegacyPanel(); bindBody(); syncStageTab(); syncDock(); seedAutoPid(); refreshActivePane(); }).catch(function () {});
    }
  }

  /* 脚本加载阶段即注册（不在 DOMContentLoaded 里）；HX 若稍后就绪，短轮询兜底。 */
  if (WIN.HX) {
    registerAll();
  } else {
    var tries = 0;
    var waitTimer = setInterval(function () {
      tries += 1;
      if (WIN.HX) {
        clearInterval(waitTimer);
        registerAll();
        boot();
      } else if (tries > 40) {
        clearInterval(waitTimer);
      }
    }, 50);
  }
  boot();

  /* 兜底轮询：业务侧未派发事件时，选中稿件变化也能增量刷新当前 pane；
     同时复核停靠位置（面板晚到重建 / 事件丢失时兜底）。 */
  var lastDraftId = ctxDraftId(null);
  setInterval(function () {
    if (!harnessOn()) return;
    ensureStageToggle();
    syncDock();
    var id = ctxDraftId(null);
    if (id !== lastDraftId) {
      lastDraftId = id;
      refreshActivePane();
    }
  }, 1600);
})();
