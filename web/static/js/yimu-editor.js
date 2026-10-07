/*!
 * YimuEditor  v1.0.0
 * 电商富文本编辑器 —— 零依赖、可嵌入、可开源
 *
 * MIT License (c) 2026
 * 特性：图文混排 / 图片视频上传 / 表格 / 源码模式 / 草稿 / 明暗主题 / 全屏
 * 引入即用：<script src="yimu-editor.js"></script>
 * 初始化：new YimuEditor('#editor', { uploadUrl: '/api/upload' })
 */
(function (global) {
  "use strict";

  var VERSION = "1.0.1";

  /* ============================================================
     全局样式注入（幂等）
     ============================================================ */
  var STYLE_ID = "rte-style-v1";
  var CSS =
    ":root{--font-ui:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei','Helvetica Neue',Arial,sans-serif;--font-serif:Georgia,'Times New Roman','Songti SC',SimSun,serif;--font-mono:Consolas,Monaco,'Courier New',monospace}" +
    ".rte-app{--bg:#f4f3f0;--surface:#ffffff;--surface-2:#f7f6f3;--surface-3:#ebeae6;--border:#dfded9;--border-strong:#c9c7c0;--text:#23221f;--text-2:#6b6a64;--text-3:#9b9a93;--accent:#0f766e;--accent-soft:#e5f3f1;--accent-contrast:#ffffff;--danger:#b3382c;--danger-soft:#fbeae7;--shadow-1:0 1px 2px rgba(20,20,16,.06),0 4px 16px rgba(20,20,16,.08);--shadow-2:0 8px 30px rgba(20,20,16,.14);--tool-btn:34px;color-scheme:light}" +
    ".rte-app[data-theme='dark']{--bg:#161618;--surface:#1e1e21;--surface-2:#232327;--surface-3:#2a2a2f;--border:#333338;--border-strong:#45454c;--text:#e9e7e2;--text-2:#a6a49c;--text-3:#75736c;--accent:#2dd4bf;--accent-soft:#123b37;--accent-contrast:#05201d;--danger:#e0685a;--danger-soft:#3a201d;--shadow-1:0 1px 2px rgba(0,0,0,.3),0 4px 16px rgba(0,0,0,.35);--shadow-2:0 8px 30px rgba(0,0,0,.5);color-scheme:dark}" +
    ".rte-app{box-sizing:border-box;display:flex;flex-direction:column;min-width:760px;background:var(--bg);color:var(--text);font-family:var(--font-ui);-webkit-font-smoothing:antialiased;transition:background .2s,color .2s;border:1px solid var(--border);border-radius:10px;overflow:hidden;position:relative}" +
    ".rte-app *,.rte-app *:before,.rte-app *:after{box-sizing:border-box;margin:0;padding:0}" +
    ".rte-app .rte-header{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:0 14px;height:48px;background:var(--surface);border-bottom:1px solid var(--border);flex:none}" +
    ".rte-app .rte-brand{display:flex;align-items:center;gap:8px;min-width:0}" +
    ".rte-app .rte-brand .logo{width:26px;height:26px;border-radius:7px;background:var(--accent);color:var(--accent-contrast);display:flex;align-items:center;justify-content:center;flex:none}" +
    ".rte-app .rte-brand .logo svg{width:15px;height:15px}" +
    ".rte-app .rte-brand .title{font-size:14px;font-weight:600;letter-spacing:.2px;white-space:nowrap}" +
    ".rte-app .rte-brand .tag{font-size:11px;color:var(--text-2);border:1px solid var(--border);padding:2px 7px;border-radius:20px;background:var(--surface-2);white-space:nowrap}" +
    ".rte-app .rte-header-actions{display:flex;align-items:center;gap:4px;flex:none}" +
    ".rte-app .rte-draft-state{display:flex;align-items:center;gap:5px;font-size:11.5px;color:var(--text-2);margin-right:6px;padding:3px 9px;border-radius:20px;background:var(--surface-2);border:1px solid var(--border);white-space:nowrap}" +
    ".rte-app .rte-draft-state .dot{width:6px;height:6px;border-radius:50%;background:var(--text-3)}" +
    ".rte-app .rte-draft-state.saved .dot{background:#2f9e63}" +
    ".rte-app .tb-btn{width:var(--tool-btn);height:var(--tool-btn);display:inline-flex;align-items:center;justify-content:center;border:1px solid transparent;border-radius:6px;background:transparent;color:var(--text-2);cursor:pointer;transition:background .12s,color .12s;flex:none;font-family:var(--font-ui)}" +
    ".rte-app .tb-btn svg{width:16px;height:16px;pointer-events:none}" +
    ".rte-app .tb-btn:hover{background:var(--surface-3);color:var(--text)}" +
    ".rte-app .tb-btn.active{background:var(--accent-soft);color:var(--accent)}" +
    ".rte-app .tb-btn:disabled{opacity:.35;cursor:not-allowed}" +
    ".rte-app .tb-btn.has-caret{width:auto;padding:0 8px;gap:4px}" +
    ".rte-app .tb-btn.has-caret .lbl{font-size:12.5px;color:var(--text);max-width:86px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}" +
    ".rte-app .tb-btn.has-caret .caret{width:11px;height:11px}" +
    ".rte-app .tb-btn.primary{background:var(--accent);color:var(--accent-contrast)}" +
    ".rte-app .tb-btn.primary:hover{background:var(--accent);opacity:.9}" +
    ".rte-app .tb-sep{width:1px;height:20px;background:var(--border);margin:0 4px;flex:none}" +
    ".rte-app .rte-toolbar{background:var(--surface);border-bottom:1px solid var(--border);flex:none;box-shadow:var(--shadow-1);position:relative;z-index:20}" +
    ".rte-app .rte-tb-row{display:flex;align-items:center;gap:4px;padding:5px 10px;flex-wrap:wrap}" +
    ".rte-app .rte-tb-row + .rte-tb-row{border-top:1px solid var(--border);padding-top:6px}" +
    ".rte-app .tb-group{display:flex;align-items:center;gap:3px;position:relative}" +
    ".rte-app .rte-body{flex:1;display:flex;flex-direction:column;min-height:0;position:relative}" +
    ".rte-app .rte-editor-scroll{flex:1;overflow:auto;padding:22px}" +
    ".rte-app .rte-editor{max-width:860px;margin:0 auto;min-height:420px;background:var(--surface);border:1px solid var(--border);border-radius:10px;box-shadow:var(--shadow-1);padding:46px 56px 64px;outline:none;font-size:16px;line-height:1.75;color:var(--text);transition:border-color .15s;text-align:justify;position:relative}" +
    ".rte-app .rte-editor:focus{border-color:var(--accent)}" +
    ".rte-app .rte-editor:empty::before{content:attr(data-placeholder);color:var(--text-3);pointer-events:none;position:absolute;top:46px;left:56px;right:56px}" +
    ".rte-app .rte-editor::after{content:'';position:absolute;top:30px;left:56px;right:56px;height:1px;background:repeating-linear-gradient(90deg,var(--border) 0 26px,transparent 26px 34px);opacity:.7;pointer-events:none}" +
    ".rte-app .rte-editor h1,.rte-app .rte-editor h2,.rte-app .rte-editor h3,.rte-app .rte-editor h4{margin:1.4em 0 .6em;line-height:1.35;font-weight:700;text-align:left}" +
    ".rte-app .rte-editor h1{font-size:1.9em;margin-top:.6em}.rte-app .rte-editor h2{font-size:1.5em}.rte-app .rte-editor h3{font-size:1.24em}.rte-app .rte-editor h4{font-size:1.08em}" +
    ".rte-app .rte-editor p{margin:.6em 0}" +
    ".rte-app .rte-editor ul,.rte-app .rte-editor ol{margin:.6em 0 .6em 1.5em}.rte-app .rte-editor ul{list-style:disc}.rte-app .rte-editor ol{list-style:decimal}" +
    ".rte-app .rte-editor li{margin:.25em 0}" +
    ".rte-app .rte-editor ul.rte-task{list-style:none;margin-left:1.6em}" +
    ".rte-app .rte-editor ul.rte-task>li{position:relative}" +
    ".rte-app .rte-editor ul.rte-task>li::before{content:'';position:absolute;left:-1.45em;top:.42em;width:.95em;height:.95em;border:1.6px solid var(--text-2);border-radius:3px;background:var(--surface)}" +
    ".rte-app .rte-editor ul.rte-task[data-checked]>li::before{background:var(--accent);border-color:var(--accent)}" +
    ".rte-app .rte-editor ul.rte-task[data-checked]>li::after{content:'';position:absolute;left:-1.24em;top:.42em;width:.55em;height:.3em;border-left:2px solid #fff;border-bottom:2px solid #fff;transform:rotate(-45deg)}" +
    ".rte-app .rte-editor blockquote{margin:1em 0;padding:.4em 0 .4em 1.1em;border-left:3px solid var(--accent);color:var(--text-2);background:var(--surface-2);border-radius:0 6px 6px 0}" +
    ".rte-app .rte-editor pre{background:var(--surface-3);border:1px solid var(--border);border-radius:8px;padding:14px 16px;overflow-x:auto;font-family:var(--font-mono);font-size:13.5px;line-height:1.6;text-align:left}" +
    ".rte-app .rte-editor code{font-family:var(--font-mono);font-size:.92em;background:var(--surface-3);padding:1px 5px;border-radius:4px}.rte-app .rte-editor pre code{background:transparent;padding:0}" +
    ".rte-app .rte-editor a{color:var(--accent);text-decoration:underline}" +
    ".rte-app .rte-editor hr{border:none;border-top:1px solid var(--border-strong);margin:1.6em 0}" +
    ".rte-app .rte-editor img{max-width:100%;height:auto;border-radius:6px;vertical-align:middle}" +
    ".rte-app .rte-editor video{max-width:100%;border-radius:6px;background:#000}" +
    ".rte-app .rte-editor .rte-embed-video{position:relative;width:100%;padding-top:56.25%;border-radius:6px;overflow:hidden;background:#000}" +
    ".rte-app .rte-editor .rte-embed-video iframe{position:absolute;inset:0;width:100%;height:100%;border:0}" +
    ".rte-app .rte-editor table{border-collapse:collapse;margin:1em auto;min-width:60%;max-width:100%}" +
    ".rte-app .rte-editor table td,.rte-app .rte-editor table th{border:1px solid var(--border-strong);padding:8px 12px;min-width:60px;vertical-align:top;text-align:left}" +
    ".rte-app .rte-editor table th{background:var(--surface-2);font-weight:600}" +
    ".rte-app .rte-editor img.rte-selected,.rte-app .rte-editor video.rte-selected{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}" +
    ".rte-app .rte-source{display:none;flex:1;width:100%;height:100%;border:none;resize:none;background:var(--surface-2);color:var(--text);font-family:var(--font-mono);font-size:13.5px;line-height:1.6;padding:20px 24px;outline:none;tab-size:2}" +
    ".rte-app.source-mode .rte-editor-scroll{display:none}.rte-app.source-mode .rte-source{display:block}" +
    ".rte-app .rte-statusbar{display:flex;align-items:center;gap:16px;padding:0 14px;height:28px;background:var(--surface);border-top:1px solid var(--border);font-size:11.5px;color:var(--text-2);flex:none}" +
    ".rte-app .rte-statusbar .right{margin-left:auto;display:flex;gap:12px;align-items:center}" +
    ".rte-app .rte-pop{position:absolute;background:var(--surface);border:1px solid var(--border);border-radius:10px;box-shadow:var(--shadow-2);padding:10px;z-index:100;display:none;min-width:200px;animation:rte-pop-in .12s ease-out}" +
    "@keyframes rte-pop-in{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:none}}" +
    ".rte-app .rte-pop.open{display:block}" +
    ".rte-app .rte-menu{display:flex;flex-direction:column;gap:2px}" +
    ".rte-app .rte-menu-item{display:flex;align-items:center;gap:10px;padding:8px 12px;border-radius:6px;font-size:13px;color:var(--text);cursor:pointer;border:none;background:none;text-align:left;width:100%;font-family:var(--font-ui)}" +
    ".rte-app .rte-menu-item:hover{background:var(--surface-3)}" +
    ".rte-app .rte-menu-item .tick{width:14px;height:14px;margin-left:auto;color:var(--accent);opacity:0;display:inline-flex}" +
    ".rte-app .rte-menu-item.active .tick{opacity:1}" +
    ".rte-app .rte-menu-head{font-size:11px;color:var(--text-3);padding:4px 12px 6px;letter-spacing:.5px}" +
    ".rte-app .rte-swatches{display:grid;grid-template-columns:repeat(8,22px);gap:6px}" +
    ".rte-app .rte-swatch{width:22px;height:22px;border-radius:5px;border:1px solid rgba(0,0,0,.12);cursor:pointer;transition:transform .1s;padding:0}" +
    ".rte-app .rte-swatch:hover{transform:scale(1.12)}" +
    ".rte-app .rte-swatch.none{background:repeating-linear-gradient(45deg,#fff 0 4px,#e5e5e5 4px 8px)}" +
    ".rte-app .rte-pop-foot{display:flex;align-items:center;gap:8px;margin-top:10px;padding-top:10px;border-top:1px solid var(--border)}" +
    ".rte-app .rte-pop-foot label{font-size:12px;color:var(--text-2)}" +
    ".rte-app .rte-pop-foot input[type=color]{width:30px;height:24px;border:1px solid var(--border);border-radius:5px;background:none;cursor:pointer;padding:0}" +
    ".rte-app .rte-form{display:flex;flex-direction:column;gap:10px;width:320px}" +
    ".rte-app .rte-form h4{font-size:14px;font-weight:600}" +
    ".rte-app .rte-field{display:flex;flex-direction:column;gap:5px}" +
    ".rte-app .rte-field label{font-size:12px;color:var(--text-2)}" +
    ".rte-app .rte-field input[type=text],.rte-app .rte-field input[type=number],.rte-app .rte-field input[type=url]{height:34px;border:1px solid var(--border-strong);border-radius:6px;padding:0 10px;font-size:13px;color:var(--text);background:var(--surface-2);outline:none;width:100%;font-family:var(--font-ui)}" +
    ".rte-app .rte-field input:focus{border-color:var(--accent)}" +
    ".rte-app .rte-field .check-row{display:flex;align-items:center;gap:7px;font-size:13px;color:var(--text)}" +
    ".rte-app .rte-form-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:2px}" +
    ".rte-app .btn{height:32px;padding:0 14px;border-radius:6px;font-size:13px;border:1px solid var(--border-strong);background:var(--surface-2);color:var(--text);cursor:pointer;transition:background .12s;font-family:var(--font-ui)}" +
    ".rte-app .btn:hover{background:var(--surface-3)}" +
    ".rte-app .btn.primary{background:var(--accent);color:var(--accent-contrast);border-color:var(--accent)}" +
    ".rte-app .btn.primary:hover{opacity:.9}" +
    ".rte-app .btn.danger{background:var(--danger-soft);color:var(--danger);border-color:transparent}" +
    ".rte-app .rte-chars{display:grid;grid-template-columns:repeat(8,34px);gap:4px}" +
    ".rte-app .rte-char{width:34px;height:34px;border:1px solid var(--border);border-radius:6px;background:var(--surface-2);color:var(--text);font-size:15px;cursor:pointer;display:flex;align-items:center;justify-content:center}" +
    ".rte-app .rte-char:hover{background:var(--accent-soft);border-color:var(--accent)}" +
    ".rte-app .rte-tabs{display:flex;gap:4px;background:var(--surface-2);padding:3px;border-radius:8px;margin-bottom:10px}" +
    ".rte-app .rte-tab{flex:1;height:30px;border:none;border-radius:6px;background:transparent;font-size:12.5px;color:var(--text-2);cursor:pointer;font-family:var(--font-ui)}" +
    ".rte-app .rte-tab.active{background:var(--surface);color:var(--text);box-shadow:var(--shadow-1);font-weight:500}" +
    ".rte-app .rte-upload-zone{border:1.5px dashed var(--border-strong);border-radius:8px;padding:20px 14px;text-align:center;color:var(--text-2);font-size:13px;cursor:pointer;transition:border-color .15s,background .15s}" +
    ".rte-app .rte-upload-zone:hover{border-color:var(--accent);background:var(--accent-soft)}" +
    ".rte-app .rte-upload-zone .up-icon{width:30px;height:30px;margin:0 auto 8px;color:var(--text-3)}" +
    ".rte-app .rte-upload-zone b{color:var(--accent)}" +
    ".rte-app .rte-upload-hint{font-size:11px;color:var(--text-3);margin-top:8px;line-height:1.6}" +
    ".rte-app .rte-upload-preview{margin-top:10px;display:flex;align-items:center;gap:10px}" +
    ".rte-app .rte-upload-preview img{width:56px;height:56px;object-fit:cover;border-radius:6px;border:1px solid var(--border)}" +
    ".rte-app .rte-upload-preview .name{font-size:12.5px;color:var(--text);word-break:break-all;line-height:1.4}" +
    ".rte-app .rte-upload-preview .meta{font-size:11px;color:var(--text-3)}" +
    ".rte-app .rte-floatbar{position:absolute;background:var(--surface);border:1px solid var(--border);border-radius:8px;box-shadow:var(--shadow-2);padding:4px;display:flex;align-items:center;gap:2px;z-index:90;font-size:12px}" +
    ".rte-app .rte-floatbar .tb-btn{width:28px;height:28px}.rte-app .rte-floatbar .tb-btn svg{width:14px;height:14px}" +
    ".rte-app .rte-floatbar .sep{width:1px;height:16px;background:var(--border);margin:0 3px}" +
    ".rte-app .rte-floatbar input[type=number]{width:52px;height:26px;border:1px solid var(--border-strong);border-radius:5px;background:var(--surface-2);color:var(--text);font-size:12px;padding:0 5px;outline:none;margin-left:2px;font-family:var(--font-ui)}" +
    ".rte-app .rte-floatbar .lbl{font-size:11px;color:var(--text-2);margin-left:2px}" +
    ".rte-app .rte-toast-wrap{position:fixed;top:16px;right:16px;z-index:200;display:flex;flex-direction:column;gap:8px;pointer-events:none}" +
    ".rte-app .rte-toast{background:var(--surface);color:var(--text);border:1px solid var(--border);border-left:3px solid var(--accent);border-radius:8px;box-shadow:var(--shadow-2);padding:10px 15px;font-size:13px;animation:rte-toast-in .2s ease-out;max-width:340px}" +
    ".rte-app .rte-toast.error{border-left-color:var(--danger)}.rte-app .rte-toast.warn{border-left-color:#d1912c}" +
    "@keyframes rte-toast-in{from{opacity:0;transform:translateX(20px)}to{opacity:1;transform:none}}" +
    ".rte-app .rte-modal-mask{position:fixed;inset:0;background:rgba(10,10,10,.45);display:none;align-items:center;justify-content:center;z-index:300}" +
    ".rte-app .rte-modal-mask.open{display:flex}" +
    ".rte-app .rte-modal{background:var(--surface);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow-2);width:560px;max-width:92vw;max-height:82vh;overflow:auto;padding:20px 22px}" +
    ".rte-app .rte-modal h3{font-size:16px;margin-bottom:4px}" +
    ".rte-app .rte-modal .sub{font-size:12.5px;color:var(--text-2);margin-bottom:14px}" +
    ".rte-app .rte-modal h4{font-size:13px;margin:14px 0 8px;color:var(--text-2);font-weight:600}" +
    ".rte-app .rte-kbd-grid{display:grid;grid-template-columns:1fr 1fr;gap:4px 18px}" +
    ".rte-app .rte-kbd-row{display:flex;align-items:center;justify-content:space-between;font-size:12.5px;padding:5px 0;border-bottom:1px dashed var(--border)}" +
    ".rte-app .rte-kbd-row .k{color:var(--text-2)}" +
    ".rte-app .rte-kbd{display:inline-block;border:1px solid var(--border-strong);border-bottom-width:2px;border-radius:5px;background:var(--surface-2);padding:1px 7px;font-size:11.5px;font-family:var(--font-mono);color:var(--text)}" +
    ".rte-app .rte-modal .close-x{position:sticky;top:0;float:right;width:28px;height:28px;border:none;border-radius:6px;background:var(--surface-2);color:var(--text-2);cursor:pointer}" +
    ".rte-app .rte-modal .close-x:hover{background:var(--surface-3);color:var(--text)}" +
    ".rte-app::-webkit-scrollbar{width:10px;height:10px}" +
    ".rte-app ::-webkit-scrollbar{width:10px;height:10px}" +
    ".rte-app ::-webkit-scrollbar-thumb{background:var(--border-strong);border-radius:6px;border:2px solid transparent;background-clip:content-box}" +
    ".rte-app ::-webkit-scrollbar-thumb:hover{background:var(--text-3);background-clip:content-box;border:2px solid transparent}" +
    ".rte-app ::-webkit-scrollbar-track{background:transparent}" +
    /* —— 工具栏吸顶（stickyToolbar，默认开启）—— */
    ".rte-app.rte-sticky{overflow:visible}" +
    ".rte-app.rte-sticky .rte-header{border-radius:10px 10px 0 0}" +
    ".rte-app.rte-sticky .rte-statusbar{border-radius:0 0 10px 10px}" +
    ".rte-app.rte-sticky .rte-toolbar{position:sticky;top:0;z-index:20}" +
    ".rte-app.rte-sticky .rte-toolbar.rte-stuck{box-shadow:var(--shadow-2)}" +
    "";

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var s = document.createElement("style");
    s.id = STYLE_ID;
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  /* ============================================================
     图标库（SVG Sprite，全局注入一次）
     ============================================================ */
  var SPRITE_ID = "rte-icons-v1";
  var ICONS = {
    undo: '<path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"/>',
    redo: '<path d="M21 7v6h-6"/><path d="M3 17a9 9 0 0 1 9-9 9 9 0 0 1 6 2.3L21 13"/>',
    bold: '<path d="M6 4h8a4 4 0 0 1 4 4 4 4 0 0 1-4 4H6z"/><path d="M6 12h9a4 4 0 0 1 4 4 4 4 0 0 1-4 4H6z"/>',
    italic: '<line x1="19" y1="4" x2="10" y2="4"/><line x1="14" y1="20" x2="5" y2="20"/><line x1="15" y1="4" x2="9" y2="20"/>',
    underline: '<path d="M6 3v7a6 6 0 0 0 6 6 6 6 0 0 0 6-6V3"/><line x1="4" y1="21" x2="20" y2="21"/>',
    strike: '<path d="M16 4H9a3 3 0 0 0-2.83 4"/><path d="M14 12a4 4 0 0 1 0 8H6"/><line x1="4" y1="12" x2="20" y2="12"/>',
    "list-ul": '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
    "list-ol": '<line x1="10" y1="6" x2="21" y2="6"/><line x1="10" y1="12" x2="21" y2="12"/><line x1="10" y1="18" x2="21" y2="18"/><path d="M4 6h1v4"/><path d="M4 10h2"/><path d="M6 18H4c0-1 2-2 2-3s-1-1.5-2-1"/>',
    "list-task": '<polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
    quote: '<path d="M3 21c3 0 7-1 7-8V5c0-1.25-.756-2.017-2-2H4c-1.25 0-2 .75-2 1.972V11c0 1.25.75 2 2 2 1 0 1 0 1 1v1c0 1-1 2-2 2s-1 .008-1 1.031V20c0 1 0 1 1 1z"/><path d="M15 21c3 0 7-1 7-8V5c0-1.25-.757-2.017-2-2h-4c-1.25 0-2 .75-2 1.972V11c0 1.25.75 2 2 2h.75c0 2.25.25 4-2.75 4v3c0 1 0 1 1 1z"/>',
    code: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
    link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    unlink: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/><line x1="22" y1="2" x2="2" y2="22"/>',
    image: '<rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
    video: '<polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>',
    table: '<path d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v18m0 0h10a2 2 0 0 0 2-2V9M9 21H5a2 2 0 0 1-2-2V9m0 0h18"/>',
    hr: '<line x1="3" y1="12" x2="21" y2="12"/><polyline points="7 8 3 12 7 16"/><polyline points="17 8 21 12 17 16"/>',
    "align-left": '<line x1="17" y1="10" x2="3" y2="10"/><line x1="21" y1="6" x2="3" y2="6"/><line x1="21" y1="14" x2="3" y2="14"/><line x1="17" y1="18" x2="3" y2="18"/>',
    "align-center": '<line x1="18" y1="10" x2="6" y2="10"/><line x1="21" y1="6" x2="3" y2="6"/><line x1="21" y1="14" x2="3" y2="14"/><line x1="18" y1="18" x2="6" y2="18"/>',
    "align-right": '<line x1="21" y1="10" x2="7" y2="10"/><line x1="21" y1="6" x2="3" y2="6"/><line x1="21" y1="14" x2="3" y2="14"/><line x1="21" y1="18" x2="7" y2="18"/>',
    "align-justify": '<line x1="21" y1="10" x2="3" y2="10"/><line x1="21" y1="6" x2="3" y2="6"/><line x1="21" y1="14" x2="3" y2="14"/><line x1="21" y1="18" x2="3" y2="18"/>',
    indent: '<polyline points="3 8 7 12 3 16"/><line x1="21" y1="6" x2="11" y2="6"/><line x1="21" y1="12" x2="11" y2="12"/><line x1="21" y1="18" x2="11" y2="18"/>',
    outdent: '<polyline points="7 8 3 12 7 16"/><line x1="21" y1="6" x2="11" y2="6"/><line x1="21" y1="12" x2="11" y2="12"/><line x1="21" y1="18" x2="11" y2="18"/>',
    lineheight: '<polyline points="12 3 9 6 15 6"/><polyline points="12 21 9 18 15 18"/><line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="18" x2="20" y2="18"/>',
    clear: '<path d="M12 3 5 21"/><line x1="19" y1="9" x2="21" y2="9"/><line x1="18.5" y1="14" x2="20.5" y2="14"/><line x1="18" y1="19" x2="20" y2="19"/>',
    clipboard: '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/>',
    fullscreen: '<path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>',
    help: '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    copy: '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    sun: '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>',
    moon: '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
    trash: '<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    refresh: '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
    "chevron-down": '<polyline points="6 9 12 15 18 9"/>',
    check: '<polyline points="20 6 9 17 4 12"/>',
    x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    "col-left": '<rect x="3" y="3" width="8" height="18" rx="1"/><line x1="13" y1="6" x2="21" y2="6"/><line x1="13" y1="12" x2="21" y2="12"/><line x1="13" y1="18" x2="21" y2="18"/>',
    "col-right": '<rect x="13" y="3" width="8" height="18" rx="1"/><line x1="3" y1="6" x2="11" y2="6"/><line x1="3" y1="12" x2="11" y2="12"/><line x1="3" y1="18" x2="11" y2="18"/>',
    "row-top": '<rect x="3" y="3" width="18" height="8" rx="1"/><line x1="6" y1="15" x2="18" y2="15"/><line x1="6" y1="19" x2="18" y2="19"/>',
    "row-bottom": '<rect x="3" y="13" width="18" height="8" rx="1"/><line x1="6" y1="5" x2="18" y2="5"/><line x1="6" y1="9" x2="18" y2="9"/>'
  };
  function ic(name, size) {
    var s = size || 16;
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:' + s + 'px;height:' + s + 'px;pointer-events:none" aria-hidden="true">' + (ICONS[name] || "") + "</svg>";
  }
  function injectSprite() {
    if (document.getElementById(SPRITE_ID)) return;
    var wrap = document.createElement("div");
    wrap.id = SPRITE_ID;
    wrap.style.display = "none";
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    var defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    Object.keys(ICONS).forEach(function (k) {
      var sym = document.createElementNS("http://www.w3.org/2000/svg", "symbol");
      sym.setAttribute("id", "rtei-" + k);
      sym.setAttribute("viewBox", "0 0 24 24");
      sym.setAttribute("fill", "none");
      sym.setAttribute("stroke", "currentColor");
      sym.setAttribute("stroke-width", "2");
      sym.setAttribute("stroke-linecap", "round");
      sym.setAttribute("stroke-linejoin", "round");
      sym.innerHTML = ICONS[k];
      defs.appendChild(sym);
    });
    svg.appendChild(defs);
    wrap.appendChild(svg);
    document.body.insertBefore(wrap, document.body.firstChild);
  }

  /* ============================================================
     默认配置
     ============================================================ */
  var DEFAULTS = {
    uploadUrl: "",                 // 上传接口；留空则以 base64 内嵌
    uploadField: "file",           // 文件字段名
    uploadHeaders: {},             // 额外请求头
    uploadResultKey: "url",        // 响应取 URL 字段，字符串响应直接用
    maxImageSize: 10 * 1024 * 1024,
    maxVideoSize: 200 * 1024 * 1024,
    imageAccept: "image/*",
    videoAccept: "video/*",
    placeholder: "开始撰写内容…支持图文混排、图片与视频上传。",
    onChange: null,                // (html, instance) => {}
    autosave: true,
    restoreDraft: true,            // 是否在初始化时恢复本地草稿（独立于 autosave）
    draftKey: "rte-draft",
    theme: "light",                // 'light' | 'dark'
    toolbar: true,                 // true | false | ['undo','bold',...] 白名单
    stickyToolbar: true,           // 工具栏吸顶：长文滚动时固定在屏幕顶部
    header: true,                  // 是否显示顶栏
    statusbar: true,               // 是否显示状态栏
    initialHTML: ""                // 初始内容
  };

  /* ============================================================
     工具函数
     ============================================================ */
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  var BLOCK_TAGS = ["P", "H1", "H2", "H3", "H4", "H5", "H6", "LI", "BLOCKQUOTE", "PRE", "TD", "TH", "DIV"];
  function isBlock(el) { return !!(el && el.nodeType === 1 && BLOCK_TAGS.indexOf(el.tagName) >= 0); }

  /* ============================================================
     编辑器类
     ============================================================ */
  function YimuEditor(target, options) {
    if (!(this instanceof YimuEditor)) return new YimuEditor(target, options);
    this.opts = Object.assign({}, DEFAULTS, options || {});
    this.el = typeof target === "string" ? document.querySelector(target) : target;
    if (!this.el) throw new Error("YimuEditor: 找不到容器元素 " + target);

    injectStyle();
    injectSprite();

    this.buildDOM();
    this.applyLayoutOptions();
    this.buildMenus();
    this.bindEvents();
    this.applyTheme(this.opts.theme);
    this.initSticky();

    if (this.opts.initialHTML) this.editor.innerHTML = this.opts.initialHTML;
    if (this.opts.restoreDraft !== false) {
      try {
        var d = localStorage.getItem(this.opts.draftKey);
        if (d && d.trim()) { this.editor.innerHTML = d; this.setDraftState(true); }
      } catch (e) {}
    }
    this.afterChange(false);
    this.updateToolbar();
  }

  /* ---------- DOM 构建 ---------- */
  YimuEditor.prototype.buildDOM = function () {
    var t = this;
    var app = document.createElement("div");
    app.className = "rte-app";
    app.setAttribute("data-theme", "light");
    t.app = app;
    t.el.innerHTML = "";
    t.el.appendChild(app);

    var uploadHintImg = this.opts.uploadUrl
      ? "已接入服务器上传接口，上传后返回远程地址。"
      : "当前为 base64 内嵌（无上传接口）。配置 uploadUrl 后自动走服务器存储。";

    app.innerHTML =
      '<!-- 顶栏 -->' +
      '<div class="rte-header">' +
        '<div class="rte-brand">' +
          '<span class="logo">' + ic("edit", 15) + '</span>' +
          '<span class="title">一幕·YIMU Editor</span>' +
          '<span class="tag">富文本</span>' +
        '</div>' +
        '<div class="rte-header-actions">' +
          '<span class="rte-draft-state" data-rte="draft-state"><span class="dot"></span><span data-rte="draft-text">草稿未保存</span></span>' +
          '<button type="button" class="tb-btn" data-rte="btn-clear-draft" data-key="cleardraft" title="清除本地草稿">' + ic("trash") + '</button>' +
          '<button type="button" class="tb-btn" data-rte="btn-theme" data-key="theme" title="切换明暗主题"></button>' +
          '<button type="button" class="tb-btn" data-rte="btn-copy" data-key="copy" title="复制 HTML">' + ic("copy") + '</button>' +
          '<button type="button" class="tb-btn" data-rte="btn-export" data-key="export" title="导出 HTML 文件">' + ic("download") + '</button>' +
          '<button type="button" class="tb-btn" data-rte="btn-help" data-key="help" title="帮助与快捷键">' + ic("help") + '</button>' +
          '<button type="button" class="tb-btn" data-rte="btn-fullscreen" data-key="fullscreen" title="全屏">' + ic("fullscreen") + '</button>' +
        '</div>' +
      '</div>' +
      '<!-- 工具栏 行1 -->' +
      '<div class="rte-toolbar">' +
        '<div class="rte-tb-row">' +
          '<div class="tb-group">' +
            '<button type="button" class="tb-btn" data-rte="cmd-undo" data-key="undo" title="撤销 (Ctrl+Z)">' + ic("undo") + '</button>' +
            '<button type="button" class="tb-btn" data-rte="cmd-redo" data-key="redo" title="重做 (Ctrl+Y)">' + ic("redo") + '</button>' +
          '</div><span class="tb-sep"></span>' +
          '<div class="tb-group">' +
            '<button type="button" class="tb-btn has-caret" data-rte="btn-format" data-key="format" title="段落格式"><span class="lbl" data-rte="lbl-format">正文</span>' + ic("chevron-down", 11) + '</button>' +
            '<button type="button" class="tb-btn has-caret" data-rte="btn-font" data-key="font" title="字体"><span class="lbl" data-rte="lbl-font">默认字体</span>' + ic("chevron-down", 11) + '</button>' +
            '<button type="button" class="tb-btn has-caret" data-rte="btn-fontsize" data-key="fontsize" title="字号"><span class="lbl" data-rte="lbl-fontsize">16</span>' + ic("chevron-down", 11) + '</button>' +
          '</div><span class="tb-sep"></span>' +
          '<div class="tb-group">' +
            '<button type="button" class="tb-btn" data-rte="cmd-bold" data-key="bold" title="加粗 (Ctrl+B)">' + ic("bold") + '</button>' +
            '<button type="button" class="tb-btn" data-rte="cmd-italic" data-key="italic" title="斜体 (Ctrl+I)">' + ic("italic") + '</button>' +
            '<button type="button" class="tb-btn" data-rte="cmd-underline" data-key="underline" title="下划线 (Ctrl+U)">' + ic("underline") + '</button>' +
            '<button type="button" class="tb-btn" data-rte="cmd-strike" data-key="strike" title="删除线">' + ic("strike") + '</button>' +
            '<button type="button" class="tb-btn" data-rte="cmd-sup" data-key="sup" title="上标"><span style="font-size:13px;font-weight:600;line-height:1">x<sup>2</sup></span></button>' +
            '<button type="button" class="tb-btn" data-rte="cmd-sub" data-key="sub" title="下标"><span style="font-size:13px;font-weight:600;line-height:1">x<sub>2</sub></span></button>' +
          '</div><span class="tb-sep"></span>' +
          '<div class="tb-group">' +
            '<button type="button" class="tb-btn has-caret" data-rte="btn-color" data-key="color" title="文字颜色"><span style="display:flex;flex-direction:column;align-items:center;line-height:1"><span style="font-size:14px;font-weight:600">A</span><span data-rte="color-bar" style="width:16px;height:3px;border-radius:2px;background:#23221f;margin-top:1px"></span></span></button>' +
            '<button type="button" class="tb-btn has-caret" data-rte="btn-hilite" data-key="hilite" title="背景高亮"><span data-rte="hilite-swatch" style="width:20px;height:20px;border-radius:4px;background:#fff94a;border:1px solid rgba(0,0,0,.1);display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600">A</span></button>' +
          '</div><span class="tb-sep"></span>' +
          '<div class="tb-group">' +
            '<button type="button" class="tb-btn" data-rte="cmd-clear" data-key="clear" title="清除格式">' + ic("clear") + '</button>' +
          '</div>' +
        '</div>' +
        '<div class="rte-tb-row">' +
          '<div class="tb-group">' +
            '<button type="button" class="tb-btn" data-rte="cmd-align-left" data-key="align-left" title="左对齐">' + ic("align-left") + '</button>' +
            '<button type="button" class="tb-btn" data-rte="cmd-align-center" data-key="align-center" title="居中">' + ic("align-center") + '</button>' +
            '<button type="button" class="tb-btn" data-rte="cmd-align-right" data-key="align-right" title="右对齐">' + ic("align-right") + '</button>' +
            '<button type="button" class="tb-btn" data-rte="cmd-align-justify" data-key="align-justify" title="两端对齐">' + ic("align-justify") + '</button>' +
          '</div><span class="tb-sep"></span>' +
          '<div class="tb-group">' +
            '<button type="button" class="tb-btn" data-rte="cmd-indent" data-key="indent" title="增加缩进 (Tab)">' + ic("indent") + '</button>' +
            '<button type="button" class="tb-btn" data-rte="cmd-outdent" data-key="outdent" title="减少缩进 (Shift+Tab)">' + ic("outdent") + '</button>' +
            '<button type="button" class="tb-btn has-caret" data-rte="btn-lineheight" data-key="lineheight" title="行距">' + ic("lineheight", 15) + ic("chevron-down", 11) + '</button>' +
          '</div><span class="tb-sep"></span>' +
          '<div class="tb-group">' +
            '<button type="button" class="tb-btn" data-rte="cmd-list-ul" data-key="list-ul" title="无序列表 (Ctrl+Shift+8)">' + ic("list-ul") + '</button>' +
            '<button type="button" class="tb-btn" data-rte="cmd-list-ol" data-key="list-ol" title="有序列表 (Ctrl+Shift+7)">' + ic("list-ol") + '</button>' +
            '<button type="button" class="tb-btn" data-rte="cmd-list-task" data-key="list-task" title="任务清单">' + ic("list-task") + '</button>' +
          '</div><span class="tb-sep"></span>' +
          '<div class="tb-group">' +
            '<button type="button" class="tb-btn" data-rte="cmd-quote" data-key="quote" title="引用块">' + ic("quote") + '</button>' +
            '<button type="button" class="tb-btn" data-rte="cmd-code" data-key="code" title="代码块">' + ic("code") + '</button>' +
          '</div><span class="tb-sep"></span>' +
          '<div class="tb-group">' +
            '<button type="button" class="tb-btn" data-rte="cmd-link" data-key="link" title="插入/编辑链接 (Ctrl+K)">' + ic("link") + '</button>' +
          '</div><span class="tb-sep"></span>' +
          '<div class="tb-group">' +
            '<button type="button" class="tb-btn" data-rte="cmd-image" data-key="image" title="插入图片">' + ic("image") + '</button>' +
            '<button type="button" class="tb-btn" data-rte="cmd-video" data-key="video" title="插入视频">' + ic("video") + '</button>' +
            '<button type="button" class="tb-btn" data-rte="cmd-table" data-key="table" title="插入表格">' + ic("table") + '</button>' +
            '<button type="button" class="tb-btn" data-rte="cmd-hr" data-key="hr" title="水平分割线">' + ic("hr") + '</button>' +
            '<button type="button" class="tb-btn" data-rte="cmd-chars" data-key="chars" title="特殊字符"><span style="font-size:15px;font-weight:600;line-height:1">Ω</span></button>' +
          '</div><span class="tb-sep"></span>' +
          '<div class="tb-group">' +
            '<button type="button" class="tb-btn" data-rte="cmd-plain" data-key="plain" title="粘贴为纯文本">' + ic("clipboard") + '</button>' +
            '<button type="button" class="tb-btn" data-rte="cmd-source" data-key="source" title="HTML 源码视图"><span style="font-family:Consolas,monospace;font-size:12.5px;font-weight:700">&lt;/&gt;</span></button>' +
          '</div>' +
        '</div>' +
      '</div>' +
      '<!-- 编辑区 -->' +
      '<div class="rte-body">' +
        '<div class="rte-editor-scroll">' +
          '<div class="rte-editor" data-rte="editor" contenteditable="true" spellcheck="true" data-placeholder="' + esc(this.opts.placeholder) + '"></div>' +
        '</div>' +
        '<textarea class="rte-source" data-rte="source" spellcheck="false" placeholder="&lt;!-- HTML 源码模式 --&gt;"></textarea>' +
      '</div>' +
      '<!-- 状态栏 -->' +
      '<div class="rte-statusbar">' +
        '<span data-rte="stat-chars">0 字符</span>' +
        '<span data-rte="stat-cjk">0 汉字</span>' +
        '<span data-rte="stat-words">0 单词</span>' +
        '<span data-rte="stat-size">0 KB</span>' +
        '<div class="right"><span data-rte="stat-sel">未选中内容</span><span>Ctrl+H 查看帮助</span></div>' +
      '</div>' +
      '<!-- 弹层 -->' +
      '<div class="rte-pop" data-rte="pop-format"><div class="rte-menu" data-rte="menu-format"></div></div>' +
      '<div class="rte-pop" data-rte="pop-font"><div class="rte-menu" data-rte="menu-font"></div></div>' +
      '<div class="rte-pop" data-rte="pop-fontsize"><div class="rte-menu" data-rte="menu-fontsize"></div></div>' +
      '<div class="rte-pop" data-rte="pop-color"><div class="rte-swatches" data-rte="swatches-text"></div><div class="rte-pop-foot"><label>自定义</label><input type="color" data-rte="color-custom" value="#0f766e"><button type="button" class="btn" data-rte="color-default" style="margin-left:auto">恢复默认</button></div></div>' +
      '<div class="rte-pop" data-rte="pop-hilite"><div class="rte-swatches" data-rte="swatches-hilite"></div><div class="rte-pop-foot"><label>自定义</label><input type="color" data-rte="hilite-custom" value="#fff94a"><button type="button" class="btn" data-rte="hilite-none" style="margin-left:auto">清除高亮</button></div></div>' +
      '<div class="rte-pop" data-rte="pop-lineheight"><div class="rte-menu" data-rte="menu-lineheight"></div></div>' +
      '<div class="rte-pop" data-rte="pop-link">' +
        '<form class="rte-form" data-rte="form-link" autocomplete="off"><h4>插入链接</h4>' +
          '<div class="rte-field"><label>链接地址</label><input type="url" data-rte="link-url" placeholder="https://example.com/product"></div>' +
          '<div class="rte-field"><label>链接文字 <span data-rte="link-text-hint" style="color:var(--text-3)">（未选中文字时使用）</span></label><input type="text" data-rte="link-text" placeholder="点击这里查看"></div>' +
          '<div class="rte-field"><label class="check-row"><input type="checkbox" data-rte="link-target" checked> 在新窗口打开</label></div>' +
          '<div class="rte-form-actions"><button type="button" class="btn danger" data-rte="link-remove" style="margin-right:auto">移除链接</button><button type="button" class="btn" data-rte="link-cancel">取消</button><button type="submit" class="btn primary">确定</button></div>' +
        '</form>' +
      '</div>' +
      '<div class="rte-pop" data-rte="pop-image">' +
        '<form class="rte-form" data-rte="form-image" autocomplete="off"><h4>插入图片</h4>' +
          '<div class="rte-tabs"><button type="button" class="rte-tab active" data-tab="upload">上传图片</button><button type="button" class="rte-tab" data-tab="url">使用链接</button></div>' +
          '<div class="rte-field" data-pane="upload">' +
            '<div class="rte-upload-zone" data-rte="img-drop">' + ic("upload", 30) + '<div>点击选择图片或拖拽到此处</div><div class="rte-upload-hint">支持 JPG / PNG / GIF / WebP / SVG。' + uploadHintImg + '</div></div>' +
            '<div class="rte-upload-preview" data-rte="img-preview" style="display:none"><img data-rte="img-prev-thumb" alt=""><div><div class="name" data-rte="img-prev-name"></div><div class="meta" data-rte="img-prev-meta"></div></div></div>' +
            '<input type="file" data-rte="img-file" accept="' + esc(this.opts.imageAccept) + '" style="display:none">' +
          '</div>' +
          '<div class="rte-field" data-pane="url" style="display:none"><label>图片链接</label><input type="url" data-rte="img-url" placeholder="https://…/image.jpg"></div>' +
          '<div class="rte-form-actions"><button type="button" class="btn" data-rte="img-cancel">取消</button><button type="submit" class="btn primary">插入图片</button></div>' +
        '</form>' +
      '</div>' +
      '<div class="rte-pop" data-rte="pop-video">' +
        '<form class="rte-form" data-rte="form-video" autocomplete="off"><h4>插入视频</h4>' +
          '<div class="rte-tabs"><button type="button" class="rte-tab active" data-tab="upload">上传视频</button><button type="button" class="rte-tab" data-tab="url">嵌入链接</button></div>' +
          '<div class="rte-field" data-pane="upload">' +
            '<div class="rte-upload-zone" data-rte="vid-drop">' + ic("video", 30) + '<div>点击选择视频或拖拽到此处</div><div class="rte-upload-hint">支持 MP4 / WebM / Ogg。' + uploadHintImg + '</div></div>' +
            '<div class="rte-upload-preview" data-rte="vid-preview" style="display:none"><div style="width:56px;height:56px;border-radius:6px;border:1px solid var(--border);background:var(--surface-3);display:flex;align-items:center;justify-content:center;color:var(--text-3)">' + ic("video", 22) + '</div><div><div class="name" data-rte="vid-prev-name"></div><div class="meta" data-rte="vid-prev-meta"></div></div></div>' +
            '<input type="file" data-rte="vid-file" accept="' + esc(this.opts.videoAccept) + '" style="display:none">' +
          '</div>' +
          '<div class="rte-field" data-pane="url" style="display:none"><label>视频链接</label><input type="url" data-rte="vid-url" placeholder="https://…/video.mp4 或 B站/YouTube/优酷/腾讯 链接"><div class="rte-upload-hint">支持 .mp4/.webm 直链，以及 B站、YouTube、优酷、腾讯视频页面链接（自动转内嵌播放器）。</div></div>' +
          '<div class="rte-form-actions"><button type="button" class="btn" data-rte="vid-cancel">取消</button><button type="submit" class="btn primary">插入视频</button></div>' +
        '</form>' +
      '</div>' +
      '<div class="rte-pop" data-rte="pop-table">' +
        '<form class="rte-form" data-rte="form-table" autocomplete="off"><h4>插入表格</h4>' +
          '<div class="rte-field"><label>行数</label><input type="number" data-rte="table-rows" min="1" max="30" value="3"></div>' +
          '<div class="rte-field"><label>列数</label><input type="number" data-rte="table-cols" min="1" max="12" value="3"></div>' +
          '<div class="rte-field"><label class="check-row"><input type="checkbox" data-rte="table-head" checked> 首行作为表头</label></div>' +
          '<div class="rte-form-actions"><button type="button" class="btn" data-rte="table-cancel">取消</button><button type="submit" class="btn primary">插入</button></div>' +
        '</form>' +
      '</div>' +
      '<div class="rte-pop" data-rte="pop-chars"><div class="rte-chars" data-rte="chars-grid"></div></div>' +
      '<!-- 浮动工具条 -->' +
      '<div class="rte-floatbar" data-rte="media-bar" style="display:none"></div>' +
      '<div class="rte-floatbar" data-rte="table-bar" style="display:none"></div>' +
      '<!-- 帮助 -->' +
      '<div class="rte-modal-mask" data-rte="help-modal">' +
        '<div class="rte-modal">' +
          '<button type="button" class="close-x" data-rte="help-close" title="关闭">' + ic("x", 14) + '</button>' +
          '<h3>一幕·YIMU Editor</h3><div class="sub">电商富文本编辑器 v' + VERSION + '：图文混排、图片/视频上传、表格、源码模式，可配置上传接口。</div>' +
          '<h4>编辑快捷键</h4>' +
          '<div class="rte-kbd-grid">' +
            '<div class="rte-kbd-row"><span class="k">加粗 / 斜体 / 下划线</span><span><span class="rte-kbd">Ctrl</span>+<span class="rte-kbd">B</span>/<span class="rte-kbd">I</span>/<span class="rte-kbd">U</span></span></div>' +
            '<div class="rte-kbd-row"><span class="k">插入链接</span><span><span class="rte-kbd">Ctrl</span>+<span class="rte-kbd">K</span></span></div>' +
            '<div class="rte-kbd-row"><span class="k">撤销 / 重做</span><span><span class="rte-kbd">Ctrl</span>+<span class="rte-kbd">Z</span>/<span class="rte-kbd">Y</span></span></div>' +
            '<div class="rte-kbd-row"><span class="k">有序 / 无序列表</span><span><span class="rte-kbd">Ctrl</span>+<span class="rte-kbd">Shift</span>+<span class="rte-kbd">7</span>/<span class="rte-kbd">8</span></span></div>' +
            '<div class="rte-kbd-row"><span class="k">缩进 / 反缩进</span><span><span class="rte-kbd">Tab</span>/<span class="rte-kbd">Shift+Tab</span></span></div>' +
            '<div class="rte-kbd-row"><span class="k">查看帮助</span><span><span class="rte-kbd">Ctrl</span>+<span class="rte-kbd">H</span></span></div>' +
            '<div class="rte-kbd-row"><span class="k">退出全屏</span><span><span class="rte-kbd">Esc</span></span></div>' +
          '</div>' +
          '<h4>常用方法</h4>' +
          '<div style="background:var(--surface-2);border:1px solid var(--border);border-radius:8px;padding:10px 12px;font-family:var(--font-mono);font-size:12px;line-height:1.8;overflow-x:auto;color:var(--text)">' +
          'RTE.getHTML() / setHTML(html)<br>RTE.getText() / clear()<br>RTE.insertHTML(html)<br>RTE.config({ uploadUrl: "/api/upload" })' +
          '</div>' +
          '<div class="rte-form-actions" style="margin-top:14px"><button type="button" class="btn primary" data-rte="help-gotit">知道了</button></div>' +
        '</div>' +
      '</div>' +
      '<div class="rte-toast-wrap" data-rte="toast-wrap"></div>' +
      '<input type="file" data-rte="media-file" style="display:none">';

    // 缓存引用
    t.editor = t.q('[data-rte="editor"]');
    t.source = t.q('[data-rte="source"]');
    t.mediaBar = t.q('[data-rte="media-bar"]');
    t.tableBar = t.q('[data-rte="table-bar"]');
    t.toastWrap = t.q('[data-rte="toast-wrap"]');
    t.inSource = false;
  };

  /* ---------- 布局选项 ---------- */
  YimuEditor.prototype.applyLayoutOptions = function () {
    var t = this;
    if (t.opts.header === false) { t.q(".rte-header").style.display = "none"; }
    if (t.opts.statusbar === false) { t.q(".rte-statusbar").style.display = "none"; }
    if (t.opts.toolbar === false) {
      t.q(".rte-toolbar").style.display = "none";
    } else if (Array.isArray(t.opts.toolbar)) {
      var keys = t.opts.toolbar;
      // 白名单仅作用于工具栏区域，不影响顶栏按钮
      t.qall(".rte-toolbar [data-key]").forEach(function (b) {
        if (keys.indexOf(b.getAttribute("data-key")) < 0) b.remove();
      });
      t.qall(".rte-toolbar .tb-sep").forEach(function (sep) {
        var p = sep.previousElementSibling, n = sep.nextElementSibling;
        if ((!p || p.classList.contains("tb-sep")) || (!n || n.classList.contains("tb-sep"))) sep.remove();
      });
      t.qall(".rte-toolbar .tb-group").forEach(function (g) { if (!g.querySelector("button")) g.remove(); });
      t.qall(".rte-toolbar .rte-tb-row").forEach(function (r) { if (!r.querySelector("button")) r.style.display = "none"; });
    }
  };

  /* ---------- 查询工具 ---------- */
  YimuEditor.prototype.q = function (sel) { return this.app.querySelector(sel); };
  YimuEditor.prototype.qall = function (sel) { return this.app.querySelectorAll(sel); };
  YimuEditor.prototype.get = function (key) { return this.q('[data-rte="' + key + '"]'); };

  /* ---------- 主题 ---------- */
  YimuEditor.prototype.applyTheme = function (theme) {
    this.app.setAttribute("data-theme", theme === "dark" ? "dark" : "light");
    var btn = this.get("btn-theme");
    if (btn) btn.innerHTML = ic(theme === "dark" ? "sun" : "moon");
  };

  /* ---------- 弹层 ---------- */
  YimuEditor.prototype.showPop = function (pop, anchor) {
    this.closePops();
    var ar = anchor.getBoundingClientRect();
    var appRect = this.app.getBoundingClientRect();
    var top = ar.bottom - appRect.top + 6;
    var left = ar.left - appRect.left;
    pop.style.top = top + "px";
    pop.style.left = left + "px";
    var pr = pop.getBoundingClientRect();
    if (pr.right > appRect.right - 8) {
      left = ar.right - appRect.left - pr.width;
      pop.style.left = (left < 8 ? 8 : left) + "px";
    }
    pop.classList.add("open");
  };
  YimuEditor.prototype.closePops = function () {
    var t = this;
    t.qall(".rte-pop.open").forEach(function (p) { p.classList.remove("open"); });
  };
  YimuEditor.prototype.closeBars = function () {
    this.mediaBar.style.display = "none";
    this.tableBar.style.display = "none";
  };

  /* ---------- 命令 ---------- */
  YimuEditor.prototype.exec = function (cmd, value) {
    this.editor.focus();
    document.execCommand(cmd, false, value);
    this.afterChange();
  };
  YimuEditor.prototype.execStyle = function (cmd, value) {
    this.editor.focus();
    document.execCommand("styleWithCSS", false, true);
    document.execCommand(cmd, false, value);
    this.afterChange();
  };

  YimuEditor.prototype.getSelectedBlocks = function () {
    var t = this;
    var sel = window.getSelection();
    if (!sel.rangeCount) return [];
    var range = sel.getRangeAt(0);
    var blocks = [];
    if (range.collapsed) {
      var el = range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentElement;
      while (el && el !== t.editor && !isBlock(el)) el = el.parentElement;
      if (el && el !== t.editor) blocks.push(el);
    } else {
      var walker = document.createTreeWalker(t.editor, NodeFilter.SHOW_ELEMENT, {
        acceptNode: function (n) {
          if (n === t.editor) return NodeFilter.FILTER_SKIP;
          if (!isBlock(n)) return NodeFilter.FILTER_SKIP;
          return range.intersectsNode(n) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
        }
      });
      while (walker.nextNode()) blocks.push(walker.currentNode);
      if (blocks.length === 0) {
        var el2 = range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentElement;
        while (el2 && el2 !== t.editor && !isBlock(el2)) el2 = el2.parentElement;
        if (el2 && el2 !== t.editor) blocks.push(el2);
      }
    }
    return blocks;
  };

  /* ---------- 上传 ---------- */
  YimuEditor.prototype.uploadFile = function (file, kind, cb) {
    var t = this;
    var isImg = kind === "image";
    var max = isImg ? t.opts.maxImageSize : t.opts.maxVideoSize;
    if (file.size > max) {
      t.toast("文件超出大小限制（" + Math.round(max / 1024 / 1024) + "MB）", "error");
      return;
    }
    if (t.opts.uploadUrl) {
      var fd = new FormData();
      fd.append(t.opts.uploadField || "file", file);
      fetch(t.opts.uploadUrl, { method: "POST", body: fd, headers: t.opts.uploadHeaders })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status)); })
        .then(function (data) {
          var url = data;
          if (data && typeof data === "object") {
            url = data[t.opts.uploadResultKey] || data.url || data.path || data.src;
          }
          if (url) cb(String(url));
          else t.toast("上传成功但未解析到文件地址", "warn");
        })
        .catch(function (e) { t.toast("上传失败：" + e.message, "error"); });
    } else {
      var reader = new FileReader();
      reader.onload = function () { cb(reader.result); };
      reader.onerror = function () { t.toast("读取文件失败", "error"); };
      reader.readAsDataURL(file);
    }
  };

  /* ---------- 文本命令 ---------- */
  YimuEditor.prototype.cmd = function (name) {
    var t = this;
    switch (name) {
      case "undo": t.exec("undo"); break;
      case "redo": t.exec("redo"); break;
      case "bold": t.exec("bold"); break;
      case "italic": t.exec("italic"); break;
      case "underline": t.exec("underline"); break;
      case "strike": t.exec("strikeThrough"); break;
      case "sup": t.exec("superscript"); break;
      case "sub": t.exec("subscript"); break;
      case "clear": t.exec("removeFormat"); break;
      case "indent": t.exec("indent"); break;
      case "outdent": t.exec("outdent"); break;
      case "align-left": t.exec("justifyLeft"); break;
      case "align-center": t.exec("justifyCenter"); break;
      case "align-right": t.exec("justifyRight"); break;
      case "align-justify": t.exec("justifyFull"); break;
      case "list-ul": t.exec("insertUnorderedList"); break;
      case "list-ol": t.exec("insertOrderedList"); break;
      case "list-task": t.toggleTaskList(); break;
      case "quote": t.exec("formatBlock", "<blockquote>"); break;
      case "code": t.exec("formatBlock", "<pre>"); break;
      case "hr":
        t.editor.focus();
        document.execCommand("insertHTML", false, "<hr>");
        t.afterChange();
        break;
    }
  };

  /* ---------- 任务清单 ---------- */
  YimuEditor.prototype.selNode = function () {
    var sel = window.getSelection();
    return sel.rangeCount ? sel.anchorNode : null;
  };
  YimuEditor.prototype.closest = function (node, tag) {
    if (!node) return null;
    var el = node.nodeType === 3 ? node.parentElement : node;
    while (el && el !== this.editor) {
      if (el.tagName === tag) return el;
      el = el.parentElement;
    }
    return null;
  };
  YimuEditor.prototype.toggleTaskList = function () {
    var t = this;
    t.editor.focus();
    var ul = t.closest(t.selNode(), "UL");
    if (ul && ul.classList.contains("rte-task")) {
      ul.classList.remove("rte-task");
      t.afterChange();
      return;
    }
    document.execCommand("insertUnorderedList");
    ul = t.closest(t.selNode(), "UL");
    if (ul) ul.classList.add("rte-task");
    t.afterChange();
  };

  /* ---------- 字体/字号/行距 ---------- */
  YimuEditor.prototype.setFontFamily = function (family) {
    var t = this;
    if (!family) return;
    t.editor.focus();
    if (family === "inherit") {
      t.exec("fontName", "PingFang SC, Microsoft YaHei, Helvetica Neue, Arial, sans-serif");
      return;
    }
    t.exec("fontName", family);
  };
  YimuEditor.prototype.setFontSize = function (px) {
    var t = this;
    t.editor.focus();
    var map = { 12: "1", 14: "2", 16: "3", 18: "4", 20: "4", 24: "5", 28: "5", 32: "6", 48: "7" };
    document.execCommand("fontSize", false, map[px] || "3");
    var sel = window.getSelection();
    if (sel.rangeCount) {
      var range = sel.getRangeAt(0);
      t.editor.querySelectorAll("font[size]").forEach(function (f) {
        if (range.intersectsNode(f)) {
          f.style.fontSize = px + "px";
          f.removeAttribute("size");
        }
      });
    }
    t.afterChange();
  };
  YimuEditor.prototype.setLineHeight = function (v) {
    var t = this;
    t.getSelectedBlocks().forEach(function (b) {
      if (v === "normal") b.style.removeProperty("line-height");
      else b.style.lineHeight = v;
    });
    t.editor.focus();
    t.afterChange();
  };
  YimuEditor.prototype.setTextColor = function (color) {
    var t = this;
    if (!color) t.execStyle("foreColor", "#23221f");
    else t.execStyle("foreColor", color);
    var bar = t.get("color-bar");
    if (bar) bar.style.background = color || "#23221f";
  };
  YimuEditor.prototype.setHilite = function (color) {
    if (!color) this.execStyle("hiliteColor", "transparent");
    else this.execStyle("hiliteColor", color);
  };

  /* ---------- 链接 ---------- */
  YimuEditor.prototype.findAnchor = function () {
    var t = this;
    var node = t.selNode();
    if (!node) return null;
    var el = node.nodeType === 3 ? node.parentElement : node;
    while (el && el !== t.editor) {
      if (el.tagName === "A") return el;
      el = el.parentElement;
    }
    return null;
  };
  YimuEditor.prototype.openLinkPop = function () {
    var t = this;
    var a = t.findAnchor();
    if (a) {
      t.get("link-url").value = a.getAttribute("href") || "";
      t.get("link-text").value = a.textContent;
      t.get("link-target").checked = a.getAttribute("target") === "_blank";
      t.get("link-text-hint").textContent = "（当前链接文字）";
    } else {
      t.get("link-url").value = "";
      var sel = window.getSelection();
      t.get("link-text").value = (sel && !sel.isCollapsed && sel.toString().trim()) ? "" : "";
      t.get("link-text-hint").textContent = "（未选中文字时使用）";
    }
    t.showPop(t.get("pop-link"), t.get("cmd-link"));
    t.get("link-url").focus();
  };
  YimuEditor.prototype.applyLink = function (e) {
    var t = this;
    e.preventDefault();
    var url = t.get("link-url").value.trim();
    if (!url) { t.toast("请输入链接地址", "warn"); return; }
    var href = url;
    if (!/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(href) && !href.startsWith("/") && !href.startsWith("#")) href = "https://" + href;
    t.editor.focus();
    var sel = window.getSelection();
    var hasSel = sel && !sel.isCollapsed && sel.toString().trim();
    if (!hasSel) {
      var text = t.get("link-text").value.trim() || href;
      var target = t.get("link-target").checked ? ' target="_blank" rel="noopener"' : "";
      document.execCommand("insertHTML", false, '<a href="' + esc(href) + '"' + target + ">" + esc(text) + "</a>");
    } else {
      document.execCommand("createLink", false, href);
      var a = t.findAnchor();
      if (a) {
        if (t.get("link-target").checked) { a.setAttribute("target", "_blank"); a.setAttribute("rel", "noopener"); }
        else { a.removeAttribute("target"); a.removeAttribute("rel"); }
      }
    }
    t.closePops();
    t.afterChange();
  };
  YimuEditor.prototype.removeLink = function () {
    var t = this;
    var a = t.findAnchor();
    if (a) {
      t.editor.focus();
      var range = document.createRange();
      range.selectNode(a);
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      document.execCommand("unlink");
    }
    t.closePops();
    t.afterChange();
  };

  /* ---------- 媒体 ---------- */
  YimuEditor.prototype.selectMedia = function (node) {
    var t = this;
    t.editor.querySelectorAll(".rte-selected").forEach(function (n) { n.classList.remove("rte-selected"); });
    node.classList.add("rte-selected");
    t.renderMediaBar(node);
  };
  YimuEditor.prototype.clearMediaSel = function () {
    this.editor.querySelectorAll(".rte-selected").forEach(function (n) { n.classList.remove("rte-selected"); });
    this.mediaBar.style.display = "none";
  };
  YimuEditor.prototype.positionBar = function (bar, node) {
    var ar = node.getBoundingClientRect();
    var appRect = this.app.getBoundingClientRect();
    var top = ar.top - appRect.top - bar.offsetHeight - 8;
    if (top < 70) top = ar.bottom - appRect.top + 8;
    var left = ar.left - appRect.left + (ar.width - bar.offsetWidth) / 2;
    left = Math.max(8, Math.min(left, this.app.clientWidth - bar.offsetWidth - 8));
    bar.style.top = top + "px";
    bar.style.left = left + "px";
  };
  YimuEditor.prototype.renderMediaBar = function (node) {
    var t = this;
    var isImg = node.tagName === "IMG";
    var isVideo = node.tagName === "VIDEO";
    if (!isImg && !isVideo && !node.classList.contains("rte-embed-video")) return;
    var html = "";
    if (isImg) {
      html =
        '<button type="button" class="tb-btn" data-act="float-left" title="左浮动">' + ic("align-left") + "</button>" +
        '<button type="button" class="tb-btn" data-act="center" title="居中显示">' + ic("align-center") + "</button>" +
        '<button type="button" class="tb-btn" data-act="float-right" title="右浮动">' + ic("align-right") + "</button>" +
        '<span class="sep"></span>' +
        '<input type="number" value="' + Math.round(node.getBoundingClientRect().width) + '" min="40" step="10" title="宽度"><span class="lbl">px</span>' +
        '<span class="sep"></span>' +
        '<button type="button" class="tb-btn" data-act="link" title="为图片添加链接">' + ic("link") + "</button>" +
        '<button type="button" class="tb-btn" data-act="replace" title="替换图片">' + ic("refresh") + "</button>" +
        '<button type="button" class="tb-btn" data-act="delete" title="删除">' + ic("trash") + "</button>";
    } else {
      html =
        '<input type="number" value="' + Math.round(node.getBoundingClientRect().width) + '" min="120" step="20" title="宽度"><span class="lbl">px</span>' +
        '<span class="sep"></span>' +
        '<button type="button" class="tb-btn" data-act="replace" title="替换视频">' + ic("refresh") + "</button>" +
        '<button type="button" class="tb-btn" data-act="delete" title="删除">' + ic("trash") + "</button>";
    }
    t.mediaBar.innerHTML = html;
    t.mediaBar.style.display = "flex";
    t.positionBar(t.mediaBar, node);
    var wInput = t.mediaBar.querySelector("input");
    if (wInput) {
      wInput.onchange = function () {
        var w = parseInt(wInput.value, 10) || 100;
        if (isImg) { node.style.width = w + "px"; node.style.height = "auto"; }
        else if (isVideo) { node.style.width = w + "px"; node.style.height = "auto"; }
        else if (node.classList.contains("rte-embed-video")) { node.style.width = w + "px"; }
        t.afterChange();
      };
    }
    t.mediaBar.querySelectorAll("[data-act]").forEach(function (btn) {
      btn.onclick = function () {
        var act = btn.getAttribute("data-act");
        if (act === "float-left") t.applyImgLayout(node, "left");
        else if (act === "center") t.applyImgLayout(node, "center");
        else if (act === "float-right") t.applyImgLayout(node, "right");
        else if (act === "link") t.imageLink(node);
        else if (act === "replace") t.replaceMedia(node);
        else if (act === "delete") t.removeMedia(node);
      };
    });
  };
  YimuEditor.prototype.applyImgLayout = function (img, mode) {
    var t = this;
    img.style.display = mode === "center" ? "block" : "inline";
    img.style.margin = mode === "center" ? "0 auto" : (mode === "left" ? "0 18px 10px 0" : "0 0 10px 18px");
    img.style.float = (mode === "left" || mode === "right") ? mode : "none";
    t.afterChange();
    t.selectMedia(img);
  };
  YimuEditor.prototype.imageLink = function (img) {
    var t = this;
    var cur = img.getAttribute("data-href") || "";
    var url = window.prompt("为图片添加链接地址（留空移除）", cur);
    if (url === null) return;
    if (url.trim() === "") img.removeAttribute("data-href");
    else img.setAttribute("data-href", url.trim());
    t.afterChange();
  };
  YimuEditor.prototype.removeMedia = function (node) {
    var t = this;
    node.remove();
    t.clearMediaSel();
    t.afterChange();
  };
  YimuEditor.prototype.replaceMedia = function (node) {
    var t = this;
    var kind = node.tagName === "IMG" ? "image" : "video";
    var input = t.get("media-file");
    input.accept = kind === "image" ? t.opts.imageAccept : t.opts.videoAccept;
    input.onchange = function () {
      var f = input.files[0];
      if (!f) return;
      t.uploadFile(f, kind, function (url) {
        if (kind === "image") {
          node.src = url;
        } else if (node.classList.contains("rte-embed-video")) {
          var wrapper = document.createElement("div");
          wrapper.className = "rte-embed-video";
          node.parentNode.insertBefore(wrapper, node);
          node.remove();
          t.selectMedia(wrapper);
        } else {
          node.src = url;
        }
        t.afterChange();
        t.clearMediaSel();
      });
    };
    input.click();
  };
  YimuEditor.prototype.insertImageUrl = function (url, width) {
    var t = this;
    t.editor.focus();
    var html = '<img src="' + esc(url) + '" alt=""' + (width ? ' style="width:' + width + 'px;height:auto"' : "") + ">";
    document.execCommand("insertHTML", false, html);
    t.afterChange();
    var imgs = t.editor.querySelectorAll("img");
    t.selectMedia(imgs[imgs.length - 1]);
  };
  YimuEditor.prototype.parseVideoUrl = function (url) {
    var bv = url.match(/bilibili\.com\/video\/(BV[0-9A-Za-z]+)/i);
    if (bv) return { type: "iframe", src: "//player.bilibili.com/player.html?bvid=" + bv[1] + "&page=1&high_quality=1" };
    var yt = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([0-9A-Za-z_-]{11})/);
    if (yt) return { type: "iframe", src: "https://www.youtube.com/embed/" + yt[1] };
    var yk = url.match(/v\.youku\.com\/v_show\/id_([0-9A-Za-z=]+)/i);
    if (yk) return { type: "iframe", src: "https://player.youku.com/embed/" + yk[1] };
    var tx = url.match(/v\.qq\.com\/x\/cover\/[0-9A-Za-z]+\/([0-9A-Za-z]+)\.html/i);
    if (tx) return { type: "iframe", src: "https://v.qq.com/txp/iframe/player.html?vid=" + tx[1] };
    if (/\.(mp4|webm|ogv|ogg|mov)(\?|#|$)/i.test(url)) return { type: "video", src: url };
    return { type: "video", src: url };
  };
  YimuEditor.prototype.insertVideoSrc = function (src, poster) {
    var t = this;
    t.editor.focus();
    var html = '<video controls preload="metadata" src="' + esc(src) + '"' + (poster ? ' poster="' + esc(poster) + '"' : "") + "></video>";
    document.execCommand("insertHTML", false, html);
    t.afterChange();
    var vids = t.editor.querySelectorAll("video");
    t.selectMedia(vids[vids.length - 1]);
  };
  YimuEditor.prototype.insertVideoEmbed = function (src) {
    var t = this;
    t.editor.focus();
    var html = '<div class="rte-embed-video"><iframe src="' + esc(src) + '" frameborder="0" allowfullscreen allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"></iframe></div>';
    document.execCommand("insertHTML", false, html);
    t.afterChange();
    var ws = t.editor.querySelectorAll(".rte-embed-video");
    t.selectMedia(ws[ws.length - 1]);
  };

  /* ---------- 表格 ---------- */
  YimuEditor.prototype.insertTable = function (rows, cols, withHead) {
    var t = this;
    var html = "<table><tbody>";
    for (var r = 0; r < rows; r++) {
      html += "<tr>";
      for (var c = 0; c < cols; c++) {
        var tag = withHead && r === 0 ? "th" : "td";
        html += "<" + tag + "><br></" + tag + ">";
      }
      html += "</tr>";
    }
    html += "</tbody></table>";
    t.editor.focus();
    document.execCommand("insertHTML", false, html);
    t.afterChange();
  };
  YimuEditor.prototype.getCell = function () {
    var t = this;
    var node = t.selNode();
    if (!node) return null;
    var el = node.nodeType === 3 ? node.parentElement : node;
    while (el && el !== t.editor) {
      if (el.tagName === "TD" || el.tagName === "TH") return el;
      el = el.parentElement;
    }
    return null;
  };
  YimuEditor.prototype.showTableBar = function () {
    var t = this;
    var cell = t.getCell();
    if (!cell) { t.tableBar.style.display = "none"; return; }
    t.tableBar.innerHTML =
      '<button type="button" class="tb-btn" data-tact="row-up" title="上方插入行">' + ic("row-top") + "</button>" +
      '<button type="button" class="tb-btn" data-tact="row-down" title="下方插入行">' + ic("row-bottom") + "</button>" +
      '<button type="button" class="tb-btn" data-tact="col-left" title="左侧插入列">' + ic("col-left") + "</button>" +
      '<button type="button" class="tb-btn" data-tact="col-right" title="右侧插入列">' + ic("col-right") + "</button>" +
      '<span class="sep"></span>' +
      '<button type="button" class="tb-btn" data-tact="del-row" title="删除行">' + ic("x") + "</button>" +
      '<button type="button" class="tb-btn" data-tact="del-table" title="删除表格">' + ic("trash") + "</button>";
    t.tableBar.style.display = "flex";
    t.positionBar(t.tableBar, cell);
    t.tableBar.querySelectorAll("[data-tact]").forEach(function (b) {
      b.onclick = function () {
        var act = b.getAttribute("data-tact");
        var cell2 = t.getCell();
        var table = cell2 ? t.getCellTable(cell2) : null;
        if (!cell2 || !table) return;
        var row = cell2.parentElement;
        if (act === "row-up" || act === "row-down") {
          var nr = row.cloneNode(true);
          nr.querySelectorAll("td,th").forEach(function (x) { x.innerHTML = "<br>"; });
          if (act === "row-up") row.parentNode.insertBefore(nr, row);
          else row.parentNode.insertBefore(nr, row.nextSibling);
        } else if (act === "col-left" || act === "col-right") {
          var idx = Array.prototype.indexOf.call(row.children, cell2);
          table.querySelectorAll("tr").forEach(function (tr) {
            var ref = tr.children[idx];
            var nc = document.createElement(ref && ref.tagName === "TH" ? "th" : "td");
            nc.innerHTML = "<br>";
            if (act === "col-left") tr.insertBefore(nc, ref);
            else if (ref && ref.nextSibling) tr.insertBefore(nc, ref.nextSibling);
            else tr.appendChild(nc);
          });
        } else if (act === "del-row") {
          row.remove();
        } else if (act === "del-table") {
          table.remove();
          t.tableBar.style.display = "none";
        }
        t.afterChange();
        t.showTableBar();
      };
    });
  };
  YimuEditor.prototype.getCellTable = function (cell) {
    var el = cell;
    while (el && el !== this.editor) {
      if (el.tagName === "TABLE") return el;
      el = el.parentElement;
    }
    return null;
  };

  /* ---------- 源码 ---------- */
  YimuEditor.prototype.toggleSource = function () {
    var t = this;
    t.inSource = !t.inSource;
    if (t.inSource) {
      t.source.value = t.editor.innerHTML;
      t.app.classList.add("source-mode");
    } else {
      t.editor.innerHTML = t.source.value;
      t.app.classList.remove("source-mode");
      t.afterChange();
    }
    var btn = t.get("cmd-source");
    if (btn) btn.classList.toggle("active", t.inSource);
  };

  /* ---------- 纯文本粘贴 ---------- */
  YimuEditor.prototype.pastePlain = function () {
    var t = this;
    navigator.clipboard.readText().then(function (text) {
      t.editor.focus();
      document.execCommand("insertText", false, text);
      t.afterChange();
    }).catch(function () {
      t.toast("无法读取剪贴板（请检查浏览器权限）", "warn");
    });
  };

  /* ---------- 统计 / 草稿 / 变更 ---------- */
  YimuEditor.prototype.afterChange = function (notify) {
    var t = this;
    t.updateStats();
    t.autosave();
    if (notify !== false && typeof t.opts.onChange === "function") t.opts.onChange(t.editor.innerHTML, t);
    t.scheduleToolbar();
  };
  YimuEditor.prototype.updateStats = function () {
    var t = this;
    var text = t.editor.innerText || t.editor.textContent || "";
    var chars = text.replace(/\s/g, "").length;
    var cjk = (text.match(/[\u4e00-\u9fa5]/g) || []).length;
    var words = (text.trim().match(/[A-Za-z0-9]+/g) || []).length;
    var size = new Blob([t.editor.innerHTML]).size;
    t.get("stat-chars").textContent = chars + " 字符";
    t.get("stat-cjk").textContent = cjk + " 汉字";
    t.get("stat-words").textContent = words + " 单词";
    t.get("stat-size").textContent = (size / 1024).toFixed(1) + " KB";
  };
  YimuEditor.prototype.autosave = function () {
    var t = this;
    if (!t.opts.autosave) return;
    clearTimeout(t._saveTimer);
    t._saveTimer = setTimeout(function () {
      try { localStorage.setItem(t.opts.draftKey, t.editor.innerHTML); t.setDraftState(true); } catch (e) {}
    }, 600);
  };
  YimuEditor.prototype.setDraftState = function (saved) {
    var el = this.get("draft-state");
    if (!el) return;
    this.get("draft-text").textContent = saved ? "草稿已自动保存" : "草稿未保存";
    el.classList.toggle("saved", !!saved);
  };
  YimuEditor.prototype.clearDraft = function () {
    var t = this;
    try { localStorage.removeItem(t.opts.draftKey); t.setDraftState(false); t.toast("本地草稿已清除"); } catch (e) {}
  };

  /* ---------- 工具栏状态 ---------- */
  YimuEditor.prototype.scheduleToolbar = function () {
    var t = this;
    clearTimeout(t._tbTimer);
    t._tbTimer = setTimeout(function () { t.updateToolbar(); }, 60);
  };
  YimuEditor.prototype.updateToolbar = function () {
    var t = this;
    function st(c) { try { return document.queryCommandState(c); } catch (e) { return false; } }
    function val(c) { try { return document.queryCommandValue(c); } catch (e) { return ""; } }
    // 白名单可能移除了按钮，先判空再操作
    function setActive(key, on) { var el = t.get(key); if (el) el.classList.toggle("active", !!on); }
    function setText(key, txt) { var el = t.get(key); if (el) el.textContent = txt; }
    setActive("cmd-bold", st("bold"));
    setActive("cmd-italic", st("italic"));
    setActive("cmd-underline", st("underline"));
    setActive("cmd-strike", st("strikeThrough"));
    setActive("cmd-sup", st("superscript"));
    setActive("cmd-sub", st("subscript"));
    setActive("cmd-list-ul", st("insertUnorderedList"));
    setActive("cmd-list-ol", st("insertOrderedList"));
    setActive("cmd-list-task", (function () {
      var ul = t.closest(t.selNode(), "UL");
      return !!(ul && ul.classList.contains("rte-task"));
    })());
    setActive("cmd-align-left", st("justifyLeft"));
    setActive("cmd-align-center", st("justifyCenter"));
    setActive("cmd-align-right", st("justifyRight"));
    setActive("cmd-align-justify", st("justifyFull"));
    var fb = (val("formatBlock") || "").toLowerCase().replace(/[<>]/g, "");
    var formatMap = { "": ["正文", "p"], p: ["正文", "p"], div: ["正文", "p"], h1: ["标题 1", "h1"],
      h2: ["标题 2", "h2"], h3: ["标题 3", "h3"], h4: ["标题 4", "h4"],
      blockquote: ["引用", "blockquote"], pre: ["代码块", "pre"] };
    var fmt = formatMap[fb] || ["正文", "p"];
    setText("lbl-format", fmt[0]);
    t.qall("[data-rte='menu-format'] .rte-menu-item").forEach(function (it) {
      it.classList.toggle("active", it.getAttribute("data-tag") === fmt[1]);
    });
    var fn = val("fontName");
    setText("lbl-font", t.fontLabel(fn));
    t.qall("[data-rte='menu-font'] .rte-menu-item").forEach(function (it) {
      var fam = it.getAttribute("data-family");
      it.classList.toggle("active", !!fn && fn.indexOf(fam.split(",")[0].replace(/['"]/g, "")) >= 0);
    });
    var fs = val("fontSize");
    var fsMap = { "1": 12, "2": 14, "3": 16, "4": 18, "5": 24, "6": 32, "7": 48 };
    var px = fsMap[fs] || 16;
    setText("lbl-fontsize", px);
    t.qall("[data-rte='menu-fontsize'] .rte-menu-item").forEach(function (it) {
      it.classList.toggle("active", parseInt(it.getAttribute("data-px"), 10) === px);
    });
    setActive("cmd-link", !!t.findAnchor());
    var sel = window.getSelection();
    if (sel && !sel.isCollapsed) setText("stat-sel", "已选中 " + sel.toString().length + " 字符");
    else setText("stat-sel", "未选中内容");
  };
  YimuEditor.prototype.fontLabel = function (fn) {
    if (!fn) return "默认字体";
    var map = {
      pingfang: "默认字体", "helvetica neue": "默认字体", "microsoft yahei": "微软雅黑",
      simhei: "黑体", simsun: "宋体", songti: "宋体", georgia: "衬线", "times new roman": "衬线",
      kai: "楷体", kaiti: "楷体", consolas: "等宽", monaco: "等宽", "courier new": "等宽"
    };
    for (var k in map) { if (fn.toLowerCase().indexOf(k) >= 0) return map[k]; }
    return fn.length > 12 ? fn.slice(0, 12) + "…" : fn;
  };

  /* ---------- 菜单构建 ---------- */
  YimuEditor.prototype.buildMenus = function () {
    var t = this;
    var fmts = [["p", "正文"], ["h1", "标题 1"], ["h2", "标题 2"], ["h3", "标题 3"], ["h4", "标题 4"], ["blockquote", "引用块"], ["pre", "代码块"]];
    t.get("menu-format").innerHTML = fmts.map(function (f) {
      return '<button type="button" class="rte-menu-item" data-tag="' + f[0] + '"><span>' + f[1] + '</span><span class="tick">' + ic("check", 14) + "</span></button>";
    }).join("");
    t.qall("[data-rte='menu-format'] .rte-menu-item").forEach(function (it) {
      it.addEventListener("click", function () {
        var tag = it.getAttribute("data-tag");
        t.exec("formatBlock", tag === "p" ? "p" : "<" + tag + ">");
        t.closePops();
      });
    });

    var fonts = [
      ["inherit", "默认字体"],
      ["PingFang SC, Microsoft YaHei, Helvetica Neue, Arial, sans-serif", "系统无衬线"],
      ["Georgia, Times New Roman, Songti SC, SimSun, serif", "衬线（宋体）"],
      ["SimHei, PingFang SC, Microsoft YaHei, sans-serif", "黑体"],
      ["Microsoft YaHei, PingFang SC, sans-serif", "微软雅黑"],
      ["KaiTi, Kaiti SC, STKaiti, serif", "楷体"],
      ["Consolas, Monaco, Courier New, monospace", "等宽"]
    ];
    t.get("menu-font").innerHTML = fonts.map(function (f) {
      return '<button type="button" class="rte-menu-item" data-family="' + esc(f[1]) + '"><span style="font-family:' + (f[0] === "inherit" ? "" : f[0]) + '">' + f[1] + '</span><span class="tick">' + ic("check", 14) + "</span></button>";
    }).join("");
    t.qall("[data-rte='menu-font'] .rte-menu-item").forEach(function (it) {
      var label = it.getAttribute("data-family");
      var fam = null;
      fonts.forEach(function (f) { if (f[1] === label) fam = f[0]; });
      it.addEventListener("click", function () { t.setFontFamily(fam || "inherit"); t.closePops(); });
    });

    var sizes = [[12, "小"], [14, "较小"], [16, "正文"], [18, "中"], [20, "大"], [24, "特大"], [32, "超大"], [48, "巨大"]];
    t.get("menu-fontsize").innerHTML = sizes.map(function (s) {
      return '<button type="button" class="rte-menu-item" data-px="' + s[0] + '"><span style="font-size:' + Math.min(s[0], 20) + 'px">' + s[1] + " " + s[0] + '</span><span class="tick">' + ic("check", 14) + "</span></button>";
    }).join("");
    t.qall("[data-rte='menu-fontsize'] .rte-menu-item").forEach(function (it) {
      it.addEventListener("click", function () { t.setFontSize(parseInt(it.getAttribute("data-px"), 10)); t.closePops(); });
    });

    var lh = [["normal", "默认"], ["1.3", "1.3 倍"], ["1.5", "1.5 倍"], ["1.75", "1.75 倍"], ["2", "2 倍"], ["2.5", "2.5 倍"], ["3", "3 倍"]];
    t.get("menu-lineheight").innerHTML = lh.map(function (l) {
      return '<button type="button" class="rte-menu-item" data-v="' + l[0] + '"><span>行距 ' + l[1] + '</span><span class="tick">' + ic("check", 14) + "</span></button>";
    }).join("");
    t.qall("[data-rte='menu-lineheight'] .rte-menu-item").forEach(function (it) {
      it.addEventListener("click", function () { t.setLineHeight(it.getAttribute("data-v")); t.closePops(); });
    });

    var textColors = ["#23221f", "#666666", "#8a8a8a", "#c0392b", "#e67e22", "#f1c40f", "#2ecc71", "#16a085",
      "#0f766e", "#2980b9", "#2c3e50", "#8e44ad", "#e91e63", "#b03a2e", "#7f8c8d", "#1abc9c",
      "#ff6b6b", "#ffd93d", "#6bcb77", "#4d96ff"];
    t.get("swatches-text").innerHTML = textColors.map(function (c) {
      return '<button type="button" class="rte-swatch" data-c="' + c + '" style="background:' + c + '"></button>';
    }).join("") + '<button type="button" class="rte-swatch none" data-c="" title="默认颜色"></button>';
    t.qall("[data-rte='swatches-text'] .rte-swatch").forEach(function (s) {
      s.addEventListener("click", function () { t.setTextColor(s.getAttribute("data-c")); t.closePops(); });
    });
    t.get("color-custom").addEventListener("input", function (e) { t.setTextColor(e.target.value); var b = t.get("color-bar"); if (b) b.style.background = e.target.value; });
    t.get("color-default").addEventListener("click", function () { t.setTextColor("#23221f"); t.closePops(); });

    var hilites = ["#fff94a", "#ffe066", "#ffd1dc", "#ffb3ba", "#c1f0c1", "#b3d9ff", "#e6ccff", "#ffdab9",
      "#d4f0ff", "#fff0c2", "#c9f2e6", "#f2e6d9"];
    t.get("swatches-hilite").innerHTML = hilites.map(function (c) {
      return '<button type="button" class="rte-swatch" data-c="' + c + '" style="background:' + c + '"></button>';
    }).join("") + '<button type="button" class="rte-swatch none" data-c="" title="无高亮"></button>';
    t.qall("[data-rte='swatches-hilite'] .rte-swatch").forEach(function (s) {
      s.addEventListener("click", function () { t.setHilite(s.getAttribute("data-c") || null); t.closePops(); });
    });
    t.get("hilite-custom").addEventListener("input", function (e) { t.setHilite(e.target.value); });
    t.get("hilite-none").addEventListener("click", function () { t.setHilite(null); t.closePops(); });

    var chars = ["©", "®", "™", "¥", "€", "£", "$", "¢", "°", "±", "×", "÷", "≈", "≠", "≤", "≥", "∞", "√", "∑", "π", "α", "β", "γ", "Δ", "Ω", "μ", "‰", "§", "¶", "†", "※", "☆", "★", "○", "●", "◎", "◇", "◆", "□", "■", "△", "▲", "→", "←", "↑", "↓", "↔", "⇒", "⇔", "•", "·", "—", "–", "…", "“", "”", "‘", "’", "〈", "〉", "《", "》", "【", "】", "（", "）", "？", "！", "：", "；", "、", "，", "。", "￥", "½", "¼", "¾", "¹", "²", "³", "₀", "₁", "₂", "₃", "①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"];
    t.get("chars-grid").innerHTML = chars.map(function (c) { return '<button type="button" class="rte-char">' + c + "</button>"; }).join("");
    t.qall("[data-rte='chars-grid'] .rte-char").forEach(function (b) {
      b.addEventListener("click", function () {
        t.editor.focus();
        document.execCommand("insertText", false, b.textContent);
        t.afterChange();
        t.closePops();
      });
    });
  };

  /* ---------- 事件绑定 ---------- */
  YimuEditor.prototype.bindEvents = function () {
    var t = this;
    // 兜底：白名单可能移除了某些按钮，$ 对缺失元素返回 no-op 对象，避免事件绑定崩溃
    var noopEl = function () {
      return {
        addEventListener: function () {},
        style: {},
        classList: { add: function () {}, remove: function () {}, toggle: function () {} },
        files: []
      };
    };
    var $ = function (k) { var el = t.get(k); return el || noopEl(); };

    // 工具栏命令
    ["undo", "redo", "bold", "italic", "underline", "strike", "sup", "sub", "clear",
     "indent", "outdent", "align-left", "align-center", "align-right", "align-justify",
     "list-ul", "list-ol", "list-task", "quote", "code", "hr"].forEach(function (k) {
      var b = t.get("cmd-" + k);
      if (b) b.addEventListener("click", function () { t.cmd(k); });
    });

    // 下拉按钮
    $("btn-format").addEventListener("click", function (e) { e.stopPropagation(); t.showPop(t.get("pop-format"), $("btn-format")); });
    $("btn-font").addEventListener("click", function (e) { e.stopPropagation(); t.showPop(t.get("pop-font"), $("btn-font")); });
    $("btn-fontsize").addEventListener("click", function (e) { e.stopPropagation(); t.showPop(t.get("pop-fontsize"), $("btn-fontsize")); });
    $("btn-lineheight").addEventListener("click", function (e) { e.stopPropagation(); t.showPop(t.get("pop-lineheight"), $("btn-lineheight")); });
    $("btn-color").addEventListener("click", function (e) { e.stopPropagation(); t.showPop(t.get("pop-color"), $("btn-color")); });
    $("btn-hilite").addEventListener("click", function (e) { e.stopPropagation(); t.showPop(t.get("pop-hilite"), $("btn-hilite")); });
    $("cmd-chars").addEventListener("click", function (e) { e.stopPropagation(); t.showPop(t.get("pop-chars"), $("cmd-chars")); });
    $("cmd-link").addEventListener("click", function (e) { e.stopPropagation(); t.openLinkPop(); });
    $("cmd-image").addEventListener("click", function (e) { e.stopPropagation(); t.openImagePop(); });
    $("cmd-video").addEventListener("click", function (e) { e.stopPropagation(); t.openVideoPop(); });
    $("cmd-table").addEventListener("click", function (e) { e.stopPropagation(); t.showPop(t.get("pop-table"), $("cmd-table")); });
    $("cmd-plain").addEventListener("click", function () { t.pastePlain(); });
    $("cmd-source").addEventListener("click", function () { t.toggleSource(); });

    // 顶栏
    $("btn-theme").addEventListener("click", function () {
      var next = t.app.getAttribute("data-theme") === "dark" ? "light" : "dark";
      t.applyTheme(next);
      t.opts.theme = next;
      try { localStorage.setItem("rte-theme", next); } catch (e) {}
    });
    $("btn-copy").addEventListener("click", function () {
      navigator.clipboard.writeText(t.editor.innerHTML).then(function () { t.toast("HTML 已复制到剪贴板"); })
        .catch(function () { t.toast("复制失败", "error"); });
    });
    $("btn-export").addEventListener("click", function () { t.exportHTML(); });
    $("btn-help").addEventListener("click", function () { t.get("help-modal").classList.add("open"); });
    $("btn-fullscreen").addEventListener("click", function () {
      if (document.fullscreenElement) document.exitFullscreen().catch(function () {});
      else document.documentElement.requestFullscreen().catch(function () { t.toast("浏览器不允许全屏", "warn"); });
    });
    $("btn-clear-draft").addEventListener("click", function () { t.clearDraft(); });

    // 链接表单
    $("form-link").addEventListener("submit", function (e) { t.applyLink(e); });
    $("link-cancel").addEventListener("click", function () { t.closePops(); });
    $("link-remove").addEventListener("click", function () { t.removeLink(); });

    // Tab 切换
    t.qall(".rte-tabs").forEach(function (tabs) {
      tabs.querySelectorAll(".rte-tab").forEach(function (tab) {
        tab.addEventListener("click", function () {
          tabs.querySelectorAll(".rte-tab").forEach(function (x) { x.classList.remove("active"); });
          tab.classList.add("active");
          var form = tabs.closest(".rte-form");
          var kind = tab.getAttribute("data-tab");
          form.querySelectorAll("[data-pane]").forEach(function (p) {
            p.style.display = p.getAttribute("data-pane") === kind ? "" : "none";
          });
        });
      });
    });

    // 图片
    var imgDrop = $("img-drop");
    imgDrop.addEventListener("click", function () { $("img-file").click(); });
    imgDrop.addEventListener("dragover", function (e) { e.preventDefault(); imgDrop.style.borderColor = "var(--accent)"; });
    imgDrop.addEventListener("dragleave", function () { imgDrop.style.borderColor = ""; });
    imgDrop.addEventListener("drop", function (e) {
      e.preventDefault();
      imgDrop.style.borderColor = "";
      var f = e.dataTransfer.files[0];
      if (f && f.type.indexOf("image/") === 0) t.handleImageFile(f);
    });
    $("img-file").addEventListener("change", function () { var f = $("img-file").files[0]; if (f) t.handleImageFile(f); });
    $("form-image").addEventListener("submit", function (e) {
      e.preventDefault();
      var pending = $("img-file").files[0];
      if (pending) { t.handleImageFile(pending); t.closePops(); return; }
      var url = $("img-url").value.trim();
      if (!url) { t.toast("请输入图片链接或选择图片", "warn"); return; }
      t.insertImageUrl(url);
      t.closePops();
      $("img-url").value = "";
    });
    $("img-cancel").addEventListener("click", function () { t.closePops(); });

    // 视频
    var vidDrop = $("vid-drop");
    vidDrop.addEventListener("click", function () { $("vid-file").click(); });
    vidDrop.addEventListener("dragover", function (e) { e.preventDefault(); vidDrop.style.borderColor = "var(--accent)"; });
    vidDrop.addEventListener("dragleave", function () { vidDrop.style.borderColor = ""; });
    vidDrop.addEventListener("drop", function (e) {
      e.preventDefault();
      vidDrop.style.borderColor = "";
      var f = e.dataTransfer.files[0];
      if (f && f.type.indexOf("video/") === 0) t.handleVideoFile(f);
    });
    $("vid-file").addEventListener("change", function () { var f = $("vid-file").files[0]; if (f) t.handleVideoFile(f); });
    $("form-video").addEventListener("submit", function (e) {
      e.preventDefault();
      var pending = $("vid-file").files[0];
      if (pending) { t.handleVideoFile(pending); t.closePops(); return; }
      var url = $("vid-url").value.trim();
      if (!url) { t.toast("请输入视频链接", "warn"); return; }
      var parsed = t.parseVideoUrl(url);
      if (parsed.type === "iframe") t.insertVideoEmbed(parsed.src);
      else t.insertVideoSrc(parsed.src);
      t.closePops();
      $("vid-url").value = "";
    });
    $("vid-cancel").addEventListener("click", function () { t.closePops(); });

    // 表格
    $("form-table").addEventListener("submit", function (e) {
      e.preventDefault();
      var rows = Math.max(1, Math.min(30, parseInt($("table-rows").value, 10) || 3));
      var cols = Math.max(1, Math.min(12, parseInt($("table-cols").value, 10) || 3));
      t.insertTable(rows, cols, $("table-head").checked);
      t.closePops();
    });
    $("table-cancel").addEventListener("click", function () { t.closePops(); });

    // 编辑器事件
    t.editor.addEventListener("input", function () { t.afterChange(); });
    t.editor.addEventListener("keyup", function () { t.scheduleToolbar(); t.showTableBar(); });
    t.editor.addEventListener("mouseup", function (e) {
      t.scheduleToolbar();
      t.showTableBar();
      if (e.target && (e.target.tagName === "IMG" || e.target.tagName === "VIDEO")) t.selectMedia(e.target);
    });
    t.editor.addEventListener("click", function (e) {
      if (e.target && (e.target.tagName === "IMG" || e.target.classList.contains("rte-embed-video"))) {
        e.preventDefault();
        t.selectMedia(e.target);
      }
    });
    t.editor.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { t.clearMediaSel(); t.closePops(); t.closeBars(); }
      if (e.key === "Tab") { e.preventDefault(); if (e.shiftKey) t.exec("outdent"); else t.exec("indent"); }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); t.openLinkPop(); }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "h") { e.preventDefault(); t.get("help-modal").classList.add("open"); }
    });

    // 帮助
    $("help-close").addEventListener("click", function () { t.get("help-modal").classList.remove("open"); });
    $("help-gotit").addEventListener("click", function () { t.get("help-modal").classList.remove("open"); });
    t.get("help-modal").addEventListener("mousedown", function (e) {
      if (e.target === t.get("help-modal")) t.get("help-modal").classList.remove("open");
    });

    // 弹层内点击不冒泡关闭
    t.qall(".rte-pop").forEach(function (p) { p.addEventListener("mousedown", function (e) { e.stopPropagation(); }); });

    // 全局：点击空白关闭
    document.addEventListener("mousedown", this._docMouseDown = function (e) {
      if (!e.target.closest(".rte-pop") && !e.target.closest(".tb-btn")) t.closePops();
      if (!e.target.closest("#mediaBar") && !e.target.closest("#tableBar") && !e.target.closest(".rte-media-bar") && !e.target.closest(".rte-table-bar") &&
          !e.target.closest(".rte-selected")) t.clearMediaSel();
      if (!e.target.closest(".rte-table-bar") && !e.target.closest(".rte-selected") && !t.getCell()) t.tableBar.style.display = "none";
    });
    document.addEventListener("selectionchange", this._docSel = function () {
      t.scheduleToolbar();
      t.showTableBar();
    });
    document.addEventListener("keydown", this._docKey = function (e) {
      if (e.key === "Escape" && document.fullscreenElement) document.exitFullscreen().catch(function () {});
    });
  };

  /* ---------- 图片/视频弹层辅助 ---------- */
  YimuEditor.prototype.handleImageFile = function (f) {
    var t = this;
    if (f.type.indexOf("image/") !== 0) { t.toast("请选择图片文件", "warn"); return; }
    var size = f.size > 1024 * 1024 ? (f.size / 1024 / 1024).toFixed(1) + " MB" : Math.ceil(f.size / 1024) + " KB";
    t.get("img-prev-name").textContent = f.name;
    t.get("img-prev-meta").textContent = size;
    t.get("img-preview").style.display = "flex";
    var reader = new FileReader();
    reader.onload = function (e) { t.get("img-prev-thumb").src = e.target.result; };
    reader.readAsDataURL(f);
    t.uploadFile(f, "image", function (url) {
      t.insertImageUrl(url);
      t.closePops();
      t.resetImagePop();
    });
  };
  YimuEditor.prototype.handleVideoFile = function (f) {
    var t = this;
    if (f.type.indexOf("video/") !== 0) { t.toast("请选择视频文件", "warn"); return; }
    var size = f.size > 1024 * 1024 ? (f.size / 1024 / 1024).toFixed(1) + " MB" : Math.ceil(f.size / 1024) + " KB";
    t.get("vid-prev-name").textContent = f.name;
    t.get("vid-prev-meta").textContent = size;
    t.get("vid-preview").style.display = "flex";
    t.uploadFile(f, "video", function (url) {
      t.insertVideoSrc(url);
      t.closePops();
      t.resetVideoPop();
    });
  };
  YimuEditor.prototype.resetImagePop = function () {
    this.get("img-file").value = "";
    this.get("img-preview").style.display = "none";
  };
  YimuEditor.prototype.resetVideoPop = function () {
    this.get("vid-file").value = "";
    this.get("vid-preview").style.display = "none";
  };
  YimuEditor.prototype.openImagePop = function () {
    var t = this;
    t.resetImagePop();
    t.get("img-url").value = "";
    t.get("img-drop").style.borderColor = "";
    t.showPop(t.get("pop-image"), t.get("cmd-image"));
  };
  YimuEditor.prototype.openVideoPop = function () {
    var t = this;
    t.resetVideoPop();
    t.get("vid-url").value = "";
    t.get("vid-drop").style.borderColor = "";
    t.showPop(t.get("pop-video"), t.get("cmd-video"));
  };

  /* ---------- 导出 ---------- */
  YimuEditor.prototype.exportHTML = function () {
    var t = this;
    var html = "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"UTF-8\"><title>导出内容</title><style>" +
      "body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;max-width:860px;margin:40px auto;padding:0 24px;line-height:1.75;color:#23221f}" +
      "h1,h2,h3,h4{line-height:1.35;font-weight:700}h2{border-bottom:1px solid #e5e5e5;padding-bottom:8px}" +
      "blockquote{border-left:3px solid #0f766e;margin:1em 0;padding:.4em 0 .4em 1.1em;color:#555;background:#f7f6f3}" +
      "pre{background:#f0efec;border-radius:8px;padding:14px 16px;overflow-x:auto;font-family:Consolas,monospace;font-size:13.5px}" +
      "img{max-width:100%;border-radius:6px}video{max-width:100%}table{border-collapse:collapse;margin:1em auto}td,th{border:1px solid #ccc;padding:8px 12px}" +
      ".rte-embed-video{position:relative;width:100%;padding-top:56.25%;background:#000;border-radius:6px;overflow:hidden}.rte-embed-video iframe{position:absolute;inset:0;width:100%;height:100%;border:0}" +
      "</style></head><body>" + t.editor.innerHTML + "</body></html>";
    var blob = new Blob([html], { type: "text/html;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "article-" + Date.now() + ".html";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 3000);
    t.toast("已导出为 HTML 文件");
  };

  /* ---------- Toast ---------- */
  YimuEditor.prototype.toast = function (msg, type) {
    var t = this;
    var el = document.createElement("div");
    el.className = "rte-toast" + (type ? " " + type : "");
    el.textContent = msg;
    t.toastWrap.appendChild(el);
    setTimeout(function () {
      el.style.opacity = "0";
      el.style.transition = "opacity .3s";
      setTimeout(function () { el.remove(); }, 320);
    }, 2600);
  };

  /* ============================================================
     对外 API
     ============================================================ */
  YimuEditor.prototype.getHTML = function () { return this.inSource ? this.source.value : this.editor.innerHTML; };
  YimuEditor.prototype.setHTML = function (html) {
    if (this.inSource) this.source.value = html;
    else this.editor.innerHTML = html;
    this.afterChange();
    return this;
  };
  YimuEditor.prototype.getText = function () { return this.editor.innerText || this.editor.textContent || ""; };
  YimuEditor.prototype.isEmpty = function () { return !(this.editor.textContent || "").trim(); };
  YimuEditor.prototype.clear = function () { this.editor.innerHTML = ""; this.afterChange(); return this; };
  YimuEditor.prototype.insertHTML = function (html) {
    this.editor.focus();
    document.execCommand("insertHTML", false, html);
    this.afterChange();
    return this;
  };
  YimuEditor.prototype.execCommand = function (cmd, value) { this.exec(cmd, value); return this; };
  YimuEditor.prototype.setSourceMode = function (on) { if (!!on !== this.inSource) this.toggleSource(); return this; };
  YimuEditor.prototype.focus = function () { this.editor.focus(); return this; };
  YimuEditor.prototype.config = function (opts) {
    Object.keys(opts || {}).forEach(function (k) { this.opts[k] = opts[k]; }, this);
    if (opts && opts.theme) this.applyTheme(opts.theme);
    if (opts && opts.stickyToolbar !== undefined) this.initSticky();
    return this;
  };
  YimuEditor.prototype.onChange = function (fn) { this.opts.onChange = fn; return this; };
  YimuEditor.prototype.getConfig = function () { return Object.assign({}, this.opts); };

  /* ---------- 工具栏吸顶 ---------- */
  YimuEditor.prototype.initSticky = function () {
    var t = this;
    // 先清理旧状态，保证可重复调用（config 运行时切换）
    if (t._stickyBound) {
      window.removeEventListener("scroll", t._stickyOnScroll);
      t._stickyBound = false;
    }
    t.app.classList.remove("rte-sticky");
    if (t.toolbarEl) t.toolbarEl.classList.remove("rte-stuck");
    var enable = t.opts.stickyToolbar !== false && t.opts.toolbar !== false;
    if (!enable) return;
    t.toolbarEl = t.toolbarEl || t.q(".rte-toolbar");
    if (!t.toolbarEl) return;
    t.app.classList.add("rte-sticky");
    t._stickyOnScroll = function () {
      if (t._stickyRaf) return;
      t._stickyRaf = requestAnimationFrame(function () {
        t._stickyRaf = null;
        if (!t.toolbarEl) return;
        var r = t.toolbarEl.getBoundingClientRect();
        t.toolbarEl.classList.toggle("rte-stuck", r.top <= 0);
      });
    };
    window.addEventListener("scroll", t._stickyOnScroll, { passive: true });
    t._stickyBound = true;
    t._stickyOnScroll(); // 初始状态判定
  };

  YimuEditor.prototype.destroy = function () {
    var t = this;
    document.removeEventListener("mousedown", t._docMouseDown);
    document.removeEventListener("selectionchange", t._docSel);
    document.removeEventListener("keydown", t._docKey);
    if (t._stickyBound) window.removeEventListener("scroll", t._stickyOnScroll);
    if (t._stickyRaf) cancelAnimationFrame(t._stickyRaf);
    clearTimeout(t._saveTimer);
    clearTimeout(t._tbTimer);
    t.app.remove();
    t.el.innerHTML = "";
  };
  YimuEditor.version = VERSION;

  /* ============================================================
     导出
     ============================================================ */
  global.YimuEditor = YimuEditor;
  global.RichTextEditor = YimuEditor; // 兼容旧名称的别名
  if (typeof module !== "undefined" && module.exports) module.exports = YimuEditor;

})(typeof window !== "undefined" ? window : this);
