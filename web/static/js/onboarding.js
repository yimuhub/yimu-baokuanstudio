/* ==========================================================================
   一幕·YIMU · 首次引导 Wizard（v15.9.1 完整重构 · 自 index.html 外置）
   --------------------------------------------------------------------------
   四步完整引导，右上角随时可跳过（跳过 = 完成标记，绝不反复打扰）：
     ① 免费额度            —— 官方通道每日 3 次轻量生成 + 首篇体验券
     ② 主链路              —— 官方通道（免 Key）或自备 API Key（AES 入保险箱）
     ③ 出图 / 出视频       —— 跟随系统默认（推荐）或指定主通道模型池里的模型
     ④ 文字审核 + 完成摘要 —— 内容安全闸开关，一步收尾

   设计原则（与后端 /api/auth/status 的 wizard.show 判定保持单一真源）：
   - 只在「已登录 且 尚未完成/跳过 且 未配置任何自备 Key」时展示一次；
   - 任何一步可关闭/跳过，关闭即 POST /api/onboarding/done 持久化标记；
   - 展示"官方通道每日 3 次免费体验额度"，让第一次成功先于第一次付费；
   - 普通用户（非管理员）第 3 步自动切换为「跟随系统默认」，不会撞 403。
   ========================================================================== */
(function () {
  'use strict';

  function byId(id) { return document.getElementById(id); }
  function $sel(s) { return document.querySelector(s); }

  // 当前已走到第几步（步骤条点击只允许回看 ≤ 该步，不允许跳到还没走到的步骤）
  window._WIZ_MAX_STEP = 1;
  var WIZ_STEPS = 4;

  window.wizardGo = function (step) {
    var s = Math.min(WIZ_STEPS, Math.max(1, Number(step) || 1));
    window._WIZ_MAX_STEP = Math.max(window._WIZ_MAX_STEP || 1, s);
    document.querySelectorAll('#wizard-steps .wz-step').forEach(function (el) {
      var cur = Number(el.dataset.step);
      el.classList.toggle('on', cur === s);
      el.style.background = cur === s ? 'rgba(64,184,190,.15)' : 'rgba(255,255,255,.04)';
      el.style.color = cur === s ? '#40b8be' : 'var(--text-muted)';
      el.dataset.locked = cur > window._WIZ_MAX_STEP ? '1' : '0';
    });
    for (var i = 1; i <= WIZ_STEPS; i++) {
      var p = byId('wizard-step-' + i);
      if (p) p.style.display = (i === s) ? 'block' : 'none';
    }
    if (s === 2) {
      var leftEl = byId('wz-free-left-2');
      if (leftEl && window._WIZ_FREE_LEFT != null) leftEl.textContent = window._WIZ_FREE_LEFT;
    }
    if (s === 3) wizardLoadGenPrefs();
    if (s === 4) wizardSyncSummary();
    // 切换步骤后把弹窗滚回顶部，避免停在上一屏的滚动位置（矮屏尤其明显）
    var box = document.querySelector('#m-wizard > .modal-box');
    if (box) box.scrollTop = 0;
    wizardSyncScrollFlag();
  };

  // 内容溢出时才给底部操作条上实色底（否则完成页会多一条难看的色带）
  function wizardSyncScrollFlag() {
    var box = document.querySelector('#m-wizard > .modal-box');
    if (!box) return;
    box.classList.toggle('is-scroll', box.scrollHeight - box.clientHeight > 4);
  }
  window.wizardSyncScrollFlag = wizardSyncScrollFlag;

  // 窗口尺寸变化（拖窗口 / 投屏切换分辨率）时重新判定是否需要实色底栏
  window.addEventListener('resize', function () {
    var wz = byId('m-wizard');
    if (wz && wz.classList.contains('on')) wizardSyncScrollFlag();
  });
  // 弹窗从 display:none 变为显示时 clientHeight 才有效，用 ResizeObserver 兜住这次变化
  try {
    var _wzBox = document.querySelector('#m-wizard > .modal-box');
    if (_wzBox && window.ResizeObserver) {
      new ResizeObserver(function () { wizardSyncScrollFlag(); }).observe(_wzBox);
    }
  } catch (_e) { /* 老浏览器没有 ResizeObserver 也不影响主流程 */ }

  // 步骤条点击：只允许回看已走过的步骤
  window.wizardStepClick = function (step) {
    var s = Number(step) || 1;
    if (s > (window._WIZ_MAX_STEP || 1)) return;
    wizardGo(s);
  };

  window.closeWizard = function () {
    /* 任何时刻关闭（跳过 ✕ / 背景 / Esc / 完成按钮）都算"完成/跳过"并落标记，
       避免反复打扰。直接 classList.remove('on')——modal() 没有返回值，不能链式调用。 */
    try {
      var w = byId('m-wizard');
      if (w) w.classList.remove('on');
    } catch (_e) { /* DOM 缺失也不阻塞标记 */ }
    window._WIZ_MAX_STEP = 1;
    fetch('/api/onboarding/done', { method: 'POST' }).catch(function () {});
  };

  window.goInspire = function () {
    /* 「去写第一条爆款 ➔」的落点：切到「灵感与选题」并聚焦关键词输入框。 */
    try {
      var nav = document.querySelector('.nav-item[data-p="inspire"]');
      if (nav) nav.click();
      var kw = byId('sk-kw');
      if (kw) {
        setTimeout(function () {
          try { kw.scrollIntoView({ block: 'center' }); kw.focus(); } catch (e) {}
        }, 200);
      }
    } catch (e) { /* 引导跳转失败不影响主界面 */ }
  };

  /* ---------- 第 2 步：主链路 ---------- */

  window.onWizardProviderChange = function () {
    var sel = byId('wz-key-provider');
    var inp = byId('wz-key-value');
    if (!sel || !inp) return;
    var isCustom = sel.value === 'custom';
    var row = byId('wz-baseurl-row');
    if (row) row.style.display = isCustom ? 'block' : 'none';
    inp.placeholder = isCustom ? 'sk-...' : 'sk-...';
  };

  function wizardSaveByok() {
    var selEl = byId('wz-key-provider');
    var inpEl = byId('wz-key-value');
    var provider = selEl ? selEl.value : 'deepseek';
    var key = inpEl ? inpEl.value.trim() : '';
    var baseUrl = (byId('wz-key-baseurl') || {}).value || '';
    if (!key) {
      if (window.toast) toast('请填写 API Key，或改选「官方通道（免 Key）」');
      if (inpEl) {
        try { inpEl.scrollIntoView({ block: 'center' }); inpEl.focus(); } catch (_e) {}
        inpEl.style.borderColor = '#f85149';
        setTimeout(function () { inpEl.style.borderColor = ''; }, 1800);
      }
      return Promise.resolve(false);
    }
    var btn = byId('wz-finish-btn');
    if (btn) { btn.disabled = true; btn.textContent = '保存中…'; }
    return fetch('/api/user/vault/keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: provider, api_key: key, model_id: '',
        base_url: (provider === 'custom') ? baseUrl.trim() : '',
        label: '首次引导'
      })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) {
          if (window.toast) toast('❌ ' + (d.detail || d.message || '保存失败'), 4000);
          return false;
        }
        if (window.toast) toast('✅ 自备 API Key 已加密保存并生效');
        return true;
      });
    }).catch(function (e) {
      if (window.toast) toast('❌ 网络错误：' + e.message, 4000);
      return false;
    }).finally(function () {
      if (btn) { btn.disabled = false; btn.textContent = '完成引导，开始创作 ➔'; }
    });
  }

  /* ---------- 第 3 步：出图 / 出视频 ---------- */

  var _wizGenPrefsLoaded = false;

  function wizardIsAdmin() {
    try {
      // checkWizard 的 statusData.user 是最可靠的当前用户态；S 里没有 user 字段
      var u = window._WIZ_USER || (window.S && window.S.user) || null;
      return !u || !u.role || u.role === 'admin' || u.role === 'owner';
    } catch (e) { return true; }
  }

  function wizardLoadGenPrefs() {
    var imgSel = byId('wz-image-model');
    var vidSel = byId('wz-video-model');
    if (!imgSel || !vidSel) return;
    var note = byId('wz-genpref-note');
    var isAdmin = wizardIsAdmin();
    if (!isAdmin && note) {
      note.textContent = '当前账号为普通用户：生成模型跟随系统默认即可，无需配置。';
    }
    if (_wizGenPrefsLoaded) return;
    _wizGenPrefsLoaded = true;
    fetch('/api/models/providers').then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d) return;
        var models = (d.cross_models || []);
        var imgs = models.filter(function (m) {
          return (m.category === 'image') && (m.is_active_provider || m.has_key !== false);
        });
        var vids = models.filter(function (m) {
          return (m.category === 'video') && (m.is_active_provider || m.has_key !== false);
        });
        imgSel.innerHTML = '<option value="">（跟随系统默认 · 推荐）</option>'
          + imgs.map(function (m) {
            return '<option value="' + esc(m.id) + '">🎨 ' + esc(m.name || m.id) + '</option>';
          }).join('');
        vidSel.innerHTML = '<option value="">（跟随系统默认 · 推荐）</option>'
          + vids.map(function (m) {
            return '<option value="' + esc(m.id) + '">🎬 ' + esc(m.name || m.id) + '</option>';
          }).join('');
        if (!vids.length && note) {
          note.textContent = '当前主通道模型池还没有视频模型：视频生成需要先在「模型服务 → 多 Agent 路由 → 视频」绑定（出图不受影响，有免 Key 保底引擎）。';
        }
      })
      .catch(function () { /* 拉取失败保持两个「系统默认」选项，不阻塞引导 */ });
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function wizardSaveGenPrefs() {
    var isAdmin = wizardIsAdmin();
    if (!isAdmin) return Promise.resolve(true);
    var imgModel = (byId('wz-image-model') || {}).value || '';
    var vidModel = (byId('wz-video-model') || {}).value || '';
    var jobs = [];
    if (imgModel) {
      jobs.push(fetch('/api/settings', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: { model: imgModel } })
      }));
    }
    if (vidModel) {
      jobs.push(fetch('/api/aivideo/config', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ video_model: vidModel })
      }));
    }
    if (!jobs.length) return Promise.resolve(true);
    return Promise.all(jobs.map(function (p) {
      return p.then(function (r) { return { ok: r.ok }; }).catch(function () { return { ok: false }; });
    })).then(function (rs) {
      var failed = rs.some(function (r) { return !r.ok; });
      if (failed && window.toast) toast('部分生成偏好未能保存（需要管理员权限），已保持系统默认', 4000);
      return true;
    });
  }

  /* ---------- 第 4 步：审核 + 完成 ---------- */

  function wizardSyncSummary() {
    var choice = ($sel('input[name="wz-choice"]:checked') || {}).value || 'official';
    var link = byId('wz-sum-link');
    if (link) link.textContent = choice === 'official' ? '官方通道（免 Key）' : '自备 API Key（' + ((byId('wz-key-provider') || {}).value || '') + '）';
    var img = byId('wz-sum-img');
    var imgModel = (byId('wz-image-model') || {}).value || '';
    if (img) img.textContent = imgModel || '系统默认';
    var vid = byId('wz-sum-video');
    var vidModel = (byId('wz-video-model') || {}).value || '';
    if (vid) vid.textContent = vidModel || '系统默认';
  }

  window.wizardFinish = function () {
    var choice = ($sel('input[name="wz-choice"]:checked') || {}).value || 'official';
    var guardOn = !!(byId('wz-guard-enabled') || {}).checked;
    var saveGuard = fetch('/api/compliance/settings', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: guardOn })
    }).catch(function () { return null; });

    var byokReady = (choice === 'key') ? wizardSaveByok() : Promise.resolve(true);
    byokReady.then(function (ok) {
      if (!ok) return; // Key 保存失败：留在当前步，不让用户以为配好了
      wizardSaveGenPrefs().then(function () {
        return saveGuard;
      }).then(function () {
        var left = (window._WIZ_FREE_LEFT != null) ? window._WIZ_FREE_LEFT : 3;
        var doneMsg = byId('wz-done-msg');
        if (doneMsg) {
          doneMsg.innerHTML = '配置完成！主链路 <b style="color:#40b8be">'
            + (choice === 'official' ? '官方通道' : '自备 Key 通道')
            + '</b>，今日剩余 <b style="color:#40b8be">' + left
            + '</b> 次免费体验额度 · 随时可在「控制中心 → 系统与 API 配置」修改。';
        }
        var btn = byId('wz-finish-btn');
        if (btn) btn.textContent = '🎉 开始创作';
        // 持久化标记（防反复打扰）
        fetch('/api/onboarding/done', { method: 'POST' }).catch(function () {});
        setTimeout(function () {
          window.closeWizard();
          if (window.refresh) try { window.refresh(); } catch (e) {}
          window.goInspire();
        }, 900);
      });
    });
  };

  /* ---------- 展示判定 ---------- */

  // 页面加载时调用：展示 或 静默跳过
  window.checkWizard = async function (statusData) {
    // 从 /api/auth/status 响应取 wizard.show 判定（后端已综合 登录态 + 未标记 两条件）
    var show = !!(statusData && statusData.wizard && statusData.wizard.show);
    if (!show) { window._WIZ_FREE_LEFT = null; return; }
    window._WIZ_USER = (statusData && statusData.user) || null;
    window._WIZ_FREE_LEFT = (statusData.wizard && statusData.wizard.free_left_today) != null
      ? statusData.wizard.free_left_today : null;
    // 二次确认：已配置自备 Key 则不再引导（直接静默标记完成）
    try {
      var r = await fetch('/api/user/vault/keys');
      var d = await r.json().catch(function () { return {}; });
      var hasKey = !!(d && d.using_platform_default === false);
      if (hasKey) { fetch('/api/onboarding/done', { method: 'POST' }).catch(function () {}); return; }
    } catch (e) { /* 网络失败也照显示，引导不阻塞 */ }
    var freeLeft = byId('wz-free-left');
    if (freeLeft && window._WIZ_FREE_LEFT != null) {
      freeLeft.textContent = window._WIZ_FREE_LEFT;
    }
    var w = byId('m-wizard');
    if (!w) return;                       // DOM 缺失就安静退出，绝不抛错打断主流程
    if (w.classList.contains('on')) return; // 已在展示中，别重复初始化
    window._WIZ_MAX_STEP = 1;
    wizardGo(1);
    modal('m-wizard');
    wizardSyncScrollFlag();   // 弹窗刚显示时才算得准 clientHeight
  };
})();
