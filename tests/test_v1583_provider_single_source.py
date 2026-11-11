# SPDX-License-Identifier: BUSL-1.1
"""V15.8.3 · 供应商配置「单一真源」回归锁。

客户缺陷：Windows 客户端在「设置 → 模型服务」填好 API 地址与密钥，
点「灵感与选题 → 一句话生成爆款」仍提示大模型不可用。

根因是同一件事被存了两份、读的又是另一份：
1. 密钥：保存写安装目录 ``.env``，而 ``load_env()`` 里用户目录 ``secrets.env``
   优先级更高——用户新填的 Key 写到了**永远读不到**的地方，旧占位值 ``test_key`` 一直生效。
2. 地址：保存写 ``gateway.providers.<pid>``，解析读 ``gateway.base_url`` 这份出厂快照。
3. 备用链：旧实现只遍历内置预设，**用户自建通道永远进不了候选**，一跳到底。

本文件把这四条钉死，并加一道静态护栏：除 registry / llm / user_paths 外，
任何模块都不许再直接读 ``MEDIAFLOW_KEY_*``——防止第五套逻辑长出来。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

SHIPPED_CONFIG = """gateway:
  provider_id: custom
  base_url: https://apihub.agnes-ai.com/v1
  model: agnes-2.5-pro-alpha
  providers:
    custom:
      name: 官方中转
      base_url: https://apihub.agnes-ai.com/v1
      model: agnes-2.5-pro-alpha
