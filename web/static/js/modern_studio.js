/**
 * 一幕·YIMU Modern Studio - 现代交互中枢与 Cmd+K 智慧命令面板
 */

(function () {
  // ⭐ 命令面板统一异常出口：命令执行失败必须让用户看见，
  //   此前只有 console.error，用户点了没反应却毫无提示。
  function notifyError(context, err) {
    const msg = (err && err.message) ? err.message : String(err);
    if (typeof window.toast === 'function') {
      window.toast(`「${context}」执行失败：${msg}`);
    } else {
      console.error(`[${context}]`, err);
    }
  }

  // ⭐ 命令动作与真实实现的映射。
  //   历史遗留：runDecorateImages / runJudgeScore / exportJianyingDraft
  //   三个名字全仓无定义（函数重命名后未同步），命令面板点了必然抛
  //   ReferenceError 且被静默吞掉。这里接到 index.html 里的真实实现：
  //     runDecorateImages      → triggerAutoImages（AI 智能配图）
  //     runJudgeScore          → rescoreCurrent（7维评审官重新打分）
  //     exportJianyingDraft→ exportJianying（导出剪映工程包）
  const ACTIONS = {
    runDecorateImages: 'triggerAutoImages',
    runJudgeScore: 'rescoreCurrent',
    exportJianyingDraft: 'exportJianying',
  };

  /** 调用全局函数；不存在则给出可读提示而不是 ReferenceError。 */
  function callGlobal(name, fallbackLabel) {
    const fn = window[name];
    if (typeof fn !== 'function') {
      notifyError(fallbackLabel || name, new Error(`功能入口「${name}」未加载，请刷新页面后重试`));
      return;
    }
    return fn();
  }

  const COMMANDS = [
    { id: 'search', icon: '🔍', title: '搜索全网对标爆款并仿写', desc: '输入赛道关键词，深度抓取 3-5 篇真实长文', shortcut: 'S', action: () => { switchSubTab('inspire', 'sp-search'); closeModal(); } },
    { id: 'editor', icon: '✍️', title: '打开一幕·富文本编辑器', desc: '图文混排、段落微调与排版直出', shortcut: 'E', action: () => { openYimuRichEditor(); } },
    { id: 'image', icon: '🎨', title: '一键电影级智能配图 (5图)', desc: 'AI 通读全文提炼视觉主体，双通道高清渲染', shortcut: 'P', action: () => { callGlobal(ACTIONS.runDecorateImages, 'AI 智能配图'); } },
    { id: 'review', icon: '⚖️', title: '7维爆款质量评审与定向提分', desc: '按网感、情绪共鸣、结构钩子自动润色', shortcut: 'R', action: () => { callGlobal(ACTIONS.runJudgeScore, '7维质量评审'); } },
    { id: 'xhs_pub', icon: '📕', title: '一键直发小红书', desc: '自动带图文、标签发布到小号', shortcut: 'X', action: () => { runXhsDirectPublish(); } },
    { id: 'jianying', icon: '🎬', title: '导出剪映短剧工程 (Draft)', desc: '含分镜、旁白音频、母带工程文件', shortcut: 'J', action: () => { callGlobal(ACTIONS.exportJianyingDraft, '导出剪映工程'); } },
    { id: 'watermark', icon: '🏷️', title: '输出水印与品牌印记设置', desc: '自由选择开启/关闭磨砂印记', shortcut: 'W', action: () => { openWatermarkModal(); } },
    { id: 'settings', icon: '⚙️', title: '系统与企业级 AI 模型配置', desc: '多网关、多模态模型无缝切换', shortcut: ',', action: () => { modal('m-cfg'); } },
  ];

  let selectedIdx = 0;
  let filteredCmds = [...COMMANDS];

  function initCmdKPalette() {
    if (document.getElementById('cmd-k-palette')) return;

    const el = document.createElement('div');
    el.id = 'cmd-k-palette';
    el.innerHTML = `
      <div class="cmd-k-box">
        <div class="cmd-k-header">
          <span style="font-size:18px">⚡</span>
          <input type="text" class="cmd-k-input" id="cmd-k-search" placeholder="输入功能命令，或按快捷键快速直达…" autocomplete="off">
          <span style="font-size:11px;color:var(--text-tertiary);background:rgba(255,255,255,0.06);padding:3px 8px;border-radius:4px">ESC 退出</span>
        </div>
        <div class="cmd-k-list" id="cmd-k-results"></div>
        <div class="cmd-k-footer">
          <span>提示：使用 <kbd style="background:rgba(255,255,255,0.1);padding:1px 5px;border-radius:3px">↑</kbd> <kbd style="background:rgba(255,255,255,0.1);padding:1px 5px;border-radius:3px">↓</kbd> 切换，<kbd style="background:rgba(255,255,255,0.1);padding:1px 5px;border-radius:3px">↵</kbd> 执行</span>
          <span>一幕·YIMU 极速命令中枢</span>
        </div>
      </div>
    `;
    document.body.appendChild(el);

    const input = el.querySelector('#cmd-k-search');
    input.addEventListener('input', (e) => {
      const q = e.target.value.toLowerCase().trim();
      filteredCmds = COMMANDS.filter(c => c.title.toLowerCase().includes(q) || c.desc.toLowerCase().includes(q) || c.shortcut.toLowerCase() === q);
      selectedIdx = 0;
      renderCmdList();
    });

    input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        selectedIdx = (selectedIdx + 1) % Math.max(1, filteredCmds.length);
        renderCmdList();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        selectedIdx = (selectedIdx - 1 + filteredCmds.length) % Math.max(1, filteredCmds.length);
        renderCmdList();
      } else if (e.key === 'Enter') {
        e.preventDefault();
        executeSelectedCmd();
      } else if (e.key === 'Escape') {
        hideCmdK();
      }
    });

    el.addEventListener('click', (e) => {
      if (e.target === el) hideCmdK();
    });

    // 监听全局 Cmd+K / Ctrl+K
    window.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        toggleCmdK();
      }
      if (e.key === 'Escape') {
        hideCmdK();
      }
    });
  }

  function renderCmdList() {
    const box = document.getElementById('cmd-k-results');
    if (!box) return;
    if (filteredCmds.length === 0) {
      box.innerHTML = '<div style="text-align:center;padding:32px;color:var(--text-tertiary);font-size:13px">无匹配命令，按 ESC 关闭</div>';
      return;
    }
    box.innerHTML = filteredCmds.map((c, idx) => `
      <div class="cmd-k-item ${idx === selectedIdx ? 'selected' : ''}" data-idx="${idx}">
        <div style="display:flex;align-items:center;gap:12px">
          <span style="font-size:18px">${c.icon}</span>
          <div>
            <div style="font-weight:600;color:#fff">${c.title}</div>
            <div style="font-size:11.5px;color:var(--text-tertiary);margin-top:2px">${c.desc}</div>
          </div>
        </div>
        <span class="shortcut">${c.shortcut}</span>
      </div>
    `).join('');

    box.querySelectorAll('.cmd-k-item').forEach(el => {
      el.addEventListener('click', () => {
        selectedIdx = parseInt(el.dataset.idx);
        executeSelectedCmd();
      });
    });
  }

  function executeSelectedCmd() {
    const cmd = filteredCmds[selectedIdx];
    if (cmd && typeof cmd.action === 'function') {
      hideCmdK();
      // ⭐ 异常必须可见：命令执行失败时给用户明确提示，不静默吞掉
      try {
        const ret = cmd.action();
        // action 可能是 async：补挂 rejection 捕获，避免异步失败无感知
        if (ret && typeof ret.catch === 'function') {
          ret.catch(err => notifyError(cmd.title, err));
        }
      } catch (err) {
        notifyError(cmd.title, err);
      }
    }
  }

  function showCmdK() {
    const p = document.getElementById('cmd-k-palette');
    if (!p) return;
    p.classList.add('active');
    const input = p.querySelector('#cmd-k-search');
    input.value = '';
    filteredCmds = [...COMMANDS];
    selectedIdx = 0;
    renderCmdList();
    setTimeout(() => input.focus(), 50);
  }

  function hideCmdK() {
    const p = document.getElementById('cmd-k-palette');
    if (p) p.classList.remove('active');
  }

  function toggleCmdK() {
    const p = document.getElementById('cmd-k-palette');
    if (!p) return;
    if (p.classList.contains('active')) hideCmdK();
    else showCmdK();
  }

  window.toggleCmdK = toggleCmdK;
  window.showCmdK = showCmdK;
  window.hideCmdK = hideCmdK;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCmdKPalette);
  } else {
    initCmdKPalette();
  }
})();
