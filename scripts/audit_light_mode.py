# SPDX-License-Identifier: BUSL-1.1
"""亮色模式全站审计：渲染每个功能页，采集对比度/背景/边框异常。"""
import json
import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # 宿主 sitecustomize 可能清掉 PYTHONPATH，这里显式补
    for cand in (
        Path(__file__).resolve().parent.parent / "dist/bundle_mac/runtime/site-packages",
        Path(__file__).resolve().parent.parent
        / "dist/bundle_mac/runtime/lib/python3.11/site-packages",
    ):
        if cand.is_dir():
            sys.path.insert(0, str(cand))
    from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8790/"
OUT = Path("/tmp/lmaudit")
if not OUT.is_dir():
    OUT.mkdir(parents=True)

PAGES = ["dashboard", "inspire", "drafts", "studio", "console", "pricing", "profile"]

AUDIT_JS = r"""
() => {
  const px = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map(s => parseFloat(s.trim()));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const ratio = (a, b) => {
    const l1 = lum(a), l2 = lum(b);
    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
  };
  const blend = (fg, bg) => ({
    r: fg.r * fg.a + bg.r * (1 - fg.a),
    g: fg.g * fg.a + bg.g * (1 - fg.a),
    b: fg.b * fg.a + bg.b * (1 - fg.a),
    a: 1
  });

  const effBg = (el) => {
    let n = el;
    let acc = null;
    while (n && n.nodeType === 1) {
      const cs = getComputedStyle(n);
      const c = px(cs.backgroundColor);
      if (c && c.a > 0.01) {
        acc = acc ? blend(acc, c) : c;
        if (acc.a >= 0.999) return { color: acc, img: null };
      }
      if (cs.backgroundImage && cs.backgroundImage !== 'none') {
        return { color: acc || { r: 248, g: 250, b: 252, a: 1 }, img: cs.backgroundImage };
      }
      n = n.parentElement;
    }
    return { color: acc || { r: 248, g: 250, b: 252, a: 1 }, img: null };
  };

  const vis = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return null;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) < 0.05) return null;
    if (r.bottom < -20 || r.top > innerHeight + 400) return null;
    return { r, cs };
  };

  const sel = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    if (el.className && typeof el.className === 'string') {
      s += '.' + el.className.trim().split(/\s+/).slice(0, 3).join('.');
    }
    return s;
  };

  const textIssues = [];
  const darkBlocks = [];
  const borderIssues = [];

  const all = document.querySelectorAll('body *');
  for (const el of all) {
    const v = vis(el);
    if (!v) continue;
    const { cs } = v;
    const bg = effBg(el);

    // 文本对比度
    const ownText = Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim().length > 0);
    if (ownText && !bg.img) {
      const fg0 = px(cs.color);
      if (fg0) {
        const fg = fg0.a < 1 ? blend(fg0, bg.color) : fg0;
        const cr = ratio(fg, bg.color);
        const size = parseFloat(cs.fontSize);
        const bold = parseInt(cs.fontWeight, 10) >= 600;
        const large = size >= 24 || (size >= 18.66 && bold);
        const need = large ? 3.0 : 4.5;
        if (cr < need && el.textContent.trim().length) {
          textIssues.push({
            s: sel(el),
            text: el.textContent.trim().slice(0, 40),
            fg: cs.color,
            bg: `rgb(${Math.round(bg.color.r)},${Math.round(bg.color.g)},${Math.round(bg.color.b)})`,
            ratio: Math.round(cr * 100) / 100,
            size,
            need
          });
        }
      }
    }

    // 亮色模式下的深色块
    const ob = px(cs.backgroundColor);
    const area = v.r.width * v.r.height;
    if (ob && ob.a > 0.5 && area > 3000) {
      const l = lum(ob);
      if (l < 0.28) {
        darkBlocks.push({
          s: sel(el),
          bg: cs.backgroundColor,
          area: Math.round(area),
          w: Math.round(v.r.width),
          h: Math.round(v.r.height)
        });
      }
    }

    // 边框对比度（越浅越看不见）
    const bw = parseFloat(cs.borderTopWidth);
    if (bw > 0 && cs.borderTopStyle !== 'none') {
      const bc = px(cs.borderTopColor);
      if (bc && bc.a > 0.3 && !bg.img) {
        const cr = ratio(bc, bg.color);
        if (cr < 1.15 && area > 1500) {
          borderIssues.push({ s: sel(el), color: cs.borderTopColor, ratio: Math.round(cr * 100) / 100, w: Math.round(v.r.width) });
        }
      }
    }
  }

  // 硬编码深色内联样式扫描
  const inlineDark = [];
  for (const el of document.querySelectorAll('[style]')) {
    const st = el.getAttribute('style') || '';
    const m = st.match(/(?:background|background-color)\s*:\s*([^;]+)/gi) || [];
    for (const decl of m) {
      const c = decl.split(':')[1] || '';
      if (/(#0[0-9a-f]{2,5}|#1[0-9a-f]{2,5}|rgba?\(\s*(?:[0-9]|[1-4][0-9])\s*,\s*(?:[0-9]|[1-4][0-9])\s*,\s*(?:[0-9]|[1-4][0-9]))/i.test(c)) {
        const v = vis(el);
        if (v) inlineDark.push({ s: sel(el), decl: decl.trim().slice(0, 70) });
      }
    }
  }

  const dedupe = (arr, key) => {
    const seen = new Set();
    return arr.filter(o => {
      const k = o.s + '|' + o[key];
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });
  };

  return {
    textIssues: dedupe(textIssues, 'text').slice(0, 60),
    darkBlocks: dedupe(darkBlocks, 'bg').slice(0, 40),
    borderIssues: dedupe(borderIssues, 'color').slice(0, 40),
    inlineDark: dedupe(inlineDark, 'decl').slice(0, 60),
    total: all.length
  };
}
"""


