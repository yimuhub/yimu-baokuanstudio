# SPDX-License-Identifier: BUSL-1.1
"""外呼 URL 安全闸（SSRF 防护）：用户可控 URL 一律先过 assert_safe_url。

🔴 为什么需要它（v15.9.8 整改）：
   服务端存在「用户填一个 URL，后端直接发请求」的功能点（声音克隆测试、
   全网抓取等）。攻击者把 URL 填成 `http://169.254.169.254/latest/meta-data/`
   或 `http://127.0.0.1:8790/api/...`，就能借服务器的网络位置：
   1. 摸云元数据接口（窃取临时凭证 / RAM 角色）；
   2. 探内网与回环端口（本机主服务、xhs-mcp、MediaCrawler 都在环回上）；
   3. 打内网管理面（路由器 / 数据库）。
   这类「服务端代请求」漏洞就是 SSRF，必须在校验和抓取前拒绝私网目标。

判定口径：
- scheme 仅允许 http / https；
- socket 解析出**全部** A / AAAA 记录逐个校验（只查第一个会被
  「第一条公网、第二条私网」的 DNS 应答绕过）；
- 拒绝私网段：10/8、172.16/12、192.168/16、127/8、169.254/16（链路本地 +
  云元数据 169.254.169.254）、100.64/10（CGNAT）、0.0.0.0/8、::1、fc00::/7、
  fe80::/10，以及 IPv4 映射 / 兼容形态的 IPv6（::ffff:10.0.0.1 这类写法
  同样会被折算成私网 IPv4 后拒绝）。

allow_private 缺省规则（单机桌面 vs 多用户服务器）：
- 未开启 ``YIMU_MULTIUSER`` → 单机桌面模式，环回/私网放行（用户连 Ollama、
  本地 xhs-mcp 都是合法场景，不能一刀切）；
- 开启 ``YIMU_MULTIUSER`` → 多用户服务器，**强制拒绝**私网目标：请求来源
  是不可信的注册用户，放行等于把内网拓扑暴露给他们。
  显式传 allow_private=True/False 可覆盖缺省（仅限平台自用的本地服务，
  如 core.search 的 xhs-mcp 固定端点）。
"""
from __future__ import annotations

import ipaddress
import logging
import os
import socket
import urllib.parse

logger = logging.getLogger(__name__)

#: 允许的 scheme 白名单（file/ftp/gopher 等一律拒绝）
_ALLOWED_SCHEMES = ("http", "https")

#: 私网 / 保留网段清单（v4 与 v6 成对给出）
_PRIVATE_V4_NETS = (
    ipaddress.ip_network("0.0.0.0/8"),         # 未指定地址（含 0.0.0.0）
    ipaddress.ip_network("10.0.0.0/8"),        # RFC1918 A 类
    ipaddress.ip_network("100.64.0.0/10"),     # 运营商级 NAT（CGNAT）
    ipaddress.ip_network("127.0.0.0/8"),       # 环回
    ipaddress.ip_network("169.254.0.0/16"),    # 链路本地（含云元数据 169.254.169.254）
    ipaddress.ip_network("172.16.0.0/12"),     # RFC1918 B 类
    ipaddress.ip_network("192.0.0.0/24"),      # IETF 协议保留
    ipaddress.ip_network("192.168.0.0/16"),    # RFC1918 C 类
    ipaddress.ip_network("198.18.0.0/15"),     # 基准测试保留
)
_PRIVATE_V6_NETS = (
    ipaddress.ip_network("::1/128"),           # IPv6 环回
    ipaddress.ip_network("fc00::/7"),          # ULA 私有地址
    ipaddress.ip_network("fe80::/10"),         # IPv6 链路本地
)


class UnsafeURLError(ValueError):
    """目标 URL 未通过安全校验（携带可直接展示给用户的中文原因）。"""


#: 永久黑名单：无论单机/多用户、无论 allow_private 取什么值都拒绝。
#: why：云元数据端点（AWS/GCP/阿里云/腾讯云同段）在任何合法业务里都不该是
#: 用户填写的目标；桌面机不会跑元数据服务，放行它只服务于 SSRF 探测。
_HARD_DENY_IPS = frozenset({"169.254.169.254"})


