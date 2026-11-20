/**
 * 一幕·YIMU 模型默认「单一真源」前端模块 (R5, v15.9.9)
 * SPDX-License-Identifier: BUSL-1.1
 *
 * 【背景】v15.9.8 及以前，模型默认的写路径散在三处（setImageModel /
 * onStudioModelChange / aivCfgSave），读路径散在 8 个影音工坊下拉 + 控制中心 +
 * 个人中心，三层存储（服务端 capability_defaults、localStorage 主键、legacy 键）
 * 互相打架——「在 A 处改了、B 处读不到、真正生成又用第三处」正是审查确认的
 * 历史事故（index.html 11077 行注释自认）。
 *
 * 【本模块的定位】
 *  - 唯一真源 = 服务端（GET /api/models/provider/defaults 读，
 *    POST /api/models/provider/set_default 写，与真正发请求时同一解析逻辑）。
 *  - localStorage 三键（yimu_image_model / yimu_studio_video_model / 两个 legacy
 *    生图键）收为「缓存位」：首屏先画缓存值避免下拉闪空白，refresh() 拉到
 *    服务端值后**以服务端为准覆盖**缓存位。
 *  - 统一写路径 apply()：写缓存位 → 同 scope 下拉联动 → POST set_default →
 *    成功后 refresh() 并广播 window 事件 'yimu-model-defaults-changed'。
 *    页面监听该事件后统一重画（下拉值 / 只读回显 / 规则提示），不再各自复制
 *    DOM 同步循环。
 *
 * 【设计边界】Agent 会话级选择（copilot-model-select / copilot-model-quick，
 * 键 yimu_copilot_provider / yimu_copilot_model）是「本次会话临时选择」，
 * 语义上不改变全站默认，**不**纳入服务端真源（见 index.html 内对应注释）。
 */
