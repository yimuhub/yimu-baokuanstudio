/**
 * 一幕·YIMU 全站动态版本管理与同步库 (Single Source of Truth)
 * 职责：
 * 1. 从服务端单一真源 (/api/version 或 <meta name="app-version">) 提取系统版本号；
 * 2. 动态同步更新全站各页面所有的 title、徽章、侧边栏、导航栏、页脚等版本号节点；
 * 3. 杜绝任何页面静态硬编码导致的版本漂移或回退错误。
 */
(function(window, document) {
  'use strict';

  var AppVersion = {
    current: '',

    normalize: function(raw) {
      if (!raw) return '';
      return String(raw).trim().replace(/^[vV]/, '');
    },

    get: function() {
      return this.current || this.readMeta() || '';
    },

    getFull: function() {
      var v = this.get();
      return v ? 'V' + v : '';
    },

    readMeta: function() {
      try {
        var meta = document.querySelector('meta[name="app-version"]');
        if (meta && meta.content) {
          return this.normalize(meta.content);
        }
      } catch (e) {}
      return '';
    },

    apply: function(ver) {
      var cleanVer = this.normalize(ver);
      if (!cleanVer) return;
      this.current = cleanVer;
      var fullVer = 'V' + cleanVer;

      // 1. 同步 <meta name="app-version">
      try {
        var meta = document.querySelector('meta[name="app-version"]');
        if (!meta) {
          meta = document.createElement('meta');
          meta.name = 'app-version';
          document.head.appendChild(meta);
        }
        meta.content = cleanVer;
      } catch (e) {}

      // 2. 动态更新 document.title 中的版本号
      try {
        if (document.title) {
          var titlePattern = /V\d+(?:\.\d+)+/g;
          if (titlePattern.test(document.title)) {
            document.title = document.title.replace(titlePattern, fullVer);
          }
        }
      } catch (e) {}

      // 3. 动态更新所有 [data-app-version] 标记的元素
      try {
        var taggedEls = document.querySelectorAll('[data-app-version]');
        taggedEls.forEach(function(el) {
          var mode = el.getAttribute('data-app-version');
          if (mode === 'prefix' || mode === 'v' || (el.textContent && el.textContent.trim().startsWith('V'))) {
            el.textContent = fullVer;
          } else {
            el.textContent = cleanVer;
          }
        });
      } catch (e) {}

      // 4. 动态更新所有 .version-badge 元素
      try {
        var badges = document.querySelectorAll('.version-badge');
        badges.forEach(function(el) {
          el.textContent = fullVer;
        });
      } catch (e) {}

      // 5. 动态更新已知专有 ID 节点
      var idMappings = [
        { id: 'nav-ver-text', val: cleanVer },
        { id: 'side-version-text', val: fullVer },
        { id: 'mobile-ver-badge', val: fullVer },
        { id: 'pricing-ver-text', val: fullVer },
        { id: 'footer-version-text', val: fullVer }
      ];
      idMappings.forEach(function(item) {
        var node = document.getElementById(item.id);
        if (node) {
          node.textContent = item.val;
        }
      });

      // 6. 扫描包含 "当前版本：" 或 "当前版本:" 的代码块容器
      try {
        var codeBlocks = document.querySelectorAll('code, span');
        codeBlocks.forEach(function(el) {
          if (el.children.length === 0 && /^V\d+(?:\.\d+)+$/.test(el.textContent.trim())) {
            // 如果此文本节点正好是一个旧版本号且父级或自身指示为版本
            var parentTxt = (el.parentElement ? el.parentElement.textContent : '');
            if (parentTxt.indexOf('版本') !== -1 || el.classList.contains('version-text')) {
              el.textContent = fullVer;
            }
          }
        });
      } catch (e) {}

      // 7. 派发全局版本更新事件
      try {
        var evt = new CustomEvent('yimu:version-changed', {
          detail: { version: cleanVer, fullVersion: fullVer }
        });
        document.dispatchEvent(evt);
        window.dispatchEvent(evt);
      } catch (e) {}
    },

    sync: function() {
      var self = this;
      return fetch('/api/version', { credentials: 'same-origin' })
        .then(function(r) { return r.ok ? r.json() : null; })
        .then(function(d) {
          if (d && d.version) {
            self.apply(d.version);
            return d.version;
          }
          return self.get();
        })
        .catch(function(err) {
          return self.get();
        });
    },

    init: function() {
      var initialVer = this.readMeta();
      if (initialVer) {
        this.apply(initialVer);
      }
      this.sync();

      var self = this;
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
          self.apply(self.get());
        });
      }
      window.addEventListener('pageshow', function() {
        self.apply(self.get());
      });
    }
  };

  // 挂载至全局
  window.AppVersion = AppVersion;

  // 兼容老代码的全局辅助方法（杜绝硬编码）
  window._normalizeLatestVersion = function(rawVer) {
    var v = AppVersion.normalize(rawVer);
    return v || AppVersion.get() || '10.1';
  };
  window.syncVersionBadge = function() {
    return AppVersion.sync();
  };

  // 立即自初始化
  AppVersion.init();

})(window, document);
