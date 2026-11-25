/* SPDX-License-Identifier: BUSL-1.1 */
/* ==========================================================================
   Harness 中栏模块（B 负责人）
   --------------------------------------------------------------------------
   职责（只负责 tasks / content 两个工作区；collect / settings 归 D 模块）：
     1. 任务页（tasks）：thread-head / meta / 执行计划卡，中栏承载真实迁入的
        #p-lite-mode 对话与生成区（不 clone、不重写业务绑定）；
     2. 内容页（content）：把真实编辑器区域重排进原型工作台容器，保留全部
        既有按钮与 onclick 链路，不重写业务逻辑；
     3. 联动 HX 的 workspace / state / drafts / draft 事件，挂载卸载不残留；
     4. 归属守卫：core 注册表中已有别人实现的工作区一律跳过，不清空、不写骨架。
   仅在 body[data-shell="harness"] 下生效；classic / v2 零影响。纯 ES5 + IIFE。
   ========================================================================== */
(function () {
  'use strict';

  var DOC = document;
  var WIN = window;

  function isHarness() {
    return !!DOC.body && DOC.body.getAttribute('data-shell') === 'harness';
  }
  if (!isHarness()) return;

  /* ------------------------------ 基础工具 ------------------------------ */

  function $(id) { return DOC.getElementById(id); }
  function hx() { return WIN.HX || null; }

  function esc(s) {
    var h = hx();
    if (h && typeof h.esc === 'function') { try { return h.esc(s); } catch (e) {} }
    if (typeof WIN.escapeHtml === 'function') { try { return WIN.escapeHtml(s); } catch (e) {} }
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
    var d = new Date(String(v).replace(' ', 'T'));
    if (isNaN(d.getTime())) return String(v).slice(5, 16).replace('T', ' ');
    var hh = d.getHours(), mm = d.getMinutes();
    return (d.getMonth() + 1) + '/' + d.getDate() + ' ' +
      (hh < 10 ? '0' + hh : hh) + ':' + (mm < 10 ? '0' + mm : mm);
  }

  function toast(msg) {
    var h = hx();
    if (h && typeof h.toast === 'function') { try { h.toast(msg); return; } catch (e) {} }
    if (typeof WIN.toast === 'function') { try { WIN.toast(msg, 2500); } catch (e) {} }
  }

  function api(path) {
    var h = hx();
    if (h && typeof h.api === 'function') {
      try { return Promise.resolve(h.api(path)); } catch (e) { return Promise.resolve(null); }
    }
    return fetch(path, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  /* 图标：优先 core 注入的 sprite / HX.ico；否则用原型内联路径兜底。 */
  var ICONS = {
    'chevron-right': '<path d="M9 5l7 7-7 7"/>',
    'chevron-down': '<path d="M6 9l6 6 6-6"/>',
    'arrow-up-right': '<path d="M7 17L17 7M8 7h9v9"/>',
    share: '<circle cx="18" cy="5.5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="18.5" r="2.5"/><path d="M8.2 10.8l7.6-4M8.2 13.2l7.6 4"/>',
    pin: '<path d="M9 4h6l-1 5 3 3v1H7v-1l3-3-1-5z"/><path d="M12 13v7"/>',
    panel: '<rect x="3.5" y="4" width="17" height="16" rx="2.5"/><path d="M15 4v16M15 9h4M15 13h4"/>',
    more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    sparkles: '<path d="M12 3l1.4 4.6L18 9l-4.6 1.4L12 15l-1.4-4.6L6 9l4.6-1.4L12 3z"/><path d="M18.5 15l.7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.3z"/>',
    book: '<path d="M5 4h6a2 2 0 0 1 2 2v14a2 2 0 0 0-2-2H5V4z"/><path d="M19 4h-6a2 2 0 0 0-2 2v14a2 2 0 0 1 2-2h6V4z"/>',
    globe: '<circle cx="12" cy="12" r="8"/><path d="M4 12h16M12 4a13 13 0 0 1 0 16M12 4a13 13 0 0 0 0 16"/>',
    notes: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h3"/>',
    clock: '<circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7"/>',
    rocket: '<path d="M5 15l-2 6 6-2c3-1 6-3 8-6l3-5-5 0-5 3-2 1-3 3z"/><path d="M14 10l3 3"/><circle cx="11" cy="9" r="1.2"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4 4"/>',
    file: '<path d="M7 3h7l4 4v14H7V3z"/><path d="M14 3v5h5M9.5 12h5M9.5 15h5M9.5 18h3"/>',
    send: '<path d="M20 4L10 14"/><path d="M20 4l-6 16-4-6-6-4 16-6z"/>',
    paperclip: '<path d="M9 12.5l6-6a3.2 3.2 0 0 1 4.5 4.5l-8 8a5 5 0 0 1-7-7l8-8"/><path d="M7 15l7-7"/>',
    hash: '<path d="M9 4L7 20M17 4l-2 16M5 9h15M4 15h15"/>',
    bolt: '<path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1.1l2-1.5-2-3.4-2.3.9a7 7 0 0 0-1.9-1.1L14.3 3h-4.6l-.4 2.8a7 7 0 0 0-1.9 1.1L5 6l-2 3.4 2 1.5A7 7 0 0 0 5 12a7 7 0 0 0 .1 1.1l-2 1.5 2 3.4 2.3-.9a7 7 0 0 0 1.9 1.1l.4 2.8h4.6l.4-2.8a7 7 0 0 0 1.9-1.1l2.3.9 2-3.4-2-1.5A7 7 0 0 0 19 12z"/>'
  };

  function ico(name, cls) {
    var h = hx();
    if (h && typeof h.ico === 'function') { try { return h.ico(name, cls); } catch (e) {} }
    var d = ICONS[name] || '';
    return '<svg class="hx-ico ' + (cls || '') + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + d + '</svg>';
  }

  /* ------------------------------ 状态与缓存 ------------------------------ */

  var cache = { tasks: [], history: [], images: [], extraFor: '' };
  var pollTimer = null;
  var restoredFor = null;

  /* 本模块只负责 tasks / content；collect / settings 归 D 模块，不注册、不渲染。 */
  var OWNED_WS = { tasks: true, content: true };
  var OWNER_TAG = 'thread';

  function domActiveDraftId() {
    var on = DOC.querySelector('#draft-list-container .draft-card.on input[data-id]');
    return on ? String(on.getAttribute('data-id')) : null;
  }

  function resolveCtx() {
    var h = hx();
    var state = (h && h.state) || {};
    var status = state.status || {};
    var drafts = state.drafts || status.drafts || [];
    var draftId = state.draftId || domActiveDraftId() || null;
    var draft = null;
    for (var i = 0; i < drafts.length; i++) {
      if (String(drafts[i].id) === String(draftId)) { draft = drafts[i]; break; }
    }
    var topic = null;
    if (draft && draft.topic_id) {
      var topics = status.topics || [];
      for (var j = 0; j < topics.length; j++) {
        if (String(topics[j].id) === String(draft.topic_id)) { topic = topics[j]; break; }
      }
    }
    return { state: state, status: status, drafts: drafts, draft: draft, topic: topic, data: cache };
  }

  function platLabel(status, code) {
    var names = status.platform_names || {};
    return names[code] || code;
  }

  function modelLabel(status) {
    var t = (status.capabilities && status.capabilities.text) || {};
    var v = t.model_tag || t.model || '';
    if (v && typeof WIN.harnessModelLabel === 'function') {
      try { return WIN.harnessModelLabel(v); } catch (e) {}
    }
    return v || '默认模型';
  }

  function stripMd(md) {
    return String(md || '')
      .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
      .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
      .replace(/[#>*`\-—|]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function wordCount(md) {
    var t = stripMd(md);
    if (!t) return 0;
    var cjk = (t.match(/[一-鿿]/g) || []).length;
    var words = (t.replace(/[一-鿿]/g, ' ').match(/[A-Za-z0-9]+/g) || []).length;
    return cjk + words;
  }

  function fmtDur(s) {
    if (s == null || s === '') return '';
    s = Number(s) || 0;
    if (s <= 0) return '';
    if (s < 60) return Math.round(s) + ' 秒';
    var m = Math.floor(s / 60);
    var sec = Math.round(s % 60);
    return m + ' 分钟' + (sec ? ' ' + sec + ' 秒' : '');
  }

  function activeTaskFor(ctx) {
    var d = ctx.draft;
    if (!d) return null;
    var tasks = cache.tasks || [];
    for (var i = 0; i < tasks.length; i++) {
      var t = tasks[i];
      if (String(t.target_id) === String(d.id) && (t.status === 'running' || t.status === 'queued')) return t;
    }
    return null;
  }

  /* 任务页语义：头部代表「当前进行中的创作任务」。只有 /api/tasks 存在
     target_id 命中且处于 running/queued 的真实任务时，才沿用该草稿标题与状态；
     否则不把内容页选中的稿子搬到任务页，标题/状态回到默认空态。 */
  function taskCtx(ctx) {
    if (activeTaskFor(ctx)) return ctx;
    return {
      state: ctx.state, status: ctx.status, drafts: ctx.drafts,
      draft: null, topic: null, data: ctx.data
    };
  }

  function pillFor(ctx, activeTask) {
    var d = ctx.draft;
    if (activeTask) return { cls: '', text: '自动执行中' };
    if (!d) return { cls: 'static', text: '新任务' };
    var st = String(d.status || '');
    if (st === 'published' || st === 'done') return { cls: 'static good', text: '已归档' };
    if (st === 'failed') return { cls: 'static danger', text: '生成失败' };
    if (st === 'draft') return { cls: 'static', text: '草稿' };
    return { cls: 'static', text: '待审' };
  }

  /* ------------------------------ 执行计划推导 ------------------------------ */
  /* 步骤与状态只来自 /api/tasks 中 target_id 命中当前草稿的真实任务；
     没有真实任务时显示「暂无执行计划」空态，不写死、不臆造演示进度。 */

  function buildPlan(ctx) {
    var d = ctx.draft;
    var tasks = cache.tasks || [];
    var empty = { steps: [], done: 0, total: 0, active: false, dur: 0, mine: [], empty: true };
    if (!d) return empty;

    var mine = [];
    tasks.forEach(function (t) {
      if (String(t.target_id) === String(d.id)) mine.push(t);
    });
    if (!mine.length) return empty;

    var steps = mine.map(function (t) {
      var st = 'wait';
      if (t.status === 'running') st = 'active';
      else if (t.status === 'completed' || t.status === 'done') st = 'done';
      else if (t.status === 'failed') st = 'fail';
      return {
        label: t.name || t.step || '后台任务',
        note: t.message || (st === 'fail' ? String(t.error || '失败').slice(0, 24) : ''),
        state: st,
        task: t
      };
    });

    var done = 0, dur = 0, active = false;
    steps.forEach(function (s) {
      if (s.state === 'done') done++;
      if (s.state === 'active') active = true;
    });
    mine.forEach(function (t) {
      if (t.status === 'completed' && t.duration_s) dur += Number(t.duration_s) || 0;
    });

    return { steps: steps, done: done, total: steps.length, active: active, dur: dur, mine: mine, empty: false };
  }

  /* ------------------------------ 任务页：头部 ------------------------------ */

  function renderTasksHead(el, ctx) {
    ctx = taskCtx(ctx);
    var d = ctx.draft;
    var pill = pillFor(ctx, activeTaskFor(ctx));
    mountOwnedHead(el,
      '<div class="hx-thread-title">' +
        '<div class="hx-crumb">任务 ' + ico('chevron-right') + ' 内容工作台</div>' +
        '<div class="hx-title-line"><h1>' + esc(d ? (d.title || '未命名草稿') : '新创作任务') + '</h1>' +
        '<span class="hx-state-pill ' + pill.cls + '"><i></i>' + esc(pill.text) + '</span></div>' +
      '</div>' +
      '<div class="hx-thread-actions">' +
        '<button type="button" class="hx-icon-btn" data-hx-act="share" data-tip="分享任务">' + ico('share') + '</button>' +
        '<button type="button" class="hx-icon-btn" data-hx-act="pin" data-tip="钉住任务">' + ico('pin') + '</button>' +
        '<button type="button" class="hx-icon-btn" data-hx-act="stage" data-tip="展开 / 收起舞台">' + ico('panel') + '</button>' +
        '<button type="button" class="hx-icon-btn" data-hx-act="more" data-tip="更多操作">' + ico('more') + '</button>' +
      '</div>');
  }

  /* ------------------------------ 任务页：元信息行 ------------------------------ */

  function tasksMetaHtml(ctx) {
    var d = ctx.draft;
    var chips = '<span class="hx-meta-chip hx-model">' + ico('sparkles') + esc(modelLabel(ctx.status)) + '</span>';
    var hist = cache.history || [];
    if (hist.length) chips += '<span class="hx-meta-chip">' + ico('book') + hist.length + ' 个历史版本</span>';
    if (d && d.platforms && d.platforms.length) {
      chips += '<span class="hx-meta-chip">' + ico('globe') +
        esc(d.platforms.map(function (p) { return platLabel(ctx.status, p); }).join(' · ')) + '</span>';
    }
    var plan = buildPlan(ctx);
    var right = '';
    if (plan.steps.length) right += '<button type="button" class="hx-meta-link" data-hx-act="plan">' + ico('notes') + plan.steps.length + ' 步计划</button>';
    if (plan.dur) right += '<button type="button" class="hx-meta-link" data-hx-act="time">' + ico('clock') + fmtDur(plan.dur) + '</button>';
    return '<div class="hx-thread-meta">' + chips + '<span class="hx-meta-spacer"></span>' + right + '</div>';
  }

  /* ------------------------------ 执行计划卡 ------------------------------ */

  var planCollapsed = false;

  function planCardHtml(plan) {
    /* 无真实步骤时不渲染空计划卡：元信息压成一行紧凑 chips，引导卡直接出现，
       不再出现重复的「暂无执行计划」空态文案。 */
    if (!plan.steps.length) return '';
    var rows = plan.steps.map(function (s) {
      var icoInner = s.state === 'done' ? ico('check') : '';
      return '<div class="hx-step ' + s.state + '"><span class="hx-step-ico">' + icoInner + '</span>' +
        '<span class="hx-step-label">' + esc(s.label) + '</span>' +
        '<span class="hx-step-note">' + esc(s.note || '') + '</span></div>';
    }).join('');
    var meta = plan.total + ' 步' + (plan.dur ? (' · ' + fmtDur(plan.dur)) : '');
    return '<div class="hx-plan-card' + (planCollapsed ? ' is-collapsed' : '') + '">' +
      '<button type="button" class="hx-plan-head" data-hx-act="plan-toggle" aria-expanded="' +
      (!planCollapsed) + '">' +
        '<span class="hx-plan-ico">' + ico('rocket') + '</span>' +
        '<div class="hx-plan-titles"><b>执行计划</b><span>' + esc(meta) + '</span></div>' +
        '<span class="hx-plan-count">' + plan.done + ' / ' + plan.total + '</span>' +
      '</button>' +
      '<div class="hx-plan-steps">' + rows + '</div></div>';
  }

  /* ------------------------------ 真实面板迁入 / 归还 ------------------------------ */
  /* 任务页：真实 #p-lite-mode 对话与生成区（整节点迁入，不 clone、不重写绑定；
     右侧成稿画布归舞台模块，中栏隐藏）。记录原父节点，离开任务页时归还。 */

  var litePanel = null;
  var liteHome = null;

  /* 模型下拉在外壳任务页置于工具栏右组；归还业务面板时复位回左组。 */
  function arrangeLiteModel(intoRight) {
    if (!litePanel) return;
    var left = litePanel.querySelector('.cb-left');
    var right = litePanel.querySelector('.cb-right');
    var model = litePanel.querySelector('.cb-model-wrap');
    if (!left || !right || !model) return;
    if (intoRight) {
      if (model.parentNode !== right) right.insertBefore(model, right.firstChild);
    } else if (model.parentNode !== left) {
      var polish = left.querySelector('.cb-pill');
      if (polish) left.insertBefore(model, polish); else left.appendChild(model);
    }
  }

  function relocateLite() {
    var p = $('p-lite-mode');
    if (!p) { litePanel = null; return null; }
    if (!liteHome) liteHome = { parent: p.parentElement, next: p.nextSibling };
    litePanel = p;
    /* 标记业务自带重复头部（外壳头已提供标题/状态/元信息），由 CSS 隐藏。 */
    var liteHead = p.querySelector('.lite-col-left > div');
    if (liteHead) liteHead.classList.add('hx-lite-head');
    arrangeLiteModel(true);
    return p;
  }

  function restoreLite() {
    if (!litePanel) return;
    arrangeLiteModel(false);
    litePanel.classList.remove('hx-lite-middle');
    litePanel.style.display = '';
    if (liteHome && liteHome.parent) {
      if (liteHome.next && liteHome.next.parentNode === liteHome.parent) {
        liteHome.parent.insertBefore(litePanel, liteHome.next);
      } else {
        liteHome.parent.appendChild(litePanel);
      }
    }
  }

  /* 内容页：真实编辑器节点迁入（整节点复用，不 clone）。 */

  var relocatedStage = null;
  var stageHome = null;
  var relocatedMediaBar = null;
  var relocatedActionBar = null;
  var relocatedPane = null;

  function relocateEditor() {
    /* 已迁入且仍挂在文档上：复用缓存引用，避免二次渲染回源面板找不到而误判为空。 */
    if (relocatedStage && DOC.body.contains(relocatedStage)) return relocatedStage;
    var panel = $('p-drafts');
    if (!panel) { relocatedStage = null; return null; }
    var real = panel.querySelector('.workspace-stage') || panel.querySelector('.stage-main-area');
    if (!real) { relocatedStage = null; return null; }
    if (!stageHome) stageHome = { parent: real.parentElement, next: real.nextSibling };
    relocatedStage = real;
    return real;
  }

  function restoreEditor() {
    /* 被迁入中栏 meta / 工具栏的真实业务节点，归还前先接回 stage，避免随自有骨架被清扫后成为孤儿。 */
    var dock = DOC.body.getAttribute('data-preview-dock');
    if (relocatedStage) {
      var root0 = relocatedStage.classList && relocatedStage.classList.contains('workspace-stage')
        ? relocatedStage : relocatedStage.closest('.workspace-stage');
      if (root0 && relocatedMediaBar && relocatedMediaBar.parentNode !== root0) {
        root0.insertBefore(relocatedMediaBar, root0.firstChild);
      }
      if (root0 && relocatedActionBar && relocatedActionBar.parentNode !== root0) {
        root0.appendChild(relocatedActionBar);
      }
      /* pane 若停在 stage 侧右栏（dock=stage），中栏不碰它；否则接回 split-workbench，
         保证离开内容页时真实预览节点留在真实 stage 子树内，不随自有骨架被清扫。 */
      if (dock !== 'stage') {
        var pane = relocatedPane || $('wb-preview-pane');
        if (pane && root0 && !root0.contains(pane)) {
          var wb = root0.querySelector('#split-workbench') || root0;
          wb.appendChild(pane);
        }
      }
    }
    if (!relocatedStage || !stageHome || !stageHome.parent) return;
    if (stageHome.next && stageHome.next.parentNode === stageHome.parent) {
      stageHome.parent.insertBefore(relocatedStage, stageHome.next);
    } else {
      stageHome.parent.appendChild(relocatedStage);
    }
  }

  /* ------------------------------ 真实状态镜像（F-2） ------------------------------ */
  /* 头部 pill 与 meta chip 只镜像真实节点文本；业务回调更新真实节点时由
     MutationObserver 同步，不自造「已与服务器同步 / 未保存 / 保存中」等状态文案。 */

  var mirrorBound = {};
  var mirrorWatch = null;

  var MIRROR_SOURCES = [
    { id: 'wb-save-status', kind: 'save' },
    { id: 'wb-editor-wordcount', kind: 'wc' },
    { id: 'wb-editor-plat-badge', kind: 'plat' }
  ];

  function mirrorSlotEls() {
    var head = $('hxThreadHead');
    var body = $('hxThreadBody');
    return {
      pill: head && head.querySelector('.hx-state-pill'),
      save: body && body.querySelector('.hx-mirror-save .hx-mirror-text'),
      wc: body && body.querySelector('.hx-mirror-wc .hx-mirror-text'),
      plat: body && body.querySelector('.hx-mirror-plat .hx-mirror-text')
    };
  }

  function setMirrorText(el, txt) {
    if (!el) return;
    txt = String(txt == null ? '' : txt).trim();
    el.textContent = txt;
    var chip = el.closest ? el.closest('.hx-meta-chip') : null;
    if (chip) chip.style.display = txt ? '' : 'none';
  }

  function syncMirror() {
    if (currentWs() !== 'content') return;
    var ctx = resolveCtx();
    var slots = mirrorSlotEls();
    /* 未选中草稿：不镜像上一篇遗留的徽标 / 字数 / 状态，隐藏三处镜像 chip，
       头部 pill 保持默认空态文案，避免空态行显示陈旧内容。 */
    if (!ctx || !ctx.draft) {
      setMirrorText(slots.save, '');
      setMirrorText(slots.wc, '');
      setMirrorText(slots.plat, '');
      return;
    }
    var save = $('wb-save-status');
    var wc = $('wb-editor-wordcount');
    var plat = $('wb-editor-plat-badge');
    var saveTxt = save ? save.textContent.trim() : '';
    /* 业务「历史版本视图」是页签状态文案，中栏统一归一为正常保存态表述，避免与历史版本入口重复。 */
    saveTxt = saveTxt.replace(/历史版本视图/g, '已保存到历史版本');
    if (slots.pill && saveTxt) {
      /* pill 保留首点 <i>，文本紧随其后；真实状态为空时保留默认文案不动。 */
      var dot = slots.pill.querySelector('i');
      slots.pill.textContent = '';
      if (dot) slots.pill.appendChild(dot);
      slots.pill.appendChild(DOC.createTextNode(saveTxt));
    }
    setMirrorText(slots.save, saveTxt);
    setMirrorText(slots.wc, wc ? wc.textContent.trim() : '');
    setMirrorText(slots.plat, plat ? plat.textContent.trim() : '');
  }

  function bindMirrorSource(cfg) {
    var prev = mirrorBound[cfg.id];
    if (prev && prev.obs) { try { prev.obs.disconnect(); } catch (e) {} }
    var el = $(cfg.id);
    if (!el || !DOC.body.contains(el)) { mirrorBound[cfg.id] = null; return; }
    var obs = new MutationObserver(function () {
      /* 真实节点被业务替换 / 脱离：按 id 重新查找并重新绑定。 */
      if (!DOC.body.contains(el)) { bindMirrorSource(cfg); return; }
      syncMirror();
    });
    obs.observe(el, { characterData: true, subtree: true, attributes: true, childList: true });
    mirrorBound[cfg.id] = { el: el, obs: obs };
  }

  function startMirror() {
    MIRROR_SOURCES.forEach(bindMirrorSource);
    /* 兜底观察迁入的 stage 子树：源节点被整体替换时按 id 重新绑定。 */
    var watchTarget = relocatedStage || $('p-drafts');
    if (mirrorWatch) { try { mirrorWatch.disconnect(); } catch (e) {} mirrorWatch = null; }
    if (watchTarget && DOC.body.contains(watchTarget)) {
      mirrorWatch = new MutationObserver(function () {
        MIRROR_SOURCES.forEach(function (cfg) {
          var b = mirrorBound[cfg.id];
          if (!b || !DOC.body.contains(b.el)) bindMirrorSource(cfg);
        });
        syncMirror();
      });
      mirrorWatch.observe(watchTarget, {
        childList: true, subtree: true, characterData: true, attributes: true
      });
    }
    syncMirror();
  }

  function stopMirror() {
    Object.keys(mirrorBound).forEach(function (k) {
      var b = mirrorBound[k];
      if (b && b.obs) { try { b.obs.disconnect(); } catch (e) {} }
    });
    mirrorBound = {};
    if (mirrorWatch) { try { mirrorWatch.disconnect(); } catch (e) {} }
    mirrorWatch = null;
  }

  /* ------------------------------ 任务页空态引导卡 ------------------------------ */
  /* 仅当真实消息子节点数为 0 时渲染一张外壳自有引导卡；业务消息出现后
     立即移除，不伪造 AI 正文 / 历史消息。离开任务页时断开观察并拆除。 */

  var guideNode = null;
  var guideObs = null;
  var guideChat = null;
  var guideSuppress = false;

  var GUIDE_PROMPTS = [
    { text: '给我一个今日热点选题，写成小红书种草笔记' },
    { text: '围绕桶装水配送写一篇公众号深度长文' },
    { text: '先出 5 个悬念赛马标题，挑点击率最高的' }
  ];

  /* 判定对话区是否处于空态：无业务子节点，或仅存在业务清空后的占位气泡
     （“对话已清空…”）。用户消息、Agent 回复、草稿载入欢迎语均视为真实内容。 */
  function guideBizChildren(chat) {
    return Array.prototype.filter.call(chat.children, function (c) {
      return c.nodeType === 1 && c.getAttribute('data-owner') !== OWNER_TAG;
    });
  }

  function guideIsPlaceholder(node) {
    if (!node || node.className.indexOf('copilot-msg') === -1) return false;
    var bubble = node.querySelector('.copilot-bubble');
    var txt = bubble ? bubble.textContent.trim() : '';
    /* 业务清空气泡可能带 emoji / 前缀，只要包含「对话已清空」即视为占位，不算真实对话。 */
    return txt.indexOf('对话已清空') >= 0;
  }

  function guideHasContent(chat) {
    var kids = guideBizChildren(chat);
    if (kids.length === 0) return false;
    if (kids.length === 1 && guideIsPlaceholder(kids[0])) return false;
    return true;
  }

  /* 是否存在真实进行中的任务会话：/api/tasks 中存在 running/queued 的真实任务。
     仅在记忆里挂着一篇草稿（state.draftId）不算进行中会话，不能据此压住引导卡。 */
  function hasActiveTask(ctx) {
    var lists = [cache.tasks, (ctx && ctx.state && ctx.state.tasks) || []];
    for (var k = 0; k < lists.length; k++) {
      var arr = lists[k] || [];
      for (var i = 0; i < arr.length; i++) {
        var st = String(arr[i].status || '');
        if (st === 'running' || st === 'queued') return true;
      }
    }
    return false;
  }

  /* 撤卡口径：对话区出现真实业务消息，或存在真实进行中任务；
     仅有草稿记忆、或只剩「对话已清空」占位气泡时不算，引导卡照常出现。 */
  function guideShouldSuppress(ctx, chat) {
    return guideHasContent(chat) || hasActiveTask(ctx);
  }

  function guideHtml() {
    var chips = GUIDE_PROMPTS.map(function (p) {
      return '<span class="hx-guide-chip" data-hx-act="guide-prompt" ' +
        'data-prompt="' + esc(p.text) + '">' + esc(p.text) + '</span>';
    }).join('');
    return '' +
      '<div class="hx-guide-avatar" aria-hidden="true">' + ico('sparkles') + '</div>' +
      '<div class="hx-guide-body">' +
        '<div class="hx-guide-title">一幕 Agent · 就绪</div>' +
        '<p class="hx-guide-copy">描述你想创作的选题、目标平台与字数，我会自动调用爆款算法与多端排版；也可以先点下方建议快速起稿。</p>' +
        '<div class="hx-guide-chips">' + chips + '</div>' +
      '</div>';
  }

  function teardownGuide() {
    if (guideObs) { try { guideObs.disconnect(); } catch (e) {} }
    guideObs = null;
    if (guideNode && guideNode.parentNode) guideNode.parentNode.removeChild(guideNode);
    guideNode = null;
  }

  function attachGuideObs() {
    if (guideObs || !guideChat) return;
    guideObs = new MutationObserver(function () {
      /* 每次 DOM 变动按最新会话内容 / 活动任务重新判定，不用上一轮缓存的抑制标记。 */
      syncGuide(guideChat, guideShouldSuppress(resolveCtx(), guideChat));
    });
    guideObs.observe(guideChat, { childList: true, subtree: true });
  }

  /* 双向同步：空态且无真实进行中会话时确保引导卡在场；出现真实消息 / 任务即撤卡。
     业务晚些写入占位气泡 / 用 innerHTML 清流时，观察器按同一规则复核，
     避免“先撤卡再补卡”的闪烁，也不把占位气泡当成真实对话叠加。 */
  function syncGuide(chat, suppress) {
    if (!chat || !DOC.body.contains(chat)) { teardownGuide(); return; }
    guideChat = chat;
    guideSuppress = !!suppress;
    if (guideSuppress || guideHasContent(chat)) {
      /* 撤卡不等于停止监听：业务后续清屏 / 新任务开启后聊天回到空态，
         观察器需仍挂在当前聊天节点上，按同一口径重新补卡。 */
      teardownGuide();
      attachGuideObs();
      return;
    }
    /* 业务用 innerHTML 清流时会把已挂载的引导卡一并摘掉；此时闭包内旧节点虽在但
       已脱离文档，必须按未挂载处理并重建，否则重挂分支不会再进、引导卡永久消失。 */
    if (!guideNode || !DOC.body.contains(guideNode)) {
      if (guideNode) guideNode = null;
      /* 移除业务清空占位气泡，由引导卡接替空态提示，不叠加。 */
      guideBizChildren(chat).forEach(function (n) {
        if (guideIsPlaceholder(n) && n.parentNode) n.parentNode.removeChild(n);
      });
      guideNode = DOC.createElement('div');
      guideNode.className = 'hx-guide';
      guideNode.setAttribute('data-owner', OWNER_TAG);
      guideNode.innerHTML = guideHtml();
      chat.insertBefore(guideNode, chat.firstChild);
    }
    attachGuideObs();
  }

  function renderGuide(chat, ctx) {
    teardownGuide();
    if (!chat || !DOC.body.contains(chat)) return;
    syncGuide(chat, guideShouldSuppress(ctx, chat));
    /* 业务占位气泡可能晚于迁入回调写入；下一帧再按最新会话 / 任务状态复核一次。 */
    if (typeof WIN.requestAnimationFrame === 'function') {
      WIN.requestAnimationFrame(function () {
        syncGuide(guideChat, guideShouldSuppress(resolveCtx(), guideChat));
      });
    }
  }

  /* ------------------------------ 任务页正文 ------------------------------ */

  function tasksRoot(el) {
    var root = el.querySelector('.hx-tasks-root');
    if (!root) {
      root = DOC.createElement('div');
      root.className = 'hx-tasks-root';
      root.setAttribute('data-owner', OWNER_TAG);
      el.appendChild(root);
    }
    return root;
  }

  function clearChrome(root) {
    var old = root.querySelectorAll('[data-owner="chrome"]');
    Array.prototype.forEach.call(old, function (n) { if (n.parentNode) n.parentNode.removeChild(n); });
  }

  function chromeNode(cls, html) {
    var n = DOC.createElement('div');
    n.className = cls;
    n.setAttribute('data-owner', 'chrome');
    n.innerHTML = html;
    return n;
  }

  function renderTasksBody(el, ctx) {
    ensureRootDelegated();
    var tctx = taskCtx(ctx);
    var root = tasksRoot(el);
    clearChrome(root);

    var metaNode = DOC.createElement('div');
    metaNode.setAttribute('data-owner', 'chrome');
    metaNode.innerHTML = tasksMetaHtml(tctx);
    root.appendChild(metaNode);
    var planHtml = planCardHtml(buildPlan(tctx));
    if (planHtml) root.appendChild(chromeNode('hx-plan-wrap', planHtml));

    var lite = relocateLite();
    if (lite) {
      /* 整节点复用：已在宿主内则只刷新类名，不重复 append、不 clone。 */
      lite.classList.add('hx-lite-middle');
      lite.style.display = 'flex';
      if (lite.parentNode !== root) root.appendChild(lite);
      /* 业务面板跨渲染保留；meta / 计划卡需排在对话面板之前，避免二次渲染后
         顺序变成「对话面板 → meta → 计划卡」。 */
      var planN = root.querySelector('.hx-plan-wrap');
      root.insertBefore(metaNode, lite);
      if (planN) root.insertBefore(planN, lite);
      renderGuide(lite.querySelector('#copilot-chat-messages'), ctx);
    } else {
      root.appendChild(chromeNode('hx-lite-empty',
        '<div class="hx-empty-note">真实对话面板尚未就绪，请稍后重试。</div>'));
      /* 业务面板可能晚于本模块首帧迁入：250ms 后一次性复核，
         面板入 DOM 后再走正常迁入 / 引导卡判定，不依赖 12s 轮询。 */
      if (WIN.setTimeout) {
        WIN.setTimeout(function () {
          if (currentWs() !== 'tasks' || $('p-lite-mode')) return;
          refreshWs('tasks', resolveCtx());
        }, 250);
      }
    }
    loadExtras(tctx);
  }

  /* ------------------------------ 内容页 ------------------------------ */

  function mountMeta(el, html) {
    var meta = DOC.createElement('div');
    meta.setAttribute('data-owner', OWNER_TAG);
    meta.innerHTML = html;
    el.insertBefore(meta, el.firstChild);
    return meta;
  }

  function renderContentBody(el, ctx) {
    ensureRootDelegated();
    var real = relocateEditor();
    var host = el.querySelector('.hx-editor-real');
    /* 已挂载真实编辑器：仅刷新自有 meta 行，不动真实节点（保留焦点/滚动/输入状态）。 */
    if (host && real && host.contains(real)) {
      /* 移除上一轮自有 meta 包裹节点；只删内部 .hx-thread-meta 会把空外壳留在槽位里。 */
      Array.prototype.forEach.call(
        el.querySelectorAll('[data-owner="' + OWNER_TAG + '"] .hx-thread-meta'),
        function (m) {
          var wrap = m.parentNode;
          if (wrap && wrap.getAttribute && wrap.getAttribute('data-owner') === OWNER_TAG && wrap.parentNode) {
            wrap.parentNode.removeChild(wrap);
          } else if (m.parentNode) {
            m.parentNode.removeChild(m);
          }
        }
      );
      /* 清扫历史泄漏的空自有包裹节点（直接挂在槽位下、无元素子节点）。 */
      Array.prototype.forEach.call(el.children, function (n) {
        if (n.nodeType !== 1 || !n.getAttribute) return;
        if (n.getAttribute('data-owner') !== OWNER_TAG) return;
        if (n.querySelector('.hx-thread-meta') || n.querySelector('.hx-editor-wrap')) return;
        if (!n.children.length && n.parentNode) n.parentNode.removeChild(n);
      });
      mountMeta(el, contentMetaHtml(ctx));
      arrangeContentPanels(host);
      startMirror();
      return;
    }
    /* 重建自有骨架前，先把上一轮迁入的真实节点摘出：
       旧 wrap 子树被整体移除时，真实 stage 不能随之被孤儿化。 */
    if (relocatedStage && relocatedStage.parentNode) {
      relocatedStage.parentNode.removeChild(relocatedStage);
    }
    clearOwned(el);
    mountMeta(el, contentMetaHtml(ctx));
    var wrap = DOC.createElement('div');
    wrap.className = 'hx-editor-wrap';
    wrap.setAttribute('data-owner', OWNER_TAG);
    wrap.innerHTML = '<div class="hx-editor-real" id="hxEditorReal">' +
      '<div class="hx-content-toolbar" data-owner="' + OWNER_TAG + '"></div>' +
      '<div class="hx-content-body" data-owner="' + OWNER_TAG + '"></div></div>';
    el.appendChild(wrap);
    host = $('hxEditorReal');
    var bodyCol = host.querySelector('.hx-content-body');
    if (real && bodyCol && bodyCol.parentNode !== bodyCol) bodyCol.appendChild(real);
    arrangeContentPanels(host);
    startMirror();
  }

  /* 内容工作台中栏布局：
     - #hxPreviewHome 是真实 #wb-preview-pane 的稳定“家”，stage 侧停靠时把 pane 搬走、
       归还时再搬回；本模块容忍 pane 暂时不在家（被搬走），不重建、不清空业务状态。
     - 署名 banner 与主工具条是业务真实节点，整节点迁入中栏对应位置，不 clone、不改绑定。 */
  function arrangeContentPanels(host) {
    if (!host) return;
    var home = $('hxPreviewHome');
    if (!home) {
      home = DOC.createElement('div');
      home.id = 'hxPreviewHome';
      home.className = 'hx-preview-home';
      host.querySelector('.hx-content-body').appendChild(home);
    }
    /* 停靠契约：data-preview-dock=stage 时 pane 由 stage 侧持有（右栏舞台），
       本侧不得抢回 home；只保证 home 稳定存在、留空占位。inline/未设置时才把 pane 放回 home。 */
    var dock = DOC.body.getAttribute('data-preview-dock');
    var pane = $('wb-preview-pane');
    if (pane) relocatedPane = pane;
    if (dock !== 'stage' && pane && pane.parentNode !== home) home.appendChild(pane);

    var stageRoot = relocatedStage
      ? (relocatedStage.classList && relocatedStage.classList.contains('workspace-stage')
        ? relocatedStage : relocatedStage.closest('.workspace-stage'))
      : null;
    /* 首次在 stage 内捕获后闭包缓存：二次渲染清扫自有骨架时节点会被摘离 DOM，
       靠 querySelector 再找会变成 null；缓存引用可在下次 arrange 时重新挂回。 */
    if (!relocatedMediaBar && stageRoot) relocatedMediaBar = stageRoot.querySelector('.user-media-badge-bar');
    if (!relocatedActionBar && stageRoot) relocatedActionBar = stageRoot.querySelector('#stage-action-bar');
    var metaRow = DOC.querySelector('#hxThreadBody .hx-thread-meta');
    if (relocatedMediaBar && metaRow && relocatedMediaBar.parentNode !== metaRow) metaRow.appendChild(relocatedMediaBar);

    var toolbar = host.querySelector('.hx-content-toolbar');
    if (relocatedActionBar && toolbar && relocatedActionBar.parentNode !== toolbar) toolbar.appendChild(relocatedActionBar);
  }

  /* —— 历史版本抽屉：复用业务真实历史接口 /api/drafts/{did}/history 与真实回退 restoreDraftVer —— */
  function historyDrawer() {
    var d = $('hxHistoryDrawer');
    if (!d) {
      d = DOC.createElement('div');
      d.id = 'hxHistoryDrawer';
      d.className = 'hx-history-drawer';
      d.hidden = true;
      d.innerHTML =
        '<div class="hx-history-mask" data-hx-act="history-close"></div>' +
        '<aside class="hx-history-panel" role="dialog" aria-label="历史版本">' +
          '<header class="hx-history-head"><b>' + ico('clock') + ' 历史版本</b>' +
          '<button type="button" class="hx-icon-btn" data-hx-act="history-close" data-tip="关闭">' + ico('more') + '</button></header>' +
          '<div class="hx-history-status" id="hxHistoryStatus">读取历史版本…</div>' +
          '<div class="hx-history-list" id="hxHistoryList"></div>' +
        '</aside>';
      slots().body.appendChild(d);
    }
    return d;
  }

  function openHistoryDrawer() {
    var d = historyDrawer();
    d.hidden = false;
    var list = $('hxHistoryList');
    var status = $('hxHistoryStatus');
    list.innerHTML = '';
    status.textContent = '读取历史版本…';
    var ctx = resolveCtx();
    var did = ctx && ctx.draft && ctx.draft.id;
    if (!did) { status.textContent = '未选中草稿'; return; }
    api('/api/drafts/' + encodeURIComponent(did) + '/history').then(function (data) {
      if (!d.isConnected) return;
      var arr = (data && data.history) || [];
      if (!arr.length) {
        status.textContent = '暂无历史版本（系统在每次重大重写或重构前会自动存档）';
        return;
      }
      status.textContent = '';
      arr.forEach(function (h) {
        var item = DOC.createElement('div');
        item.className = 'hx-history-item';
        var when = h.created_at ? new Date(h.created_at * 1000).toLocaleString() : '';
        var score = (h.score != null && h.score !== '') ? ' · 历史评分 ' + h.score : '';
        var main = DOC.createElement('div');
        main.className = 'hx-history-item-main';
        var title = DOC.createElement('div');
        title.className = 'hx-history-item-title';
        title.textContent = h.title || '未命名版本';
        var meta = DOC.createElement('div');
        meta.className = 'hx-history-item-meta';
        meta.textContent = when + score;
        main.appendChild(title); main.appendChild(meta);
        var rb = DOC.createElement('button');
        rb.type = 'button';
        rb.className = 'btn btn-sm ghost';
        rb.textContent = '回退至该版本';
        rb.onclick = function () {
          if (typeof WIN.restoreDraftVer === 'function') WIN.restoreDraftVer(did, h.id);
        };
        item.appendChild(main);
        item.appendChild(rb);
        list.appendChild(item);
      });
    }).catch(function () { status.textContent = '读取历史失败，请稍后重试'; });
  }

  function closeHistoryDrawer() {
    var d = $('hxHistoryDrawer');
    if (d) d.hidden = true;
  }

  function mirrorChip(kind, icon, text) {
    var t = String(text == null ? '' : text).trim();
    return '<span class="hx-meta-chip hx-mirror-' + kind + '" data-mirror="' + kind + '"' +
      (t ? '' : ' style="display:none"') + '>' + ico(icon) +
      '<span class="hx-mirror-text">' + esc(t) + '</span></span>';
  }

  function contentMetaHtml(ctx) {
    var d = ctx.draft;
    var platBadge = $('wb-editor-plat-badge');
    var wc = $('wb-editor-wordcount');
    var save = $('wb-save-status');

    /* 未选中草稿时不镜像上一篇遗留的徽标 / 字数 / 状态，避免空态行显示陈旧文案。 */
    var platTxt = '';
    var wcTxt = '';
    var saveTxt = '';
    if (d) {
      platTxt = platBadge && platBadge.textContent.trim()
        ? platBadge.textContent.trim()
        : (d.platforms && d.platforms.length
          ? d.platforms.map(function (p) { return platLabel(ctx.status, p); }).join(' · ')
          : '');
      wcTxt = wc && wc.textContent.trim() ? wc.textContent.trim() : wordCount(d.body_md) + ' 字';
      saveTxt = save ? save.textContent.trim().replace(/历史版本视图/g, '已保存到历史版本') : '';
    }

    return '<div class="hx-thread-meta">' +
      mirrorChip('plat', 'globe', platTxt) +
      mirrorChip('wc', 'file', wcTxt) +
      mirrorChip('save', 'check', saveTxt) +
      '<span class="hx-meta-spacer"></span>' +
      '<button type="button" class="hx-meta-link" data-hx-act="history-drawer">' + ico('clock') + '历史版本</button></div>';
  }

  function renderContentHead(el, ctx) {
    var d = ctx.draft;
    var saveTxt = '';
    var save = $('wb-save-status');
    if (save) saveTxt = save.textContent.trim().replace(/历史版本视图/g, '已保存到历史版本');
    mountOwnedHead(el,
      '<div class="hx-thread-title">' +
        '<div class="hx-crumb">内容工作台 ' + ico('chevron-right') + (d ? esc(trim(d.title, 12)) : '草稿') + '</div>' +
        '<div class="hx-title-line"><h1>' + esc(d ? (d.title || '未选择草稿') : '未选择草稿') + '</h1>' +
        '<span class="hx-state-pill static">' + esc(d ? (saveTxt || '待审') : '空态') + '</span></div>' +
      '</div>' +
      '<div class="hx-thread-actions">' +
        '<button type="button" class="hx-icon-btn" data-hx-act="save" data-tip="保存草稿">' + ico('check') + '</button>' +
        '<button type="button" class="hx-icon-btn" data-hx-act="share" data-tip="分享草稿">' + ico('share') + '</button>' +
        '<button type="button" class="hx-icon-btn" data-hx-act="stage" data-tip="展开 / 收起预览">' + ico('panel') + '</button>' +
        '<button type="button" class="hx-icon-btn" data-hx-act="more" data-tip="更多">' + ico('more') + '</button>' +
      '</div>');
  }

  /* ------------------------------ 注册表 / 插槽归属守卫 ------------------------------ */

  var renderers = {
    tasks: { head: renderTasksHead, body: renderTasksBody },
    content: { head: renderContentHead, body: renderContentBody }
  };

  /* 判断当前工作区是否由本模块负责：core 注册表中已有别人的实现则一律跳过，
     不清空、不写骨架、不覆写真实业务面板。 */
  function ownsWorkspace(ws) {
    var h = hx();
    if (h && h._reg && h._reg.thread) {
      var impl = h._reg.thread[ws];
      if (impl && impl._hxOwner !== OWNER_TAG) return false;
    }
    return !!OWNED_WS[ws];
  }

  /* 只移除本模块上一次渲染的自有节点；插槽内别的模块迁入的真实面板一律保留。 */
  function clearOwned(slot) {
    if (!slot) return;
    var owned = slot.querySelectorAll ? slot.querySelectorAll('[data-owner="' + OWNER_TAG + '"]') : [];
    Array.prototype.forEach.call(owned || [], function (n) { if (n.parentNode) n.parentNode.removeChild(n); });
    var kids = slot.childNodes || slot.children || [];
    Array.prototype.forEach.call(kids, function (n) {
      if (n.nodeType === 1 && n.getAttribute && n.getAttribute('data-owner') === OWNER_TAG) slot.removeChild(n);
    });
  }

  function mountOwnedHead(el, innerHtml) {
    /* 头部槽只承载线程标题 chrome，不存放真实业务面板；切换工作区时清掉
       上一工作区残留的别的模块标题，避免新旧标题叠加。 */
    el.innerHTML = '';
    var node = DOC.createElement('div');
    node.className = 'hx-thread-head';
    node.setAttribute('data-owner', OWNER_TAG);
    node.innerHTML = innerHtml;
    el.appendChild(node);
  }

  function slots() {
    var thread = $('hxThread');
    if (!thread) {
      thread = DOC.createElement('div');
      thread.id = 'hxThread';
      var main = DOC.querySelector('.main-wrapper > main');
      if (main) main.appendChild(thread); else DOC.body.appendChild(thread);
    }
    var head = $('hxThreadHead');
    var body = $('hxThreadBody');
    if (!head) { head = DOC.createElement('div'); head.id = 'hxThreadHead'; thread.appendChild(head); }
    if (!body) { body = DOC.createElement('div'); body.id = 'hxThreadBody'; thread.appendChild(body); }
    return { head: head, body: body };
  }

  function refreshWs(ws, ctx) {
    if (!ownsWorkspace(ws)) return;
    var r = renderers[ws];
    if (!r) return;
    /* core 直调注册实现时传入的 ctx.draft 只是 draftId 字符串，这里统一用
       本模块 resolveCtx() 解析成草稿对象，避免标题/状态取到 undefined。 */
    ctx = resolveCtx();
    var s = slots();
    try { r.head(s.head, ctx); } catch (e) { console.warn('[hx-thread] head', e); }
    try { r.body(s.body, ctx); } catch (e) { console.warn('[hx-thread] body', e); }
    ensureRootDelegated();
    syncStageButtons();
  }

  function currentWs() {
    var h = hx();
    return (h && h.state && h.state.workspace) || 'tasks';
  }

  /* 只移除本模块标记为自有节点的 chrome；插槽内别的模块迁入的真实面板一律保留。 */
  function sweepOwned(slot) {
    if (!slot) return;
    var mine = [];
    Array.prototype.forEach.call(slot.children, function (n) {
      if (n.nodeType === 1 && n.getAttribute && n.getAttribute('data-owner') === OWNER_TAG) mine.push(n);
    });
    mine.forEach(function (n) { if (n.parentNode) n.parentNode.removeChild(n); });
  }

  /* 离开本模块负责的工作区：归还迁入的真实面板、解除真实状态镜像观察，
     并清扫头部 / 正文里本模块的自有 chrome，避免上一工作区标题、字数、平台、
     状态残留在插槽中；别的模块迁入的真实面板与根节点一律不动。 */
  function detachOwned(ws) {
    var body = $('hxThreadBody');
    var head = $('hxThreadHead');
    if (ws === 'tasks') {
      teardownGuide();
      restoreLite();
    } else if (ws === 'content') {
      stopMirror();
      closeHistoryDrawer();
      restoreEditor();
    }
    sweepOwned(body);
    sweepOwned(head);
  }

  /* 切到任务页时业务侧会清空编辑器/选中卡片，但 core 保留 state.draftId；
     回到内容页若选中态未恢复，按 retained draftId 调公开业务函数把该稿
     重新载入（不改 draftId、不重写业务逻辑），避免头部标题与空编辑器不一致。 */
  function ensureBusinessDraft(ctx) {
    if (currentWs() !== 'content') return;
    var id = ctx.state.draftId || domActiveDraftId();
    if (!id) return;
    var on = DOC.querySelector('#draft-list-container .draft-card.on input[data-id]');
    if (on && String(on.getAttribute('data-id')) === String(id)) return;
    var input = $('wb-editor-input');
    if (input && input.value.trim()) return;
    if (restoredFor === String(id)) return;
    restoredFor = String(id);
    var h = hx();
    if (h && typeof h.openDraft === 'function') { try { h.openDraft(String(id)); return; } catch (e) {} }
    if (typeof WIN.selectDraft === 'function') { try { WIN.selectDraft(String(id)); } catch (e) {} }
  }

  var prevWs = null;

  function refreshActive() {
    if (!isHarness()) return;
    var ws = currentWs();
    if (prevWs && prevWs !== ws) { restoredFor = null; detachOwned(prevWs); }
    prevWs = ws;
    var ctx = resolveCtx();
    refreshWs(ws, ctx);
    setupPoll(ws);
    ensureBusinessDraft(ctx);
  }

  /* ------------------------------ 动作分发 ------------------------------ */

  function openDraft(id) {
    var h = hx();
    if (h && typeof h.openDraft === 'function') { try { h.openDraft(id); return; } catch (e) {} }
    if (typeof WIN.selectDraft === 'function') { try { WIN.selectDraft(id); } catch (e) {} }
    if (typeof WIN.switchToPage === 'function') { try { WIN.switchToPage('drafts'); } catch (e) {} }
  }

  function actDispatch(act, btn, ctx, el) {
    var h = hx();
    switch (act) {
      case 'share':
        toast('分享面板即将接入');
        break;
      case 'pin':
        btn.classList.toggle('on');
        toast(btn.classList.contains('on') ? '已钉住当前任务' : '已取消钉住');
        break;
      case 'stage':
        if (h && typeof h.toggleStage === 'function') h.toggleStage();
        syncStageButtons();
        break;
      case 'more':
        toast('更多操作菜单即将接入');
        break;
      case 'plan-toggle': {
        var card0 = btn.closest('.hx-plan-card');
        if (!card0) break;
        planCollapsed = !card0.classList.contains('is-collapsed');
        card0.classList.toggle('is-collapsed', planCollapsed);
        btn.setAttribute('aria-expanded', String(!planCollapsed));
        break;
      }
      case 'plan': {
        var card = el.querySelector('.hx-plan-card');
        if (card) card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        break;
      }
      case 'time':
        toast('耗时来自已完成的真实任务记录');
        break;
      case 'open-draft':
        openDraft(btn.getAttribute('data-did'));
        break;
      case 'save': {
        var saveBtn = $('btn-wb-save');
        if (saveBtn) saveBtn.click();
        else if (typeof WIN.saveCurrentPlatformContent === 'function') WIN.saveCurrentPlatformContent();
        break;
      }
      case 'history':
        if (typeof WIN.switchPlatformTab === 'function') { try { WIN.switchPlatformTab('history'); } catch (e) {} }
        break;
      case 'history-drawer':
        openHistoryDrawer();
        break;
      case 'history-close':
        closeHistoryDrawer();
        break;
      case 'guide-prompt': {
        var guideInput = $('copilot-input');
        if (!guideInput) break;
        guideInput.value = btn.getAttribute('data-prompt') || '';
        guideInput.dispatchEvent(new WIN.Event('input', { bubbles: true }));
        if (typeof WIN.syncCopilotInputState === 'function') {
          try { WIN.syncCopilotInputState(); } catch (e) {}
        }
        guideInput.focus();
        break;
      }
      default:
        break;
    }
  }

  /* 委托绑在线程根容器上，同时覆盖页头（share/pin/stage/more）与正文动作；
     幂等标记挂根节点，重复刷新不会叠加监听、不会一次点击触发两遍。 */
  function threadRoot() {
    var r = $('hxThread');
    if (r) return r;
    var s = slots();
    return (s.head && s.head.parentNode) || (s.body && s.body.parentNode) || null;
  }

  function ensureRootDelegated() {
    var root = threadRoot();
    if (!root) return;
    if (root.dataset.hxBound === '1') return;
    root.dataset.hxBound = '1';
    root.addEventListener('click', function (e) {
      if (!isHarness()) return;
      var b = e.target.closest ? e.target.closest('[data-hx-act]') : null;
      if (!b) return;
      try { actDispatch(b.getAttribute('data-hx-act'), b, resolveCtx(), root); }
      catch (err) { console.warn('[hx-thread]', err); }
    });
  }

  /* 舞台按钮激活态与 body[data-stage] 真实同步：刷新 / 切工作区后由头部渲染或
     core 的 stage 事件重新对齐，不会出现「按钮已收起但舞台还开着」。 */
  function syncStageButtons() {
    var open = DOC.body.getAttribute('data-stage') !== 'closed';
    var btns = DOC.querySelectorAll('[data-hx-act="stage"]');
    Array.prototype.forEach.call(btns, function (b) {
      b.setAttribute('aria-pressed', open ? 'true' : 'false');
      b.classList.toggle('is-on', open);
    });
  }

  /* ------------------------------ 数据拉取 / 轮询 ------------------------------ */

  function loadExtras(ctx) {
    var d = ctx.draft;
    if (!d || !d.id) return;
    if (cache.extraFor === String(d.id)) return;
    cache.extraFor = String(d.id);
    cache.history = [];
    cache.images = [];
    api('/api/drafts/' + d.id + '/history').then(function (h) {
      cache.history = (h && h.history) || [];
      if (currentWs() === 'tasks') refreshWs('tasks', resolveCtx());
    });
    api('/api/drafts/' + d.id + '/images').then(function (im) {
      cache.images = Array.isArray(im) ? im : [];
      if (currentWs() === 'tasks') refreshWs('tasks', resolveCtx());
    });
  }

  function loadTasks() {
    api('/api/tasks').then(function (d) {
      cache.tasks = (d && d.tasks) || [];
      if (currentWs() === 'tasks') refreshWs('tasks', resolveCtx());
    });
  }

  function stopPoll() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  function setupPoll(ws) {
    stopPoll();
    if (ws !== 'tasks') return;
    loadTasks();
    pollTimer = setInterval(loadTasks, 12000);
  }

  function onEvent() {
    if (!isHarness()) return;
    refreshActive();
  }

  /* ------------------------------ 启动 ------------------------------ */

  function register() {
    var h = hx();
    if (!h || typeof h.registerThread !== 'function') return false;
    Object.keys(renderers).forEach(function (ws) {
      var r = renderers[ws];
      var impl = {
        _hxOwner: OWNER_TAG,
        head: function (el) { r.head(el, resolveCtx()); },
        body: function (el) { r.body(el, resolveCtx()); },
        refresh: function () { refreshWs(ws, resolveCtx()); }
      };
      h.registerThread(ws, impl);
    });
    ['workspace', 'state', 'drafts', 'draft', 'stage'].forEach(function (ev) {
      if (typeof h.on === 'function') h.on(ev, onEvent);
    });
    return true;
  }

  function boot() {
    if (!isHarness()) return;
    if (register()) {
      refreshActive();
      return;
    }
    var h = hx();
    if (h && h.ready && typeof h.ready.then === 'function') {
      h.ready.then(function () { register(); refreshActive(); });
    } else {
      var tries = 0;
      var iv = setInterval(function () {
        if (register() || ++tries > 20) { clearInterval(iv); refreshActive(); }
      }, 150);
    }
  }

  if (DOC.readyState === 'loading') DOC.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
