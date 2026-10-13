#!/usr/bin/env python3
"""Generate optimized web/static/js/i18n.js for V9.1.1 with 1768 terms full coverage."""
import json
import re

def main():
    with open('web/static/js/i18n_dict.json', 'r', encoding='utf-8') as f:
        dict_map = json.load(f)

    # Sort phrase list by length descending
    phrases = sorted(dict_map.items(), key=lambda x: len(x[0]), reverse=True)
    
    # Reverse phrase list for falling back to Chinese
    reverse_phrases = sorted(dict_map.items(), key=lambda x: len(x[1]), reverse=True)

    i18n_js_content = '''/**
 * 一幕·YIMU Studio (V9.1.1) 全局国际化多语言引擎 (i18n Engine)
 * 支持中英文全站 100% 绝对统一切换、各级菜单各级页面深度遍历与实时 DOM 翻译。
 * 杜绝半中半英状态：英文模式下各级菜单各级页面纯英文，中文模式下各级菜单各级页面纯中文。
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
      nav_profile_sub: "画像 · 密钥 · 偏好设置",
      top_profile_6d: "👤 6维画像",
      top_my_api: "🔑 我的API",
      theme_system: "跟随系统",
      top_auth_logged_in: "创作者已登录",
      billing_credits: "算力:",
      plan_free: "基础版",
      billing_plans_pricing: "套餐/价格",
      top_refresh: "↻ 刷新状态",
      radar_title: "一幕·YIMU 爆款雷达实时巡航中",
      top_task: "⚡ 任务",
      top_settings: "⚙️ 设置",
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
      nav_profile_sub: "Persona · Keys · Preferences",
      top_profile_6d: "👤 6D Persona",
      top_my_api: "🔑 My API",
      theme_system: "Follow System",
      top_auth_logged_in: "Creator Logged In",
      billing_credits: "Credits:",
      plan_free: "Free Tier",
      billing_plans_pricing: "Plans/Pricing",
      top_refresh: "↻ Refresh Status",
      radar_title: "YIMU Studio Viral Radar Cruising",
      top_task: "⚡ Tasks",
      top_settings: "⚙️ Settings",
      copilot_title: "Viral Creation Copilot",
      btn_lite_drafts: "Lite Drafts",
      copilot_input_ph: "Enter your viral topic, inspiration, or rewriting instruction... (Enter to send, Shift+Enter for newline)",
      btn_send: "Send",
      current_lang_label: "🌐 中文",
      lang_name: "English"
    }
  };

  const EXACT_MAP = ''' + json.dumps(dict_map, ensure_ascii=False, indent=2) + ''';

  // 反向映射表 (用于切回中文时恢复)
  const REVERSE_MAP = {};
  for (const [zh, en] of Object.entries(EXACT_MAP)) {
    if (en && !REVERSE_MAP[en]) {
      REVERSE_MAP[en] = zh;
    }
  }

  // 按长度倒序排列的子串替换列表 (中文 -> 英文)
  const PHRASE_LIST = ''' + json.dumps(phrases, ensure_ascii=False) + ''';

  // 反向长短语替换列表 (英文 -> 中文)
  const REVERSE_PHRASE_LIST = ''' + json.dumps([(en, zh) for zh, en in reverse_phrases if len(en) > 3], ensure_ascii=False) + ''';

  const CHINESE_REGEX = /[\\u4e00-\\u9fa5]/;

  let currentLang = localStorage.getItem('yimu_lang') || 'zh';
  let isTranslating = false;

  function t(key, fallback = '') {
    const dict = I18N_DICT[currentLang] || I18N_DICT.zh;
    return dict[key] || fallback || key;
  }

  // 递归翻译 DOM 节点（支持文本、输入框 placeholder、title、aria-label、value）
  function translateDOMNode(node, toLang) {
    if (!node || node.nodeType === undefined) return;

    const tagName = node.tagName ? node.tagName.toUpperCase() : '';
    if (['SCRIPT', 'STYLE', 'CODE', 'PRE'].includes(tagName)) return;

    if (node.nodeType === Node.TEXT_NODE) {
      const val = node.nodeValue;
      if (!val || !val.trim()) return;
      const trimmed = val.trim();

      if (toLang === 'en') {
        // 保存原始中文 (仅当包含中文字符时才存为 _orig_zh)
        if (CHINESE_REGEX.test(val) && !node._orig_zh) {
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
        } else {
          // 反向长短语替换
          let txt = val;
          for (let i = 0; i < REVERSE_PHRASE_LIST.length; i++) {
            const en = REVERSE_PHRASE_LIST[i][0];
            const zh = REVERSE_PHRASE_LIST[i][1];
            if (txt.includes(en)) {
              txt = txt.split(en).join(zh);
            }
          }
          if (txt !== val) {
            node.nodeValue = txt;
          }
        }
      }
      return;
    }

    if (node.nodeType === Node.ELEMENT_NODE) {
      // 翻译常用属性
      const attrs = ['placeholder', 'title', 'aria-label', 'value'];
      for (let a = 0; a < attrs.length; a++) {
        const attr = attrs[a];
        const val = node.getAttribute(attr);
        if (val && val.trim()) {
          const trimmed = val.trim();
          if (toLang === 'en') {
            if (CHINESE_REGEX.test(val) && !node['_orig_' + attr]) {
              node['_orig_' + attr] = val;
            }
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

      // 3. 更新页面标题 <title>
      if (currentLang === 'en') {
        document.title = "YIMU Studio V9.1.1 · Omni-Media Super Creation Engine";
      } else {
        document.title = "一幕·YIMU 爆款工作室 V9.1.1 · 全媒体超级创作引擎";
      }

      // 4. 更新顶栏与移动端语言切换指示器
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

      // 5. 更新核心输入框 Placeholder
      const copilotInput = document.getElementById('lite-chat-input');
      if (copilotInput) {
        copilotInput.placeholder = t('copilot_input_ph');
      }

      // 6. 更新顶栏标题 (根据当前激活的页面自动更新)
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

      // 7. 广播全局语言变更事件
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
        isTranslating = true;
        try {
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
        } finally {
          isTranslating = false;
        }
      }
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  });
})();
'''

    with open('web/static/js/i18n.js', 'w', encoding='utf-8') as f:
        f.write(i18n_js_content)
    print("Generated web/static/js/i18n.js successfully! Length:", len(i18n_js_content))

if __name__ == '__main__':
    main()
