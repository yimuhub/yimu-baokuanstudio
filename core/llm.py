"""企业级大模型网关中枢与供应商控制台 (OpenAI 兼容 /v1/chat/completions)。

支持主流全球与国产大模型供应商一键切换、毫秒级连通性测速 (Ping)、多 Agent 智能分工路由。
"""
import logging
import os
import time
from pathlib import Path

import httpx
import yaml

logger = logging.getLogger(__name__)
BASE = Path(__file__).resolve().parent.parent

# 13 大主流模型供应商企业级预设（含国产主力：火山引擎、混元、星火、百川等）
MODEL_PROVIDERS = {
    "yimu_official": {
        "id": "yimu_official",
        "name": "一幕·YIMU 官方",
        "icon": "🎭",
        "badge": "官方计费",
        "base_url": "https://gateway.yimu.studio/v1",
        "default_model": "yimu-chat",
        "models": ["yimu-chat", "yimu-reasoner", "yimu-vision"],
        "doc_url": "https://yimu.studio",
        "tips": "官方通道：按实际 Token 消耗扣减会员额度，免去自备 Key 的麻烦",
        "official": True,
        "metered": True,
    },
    "deepseek": {
        "id": "deepseek",
        "name": "DeepSeek 深度求索 (官方)",
        "icon": "🚀",
        "badge": "爆款推荐",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "doc_url": "https://platform.deepseek.com",
        "tips": "V3 文案极佳，R1 深度思考适合反思与逻辑解构，性价比天花板"
    },
    "openai": {
        "id": "openai",
        "name": "OpenAI (GPT-4o / o1 / DALL-E)",
        "icon": "🧠",
        "badge": "全球旗舰",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "models": ["gpt-4o", "gpt-4o-mini", "o1", "o3-mini", "dall-e-3", "sora"],
        "doc_url": "https://platform.openai.com",
        "tips": "全球综合能力基准，含 DALL-E 3 高清生图与 Sora 视频旗舰"
    },
    "claude": {
        "id": "claude",
        "name": "Anthropic Claude",
        "icon": "🟣",
        "badge": "文笔之王",
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-3-5-sonnet-20241022",
        "models": ["claude-3-7-sonnet", "claude-3-5-sonnet-20241022", "claude-3-5-haiku"],
        "doc_url": "https://docs.anthropic.com",
        "tips": "细腻文学感、长篇叙事最强音色（建议配合中转格式）"
    },
    "gemini": {
        "id": "gemini",
        "name": "Google Gemini (多模态)",
        "icon": "🔷",
        "badge": "超长上下文",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-2.0-flash",
        "models": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash", "imagen-3.0-generate-002"],
        "doc_url": "https://ai.google.dev",
        "tips": "极速文本与 Imagen 3 原生电影级文生图"
    },
    "qwen": {
        "id": "qwen",
        "name": "阿里通义千问 (Qwen & 万相)",
        "icon": "🔴",
        "badge": "国内顶流",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-max",
        "models": ["qwen-max", "qwen-plus", "qwen-turbo", "wanx-v1", "wanx-video"],
        "doc_url": "https://help.aliyun.com/document_detail/271257.html",
        "tips": "中文语境顶级，通义万相生图与视频模型全面集成"
    },
    "glm": {
        "id": "glm",
        "name": "智谱 GLM (智谱清言 & Cog)",
        "icon": "🟢",
        "badge": "中文权威",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-plus",
        "models": ["glm-4-plus", "glm-4-flash", "glm-4-long", "cogview-3-plus", "cogvideox"],
        "doc_url": "https://open.bigmodel.cn",
        "tips": "配备 CogView 3+ 高清生图与 CogVideoX 影视级生成"
    },
    "kimi": {
        "id": "kimi",
        "name": "月之暗面 (Kimi / Moonshot)",
        "icon": "🌙",
        "badge": "超长长文本",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-32k",
        "models": ["moonshot-v1-32k", "moonshot-v1-128k", "moonshot-v1-auto"],
        "doc_url": "https://platform.moonshot.cn",
        "tips": "万字材料吃透、爆款逆向拆解神器"
    },
    "ollama": {
        "id": "ollama",
        "name": "本地私有化 (Ollama / vLLM)",
        "icon": "⚡",
        "badge": "100% 本地隐私",
        "base_url": "http://localhost:11434/v1",
        "default_model": "deepseek-r1:8b",
        "models": ["deepseek-r1:8b", "qwen2.5:7b", "llama3.3:8b"],
        "doc_url": "https://ollama.ai",
        "tips": "零 Token 成本，纯离线保护核心数据资产"
    },
    "custom": {
        "id": "custom",
        "name": "自定义聚合网关 (硅基流动 / OneAPI)",
        "icon": "🌐",
        "badge": "中转网关",
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "deepseek-ai/DeepSeek-V3",
        "models": [
            "deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1", "Qwen/Qwen2.5-72B-Instruct",
            "black-forest-labs/FLUX.1-schnell", "deepseek-chat", "gpt-4o"
        ],
        "doc_url": "",
        "tips": "接入 SiliconFlow 硅基流动、OneAPI、NewAPI 或企业自建中转池"
    },
    "volcengine": {
        "id": "volcengine",
        "name": "火山引擎 (字节豆包 / Ark)",
        "icon": "🔥",
        "badge": "字节旗舰",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "default_model": "doubao-pro-32k",
        "models": ["doubao-pro-32k", "doubao-pro-128k", "doubao-lite-32k", "doubao-1-5-pro-32k", "doubao-1-5-pro-256k"],
        "doc_url": "https://www.volcengine.com/product/ark",
        "tips": "字节跳动豆包大模型，中文创作强劲，长上下文 128k/256k，国内访问极速"
    },
    "hunyuan": {
        "id": "hunyuan",
        "name": "腾讯混元 (Hunyuan)",
        "icon": "🐧",
        "badge": "腾讯出品",
        "base_url": "https://api.hunyuan.tencent.com/v1",
        "default_model": "hunyuan-pro",
        "models": ["hunyuan-pro", "hunyuan-standard", "hunyuan-lite", "hunyuan-turbo", "hunyuan-vision"],
        "doc_url": "https://cloud.tencent.com/product/hunyuan",
        "tips": "腾讯混元大模型，深度融合腾讯生态，适合微信公众号、视频号场景创作"
    },
    "spark": {
        "id": "spark",
        "name": "讯飞星火 (Spark)",
        "icon": "✨",
        "badge": "国产权威",
        "base_url": "https://spark-api-open.xf-yun.com/v1",
        "default_model": "4.0Ultra",
        "models": ["4.0Ultra", "max-32k", "pro-128k", "lite", "generalv3.5"],
        "doc_url": "https://xinghuo.xfyun.cn/sparkapi",
        "tips": "科大讯飞星火认知大模型，语音+文本双优，适合音视频内容创作场景"
    },
    "baichuan": {
        "id": "baichuan",
        "name": "百川智能 (Baichuan AI)",
        "icon": "🌊",
        "badge": "中文专精",
        "base_url": "https://api.baichuan-ai.com/v1",
        "default_model": "Baichuan4-Turbo",
        "models": ["Baichuan4-Turbo", "Baichuan4-Air", "Baichuan3-Turbo", "Baichuan3-Turbo-128k"],
        "doc_url": "https://platform.baichuan-ai.com",
        "tips": "百川智能专注中文语言理解，医疗/法律/金融垂类内容极强，RAG 检索增强"
    }
}


