/* SPDX-License-Identifier: BUSL-1.1
 * 配图视觉风格下拉 · 单一真源（v15.9.10）
 *
 * 背景：全站原有 3 份硬编码风格下拉（灵感页 inspire-image-style-sel、
 * 一句话成爆款 oneshot-image-style-sel、编辑器 stage-image-style-sel），
 * 与后端 VISUAL_STYLE_PRESETS 各自演进——后端增删风格，前端三处都不会变。
 * 本模块统一从 GET /api/drafts/image_styles 拉取（后端 PRESET 唯一真源），
 * 填充三处下拉；接口不可用（未登录/离线/旧版本）时保留页面原有静态选项，
 * 不影响任何生成流程。
 *
 * 约定：各下拉的第一项若为「自动/默认」语义（value 为空或 auto），原样保留；
 * 其余选项全部由接口重建。重复执行幂等（dataset.styleSource 标记）。
 */
(function () {
  'use strict';

  var SELECT_IDS = [
    'inspire-image-style-sel',
    'oneshot-image-style-sel',
    'stage-image-style-sel'
  ];
  var ENDPOINT = '/api/drafts/image_styles';
  var cache = null;

  function isAutoValue(v) {
    return !v || v === 'auto';
  }

  function fillOne(select, styles) {
    if (!select || select.dataset.styleSource === 'api') { return false; }
    var current = select.value;
    var first = select.options.length ? select.options[0] : null;
    var keepFirst = first && isAutoValue(first.value);
    var head = keepFirst ? first.cloneNode(true) : null;

    select.innerHTML = '';
    if (head) { select.appendChild(head); }
    for (var i = 0; i < styles.length; i++) {
      var s = styles[i] || {};
      var key = String(s.key || '').trim();
      if (!key) { continue; }
      var opt = document.createElement('option');
      opt.value = key;
      opt.textContent = (s.icon ? s.icon + ' ' : '') + (s.name || key);
      select.appendChild(opt);
    }

    // 尽量保留用户当前选择；没有则回到「自动」或第一项
    if (current) {
      for (var j = 0; j < select.options.length; j++) {
        if (select.options[j].value === current) {
          select.value = current;
          break;
        }
      }
    }
    if (!select.value && select.options.length) {
      select.selectedIndex = 0;
    }
    select.dataset.styleSource = 'api';
    return true;
  }

  function apply(styles) {
    var changed = 0;
    for (var i = 0; i < SELECT_IDS.length; i++) {
      if (fillOne(document.getElementById(SELECT_IDS[i]), styles)) { changed++; }
    }
    return changed;
  }

  function refresh() {
    if (cache) {
      apply(cache);
      return Promise.resolve(cache);
    }
    return fetch(ENDPOINT, {
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json' }
    })
      .then(function (resp) {
        if (!resp.ok) { return null; }
        return resp.json();
      })
      .then(function (data) {
        if (!data || !data.ok || !Array.isArray(data.styles) || !data.styles.length) {
          return null;
        }
        cache = data.styles;
        apply(cache);
        return cache;
      })
      .catch(function (err) {
        // 静默回退：页面原有静态选项继续可用，不打扰用户
        if (window.console && console.warn) {
          console.warn('[yimu-image-styles] 风格清单拉取失败，沿用静态选项:', err && err.message);
        }
        return null;
      });
  }

  function boot() {
    refresh();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }

  window.YIMU_IMAGE_STYLES = { refresh: refresh };
})();
