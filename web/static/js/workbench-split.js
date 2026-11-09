/* SPDX-License-Identifier: BUSL-1.1 */
/* ==========================================================================
   V15.6 · 内容工作台双栏可拖拽分栏
   --------------------------------------------------------------------------
   左：#wb-editor-pane（源文案编辑）／右：#wb-preview-pane（成稿预览）。
   宽度存成百分比而非像素，换窗口尺寸、进/出全屏舞台都能保持视觉比例。
   只负责布局，不碰任何业务函数、不读接口、不写数据库。
   ========================================================================== */
(function () {
  'use strict';

  var LS = 'yimu.wb.split';
  var DEFAULT_PCT = 46;
  var MIN_EDITOR = 320;      // 编辑栏保底
  var MIN_PREVIEW = 380;     // 预览栏保底
  var HANDLE_W = 10;
  var KEY_STEP = 2;

  var split = null, editor = null, handle = null;
  var pct = DEFAULT_PCT;
  var dragging = false;
  var pointerId = null;
  var lastHidden = null;   // 防止 apply() 改写 style 反过来触发 observer 递归

  function clamp(n, a, b) { return Math.max(a, Math.min(b, n)); }

  function readPct() {
    try {
      var v = parseFloat(localStorage.getItem(LS));
      return isFinite(v) && v > 0 ? clamp(v, 12, 88) : DEFAULT_PCT;
    } catch (e) { return DEFAULT_PCT; }
  }

  function savePct(v) {
    try { localStorage.setItem(LS, String(Math.round(v * 10) / 10)); } catch (e) { /* ignore */ }
  }

  function bounds() {
    var w = split.getBoundingClientRect().width;
    if (!w) return [12, 88];
    var lo = clamp(MIN_EDITOR / w * 100, 10, 60);
    var hi = clamp(100 - (MIN_PREVIEW + HANDLE_W) / w * 100, lo + 4, 90);
    return [lo, hi];
  }

  function apply() {
    if (!split) return;
    var b = bounds();
    pct = clamp(pct, b[0], b[1]);
    split.style.setProperty('--wb-editor-w', pct.toFixed(2) + '%');
    split.setAttribute('data-split-pct', pct.toFixed(1));
    if (handle) {
      handle.setAttribute('aria-valuenow', Math.round(pct));
      handle.setAttribute('aria-valuemin', Math.round(b[0]));
      handle.setAttribute('aria-valuemax', Math.round(b[1]));
    }
  }

  function syncVisibility() {
    if (!handle || !editor || !split) return;
    // toggleLeftEditor() 会直接把编辑栏 display 切成 none；手柄必须一起收起，
    // 否则会残留一条竖线，同时预览栏应吃满整行。
    var hidden = getComputedStyle(editor).display === 'none' ||
                 getComputedStyle(split).display === 'none';
    lastHidden = hidden;
    handle.style.display = hidden ? 'none' : '';
    // 分屏首次显示时容器宽度才真实存在，此时必须按实际像素重算 clamp 边界，
    // 否则 bounds() 在 display:none 阶段退化成 [12,88]，保存的比例会被误裁剪。
    if (!hidden) apply();
  }

  function onMutate() {
    if (!handle || !editor || !split) return;
    var hidden = getComputedStyle(editor).display === 'none' ||
                 getComputedStyle(split).display === 'none';
    // apply() 会改写 split.style，observer 会再次回调；只有「显隐真的变了」才继续，
    // 否则直接吞掉，避免自激循环。
    if (hidden === lastHidden) return;
    syncVisibility();
  }

  function onMove(e) {
    if (!dragging) return;
    var r = split.getBoundingClientRect();
    if (!r.width) return;
    var b = bounds();
    pct = clamp((e.clientX - r.left) / r.width * 100, b[0], b[1]);
    split.style.setProperty('--wb-editor-w', pct.toFixed(2) + '%');
    if (handle) handle.setAttribute('aria-valuenow', Math.round(pct));
    if (e.cancelable) e.preventDefault();
  }

  function onUp(e) {
    if (!dragging) return;
    dragging = false;
    document.body.classList.remove('wb-split-drag');
    if (pointerId != null && handle && handle.releasePointerCapture) {
      try { handle.releasePointerCapture(pointerId); } catch (err) { /* ignore */ }
    }
    pointerId = null;
    savePct(pct);
    apply();
    // iframe srcdoc 宽度是 100%，天然重排；广播 resize 让外壳顺带重算纸高与顶栏
    window.dispatchEvent(new Event('resize'));
  }

  function onDown(e) {
    if (!split || !handle) return;
    if (e.button != null && e.button !== 0) return;
    dragging = true;
    pointerId = e.pointerId;
    document.body.classList.add('wb-split-drag');
    if (handle.setPointerCapture && e.pointerId != null) {
      try { handle.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
    }
    if (e.cancelable) e.preventDefault();
  }

  function reset() {
    pct = DEFAULT_PCT;
    try { localStorage.removeItem(LS); } catch (e) { /* ignore */ }
    apply();
  }

  function onKey(e) {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      var b = bounds();
      pct = clamp(pct + (e.key === 'ArrowLeft' ? -KEY_STEP : KEY_STEP), b[0], b[1]);
      apply();
      savePct(pct);
      window.dispatchEvent(new Event('resize'));
      e.preventDefault();
    } else if (e.key === 'Home' || e.key === 'Enter') {
      reset();
      window.dispatchEvent(new Event('resize'));
      e.preventDefault();
    }
  }

  function boot() {
    split = document.getElementById('split-workbench');
    editor = document.getElementById('wb-editor-pane');
    handle = document.getElementById('wb-splitter');
    if (!split || !editor || !handle) return;

    handle.title = '左右拖动调整两栏宽度 · 双击复位 · 方向键微调';
    handle.setAttribute('aria-valuemin', '12');
    handle.setAttribute('aria-valuemax', '88');
    pct = readPct();
    apply();

    handle.addEventListener('pointerdown', onDown);
    handle.addEventListener('pointermove', onMove);
    handle.addEventListener('pointerup', onUp);
    handle.addEventListener('pointercancel', onUp);
    handle.addEventListener('lostpointercapture', onUp);
    handle.addEventListener('dblclick', reset);
    handle.addEventListener('keydown', onKey);
    // 指针捕获在部分浏览器 / 跨 iframe 场景可能失效，窗口级监听做兜底；
    // onMove 幂等、onUp 有 dragging 守卫，重复触发不会出错。
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
    window.addEventListener('blur', onUp);

    var t = null;
    window.addEventListener('resize', function () {
      clearTimeout(t);
      t = setTimeout(function () { apply(); syncVisibility(); }, 120);
    });

    // 观察编辑栏 / 整个分屏的显隐（selectDraft、toggleLeftEditor、舞台开合）
    if (window.MutationObserver) {
      var mo = new MutationObserver(onMutate);
      mo.observe(editor, { attributes: true, attributeFilter: ['style', 'class'] });
      mo.observe(split, { attributes: true, attributeFilter: ['style', 'class'] });
    }
    syncVisibility();

    window.YIMU_SPLIT = {
      version: '15.6.0',
      reset: reset,
      set: function (v) { pct = clamp(Number(v) || DEFAULT_PCT, 12, 88); apply(); savePct(pct); },
      get: function () { return Math.round(pct * 10) / 10; }
    };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
