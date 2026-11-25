/* SPDX-License-Identifier: BUSL-1.1 */
/* ==========================================================================
   Harness 外壳 · rail（A 外壳底座）
   --------------------------------------------------------------------------
   左栏 chrome：brand / 新建 / 搜索 / 主导航（4 工作区 + 更多分组）/
   #hxRailCtx 上下文插槽 / 额度卡 / 账号行；tasks 与 content 基础版接真实数据。
   真实 .nav-item[data-p] 节点保留在 aside.side 内，点击链路不变。
   非 body[data-shell="harness"] 下零副作用退出。
   ========================================================================== */
(function () {
  'use strict';

  var DOC = document;
  var WIN = window;
  if (!DOC.body || DOC.body.getAttribute('data-shell') !== 'harness') return;
  var HX = WIN.HX;
  if (!HX) return;

  function $(id) { return DOC.getElementById(id); }
  function qsa(root, sel) { return Array.prototype.slice.call(root.querySelectorAll(sel)); }
  function railAmount(v) {
    if (v == null) return null;
    var m = String(v).replace(/[¥￥\s]/g, '').match(/\d[\d,]*/);
    if (!m) return null;
    var n = Number(m[0].replace(/,/g, ''));
    return isNaN(n) ? null : n;
  }

  var WS_MENU = [
    { ws: 'tasks', icon: 'tasks', label: '任务' },
    { ws: 'content', icon: 'file', label: '内容工作台' },
    { ws: 'collect', icon: 'globe', label: '采集工作台' },
    { ws: 'settings', icon: 'settings', label: '系统设置' }
  ];
  var MORE_NAV = [
    { key: 'dashboard', icon: 'grid', label: '操盘大屏' },
    { key: 'studio', icon: 'video', label: '影音工坊' },
    { key: 'pricing', icon: 'bolt', label: '套餐与价格' },
    { key: 'profile', icon: 'user', label: '个人中心' }
  ];

  /* ------------------------------ 状态文案 ------------------------------ */
  function taskDot(status) {
    var s = String(status || '');
    if (/running|pending|processing|queue/.test(s)) return { cls: 'green', text: '生成中' };
    if (/preview|draft|review/.test(s)) return { cls: 'orange', text: '待审阅' };
    if (/done|success|finished|published|drafted|approved/.test(s)) return { cls: '', text: '已完成' };
    if (/failed|rejected|error/.test(s)) return { cls: 'blue', text: '失败' };
    return { cls: 'blue', text: '草稿' };
  }
  function draftDot(status) {
    var s = String(status || '');
    if (s === 'published' || s === 'drafted' || s === 'approved') return { cls: 'green', text: '已发布' };
    if (s === 'preview') return { cls: 'orange', text: '待审' };
    if (s === 'draft') return { cls: 'blue', text: '草稿' };
    if (s === 'rejected') return { cls: '', text: '已拒绝' };
    return { cls: '', text: '归档' };
  }

  /* ------------------------------ tasks 上下文 ------------------------------ */
  function renderTasksCtx(slot, ctx) {
    var tasks = (ctx.state.tasks || []).slice(0, 8);
    var drafts = ctx.drafts || [];
    slot.innerHTML =
      '<div class="hx-rail-sect-head"><span>最近任务</span><button type="button" title="刷新任务">' + HX.ico('refresh', 'sm') + '</button></div>' +
      '<div class="hx-task-list"></div>';
    var list = slot.querySelector('.hx-task-list');
    var headBtn = slot.querySelector('.hx-rail-sect-head button');
    if (headBtn) headBtn.addEventListener('click', function () { HX.refresh(); });

    if (!tasks.length && !drafts.length) {
      list.innerHTML = '<div class="hx-rail-empty">暂无进行中的任务，新建一个开始创作。</div>';
      return;
    }

    /* 优先真实任务队列；无任务时回退草稿列表作为最近稿件。 */
    var rows = tasks.map(function (t) {
      var dot = taskDot(t.status);
      var asset = (t.target_id ? '关联稿件' : '');
      var title = t.name || t.current_step || '未命名任务';
      var media = /video|drama|tts/.test(String(t.task_type || ''));
      return {
        cover: media ? 'blue' : 'orange',
        thumb: (String(title).charAt(0) || '任'),
        title: title,
        dot: dot.cls,
        meta: dot.text,
        extra: asset,
        targetId: t.target_id || t.id
      };
    });
    if (!rows.length) {
      rows = drafts.slice(0, 6).map(function (d) {
        var dot = draftDot(d.status);
        var title = d.title || '未命名草稿';
        return {
          cover: 'orange',
          thumb: (String(title).charAt(0) || '草'),
          title: title,
          dot: dot.cls,
          meta: dot.text,
          extra: (d.cards ? d.cards + ' 卡' : '') + (d.imgs ? ' · ' + d.imgs + ' 图' : ''),
          targetId: d.id
        };
      });
    }

    rows.forEach(function (r) {
      var row = DOC.createElement('button');
      row.type = 'button';
      row.className = 'hx-task' + (r.targetId === ctx.state.draftId ? ' is-active' : '');
      row.innerHTML =
        '<span class="hx-task-thumb hx-cover-' + r.cover + '">' + HX.esc(r.thumb) + '</span>' +
        '<span class="hx-task-main">' +
          '<span class="hx-task-title">' + HX.esc(HX.trim(r.title, 22)) + '</span>' +
          '<span class="hx-task-meta"><i class="hx-dot ' + r.dot + '"></i>' + HX.esc(r.meta) +
            (r.extra ? '<span class="hx-sep">·</span>' + HX.esc(r.extra) : '') + '</span>' +
        '</span>' +
        '<span class="hx-task-more">' + HX.ico('more', 'sm') + '</span>';
      row.addEventListener('click', function () {
        if (r.targetId) HX.openDraft(r.targetId);
        else HX.openWorkspace('tasks');
      });
      list.appendChild(row);
    });
  }

  /* ------------------------------ content 上下文（真实草稿 DOM） ------------------------------ */
  var showArchived = false;

  function draftItems(ctx) {
    var box = $('draft-list-container');
    var cards = box ? qsa(box, '.draft-card') : [];
    var items = [];
    if (cards.length) {
      cards.forEach(function (card) {
        var titleEl = card.querySelector('.dc-title');
        var metaEl = card.querySelector('.dc-meta');
        var title = titleEl ? titleEl.textContent.trim() : '未命名草稿';
        var meta = metaEl ? metaEl.textContent.trim() : '';
        var on = card.classList.contains('on');
        var chk = card.querySelector('input[data-id]');
        var id = chk ? chk.dataset.id : null;
        if (id) items.push({ id: String(id), title: title, meta: meta, on: on, card: card });
      });
    } else {
      (ctx.drafts || []).slice(0, 12).forEach(function (d) {
        var dot = draftDot(d.status);
        items.push({
          id: String(d.id),
          title: d.title || '未命名草稿',
          meta: dot.text,
          on: String(d.id) === String(ctx.state.draftId),
          draft: d
        });
      });
    }
    return items;
  }

  function renderContentCtx(slot, ctx) {
    slot.innerHTML =
      '<div class="hx-rail-sect-head"><span>草稿箱</span><button type="button" title="刷新草稿">' + HX.ico('refresh', 'sm') + '</button></div>' +
      '<div class="hx-rail-filter"></div>' +
      '<div class="hx-draft-list"></div>';
    var list = slot.querySelector('.hx-draft-list');
    var filter = slot.querySelector('.hx-rail-filter');
    var headBtn = slot.querySelector('.hx-rail-sect-head button');
    if (headBtn) headBtn.addEventListener('click', function () { HX.refresh(); });

    var items = draftItems(ctx);
    var archived = items.filter(function (it) { return isArchived(it.id); });
    var archCount = archived.length;
    var visible = items.filter(function (it) {
      return showArchived ? isArchived(it.id) : !isArchived(it.id);
    });
    visible.sort(function (a, b) { return (isPinned(b.id) ? 1 : 0) - (isPinned(a.id) ? 1 : 0); });

    filter.innerHTML =
      '<button type="button" class="' + (!showArchived ? 'is-active' : '') + '" data-view="active">全部 <b>' + (items.length - archCount) + '</b></button>' +
      (archCount ? '<button type="button" class="' + (showArchived ? 'is-active' : '') + '" data-view="archived">已归档 <b>' + archCount + '</b></button>' : '');
    qsa(filter, '[data-view]').forEach(function (b) {
      b.addEventListener('click', function () {
        showArchived = b.getAttribute('data-view') === 'archived';
        renderContentCtx(slot, ctx);
      });
    });

    if (!visible.length) {
      list.innerHTML = '<div class="hx-rail-empty">' +
        (archCount && !showArchived ? '暂无未归档草稿，可切换到「已归档」查看。' : '暂无草稿。可在任务页生成成稿。') +
        '</div>';
      return;
    }

    visible.forEach(function (it) {
      var pinned = isPinned(it.id);
      var archivedRow = isArchived(it.id);
      var dot = it.draft ? draftDot(it.draft.status) : { cls: 'orange', text: it.meta };
      var thumb = (it.title || '草').charAt(0);
      var row = DOC.createElement('button');
      row.type = 'button';
      row.className = 'hx-draft-row' + (it.on ? ' is-active' : '') + (pinned ? ' is-pinned' : '') + (archivedRow ? ' is-archived' : '');
      row.innerHTML =
        '<span class="hx-draft-thumb hx-cover-orange">' + HX.esc(thumb) + '</span>' +
        '<span class="hx-draft-main">' +
          '<span class="hx-draft-title">' + HX.esc(HX.trim(it.title, 20)) +
            (pinned ? '<i class="hx-pin-mark" title="已置顶">' + HX.ico('pin', 'sm') + '</i>' : '') + '</span>' +
          '<span class="hx-draft-meta"><i class="hx-dot ' + dot.cls + '"></i>' + HX.esc(HX.trim(it.meta, 24)) + '</span>' +
        '</span>' +
        '<span class="hx-draft-more" role="button" tabindex="0" title="稿件操作" aria-label="稿件操作">' + HX.ico('more', 'sm') + '</span>';
      row.addEventListener('click', function () {
        if (it.id) HX.openDraft(it.id); else if (it.card) it.card.click();
      });
      var more = row.querySelector('.hx-draft-more');
      var openMenu = function (e) { e.stopPropagation(); e.preventDefault(); openDraftMenu(more, it); };
      more.addEventListener('click', openMenu);
      more.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); openMenu(e); }
      });
      list.appendChild(row);
    });
  }

  /* ------------------------------ 采集 / 设置兜底（D 模块可覆盖） ------------------------------ */
  function renderPendingCtx(slot, label, hint) {
    slot.innerHTML =
      '<div class="hx-rail-sect-head"><span>' + HX.esc(label) + '</span></div>' +
      '<div class="hx-rail-empty">' + HX.esc(hint || '该工作台面板由对应模块接入，当前暂无内容。') + '</div>';
  }

  /* ------------------------------ 本机偏好：置顶 / 归档 ------------------------------
     后端暂无 pin / archive / 字段，先按 workspaceId + did 落 localStorage；
     待后端加字段后切服务端同步。 */
  var PREF = { pin: 'yimu.hx.draftPin', archive: 'yimu.hx.draftArchive' };

  function prefLoad(key) {
    try {
      var v = JSON.parse(WIN.localStorage.getItem(key) || '{}');
      return v && typeof v === 'object' ? v : {};
    } catch (e) { return {}; }
  }
  function prefSave(key, v) {
    try { WIN.localStorage.setItem(key, JSON.stringify(v)); } catch (e) { /* 隐私模式静默 */ }
  }
  function prefKey(did) {
    var ws = (HX.state.status && HX.state.status.workspace_id) || 'ws-default';
    return String(ws) + ':' + String(did);
  }
  function isPinned(did) { return !!prefLoad(PREF.pin)[prefKey(did)]; }
  function isArchived(did) { return !!prefLoad(PREF.archive)[prefKey(did)]; }
  function togglePref(key, did) {
    var m = prefLoad(key), k = prefKey(did);
    if (m[k]) { delete m[k]; } else { m[k] = true; }
    prefSave(key, m);
    return !!m[k];
  }
  function rerail() { if (typeof HX._renderAll === 'function') HX._renderAll(); }
  function callReal(name, args) {
    var fn = WIN[name];
    if (typeof fn !== 'function') return false;
    try { fn.apply(null, args || []); return true; }
    catch (e) { console.warn('[HX rail] ' + name + ' 调用失败:', e); return false; }
  }

  /* ------------------------------ 草稿三点菜单（单实例） ------------------------------ */
  var draftMenu = null;
  var draftMenuFor = null;

  function closeDraftMenu() {
    if (draftMenu) draftMenu.classList.remove('open');
    draftMenuFor = null;
  }

  function ensureDraftMenu() {
    if (draftMenu) return draftMenu;
    draftMenu = DOC.createElement('div');
    draftMenu.className = 'hx-draft-menu';
    draftMenu.id = 'hxDraftMenu';
    draftMenu.addEventListener('click', function (e) { e.stopPropagation(); });
    DOC.body.appendChild(draftMenu);
    DOC.addEventListener('pointerdown', function (e) {
      if (!draftMenu.classList.contains('open')) return;
      if (draftMenu.contains(e.target)) return;
      if (draftMenuFor && draftMenuFor.contains(e.target)) return;
      closeDraftMenu();
    });
    DOC.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeDraftMenu();
    });
    return draftMenu;
  }

  function positionDraftMenu(anchor) {
    var m = draftMenu;
    if (!m) return;
    var rect = anchor.getBoundingClientRect();
    var mw = m.offsetWidth || 180, mh = m.offsetHeight || 220, pad = 8;
    var left = rect.right + 6;
    if (left + mw > WIN.innerWidth - pad) left = rect.left - mw - 6;
    left = Math.max(pad, Math.min(left, WIN.innerWidth - mw - pad));
    var top = rect.top;
    if (top + mh > WIN.innerHeight - pad) top = WIN.innerHeight - mh - pad;
    top = Math.max(pad, top);
    m.style.left = left + 'px';
    m.style.top = top + 'px';
  }

  function openDraftMenu(anchor, item) {
    var m = ensureDraftMenu();
    closeDraftMenu();
    draftMenuFor = anchor;
    var pinned = isPinned(item.id);
    var archived = isArchived(item.id);
    var draft = (HX.state.drafts || []).filter(function (x) { return String(x.id) === String(item.id); })[0] || item;
    var rows = [
      { act: 'open', icon: 'file', label: '打开稿件' },
      { act: 'rename', icon: 'edit', label: '重命名' },
      { act: 'export', icon: 'download', label: '导出 HTML' },
      { act: 'history', icon: 'clock', label: '历史版本' },
      { sep: '本机偏好（本地保存，待后端字段同步）' },
      { act: 'pin', icon: 'pin', label: pinned ? '取消置顶' : '置顶', tag: '本机' },
      { act: 'archive', icon: 'folder', label: archived ? '取消归档' : '归档', tag: '本机' },
      { act: 'delete', icon: 'x', label: '删除', tag: '软删除', danger: true },
      { act: 'copy', icon: 'copy', label: '复制派生', tag: '未接入', disabled: true }
    ];
    m.innerHTML = rows.map(function (r) {
      if (r.sep) return '<div class="hx-dm-sep">' + HX.esc(r.sep) + '</div>';
      var cls = 'hx-dm-item' + (r.disabled ? ' is-disabled' : '') + (r.danger ? ' is-danger' : '');
      return '<button type="button" class="' + cls + '" data-act="' + r.act + '"' + (r.disabled ? ' disabled' : '') + '>' +
        HX.ico(r.icon, 'sm') + '<span class="hx-dm-label">' + HX.esc(r.label) + '</span>' +
        (r.tag ? '<em class="hx-dm-tag">' + HX.esc(r.tag) + '</em>' : '') + '</button>';
    }).join('');
    qsa(m, '[data-act]').forEach(function (b) {
      b.addEventListener('click', function () {
        onDraftMenuAct(b.getAttribute('data-act'), item, draft);
      });
    });
    m.classList.add('open');
    positionDraftMenu(anchor);
  }

  function onDraftMenuAct(act, item, draft) {
    closeDraftMenu();
    switch (act) {
      case 'open':
        HX.openDraft(item.id);
        break;
      case 'rename':
        openRenameModal(item.id, (draft && draft.title) || item.title || '');
        break;
      case 'export':
        callReal('exportDraftAsHtml', [item.id, draft || {}]);
        break;
      case 'history':
        openHistoryModal(item.id);
        break;
      case 'pin': {
        var nowPin = togglePref(PREF.pin, item.id);
        HX.toast(nowPin ? '已置顶（本机偏好）' : '已取消置顶');
        rerail();
        break;
      }
      case 'archive': {
        var nowArch = togglePref(PREF.archive, item.id);
        HX.toast(nowArch ? '已归档（本机偏好，可在「已归档」中恢复）' : '已取消归档');
        rerail();
        break;
      }
      case 'delete':
        openDeleteConfirm(item);
        break;
      case 'copy':
        break; /* 无后端端点：禁用态，不画假动作 */
    }
  }

  /* ------------------------------ 通用弹层 ------------------------------ */
  function ensureModal(id) {
    var m = $(id);
    if (m) return m;
    m = DOC.createElement('div');
    m.id = id;
    m.className = 'hx-modal-wrap';
    m.innerHTML = '<div class="hx-modal-mask" data-mask></div><div class="hx-modal-panel" role="dialog" aria-modal="true"></div>';
    m.addEventListener('click', function (e) {
      if (e.target.closest && e.target.closest('[data-mask]')) closeModal(m);
    });
    DOC.body.appendChild(m);
    return m;
  }
  function openModal(m) { m.classList.add('on'); }
  function closeModal(m) { m.classList.remove('on'); }
  DOC.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') qsa(DOC, '.hx-modal-wrap.on').forEach(closeModal);
  });

  /* ------------------------------ 重命名 ------------------------------ */
  var renameModal = null, renameDid = null;
  function openRenameModal(did, title) {
    renameDid = did;
    renameModal = ensureModal('hxRenameModal');
    var panel = renameModal.querySelector('.hx-modal-panel');
    panel.innerHTML =
      '<div class="hx-modal-head"><span class="hx-modal-title">重命名稿件</span>' +
      '<button type="button" class="hx-modal-x" data-close>' + HX.ico('x', 'sm') + '</button></div>' +
      '<div class="hx-modal-body"><input class="hx-modal-input" id="hxRenameInput" maxlength="60" value="' + HX.esc(title) + '">' +
      '<div class="hx-modal-err" id="hxRenameErr"></div></div>' +
      '<div class="hx-modal-foot"><button type="button" class="hx-btn ghost" data-close>取消</button>' +
      '<button type="button" class="hx-btn primary" id="hxRenameSave">保存</button></div>';
    panel.querySelector('[data-close]').addEventListener('click', function () { closeModal(renameModal); });
    var input = panel.querySelector('#hxRenameInput');
    input.focus(); input.select();
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); doRename(); } });
    panel.querySelector('#hxRenameSave').addEventListener('click', doRename);
    openModal(renameModal);
  }

  function doRename() {
    var input = $('hxRenameInput'), err = $('hxRenameErr'), btn = $('hxRenameSave');
    var title = input ? input.value.trim() : '';
    if (!title) { if (err) err.textContent = '标题不能为空'; return; }
    if (btn) btn.disabled = true;
    HX.api('/api/drafts/' + encodeURIComponent(renameDid) + '/title', {
      method: 'POST',
      body: JSON.stringify({ title: title })
    }).then(function (res) {
      if (btn) btn.disabled = false;
      if (!res) { if (err) err.textContent = '保存失败，请稍后重试'; return; }
      var fresh = (res.draft && res.draft.title) || title;
      var row = (HX.state.drafts || []).filter(function (x) { return String(x.id) === String(renameDid); })[0];
      if (row) row.title = fresh;
      closeModal(renameModal);
      callReal('refresh', []);
      if (String(HX.state.draftId) === String(renameDid)) callReal('selectDraft', [renameDid]);
      HX.toast('已重命名为「' + HX.trim(fresh, 20) + '」');
      rerail();
    });
  }

  /* ------------------------------ 历史版本 ------------------------------ */
  var historyModal = null;
  function openHistoryModal(did) {
    historyModal = ensureModal('hxHistoryModal');
    var panel = historyModal.querySelector('.hx-modal-panel');
    panel.innerHTML =
      '<div class="hx-modal-head"><span class="hx-modal-title">历史版本</span>' +
      '<button type="button" class="hx-modal-x" data-close>' + HX.ico('x', 'sm') + '</button></div>' +
      '<div class="hx-modal-body"><div class="hx-hist-list" id="hxHistList">读取历史版本…</div></div>';
    panel.querySelector('[data-close]').addEventListener('click', function () { closeModal(historyModal); });
    openModal(historyModal);
    HX.api('/api/drafts/' + encodeURIComponent(did) + '/history').then(function (res) {
      var box = $('hxHistList');
      if (!box) return;
      var list = (res && res.history) || [];
      if (!list.length) {
        box.innerHTML = '<div class="hx-modal-empty">暂无历史版本（重大重写或重构前会自动存档）</div>';
        return;
      }
      box.innerHTML = list.map(function (h, i) {
        var t = HX.fmtTime(h.created_at);
        var score = h.score != null ? ' · 评分 ' + h.score : '';
        return '<div class="hx-hist-row">' +
          '<div class="hx-hist-main"><div class="hx-hist-title">' + HX.esc(h.title || ('版本 ' + (i + 1))) + '</div>' +
          '<div class="hx-hist-meta">' + HX.esc(t || '') + HX.esc(score) + '</div></div>' +
          '<button type="button" class="hx-btn ghost hx-hist-restore" data-hid="' + HX.esc(h.id) + '">回退至此版</button></div>';
      }).join('');
      qsa(box, '[data-hid]').forEach(function (b) {
        b.addEventListener('click', function () {
          callReal('restoreDraftVer', [did, b.getAttribute('data-hid')]);
          closeModal(historyModal);
        });
      });
    });
  }

  /* ------------------------------ 删除确认 ------------------------------ */
  var confirmModal = null, confirmDid = null;
  function openDeleteConfirm(item) {
    confirmDid = item.id;
    confirmModal = ensureModal('hxConfirmModal');
    var panel = confirmModal.querySelector('.hx-modal-panel');
    panel.innerHTML =
      '<div class="hx-modal-head"><span class="hx-modal-title">删除稿件</span>' +
      '<button type="button" class="hx-modal-x" data-close>' + HX.ico('x', 'sm') + '</button></div>' +
      '<div class="hx-modal-body">' +
      '<p class="hx-confirm-desc">确定删除「' + HX.esc(HX.trim(item.title || '未命名草稿', 28)) + '」？</p>' +
      '<p class="hx-confirm-hint">将移入废纸篓（软删除），不物理清除文件。</p></div>' +
      '<div class="hx-modal-foot"><button type="button" class="hx-btn ghost" data-close>取消</button>' +
      '<button type="button" class="hx-btn danger" id="hxConfirmDelete">确认删除</button></div>';
    panel.querySelector('[data-close]').addEventListener('click', function () { closeModal(confirmModal); });
    panel.querySelector('#hxConfirmDelete').addEventListener('click', doDeleteDraft);
    openModal(confirmModal);
  }

  function doDeleteDraft() {
    var btn = $('hxConfirmDelete');
    if (btn) btn.disabled = true;
    HX.api('/api/drafts/delete', {
      method: 'POST',
      body: JSON.stringify({ ids: [confirmDid] })
    }).then(function (res) {
      if (btn) btn.disabled = false;
      var removed = (res && res.removed) || [];
      var skipped = (res && res.skipped) || [];
      if (removed.indexOf(String(confirmDid)) >= 0) {
        HX.state.drafts = (HX.state.drafts || []).filter(function (x) { return String(x.id) !== String(confirmDid); });
        closeModal(confirmModal);
        HX.toast('已删除 1 篇草稿');
        callReal('refresh', []);
        HX.refresh();
      } else {
        closeModal(confirmModal);
        HX.toast(skipped.length ? '未删除：该稿件无权操作或不存在' : '删除失败，请稍后重试');
      }
    });
  }

  HX.registerRailCtx('tasks', renderTasksCtx);
  HX.registerRailCtx('content', renderContentCtx);
  HX.registerRailCtx('collect', function (slot) { renderPendingCtx(slot, '采集记录', '采集工作台由采集模块接入，暂未展示记录。'); });
  HX.registerRailCtx('settings', function (slot) { renderPendingCtx(slot, '设置导航', '设置项由设置模块接入。'); });

  /* ------------------------------ 左栏 chrome ------------------------------ */
  function readVersion() {
    var v = DOC.querySelector('[data-app-version="prefix"]');
    if (v && v.textContent.trim()) return v.textContent.trim();
    var raw = $('side-version-text');
    return raw ? raw.textContent.trim() : '';
  }

  function buildChrome(root) {
    if ($('hxRailBrand')) return;

    var brand = DOC.createElement('div');
    brand.className = 'hx-rail-brand';
    brand.id = 'hxRailBrand';
    brand.innerHTML =
      '<img class="hx-brand-logo" src="/static/img/logo-icon.png" srcset="/static/img/logo-icon.png 1x, /static/img/logo.png 2x" alt="一幕·YIMU">' +
      '<div class="hx-brand-text">' +
        '<div class="hx-brand-line"><span class="hx-brand-title">一幕·YIMU</span><span class="hx-brand-badge">爆款工作室</span></div>' +
        '<span class="hx-brand-sub">全媒体创作工作台</span>' +
      '</div>' +
      '<button class="hx-rail-collapse" id="hxRailToggle" type="button" title="收起左栏" aria-label="收起左栏">' + HX.ico('panel', 'sm') + '</button>';

    var body = DOC.createElement('div');
    body.className = 'hx-rail-body';
    body.id = 'hxRailBody';
    body.innerHTML =
      '<button class="hx-new-task" id="hxNewTask" type="button">' +
        '<span class="hx-new-task-plus">' + HX.ico('plus', 'sm') + '</span>' +
        '<span class="hx-new-label">新建任务</span><kbd>⌘N</kbd>' +
      '</button>' +
      '<button class="hx-rail-search" id="hxRailSearch" type="button">' +
        HX.ico('search') + '<span>搜索任务、资产…</span><kbd>⌘K</kbd>' +
      '</button>' +
      '<nav class="hx-rail-menu" id="hxRailMenu" aria-label="主导航"></nav>' +
      '<div class="hx-rail-ctx" id="hxRailCtx"></div>';

    var bottom = DOC.createElement('div');
    bottom.className = 'hx-rail-bottom';
    bottom.id = 'hxRailBottom';
    bottom.innerHTML =
      '<div class="hx-quota-card">' +
        '<div class="hx-quota-line">' + HX.ico('bolt') + '<span>算力余额</span><b id="hxQuotaTier">套餐有效</b></div>' +
        '<div class="hx-quota-num"><span id="hxQuotaNum">—</span><small>Token</small></div>' +
        '<div class="hx-quota-track"><i id="hxQuotaBar"></i></div>' +
      '</div>' +
      '<div class="hx-profile-row">' +
        '<span class="hx-profile-avatar" id="hxProfileAvatar">曹</span>' +
        '<div class="hx-profile-main"><div class="hx-profile-name" id="hxProfileName">个人中心</div>' +
        '<div class="hx-profile-sub" id="hxProfileSub">已登录</div></div>' +
        '<button class="hx-profile-gear" type="button" title="个人设置">' + HX.ico('settings', 'sm') + '</button>' +
      '</div>';

    root.appendChild(brand);
    root.appendChild(body);
    root.appendChild(bottom);

    var menu = $('hxRailMenu');
    WS_MENU.forEach(function (m) {
      var b = DOC.createElement('button');
      b.type = 'button';
      b.className = 'hx-menu-item';
      b.setAttribute('data-ws', m.ws);
      b.innerHTML = HX.ico(m.icon) + '<span class="hx-menu-label">' + HX.esc(m.label) + '</span><span class="hx-menu-count"></span>';
      b.addEventListener('click', function () { HX.openWorkspace(m.ws); });
      menu.appendChild(b);
    });

    var more = DOC.createElement('div');
    more.className = 'hx-rail-more';
    more.innerHTML = '<div class="hx-rail-sect-head"><span>更多</span></div>';
    MORE_NAV.forEach(function (n) {
      var b = DOC.createElement('button');
      b.type = 'button';
      b.className = 'hx-menu-item hx-menu-more';
      b.setAttribute('data-page', n.key);
      b.innerHTML = HX.ico(n.icon) + '<span class="hx-menu-label">' + HX.esc(n.label) + '</span>';
      b.addEventListener('click', function () { HX.openMorePage(n.key); });
      more.appendChild(b);
    });
    menu.appendChild(more);

    var newBtn = $('hxNewTask');
    if (newBtn) newBtn.addEventListener('click', function () { HX.newTask(); });
    var search = $('hxRailSearch');
    if (search) search.addEventListener('click', function () {
      if (typeof WIN.toggleCmdK === 'function') { try { WIN.toggleCmdK(); } catch (e) { /* 忽略 */ } }
    });
    var toggle = $('hxRailToggle');
    if (toggle) toggle.addEventListener('click', function () { HX.toggleRail(); });
    var gear = bottom.querySelector('.hx-profile-gear');
    if (gear) gear.addEventListener('click', function () {
      if (typeof WIN.switchToProfileCenter === 'function') { try { WIN.switchToProfileCenter(); } catch (e) { /* 忽略 */ } }
    });
    var profile = bottom.querySelector('.hx-profile-row');
    if (profile) profile.addEventListener('click', function (e) {
      if (e.target.closest('.hx-profile-gear')) return;
      if (typeof WIN.switchToProfileCenter === 'function') { try { WIN.switchToProfileCenter(); } catch (e) { /* 忽略 */ } }
    });
  }

  /* 菜单 / 更多项激活态纯同步：唯一判据 `.is-active`，由 core 路由在渲染中栏前调用。 */
  function syncMenuActive(root, st) {
    qsa(root, '.hx-menu-item[data-ws]').forEach(function (b) {
      b.classList.toggle('is-active', !st.moreKey && b.getAttribute('data-ws') === st.workspace);
    });
    qsa(root, '.hx-menu-item[data-page]').forEach(function (b) {
      b.classList.toggle('is-active', b.getAttribute('data-page') === st.moreKey || b.getAttribute('data-page') === st.page);
    });
  }

  /* 左栏开合按钮回显：迷你态 → 展开入口（图标 + title/aria-label 写明「展开左栏」）；
     常态 → 收起入口。状态唯一判据 HX.state.railMini，沿用既有持久化。 */
  function syncRailToggle() {
    var btn = $('hxRailToggle');
    if (!btn) return;
    var mini = !!(HX.state && HX.state.railMini);
    btn.title = mini ? '展开左栏' : '收起左栏';
    btn.setAttribute('aria-label', mini ? '展开左栏' : '收起左栏');
    btn.innerHTML = HX.ico(mini ? 'expand' : 'panel', 'sm');
  }

  function refreshChrome(root, ctx) {
    if (!$('hxRailBrand')) return;
    var state = ctx.state;

    /* 菜单激活态与计数 */
    syncMenuActive(root, state);

    qsa(root, '.hx-menu-item[data-ws]').forEach(function (b) {
      var ws = b.getAttribute('data-ws');
      var count = b.querySelector('.hx-menu-count');
      if (!count) return;
      var n = 0;
      if (ws === 'tasks') n = (state.tasks || []).filter(function (t) {
        return t && t.status && !(/done|success|failed|cancelled|canceled|completed/.test(String(t.status)));
      }).length;
      else if (ws === 'content') n = (state.drafts || []).length;
      else if (ws === 'collect') n = ((ctx.status && ctx.status.topics) || []).length;
      count.textContent = n > 0 ? String(n) : '';
      count.style.display = n > 0 ? '' : 'none';
    });

    /* 额度卡：真实账单节点优先，其次 billing 接口缓存。 */
    var bal = $('nav-token-bal');
    var tier = $('nav-tier-badge');
    var billing = (state.data && state.data.billing) || {};
    var numEl = $('hxQuotaNum'), tierEl = $('hxQuotaTier'), barEl = $('hxQuotaBar');
    var left = billing.credits_left != null ? billing.credits_left : railAmount(bal ? bal.textContent : null);
    var used = billing.credits_used != null ? billing.credits_used : null;
    if (numEl) numEl.textContent = left != null && left !== '' ? String(left) : '—';
    if (tierEl) tierEl.textContent = tier ? tier.textContent : (billing.tier_display || '套餐有效');
    if (barEl) {
      var pct = 62;
      if (left != null && used != null && Number(left) + Number(used) > 0) {
        pct = Math.round(100 * Number(left) / (Number(left) + Number(used)));
        pct = Math.max(4, Math.min(100, pct));
      }
      barEl.style.width = pct + '%';
    }

    /* 账号行 */
    var nameEl = $('hxProfileName'), subEl = $('hxProfileSub'), avatarEl = $('hxProfileAvatar');
    var realName = ($('profile-user-display-name') || {}).textContent ||
      ($('side-user-title') || {}).textContent || ($('top-auth-text') || {}).textContent || '个人中心';
    realName = String(realName).trim() || '个人中心';
    if (nameEl) nameEl.textContent = HX.trim(realName, 12);
    if (subEl) subEl.textContent = '已登录';
    if (avatarEl) {
      var realAvatar = $('top-auth-avatar-img') || $('profile-user-avatar-img');
      if (realAvatar && realAvatar.src) {
        avatarEl.innerHTML = '<img src="' + HX.esc(realAvatar.src) + '" alt="">';
      } else {
        avatarEl.textContent = realName.charAt(0) || '曹';
      }
    }

    /* 版本号 */
    var sub = DOC.querySelector('.hx-brand-sub');
    var ver = readVersion();
    if (sub && ver) sub.textContent = '全媒体创作工作台 · ' + ver;

    syncRailToggle();
  }

  HX._registerRailChrome(function (root, ctx) {
    try {
      buildChrome(root);
      refreshChrome(root, ctx);
    } catch (e) { console.warn('[HX rail] chrome 渲染失败:', e); }
  });

  /* 纯高亮同步：core 路由在渲染中栏前与 rAF 复核时调用，只切激活类，不碰计数/账单。 */
  HX._registerRailActive(function (c) {
    var root = $('hxRail');
    var st = (c && c.state) ? c.state : HX._ctx().state;
    if (root) syncMenuActive(root, st);
  });

  /* 状态变化后刷新 chrome（计数 / 额度 / 激活态）。 */
  HX.on('state', function (c) {
    var root = $('hxRail');
    if (root) refreshChrome(root, (c && c.state) ? c : HX._ctx());
  });
  HX.on('drafts', function () {
    var root = $('hxRail');
    if (root) refreshChrome(root, HX._ctx());
  });
})();