(function () {
  'use strict';

  var EVENT = 'yimu-model-defaults-changed';

  /* scope → localStorage 缓存位。
     why 只有 image/video 两条：text 线从未在 localStorage 里存过默认
     （对话模型走会话级选择或控制中心），没有需要兼容的旧键。 */
  var CACHE_KEYS = {
    image: 'yimu_image_model',
    video: 'yimu_studio_video_model'
  };

  /* 生图旧键：v15.9.4 之前模型散在两个键里（历史事故源头）。写缓存时仍双写
     一个版本——仓库里个别未改造的读取点/旧版本页面仍可能读旧键，双写可避免
     它们读到陈旧值造成「改了没生效」的观感。一个版本后再评估清理。 */
  var IMAGE_LEGACY_KEYS = ['yimu_studio_image_model', 'yimu_copilot_image_model'];

  /* 免 Key 保底引擎：不属于任何一家通道，服务端 capability_defaults 里
     没有它的位置——它的权威落点是 settings.image.model（saveImageCfg 写入）。
     why 单独列出：refresh() 拿到服务端空结果时会把缓存位抹成「自动」，
     若不豁免这类引擎，用户刚在设置里选好 flux-schnell、重开弹窗就回落成
     「自动（当前没有可用模型）」，而真正生成用的又是 flux-schnell。 */
  var FREE_ENGINES = { 'flux-schnell': 1 };

  var _defaults = null;   /* {text,image,video} 服务端真源（内存缓存） */
  var _refreshing = null; /* in-flight 去重：并发 refresh 共享同一个 promise */

  function lsGet(k) {
    try { return localStorage.getItem(k); } catch (e) { return null; } /* 隐私模式兜底 */
  }
  function lsSet(k, v) {
    try { localStorage.setItem(k, v); } catch (e) { /* 同上 */ }
  }

  /* ---------- 缓存位（读：首屏先画；写：仅作为最近已知值的加速位） ---------- */

  function readCache(scope) {
    var k = CACHE_KEYS[scope];
    if (!k) return '';
    var v = lsGet(k);
    return (v === null || v === undefined || v === '__default__') ? '' : String(v);
  }

  /* why 单独成函数并标注「缓存位写」：验收 grep 需要能区分
     「写 localStorage 的模型默认真写路径」与「缓存位写」——本函数是唯一豁免点。 */
  function writeCache(scope, val) {
    var v = (val && val !== '__default__') ? String(val) : '';
    var k = CACHE_KEYS[scope];
    if (!k) return;
    lsSet(k, v);
    if (scope === 'image') {
      for (var i = 0; i < IMAGE_LEGACY_KEYS.length; i++) {
        /* yimu_copilot_image_model 历史上用 '__default__' 表示空串语义，保持一致 */
        lsSet(IMAGE_LEGACY_KEYS[i], v || '__default__');
      }
    }
  }

  /* ---------- 服务端真源读 ---------- */

  function request(path, opts) {
    /* 优先复用页面 api()（统一超时/CSRF/错误语义）；本模块加载早于内联主脚本，
       运行期调用时 api() 已就绪，这里做 typeof 守卫只是兜底。 */
    if (typeof window.api === 'function') return window.api(path, opts);
    return fetch(path, opts).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  /* 拉取并缓存服务端默认；成功后覆盖缓存位并广播。
     失败时静默保留现有缓存（离线/未登录兜底：缓存值仍是上一次的真源快照）。 */
  function refresh() {
    if (_refreshing) return _refreshing;
    _refreshing = request('/api/models/provider/defaults', { method: 'GET' })
      .then(function (d) {
        _refreshing = null;
        _defaults = {
          text: (d && d.text) || {},
          image: (d && d.image) || {},
          video: (d && d.video) || {}
        };
        /* 以服务端值为准覆盖缓存位（先画缓存 → 异步以服务端覆盖）。
           why 显式默认写 model_tag（与下拉 option value 同格式「通道/模型」），
           自动（source 非 explicit）写空串——空串语义 = 跟随系统默认，
           保证「控制中心把默认改回自动」不会被旧缓存顶住（历史打架根因之一）。
           免 Key 保底引擎不依赖本缓存位：它由后端 settings.image.model
           （saveImageCfg 已写入）与 imagegen 兜底链承接，服务端三条能力线里
           查不到它；此时若照写空串，用户刚选的 flux-schnell 会被抹成「自动」，
           但真正生成仍用 flux-schnell —— 界面与事实背离。故保留该缓存值。 */
        var imgTag = tagOf('image');
        if (imgTag || !FREE_ENGINES[readCache('image')]) writeCache('image', imgTag);
        writeCache('video', tagOf('video'));
        try {
          window.dispatchEvent(new CustomEvent(EVENT, {
            detail: { defaults: _defaults, source: 'server' }
          }));
        } catch (e) { /* 老环境无 CustomEvent 时跳过广播 */ }
        return _defaults;
      })
      .catch(function (e) {
        _refreshing = null;
        if (window.console && console.warn) console.warn('[yimu-model-defaults] 拉取默认失败(保留缓存):', e && e.message);
        return null;
      });
    return _refreshing;
  }

  /* ---------- 读 ---------- */

  function get(scope) {
    return (_defaults && _defaults[scope]) || null;
  }

  /* 当前生效默认的「通道/模型」tag；未拉到或自动选择返回 ''（= 跟随系统默认）。 */
  function tagOf(scope) {
    var d = get(scope);
    if (!d) return '';
    return String(d.model_tag || d.model || '');
  }

  /* ---------- DOM 联动画值 ---------- */

  /* 把值画到所有同 scope 下拉（替代原先 setImageModel / onStudioModelChange /
     aivCfgSave 里三段互相复制的 STUDIO_*_SELECT_IDS.forEach 同步循环）。
     匹配规则与页面 pick() 一致：先精确，再按「/」后缀兜底（值可能带/不带通道前缀）。 */
  function paint(scope, val, excludeEl) {
    var els = document.querySelectorAll('[data-model-scope="' + scope + '"]');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (el === excludeEl) continue;
      if (el.value === val) continue;
      el.value = val;
      if (el.value !== val && val) {
        var plain = String(val).split('/').pop();
        var opts = el.options || [];
        var hit = null;
        for (var j = 0; j < opts.length; j++) {
          if (opts[j].value && opts[j].value.split('/').pop() === plain) { hit = opts[j].value; break; }
        }
        if (hit) el.value = hit;
      }
    }
  }

  /* ---------- 统一写路径 ---------- */

  /* apply(scope, value):
     1) 写缓存位（缓存位写，见 writeCache 注释；含 legacy 双写一个版本）；
     2) 同 scope 下拉立即联动（本地先一致，避免「改了这处、那处还是旧值」）；
     3) POST set_default 写服务端真源（'' = 清除显式默认改回自动）；
     4) 成功 → refresh()（以服务端权威值再覆盖一次并广播）；
        失败 → 保留本地联动并如实 toast。
        why 失败不回滚下拉：普通用户没有 set_default 权限(guard_admin)，
        但其选择仍会作为请求体里的 model 参数随任务下发（逐请求覆盖语义），
        回滚会把「本次任务用我选的模型」也一并丢掉——那是 v15.9.8 既有能力。
        toast 必须说明「全局默认未生效」，不许假成功。 */
  function apply(scope, value, opts) {
    var val = (value && value !== '__default__') ? String(value).trim() : '';
    writeCache(scope, val);
    paint(scope, val, opts && opts.sourceEl);

    var body;
    if (!val) {
      body = { provider_id: '', scope: scope };
    } else {
      /* 值是「通道/模型」形式；模型 ID 自身也可能带斜杠，只切第一个（与页面约定一致） */
      var i = val.indexOf('/');
      body = (i > 0)
        ? { provider_id: val.slice(0, i), scope: scope, model: val.slice(i + 1) }
        : { provider_id: '', scope: scope, model: val };
      /* 无通道前缀时无法定位通道：交给服务端按当前活动通道解析该 model */
      if (i <= 0) delete body.provider_id;
    }

    return request('/api/models/provider/set_default', {
      method: 'POST',
      body: JSON.stringify(body)
    }).then(function (res) {
      return refresh().then(function () { return res; });
    }).catch(function (e) {
      var msg = (e && e.message) || '未知错误';
      if (window.toast) toast('⚠️ 模型已用于本次生成，但全局默认未生效（' + msg + '）。需管理员在控制中心设置全局默认。', 4000);
      else if (window.console && console.warn) console.warn('[yimu-model-defaults] set_default 失败:', msg);
      return null;
    });
  }

  /* ---------- 绑定 ---------- */

  /* bind(el)：给带 data-model-scope 的 select 挂 change → apply()。
     data-model-mode="save" 的控件（个人中心配图设置、AI 视频配置弹窗）是
     「保存按钮流」：change 不立即写服务端（用户可能改了又取消），
     由各自的保存函数显式调用 apply()——这里只标记已管理，防止误绑。 */
  function bind(el) {
    if (!el || el.dataset.modelScopeBound) return;
    el.dataset.modelScopeBound = '1';
    var scope = el.getAttribute('data-model-scope');
    if (!scope) return;
    if ((el.getAttribute('data-model-mode') || '') === 'save') return;
    el.addEventListener('change', function () {
      apply(scope, el.value, { sourceEl: el });
    });
  }

  /* bindAll(root)：自动绑定 root（默认 document）下所有带 data-model-scope 的下拉。
     动态填充下拉后（initStudioModelSelects）需再调一次，新渲染的元素也会被绑上。 */
  function bindAll(root) {
    var r = root || document;
    if (!r || !r.querySelectorAll) return;
    var els = r.querySelectorAll('[data-model-scope]');
    for (var i = 0; i < els.length; i++) bind(els[i]);
  }

  /* paintAll()：把服务端真源画到所有同 scope 下拉。
     why 单独暴露：首屏由页面 init 调用一次（下拉此时已填充 option），
     之后各下拉 change 由 bind()/apply() 自行维护；页面重渲染下拉
     （initStudioModelSelects）后再调一次即可回显最新服务端值。
     why 服务端为空时回落缓存位：免 Key 保底引擎（flux-schnell）不在服务端
     能力线里，只存在于 settings.image.model 与缓存位；若只画服务端值，
     重开设置弹窗就会显示「自动」而实际生成用 flux-schnell。
     回落是安全的：非免 Key 值的缓存位已由 refresh() 按服务端结果清空。 */
  function paintAll() {
    if (!_defaults) return;
    paint('image', tagOf('image') || readCache('image'));
    paint('video', tagOf('video') || readCache('video'));
  }

  /* init()：首屏入口 = 绑定全部下拉 + 拉服务端真源 + 回画。
     返回 promise，页面可 await 或忽略（失败时静默保留缓存位，不阻塞首屏）。 */
  function init() {
    bindAll(document);
    return refresh().then(function (d) {
      paintAll();
      return d;
    });
  }

  window.YIMU_MODEL_DEFAULTS = {
    EVENT: EVENT,
    refresh: refresh,
    get: get,
    tag: tagOf,
    apply: apply,
    bind: bind,
    bindAll: bindAll,
    paintAll: paintAll,
    init: init,
    readCache: readCache,
    writeCache: writeCache /* 供页面保存流复用（写缓存位 + legacy 双写），仅此一处豁免 */
  };
})();
