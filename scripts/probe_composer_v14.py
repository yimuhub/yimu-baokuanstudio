"""V14 输入框端到端走查：附件上传、模型直选、提示词优化、发送键尺寸。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/Users/czmj/WorkBuddy/Worktrees/yimu-baokuanstudio/main-2c356311/dist/bundle_mac/runtime/site-packages")
from playwright.sync_api import sync_playwright  # noqa: E402

OUT = Path("/tmp/lmaudit")
BASE = "http://127.0.0.1:8790/"


def main() -> int:
    report = {}
    with sync_playwright() as p:
        b = p.chromium.launch(
            headless=True,
            executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            args=["--no-sandbox"],
        )
        ctx = b.new_context(viewport={"width": 1512, "height": 950})
        ctx.add_init_script("localStorage.setItem('yimu_ui_theme_mode','light');")
        pg = ctx.new_page()
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(BASE, wait_until="domcontentloaded")
        pg.wait_for_timeout(4000)

        # 1. 发送键几何
        report["send_box"] = pg.evaluate(
            """() => {
                const b = document.getElementById('btn-copilot-send');
                const r = b.getBoundingClientRect();
                const cs = getComputedStyle(b);
                return {w: Math.round(r.width), h: Math.round(r.height),
                        radius: cs.borderRadius, display: cs.display};
            }"""
        )

        # 2. 模型下拉是否填充
        report["model_options"] = pg.evaluate(
            """() => {
                const s = document.getElementById('copilot-model-quick');
                return {count: s ? s.options.length : -1,
                        labels: s ? Array.from(s.options).slice(0, 6).map(o => o.textContent) : [],
                        groups: s ? Array.from(s.querySelectorAll('optgroup')).map(g => g.label) : []};
            }"""
        )

        # 3. 附件上传（真实走 /api/copilot/attach）
        pg.set_input_files("#copilot-file-input", "/tmp/demo_attach.docx")
        pg.wait_for_timeout(1800)
        report["attach"] = pg.evaluate(
            """() => {
                const chips = Array.from(document.querySelectorAll('#copilot-attach-list .cb-attach'));
                const list = document.getElementById('copilot-attach-list');
                return {
                    count: chips.length,
                    visible: list ? getComputedStyle(list).display : null,
                    html: chips.map(c => c.textContent.trim()).slice(0, 3),
                    hasErr: chips.some(c => c.classList.contains('err'))
                };
            }"""
        )
        pg.screenshot(path=str(OUT / "composer_attach.png"))

        # 4. 提示词优化（等真实返回，最多 30s）
        pg.fill("#copilot-input", "写一篇讲苹果 AI 的笔记")
        pg.click("#copilot-polish-btn")
        val = ""
        for _ in range(60):
            pg.wait_for_timeout(500)
            val = pg.input_value("#copilot-input")
            if len(val) > 40:
                break
        report["polish"] = {"len": len(val), "head": val[:60]}
        pg.screenshot(path=str(OUT / "composer_polish.png"))

        # 5. 附件上下文拼接
        report["ctx"] = pg.evaluate("() => buildCopilotAttachmentContext().slice(0, 160)")

        report["console_errors"] = errs[:5]
        b.close()
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
