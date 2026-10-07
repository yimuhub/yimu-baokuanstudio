"""优雅水印引擎 (Aesthetic Watermark Engine)。

支持在生成的图文排版长图、信息卡片、封面图与视频帧上压印高质感品牌印记。
核心原则：绝不强制，100% 自由控制，在免费版与付费版中均支持全局与单篇一键自由开启/关闭。
"""
import logging
from pathlib import Path
from typing import Optional, Tuple, Union
import yaml

logger = logging.getLogger(__name__)
BASE = Path(__file__).resolve().parent.parent


def get_watermark_config() -> dict:
    """读取水印配置。"""
    cfg_file = BASE / "config.yaml"
    default_cfg = {
        "enabled": True,
        "text": "Designed with 一幕 YIMU",
        "position": "bottom-right",  # bottom-right, bottom-center, top-right
        "opacity": 0.45,
        "font_size": 16,
        "show_on_cards": True,
        "show_on_cover": True,
        "show_on_video": True
    }
    if cfg_file.exists():
        try:
            with open(cfg_file, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                wm = data.get("watermark", {})
                default_cfg.update(wm)
        except Exception:
            pass
    return default_cfg


def is_watermark_enabled() -> bool:
    return bool(get_watermark_config().get("enabled", False))


def apply_image_watermark(
    img_path: Union[str, Path],
    out_path: Optional[Union[str, Path]] = None,
    text: Optional[str] = None,
    force: bool = False
) -> bool:
    """为目标图片添加优雅品牌水印。若全局未启用且未强制，则直接略过。"""
    cfg = get_watermark_config()
    if not cfg.get("enabled", False) and not force:
        return False

    target_text = (text or cfg.get("text", "Designed with 一幕 YIMU")).strip()
    if not target_text:
        return False

    src_p = Path(img_path)
    if not src_p.exists():
        return False

    dest_p = Path(out_path) if out_path else src_p

    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.open(src_p).convert("RGBA")
        w, h = img.size

        # 创建半透明绘制图层
        overlay = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)

        # 字体适配
        font_size = max(13, min(int(w * 0.022), 24))
        font = None
        for fpath in [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fontsrial.ttf"
        ]:
            if Path(fpath).exists():
                try:
                    font = ImageFont.truetype(fpath, font_size)
                    break
                except Exception:
                    continue
        if not font:
            font = ImageFont.load_default()

        # 计算文字尺寸
        bbox = draw.textbbox((0, 0), target_text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        # 胶囊药丸背景宽度与位置
        pad_x, pad_y = 12, 6
        pill_w = tw + pad_x * 2
        pill_h = th + pad_y * 2
        margin = max(16, int(w * 0.03))

        pos = cfg.get("position", "bottom-right")
        if pos == "bottom-right":
            x1, y1 = w - margin - pill_w, h - margin - pill_h
        elif pos == "bottom-center":
            x1, y1 = (w - pill_w) // 2, h - margin - pill_h
        else:
            x1, y1 = w - margin - pill_w, margin

        x2, y2 = x1 + pill_w, y1 + pill_h

        # 绘制磨砂质感深色胶囊底块
        draw.rounded_rectangle([(x1, y1), (x2, y2)], radius=pill_h // 2, fill=(0, 0, 0, 90))
        # 绘制极简小点和文字
        draw.text((x1 + pad_x, y1 + pad_y), target_text, fill=(255, 255, 255, 200), font=font)

        # 合成图层
        watermarked = Image.alpha_composite(img, overlay).convert("RGB")
        dest_p.parent.mkdir(parents=True, exist_ok=True)
        watermarked.save(dest_p, quality=95)
        logger.info(f"[Watermark] 成功为图片注入优雅水印: {dest_p.name}")
        return True
    except Exception as e:
        logger.warning(f"[Watermark] 压印水印失败 (安全略过): {e}")
        return False
