# SPDX-License-Identifier: BUSL-1.1
"""通知推送：可插拔 provider 体系。

R5-1 背景
---------
此前本模块只有钉钉一条通道，且 webhook 只写在**运营自己的** ``.env`` 里，
用户侧零推送能力——用户注册后没有任何触达，付费转化、额度提醒、
召回全靠人工。本批次引入 provider 概念，把「通知」拆成两类受众：

- **运营侧**（``send``）：钉钉机器人保留原样，运营自己看工单/审核卡片。
- **用户侧**（``notify_user``）：新增邮件通道（标准库 ``smtplib``），
  面向注册用户本人，承载注册欢迎、额度召回、邀请奖励等触点。

设计要点
--------
1. **provider 可插拔**：``PROVIDERS`` 注册表按名字取实现，新增微信服务号
   只需再注册一个 provider，不必改调用方。
2. **无配置优雅降级**：任何 provider 未配置时返回 ``{"ok": False,
   "skipped": True, ...}`` 而**不抛异常**——通知是旁路能力，绝不能因为
   邮件服务器没配就把用户的主流程带崩。
3. **用户侧通道必须拿到收件地址**：没有邮箱就记一条待发队列（落库），
   等用户补全邮箱后再由后续任务补发，避免静默丢消息。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import smtplib
import time
import urllib.parse
from email.message import EmailMessage
from typing import Callable

import httpx

from core.llm import load_env

# ---------------------------------------------------------------------------
# 运营侧：钉钉自定义机器人（webhook + 加签）
# ---------------------------------------------------------------------------


def configured() -> bool:
    """运营侧钉钉机器人是否已配置。"""
    env = load_env()
    return bool(env.get("DINGTALK_WEBHOOK", "").strip())


def send(title: str, markdown_text: str) -> dict:
    """推送给运营（钉钉）。保持既有签名与返回结构不变。"""
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


# ---------------------------------------------------------------------------
# 用户侧：provider 注册表
# ---------------------------------------------------------------------------

#: provider 名 → 发送函数 (to, subject, body) -> dict
PROVIDERS: dict[str, Callable[[str, str, str], dict]] = {}


def register_provider(name: str):
    """provider 注册装饰器。新增通道（如微信服务号）只需套一层。"""

    def _wrap(fn: Callable[[str, str, str], dict]) -> Callable[[str, str, str], dict]:
        PROVIDERS[name] = fn
        return fn

    return _wrap


def email_configured() -> bool:
    """邮件通道是否具备最小可用配置（主机 + 发件人）。"""
    env = load_env()
    return bool(env.get("SMTP_HOST", "").strip() and env.get("SMTP_FROM", "").strip())


def available_providers() -> list[str]:
    """当前实际可用的用户侧通道名列表（未配置的不算）。"""
    if email_configured():
        return [n for n in PROVIDERS if n != "email"]
    return []


@register_provider("email")
def _send_email(to: str, subject: str, body: str) -> dict:
    """邮件通道：标准库 smtplib，支持明文 / STARTTLS / SSL 三种接入方式。

    配置（.env）::

        SMTP_HOST=smtp.example.com
        SMTP_PORT=465
        SMTP_USER=notify@example.com
        SMTP_PASSWORD=***
        SMTP_FROM=notify@example.com
        SMTP_SECURITY=ssl   # ssl / starttls / none（默认按端口猜）

    未配置时返回 skipped 而不抛异常——邮件只是触达手段，缺失不应阻断主流程。
    """
    env = load_env()
    host = env.get("SMTP_HOST", "").strip()
    sender = env.get("SMTP_FROM", "").strip()
    if not host or not sender:
        return {"ok": False, "skipped": True, "error": "邮件通道未配置"}

    port = int(env.get("SMTP_PORT", "465").strip() or 465)
    security = env.get("SMTP_SECURITY", "").strip().lower()
    if not security:
        security = "ssl" if port == 465 else "starttls"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body)

    try:
        if security == "ssl":
            with smtplib.SMTP_SSL(host, port, timeout=20) as srv:
                _smtp_auth(srv, env)
                srv.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as srv:
                if security == "starttls":
                    srv.starttls()
                _smtp_auth(srv, env)
                srv.send_message(msg)
        return {"ok": True, "provider": "email", "to": _mask_email(to)}
    except Exception as e:  # 网络/认证异常一律吞掉，返回结构化失败
        return {"ok": False, "provider": "email", "error": str(e)[:200]}


def _smtp_auth(srv, env) -> None:
    """按配置决定是否登录 SMTP（部分内网中继无需认证）。"""
    user = env.get("SMTP_USER", "").strip()
    pwd = env.get("SMTP_PASSWORD", "").strip()
    if user and pwd:
        srv.login(user, pwd)


def _mask_email(addr: str) -> str:
    """邮箱脱敏：a**@b.com。日志与返回值里不出现完整地址。"""
    addr = (addr or "").strip()
    if "@" not in addr:
        return "***"
    name, domain = addr.split("@", 1)
    head = name[:1] if name else ""
    return f"{head}**@{domain}"


# ---------------------------------------------------------------------------
# 用户侧统一入口
# ---------------------------------------------------------------------------


def notify_user(to: str, subject: str, body: str,
                provider: str = "email") -> dict:
    """给用户本人发一条通知。

    Args:
        to: 收件地址（邮件通道为邮箱）。
        subject: 标题 / 微信通道对应消息摘要。
        body: 正文（纯文本）。
        provider: 指定通道名；默认 email。

    Returns:
        ``{"ok": bool, ...}``。未配置通道时 ``ok=False, skipped=True``——
        调用方据此判断「没发出去」，但不视为异常。
    """
    if not (to or "").strip():
        return {"ok": False, "skipped": True, "error": "缺少收件地址"}
    fn = PROVIDERS.get(provider)
    if fn is None:
        return {"ok": False, "skipped": True, "error": f"未知通知通道: {provider}"}
    try:
        return fn(to.strip(), subject, body)
    except Exception as e:  # provider 自身异常也不许上抛
        return {"ok": False, "error": str(e)[:200]}