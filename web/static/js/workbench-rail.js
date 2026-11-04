/* SPDX-License-Identifier: BUSL-1.1 */
/* ==========================================================================
   一幕 · YIMU — V11 三栏工作台 · 左栏 / 中栏增强（与 ui-v2 原型对齐）
   --------------------------------------------------------------------------
   本文件只做「补块与换装」：
     · 左栏：新建创作按钮、二级导航树、最近产出列表、底部图标条
     · 中栏：标题副行、快捷胶囊条（subbar）、输入框圆角化与圆形发送
     · 右栏：底部动作条（复制 / 导出 / 发布）
   所有交互都调既有业务函数（newLiteDraft / switchSubTab / setCopilotPrompt /
   copyLiteCurrentRichContent / dlXhsZip / openPublishModal / selectDraft），
   不复制一份逻辑，也不改写任何业务实现。
   ========================================================================== */
(function () {
  'use strict';

  var DOC = document;
  var WIN = window;

  function byId(id) { return DOC.getElementById(id); }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function isV2() {
    return DOC.body && DOC.body.getAttribute('data-shell') === 'v2';
  }

  // 脚本级词法绑定（let S / let curDraft）不会挂到 window 上，必须用裸标识符
  function draftList() {
    try {
      /* eslint-disable no-undef */
      return (typeof S !== 'undefined' && S && S.drafts) || [];
      /* eslint-enable no-undef */
    } catch (e) { return []; }
  }

  function activeDraftId() {
    try {
      /* eslint-disable no-undef */
      if (typeof curDraft !== 'undefined' && curDraft) return curDraft;
      /* eslint-enable no-undef */
    } catch (e) { /* 业务尚未就绪 */ }
    return null;
  }

  function toast(msg) {
    try {
      if (typeof WIN.toast === 'function') WIN.toast(msg);
    } catch (e) { /* ignore */ }
  }

  function call(name, arg) {
    try {
      if (typeof WIN[name] === 'function') { WIN[name](arg); return true; }
      /* eslint-disable no-undef */
      if (typeof eval(name) === 'function') { /* noop, 仅为可读性 */ }
      /* eslint-enable no-undef */
    } catch (e) { /* ignore */ }
    // let/function 声明的顶层函数不挂在 window 上，用 Function 兜底解析
    try {
      /* eslint-disable no-new-func */
      var fn = new Function('return typeof ' + name + " === 'function' ? " + name + ' : null;')();
      /* eslint-enable no-new-func */
      if (typeof fn === 'function') { fn(arg); return true; }
    } catch (e2) { /* ignore */ }
    return false;
  }

  /* ------------------------------ 图标 ------------------------------ */
  function ico(name, cls) {
    var d = {
      plus: '<path d="M12 5v14M5 12h14"/>',
      spark: '<path d="M12 3.5l1.9 4.9 4.9 1.9-4.9 1.9L12 17.1l-1.9-4.9L5.2 10.3l4.9-1.9z"/>',
      radar: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4"/><path d="M12 12l6.6-6.6"/>',
      doc: '<path d="M6.5 3.5h7l4.5 4.5v13h-11.5z"/><path d="M13.5 3.5V8h4.5M9 12.5h6M9 16h4"/>',
      film: '<rect x="3.5" y="4.5" width="17" height="15" rx="2.2"/><path d="M8 4.5v15M16 4.5v15M3.5 12h17"/>',
      gear: '<path d="M4 7.5h8M16.5 7.5H20M4 16.5h3.5M12 16.5h8"/><circle cx="14.2" cy="7.5" r="2.3"/><circle cx="9.8" cy="16.5" r="2.3"/>',
      search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4 4"/>',
      gem: '<path d="M7 4.5h10l3.5 5-8.5 10L3.5 9.5z"/><path d="M3.5 9.5h17M9.5 9.5L12 19.5l2.5-10"/>',
      user: '<circle cx="12" cy="8.5" r="3.6"/><path d="M4.8 20c1-3.7 3.8-5.6 7.2-5.6s6.2 1.9 7.2 5.6"/>',
      chev: '<path d="M9 6l6 6-6 6"/>',
      layers: '<path d="M12 3.5l8.5 4.4L12 12.3 3.5 7.9z"/><path d="M3.5 12.4L12 16.8l8.5-4.4M3.5 16.6L12 21l8.5-4.4"/>',
      moon: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/>',
      copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 5.5h-9a2 2 0 0 0-2 2v9"/>',
      down: '<path d="M12 4.5v11M7.5 11L12 15.5 16.5 11M5 19.5h14"/>',
      send: '<path d="M12 19.5V5M5.5 11.5L12 5l6.5 6.5"/>',
      expand: '<path d="M9 4.5H4.5V9M15 19.5h4.5V15M19.5 9V4.5H15M4.5 15v4.5H9"/>'
    }[name] || '';
    return '<svg class="' + (cls || '') + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + d + '</svg>';
  }

  /* --------------------- 一级页 → 二级入口（真实可点） --------------------- */
  // sp：真实的 switchSubTab 目标；kw：面板内滚动定位用的关键词
  var SUBS = {
    dashboard: [
      { n: '数据总览', en: 'Data Overview', kw: '产能' },
      { n: '7 天走势', en: '7-Day Trend' },
      { n: '发布排期', en: 'Publishing Schedule', kw: '排期' },
      { n: '矩阵空间', en: 'Matrix Space', kw: '矩阵' }
    ],
    lite: [
      { n: '对话成稿', en: 'Chat to Draft' },
      { n: '一句话成爆款', en: 'One-line Hit', sp: 'inspire::sp-oneshot' },
      { n: '批量矩阵生产', en: 'Batch Matrix', sp: 'inspire::sp-batch' }
    ],
    inspire: [
      { n: '实时热榜抓取', en: 'Hot List Scraper', sp: 'inspire::sp-hot' },
      { n: '万能爆款链接采集', en: 'Link Collector', sp: 'inspire::sp-extract' },
      { n: '爆款搜索仿写', en: 'Reference Rewrite', sp: 'inspire::sp-search' },
      { n: '粘贴文案改编', en: 'Paste Adapt', sp: 'inspire::sp-paste' },
      { n: '一句话成爆款', sp: 'inspire::sp-oneshot' },
      { n: '批量矩阵生产', sp: 'inspire::sp-batch' }
    ],
    drafts: [
      { n: '多平台成稿与排版', en: 'Multi-platform Layout', kw: '多平台' },
      { n: '单平台改写', en: 'Single-platform Rewrite', kw: '改写' },
      { n: '口播稿生成', en: 'Voice Script', kw: '口播' },
      { n: 'AI 配图与风格', en: 'AI Images', kw: '配图' },
      { n: '质量体检提分', en: 'Quality Check', kw: '评分' },
      { n: '一键多平台发布', en: 'Publish Everywhere', kw: '发布' }
    ],
    studio: [
      { n: '全自动 AI 短剧', en: 'Auto Short Drama', sp: 'studio::sp-drama' },
      { n: '快速短视频合成', en: 'Fast Video', sp: 'studio::sp-video' },
      { n: 'AI 短视频生成', en: 'AI Video', sp: 'studio::sp-aivideo' },
      { n: '电影级分镜脚本', en: 'Storyboard', sp: 'studio::sp-storyboard' },
      { n: 'AI 口播配音 TTS', en: 'TTS Voice', sp: 'studio::sp-audio' },
      { n: '成片资产库', en: 'Finished Library', sp: 'studio::sp-video-tasks' }
    ],
    console: [
      { n: '每日工单', en: 'Daily Tickets', sp: 'console::sp-ticket' },
      { n: 'Agent 配置', en: 'Agent Config', sp: 'console::sp-agent-config' },
      { n: '技能库', en: 'Skills', sp: 'console::sp-skills' },
      { n: '服务健康自检', en: 'Health Check', sp: 'console::sp-health' },
      { n: '系统与 API 配置', en: 'API Settings', sp: 'console::sp-settings' },
      { n: '用户与会员', en: 'Users', sp: 'console::sp-user-admin' }
    ],
    pricing: [
      { n: '会员订阅', en: 'Subscription', kw: '订阅' },
      { n: '算力充值', en: 'Credits', kw: '充值' }
    ],
    profile: [
      { n: '画像与品牌', en: 'Brand Profile', kw: '画像' },
      { n: '密钥管理', en: 'API Keys', kw: '密钥' },
      { n: '外观偏好', en: 'Appearance', kw: '外观' },
      { n: '账单与充值', en: 'Billing', kw: '账单' }
    ]
  };

  var PAGE_SUB = {
    dashboard: '全网雷达 · 产能中枢 · 发布排期一屏看完',
    lite: '对话即成品 · 说一句话，右侧直接出稿',
    inspire: '热榜挖掘 · 链接采集 · 爆款仿写',
    drafts: '一篇稿，同时出多个平台的排版',
    studio: '短剧、短视频、口播配音与分镜',
    console: '工单、Agent、技能与系统治理',
    pricing: '会员订阅与算力充值',
    profile: '画像、密钥、外观与账单'
  };

  // 顶部快捷胶囊的英文对照，按原芯片顺序
  var SB_EN = [
    'Hot topics to draft',
    'Xiaohongshu short post',
    'WeChat long read',
    '5 headline variants',
    'Author voice injection',
    'Quality check'
  ];

  var PAGE_SUB_EN = {
    dashboard: 'Radar, capacity and schedule in one screen',
    lite: 'Say one line, the draft and media come out on the right',
    inspire: 'Hot lists, link capture and viral rewrites',
    drafts: 'One draft, laid out for every platform',
    studio: 'Drama, short video, voice-over and storyboard',
    console: 'Tickets, agents, skills and system governance',
    pricing: 'Membership plans and credits',
    profile: 'Profile, keys, appearance and billing'
  };

  var PAGE_ICON = {
    dashboard: 'radar', lite: 'spark', inspire: 'search', drafts: 'doc',
    studio: 'film', console: 'gear', pricing: 'gem', profile: 'user'
  };

  /* ------------------------------ 左栏 ------------------------------ */

  function buildNewButton(side) {
    var box = side.querySelector('.logo-box');
    if (!box || side.querySelector('.rail-new')) return;
    var btn = DOC.createElement('button');
    btn.type = 'button';
    btn.className = 'rail-new';
    btn.innerHTML = ico('plus') + '<span>' + t('新建创作', 'New draft') + '</span>';
    btn.title = t('清空当前草稿，开启全新空白创作', 'Start a blank draft');
    btn.addEventListener('click', function () {
      // 先切回创作台，再清空为全新草稿
      var liteNav = DOC.querySelector('.nav-item[data-p="lite"]');
      if (liteNav && !liteNav.classList.contains('on')) liteNav.click();
      if (!call('newLiteDraft')) {
        if (!call('openNewDraftModal')) toast('新建创作入口暂不可用');
      }
    });
    box.insertAdjacentElement('afterend', btn);
  }

  function switchToPage(key) {
    var nav = DOC.querySelector('.nav-item[data-p="' + key + '"]');
    if (nav) nav.click();
  }

  // 在目标面板里按关键词滚动定位；找不到就只切页
  function revealIn(key, kw) {
    if (!kw) return;
    var panel = byId('p-' + key);
    if (!panel) return;
    var nodes = panel.querySelectorAll('h1,h2,h3,h4,div,span,button');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el.children.length > 2) continue;
      if ((el.textContent || '').indexOf(kw) >= 0) {
        try { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) { /* ignore */ }
        el.classList.add('rail-flash');
        setTimeout(function () { el.classList.remove('rail-flash'); }, 1400);
        return;
      }
    }
  }

  function goSub(parentKey, sub) {
    if (!sub) return;
    var targetKey = parentKey;
    var sp = null;
    if (sub.sp) {
      var parts = sub.sp.split('::');
      targetKey = parts[0];
      sp = parts[1];
    }
    switchToPage(targetKey);
    if (sp) {
      setTimeout(function () {
        try {
          /* eslint-disable no-undef */
          switchSubTab(targetKey, sp);
          /* eslint-enable no-undef */
        } catch (e) { /* ignore */ }
      }, 60);
    } else if (sub.kw) {
      setTimeout(function () { revealIn(targetKey, sub.kw); }, 80);
    }
    markSubActive(parentKey, sub.n);
  }

  function markSubActive(parentKey, label) {
    var subs = DOC.querySelectorAll('.rail-subs[data-for="' + parentKey + '"] .rail-sub');
    for (var i = 0; i < subs.length; i++) {
      subs[i].classList.toggle('on', subs[i].textContent.trim() === label);
    }
  }

  function buildSubs(side) {
    var items = side.querySelectorAll('.nav-item');
    for (var i = 0; i < items.length; i++) {
      var item = items[i];
      var key = item.getAttribute('data-p');
      var list = SUBS[key];
      if (!list || !list.length) continue;
      if (item.querySelector('.rail-chev')) continue;

      // 图标换成线性图标，隐藏原 emoji 文本
      var iconEl = item.querySelector('.nav-icon');
      if (iconEl && !iconEl.querySelector('svg')) {
        iconEl.innerHTML = ico(PAGE_ICON[key] || 'spark');
        iconEl.style.display = 'flex';
        iconEl.style.alignItems = 'center';
        iconEl.style.justifyContent = 'center';
      }

      // 展开箭头
      var chev = DOC.createElement('span');
      chev.className = 'rail-chev';
      chev.style.cssText = 'width:12px;height:12px;flex:0 0 12px;margin-left:auto;' +
        'display:flex;align-items:center;justify-content:center;color:#5c6a7d;opacity:.9;';
      chev.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" ' +
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
        'aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>';
      item.appendChild(chev);

      // 点击箭头区域展开/收起，点行本身仍是切换页面
      chev.addEventListener('click', function (ev) {
        ev.stopPropagation();
        toggleSubs(this.parentElement);
      });

      // 二级容器
      var box = DOC.createElement('div');
      box.className = 'rail-subs';
      box.setAttribute('data-for', key);
      for (var j = 0; j < list.length; j++) {
        var sub = DOC.createElement('div');
        sub.className = 'rail-sub';
        sub.textContent = (isEn() && list[j].en) ? list[j].en : list[j].n;
        sub.setAttribute('role', 'button');
        sub.addEventListener('click', (function (k, s) {
          return function (ev) {
            ev.stopPropagation();
            goSub(k, s);
          };
        })(key, list[j]));
        box.appendChild(sub);
      }
      item.insertAdjacentElement('afterend', box);
    }
  }

  function toggleSubs(item) {
    var key = item.getAttribute('data-p');
    var box = DOC.querySelector('.rail-subs[data-for="' + key + '"]');
    if (!box) return;
    var open = box.classList.toggle('on');
    item.classList.toggle('open', open);
    if (open) {
      // 手风琴：同时只展开一个
      var others = DOC.querySelectorAll('.rail-subs.on');
      for (var i = 0; i < others.length; i++) {
        if (others[i] === box) continue;
        others[i].classList.remove('on');
        var prev = others[i].previousElementSibling;
        if (prev) prev.classList.remove('open');
      }
    }
  }

  function buildRecent(side) {
    if (side.querySelector('.rail-head')) return;
    var navGroup = side.querySelector('.nav-group');
    if (!navGroup) return;

    var head = DOC.createElement('div');
    head.className = 'rail-head';
    head.innerHTML = '<span>' + t('最近产出', 'Recent') + '</span>' +
      '<button type="button" class="rail-search-btn" title="' +
      t('打开草稿箱，搜索全部稿件', 'Open draft box and search') + '">' + ico('search') + '</button>';
    var searchBtn = head.querySelector('.rail-search-btn');
    if (searchBtn) {
      searchBtn.addEventListener('click', function () {
        if (!call('openLiteDraftsModal')) toast('草稿箱入口暂不可用');
      });
    }

    var list = DOC.createElement('div');
    list.className = 'rail-list';
    list.id = 'railRecentList';

    navGroup.insertAdjacentElement('afterend', head);
    head.insertAdjacentElement('afterend', list);
  }

  function renderRecent() {
    var list = byId('railRecentList');
    if (!list) return;
    var ds = draftList();
    if (!ds.length) {
      list.innerHTML = '<div class="rail-empty">' +
        (isEn() ? 'Nothing yet<br>Say one line in the middle to get a draft'
                : '还没有产出<br>在中间说一句话就能出稿') + '</div>';
      return;
    }
    var act = activeDraftId();
    var html = '';
    var n = Math.min(ds.length, 12);
    for (var i = 0; i < n; i++) {
      var d = ds[i] || {};
      var title = d.title || d.topic || d.name || ('未命名稿件 ' + (i + 1));
      /* 平台：单值字段优先，其次 platforms 数组与来源平台 */
      var plat = d.platform || d.target_platform || '';
      if (!plat && d.platforms && d.platforms.length) plat = d.platforms[0];
      if (!plat) plat = d.source_platform || '';
      /* 时间：updated_at 优先；草稿表实际只给 created_at（unix 秒，可能是字符串） */
      var when = '';
      var stamp = d.updated_at || d.created_at || d.saved_at || '';
      if (stamp) {
        try {
          var num = Number(stamp);
          var dt = (!isNaN(num) && num > 1e9) ? new Date(num * 1000) : new Date(stamp);
          if (!isNaN(dt.getTime())) {
            var diff = (Date.now() - dt.getTime()) / 1000;
            if (diff < 3600) when = Math.max(1, Math.round(diff / 60)) + ' 分钟前';
            else if (diff < 86400) when = Math.round(diff / 3600) + ' 小时前';
            else when = (dt.getMonth() + 1) + '月' + dt.getDate() + '日';
          }
        } catch (e) { /* ignore */ }
      }
      html += '<div class="rail-item' + (d.id === act ? ' on' : '') + '" data-did="' + esc(d.id) + '">' +
        '<div class="t">' + esc(title) + '</div>' +
        '<div class="s">' +
        (plat ? '<em>' + esc(platName(plat)) + '</em>' : '') +
        (when ? '<span>' + esc(when) + '</span>' : '') +
        '</div></div>';
    }
    list.innerHTML = html;

    var items = list.querySelectorAll('.rail-item');
    for (var k = 0; k < items.length; k++) {
      items[k].addEventListener('click', function () {
        var did = this.getAttribute('data-did');
        switchToPage('drafts');
        if (!call('selectDraft', did)) toast('打开稿件失败');
      });
    }
  }

  function buildFoot(side) {
    var foot = side.querySelector('.side-foot');
    if (!foot || foot.querySelector('.rail-icobtn')) return;

    // 主题切换
    var theme = DOC.createElement('button');
    theme.type = 'button';
    theme.className = 'rail-icobtn';
    theme.title = t('切换明暗外观', 'Toggle light / dark');
    theme.innerHTML = ico('moon');
    theme.addEventListener('click', function () {
      var cur = DOC.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
      DOC.documentElement.setAttribute('data-theme', cur);
      try { localStorage.setItem('yimu.theme', cur); } catch (e) { /* ignore */ }
      if (!call('toggleTheme')) { /* 已本地切换 */ }
    });

    // 经典版
    var classic = DOC.createElement('button');
    classic.type = 'button';
    classic.className = 'rail-icobtn';
    classic.title = t('切换到经典版（原界面）', 'Switch to classic UI');
    classic.innerHTML = ico('layers');
    classic.addEventListener('click', function () {
      try {
        localStorage.setItem('yimu.shell.mode', 'classic');
        var u = new URL(location.href);
        u.searchParams.set('legacy', '1');
        location.href = u.toString();
      } catch (e) { /* ignore */ }
    });

    // 控制中心
    var gear = DOC.createElement('button');
    gear.type = 'button';
    gear.className = 'rail-icobtn';
    gear.title = t('打开控制中心', 'Open control center');
    gear.innerHTML = ico('gear');
    gear.addEventListener('click', function () { switchToPage('console'); });

    foot.insertBefore(theme, foot.firstChild);
    foot.appendChild(classic);
    foot.appendChild(gear);
  }

  /* ------------------------------ 中栏 ------------------------------ */

  function buildHeaderSub() {
    var title = byId('header-title');
    if (!title || title.parentElement.querySelector('.rail-headsub')) return;
    var sub = DOC.createElement('span');
    sub.className = 'rail-headsub';
    sub.id = 'rail-headsub';
    title.parentElement.appendChild(sub);
    title.parentElement.style.flexDirection = 'column';
    title.parentElement.style.alignItems = 'flex-start';
    title.parentElement.style.gap = '0';
    syncHeaderSub();
  }

  function isEn() {
    try {
      if (WIN.YIMU_I18N && typeof WIN.YIMU_I18N.getLang === 'function') {
        return WIN.YIMU_I18N.getLang() === 'en';
      }
    } catch (e) { /* ignore */ }
    return false;
  }

  // 注入块的固定文案：中英各一份，跟随当前语言
  function t(zh, en) { return isEn() ? en : zh; }

  // 平台键 → 展示名（与 adapters/base.py 的 NAMES 对齐，多平台补齐）
  var PLAT = {
    wechat_mp: ['公众号', 'WeChat'],
    xhs: ['小红书', 'Xiaohongshu'],
    toutiao: ['今日头条', 'Toutiao'],
    douyin: ['抖音', 'Douyin'],
    zhihu: ['知乎', 'Zhihu'],
    bilibili: ['B站', 'Bilibili'],
    weibo: ['微博', 'Weibo'],
    shipinhao: ['视频号', 'Channels']
  };
  function platName(key) {
    var k = String(key || '');
    var p = PLAT[k];
    return p ? (isEn() ? p[1] : p[0]) : k;
  }

  function syncHeaderSub() {
    var sub = byId('rail-headsub');
    if (!sub) return;
    var on = DOC.querySelector('.nav-item.on');
    var key = on ? on.getAttribute('data-p') : 'lite';

    // 中文环境下，创作台页沿用原型标题，而不是沿用旧的模式名
    var titleEl = byId('header-title');
    if (titleEl && key === 'lite' && !isEn()) {
      if ((titleEl.textContent || '').trim() !== '创作台') titleEl.textContent = '创作台';
    }
    var text = (isEn() && PAGE_SUB_EN[key]) ? PAGE_SUB_EN[key] : (PAGE_SUB[key] || '');
    if (sub.textContent !== text) sub.textContent = text;
  }

  function buildSubbar() {
    var lite = byId('p-lite-mode');
    if (!lite || lite.querySelector('.rail-subbar')) return;
    var chips = lite.querySelectorAll('.copilot-chip');
    if (!chips.length) return;

    var bar = DOC.createElement('div');
    bar.className = 'rail-subbar';
    bar.id = 'railSubbar';

    for (var i = 0; i < chips.length && i < 4; i++) {
      var c = chips[i];
      var label = (c.textContent || '').replace(/^[^\u4e00-\u9fa5A-Za-z]+/, '').trim();
      var b = DOC.createElement('button');
      b.type = 'button';
      b.className = 'sb' + (i === 0 ? ' on' : '');
      b.textContent = (isEn() && SB_EN[i]) ? SB_EN[i] : label;
      b.setAttribute('data-prompt', c.getAttribute('onclick') || '');
      b.setAttribute('data-zh', label);
      b.addEventListener('click', (function (chip, btn) {
        return function () {
          var on = bar.querySelectorAll('.sb');
          for (var k = 0; k < on.length; k++) on[k].classList.remove('on');
          btn.classList.add('on');
          chip.click();
        };
      })(c, b));
      bar.appendChild(b);
    }

    // 固定插在消息区之前，顺序与原型的 chat-head → subbar → msgs → composer 一致
    var msgs = byId('copilot-chat-messages');
    if (msgs && msgs.parentElement) {
      msgs.parentElement.insertBefore(bar, msgs);
    } else {
      var col = lite.querySelector('.lite-col-left');
      if (col) col.insertBefore(bar, col.firstChild);
    }
  }

  // 把原「爆款创作 Copilot」行里的两个入口收进胶囊条右侧，让中栏回到
  // 原型的 chat-head → subbar → 对话 → 输入 四段结构，功能入口一个不少。
  function mergeHeadIntoSubbar() {
    var lite = byId('p-lite-mode');
    var bar = byId('railSubbar');
    if (!lite || !bar) return;
    var col = lite.querySelector('.lite-col-left');
    if (!col) return;
    var head = col.firstElementChild;
    if (!head || head === bar) return;
    var pills = head.querySelectorAll('.btn-lite-head-pill');
    if (pills.length) {
      var sp = DOC.createElement('span');
      sp.style.cssText = 'flex:1 1 auto;min-width:8px;';
      bar.appendChild(sp);
      for (var i = 0; i < pills.length; i++) {
        var p = pills[i];
        p.classList.add('sb-tool');
        var lbl = (p.textContent || '').trim();
        if (lbl) p.title = lbl;
        p.setAttribute('aria-label', lbl);
        bar.appendChild(p);
      }
    }
    head.style.display = 'none';
  }

  // 对话为空时补一组功能引导卡，与原型 msgs 区的功能卡一致；
  // 一旦开始对话就自动撤掉，不干扰正常消息流。
  var GUIDE = [
    { ic: 'spark', zh: '一句话成爆款', en: 'One-line hit',
      zhD: '说一句需求，选题、正文、配图、体检一次跑完',
      enD: 'One line in, topic, draft, images and check come out',
      go: ['inspire', 'sp-oneshot'] },
    { ic: 'radar', zh: '抓今日热榜', en: 'Today hot list',
      zhD: '六个平台的热榜拉回来，按赛道筛出能写的题',
      enD: 'Pull hot lists from six platforms and filter by track',
      go: ['inspire', 'sp-hot'] },
    { ic: 'doc', zh: '多平台排版', en: 'Multi-platform layout',
      zhD: '一篇稿同时出小红书、公众号、头条版本',
      enD: 'One draft laid out for Xiaohongshu, WeChat and Toutiao',
      go: ['drafts', null] }
  ];

  function buildEmptyGuide() {
    var box = byId('copilot-chat-messages');
    if (!box || box.querySelector('.rail-guide')) return;
    var msgs = box.querySelectorAll('.copilot-msg').length;
    if (msgs > 1) return;

    var g = DOC.createElement('div');
    g.className = 'rail-guide';
    var html = '<div class="rg-t">' + t('从这里开始', 'Start here') + '</div>';
    for (var i = 0; i < GUIDE.length; i++) {
      var it = GUIDE[i];
      html += '<div class="rg-card" data-i="' + i + '">' +
        '<div class="ic">' + ico(it.ic) + '</div>' +
        '<div class="tx"><b>' + (isEn() ? it.en : it.zh) + '</b>' +
        '<p>' + (isEn() ? it.enD : it.zhD) + '</p></div>' +
        '<span class="arw">›</span></div>';
    }
    g.innerHTML = html;
    box.appendChild(g);

    var cards = g.querySelectorAll('.rg-card');
    for (var k = 0; k < cards.length; k++) {
      cards[k].addEventListener('click', function () {
        var idx = parseInt(this.getAttribute('data-i'), 10);
        var it = GUIDE[idx];
        if (!it) return;
        if (it.go[1]) goSub(it.go[0], { n: it.zh, sp: it.go[0] + '::' + it.go[1] });
        else switchToPage(it.go[0]);
      });
    }
  }

  function syncEmptyGuide() {
    var box = byId('copilot-chat-messages');
    if (!box) return;
    var g = box.querySelector('.rail-guide');
    var msgs = box.querySelectorAll('.copilot-msg').length;
    if (msgs > 1) {
      if (g) g.remove();
    } else if (!g) {
      buildEmptyGuide();
    }
  }

  function wrapComposer() {
    var input = byId('copilot-input');
    if (!input) return;
    var box = input.parentElement;
    var wrap = box && box.parentElement;
    if (box && box.classList) box.classList.add('composer-v11-box');
    if (wrap && wrap.classList) wrap.classList.add('composer-v11-wrap');

    var send = byId('btn-copilot-send');
    if (send && !send.classList.contains('rail-send')) {
      send.classList.add('rail-send');
      send.setAttribute('aria-label', '发送');
    }
  }

  /* ------------------------------ 右栏 ------------------------------ */

  function buildAssetsActs() {
    var panel = byId('assetsPanel');
    if (!panel || panel.querySelector('.assets-acts')) return;
    var foot = panel.querySelector('.assets-foot');

    var bar = DOC.createElement('div');
    bar.className = 'assets-acts';
    bar.innerHTML =
      '<button type="button" class="btn" data-act="copy">' + ico('copy') +
        '<span>' + t('复制', 'Copy') + '</span></button>' +
      '<button type="button" class="btn" data-act="export">' + ico('down') +
        '<span>' + t('导出', 'Export') + '</span></button>' +
      '<button type="button" class="btn primary" data-act="publish">' + ico('send') +
        '<span>' + t('发布', 'Publish') + '</span></button>';

    bar.querySelector('[data-act="copy"]').addEventListener('click', function () {
      if (!call('copyLiteCurrentRichContent')) toast('当前没有可复制的成稿');
    });
    bar.querySelector('[data-act="export"]').addEventListener('click', function () {
      if (!call('dlXhsZip')) toast('当前没有可导出的配图');
    });
    bar.querySelector('[data-act="publish"]').addEventListener('click', function () {
      if (!call('openPublishModal')) toast('发布入口暂不可用');
    });

    if (foot) foot.insertAdjacentElement('beforebegin', bar);
    else panel.appendChild(bar);
  }

  // 语言切换后就地刷新注入块文案，避免出现半中半英
  var lastLang = null;
  function applyLang() {
    var en = isEn();
    if (lastLang === en) return;
    lastLang = en;

    var nb = DOC.querySelector('body > .side .rail-new > span');
    if (nb) nb.textContent = t('新建创作', 'New draft');

    var rh = DOC.querySelector('body > .side .rail-head > span');
    if (rh) rh.textContent = t('最近产出', 'Recent');

    var acts = DOC.querySelectorAll('.assets-acts .btn > span');
    if (acts[0]) acts[0].textContent = t('复制', 'Copy');
    if (acts[1]) acts[1].textContent = t('导出', 'Export');
    if (acts[2]) acts[2].textContent = t('发布', 'Publish');

    var sbs = DOC.querySelectorAll('.rail-subbar .sb:not(.sb-tool)');
    for (var m = 0; m < sbs.length; m++) {
      if (SB_EN[m]) sbs[m].textContent = en ? SB_EN[m] : sbs[m].getAttribute('data-zh') || sbs[m].textContent;
    }

    var boxes = DOC.querySelectorAll('body > .side .rail-subs');
    for (var i = 0; i < boxes.length; i++) {
      var key = boxes[i].getAttribute('data-for');
      var list = SUBS[key] || [];
      var nodes = boxes[i].children;
      for (var j = 0; j < nodes.length && j < list.length; j++) {
        nodes[j].textContent = (en && list[j].en) ? list[j].en : list[j].n;
      }
    }
    syncHeaderSub();
    renderRecent();
  }

  /* ------------------------------ 装配 ------------------------------ */

  function boot() {
    if (!isV2()) return;
    var side = DOC.querySelector('body > .side');
    if (!side) return;

    buildNewButton(side);
    buildSubs(side);
    buildRecent(side);
    buildFoot(side);

    buildHeaderSub();
    buildSubbar();
    mergeHeadIntoSubbar();
    buildEmptyGuide();
    wrapComposer();
    buildAssetsActs();

    // 首帧与后续数据到达时刷新最近产出
    var tries = 0;
    (function wait() {
      renderRecent();
      if (draftList().length === 0 && tries < 14) { tries++; setTimeout(wait, 240); }
    })();

    // 选稿后高亮跟随
    var origSelect = null;
    try {
      /* eslint-disable no-undef */
      if (typeof selectDraft === 'function' && !selectDraft.__railWrapped) {
        origSelect = selectDraft;
        /* eslint-enable no-undef */
      }
    } catch (e) { /* ignore */ }

    // 标题副行随页面切换同步
    var titleEl = byId('header-title');
    if (titleEl && WIN.MutationObserver) {
      new WIN.MutationObserver(syncHeaderSub).observe(titleEl, {
        childList: true, characterData: true, subtree: true
      });
    }

    // 导航点击后刷新选中态与二级展开
    DOC.addEventListener('click', function (ev) {
      var item = ev.target && ev.target.closest ? ev.target.closest('.nav-item') : null;
      if (!item) return;
      setTimeout(function () {
        var key = item.getAttribute('data-p');
        var box = DOC.querySelector('.rail-subs[data-for="' + key + '"]');
        /* 手风琴：切页时先收起其它已展开的二级树，否则连点几次会全摊开把「最近产出」顶下去 */
        var others = DOC.querySelectorAll('.rail-subs.on');
        for (var i = 0; i < others.length; i++) {
          if (others[i] === box) continue;
          others[i].classList.remove('on');
          var prev = others[i].previousElementSibling;
          if (prev) prev.classList.remove('open');
        }
        if (box && SUBS[key] && SUBS[key].length) {
          box.classList.add('on');
          item.classList.add('open');
        }
        syncHeaderSub();
        renderRecent();
      }, 30);
    }, true);

    // 业务侧更新草稿后同步最近列表
    applyLang();
    var tickN = 0;
    (function tick() {
      applyLang();
      syncEmptyGuide();
      renderRecent();
      if (++tickN < 40) setTimeout(tick, 3000);
    })();
  }

  if (DOC.readyState === 'loading') {
    DOC.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  WIN.YIMU_RAIL = { refresh: renderRecent, version: '12.0.0' };
})();
