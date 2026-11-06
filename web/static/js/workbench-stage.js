/* ==========================================================================
   一幕·YIMU · V12 右栏舞台（Stage）
   --------------------------------------------------------------------------
   交互模型：
     · 左侧功能栏        —— 永远不动
     · 中间对话栏        —— 永远不动，始终是同一个对话框
     · 点左侧菜单        —— 对应功能页面在右侧面板打开
     · 右侧面板          —— 可全屏 / 可回到对话

   实现方式：DOM 搬家，不是重写页面。
   8 个业务面板（#p-dashboard / #p-inspire / #p-drafts / #p-studio /
   #p-console / #p-pricing / #p-profile）原本就在 <main> 里，靠 .on 显隐。
   点菜单时把目标面板 appendChild 进舞台，离开时搬回原位 —— 面板内部的
   onclick、已绑定的事件、滚动位置、表单状态全部原样保留，业务逻辑零复制。

   只在 body[data-shell="v2"] 下工作；?legacy=1 与 <1280px 经典布局完全不受影响。
   ========================================================================== */
(function () {
  'use strict';

  var DOC = document;
  var WIN = window;

  function byId(id) { return DOC.getElementById(id); }

  function isV2() {
    return DOC.body && DOC.body.getAttribute('data-shell') === 'v2';
  }

  function isEn() {
    try {
      if (WIN.YIMU_I18N && typeof WIN.YIMU_I18N.getLang === 'function') {
        return WIN.YIMU_I18N.getLang() === 'en';
      }
    } catch (e) { /* ignore */ }
    return false;
  }

  function t(zh, en) { return isEn() ? en : zh; }

  /* 左栏 8 项里除「极简模式」外的 7 个功能页；lite 是对话本身，不进舞台 */
  var PAGES = {
    dashboard: { zh: '操盘大屏', en: 'Dashboard',    sub: '全网雷达 · 产能中枢',        subEn: 'Radar · Capacity',        ic: '🌐' },
    inspire:   { zh: '灵感与选题', en: 'Inspiration', sub: '热榜挖掘 · 爆款仿写',        subEn: 'Trends · Rewrite',        ic: '🔥' },
    drafts:    { zh: '内容工作台', en: 'Workspace',   sub: '仿写 · 适配 · 精修一站到底',  subEn: 'Rewrite · Adapt · Refine', ic: '📝' },
    studio:    { zh: '内容工厂', en: 'Studio',       sub: '短片 · 图片 · 数字人',        subEn: 'Video · Image · Avatar',  ic: '🎬' },
    console:   { zh: 'AI 控制台', en: 'Console',     sub: '工单 · 模型 · 链路总览',      subEn: 'Tickets · Models · Pipeline', ic: '⚙️' },
    pricing:   { zh: '订阅与会员', en: 'Pricing',    sub: '套餐 · 算力 · 账单',          subEn: 'Plans · Credits · Billing', ic: '💎' },
    profile:   { zh: '个人中心', en: 'Profile',      sub: '账号 · 偏好 · 安全',          subEn: 'Account · Prefs · Security', ic: '👤' }
  };

  var ICON_BACK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>';
  var ICON_FULL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" ' +
    'stroke-linecap="round" stroke-linejoin="round"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>';
  var ICON_SHRINK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" ' +
    'stroke-linecap="round" stroke-linejoin="round"><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/></svg>';
  var ICON_CLOSE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>';
  var ICON_CHAT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" ' +
    'stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.4 8.4 0 01-9 8.4 9.3 9.3 0 01-3.7-.8L3 21l1.9-4.9A8.4 8.4 0 0112 3.1a8.4 8.4 0 019 8.4z"/></svg>';

  var stage = null;     // 舞台根节点
  var body = null;      // 舞台内容区
  var nameEl = null;
  var subEl = null;
  var icEl = null;
  var fullBtn = null;
  var current = null;   // 当前在舞台上的页面 key

  /* ------------------------------------------------------------------ 构建 */

  function build() {
    var assets = byId('assetsPanel');
    if (!assets || byId('workStage')) return false;

    stage = DOC.createElement('div');
    stage.className = 'stage';
    stage.id = 'workStage';
    stage.setAttribute('aria-hidden', 'true');
    stage.innerHTML =
      '<div class="stage-head">' +
        '<button class="stage-back" id="stageBack" type="button" ' +
          'title="' + t('回到对话', 'Back to chat') + '">' + ICON_BACK + '</button>' +
        '<div class="stage-title">' +
          '<span class="stage-ic" id="stageIc">🌐</span>' +
          '<span class="stage-nm" id="stageNm"></span>' +
          '<span class="stage-sb" id="stageSb"></span>' +
        '</div>' +
        '<button class="stage-btn" id="stageFull" type="button" ' +
          'title="' + t('全屏', 'Full screen') + '">' + ICON_FULL + '</button>' +
        '<button class="stage-btn" id="stageClose" type="button" ' +
          'title="' + t('关闭，回到对话', 'Close and return to chat') + '">' + ICON_CLOSE + '</button>' +
      '</div>' +
      '<div class="stage-body" id="stageBody"></div>';

    assets.appendChild(stage);

    body = byId('stageBody');
    nameEl = byId('stageNm');
    subEl = byId('stageSb');
    icEl = byId('stageIc');
    fullBtn = byId('stageFull');

    byId('stageBack').addEventListener('click', close);
    byId('stageClose').addEventListener('click', close);
    fullBtn.addEventListener('click', toggleFull);

    /* 双击舞台头同样可以全屏 / 退出全屏 */
    stage.querySelector('.stage-title').addEventListener('dblclick', toggleFull);

    return true;
  }

  /* ------------------------------------------------------------------ 搬运 */

  function homeMain() {
    return DOC.querySelector('body[data-shell="v2"] .main-wrapper > main') ||
           DOC.querySelector('.main-wrapper > main');
  }

  /* 把面板搬回 <main>，紧跟在 #p-lite-mode 之后，保持原始次序 */
  function restore() {
    if (!current) return;
    var panel = byId('p-' + current);
    var main = homeMain();
    var anchor = byId('p-lite-mode');
    if (panel && main) {
      if (anchor && anchor.parentNode === main) {
        main.insertBefore(panel, anchor.nextSibling);
      } else {
        main.appendChild(panel);
      }
    }
    current = null;
  }

  function open(key) {
    var meta = PAGES[key];
    if (!meta || !body) return;
    var panel = byId('p-' + key);
    if (!panel) return;

    /* 同一页重复触发（业务跳转 + 导航冒泡各来一次）时直接复用，
       避免反复搬运把滚动位置与输入焦点冲掉 */
    if (current === key && body.getAttribute('data-stage') === 'on' && panel.parentNode === body) {
      panel.classList.add('on');
      return;
    }

    restore();

    current = key;
    panel.classList.add('on');           // 业务侧靠 .on 控制显隐，搬过来仍要保留
    panel.removeAttribute('style');       // 清掉业务可能写死的 display
    body.appendChild(panel);

    DOC.body.setAttribute('data-stage', 'on');
    stage.setAttribute('aria-hidden', 'false');

    if (nameEl) nameEl.textContent = isEn() ? meta.en : meta.zh;
    if (subEl) subEl.textContent = isEn() ? meta.subEn : meta.sub;
    if (icEl) icEl.textContent = meta.ic;

    /* 舞台头部与面板标题重复时，收起面板自己的大标题（只留工具栏） */
    panel.classList.add('stage-host');

    try { panel.scrollTop = 0; } catch (e) { /* ignore */ }
    /* 部分面板把滚动放在内层容器上 */
    var sc = panel.querySelector('.panel-scroll, .workspace-layout, .sub-view');
    if (sc) { try { sc.scrollTop = 0; } catch (e2) { /* ignore */ } }
  }

  function close() {
    if (current) {
      var panel = byId('p-' + current);
      if (panel) {
        panel.classList.remove('on');
        panel.classList.remove('stage-host');
      }
    }
    restore();
    DOC.body.removeAttribute('data-stage');
    DOC.body.removeAttribute('data-stage-full');
    if (stage) stage.setAttribute('aria-hidden', 'true');
    if (fullBtn) fullBtn.innerHTML = ICON_FULL;

    /* 回到对话时把左栏高亮复位到「极简模式」 */
    var navs = DOC.querySelectorAll('body > .side .nav-item');
    for (var i = 0; i < navs.length; i++) {
      navs[i].classList.toggle('on', navs[i].getAttribute('data-p') === 'lite');
    }
    var title = byId('header-title');
    if (title) title.textContent = t('创作台', 'Studio');
  }

  /* ------------------------------------------------------------------ 全屏 */

  function toggleFull() {
    if (!current) return;
    var on = DOC.body.getAttribute('data-stage-full') === '1';
    if (on) {
      DOC.body.removeAttribute('data-stage-full');
      if (fullBtn) { fullBtn.innerHTML = ICON_FULL; fullBtn.title = t('全屏', 'Full screen'); }
    } else {
      DOC.body.setAttribute('data-stage-full', '1');
      if (fullBtn) { fullBtn.innerHTML = ICON_SHRINK; fullBtn.title = t('退出全屏', 'Exit full screen'); }
    }
  }

  /* ------------------------------------------------------------------ 事件 */

  function bindNav() {
    var nav = DOC.querySelector('body > .side .nav-group');
    if (!nav || nav.getAttribute('data-stage-bound') === '1') return;
    nav.setAttribute('data-stage-bound', '1');

    /* 冒泡阶段之后再执行：先让业务把 .panel.on 切好，我们再搬家 */
    nav.addEventListener('click', function (e) {
      var item = e.target && e.target.closest ? e.target.closest('.nav-item') : null;
      if (!item) return;
      var key = item.getAttribute('data-p');
      if (key === 'lite') { setTimeout(close, 0); return; }
      if (!PAGES[key]) return;
      setTimeout(function () { open(key); }, 0);
    });
  }

  /* 左栏二级树里也有直接跳功能页的入口 */
  function bindTreeJumps() {
    DOC.addEventListener('click', function (e) {
      var el = e.target && e.target.closest ? e.target.closest('[data-stage-page]') : null;
      if (!el) return;
      var key = el.getAttribute('data-stage-page');
      if (PAGES[key]) setTimeout(function () { open(key); }, 0);
    });

    /* 二级树项：先把它所属的页面开到舞台上，再让业务切子视图（capture 阶段抢先） */
    DOC.addEventListener('click', function (e) {
      var sub = e.target && e.target.closest ? e.target.closest('.rail-sub') : null;
      if (!sub) return;
      var box = sub.closest('.rail-subs');
      var key = box && box.getAttribute('data-for');
      if (!key || !PAGES[key]) return;
      if (current !== key) open(key);
    }, true);
  }

  /* 业务里任何「跳到某页」的调用，在舞台打开时改走舞台，避免页面在看不见的主区里切换。
     注意：必须先让业务函数跑完（它会挂进页钩子、拉数据、切子视图、写高亮），再搬面板；
     否则页面会停在自己的「加载中」状态。 */
  function patchSwitchPage() {
    var orig = WIN.switchToPage;
    if (typeof orig !== 'function' || orig.__stageWrapped) return;
    var wrapped = function (key, sub) {
      if (DOC.body.getAttribute('data-stage') === 'on' && PAGES[key]) {
        var ret;
        try { ret = orig.apply(this, arguments); } catch (er) { /* ignore */ }
        open(key);
        if (sub && typeof WIN.switchSubTab === 'function') {
          setTimeout(function () { try { WIN.switchSubTab(key, sub); } catch (er) { /* ignore */ } }, 60);
        }
        return ret;
      }
      return orig.apply(this, arguments);
    };
    wrapped.__stageWrapped = true;
    WIN.switchToPage = wrapped;
  }

  function bindKeys() {
    DOC.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      var typing = e.target && (e.target.tagName === 'INPUT' ||
                   e.target.tagName === 'TEXTAREA' || e.target.isContentEditable);
      if (typing) return;
      if (DOC.body.getAttribute('data-stage-full') === '1') {
        toggleFull();
        e.preventDefault();
        return;
      }
      if (DOC.body.getAttribute('data-stage') === 'on') {
        close();
        e.preventDefault();
      }
    });
  }

  /* 语言切换后刷新舞台头文案 */
  var lastEn = null;
  function syncLang() {
    var en = isEn();
    if (en === lastEn) return;
    lastEn = en;
    var back = byId('stageBack');
    var closeBtn = byId('stageClose');
    if (back) back.title = t('回到对话', 'Back to chat');
    if (closeBtn) closeBtn.title = t('关闭，回到对话', 'Close and return to chat');
    if (fullBtn) {
      var isFull = DOC.body.getAttribute('data-stage-full') === '1';
      fullBtn.title = isFull ? t('退出全屏', 'Exit full screen') : t('全屏', 'Full screen');
    }
    if (current && PAGES[current]) {
      var m = PAGES[current];
      if (nameEl) nameEl.textContent = en ? m.en : m.zh;
      if (subEl) subEl.textContent = en ? m.subEn : m.sub;
    }

    /* 中栏底部提示：跟随语言 */
    var tip = byId('lite-tip');
    if (tip) {
      tip.textContent = en
        ? '💡 Enter to chat. Any feature on the left opens on the right — full screen supported.'
        : '💡 提示：按 Enter 直接对话；点左侧功能，内容在右侧打开，可全屏';
    }
  }

  /* ------------------------------------------------------------------ 启动 */

  function boot() {
    if (!isV2()) return;
    if (!build()) return;
    bindNav();
    bindTreeJumps();
    bindKeys();
    patchSwitchPage();
    syncLang();
    setInterval(syncLang, 1000);

    /* 对外：允许其他模块主动打开某个页面（例如右栏资产台的「去工作台」） */
    WIN.YIMU_STAGE = {
      version: '13.0.0',
      open: open,
      close: close,
      full: toggleFull,
      current: function () { return current; },
      PAGES: PAGES
    };
  }

  if (DOC.readyState === 'loading') {
    DOC.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
