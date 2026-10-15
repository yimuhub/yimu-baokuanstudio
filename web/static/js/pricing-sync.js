/**
 * 一幕·YIMU 动态套餐价格同步与超级管理员后台定价配置模块
 * 单一价格真源：/api/pricing 与 /api/admin/pricing
 * 彻底消除前端 99 / 300 硬编码不一致问题，支持后台自主设定并全站实时生效。
 */
(function () {
  'use strict';

  function $(id) {
    return document.getElementById(id);
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function getCsrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  async function reqJson(url, opts) {
    if (typeof window.api === 'function') {
      return await window.api(url, opts);
    }
    var headers = Object.assign({ 'Content-Type': 'application/json' }, (opts && opts.headers) || {});
    if (opts && opts.method && opts.method !== 'GET') {
      headers['X-CSRF-Token'] = getCsrf();
    }
    var r = await fetch(url, Object.assign({ credentials: 'same-origin' }, opts || {}, { headers: headers }));
    var d = await r.json();
    if (!r.ok) {
      var msg = (d && d.detail && d.detail.message) ? d.detail.message : ((d && d.detail) || '请求失败');
      throw new Error(msg);
    }
    return d;
  }

  function notify(msg) {
    if (typeof window.toast === 'function') {
      window.toast(msg);
    } else {
      alert(msg);
    }
  }

  async function syncDynamicPricingUI() {
    try {
      var r = await reqJson('/api/pricing');
      if (!r || !Array.isArray(r.plans)) return;

      r.plans.forEach(function (p) {
        var code = p.code;
        var periodStr = p.period_days === 365 ? '/年' : (p.period_days === 30 ? '/月' : ('/' + p.period_days + '天'));
        var priceText = p.price_yuan > 0 ? ('¥' + p.price_yuan + periodStr) : '¥0';
        var priceHtml = p.price_yuan > 0
          ? ('¥' + p.price_yuan + ' <span style="font-size:11px;font-weight:normal;color:var(--text-muted)">' + periodStr + '</span>')
          : '¥0';
        var creditsStr = Number(p.credits || 0).toLocaleString();

        if (typeof window.BILLING_PLAN_META === 'object' && window.BILLING_PLAN_META) {
          window.BILLING_PLAN_META[code] = {
            name: p.name,
            price: priceText,
            credits: p.credits,
            desc: '已选中 ' + p.name + ' · ' + priceText + ' · 享 ' + creditsStr + ' 点算力额度及全部对应特权'
          };
        }

        // 更新所有 .billing-plan-card[data-plan="..."] 卡片内部价格、名称与权益
        document.querySelectorAll('.billing-plan-card[data-plan="' + code + '"]').forEach(function (card) {
          var nameEl = card.querySelector('[data-plan-name]') || card.children[code === 'pro' ? 1 : 0];
          var priceEl = card.querySelector('[data-plan-price]') || card.children[code === 'pro' ? 2 : 1];
          var featsEl = card.querySelector('[data-plan-feats]') || card.children[code === 'pro' ? 3 : 2];
          if (nameEl) nameEl.textContent = p.name;
          if (priceEl) priceEl.innerHTML = priceHtml;
          if (featsEl) {
            var hl = Array.isArray(p.highlights) && p.highlights.length
              ? p.highlights.slice(0, 3).map(function (h) { return '• ' + esc(String(h).replace(/^\*\*|\*\*$/g, '')); }).join('<br>')
              : '';
            featsEl.innerHTML = '• ' + creditsStr + ' 点算力额度' + (hl ? ('<br>' + hl) : '');
          }
        });
      });

      var selPlan = (typeof window.currentSelectedPlan === 'string' && window.currentSelectedPlan) ? window.currentSelectedPlan : 'pro';
      var metaMap = (typeof window.BILLING_PLAN_META === 'object' && window.BILLING_PLAN_META) ? window.BILLING_PLAN_META : {};
      var curMeta = metaMap[selPlan] || metaMap.pro;
      if (curMeta) {
        if ($('billing-modal-selected-tag')) $('billing-modal-selected-tag').textContent = '已选：' + curMeta.name;
        if ($('billing-action-desc')) {
          $('billing-action-desc').innerHTML = '已选中 <b>' + esc(curMeta.name) + '</b> · ' + esc(curMeta.price) + ' · 享 ' + Number(curMeta.credits || 0).toLocaleString() + ' 点算力额度及专属创作特权';
        }
      }
    } catch (e) {
      console.warn('[pricing-sync] 同步价格失败:', e);
    }
  }

  function ensureAdminPricingCardMounted() {
    var container = $('sp-user-admin');
    if (!container || $('admin-pricing-config-card')) return;
    var card = document.createElement('div');
    card.id = 'admin-pricing-config-card';
    card.className = 'card';
    card.style.cssText = 'margin-top:16px;border:1px solid rgba(240,136,62,0.4)';
    card.innerHTML = [
      '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:14px">',
      '  <div>',
      '    <h3 style="margin:0 0 4px;font-size:16px;color:#fff;display:flex;align-items:center;gap:6px">',
      '      <span>💰</span> 会员套餐与充值价格后台设定（单一价格真源）',
      '    </h3>',
      '    <p class="sub" style="margin:0">超级管理员可在此自主设定 Pro 与 Studio 会员售价、授信算力点数与周期天数，保存后全站弹窗、个人中心、价格页及下单结算实时同步生效。</p>',
      '  </div>',
      '  <div style="display:flex;gap:8px">',
      '    <button class="btn btn-sm ghost" onclick="window.loadAdminPricingConfig()">↻ 刷新配置</button>',
      '    <button class="btn btn-sm ghost" onclick="window.resetAdminPricingConfig()">↺ 恢复默认</button>',
      '    <button class="btn btn-sm ok" onclick="window.saveAdminPricingConfig()">💾 保存价格配置</button>',
      '  </div>',
      '</div>',
      '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px">',
      '  <div style="background:#0d1117;border:1px solid var(--border);border-radius:10px;padding:14px">',
      '    <div style="font-weight:700;color:#fff;margin-bottom:8px">🌱 Free 免费体验档</div>',
      '    <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:6px">套餐名称<input id="adm-price-free-name" type="text" value="新人体验官 Free" style="width:100%;margin-top:4px"></label>',
      '    <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:6px">周期赠送算力（点）<input id="adm-price-free-credits" type="number" min="0" step="100" value="3000" style="width:100%;margin-top:4px"></label>',
      '    <label style="font-size:12px;color:var(--text-muted);display:block">刷新周期（天）<input id="adm-price-free-days" type="number" min="1" value="30" style="width:100%;margin-top:4px"></label>',
      '  </div>',
      '  <div style="background:rgba(240,136,62,0.06);border:1px solid rgba(240,136,62,0.35);border-radius:10px;padding:14px">',
      '    <div style="font-weight:700;color:var(--primary);margin-bottom:8px">🔥 Pro 超级创作者档</div>',
      '    <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:6px">套餐名称<input id="adm-price-pro-name" type="text" value="超级创作者 Pro" style="width:100%;margin-top:4px"></label>',
      '    <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:6px">充值价格（人民币 ¥）<input id="adm-price-pro-yuan" type="number" min="0.01" step="1" placeholder="自主设定价格（如 99）" style="width:100%;margin-top:4px"></label>',
      '    <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:6px">包含算力额度（点）<input id="adm-price-pro-credits" type="number" min="100" step="1000" value="30000" style="width:100%;margin-top:4px"></label>',
      '    <label style="font-size:12px;color:var(--text-muted);display:block">有效周期（天）<input id="adm-price-pro-days" type="number" min="1" value="30" style="width:100%;margin-top:4px"></label>',
      '  </div>',
      '  <div style="background:rgba(168,85,247,0.06);border:1px solid rgba(168,85,247,0.35);border-radius:10px;padding:14px">',
      '    <div style="font-weight:700;color:#d8b4fe;margin-bottom:8px">🏢 Studio 机构矩阵档</div>',
      '    <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:6px">套餐名称<input id="adm-price-studio-name" type="text" value="MCN 机构矩阵版 Studio" style="width:100%;margin-top:4px"></label>',
      '    <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:6px">充值价格（人民币 ¥）<input id="adm-price-studio-yuan" type="number" min="0.01" step="1" placeholder="自主设定 Studio 价格" style="width:100%;margin-top:4px"></label>',
      '    <label style="font-size:12px;color:var(--text-muted);display:block;margin-bottom:6px">包含算力额度（点）<input id="adm-price-studio-credits" type="number" min="100" step="1000" value="200000" style="width:100%;margin-top:4px"></label>',
      '    <label style="font-size:12px;color:var(--text-muted);display:block">有效周期（天）<input id="adm-price-studio-days" type="number" min="1" value="365" style="width:100%;margin-top:4px"></label>',
      '  </div>',
      '</div>'
    ].join('\n');
    container.appendChild(card);
  }

  async function loadAdminPricingConfig() {
    ensureAdminPricingCardMounted();
    try {
      var r = await reqJson('/api/admin/pricing');
      if (!r || !r.ok || !r.plans) return;
      var p = r.plans;
      if (p.free) {
        if ($('adm-price-free-name')) $('adm-price-free-name').value = p.free.name || '新人体验官 Free';
        if ($('adm-price-free-credits')) $('adm-price-free-credits').value = p.free.credits != null ? p.free.credits : 3000;
        if ($('adm-price-free-days')) $('adm-price-free-days').value = p.free.period_days != null ? p.free.period_days : 30;
      }
      if (p.pro) {
        if ($('adm-price-pro-name')) $('adm-price-pro-name').value = p.pro.name || '超级创作者 Pro';
        if ($('adm-price-pro-yuan')) $('adm-price-pro-yuan').value = p.pro.price_yuan != null ? p.pro.price_yuan : '';
        if ($('adm-price-pro-credits')) $('adm-price-pro-credits').value = p.pro.credits != null ? p.pro.credits : 30000;
        if ($('adm-price-pro-days')) $('adm-price-pro-days').value = p.pro.period_days != null ? p.pro.period_days : 30;
      }
      if (p.studio) {
        if ($('adm-price-studio-name')) $('adm-price-studio-name').value = p.studio.name || 'MCN 机构矩阵版 Studio';
        if ($('adm-price-studio-yuan')) $('adm-price-studio-yuan').value = p.studio.price_yuan != null ? p.studio.price_yuan : '';
        if ($('adm-price-studio-credits')) $('adm-price-studio-credits').value = p.studio.credits != null ? p.studio.credits : 200000;
        if ($('adm-price-studio-days')) $('adm-price-studio-days').value = p.studio.period_days != null ? p.studio.period_days : 365;
      }
    } catch (e) {
      console.warn('[admin-pricing] 加载配置失败:', e);
    }
  }

  async function saveAdminPricingConfig() {
    try {
      var payload = {
        plans: {
          free: {
            name: ($('adm-price-free-name') ? $('adm-price-free-name').value : '新人体验官 Free').trim(),
            credits: parseInt($('adm-price-free-credits') ? $('adm-price-free-credits').value : '3000', 10),
            period_days: parseInt($('adm-price-free-days') ? $('adm-price-free-days').value : '30', 10)
          },
          pro: {
            name: ($('adm-price-pro-name') ? $('adm-price-pro-name').value : '超级创作者 Pro').trim(),
            price_yuan: parseFloat($('adm-price-pro-yuan') ? $('adm-price-pro-yuan').value : '0'),
            credits: parseInt($('adm-price-pro-credits') ? $('adm-price-pro-credits').value : '30000', 10),
            period_days: parseInt($('adm-price-pro-days') ? $('adm-price-pro-days').value : '30', 10)
          },
          studio: {
            name: ($('adm-price-studio-name') ? $('adm-price-studio-name').value : 'MCN 机构矩阵版 Studio').trim(),
            price_yuan: parseFloat($('adm-price-studio-yuan') ? $('adm-price-studio-yuan').value : '0'),
            credits: parseInt($('adm-price-studio-credits') ? $('adm-price-studio-credits').value : '200000', 10),
            period_days: parseInt($('adm-price-studio-days') ? $('adm-price-studio-days').value : '365', 10)
          }
        }
      };
      var r = await reqJson('/api/admin/pricing', { method: 'PUT', body: JSON.stringify(payload) });
      if (r && r.ok) {
        notify('✅ 套餐价格与额度已保存并全局生效！');
        await syncDynamicPricingUI();
        if (typeof window.loadIntegratedPricingPanel === 'function') await window.loadIntegratedPricingPanel();
        if (typeof window.loadPlans === 'function') await window.loadPlans();
      }
    } catch (e) {
      notify('❌ 保存价格失败：' + e.message);
    }
  }

  async function resetAdminPricingConfig() {
    if (!confirm('确定恢复系统默认套餐价格配置吗？')) return;
    try {
      var r = await reqJson('/api/admin/pricing/reset', { method: 'POST', body: JSON.stringify({}) });
      if (r && r.ok) {
        notify('↺ 已恢复默认套餐价格配置');
        await loadAdminPricingConfig();
        await syncDynamicPricingUI();
        if (typeof window.loadIntegratedPricingPanel === 'function') await window.loadIntegratedPricingPanel();
        if (typeof window.loadPlans === 'function') await window.loadPlans();
      }
    } catch (e) {
      notify('❌ 恢复失败：' + e.message);
    }
  }

  window.syncDynamicPricingUI = syncDynamicPricingUI;
  window.loadAdminPricingConfig = loadAdminPricingConfig;
  window.saveAdminPricingConfig = saveAdminPricingConfig;
  window.resetAdminPricingConfig = resetAdminPricingConfig;

  function boot() {
    ensureAdminPricingCardMounted();
    syncDynamicPricingUI();
    if ($('adm-price-pro-yuan')) {
      loadAdminPricingConfig();
    }
    var origOpenBilling = window.openBillingModal;
    if (typeof origOpenBilling === 'function' && !origOpenBilling._pricingWrapped) {
      var wrapped = function () {
        syncDynamicPricingUI();
        return origOpenBilling.apply(this, arguments);
      };
      wrapped._pricingWrapped = true;
      window.openBillingModal = wrapped;
    }
    var origLoadAdminUsers = window.loadAdminUsers;
    if (typeof origLoadAdminUsers === 'function' && !origLoadAdminUsers._pricingWrapped) {
      var wrappedUsers = function () {
        ensureAdminPricingCardMounted();
        loadAdminPricingConfig();
        return origLoadAdminUsers.apply(this, arguments);
      };
      wrappedUsers._pricingWrapped = true;
      window.loadAdminUsers = wrappedUsers;
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    setTimeout(boot, 50);
  }
})();
