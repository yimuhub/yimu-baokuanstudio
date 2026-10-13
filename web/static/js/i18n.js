/**
 * 一幕·YIMU Studio (V9.1.0) 国际化多语言引擎 (i18n Engine)
 * 支持中英文全站 100% 绝对统一切换、本地持久化与实时 DOM 翻译。
 * 杜绝半中半英状态，英文模式下全站纯英文，中文模式下全站纯中文。
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
      theme_system: "跟随系统",
      theme_light: "浅色明亮",
      theme_dark: "深色暗黑",
      nav_my_api: "🔑 我的API"
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
      theme_system: "System",
      theme_light: "Light",
      theme_dark: "Dark",
      nav_my_api: "🔑 My API"
    }
  };

  // 全站通用中英文词条对应字典（用于递归全域纯净替换）
  const PHRASE_MAP = [
    // 品牌与导航
    ["一幕·YIMU 爆款工作室", "YIMU Viral Studio"],
    ["一幕·YIMU 移动工作室", "YIMU Mobile Studio"],
    ["一幕·YIMU", "YIMU Studio"],
    ["全媒体超级创作引擎", "Omni-Media AI Creation Engine"],
    ["全媒体创作引擎", "Omni-Media Creation Engine"],
    ["PC与移动端数据100%全域实时互联", "PC & Mobile 100% Real-Time Cloud Synced"],
    ["操盘大屏", "Dashboard"],
    ["极简模式", "Lite Mode"],
    ["灵感与选题", "Inspirations"],
    ["内容工作台", "Workbench"],
    ["影音工坊", "Media Studio"],
    ["控制中心", "Control Center"],
    ["个人中心", "Profile Center"],
    ["全网雷达 · 产能中枢", "Radar & Analytics Hub"],
    ["对话成稿 · 秒出排版", "Chat to Draft & Layout"],
    ["热榜挖掘 · 爆款仿写", "Hot Trends & Topic Mining"],
    ["真机实景排版 · 复制", "Live Device Layout & Export"],
    ["口播 TTS · 竖版短视频", "Voice TTS & Video AI"],
    ["每日工单 · 技能 · 平台治理", "Daily Tasks · Skills · Governance"],
    ["会员套餐 · 算力明细", "Membership · Token Ledger"],
    ["创作者已登录", "Creator Logged In"],
    ["已登录", "Logged In"],
    ["退出登录 / 切换账号", "Log Out / Switch Account"],
    ["退出登录", "Log Out"],
    ["检查更新 ↗", "Check Update ↗"],
    ["检查更新", "Check Update"],
    ["版本更新展示", "Release Notes"],
    ["版本更新", "Releases"],
    ["版本", "Version"],
    ["跟随系统", "System Theme"],
    ["浅色明亮", "Light Mode"],
    ["深色暗黑", "Dark Mode"],
    ["6维画像", "6D Persona"],
    ["我的API", "My API"],
    ["刷新状态", "Refresh Status"],
    ["算力:", "Credits:"],
    ["算力", "Credits"],
    ["基础版", "Free Tier"],
    ["专业版", "Pro Tier"],
    ["工作室版", "Studio Tier"],
    ["套餐/价格 ▾", "Plans/Pricing ▾"],
    ["套餐/价格", "Plans/Pricing"],
    ["商业化套餐与价格权益", "Pricing & Subscription Plans"],
    ["商业化套餐", "Pricing Plans"],
    ["爆款雷达实时巡航中", "Viral Radar Live Cruising"],
    ["今日爆款全网捕获:", "Today Captured:"],
    ["AI平均质量评分:", "Avg AI Score:"],
    ["全域自适应分发:", "Adaptive Channels:"],
    ["公众号 · 头条 · 小红书 · 视频", "WeChat · Toutiao · RED · Video"],
    ["爆款创作 Copilot", "Viral Creation Copilot"],
    ["极简草稿箱", "Lite Drafts"],
    ["极简草稿箱管理中枢", "Lite Drafts Management Hub"],
    ["模型/技能", "Model / Skills"],
    ["发送", "Send"],
    ["全部草稿", "All Drafts"],
    ["全部平台形态", "All Platforms"],
    ["全部评分等级", "All Scores"],
    ["微信公众号", "WeChat Official Account"],
    ["小红书笔记", "RED Notes"],
    ["今日头条", "Toutiao Feed"],
    ["90分以上 (顶级爆款)", "90+ Score (Top Tier)"],
    ["80-90分 (良好达标)", "80-90 Score (Good)"],
    ["搜索草稿标题或内容关键词…", "Search draft title or keyword..."],
    ["全景算力任务队列", "Panoramic Compute Task Queue"],
    ["模型与系统设置", "Model & System Settings"],
    ["功能菜单", "Menu"],
    ["极简", "Lite"],
    ["稿件", "Drafts"],
    ["热榜", "Hot"],
    ["工坊", "Studio"],
    ["我的", "Profile"],
    ["任务", "Tasks"],
    ["设置", "Settings"],
    ["爆款效果归因分析 (Postmortem)", "Viral Performance Postmortem"],
    ["立即诊断", "Analyze Now"],
    ["录入真实发布笔记数据，AI 深度拆解核心爆点或平淡成因，提炼可复用公式。", "Input publication metrics to extract key virality catalysts and reusable formulas."],
    ["媒体名称:", "Media Brand:"],
    ["当前算力:", "Current Balance:"],
    ["当前版本:", "Current Version:"],
    ["账号与口令", "Account & Password"],
    ["修改密码", "Change Password"],
    ["算力账本", "Token Ledger"],
    ["修改当前登录账号密码", "Change current account password"],
    ["商业化充值与卡密兑换", "Top-up & Redeem Key"],
    ["检查 GitHub 仓库最新代码", "Check GitHub for updates"],
    ["GitHub 仓库在线升级与同步", "Online GitHub Upgrade & Sync"],
    ["立即升级", "Upgrade Now"],
    ["升级 Pro 会员", "Upgrade to Pro Tier"],
    ["该功能为 Pro 会员专属，升级解锁完整体验", "This feature is exclusive to Pro members. Upgrade to unlock full access."],
    ["查看价格与购买", "View Pricing & Purchase"],
    ["稍后再说", "Maybe Later"],
    ["还未配置大模型", "LLM Model Not Configured"],
    ["去配置", "Configure"],
    ["爆款 Agent 任务正在进行中", "Viral Agent Task In Progress"],
    ["当前执行阶段", "Current Execution Phase"],
    ["正在分析指令意图并锁定微创操作靶位…", "Analyzing intent and targeting operation zone..."],
    ["全能微创改写与生成引擎调度中…", "Dispatching micro-surgical rewrite and generation engine..."],
    ["一幕 · 7 维爆款质量体检报告", "YIMU 7-Dimensional Viral Health Report"],
    ["良好", "Good"],
    ["正在载入体检诊断…", "Loading diagnostic assessment..."],
    ["重新体检打分", "Re-run Diagnostics"],
    ["关闭", "Close"],
    ["呼唤 Agent 按此建议定向提分", "Invoke Agent to Boost Score"],
    ["当前已是最新版本", "Current version is up to date"],
    ["无需升级", "No update needed"],
    ["检测失败", "Check failed"],
    ["请检查网络连接", "Please check network connection"],
    ["连接 GitHub 异常", "Failed to connect to GitHub"],
    ["已是最新", "Up to Date"],
    ["您好！欢迎使用 一幕·YIMU 移动极简模式。告诉我您今天想创作什么？", "Hello! Welcome to YIMU Mobile Lite Mode. What would you like to create today?"],
    ["零门槛小白上手即用！您可轻触下方 6 大快捷提示词，或在输入框直接告诉我您的想法：", "Zero learning curve! Tap the quick prompts below or tell me your topic directly:"],
    ["帮我写一篇关于普通人下班副业的小红书爆款图文", "Write a high-converting RED lifestyle post about side hustles after work."],
    ["抓取今日最热科技话题生成公众号长文", "Fetch today's top tech news and synthesize an in-depth WeChat article."],
    ["把当前稿件重拟 5 个点击率最高的爆款悬念标题", "Generate 5 high-CTR curiosity-gap headlines for current draft."]
  ];

  let currentLang = localStorage.getItem('yimu_lang') || 'zh';
  let isTranslating = false;

  function t(key, fallback = '') {
    const dict = I18N_DICT[currentLang] || I18N_DICT.zh;
    return dict[key] || fallback || key;
  }

  // 递归遍历 DOM 文本节点，进行 100% 彻底的中英替换
  function translateDOMNode(node, toLang) {
    if (!node || node.nodeType === undefined) return;

    // 跳过代码块与脚本
    const tagName = node.tagName ? node.tagName.toUpperCase() : '';
    if (['SCRIPT', 'STYLE', 'CODE', 'PRE'].includes(tagName)) return;

    if (node.nodeType === Node.TEXT_NODE) {
      let val = node.nodeValue;
      if (!val || !val.trim()) return;

      if (toLang === 'en') {
        if (!node._orig_zh) {
          node._orig_zh = val;
        }
        let txt = val;
        for (const [zh, en] of PHRASE_MAP) {
          if (txt.includes(zh)) {
            txt = txt.split(zh).join(en);
          }
        }
        if (txt !== val) {
          node.nodeValue = txt;
        }
      } else {
        if (node._orig_zh) {
          node.nodeValue = node._orig_zh;
        }
      }
      return;
    }

    if (node.nodeType === Node.ELEMENT_NODE) {
      // 翻译常用属性
      const attrs = ['placeholder', 'title', 'aria-label'];
      attrs.forEach(attr => {
        const val = node.getAttribute(attr);
        if (val) {
          if (toLang === 'en') {
            if (!node[`_orig_${attr}`]) node[`_orig_${attr}`] = val;
            let txt = val;
            for (const [zh, en] of PHRASE_MAP) {
              if (txt.includes(zh)) txt = txt.split(zh).join(en);
            }
            node.setAttribute(attr, txt);
          } else {
            if (node[`_orig_${attr}`]) {
              node.setAttribute(attr, node[`_orig_${attr}`]);
            }
          }
        }
      });

      // 递归子节点
      for (let i = 0; i < node.childNodes.length; i++) {
        translateDOMNode(node.childNodes[i], toLang);
      }
    }
  }

  function applyLanguage(lang) {
    if (isTranslating) return;
    isTranslating = true;
    try {
      currentLang = (lang === 'en') ? 'en' : 'zh';
      localStorage.setItem('yimu_lang', currentLang);
      document.documentElement.setAttribute('lang', currentLang === 'en' ? 'en' : 'zh-CN');

      // 1. 更新显式带有 data-i18n 的元素
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

      // 2. 深度遍历全页面 DOM 进行全站绝对统一中英替换（杜绝半中半英）
      translateDOMNode(document.body, currentLang);

      // 3. 更新顶栏切换按钮文案
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

      // 4. 更新输入框 Placeholder
      const copilotInput = document.getElementById('lite-chat-input');
      if (copilotInput) {
        copilotInput.placeholder = t('copilot_input_ph');
      }

      // 5. 广播全局语言变更事件
      window.dispatchEvent(new CustomEvent('yimu_lang_changed', { detail: { lang: currentLang } }));
    } finally {
      isTranslating = false;
    }
  }

  function toggleLanguage() {
    const next = currentLang === 'zh' ? 'en' : 'zh';
    applyLanguage(next);
    if (window.toast) {
      window.toast(next === 'en' ? 'Switched to English' : '已切换至中文');
    }
  }

  window.YIMU_I18N = {
    t,
    getLang: () => currentLang,
    setLanguage: applyLanguage,
    toggleLanguage,
    dict: I18N_DICT,
    translateNode: (node) => translateDOMNode(node, currentLang)
  };

  window.t = t;
  window.toggleLanguage = toggleLanguage;

  document.addEventListener('DOMContentLoaded', () => {
    applyLanguage(currentLang);

    // 监听后续动态插入的节点（例如 Copilot 消息、弹窗内容），确保 100% 语言一致
    const observer = new MutationObserver((mutations) => {
      if (currentLang === 'en' && !isTranslating) {
        mutations.forEach(m => {
          m.addedNodes.forEach(node => {
            if (node.nodeType === Node.ELEMENT_NODE || node.nodeType === Node.TEXT_NODE) {
              translateDOMNode(node, 'en');
            }
          });
        });
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
  });
})();