"""


@pytest.fixture()
def install(tmp_path, monkeypatch):
    """隔离的安装目录 + 用户目录，清掉进程里可能残留的 MEDIAFLOW_* 变量。"""
    app = tmp_path / "app"
    userdata = tmp_path / "userdata"
    (app / "data").mkdir(parents=True)
    userdata.mkdir()

    from core import llm, provider_registry as reg, user_paths

    monkeypatch.setattr(reg, "BASE", app)
    monkeypatch.setattr(llm, "BASE", app)
    monkeypatch.setattr(user_paths, "user_data_dir", lambda: userdata)
    monkeypatch.setattr(user_paths, "secrets_env_path", lambda: userdata / "secrets.env")
    for key in list(os.environ):
        if key.startswith("MEDIAFLOW_"):
            monkeypatch.delenv(key, raising=False)

    (app / "config.yaml").write_text(SHIPPED_CONFIG, encoding="utf-8")
    return app, userdata


# ---------------------------------------------------------------------------
# 1. 核心缺陷：保存之后，解析出来的必须就是用户填的东西
# ---------------------------------------------------------------------------

def test_save_then_resolve_returns_user_values(install):
    app, _ = install
    from core import llm

    llm.save_provider_config(
        "custom", "https://my-gateway.example/v1", "sk-real-user-key", "my-model",
    )

    base, key, model, pid = llm.resolve_llm_endpoint()
    assert base == "https://my-gateway.example/v1", "地址必须用用户新填的，而不是出厂快照"
    assert key == "sk-real-user-key", "密钥必须用用户新填的，而不是旧的占位值"
    assert model == "my-model"
    assert pid == "custom"


def test_key_lands_in_user_secrets_not_install_env(install):
    app, userdata = install
    from core import llm, user_paths

    llm.save_provider_config("custom", "https://x.example/v1", "sk-abc-123456", "m")

    secrets = user_paths.read_env_file(userdata / "secrets.env")
    assert secrets.get("MEDIAFLOW_KEY_CUSTOM") == "sk-abc-123456"
    # 安装目录 .env 不再写入密钥（它是低优先级位置，写进去等于没写）
    install_env = user_paths.read_env_file(app / ".env")
    assert "MEDIAFLOW_KEY_CUSTOM" not in install_env


def test_config_file_keeps_single_source(install):
    """落盘只允许 provider_id + providers，不允许再出现 gateway.base_url 快照。"""
    app, _ = install
    import yaml

    from core import llm

    llm.save_provider_config("custom", "https://new.example/v1", "sk-1", "m1")

    raw = yaml.safe_load((app / "config.yaml").read_text(encoding="utf-8"))
    gw = raw["gateway"]
    for field in ("base_url", "model", "configured_models", "agent_routing"):
        assert field not in gw, f"gateway.{field} 不该再作为独立事实落盘"
    assert gw["providers"]["custom"]["base_url"] == "https://new.example/v1"


# ---------------------------------------------------------------------------
# 2. 占位值必须被当成「没配」，否则会把用户送到必然 401 的通道
# ---------------------------------------------------------------------------

def test_placeholder_key_counts_as_missing(install):
    app, userdata = install
    from core import llm, provider_registry as reg

    (userdata / "secrets.env").write_text(
        "MEDIAFLOW_APIPOOL_KEY=test_key\nMEDIAFLOW_KEY_CUSTOM=test_key\n", encoding="utf-8"
    )
    assert reg.key_for("custom", allow_global=True) == ""
    assert llm.available() is False, "示例值不能算「已配置」"

    diag = llm.diagnose()
    assert diag["key_present"] is False
    assert diag["placeholder_keys"], "应当明确指出命中了占位值"
    assert "示例值" in diag["advice"]


def test_real_key_after_placeholder_wins(install):
    """用户覆盖掉示例值后必须立刻生效（哪怕安装目录 .env 还留着旧值）。"""
    app, userdata = install
    from core import llm

    (app / ".env").write_text("MEDIAFLOW_KEY_CUSTOM=test_key\n", encoding="utf-8")
    (userdata / "secrets.env").write_text("MEDIAFLOW_KEY_CUSTOM=test_key\n", encoding="utf-8")

    llm.save_provider_config("custom", "https://real.example/v1", "sk-real-key-9999", "m")
    _base, key, _model, _pid = llm.resolve_llm_endpoint()
    assert key == "sk-real-key-9999"
    assert llm.diagnose()["key_source"] == "MEDIAFLOW_KEY_CUSTOM"


# ---------------------------------------------------------------------------
# 3. 备用链要认得用户自建通道（旧实现只遍历内置预设）
# ---------------------------------------------------------------------------

def test_fallback_candidates_include_custom_providers(install):
    app, userdata = install
    from core import llm, provider_registry as reg

    reg.save_provider("my_gateway", base_url="https://gw.example/v1", model="gw-model", name="我的中转")
    reg.set_key("my_gateway", "sk-gw-key")
    reg.set_active("custom")

    cands = [c[3] for c in llm._get_fallback_candidates("custom")]
    assert "my_gateway" in cands, "用户自建的通道必须能作为备用通道"


def test_fallback_skips_placeholders(install):
    app, userdata = install
    from core import llm, provider_registry as reg

    reg.save_provider("my_gateway", base_url="https://gw.example/v1", model="gw-model")
    reg.set_key("my_gateway", "test_key")  # 占位值不构成可用通道

    cands = [c[3] for c in llm._get_fallback_candidates("custom")]
    assert "my_gateway" not in cands


# ---------------------------------------------------------------------------
# 4. 旧配置折叠：升级上来的「双份存储」要收敛成一份
# ---------------------------------------------------------------------------

def test_normalize_folds_legacy_snapshot(install):
    app, _ = install
    from core import provider_registry as reg

    cfg, dirty = reg.normalize(reg.raw_config())
    assert dirty is True
    gw = cfg["gateway"]
    assert "base_url" not in gw
    assert gw["providers"]["custom"]["base_url"] == "https://apihub.agnes-ai.com/v1"


def test_migrate_is_idempotent(install):
    app, _ = install
    from core import provider_registry as reg

    assert reg.migrate() is True
    assert reg.migrate() is False, "已归一化时不应重复回写"


def test_pool_wins_over_legacy_top_level(install):
    """池里已有值（用户最近保存）时，绝不能被顶层旧快照覆盖。"""
    app, _ = install
    from core import provider_registry as reg

    (app / "config.yaml").write_text(
        """gateway:
  provider_id: custom
  base_url: https://stale.example/v1
  model: stale-model
  providers:
    custom:
      base_url: https://fresh.example/v1
      model: fresh-model
