/* SPDX-License-Identifier: BUSL-1.1 */
/* ==========================================================================
   V11 · 三栏工作台外壳（P0）
   --------------------------------------------------------------------------
   职责边界（严格）：
     1. 三栏宽度拖拽 + 记忆；
     2. 右栏资产台：把成稿 / 图片 / 视频 / 数据四类既有产出聚合展示；
     3. 专注态（右栏放大到整屏）；
     4. 经典版往返（?legacy=1 ↔ 新版）。
   不做的事：不接管路由、不改任何业务函数、不写数据库。
   所有数据都来自既有只读接口，所有动作都调用既有函数。
   ========================================================================== */
(function () {
  'use strict';

  var DOC = document;
  var WIN = window;

  var LS_W = 'yimu.shell.w';
  var LS_TAB = 'yimu.shell.tab';
  var LS_MODE = 'yimu.shell.mode';
  var BREAK = 1180;                 // 低于该宽度不启用三栏
  var MIN_RAIL = 200, MAX_RAIL = 420;
  var MIN_PANEL = 300, MAX_PANEL = 680;
  var MIN_MAIN = 460;               // 中栏保底宽度，宁可挤右栏也不压垮主台

  var ST = {
    tab: 'doc',
    draft: null,
    plat: 'wechat_mp',
    focus: false,
    imgs: [],
    lbIdx: 0,
    seq: 0
  };

  /* ------------------------------ 小工具 ------------------------------ */
  function byId(id) { return DOC.getElementById(id); }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function clamp(n, a, b) { return Math.max(a, Math.min(b, n)); }

  function px(n) { return Math.round(n) + 'px'; }

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

  function htmlToText(h) {
    var d = DOC.createElement('div');
    d.innerHTML = h || '';
    return (d.textContent || '').replace(/\s+/g, '');
  }

  /* ------------------------------ 数据接口 ------------------------------ */
  function apiGet(path) {
    if (typeof WIN.api === 'function') return WIN.api(path);
    return fetch(path, { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  function apiPost(path, body) {
    if (typeof WIN.api === 'function') {
      return WIN.api(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {})
      });
    }
    return fetch(path, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (r) { return r.json(); });
  }

  function draftList() {
    // 说明：主界面用 `let S` 声明全局状态，属于脚本级词法绑定，不会挂到 window 上，
    //       因此这里必须用裸标识符访问，不能写 window.S。
    try {
      /* eslint-disable no-undef */
      return (typeof S !== 'undefined' && S && S.drafts) || [];
      /* eslint-enable no-undef */
    } catch (e) { return []; }
  }

  function currentDraftId() {
    var id = activeDraftId();
    if (id) return id;
    var ds = draftList();
    return ds.length ? ds[0].id : null;
  }

  // 严格意义的「正在编辑的稿」：内容工作台的 curDraft，或极简模式的当前稿。
  // 两者都没有时返回 null（右栏改为展示最近产出列表，避免与中栏空态打架）。
  function activeDraftId() {
    try {
      /* eslint-disable no-undef */
      if (typeof curDraft !== 'undefined' && curDraft) return curDraft;
      /* eslint-enable no-undef */
    } catch (e) { /* 极早期脚本尚未执行 */ }
    try {
      /* eslint-disable no-undef */
      if (typeof currentLiteDraftId !== 'undefined' && currentLiteDraftId) return currentLiteDraftId;
      /* eslint-enable no-undef */
    } catch (e) { /* 同上 */ }
    return null;
  }

  function draftMeta(id) {
    var ds = draftList();
    for (var i = 0; i < ds.length; i++) {
      if (ds[i].id === id) return ds[i];
    }
    return null;
  }

  function toast(msg) {
    if (typeof WIN.toast === 'function') WIN.toast(msg);
  }

  // 优先走全局 i18n 引擎，取不到就退中文原文
  function tr(key, fallback) {
    try {
      if (typeof WIN.t === 'function') {
        var v = WIN.t(key);
        if (v && v !== key) return v;
      }
    } catch (e) { /* ignore */ }
    return fallback;
  }

  /* ------------------------------ 三栏宽度 ------------------------------ */
  function defaultWidths() {
    // 屏幕越窄，两侧收得越紧，把宽度让给中栏
    var vw = WIN.innerWidth || 1440;
    if (vw < 1320) return { rail: 210, panel: 340 };
    if (vw < 1400) return { rail: 224, panel: 360 };
    return { rail: 248, panel: 400 };
  }

  function readWidths() {
    var w = {};
    try { w = JSON.parse(localStorage.getItem(LS_W) || '{}') || {}; } catch (e) { w = {}; }
    var def = defaultWidths();
    var rail = clamp(parseInt(w.rail, 10) || def.rail, MIN_RAIL, MAX_RAIL);
    var panel = clamp(parseInt(w.panel, 10) || def.panel, MIN_PANEL, MAX_PANEL);
    return fitWidths(rail, panel);
  }

  function fitWidths(rail, panel) {
    var vw = WIN.innerWidth || 1440;
    rail = clamp(rail, MIN_RAIL, MAX_RAIL);
    panel = clamp(panel, MIN_PANEL, MAX_PANEL);
    // 先保中栏，再压右栏，最后压左栏
    if (rail + panel + MIN_MAIN > vw) panel = Math.max(MIN_PANEL, vw - rail - MIN_MAIN);
    if (rail + panel + MIN_MAIN > vw) rail = Math.max(MIN_RAIL, vw - panel - MIN_MAIN);
    return { rail: Math.round(rail), panel: Math.round(panel) };
  }

  function applyWidths(w) {
    DOC.documentElement.style.setProperty('--railw', w.rail + 'px');
    DOC.documentElement.style.setProperty('--panelw', w.panel + 'px');
  }

  function saveWidths(w) {
    try { localStorage.setItem(LS_W, JSON.stringify(w)); } catch (e) { /* 隐私模式 */ }
  }

  function currentWidths() {
    var cs = getComputedStyle(DOC.documentElement);
    return {
      rail: parseInt(cs.getPropertyValue('--railw'), 10) || 248,
      panel: parseInt(cs.getPropertyValue('--panelw'), 10) || 400
    };
  }

  function initResize() {
    var body = DOC.body;
    var drag = null;

    function onDown(ev, side) {
      if (ev.button != null && ev.button !== 0) return;
      ev.preventDefault();
      var w = currentWidths();
      drag = {
        side: side,
        x: ev.clientX,
        rail: w.rail,
        panel: w.panel
      };
      // 抓住指针：拖动过程中手柄自身会跟着移动，不捕获会丢事件
      try { ev.currentTarget.setPointerCapture(ev.pointerId); } catch (e) { /* 老浏览器 */ }
      body.classList.add('rz-drag');
      body.style.cursor = 'col-resize';
    }

    function onMove(ev) {
      if (!drag) return;
      var dx = ev.clientX - drag.x;
      var next;
      if (drag.side === 'l') {
        next = fitWidths(drag.rail + dx, drag.panel);
      } else {
        next = fitWidths(drag.rail, drag.panel - dx);
      }
      applyWidths(next);
      drag.last = next;
    }

    function onUp() {
      if (!drag) return;
      body.classList.remove('rz-drag');
      body.style.cursor = '';
      if (drag.last) saveWidths(drag.last);
      drag = null;
      fitPaper();
    }

    var hl = byId('rzLeft');
    var hr = byId('rzRight');
    if (hl) {
      hl.addEventListener('pointerdown', function (e) { onDown(e, 'l'); });
      hl.addEventListener('dblclick', function () { resetWidths(); });
    }
    if (hr) {
      hr.addEventListener('pointerdown', function (e) { onDown(e, 'r'); });
      hr.addEventListener('dblclick', function () { resetWidths(); });
    }
    WIN.addEventListener('pointermove', onMove, { passive: true });
    WIN.addEventListener('pointerup', onUp);
    WIN.addEventListener('pointercancel', onUp);
    WIN.addEventListener('blur', onUp);

    WIN.addEventListener('resize', function () {
      if (DOC.body.getAttribute('data-shell') !== 'v2') return;
      var w = currentWidths();
      applyWidths(fitWidths(w.rail, w.panel));
      fitPaper();
    });
  }

  function resetWidths() {
    var w = defaultWidths();
    applyWidths(w);
    saveWidths(w);
    toast('已恢复默认栏宽');
  }

  /* ------------------------------ 专注态 ------------------------------ */
  function setFocus(on) {
    ST.focus = !!on;
    if (ST.focus) DOC.body.setAttribute('data-focus', 'on');
    else DOC.body.removeAttribute('data-focus');
    setTimeout(fitPaper, 60);
  }

  function toggleFocus() { setFocus(!ST.focus); }

  /* ------------------------------ 灯箱 ------------------------------ */
  var LB = null;

  function ensureLB() {
    if (LB) return LB;
    LB = DOC.createElement('div');
    LB.className = 'a-lb';
    LB.innerHTML =
      '<div class="bar">' +
        '<span id="aLbName">图片预览</span>' +
        '<span class="sp"></span>' +
        '<span class="idx" id="aLbIdx">1 / 1</span>' +
        '<button type="button" data-lb="prev">← 上一张</button>' +
        '<button type="button" data-lb="next">下一张 →</button>' +
        '<button type="button" data-lb="close">✕ 关闭</button>' +
      '</div>' +
      '<div class="stage"><img id="aLbImg" alt=""></div>';
    DOC.body.appendChild(LB);

    LB.addEventListener('click', function (e) {
      var t = e.target.closest('[data-lb]');
      if (t) {
        var act = t.getAttribute('data-lb');
        if (act === 'close') closeLB();
        else stepLB(act === 'next' ? 1 : -1);
        return;
      }
      if (e.target === LB || e.target.id === 'aLbImg') closeLB();
    });
    return LB;
  }

  function openLB(list, idx) {
    ensureLB();
    ST.imgs = list || [];
    ST.lbIdx = clamp(idx || 0, 0, Math.max(0, ST.imgs.length - 1));
    paintLB();
    LB.classList.add('on');
  }

  function paintLB() {
    var it = ST.imgs[ST.lbIdx];
    if (!it) return;
    var img = byId('aLbImg');
    img.src = it.url;
    img.alt = it.name || '';
    byId('aLbName').textContent = it.name || '图片预览';
    byId('aLbIdx').textContent = (ST.lbIdx + 1) + ' / ' + ST.imgs.length;
  }

  function stepLB(d) {
    if (!ST.imgs.length) return;
    ST.lbIdx = (ST.lbIdx + d + ST.imgs.length) % ST.imgs.length;
    paintLB();
  }

  function closeLB() { if (LB) LB.classList.remove('on'); }

  function lbOpen() { return !!(LB && LB.classList.contains('on')); }

  /* ------------------------------ 渲染：骨架 ------------------------------ */
  function totalDrafts() { return draftList().length; }

  function emptyState(icon, text, actLabel, act) {
    return '<div class="a-empty"><div class="ic">' + icon + '</div>' +
      '<div class="tx">' + text + '</div>' +
      (actLabel ? '<button class="abtn" type="button" data-act="' + act + '">' + actLabel + '</button>' : '') +
      '</div>';
  }

  function render() {
    var box = byId('assetsBody');
    if (!box) return;
    box.scrollTop = 0;

    var tabs = DOC.querySelectorAll('#assetsTabs .assets-tab');
    for (var i = 0; i < tabs.length; i++) {
      tabs[i].classList.toggle('on', tabs[i].getAttribute('data-at') === ST.tab);
    }
    var hint = byId('assetsHint');
    if (hint) {
      hint.textContent = ST.focus
        ? tr('shell_hint_focus', '专注查看 · Esc 退出')
        : tr('shell_hint_follow', '跟随左侧所选稿件');
    }

    var seq = ++ST.seq;
    if (ST.tab === 'doc') renderDoc(box, seq);
    else if (ST.tab === 'img') renderImg(box, seq);
    else if (ST.tab === 'video') renderVideo(box, seq);
    else renderData(box, seq);
  }

  function guard(seq) { return seq === ST.seq; }

  /* ------------------------------ 成稿 ------------------------------ */
  function platBar() {
    var plats = [
      ['wechat_mp', '公众号'],
      ['xhs', '小红书'],
      ['toutiao', '头条'],
      ['douyin', '抖音']
    ];
    return '<div class="a-plats">' + plats.map(function (p) {
      return '<span class="a-plat' + (ST.plat === p[0] ? ' on' : '') +
        '" data-act="plat" data-plat="' + p[0] + '">' + p[1] + '</span>';
    }).join('') + '</div>';
  }

  function renderDoc(box, seq) {
    var id = ST.draft || activeDraftId();
    var meta = id ? draftMeta(id) : null;
    if (!id || !meta) {
      var ds = draftList();
      if (!ds.length) {
        box.innerHTML = emptyState('📝',
          '稿库还是空的。去「灵感与选题」跑一篇，成稿会自动出现在这里。',
          '去挖一个选题', 'open-inspire');
        return;
      }
      // 中栏还没选稿（或所选稿已删除）→ 这里直接给出最近产出，点一下载入中栏
      ST.draft = null;
      box.innerHTML = '<div class="a-label">最近产出<span class="sp"></span>' +
        '<span class="r" data-act="open-drafts">全部稿件 ↗</span></div>' +
        ds.slice(0, 8).map(function (d) {
          var sc = (d.score != null && d.score !== '') ? Math.round(Number(d.score)) : null;
          return '<div class="a-row" data-act="pick" data-id="' + esc(d.id) + '" ' +
            'title="点击载入内容工作台">' +
            '<b>' + (sc == null ? '·' : sc) + '</b>' +
            '<span>' + esc(d.title || '未命名') + '</span>' +
            '<i>' + (d.imgs || 0) + ' 图</i></div>';
        }).join('');
      return;
    }
    ST.draft = id;
    var m = draftMeta(id) || {};
    var score = (m.score != null && m.score !== '') ? Math.round(Number(m.score)) : null;

    box.innerHTML =
      '<div class="a-score">' +
        '<div class="n">' + (score == null ? '—' : score) + (score == null ? '' : '<small>/100</small>') + '</div>' +
        '<div class="d"><b>' + esc(m.title || '未命名稿件') + '</b>' +
          (score == null ? '尚未评分' : '爆款指数 · ' + (m.grade || '') ) +
          ' · ' + (m.imgs || 0) + ' 图 · ' + (m.cards || 0) + ' 卡</div>' +
      '</div>' +
      platBar() +
      '<div class="a-paper"><div class="loading">排版渲染中…</div></div>' +
      '<div class="a-meta"><span>平台预览与左侧工作台完全同源</span>' +
        '<span class="sp" style="flex:1"></span>' +
        '<span data-act="open-drafts" style="cursor:pointer;color:var(--primary)">在当前工作台编辑 ↗</span></div>' +
      '<div class="a-label">版本历史<span class="sp"></span>' +
        '<span class="r" data-act="reload">刷新</span></div>' +
      '<div id="aHistory"><div class="a-row"><span>读取中…</span></div></div>';

    apiGet('/api/drafts/' + encodeURIComponent(id) + '/raw/' + ST.plat).then(function (r) {
      if (!guard(seq)) return;
      var paper = box.querySelector('.a-paper');
      if (!paper) return;
      var html = (r && (r.html || r.text || '')) || '';
      paintPaper(paper, html);
    }).catch(function (e) {
      if (!guard(seq)) return;
      var paper = box.querySelector('.a-paper');
      if (paper) paper.innerHTML = '<div class="loading">预览加载失败：' + esc(e.message) + '</div>';
    });

    apiGet('/api/drafts/' + encodeURIComponent(id) + '/history').then(function (r) {
      if (!guard(seq)) return;
      var box2 = byId('aHistory');
      if (!box2) return;
      var hs = (r && r.history) || [];
      if (!hs.length) {
        box2.innerHTML = '<div class="a-row"><span>暂无历史快照，改写一次就会自动留档</span></div>';
        return;
      }
      box2.innerHTML = hs.slice(0, 6).map(function (h, i) {
        return '<div class="a-row' + (i === 0 ? ' on' : '') + '" data-act="restore" data-hid="' +
          esc(h.id) + '" data-title="' + esc(h.title || '') + '" title="点击回滚到该版本">' +
          '<b>v' + (hs.length - i) + '</b>' +
          '<span>' + esc(h.title || '未命名') + '</span>' +
          '<i>' + esc(fmtTime(h.created_at)) + '</i></div>';
      }).join('');
    }).catch(function () { /* 历史失败不影响主预览 */ });
  }

  function paintPaper(paper, bodyHtml) {
    var css = 'html,body{margin:0;padding:0}' +
      'body{padding:26px 22px 40px;font:15px/1.85 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;' +
      'color:#1f2937;background:#fff;word-break:break-word;-webkit-font-smoothing:antialiased}' +
      'img{max-width:100%!important;height:auto!important;border-radius:8px;display:block;margin:12px auto}' +
      'h1{font-size:20px;line-height:1.5;margin:0 0 14px}h2{font-size:17px;margin:20px 0 10px}' +
      'h3{font-size:16px;margin:18px 0 8px}p{margin:0 0 12px}' +
      'blockquote{margin:14px 0;padding:8px 12px;border-left:3px solid #f0883e;background:#fdf6f1;color:#6b7280}' +
      'table{width:100%;border-collapse:collapse;font-size:13px}td,th{border:1px solid #e5e7eb;padding:6px 8px}' +
      'a{color:#ea580c}';
    var doc = '<!doctype html><html><head><meta charset="utf-8">' +
      '<meta name="viewport" content="width=device-width,initial-scale=1">' +
      '<style>' + css + '</style></head><body>' + (bodyHtml || '<p style="color:#94a3b8">暂无排版内容</p>') +
      '</body></html>';

    var ifr = DOC.createElement('iframe');
    ifr.setAttribute('sandbox', 'allow-same-origin');
    ifr.setAttribute('referrerpolicy', 'no-referrer');
    ifr.setAttribute('title', '成稿预览');
    ifr.srcdoc = doc;
    paper.innerHTML = '';
    paper.appendChild(ifr);
    fitPaper();
  }

  function fitPaper() {
    var ifrs = DOC.querySelectorAll('.a-paper iframe');
    if (!ifrs.length) return;
    var h;
    if (ST.focus) {
      h = Math.max(420, WIN.innerHeight - 236);
    } else {
      h = clamp(WIN.innerHeight * 0.52, 300, 560);
    }
    for (var i = 0; i < ifrs.length; i++) ifrs[i].style.height = px(h);
  }

  /* ------------------------------ 图片 ------------------------------ */
  function renderImg(box, seq) {
    var id = ST.draft || currentDraftId();
    if (!id) {
      box.innerHTML = emptyState('🖼️', '还没有图片资产。稿件出图后，封面与配图会出现在这里。', '去生成图片', 'open-drafts');
      return;
    }
    box.innerHTML = '<div class="a-label">稿件配图<span class="sp"></span><span class="r" data-act="reload">刷新</span></div>' +
      '<div class="a-thumbs" id="aThumbs"><div class="a-row"><span>读取中…</span></div></div>';

    apiGet('/api/drafts/' + encodeURIComponent(id) + '/images').then(function (r) {
      if (!guard(seq)) return;
      var list = Array.isArray(r) ? r : (r && r.images) || [];
      list = list.map(function (x) {
        if (typeof x === 'string') return { url: x, name: x.split('/').pop() };
        return { url: x.url || x.path || '', name: x.name || x.title || '' };
      }).filter(function (x) { return !!x.url; });

      ST.imgs = list;
      var cnt = byId('assetsImgCount');
      if (cnt) cnt.textContent = list.length ? String(list.length) : '';

      var host = byId('aThumbs');
      if (!host) return;
      if (!list.length) {
        host.outerHTML = emptyState('🖼️', '这篇稿子还没有出图。在内容工作台点「一键配图」后回来刷新即可。',
          '去配图', 'open-drafts');
        return;
      }
      host.innerHTML = list.map(function (x, i) {
        return '<div class="a-thumb" data-act="zoom" data-idx="' + i + '" title="点击放大">' +
          '<img src="' + esc(x.url) + '" alt="' + esc(x.name) + '" loading="lazy">' +
          '<i>' + esc(x.name || ('图 ' + (i + 1))) + '</i></div>';
      }).join('');
    }).catch(function (e) {
      if (!guard(seq)) return;
      var host = byId('aThumbs');
      if (host) host.innerHTML = '<div class="a-row"><span>图片读取失败：' + esc(e.message) + '</span></div>';
    });
  }

  /* ------------------------------ 视频 ------------------------------ */
  function renderVideo(box, seq) {
    box.innerHTML = '<div class="a-label">成片库<span class="sp"></span><span class="r" data-act="reload">刷新</span></div>' +
      '<div id="aVideos"><div class="a-row"><span>读取中…</span></div></div>';

    apiGet('/api/video/tasks').then(function (r) {
      if (!guard(seq)) return;
      var list = (r && r.tasks) || [];
      var host = byId('aVideos');
      if (!host) return;
      if (!list.length) {
        host.outerHTML = emptyState('🎬', '还没有成片。影音工坊跑完一条短视频或 AI 短剧后，这里可以直接播放。',
          '刷新成片库', 'reload');
        return;
      }
      host.innerHTML = list.slice(0, 6).map(function (t, i) {
        var aspect = t.aspect === '9:16' ? '9/16' : '16/9';
        return '<div class="a-video"' + (i > 0 ? ' style="margin-top:10px"' : '') + '>' +
          '<video controls preload="metadata" style="aspect-ratio:' + aspect + ';object-fit:contain" src="' +
          esc(t.url) + '"></video></div>' +
          '<div class="a-meta" style="padding:0 2px 8px"><b>' + esc(t.title || t.tid || '') + '</b>' +
          '<span>' + esc(t.aspect || '') + (t.seconds ? ' · ' + t.seconds + 's' : '') +
          (t.size_kb ? ' · ' + t.size_kb + 'KB' : '') + '</span>' +
          '<span style="flex:1"></span><i style="font-style:normal;opacity:.65">' + esc(fmtTime(t.mtime)) + '</i></div>';
      }).join('');
    }).catch(function (e) {
      if (!guard(seq)) return;
      var host = byId('aVideos');
      if (host) host.innerHTML = '<div class="a-row"><span>成片读取失败：' + esc(e.message) + '</span></div>';
    });
  }

  /* ------------------------------ 数据 ------------------------------ */
  function renderData(box, seq) {
    var id = ST.draft || currentDraftId();
    var m = id ? draftMeta(id) : null;

    box.innerHTML =
      '<div class="a-label">当前稿件<span class="sp"></span>' +
        (id ? '<span class="r" data-act="reload">刷新</span>' : '') + '</div>' +
      (m ? '<div class="a-score"><div class="n">' + (m.score == null ? '—' : Math.round(Number(m.score))) +
        '<small>/100</small></div><div class="d"><b>' + esc(m.title || '未命名') + '</b>' +
        (m.imgs || 0) + ' 图 · ' + (m.cards || 0) + ' 卡' + (m.status ? ' · ' + esc(m.status) : '') + '</div></div>'
        : '<div class="a-row"><span>未选中稿件</span></div>') +
      '<div class="a-label">后台任务<span class="sp"></span></div>' +
      '<div id="aTasks"><div class="a-row"><span>读取中…</span></div></div>' +
      '<div class="a-label">资产统计</div>' +
      '<div id="aStats"><div class="a-row"><span>统计中…</span></div></div>';

    apiGet('/api/tasks').then(function (r) {
      if (!guard(seq)) return;
      var list = (r && r.tasks) || [];
      var host = byId('aTasks');
      if (!host) return;
      if (!list.length) { host.innerHTML = '<div class="a-row"><span>当前没有后台任务</span></div>'; return; }
      host.innerHTML = list.slice(0, 8).map(function (t) {
        var st = String(t.status || '');
        var mark = st === 'completed' ? '✅' : (st === 'failed' ? '❌' : (st === 'running' ? '⏳' : '🕓'));
        var pct = t.progress != null ? t.progress : (t.pct != null ? t.pct : null);
        return '<div class="a-row" title="' + esc(t.id || '') + '">' +
          '<b>' + mark + '</b>' +
          '<span>' + esc(t.name || t.title || t.task_type || '任务') + '</span>' +
          '<i>' + (pct != null ? pct + '%' : esc(st)) + '</i></div>';
      }).join('');
    }).catch(function () {
      var host = byId('aTasks');
      if (host) host.innerHTML = '<div class="a-row"><span>任务接口暂不可用</span></div>';
    });

    Promise.all([
      apiGet('/api/assets/library?per_page=1').catch(function () { return null; }),
      apiGet('/api/video/tasks').catch(function () { return null; })
    ]).then(function (res) {
      if (!guard(seq)) return;
      var host = byId('aStats');
      if (!host) return;
      var imgTotal = (res[0] && res[0].total) || 0;
      var vids = (res[1] && res[1].tasks) || [];
      host.innerHTML =
        '<div class="a-row"><b>📝</b><span>稿件</span><i>' + totalDrafts() + ' 篇</i></div>' +
        '<div class="a-row"><b>🖼️</b><span>图片资产</span><i>' + imgTotal + ' 张</i></div>' +
        '<div class="a-row"><b>🎬</b><span>成片</span><i>' + vids.length + ' 条</i></div>';
    });
  }

  /* ------------------------------ 顶栏溢出菜单 ------------------------------ */
  // 中栏变窄后顶栏一行放不下全部动作；这里按「重要性从高到低」自动把放不下的
  // 收进「⋯ 更多」。移的是真实 DOM 节点，onclick 与状态全部原样保留。
  var HDR_ORDER = ['misc', 'refresh', 'lang', 'theme', 'watermark', 'persona',
    'api', 'cmd', 'jobs', 'mode', 'cal', 'ws', 'token', 'auth'];
  var hdrMenu = null;
  var hdrItems = [];
  var MORE_LABEL = tr('shell_more', '⋯ 更多');
  var LESS_LABEL = tr('shell_less', '✕ 收起');

  function hdrKind(el) {
    if (el.id === 'top-auth-btn') return 'auth';
    if (el.classList.contains('token-pill') || el.classList.contains('unified-billing-pill')) return 'token';
    if (el.classList.contains('ws-brand-selector')) return 'ws';
    if (el.classList.contains('ws-mode-switcher')) return 'mode';
    if (el.id === 'btn-theme-mode-toggle') return 'theme';
    if (el.id === 'btn-lang-toggle') return 'lang';
    var t = el.textContent || '';
    if (t.indexOf('排期日历') >= 0) return 'cal';
    if (t.indexOf('快捷命令') >= 0) return 'cmd';
    if (t.indexOf('任务监控') >= 0) return 'jobs';
    if (t.indexOf('水印') >= 0) return 'watermark';
    if (t.indexOf('6维画像') >= 0) return 'persona';
    if (t.indexOf('我的API') >= 0 || t.indexOf('我的 API') >= 0) return 'api';
    if (t.indexOf('刷新状态') >= 0) return 'refresh';
    return 'misc';
  }

  function hdrRank(el) {
    var i = HDR_ORDER.indexOf(hdrKind(el));
    return i < 0 ? 0 : i;
  }

  function hdrOverflow(acts) {
    // 注意：justify-content:flex-end 的容器溢出发生在左侧，而 scrollWidth 只统计
    // 右侧溢出，因此不能用 scrollWidth 判断，必须累加子项实际宽度。
    var kids = Array.prototype.slice.call(acts.children);
    var total = 0;
    var n = 0;
    kids.forEach(function (e) {
      var w = e.getBoundingClientRect().width;
      if (w > 0) { total += w; n++; }
    });
    var gap = parseFloat(getComputedStyle(acts).columnGap) || 0;
    total += gap * Math.max(0, n - 1);
    return total > acts.clientWidth + 1;
  }

  function fitHeader() {
    var acts = DOC.querySelector('header .top-acts');
    if (!acts || !hdrMenu) return;
    var more = hdrMenu.parentNode;

    // 1) 全部先摆回顶栏
    hdrItems.forEach(function (el) { acts.insertBefore(el, more); });

    // 2) 从最低优先级开始往菜单里收，直到一行放得下
    var moved = 0;
    for (var i = 0; i < hdrItems.length; i++) {
      if (!hdrOverflow(acts)) break;
      hdrMenu.appendChild(hdrItems[i]);
      moved++;
    }

    // 3) 菜单内按重要性从高到低排列（最重要的一项在最上面）
    for (var k = moved - 1; k >= 0; k--) hdrMenu.appendChild(hdrItems[k]);

    more.style.display = moved ? '' : 'none';
  }

  function buildHeaderOverflow() {
    var acts = DOC.querySelector('header .top-acts');
    if (!acts || acts.getAttribute('data-shell-hdr') === '1') return;
    acts.setAttribute('data-shell-hdr', '1');

    var more = DOC.createElement('div');
    more.className = 'hdr-more';
    more.innerHTML = '<button class="abtn" id="shellMoreBtn" type="button" title="更多功能入口">' + MORE_LABEL + '</button>' +
      '<div class="hdr-menu" id="shellMoreMenu"></div>';
    acts.appendChild(more);
    hdrMenu = more.querySelector('#shellMoreMenu');

    var btn = more.querySelector('#shellMoreBtn');
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      hdrMenu.classList.toggle('on');
      btn.textContent = hdrMenu.classList.contains('on') ? LESS_LABEL : MORE_LABEL;
    });
    DOC.addEventListener('click', function (e) {
      if (!more.contains(e.target)) {
        hdrMenu.classList.remove('on');
        btn.textContent = MORE_LABEL;
      }
    });
    // 点了菜单里的任意项（除工作区下拉）就把菜单收起
    hdrMenu.addEventListener('click', function (e) {
      if (e.target.closest('select, .ws-brand-selector')) return;
      setTimeout(function () {
        hdrMenu.classList.remove('on');
        btn.textContent = MORE_LABEL;
      }, 120);
    });

    var SKIP_ID = { 'nav-ver-text': 1, 'header-extra': 1 };
    hdrItems = Array.prototype.filter.call(acts.children, function (el) {
      if (el === more || el.tagName === 'SCRIPT') return false;
      if (SKIP_ID[el.id]) return false;
      return true;
    });
    // 稳定的优先级顺序（同级别保持原有左右次序）
    hdrItems.forEach(function (el, i) { el.__hdrOrder = i; });
    hdrItems.sort(function (a, b) {
      return hdrRank(a) - hdrRank(b) || a.__hdrOrder - b.__hdrOrder;
    });

    fitHeader();
    var t = null;
    WIN.addEventListener('resize', function () {
      if (DOC.body.getAttribute('data-shell') !== 'v2') return;
      clearTimeout(t);
      t = setTimeout(fitHeader, 160);
    });
  }

  /* ------------------------------ 交互 ------------------------------ */
  function gotoPanel(key) {
    var nav = DOC.querySelector('.nav-item[data-p="' + key + '"]');
    if (nav) nav.click();
  }

  function bindAssets() {
    var box = byId('assetsBody');
    if (!box) return;

    box.addEventListener('click', function (e) {
      var t = e.target.closest('[data-act]');
      if (!t) return;
      var act = t.getAttribute('data-act');
      if (act === 'open-drafts') { gotoPanel('drafts'); return; }
      if (act === 'open-inspire') { gotoPanel('inspire'); return; }
      if (act === 'open-studio') { gotoPanel('studio'); return; }
      if (act === 'pick') {
        var did = t.getAttribute('data-id');
        if (!did) return;
        ST.draft = did;
        ST.tab = 'doc';
        try { localStorage.setItem(LS_TAB, 'doc'); } catch (err0) { /* ignore */ }
        gotoPanel('drafts');
        try { if (typeof WIN.selectDraft === 'function') WIN.selectDraft(did); } catch (err1) { /* ignore */ }
        render();
        return;
      }
      if (act === 'reload') { refreshDoc(); return; }
      if (act === 'plat') {
        ST.plat = t.getAttribute('data-plat') || 'wechat_mp';
        render();
        return;
      }
      if (act === 'zoom') {
        var idx = parseInt(t.getAttribute('data-idx'), 10) || 0;
        openLB(ST.imgs, idx);
        return;
      }
      if (act === 'restore') {
        var hid = t.getAttribute('data-hid');
        if (!hid) return;
        var title = t.getAttribute('data-title') || '';
        if (!WIN.confirm('回滚到「' + title + '」这个版本？当前内容会作为新快照保留。')) return;
        apiPost('/api/drafts/' + encodeURIComponent(ST.draft) + '/restore', { hid: hid })
          .then(function () {
            toast('已回滚到该版本');
            if (typeof WIN.refresh === 'function') WIN.refresh();
            setTimeout(refreshDoc, 400);
          })
          .catch(function (err) { toast('回滚失败：' + err.message); });
      }
    });

    var tabs = byId('assetsTabs');
    if (tabs) {
      tabs.addEventListener('click', function (e) {
        var t = e.target.closest('.assets-tab');
        if (!t) return;
        ST.tab = t.getAttribute('data-at') || 'doc';
        try { localStorage.setItem(LS_TAB, ST.tab); } catch (err) { /* ignore */ }
        render();
      });
    }

    var rf = byId('assetsRefresh');
    if (rf) rf.addEventListener('click', function () { refreshDoc(true); });

    var fc = byId('assetsFocus');
    if (fc) fc.addEventListener('click', function () { toggleFocus(); });

    var cl = byId('assetsClassic');
    if (cl) cl.addEventListener('click', function () {
      try { localStorage.setItem(LS_MODE, 'classic'); } catch (e) { /* ignore */ }
      var u = new URL(location.href);
      u.searchParams.set('legacy', '1');
      location.href = u.toString();
    });

    var fab = byId('shell-fab');
    if (fab) fab.addEventListener('click', function () { setFocus(false); });
  }

  function refreshDoc(explicit) {
    if (explicit) ST.draft = currentDraftId();
    render();
    if (explicit) toast('已刷新');
  }

  function bindKeys() {
    DOC.addEventListener('keydown', function (e) {
      var tag = (e.target && e.target.tagName) || '';
      var typing = tag === 'INPUT' || tag === 'TEXTAREA' || (e.target && e.target.isContentEditable);
      if (e.key === 'Escape') {
        if (lbOpen()) { closeLB(); e.preventDefault(); return; }
        if (ST.focus) { setFocus(false); e.preventDefault(); return; }
      }
      if (lbOpen() && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
        stepLB(e.key === 'ArrowRight' ? 1 : -1);
        e.preventDefault();
        return;
      }
    });
  }

  /* ------------------------------ 与现有逻辑搭桥 ------------------------------ */
  function patch(fns) {
    Object.keys(fns).forEach(function (name) {
      var orig = WIN[name];
      if (typeof orig !== 'function' || orig.__shellWrapped) return;
      var wrapped = function () {
        var out = orig.apply(this, arguments);
        try { fns[name].apply(this, arguments); } catch (e) { /* 外壳永不阻断业务 */ }
        return out;
      };
      wrapped.__shellWrapped = true;
      WIN[name] = wrapped;
    });
  }

  function bindBridge() {
    // 选中稿件 → 右栏立刻跟随
    patch({
      selectDraft: function (id) {
        if (!id) return;
        ST.draft = id;
        if (ST.tab === 'doc' || ST.tab === 'img') render();
      },
      // 全局刷新（生成完成/切换工作区）→ 右栏重取
      refresh: function () {
        setTimeout(function () {
          if (!ST.draft || !draftMeta(ST.draft)) ST.draft = currentDraftId();
          render();
        }, 300);
      }
    });

    // 左侧导航 → 右栏自动切到最相关的资产页
    var nav = DOC.querySelector('.nav-group');
    if (nav) {
      nav.addEventListener('click', function (e) {
        var it = e.target.closest('.nav-item');
        if (!it) return;
        var map = { drafts: 'doc', studio: 'video', dashboard: 'data', console: 'data' };
        var key = it.getAttribute('data-p');
        if (map[key] && map[key] !== ST.tab) {
          ST.tab = map[key];
          try { localStorage.setItem(LS_TAB, ST.tab); } catch (err) { /* ignore */ }
          setTimeout(render, 120);
        }
      });
    }
  }

  /* ------------------------------ 经典版返程 ------------------------------ */
  function bindClassicReturn() {
    // 经典版布局下也提供一个返回新版的小浮标（窄屏不显示，由 CSS 控制）
    var pill = byId('shell-classic-pill');
    if (!pill) return;
    pill.addEventListener('click', function () {
      try { localStorage.removeItem(LS_MODE); } catch (e) { /* ignore */ }
      var u = new URL(location.href);
      u.searchParams.delete('legacy');
      u.searchParams.delete('classic');
      location.href = u.toString();
    });
  }

  /* ------------------------------ 启动 ------------------------------ */
  function boot() {
    bindClassicReturn();

    if (DOC.body.getAttribute('data-shell') !== 'v2') return;

    // 拖拽手柄（HTML 里没写，避免经典版多两个无用节点）
    var hl = DOC.createElement('div');
    hl.className = 'rz rz-l';
    hl.id = 'rzLeft';
    hl.title = '拖动调整功能栏宽度 · 双击复位';
    var hr = DOC.createElement('div');
    hr.className = 'rz rz-r';
    hr.id = 'rzRight';
    hr.title = '拖动调整资产台宽度 · 双击复位';
    DOC.body.appendChild(hl);
    DOC.body.appendChild(hr);

    applyWidths(readWidths());
    initResize();
    buildHeaderOverflow();
    bindAssets();
    bindKeys();
    bindBridge();

    try {
      var t = localStorage.getItem(LS_TAB);
      if (t && ['doc', 'img', 'video', 'data'].indexOf(t) >= 0) ST.tab = t;
    } catch (e) { /* ignore */ }

    // 等业务侧把 S.drafts 拉回来再渲染首屏
    var tries = 0;
    (function wait() {
      var ready = draftList().length > 0 || tries > 12;
      if (!ready) { tries++; setTimeout(wait, 160); return; }
      ST.draft = activeDraftId();
      render();
    })();

    WIN.YIMU_SHELL = {
      version: '12.1.0',
      setTab: function (t) { ST.tab = t; render(); },
      focus: setFocus,
      refresh: render,
      widths: currentWidths
    };
  }

  if (DOC.readyState === 'loading') {
    DOC.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
