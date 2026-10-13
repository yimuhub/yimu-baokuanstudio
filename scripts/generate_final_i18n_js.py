#!/usr/bin/env python3
"""Compile web/static/js/i18n.js with full 984 translations embedded."""
import json
from pathlib import Path

DICT_FILE = Path("web/static/js/i18n_dict.json")
with open(DICT_FILE, encoding="utf-8") as f:
    mapping = json.load(f)

# Sort phrases by length descending
sorted_phrases = sorted(mapping.items(), key=lambda x: len(x[0]), reverse=True)

# Generate JavaScript
js_content = """/**
 * 一幕·YIMU Studio (V9.1.0) 全局国际化多语言引擎 (i18n Engine)
 * 支持中英文全站 100% 绝对统一切换、各级菜单各级页面深度遍历与实时 DOM 翻译。
 * 彻底根除半中半英状态：英文模式下各级菜单各级页面纯英文，中文模式下各级菜单各级页面纯中文。
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
      lang_name: "简体中文"
    },
    en: {
      brand_title: "🎬 YIMU Studio",
      brand_badge: "Viral Studio",
      nav_dashboard: "Dashboard",
      nav_dashboard_sub: "Radar & Analytics Hub",
      nav_lite: "Lite Mode",
      nav_lite_sub: "Chat to Draft & Layout",
      nav_inspire: "Inspirations",
      nav_inspire_sub: "Hot Trends & Topic Mining",
      nav_drafts: "Workbench",
      nav_drafts_sub: "Live Device Layout & Export",
      nav_studio: "Media Studio",
      nav_studio_sub: "Voice TTS & Video AI",
      nav_console: "Control Center",
      nav_console_sub: "Daily Tasks · Skills · Governance",
      nav_profile: "Profile Center",
      nav_profile_sub: "Membership · Token Ledger",
      btn_api: "🔑 My API",
      btn_login: "Creator Logged In",
      btn_refresh: "↻ Refresh Status",
      token_title: "💎 Credits:",
      tier_basic: "Free Tier",
      btn_pricing: "Plans/Pricing ▾",
      banner_title: "Viral Radar Live Cruising",
      banner_today_captured: "Today Captured:",
      banner_avg_score: "Avg AI Score:",
      banner_distribution: "Adaptive Channels:",
      banner_platforms: "WeChat · Toutiao · RED · Video",
      copilot_title: "Viral Creation Copilot",
      btn_lite_drafts: "Lite Drafts",
      copilot_input_ph: "Enter your viral topic, inspiration, or rewriting instruction... (Enter to send, Shift+Enter for newline)",
      btn_send: "Send",
      current_lang_label: "🌐 中文",
      lang_name: "English"
    }
  };

  // 全站精准词条映射表 (O(1) 匹配)
  const EXACT_MAP = """ + json.dumps(mapping, ensure_ascii=False, indent=2) + """;

  // 反向映射表 (用于切回中文时恢复)
  const REVERSE_MAP = {};
  for (const [zh, en] of Object.entries(EXACT_MAP)) {
    if (en && !REVERSE_MAP[en]) {
      REVERSE_MAP[en] = zh;
    }
  }

  // 按长度倒序排列的子串替换列表
  const PHRASE_LIST = """ + json.dumps(sorted_phrases, ensure_ascii=False) + """;

  let currentLang = localStorage.getItem('yimu_lang') || 'zh';
  let isTranslating = false;

  function t(key, fallback = '') {
    const dict = I18N_DICT[currentLang] || I18N_DICT.zh;
    return dict[key] || fallback || key;
  }

  // 递归翻译 DOM 节点（支持文本、输入框 placeholder、title、aria-label）
  function translateDOMNode(node, toLang) {
    if (!node || node.nodeType === undefined) return;

    const tagName = node.tagName ? node.tagName.toUpperCase() : '';
    if (['SCRIPT', 'STYLE', 'CODE', 'PRE'].includes(tagName)) return;

    if (node.nodeType === Node.TEXT_NODE) {
      let val = node.nodeValue;
      if (!val || !val.trim()) return;
      const trimmed = val.trim();

      if (toLang === 'en') {
        if (!node._orig_zh) {
          node._orig_zh = val;
        }
        // 1. 精准全词匹配 O(1)
        if (EXACT_MAP[trimmed]) {
          node.nodeValue = val.replace(trimmed, EXACT_MAP[trimmed]);
          return;
        }
        // 2. 长短语子串匹配替换
        let txt = val;
        for (let i = 0; i < PHRASE_LIST.length; i++) {
          const zh = PHRASE_LIST[i][0];
          const en = PHRASE_LIST[i][1];
          if (txt.includes(zh)) {
            txt = txt.split(zh).join(en);
          }
        }
        if (txt !== val) {
          node.nodeValue = txt;
        }
      } else {
        // 恢复中文
        if (node._orig_zh) {
          node.nodeValue = node._orig_zh;
        } else if (REVERSE_MAP[trimmed]) {
          node.nodeValue = val.replace(trimmed, REVERSE_MAP[trimmed]);
        }
      }
      return;
    }

    if (node.nodeType === Node.ELEMENT_NODE) {
      // 翻译常用属性
      const attrs = ['placeholder', 'title', 'aria-label'];
      for (let a = 0; a < attrs.length; a++) {
        const attr = attrs[a];
        const val = node.getAttribute(attr);
        if (val && val.trim()) {
          const trimmed = val.trim();
          if (toLang === 'en') {
            if (!node['_orig_' + attr]) node['_orig_' + attr] = val;
            if (EXACT_MAP[trimmed]) {
              node.setAttribute(attr, val.replace(trimmed, EXACT_MAP[trimmed]));
            } else {
              let txt = val;
              for (let i = 0; i < PHRASE_LIST.length; i++) {
                const zh = PHRASE_LIST[i][0];
                const en = PHRASE_LIST[i][1];
                if (txt.includes(zh)) txt = txt.split(zh).join(en);
              }
              node.setAttribute(attr, txt);
            }
          } else {
            if (node['_orig_' + attr]) {
              node.setAttribute(attr, node['_orig_' + attr]);
            } else if (REVERSE_MAP[trimmed]) {
              node.setAttribute(attr, val.replace(trimmed, REVERSE_MAP[trimmed]));
            }
          }
        }
      }

      // 递归子节点
      const children = node.childNodes;
      for (let i = 0; i < children.length; i++) {
        translateDOMNode(children[i], toLang);
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

      // 1. 显式带有 data-i18n 的元素更新
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

      // 2. 深度遍历全页面各级菜单与各级子页面进行 100% 绝对统一中英替换
      translateDOMNode(document.body, currentLang);

      // 3. 更新顶栏与移动端语言切换指示器
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

      // 4. 更新核心输入框 Placeholder
      const copilotInput = document.getElementById('lite-chat-input');
      if (copilotInput) {
        copilotInput.placeholder = t('copilot_input_ph');
      }

      // 5. 更新顶栏标题 (根据当前激活的页面自动更新)
      const activeNav = document.querySelector('.nav-item.on');
      if (activeNav && activeNav.dataset.p) {
        const pKey = activeNav.dataset.p;
        const titles_zh = {dashboard:'操盘大屏', lite:'极简模式', inspire:'灵感与选题', drafts:'内容工作台', studio:'影音工坊', console:'控制中心', profile:'个人中心'};
        const titles_en = {dashboard:'Dashboard', lite:'Lite Mode', inspire:'Inspirations', drafts:'Workbench', studio:'Media Studio', console:'Control Center', profile:'Profile Center'};
        const hTitle = document.getElementById('header-title');
        if (hTitle) {
          hTitle.textContent = currentLang === 'en' ? titles_en[pKey] : titles_zh[pKey];
        }
      }

      // 6. 广播全局语言变更事件
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
    exactMap: EXACT_MAP,
    reverseMap: REVERSE_MAP,
    translateNode: (node) => translateDOMNode(node, currentLang)
  };

  window.t = t;
  window.toggleLanguage = toggleLanguage;

  document.addEventListener('DOMContentLoaded', () => {
    applyLanguage(currentLang);

    // 监听后续动态插入与修改的节点（如 Copilot 消息、任务弹窗、异步加载卡片），确保 100% 语言一致
    const observer = new MutationObserver((mutations) => {
      if (currentLang === 'en' && !isTranslating) {
        mutations.forEach(m => {
          if (m.type === 'childList') {
            m.addedNodes.forEach(node => {
              if (node.nodeType === Node.ELEMENT_NODE || node.nodeType === Node.TEXT_NODE) {
                translateDOMNode(node, 'en');
              }
            });
          } else if (m.type === 'characterData' && m.target) {
            translateDOMNode(m.target, 'en');
          }
        });
      }
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  });
})();
"""

output_path = Path("web/static/js/i18n.js")
output_path.write_text(js_content, encoding="utf-8")
print(f"Generated {output_path} successfully ({len(js_content)} bytes).")
