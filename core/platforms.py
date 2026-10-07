"""平台规则包：每个平台的图文/视频/音频规格与发布规范。

生成内容时按包自动适配——这是「一篇母版 → 全平台全形态」的核心。
新平台：在 PACKS 里加一个条目即可。
"""

PACKS = {
    "wechat_mp": {
        "label": "公众号",
        "video": {"aspect": "16:9", "clip": 5, "default_seconds": 60,
                  "style": "深度讲解，节奏沉稳", "bgm_volume": 0.15},
        "audio": {"voice": "zh-CN-YunxiNeural", "rate": "1.0",
                  "style": "领读/播客感，语速平缓"},
        "publish_tips": "排版用主题渲染后复制；封面图 2.35:1 裁切效果最佳",
    },
    "xhs": {
        "label": "小红书",
        "video": {"aspect": "9:16", "clip": 3, "default_seconds": 15,
                  "style": "快节奏口播，前3秒钩子", "bgm_volume": 0.2},
        "audio": {"voice": "zh-CN-XiaoxiaoNeural", "rate": "1.1",
                  "style": "闺蜜分享感，轻快"},
        "publish_tips": "卡片图 3:4；正文 ≤1000 字；标签 5-8 个",
    },
    "toutiao": {
        "label": "今日头条",
        "video": {"aspect": "16:9", "clip": 4, "default_seconds": 45,
                  "style": "资讯体，信息密度高", "bgm_volume": 0.15},
        "audio": {"voice": "zh-CN-YunyangNeural", "rate": "1.05",
                  "style": "新闻播报感"},
        "publish_tips": "标题带地域/数字钩子；正文 Markdown 直贴",
    },
    "douyin": {
        "label": "抖音",
        "video": {"aspect": "9:16", "clip": 2, "default_seconds": 20,
                  "style": "极快节奏，2秒一切，前1秒必须有冲突", "bgm_volume": 0.25},
        "audio": {"voice": "zh-CN-XiaoxiaoNeural", "rate": "1.15",
                  "style": "高能快节奏"},
        "publish_tips": "视频 ≤60s；封面=首帧；前 1 秒决定完播率",
    },
    "shipinhao": {
        "label": "视频号",
        "video": {"aspect": "9:16", "clip": 3, "default_seconds": 30,
                  "style": "口播为主，节奏中等，适合知识分享", "bgm_volume": 0.15},
        "audio": {"voice": "zh-CN-XiaoyiNeural", "rate": "1.05",
                  "style": "亲切自然"},
        "publish_tips": "视频号用户偏中年：语速稍慢、字幕加大",
    },
    "bili": {
        "label": "B站",
        "video": {"aspect": "16:9", "clip": 5, "default_seconds": 90,
                  "style": "知识区风格，讲解+图文穿插", "bgm_volume": 0.12},
        "audio": {"voice": "zh-CN-YunxiNeural", "rate": "1.0",
                  "style": "轻松科普感"},
        "publish_tips": "横版 16:9；三连引导放片尾",
    },
}

DEFAULT_PACK = "toutiao"


def get_pack(platform: str) -> dict:
    return PACKS.get(platform, PACKS[DEFAULT_PACK])


def list_packs() -> dict:
    return {k: {"label": v["label"],
                "video": v["video"], "audio": v["audio"],
                "publish_tips": v["publish_tips"]}
            for k, v in PACKS.items()}
