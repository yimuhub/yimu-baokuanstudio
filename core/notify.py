"""通知推送：钉钉自定义机器人（webhook+加签）。配置在 .env：
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxx
DINGTALK_SECRET=SECxxx（机器人安全设置选"加签"时填）
"""
import base64
import hashlib
import hmac
import time
import urllib.parse

import httpx

from core.llm import load_env


def configured() -> bool:
    env = load_env()
    return bool(env.get("DINGTALK_WEBHOOK", "").strip())


def send(title: str, markdown_text: str) -> dict:
    env = load_env()
    url = env.get("DINGTALK_WEBHOOK", "").strip()
    if not url:
        return {"ok": False, "error": "未配置钉钉机器人"}
    secret = env.get("DINGTALK_SECRET", "").strip()
    if secret:
        ts = str(round(time.time() * 1000))
        sign = base64.b64encode(hmac.new(secret.encode(), f"{ts}\n{secret}".encode(),
                                         hashlib.sha256).digest()).decode()
        url += f"&timestamp={ts}&sign={urllib.parse.quote_plus(sign)}"
    try:
        r = httpx.post(url, json={"msgtype": "markdown",
                                  "markdown": {"title": title, "text": markdown_text}},
                       timeout=15)
        data = r.json()
        return {"ok": data.get("errcode") == 0, "resp": str(data)[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