def _chrome() -> str | None:
    """优先用随包 Chrome for Testing，避免依赖 playwright 自带内核是否已下载。"""
    root = Path(__file__).resolve().parent.parent
    cands = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        root / "dist/bundle_mac/chromium/chrome-mac-arm64/Google Chrome for Testing.app"
        "/Contents/MacOS/Google Chrome for Testing",
    ]
    for c in cands:
        if c.is_file():
            return str(c)
    return None


def main() -> int:
    report = {}
    exe = _chrome()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path=exe,
            args=["--force-color-profile=srgb", "--no-sandbox"],
        )
        ctx = browser.new_context(viewport={"width": 1512, "height": 950}, device_scale_factor=1)
        ctx.add_init_script("localStorage.setItem('yimu_ui_theme_mode','light');")
        page = ctx.new_page()
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_timeout(4500)
        theme = page.get_attribute("html", "data-theme")
        print("theme =", theme)
        page.screenshot(path=str(OUT / "_home.png"))

        # 中栏对话（默认）
        report["_home"] = page.evaluate(AUDIT_JS)

        for key in PAGES:
            clicked = page.evaluate(
                """(k) => {
                    const it = document.querySelector('.nav-item[data-p="' + k + '"]');
                    if (!it) return false;
                    it.click();
                    return true;
                }""",
                key,
            )
            if not clicked:
                print(f"[skip] {key} 无导航项")
                continue
            page.wait_for_timeout(2600)
            stage = page.get_attribute("body", "data-stage")
            page.screenshot(path=str(OUT / f"{key}.png"))
            report[key] = page.evaluate(AUDIT_JS)
            report[key]["stage"] = stage
            print(f"[ok] {key} stage={stage}")

        # 全屏舞台下的一个复杂页
        page.evaluate("""() => {
            const it = document.querySelector('.nav-item[data-p="console"]');
            if (it) it.click();
        }""")
        page.wait_for_timeout(1200)
        page.evaluate("""() => { const b = document.getElementById('stageFull'); if (b) b.click(); }""")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "console_full.png"))
        report["console_full"] = page.evaluate(AUDIT_JS)

        # 设置弹窗
        page.evaluate("""() => {
            const b = document.getElementById('btn-theme-mode-toggle');
            if (b) b.click();
        }""")
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "after_toggle.png"))

        browser.close()

    Path("/tmp/lmaudit.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    for name, data in report.items():
        if not isinstance(data, dict) or "textIssues" not in data:
            continue
        print(
            f"{name:14s} 低对比文字 {len(data['textIssues']):3d} | 深色块 {len(data['darkBlocks']):3d} "
            f"| 边框过浅 {len(data['borderIssues']):3d} | 内联深色 {len(data['inlineDark']):3d}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
