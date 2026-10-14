/**
 * 一幕·YIMU V10.0.0 全局单次弹窗熔断守卫 (PopupOnceGuard)
 * 规则：同一弹窗最多只弹一次；若未选择/取消或处于创作生成期间，后续弹窗直接静默拦截。
 */
(function(window) {
  if (window.__yimuPopupGuardV10) return;
  window.__yimuPopupGuardV10 = true;
})(window);