def classify_model(model_id: str) -> str:
    """智能分类模型类别：
    'text': 文字/对话/逻辑推理模型
    'image': 图片/绘画生成模型
    'video': 视频/影视生成模型
    """
    m = (model_id or "").lower()
    
    # 视频生成特征词
    video_keywords = ["video", "sora", "kling", "runway", "gen-3", "gen3",
                      "cogvideox", "cogvideo", "hailuo", "pika", "luma", "viggle",
                      "wanx-video", "wanx-v2-video", "veo", "pixverse", "seedance"]
    if any(k in m for k in video_keywords) or ("gen-2" in m and "generate" not in m) or ("gen2" in m and "generate" not in m):
        return "video"
        
    # 图片生成特征词
    image_keywords = ["image", "dall-e", "dalle", "flux", "midjourney", "stable-diffusion",
                      "sdxl", "sd-", "sd1", "sd2", "sd3", "imagen", "cogview", "kolors",
                      "wanx", "doubao-image", "qwen-vl-image", "agnes-image"]
    if any(k in m for k in image_keywords):
        return "image"
        
    return "text"


def fetch_remote_models(base_url: str, api_key: str = "", provider_id: str = "") -> dict:
    """调用远端供应商 /v1/models 或兼容端点获取模型清单并结构化分类，若失败自动降级到预设模型。"""
    base = (base_url or "").strip().rstrip("/")
    if not base and provider_id in MODEL_PROVIDERS:
        base = MODEL_PROVIDERS[provider_id].get("base_url", "").rstrip("/")
        
    key = (api_key or "").strip() or load_env().get("MEDIAFLOW_APIPOOL_KEY", "")

    candidates = []
    if base.endswith("/v1") or base.endswith("/v4"):
        candidates.append(f"{base}/models")
    else:
        candidates.append(f"{base}/v1/models")
        candidates.append(f"{base}/models")
    if "localhost:11434" in base or "127.0.0.1:11434" in base:
        candidates.insert(0, f"{base}/api/tags")

    headers = {}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    remote_models = []
    error_msg = ""
    is_local = "127.0.0.1" in base or "localhost" in base

    for url in candidates:
        try:
            with httpx.Client(timeout=8.0, trust_env=not is_local) as client:
                r = client.get(url, headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    # OpenAI 标准: {"data": [{"id": "..."}]}
                    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                        for item in data["data"]:
                            if isinstance(item, dict) and "id" in item:
                                remote_models.append(str(item["id"]))
                            elif isinstance(item, str):
                                remote_models.append(item)
                    # Ollama: {"models": [{"name": "..."}]}
                    elif isinstance(data, dict) and "models" in data and isinstance(data["models"], list):
                        for item in data["models"]:
                            if isinstance(item, dict) and "name" in item:
                                remote_models.append(str(item["name"]))
                            elif isinstance(item, str):
                                remote_models.append(item)
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and "id" in item:
                                remote_models.append(str(item["id"]))
                            elif isinstance(item, str):
                                remote_models.append(item)
                    if remote_models:
                        break
                else:
                    error_msg = f"HTTP {r.status_code}"
        except Exception as e:
            error_msg = str(e)

    # 去重并保序
    seen = set()
    cleaned = []
    for m in remote_models:
        if m and m not in seen:
            seen.add(m)
            cleaned.append(m)

    # 若未拉取到（如网络阻断或不支持 /models），采用预设回退
    is_preset_fallback = False
    if not cleaned:
        is_preset_fallback = True
        p_info = MODEL_PROVIDERS.get(provider_id, {})
        preset_list = p_info.get("models", [])
        if not preset_list and provider_id == "custom":
            preset_list = MODEL_PROVIDERS["custom"]["models"]
        cleaned = preset_list or ["deepseek-chat", "gpt-4o", "flux-schnell"]

    # 结构化分类并赋予初始勾选状态
    classified_models = []
    for mid in cleaned:
        cat = classify_model(mid)
        classified_models.append({
            "id": mid,
            "name": mid,
            "category": cat,
            "is_enabled": True
        })

    return {
        "ok": True,
        "is_fallback": is_preset_fallback,
        "count": len(classified_models),
        "models": classified_models,
        "msg": "成功从远端获取模型列表" if not is_preset_fallback else f"远端端点未响应模型列表 ({error_msg or '未开放 /v1/models'})，已载入高质量预设模型库"
    }


def load_config() -> dict:
    cfg_file = BASE / "config.yaml"
    if cfg_file.exists():
        with open(cfg_file, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def load_env() -> dict:
    env_path = BASE / ".env"
    vals = dict(os.environ)
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                vals.setdefault(k.strip(), v.strip())
    return vals


def ping_provider(base_url: str, api_key: str, model: str) -> dict:
    """向指定供应商端点发送极简测试握手，测算真实网络延迟并验证 Key 权限。"""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return {"ok": False, "error": "Base URL 不能为空", "latency_ms": 0}
    if not base.endswith("/v1") and not base.endswith("/v4"):
        # 宽容拼接
        test_url = f"{base}/v1/chat/completions" if "bigmodel" not in base else f"{base}/chat/completions"
    else:
        test_url = f"{base}/chat/completions"

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    headers["Content-Type"] = "application/json"

    body = {
        "model": (model or "gpt-3.5-turbo").strip(),
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 5,
        "temperature": 0.1,
    }

    t0 = time.time()
    try:
        is_local = "127.0.0.1" in test_url or "localhost" in test_url
        with httpx.Client(timeout=10.0, trust_env=not is_local) as client:
            r = client.post(test_url, json=body, headers=headers)
            latency = int((time.time() - t0) * 1000)
            if r.status_code == 200:
                res_json = r.json()
                reply = res_json.get("choices", [{}])[0].get("message", {}).get("content", "")
                return {
                    "ok": True,
                    "latency_ms": latency,
                    "status_code": 200,
                    "model": model,
                    "reply": (reply[:30] + "...") if len(reply) > 30 else reply,
                    "msg": f"握手成功！响应延迟 {latency}ms"
                }
            else:
                err_text = r.text[:200]
                return {
                    "ok": False,
                    "latency_ms": latency,
                    "status_code": r.status_code,
                    "error": f"HTTP {r.status_code}: {err_text}",
                    "msg": f"连接返回异常 ({r.status_code})"
                }
    except Exception as e:
        latency = int((time.time() - t0) * 1000)
        return {
            "ok": False,
            "latency_ms": latency,
            "error": str(e),
            "msg": f"连接超时或网络不可达: {e}"
        }


def get_all_configured_providers() -> dict:
    """返回所有已配置/已保存的供应商字典，并融合内置预设信息与所有自定义供应商。"""
    cfg = load_config()
    gw = cfg.get("gateway", {})
    saved_providers = gw.get("providers", {})
    env = load_env()
    active_pid = gw.get("provider_id", "deepseek")

    result = {}

    deleted_pids = set(gw.get("deleted_providers") or [])

    # 1. 载入官方预设供应商（过滤已被用户删除的预设）
    for pid, pinfo in MODEL_PROVIDERS.items():
        if pid in deleted_pids:
            continue
        saved = saved_providers.get(pid, {})
        spec_k = f"MEDIAFLOW_KEY_{pid.upper()}"
        has_key = bool(env.get(spec_k)) or (pid == active_pid and bool(env.get("MEDIAFLOW_APIPOOL_KEY")))

        saved_models = saved.get("configured_models")
        if not saved_models:
            saved_models = [
                {"id": m, "name": m, "category": classify_model(m), "is_enabled": True}
                for m in pinfo.get("models", [])
            ]

        result[pid] = {
            "id": pid,
            "name": saved.get("name") or pinfo["name"],
            "badge": pinfo.get("badge", ""),
            "tips": pinfo.get("tips", ""),
            "icon": pinfo.get("icon", "⚡"),
            "base_url": saved.get("base_url") or pinfo["base_url"],
            "default_model": saved.get("model") or pinfo["default_model"],
            "models": saved_models,
            "has_key": has_key,
            "is_active": pid == active_pid,
            "is_custom": False,
            "is_builtin": True,
        }

    # 2. 载入所有自定义供应商 (支持添加任意多个自定义中转、本地机群或独立供应商)
    for pid, p_saved in saved_providers.items():
        if pid in deleted_pids:
            continue
        if pid not in result and isinstance(p_saved, dict):
            spec_k = f"MEDIAFLOW_KEY_{pid.upper()}"
            has_key = bool(env.get(spec_k)) or (pid == active_pid and bool(env.get("MEDIAFLOW_APIPOOL_KEY")))
            saved_models = p_saved.get("configured_models")
            if not saved_models:
                p_models = p_saved.get("models", [p_saved.get("model", "gpt-3.5-turbo")])
                saved_models = [
                    {"id": m if isinstance(m, str) else m.get("id"),
                     "name": m if isinstance(m, str) else m.get("name", m.get("id")),
                     "category": classify_model(m if isinstance(m, str) else m.get("id")),
                     "is_enabled": True}
                    for m in p_models
                ]

            result[pid] = {
                "id": pid,
                "name": p_saved.get("name") or f"自定义网关 ({pid})",
                "badge": "自定义",
                "tips": p_saved.get("tips", "第三方中转或自建 OpenAI 兼容端点"),
                "icon": p_saved.get("icon", "🌐"),
                "base_url": p_saved.get("base_url", ""),
                "default_model": p_saved.get("model", ""),
                "models": saved_models,
                "has_key": has_key,
                "is_active": pid == active_pid,
                "is_custom": True,
                "is_builtin": False,
            }

    return result


def get_configured_models() -> list[dict]:
    """返回当前活动供应商已配置/已启用的模型清单（若尚未配置则回退到预设精品模型池）。"""
    cfg = load_config()
    gw = cfg.get("gateway", {})
    provider_id = gw.get("provider_id", "deepseek")

    # 优先读取 gateway.configured_models
    models = gw.get("configured_models")
    if models and isinstance(models, list) and len(models) > 0:
        return models

    # 其次读取 providers[provider_id].configured_models
    p_saved = gw.get("providers", {}).get(provider_id, {})
    if p_saved.get("configured_models"):
        return p_saved["configured_models"]

    p_info = MODEL_PROVIDERS.get(provider_id, MODEL_PROVIDERS.get("deepseek", {}))
    res = []
    for m in p_info.get("models", []):
        res.append({
            "id": m,
            "name": m,
            "category": classify_model(m),
            "is_enabled": True
        })
    return res


def save_provider_config(provider_id: str, base_url: str, api_key: str, model: str,
                         agent_routing: dict | None = None, params: dict | None = None,
                         configured_models: list[dict] | None = None,
                         provider_name: str | None = None,
                         is_set_active: bool = True) -> bool:
    """持久化保存供应商配置至 config.yaml 与 .env，同时维护多供应商配置池。"""
    pid = (provider_id or "custom").strip()
    cfg_file = BASE / "config.yaml"
    cfg = load_config()
    gw = cfg.setdefault("gateway", {})

    should_activate = is_set_active or gw.get("provider_id") == pid or not gw.get("provider_id")
    if should_activate:
        gw["provider_id"] = pid
        gw["base_url"] = base_url.strip()
        gw["model"] = model.strip()
        if agent_routing is not None:
            gw["agent_routing"] = agent_routing
        if configured_models is not None:
            gw["configured_models"] = configured_models
    # 若此前曾删除过该供应商，重新配置时将其移出已删除黑名单
    deleted_pids = set(gw.get("deleted_providers") or [])
    if pid in deleted_pids:
        deleted_pids.remove(pid)
        gw["deleted_providers"] = list(deleted_pids)

    # 维护多供应商持久化池
    providers = gw.setdefault("providers", {})
    p_entry = providers.setdefault(pid, {})
    if provider_name and provider_name.strip():
        p_entry["name"] = provider_name.strip()
    elif pid in MODEL_PROVIDERS:
        p_entry["name"] = MODEL_PROVIDERS[pid]["name"]
    else:
        p_entry.setdefault("name", f"自定义网关 ({pid})")

    p_entry["base_url"] = base_url.strip()
    p_entry["model"] = model.strip()
    if agent_routing is not None:
        p_entry["agent_routing"] = agent_routing
        gw["agent_routing"] = agent_routing
    if configured_models is not None:
        p_entry["configured_models"] = configured_models

    with open(cfg_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True)

    # 写入 .env 密钥（同时更新全局活动 Key 与供应商专属 Key）
    if api_key and api_key.strip():
        env_file = BASE / ".env"
        lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
        main_k = "MEDIAFLOW_APIPOOL_KEY"
        spec_k = f"MEDIAFLOW_KEY_{pid.upper()}"
        clean_key = api_key.strip()

        found_main, found_spec = False, False
        new_lines = []
        for ln in lines:
            s = ln.strip()
            if s.startswith(f"{main_k}="):
                if should_activate:
                    new_lines.append(f"{main_k}={clean_key}")
                else:
                    new_lines.append(ln)
                found_main = True
            elif s.startswith(f"{spec_k}="):
                new_lines.append(f"{spec_k}={clean_key}")
                found_spec = True
            else:
                new_lines.append(ln)
        if not found_main and should_activate:
            new_lines.append(f"{main_k}={clean_key}")
        if not found_spec:
            new_lines.append(f"{spec_k}={clean_key}")
        env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        if should_activate:
            os.environ[main_k] = clean_key
        os.environ[spec_k] = clean_key

    return True


def delete_provider(provider_id: str) -> bool:
    """删除指定的自定义供应商配置及环境变量密钥。"""
    pid = provider_id.strip()
    cfg_file = BASE / "config.yaml"
    cfg = load_config()
    gw = cfg.setdefault("gateway", {})
    providers = gw.setdefault("providers", {})

    if pid in providers:
        del providers[pid]

    deleted_pids = set(gw.get("deleted_providers") or [])
    deleted_pids.add(pid)
    gw["deleted_providers"] = list(deleted_pids)

    # 若删除的是当前活动主网关，平滑回退
    if gw.get("provider_id") == pid:
        all_candidates = [k for k in (list(providers.keys()) + list(MODEL_PROVIDERS.keys())) if k not in deleted_pids]
        new_active = "deepseek" if "deepseek" in all_candidates else (all_candidates[0] if all_candidates else "deepseek")
        gw["provider_id"] = new_active
        p_info = providers.get(new_active) or MODEL_PROVIDERS.get(new_active, {})
        gw["base_url"] = p_info.get("base_url", "")
        gw["model"] = p_info.get("model") or p_info.get("default_model", "")
        if p_info.get("configured_models"):
            gw["configured_models"] = p_info["configured_models"]

    with open(cfg_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True)

    # 清理 .env 中的对应 Key
    env_file = BASE / ".env"
    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8").splitlines()
        spec_k = f"MEDIAFLOW_KEY_{pid.upper()}"
        new_lines = [ln for ln in lines if not ln.strip().startswith(f"{spec_k}=")]
        env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        os.environ.pop(spec_k, None)

    return True


def set_active_provider(provider_id: str) -> bool:
    """切换系统当前活动主供应商。"""
    pid = provider_id.strip()
    cfg_file = BASE / "config.yaml"
    cfg = load_config()
    gw = cfg.setdefault("gateway", {})
    providers = gw.setdefault("providers", {})

    p_saved = providers.get(pid, {})
    p_preset = MODEL_PROVIDERS.get(pid, {})

    gw["provider_id"] = pid
    gw["base_url"] = p_saved.get("base_url") or p_preset.get("base_url", gw.get("base_url", ""))
    gw["model"] = p_saved.get("model") or p_preset.get("default_model", gw.get("model", ""))
    if p_saved.get("configured_models"):
        gw["configured_models"] = p_saved["configured_models"]
    if p_saved.get("agent_routing"):
        gw["agent_routing"] = p_saved["agent_routing"]

    with open(cfg_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True)

    # 同步活动 Key 到 MEDIAFLOW_APIPOOL_KEY
    env = load_env()
    spec_k = f"MEDIAFLOW_KEY_{pid.upper()}"
    key_val = env.get(spec_k, "")
    if key_val:
        env_file = BASE / ".env"
        lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
        main_k = "MEDIAFLOW_APIPOOL_KEY"
        found = False
        new_lines = []
        for ln in lines:
            if ln.strip().startswith(f"{main_k}="):
                new_lines.append(f"{main_k}={key_val}")
                found = True
            else:
                new_lines.append(ln)
        if not found:
            new_lines.append(f"{main_k}={key_val}")
        env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        os.environ[main_k] = key_val

    return True


def resolve_llm_endpoint(model: str | None = None, stage: str | None = None, user_id: str | None = None) -> tuple[str, str, str, str]:
    """统一模型端点与凭据解析器 (Universal Endpoint Resolver)。
    
    返回四元组：(base_url, api_key, resolved_model, provider_id)
    
    解析机制：
    0. V6 多用户支持：若传入 user_id 且该用户在 API Vault 中配置了自定义生效的 Provider/Key，优先使用该用户的独立配置；
    1. 纯空/跟随全局：直接走当前活动供应商 (active_provider) 的主模型；
    2. 显式指定供应商前缀（如 'openai/gpt-4o' 或 'deepseek:deepseek-chat'）：精准路由至对应供应商；
    3. 纯模型名称匹配：
       - 优先在当前活动供应商的已配置模型池中匹配；
       - 若未匹配，检索其他已配置并具有 API Key 的供应商池（实现跨运营商多 Agent 协作）；
       - 若全网无匹配：自动平滑安全回退至当前活动供应商的主模型。
    """
    # V6 用户专属 API Key 优先
    if user_id:
        try:
            from core import auth
            user_key_info = auth.get_active_user_llm_config(user_id)
            if user_key_info and user_key_info.get("plain_api_key"):
                u_pid = user_key_info.get("provider", "custom")
                pinfo = MODEL_PROVIDERS.get(u_pid, {})
                u_base = (user_key_info.get("base_url") or pinfo.get("base_url") or "https://api.deepseek.com").rstrip("/")
                u_model = (model or "").strip() or user_key_info.get("model_id") or pinfo.get("default_model") or "deepseek-chat"
                return u_base, user_key_info["plain_api_key"], u_model, u_pid
        except Exception as e:
            logger.warning(f"[LLM] 解析用户专属 API 异常，回退至系统托管: {e}")

    cfg = load_config()
    gw = cfg.get("gateway", {})
    env = load_env()

    active_pid = gw.get("provider_id") or "deepseek"
    active_pinfo = MODEL_PROVIDERS.get(active_pid, MODEL_PROVIDERS.get("deepseek", {}))

    active_base = (gw.get("base_url") or active_pinfo.get("base_url", "https://api.deepseek.com")).rstrip("/")
    active_model = gw.get("model") or active_pinfo.get("default_model", "deepseek-chat")
    active_key = env.get(f"MEDIAFLOW_KEY_{active_pid.upper()}") or env.get("MEDIAFLOW_APIPOOL_KEY", "")

    req_model = (model or "").strip()

    # 1. 未指定模型：直接走当前活动供应商默认模型
    if not req_model:
        return active_base, active_key, active_model, active_pid

    # 2. 带供应商前缀（例如 "openai/gpt-4o" 或 "qwen:qwen-max"）
    if "/" in req_model or ":" in req_model:
        p_prefix, actual_m = req_model.replace(":", "/").split("/", 1)
        p_prefix = p_prefix.strip().lower()
        actual_m = actual_m.strip()
        if p_prefix in MODEL_PROVIDERS or p_prefix in gw.get("providers", {}):
            saved_p = gw.get("providers", {}).get(p_prefix, {})
            preset_p = MODEL_PROVIDERS.get(p_prefix, {})
            target_base = (saved_p.get("base_url") or preset_p.get("base_url", "")).rstrip("/")
            target_key = env.get(f"MEDIAFLOW_KEY_{p_prefix.upper()}") or (active_key if p_prefix == active_pid else "")
            if target_base:
                return target_base, target_key, actual_m, p_prefix

    # 3. 检查当前活动供应商的模型池
    active_models_cfg = gw.get("configured_models") or []
    active_model_ids = [m.get("id") if isinstance(m, dict) else str(m) for m in active_models_cfg]
    if not active_model_ids and active_pid in MODEL_PROVIDERS:
        active_model_ids = MODEL_PROVIDERS[active_pid].get("models", [])

    if req_model in active_model_ids:
        return active_base, active_key, req_model, active_pid

    # 4. 跨供应商智能查找：检索其他已配置并具有密钥的供应商
    saved_providers = gw.get("providers", {})
    for pid, pdata in saved_providers.items():
        if pid == active_pid:
            continue
        p_models = [m.get("id") if isinstance(m, dict) else str(m) for m in pdata.get("configured_models", [])]
        if not p_models and pid in MODEL_PROVIDERS:
            p_models = MODEL_PROVIDERS[pid].get("models", [])
        if req_model in p_models:
            p_base = (pdata.get("base_url") or MODEL_PROVIDERS.get(pid, {}).get("base_url", "")).rstrip("/")
            p_key = env.get(f"MEDIAFLOW_KEY_{pid.upper()}", "")
            if p_base and (p_key or "11434" in p_base):
                logger.info(f"[LLM] 模型 '{req_model}' 命中已配置跨运营商通道 [{pid}] ({p_base})")
                return p_base, p_key, req_model, pid

    # 5. 跨供应商查找未存入 providers 但在内置预设中的供应商（且环境变量配置了该密钥）
    for pid, pinfo in MODEL_PROVIDERS.items():
        if pid == active_pid:
            continue
        if req_model in pinfo.get("models", []):
            p_key = env.get(f"MEDIAFLOW_KEY_{pid.upper()}", "")
            if p_key:
                p_base = pinfo.get("base_url", "").rstrip("/")
                logger.info(f"[LLM] 模型 '{req_model}' 命中预设跨运营商通道 [{pid}] ({p_base})")
                return p_base, p_key, req_model, pid

    # 6. 防御性回退：模型无效或属于旧机器（如 agnes-3.0-flash），平滑回退到当前主模型
    logger.warning(
        f"[LLM] 目标模型 '{req_model}' 在当前供应商 [{active_pid}] 中未注册，自动平滑安全回退至当前主模型 '{active_model}'"
    )
    return active_base, active_key, active_model, active_pid


def _get_fallback_candidates(exclude_pid: str) -> list[tuple[str, str, str, str]]:
    """获取所有具备有效密钥/可用连接的备选供应商列表 (base, key, default_model, pid)"""
    candidates = []
    cfg = load_config()
    gw = cfg.get("gateway", {})
    env = load_env()
    saved_providers = gw.get("providers", {})

    priority = ["deepseek", "qwen", "custom", "openai", "glm"]
    all_pids = priority + [p for p in MODEL_PROVIDERS if p not in priority]

    for pid in all_pids:
        if pid == exclude_pid:
            continue
        p_info = MODEL_PROVIDERS.get(pid, {})
        saved = saved_providers.get(pid, {})
        base = (saved.get("base_url") or p_info.get("base_url", "")).rstrip("/")
        m = saved.get("model") or p_info.get("default_model", "deepseek-chat")
        key = env.get(f"MEDIAFLOW_KEY_{pid.upper()}", "") or (env.get("MEDIAFLOW_APIPOOL_KEY", "") if pid == gw.get("provider_id") else "")
        if base and (key or "11434" in base or "127.0.0.1" in base):
            candidates.append((base, key, m, pid))
    return candidates


def chat(messages: list[dict], *, model: str | None = None,
         temperature: float = 0.8, timeout_s: float | None = None, stage: str | None = None, user_id: str | None = None) -> str:
    """大模型通用对话调用，全自动跨运营商路由与多通道自动熔断降级。支持 V6 独立用户 API 隔离。"""
    base, key, target_model, provider_id = resolve_llm_endpoint(model, stage=stage, user_id=user_id)

    # 针对本地 Ollama 允许无 key 调用
    if not key and "localhost:11434" not in base and "127.0.0.1" not in base:
        fallbacks = _get_fallback_candidates(provider_id)
        if fallbacks:
            base, key, target_model, provider_id = fallbacks[0]
            logger.warning(f"[LLM] 主通道缺少密钥，自动切换至已配置备用通道 [{provider_id}]")
        else:
            raise RuntimeError(f"供应商 [{provider_id}] 尚未配置 API Key，请先在控制中心企业级 AI 供应商中配置密钥")

    # 对话接口安全保护：若解析出的目标模型是生图/视频模型，回退到当前主文本模型
    if classify_model(target_model) in ("image", "video"):
        p_info = MODEL_PROVIDERS.get(provider_id, MODEL_PROVIDERS.get("deepseek", {}))
        target_model = p_info.get("default_model", "deepseek-chat")

    cfg = load_config().get("gateway", {})
    timeout = timeout_s if timeout_s is not None else cfg.get("timeout_s", 60)

    chain = [(base, key, target_model, provider_id)]
    for fb in _get_fallback_candidates(provider_id):
        chain.append(fb)

    last_err = None
    for attempt_idx, (curr_base, curr_key, curr_model, curr_pid) in enumerate(chain):
        req_url = f"{curr_base}/chat/completions" if not curr_base.endswith("/chat/completions") else curr_base
        body = {
            "model": curr_model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if curr_key:
            headers["Authorization"] = f"Bearer {curr_key}"

        is_local = "127.0.0.1" in req_url or "localhost" in req_url
        try:
            with httpx.Client(timeout=timeout, trust_env=not is_local) as client:
                r = client.post(req_url, json=body, headers=headers)
                if r.status_code == 200:
                    payload = r.json()
                    content = payload["choices"][0]["message"]["content"]
                    # 双轨制计量：提取 usage，全 provider 记统计，官方通道扣费
                    try:
                        from studio import llm_metering as _metering

                        _u = payload.get("usage") or {}
                        _pt = int(_u.get("prompt_tokens") or 0)
                        _ct = int(_u.get("completion_tokens") or 0)
                        _tt = int(_u.get("total_tokens") or 0) or (_pt + _ct)
                        _prompt_text = "\n".join(
                            str(m.get("content", "")) for m in messages if isinstance(m, dict)
                        )
                        _metering.record_llm_call(
                            curr_pid, curr_model, _pt, _ct, _tt, user_id=user_id,
                            prompt_text=_prompt_text, completion_text=content or "",
                        )
                    except _metering.InsufficientCreditsError:
                        raise
                    except Exception as _me:  # noqa: BLE001
                        logger.warning(f"[LLM] 用量计量失败（不阻塞返回）: {_me}")
                    return content
                else:
                    last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                    logger.warning(f"[LLM] 渠道 [{curr_pid}] 返回异常状态码: {r.status_code}，尝试备用通道...")
        except Exception as e:
            last_err = e
            logger.warning(f"[LLM] 渠道 [{curr_pid}] 发生异常: {e}，正在尝试自动降级转移...")

    raise RuntimeError(f"大模型全链路调用失败，已尝试所有可用备选通道。最后错误: {last_err}")


def chat_stream(messages: list[dict], *, model: str | None = None,
                temperature: float = 0.8, timeout_s: float | None = None, stage: str | None = None,
                user_id: str | None = None):
    """流式打字机输出生成器，实时 yield 文本 chunk (SSE)。"""
    base, key, target_model, provider_id = resolve_llm_endpoint(model, stage=stage)
    if not key and "localhost:11434" not in base and "127.0.0.1" not in base:
        fallbacks = _get_fallback_candidates(provider_id)
        if fallbacks:
            base, key, target_model, provider_id = fallbacks[0]
        else:
            raise RuntimeError(f"供应商 [{provider_id}] 尚未配置 API Key")

    if classify_model(target_model) in ("image", "video"):
        p_info = MODEL_PROVIDERS.get(provider_id, MODEL_PROVIDERS.get("deepseek", {}))
        target_model = p_info.get("default_model", "deepseek-chat")

    body = {
        "model": target_model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
        # OpenAI 兼容协议：流式需显式声明才会在最后一个 chunk 返回 usage
        "stream_options": {"include_usage": True},
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    cfg = load_config().get("gateway", {})
    timeout = timeout_s if timeout_s is not None else cfg.get("timeout_s", 60)
    req_url = f"{base}/chat/completions" if not base.endswith("/chat/completions") else base
    is_local = "127.0.0.1" in req_url or "localhost" in req_url

    with httpx.Client(timeout=timeout, trust_env=not is_local) as client:
        with client.stream("POST", req_url, json=body, headers=headers) as response:
            response.raise_for_status()
            _s_pt, _s_ct, _s_tt = 0, 0, 0
            _s_text_parts = []  # 累积流式输出文本，用于 usage 缺失时估算
            for line in response.iter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        import json as _json
                        chunk = _json.loads(data_str)
                        # SSE usage 累加（最后一个 chunk 通常带 usage；没有则记 0）
                        _u = chunk.get("usage") or {}
                        if _u:
                            _s_pt = int(_u.get("prompt_tokens") or _s_pt)
                            _s_ct = int(_u.get("completion_tokens") or _s_ct)
                            _s_tt = int(_u.get("total_tokens") or _s_tt)
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            _s_text_parts.append(content)
                            yield content
                    except Exception:
                        pass
            # 流结束：双轨制计量
            try:
                from studio import llm_metering as _metering

                if not _s_tt:
                    _s_tt = _s_pt + _s_ct
                _prompt_text = "\n".join(
                    str(m.get("content", "")) for m in messages if isinstance(m, dict)
                )
                _metering.record_llm_call(
                    provider_id, target_model, _s_pt, _s_ct, _s_tt, user_id=user_id,
                    prompt_text=_prompt_text, completion_text="".join(_s_text_parts),
                )
            except _metering.InsufficientCreditsError:
                raise
            except Exception as _me:  # noqa: BLE001
                logger.warning(f"[LLM] 流式用量计量失败（不阻塞返回）: {_me}")


def available() -> bool:
    cfg = load_config().get("gateway", {})
    base = cfg.get("base_url", "")
    if "11434" in base:
        return True
    env = load_env()
    pid = cfg.get("provider_id", "deepseek")
    return bool(env.get("MEDIAFLOW_APIPOOL_KEY", "") or env.get(f"MEDIAFLOW_KEY_{pid.upper()}", ""))