def multiuser_enabled() -> bool:
    """是否多用户服务器模式（与 web.admin / web.routers.ops 同一判定口径）。"""
    return (os.environ.get("YIMU_MULTIUSER") or "").strip().lower() in ("1", "true", "yes")


def _is_private_ip(ip: ipaddress._BaseAddress) -> bool:
    """按网段清单判断是否私网 / 保留地址。

    为什么不用 ip.is_private 一把梭：Python 的 is_private 在不同版本对
    ::ffff:0:0/96（IPv4 映射段）的覆盖不一致，显式列网段行为可控、可测。
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # ::ffff:10.0.0.1 → 10.0.0.1，按 IPv4 规则再判一次
    if isinstance(ip, ipaddress.IPv4Address):
        return any(ip in net for net in _PRIVATE_V4_NETS)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.is_loopback or ip.is_link_local:
            return True
        return any(ip in net for net in _PRIVATE_V6_NETS)
    return True  # 未知类型按最保守处理


def _resolve_all_ips(host: str) -> list[str]:
    """解析主机名的全部 A / AAAA 记录。

    为什么不用 socket.gethostbyname：它只返回第一个 IPv4，
    攻击者可以用「多条记录、一条公网一条私网」的 DNS 应答绕过单点校验。
    """
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return [info[4][0] for info in infos]


def assert_safe_url(url: str, allow_private: bool | None = None) -> str:
    """校验外呼 URL 安全性；不通过抛 :class:`UnsafeURLError`，通过返回原 URL。

    Args:
        url: 用户可控的完整 URL（含 scheme）。
        allow_private: None=按部署模式自动判定（单机放行私网/多用户强制拒绝）；
            True/False 显式覆盖（仅供平台自用的固定本地服务使用）。

    Raises:
        UnsafeURLError: scheme 非法 / 无法解析 / 解析结果含私网地址。
    """
    raw = str(url or "").strip()
    if not raw:
        raise UnsafeURLError("URL 不能为空")

    try:
        parts = urllib.parse.urlsplit(raw)
    except ValueError as e:
        raise UnsafeURLError(f"URL 格式非法：{e}") from e

    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(f"仅支持 http/https 链接，当前 scheme：{parts.scheme or '(空)'}")
    if not parts.hostname:
        raise UnsafeURLError("URL 缺少主机名")

    host = parts.hostname.strip("[]").lower()
    # 带字面量 IP 的 URL 直接判定；域名先解析再判定（防 DNS 指向私网）
    if host in ("localhost", "localhost.") or host.endswith(".localhost"):
        ips: list[str] = ["127.0.0.1", "::1"]
    else:
        try:
            ips = _resolve_all_ips(host)
        except OSError as e:
            raise UnsafeURLError(f"目标主机无法解析：{host}（{e}）") from e

    private_hits = []
    for ip_str in ips:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            raise UnsafeURLError(f"目标主机解析到非法地址：{ip_str}")
        if str(ip) in _HARD_DENY_IPS:
            # 云元数据端点：任何模式下一律拒绝（不受 allow_private 影响）
            logger.warning("[outbound_guard] 已拦截云元数据端点外呼: host=%s ip=%s", host, ip)
            raise UnsafeURLError(f"不允许访问云元数据端点（{host} → {ip}）")
        if _is_private_ip(ip):
            private_hits.append(str(ip))

    if private_hits:
        if allow_private is None:
            # why：缺省取「未开启 YIMU_MULTIUSER」——单机桌面放行环回
            # （连本地 Ollama / xhs-mcp 是合法需求）；多用户服务器强制拒绝。
            allow_private = not multiuser_enabled()
        if not allow_private:
            logger.warning(
                "[outbound_guard] 已拦截指向私网的外呼请求 host=%s resolved=%s",
                host, private_hits)
            raise UnsafeURLError(
                f"出于安全考虑，不允许访问内网 / 本机地址（{host} → {private_hits[0]}）。"
                "请填写公网 http/https 链接")

    return raw