""", encoding="utf-8")
    cfg, _ = reg.normalize(reg.raw_config())
    entry = cfg["gateway"]["providers"]["custom"]
    assert entry["base_url"] == "https://fresh.example/v1"
    assert entry["model"] == "fresh-model"


# ---------------------------------------------------------------------------
# 5. 失败信息要逐通道说明，而不是一句「全链路失败」
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text

    def json(self):
        return {"choices": [{"message": {"content": "ok"}}]}


class _Client:
    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, headers=None):
        return _Resp(401, "invalid api key")


def test_chat_error_lists_every_channel(install, monkeypatch):
    app, userdata = install
    from core import llm, provider_registry as reg

    # 两条通道都会 401，确认错误信息逐条列出
    reg.save_provider("custom", base_url="https://a.example/v1", model="m1")
    reg.set_key("custom", "sk-aaa")
    reg.save_provider("alt", base_url="https://b.example/v1", model="m2")
    reg.set_key("alt", "sk-bbb")
    reg.set_active("custom")

    monkeypatch.setattr(llm.httpx, "Client", _Client)

    with pytest.raises(RuntimeError) as ei:
        llm.chat([{"role": "user", "content": "hi"}], timeout_s=1)
    msg = str(ei.value)
    assert "已尝试" in msg
    assert "401" in msg and "密钥无效" in msg
    assert "a.example" in msg and "b.example" in msg, "每条失败通道都要点到名"


# ---------------------------------------------------------------------------
# 6. 静态护栏：不许再长出第五套读密钥的逻辑
# ---------------------------------------------------------------------------

_ALLOWED_KEY_READERS = {
    "core/llm.py",
    "core/provider_registry.py",
    "core/user_paths.py",
}


def test_no_module_reads_provider_keys_directly():
    """AST 级护栏：除白名单外，任何模块不得出现 MEDIAFLOW_KEY_* 字面量。

    用 AST 而不是 grep，是为了不被注释与文档字符串里的举例误判——
    真正危险的是代码里拼键名，而不是文档里提到它。
    """
    import ast

    needles = ("MEDIAFLOW_KEY_", "MEDIAFLOW_APIPOOL_KEY")
    offenders = []

    for sub in ("core", "web", "studio"):
        for path in (ROOT / sub).rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if rel in _ALLOWED_KEY_READERS:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                continue

            # 收集文档字符串（模块 / 类 / 函数），这些不算代码引用
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    body = getattr(node, "body", None)
                    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                            and isinstance(body[0].value.value, str):
                        docstrings.add(id(body[0].value))

            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                        and id(node) not in docstrings:
                    if any(n in node.value for n in needles):
                        offenders.append(f"{rel}:{node.lineno}: {node.value[:80]!r}")

    assert not offenders, (
        "供应商密钥只能通过 core.provider_registry 访问，以下位置绕过了单一真源：\n"
        + "\n".join(offenders)
    )


def test_diagnose_never_leaks_full_key(install):
    app, userdata = install
    from core import llm

    llm.save_provider_config("custom", "https://x.example/v1", "sk-super-secret-key-1234", "m")
    diag = llm.diagnose()
    dumped = repr(diag)
    assert "sk-super-secret-key-1234" not in dumped
    assert diag["key_tail"] == "1234"


def test_save_reports_failure_instead_of_pretending(install, monkeypatch):
    """写盘失败必须如实返回 False——旧实现在这种情况下仍回「已持久化保存」。"""
    from core import llm, provider_registry as reg

    monkeypatch.setattr(reg, "write_config", lambda cfg: False)
    assert llm.save_provider_config("custom", "https://x.example/v1", "sk-a", "m") is False
