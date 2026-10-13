/**
 * 一幕·YIMU Studio (V9.0.0) 国际化多语言引擎 (i18n Engine)
 * 支持中英文即时无缝切换、本地持久化与动态 DOM 翻译绑定。
 */
(function() {
  const I18N_DICT = {
    zh: {
      brand_title: "🎬 一幕·YIMU",
      brand_badge: "爆款工作室",
      nav_dashboard: "操盘大屏",
      nav_dashboard_sub: "全网雷达 · 产能中枢",
      nav_lite: "极简模式",
      nav_lite_sub: "对话成稿 · 秒出排版",
      nav_inspire: "灵感与选题",
      nav_inspire_sub: "热榜挖掘 · 爆款仿写",
      nav_drafts: "内容工作台",
      nav_drafts_sub: "真机实景排版 · 复制",
      nav_studio: "影音工坊",
      nav_studio_sub: "口播 TTS · 竖版短视频",
      nav_console: "控制中心",
      nav_console_sub: "每日工单 · 技能 · 平台治理",
      nav_profile: "个人中心",
      nav_profile_sub: "会员套餐 · 算力明细",
      btn_api: "🔑 我的API",
      btn_login: "创作者已登录",
      btn_refresh: "↻ 刷新状态",
      token_title: "💎 算力:",
      tier_basic: "基础版",
      btn_pricing: "套餐/价格 ▾",
      banner_title: "一幕·YIMU 爆款雷达实时巡航中",
      banner_today_captured: "今日爆款全网捕获:",
      banner_avg_score: "AI平均质量评分:",
      banner_distribution: "全域自适应分发:",
      banner_platforms: "公众号 · 头条 · 小红书 · 视频",
      copilot_title: "爆款创作 Copilot",
      btn_lite_drafts: "极简草稿箱",
      copilot_input_ph: "输入你想创作的爆款主题、一句话灵感或文章改写要求… (Enter 发送，Shift+Enter 换行)",
      btn_send: "发送",
      current_lang_label: "🌐 English",
      lang_name: "简体中文",
      top_task: "⚡ 任务",
      top_settings: "⚙️ 设置",
      top_refresh: "↻ 刷新状态",
      top_auth_logged_in: "创作者已登录",
      billing_credits: "算力:",
      billing_plans_pricing: "套餐/价格",
      plan_free: "基础版",
      radar_title: "一幕·YIMU 爆款雷达实时巡航中",
      theme_system: "跟随系统"
    },
    en: {
      brand_title: "🎬 YIMU Studio",
      brand_badge: "Viral Engine",
      nav_dashboard: "Dashboard",
      nav_dashboard_sub: "Radar & Analytics Hub",
      nav_lite: "Lite Mode",
      nav_lite_sub: "Chat to Draft & Layout",
      nav_inspire: "Inspirations",
      nav_inspire_sub: "Hot Trends & Topic Mining",
      nav_drafts: "Workbench",
      nav_drafts_sub: "Live Layout & Export",
      nav_studio: "Media Studio",
      nav_studio_sub: "Voice TTS & Video AI",
      nav_console: "Control Center",
      nav_console_sub: "Tasks · Skills · Settings",
      nav_profile: "Profile & Account",
      nav_profile_sub: "Plans · Token Ledger",
      btn_api: "🔑 My API Keys",
      btn_login: "Creator Account",
      btn_refresh: "↻ Refresh",
      token_title: "💎 Compute:",
      tier_basic: "Basic Plan",
      btn_pricing: "Plans & Pricing ▾",
      banner_title: "YIMU Viral Radar Live Cruising",
      banner_today_captured: "Today Captured:",
      banner_avg_score: "AI Quality Score:",
      banner_distribution: "Distribution Engine:",
      banner_platforms: "WeChat · Toutiao · Xiaohongshu · Video",
      copilot_title: "Creation Copilot",
      btn_lite_drafts: "Lite Drafts",
      copilot_input_ph: "Enter your viral topic, inspiration, or rewriting instruction... (Enter to send, Shift+Enter for newline)",
      btn_send: "Send",
      current_lang_label: "🌐 中文",
      lang_name: "English",
      top_task: "⚡ Tasks",
      top_settings: "⚙️ Settings",
      top_refresh: "↻ Refresh",
      top_auth_logged_in: "Logged In",
      billing_credits: "Credits:",
      billing_plans_pricing: "Plans/Pricing",
      plan_free: "Free Tier",
      radar_title: "YIMU Radar Live Cruising",
      theme_system: "System"
    }
  };

  let currentLang = localStorage.getItem('yimu_lang') || 'zh';

  function t(key, fallback = '') {
    const dict = I18N_DICT[currentLang] || I18N_DICT.zh;
    return dict[key] || fallback || key;
  }

  function applyLanguage(lang) {
    currentLang = (lang === 'en') ? 'en' : 'zh';
    localStorage.setItem('yimu_lang', currentLang);
    document.documentElement.setAttribute('lang', currentLang === 'en' ? 'en' : 'zh-CN');

    // 1. 批量更新带有 data-i18n 的元素
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      const text = t(key);
      if (text) {
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
          el.placeholder = text;
        } else {
          el.textContent = text;
        }
      }
    });

    // 2. 更新切换按钮文案
    const toggleLabels = document.querySelectorAll('.lang-toggle-label');
    toggleLabels.forEach(el => {
      el.textContent = currentLang === 'en' ? '中文' : 'English';
    });

    const langBtnText = document.getElementById('lang-toggle-text');
    if (langBtnText) {
      langBtnText.textContent = currentLang === 'en' ? '中文' : 'English';
    }

    const mobileLangText = document.getElementById('mobile-lang-text');
    if (mobileLangText) {
      mobileLangText.textContent = currentLang === 'en' ? '🌐 中文' : '🌐 EN';
    }

    const copilotInput = document.getElementById('lite-chat-input');
    if (copilotInput) {
      copilotInput.placeholder = t('copilot_input_ph');
    }

    // 3. 广播语言变更事件
    window.dispatchEvent(new CustomEvent('yimu_lang_changed', { detail: { lang: currentLang } }));
  }

  function toggleLanguage() {
    const next = currentLang === 'zh' ? 'en' : 'zh';
    applyLanguage(next);
    if (window.toast) {
      window.toast(next === 'en' ? 'Switched to English interface' : '已切换至中文界面');
    }
  }

  window.YIMU_I18N = {
    t,
    getLang: () => currentLang,
    setLanguage: applyLanguage,
    toggleLanguage,
    dict: I18N_DICT
  };

  // 暴露给全局便捷调用
  window.t = t;
  window.toggleLanguage = toggleLanguage;

  document.addEventListener('DOMContentLoaded', () => {
    applyLanguage(currentLang);
  });
})();
