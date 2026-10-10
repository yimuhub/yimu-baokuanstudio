# 视频大模型接入规则与快速配置指南

> 适用版本：V8（8.0.0）。本文覆盖市场主流视频生成模型（Agnes / Sora / Veo / 可灵 Kling / 万相 Wan 等）的接入协议、参数限制与系统配置方法。
> 当前生产环境使用 Agnes（网关 8787）联调，本文同时为未来接入更多模型提供规则依据。

---

## 1. 五类视频生成协议总览

市面上视频大模型的 API 可归为 **5 类协议**。`core/ad_video.py::_call_video_model` 目前已实现前两类，后三类通过「OpenAI 兼容中转层」接入或在扩展点新增分支即可。

| # | 协议类型 | 代表 | 建任务端点 | 轮询端点 | 取结果 | 系统支持状态 |
|---|---------|------|-----------|---------|--------|:---:|
| P1 | **Agnes 异步任务式**（`/v1` 后缀自动识别） | Agnes Flash / 自研网关 | `POST {base}/videos` | `GET {base}/videos/{task_id}` | 完成态 `metadata.url` / `b64_json` | ✅ 已实现（含 503 退避） |
| P2 | **通用同步式**（OpenAI 风格） | Sora、中转层包装后的任意模型 | `POST {base}/videos/generations` | 无需轮询 | 响应内 `b64_json` / `url` | ✅ 已实现 |
| P3 | **OpenAI 异步视频式** | OpenAI Sora 官方 API | `POST /v1/videos` | `GET /v1/videos/{id}`（建议 20s） | `completed` 态下载 | ⚠️ 与 P1 同构，中转层包装后即可走 P1 |
| P4 | **Google LRO 长任务式** | Veo（Gemini API） | `POST /v1beta/models/{model}:predictLongRunning` | `GET /v1beta/{operation_name}`（建议 10s） | `done=true` 后 `response…generatedSamples[0].video.uri` | 🔧 需扩展分支 |
| P5 | **DashScope 异步任务式** | 阿里万相 Wan（百炼） | `POST /api/v1/services/aigc/video-generation/video-synthesis` + 头 `X-DashScope-Async: enable` | `GET /api/v1/tasks/{task_id}`（建议 15s） | `SUCCEEDED` 后 `output.video_url` | 🔧 需扩展分支 |
| P6 | **Kling 任务式** | 可灵 Kling | `POST https://api-singapore.klingai.com/image-to-video/{model}`（文生视频用对应 `/text-to-video/{model}`） | `GET /tasks` 或按 `task_id` 查询 | `succeeded` 态取视频 | 🔧 需扩展分支 |

> 结论：**凡是能暴露 `/v1/videos`（P1/P3 同构）或 `/videos/generations`（P2）的端点，不改代码即可接入**——这是客户快速配置的首选路径（用 OneAPI、硅基流动、自研网关等中转层包装原生协议）。原生直连（P4/P5/P6）需要按下文「扩展指南」加分支。

---

## 2. 主流模型能力矩阵（关键参数限制）

> 客户接入前先看此表，把系统默认值（时长 5s / 竖屏 9:16）映射到目标模型允许的档位；不支持的值会被接口 400 拒绝。

| 模型 | 供应商/入口 | 时长（可选档位） | 画幅 | 分辨率 | 输入 | 音频 | 特性备注 |
|------|------------|-----------------|------|--------|------|------|---------|
| **agnes-video-2.5-flash** | Agnes（网关 8787 当前在用） | **固定 5s**（不可传 duration/seconds 字段） | `aspect_ratio`：9:16 / 16:9 | 720p | `mode: text` 或 `image`（参考图） | — | 异步任务，单次约 1–4 分钟；队列满返回 503 |
| **agnes-video-v2.0** | Agnes | 5s 档 | 9:16 / 16:9 | 720p/1080p | text / image | — | 当前上游无可用渠道（503），保留配置 |
| **sora-2** | OpenAI | 4 / 8 / 12 s | `size`：1280x720、720x1280（横/竖） | 720p 档为主 | prompt + 可选首帧 | ✅ 原生音画同步 | 异步任务；生成 1–5 分钟；短时长（4–8s）稳定性最好 |
| **sora-2-pro** | OpenAI | 更长档位（含 15/20s） | 支持 1080p 级 `size` | 1080p 档 | prompt + 可选首帧 | ✅ | 价格/时延更高；档位以 OpenAI 官方 docs 实时为准 |
| **veo-3.1-generate-preview** | Google Gemini API | 4 / 8 s（`durationSeconds`） | `aspectRatio`：16:9（默认）/ 9:16 | 720p / 1080p / 4k（Lite 无 4k） | 文本、首帧图、首尾帧、参考图（R2V 限 16:9+8s）、视频续写（限 720p） | ✅ 原生音频 | LRO 长任务；轮询建议 10s；4k 更贵更慢 |
| **kling-2.5 / kling-2.6** | 可灵（Kuaishou） | **5 / 10 s**（整数二选一） | 16:9 / 9:16 / 1:1 | 720p / 1080p（`settings.resolution`） | prompt（≤2500 字）、首帧/尾帧图（≥300px、宽高比 1:2.5~2.5:1、≤50MB）、voice（最多 2 个） | `audio: native`（**仅 1080p**；首尾帧也仅 1080p） | 2.6 版 `contents` 新协议；支持 `callback_url` 回调、`external_task_id`、水印开关；旧版（1.5/1.6/2.1）用 `mode: std/pro` |
| **wan2.7-t2v / i2v / r2v** | 阿里百炼（DashScope） | **2–15 s 整数** | `ratio`：16:9（默认）/ 9:16 / 1:1 / 4:3 / 3:4（传首帧图时 ratio 被忽略，随首帧） | 720P / 1080P（`resolution`） | 文本、首帧/尾帧图（≤100MB、240–4096px、宽高比 1:8~8:1）、参考视频（2–10s，mp4/mov）、音频驱动（WAV/MP3 1–10s ≤15MB） | 支持自动配音/上传音频声画同步 | `X-DashScope-Async: enable` 必带；状态 PENDING→RUNNING→SUCCEEDED/FAILED；task_id 24h 有效；多镜头叙事 |

### 系统默认值 → 各模型换算表（duration_s=5、aspect=9:16 场景）

| 目标模型 | 应传时长 | 应传画幅 | 注意事项 |
|---------|---------|---------|---------|
| agnes-video-2.5-flash | **不传**（固定 5s） | `aspect_ratio: "9:16"` | 传 duration/seconds 会 400 |
| sora-2 | 4 或 8（取最近的允许档） | `size: "720x1280"` | 不支持 5s，需就近取档 |
| veo-3.1 | 4 或 8 | `aspectRatio: "9:16"` | durationSeconds 仅 4/8 |
| kling-2.x | 5 | `aspect_ratio: "9:16"` | 5s 直接命中，无需换算 |
| wan2.7 | 5（整数 2–15 均可） | `ratio: "9:16"` | 传首帧时随首帧画幅 |

---

## 3. 各供应商接入细节（端点 / 鉴权 / 轮询 / 退避）

### 3.1 Agnes（当前生产）
- 端点：`{base_url}/videos` 建任务，`{base_url}/videos/{task_id}` 轮询（base 以 `/v1` 结尾时系统自动走 P1 分支）。
- 鉴权：`Authorization: Bearer {MEDIAFLOW_KEY_YIMU_OFFICIAL}`。
- 建任务体：`{"model", "mode": "text"|"image", "prompt", "aspect_ratio", "image"?(b64)}`。**禁止字段**：`duration`、`seconds`（上游 400）。
- 轮询：5s 间隔，上限 10 分钟；成功态 `completed/success/succeeded/finished` → 取 `metadata.url`（或 `b64_json`）下载。
- 退避：建任务 503（队列满/无渠道）→ 等 20s 重试，最多 5 次。

### 3.2 OpenAI Sora
- 端点：`POST https://api.openai.com/v1/videos`（Azure：`{resource}.openai.azure.com/openai/v1/`）；轮询 `GET /v1/videos/{id}`。
- 鉴权：`Authorization: Bearer sk-…`。
- 创建参数：`model: "sora-2"`，`prompt`，`size`（如 `720x1280`），`seconds`（4/8/12）；可带 `input_reference` 首帧。
- 轮询建议 20s；状态机 `queued → in_progress → completed / failed / cancelled`。
- 下载：完成态返回视频下载地址。

### 3.3 Google Veo（Gemini API）
- 端点：`POST https://generativelanguage.googleapis.com/v1beta/models/{model}:predictLongRunning`；轮询 `GET /v1beta/{name}`。
- 鉴权：头 `x-goog-api-key: {GEMINI_API_KEY}`（**不是 Bearer**）。
- 创建体：`instances: [{prompt, image?(inlineData), lastFrame?, video?(续写)}]` + `parameters: {aspectRatio, resolution, durationSeconds, sampleCount, numberOfVideos}`。
- 轮询建议 10s；`done=true` 后先看 `error`（完成≠成功），再取 `response.generateVideoResponse.generatedSamples[0].video.uri` 下载（下载也带 api-key 头、跟随重定向）。
- 工程要点：operation name 落库可断点续查；重复提交前做幂等（避免重复计费）。

### 3.4 可灵 Kling
- 端点（2.6 协议）：`POST https://api-singapore.klingai.com/image-to-video/kling-2.6`（文生视频为 `/text-to-video/kling-2.6`）。
- 鉴权：`Authorization: Bearer {KLING_API_KEY}`。
- 创建体（2.6 新协议）：
  ```json
  {
    "contents": [
      {"type": "prompt", "text": "…(≤2500字)"},
      {"type": "first_frame", "url": "https://…jpg 或 base64"},
      {"type": "voice", "voice_id": "…", "id": "1"}
    ],
    "settings": {"audio": "native|off", "resolution": "720p|1080p", "duration": 5},
    "options": {"callback_url": "…", "external_task_id": "…", "watermark_info": {"enabled": false}}
  }
  ```
  关键约束：首尾帧同时给 → 仅 1080p；audio=native → 仅 1080p；首帧图 ≥300px、宽高比 1:2.5~2.5:1、≤50MB；voice 最多 2 个且指定 voice 时 audio 不能为 off。
- 旧版（1.5/1.6/2.1）：`{"model":"kling","task_type":"video_generation","input":{"prompt","image_url","cfg_scale"(0~1，推荐0.5),"duration":5|10,"aspect_ratio","camera_control"},"mode":"std|pro","version":"2.1"}`。
- 查询：`GET /tasks`（带 status/product_type 过滤器）或按任务 id；状态 `submitted → processing → succeeded/failed`；也支持 `callback_url` 回调，可替代轮询。

### 3.5 阿里万相 Wan（百炼 DashScope）
- 端点（各地域不同，北京示例）：`POST https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis`。
- 鉴权：`Authorization: Bearer $DASHSCOPE_API_KEY` + **必带头 `X-DashScope-Async: enable`**（HTTP 仅支持异步）。
- 创建体：
  ```json
  {
    "model": "wan2.7-i2v-2026-04-25",
    "input": {"prompt": "…", "media": [{"type": "first_frame", "url": "…"}]},
    "parameters": {"resolution": "720P", "ratio": "9:16", "duration": 10, "prompt_extend": false, "watermark": true}
  }
  ```
  模型族：`wan2.7-t2v`（文生视频）/ `wan2.7-i2v`（图生视频：首帧、首尾帧、续写）/ `wan2.7-r2v`（多模态参考）。
- 轮询：`GET …/api/v1/tasks/{task_id}`，建议 15s；状态 `PENDING → RUNNING → SUCCEEDED/FAILED`；结果在 `output.video_url`。
- 工程要点：task_id 24h 有效；OSS 素材需先换临时 URL；失败不计费。

---

## 4. 客户快速配置指南（不改代码路径）

> 目标：接入一个新视频模型后，控制中心「AI 视频生成配置」的下拉框自动出现，选中即用。

### 步骤 1 — 在 `config.yaml` 注册模型
给目标供应商（或自定义中转）加一条 `configured_models`，`category` 必须为 `video`（`core/llm.classify_model` 按 id 前缀识别，含 video/sora/veo/kling/wan 等的自动归为 video，显式写 category 更稳）：

```yaml
gateway:
  providers:
    kling:                                # 示例：直连可灵（原生协议需 §5 扩展；走中转则用 custom）
      base_url: https://api-singapore.klingai.com
      model: kling-2.6
      name: 可灵 Kling
      configured_models:
        - {id: kling-2.6, name: 可灵 2.6（5/10s，720p/1080p）, category: video, is_enabled: true}
        - {id: kling-2.5, name: 可灵 2.5, category: video, is_enabled: true}
    sora:                                 # 示例：OpenAI Sora（走 OpenAI 兼容 /v1 即可命中 P1/P2）
      base_url: https://api.openai.com/v1
      model: sora-2
      name: OpenAI Sora
      configured_models:
        - {id: sora-2, name: Sora 2（4/8/12s 带音频）, category: video, is_enabled: true}
    veo:                                  # 示例：Gemini Veo（原生 LRO 需 §5 扩展；走兼容层则直接可用）
      base_url: https://generativelanguage.googleapis.com/v1beta
      model: veo-3.1-generate-preview
      name: Google Veo
      configured_models:
        - {id: veo-3.1-generate-preview, name: Veo 3.1（4/8s，原生音频）, category: video, is_enabled: true}
    wan:                                  # 示例：阿里万相（原生异步需 §5 扩展）
      base_url: https://dashscope.aliyuncs.com/api/v1
      model: wan2.7-i2v-2026-04-25
      name: 阿里百炼万相
      configured_models:
        - {id: wan2.7-i2v-2026-04-25, name: 万相 2.7 图生视频（2-15s）, category: video, is_enabled: true}
```

### 步骤 2 — 在 `.env` 配 Key（命名固定规则）
系统按 `MEDIAFLOW_KEY_{供应商ID大写}` 读取：

```
MEDIAFLOW_KEY_KLING=jk_xxx
MEDIAFLOW_KEY_SORA=sk-xxx
MEDIAFLOW_KEY_VEO=AIzaXxx
MEDIAFLOW_KEY_WAN=sk-xxx        # 百炼 DashScope Key
```
（当前激活供应商也可用 `MEDIAFLOW_APIPOOL_KEY` 兜底。）

### 步骤 3 — 指定 Agent 用哪个模型（二选一）
- 全局路由：`config.yaml` → `agent_routing.video: "供应商id/模型id"`（或单写模型 id）；
- 实例级：`data/ai_video_config.json` → `video_model`（UI 下拉框保存的就是它，格式 `供应商/模型`）。

### 步骤 4 — 重启并验证
```bash
# 重启服务（18790）与网关（8787）后：
curl -s http://127.0.0.1:18790/api/models/providers | python3 -c "import sys,json; d=json.load(sys.stdin); [print(p['id'], [m['id'] for m in p['models'] if m['category']=='video'], '有Key' if p['has_key'] else '缺Key') for p in d['providers'].values()]"
```
- 下拉框出现新模型 = 配置成功；
- 点一次「AI 视频生成」，看服务端日志 `[ad_video] 视频任务已创建 / 视频片段下载完成` 即全链路通；
- 503 → 队列满退避重试中；401 → Key 没配或写错；`不是视频生成模型` → category 没标 video。

### 步骤 5（中转层方案，零代码）
若供应商原生协议是 P4/P5/P6，可先用 OpenAI 兼容中转（OneAPI / 硅基流动 / 自研网关）把该模型包装成 `/v1` 端点暴露视频任务接口，然后**步骤 1–4 原样执行**，`base_url` 指向中转层即可。这是当前最快的上线方式。

---

## 5. 扩展指南：原生协议加分支（需要改代码时）

在 `core/ad_video.py::_call_video_model` 的协议识别区按 base_url 特征插入分支，模板（以万相为例）：

```python
# ── N. 万相/DashScope 异步任务协议 ─────────────────────────
if "dashscope.aliyuncs.com" in base or "maas.aliyuncs.com" in base:
    r = client.post(f"{base}/services/aigc/video-generation/video-synthesis",
                    json={"model": model,
                          "input": {"prompt": prompt},
                          "parameters": {"resolution": "720P", "duration": min(duration_s, 15)}},
                    headers={**headers, "X-DashScope-Async": "enable"})
    task_id = r.json()["output"]["task_id"]
    for _ in range(60):                       # 15s × 60 ≈ 15 分钟上限
        _t.sleep(15)
        pr = client.get(f"{base}/tasks/{task_id}", headers=headers)
        st = pr.json()["output"]["task_status"]
        if st == "SUCCEEDED":
            out_path.write_bytes(client.get(pr.json()["output"]["video_url"]).content)
            return True
        if st == "FAILED":
            info["last_error"] = f"万相任务失败: {pr.json()}"
            return False
    return False
```

新增分支时同步做三件事：
1. 按 §2 矩阵做**参数钳制**（时长就近取允许档、画幅/分辨率枚举校验、音频限制）；
2. 轮询间隔与超时按 §3 各节取值（别 1s 猛轮，会被限流）；
3. 失败信息写 `info["last_error"]`（用户可见），并在 `问题修复记录.md` 记一笔。

---

## 6. 常见问题（FAQ）

| 现象 | 原因 | 处理 |
|------|------|------|
| 建任务 400「字段不识别」 | 给 Agnes 传了 duration/seconds | 去掉时长字段（Flash 固定 5s） |
| 建任务 405/404 | base_url 未以 `/v1` 结尾且非 P2 路径 | 检查 §4 步骤 1 的 base_url |
| 一直 503 | 上游队列满/无渠道 | 系统自动 20s×5 退避；仍失败换渠道或模型档 |
| 401 | Key 缺失或错 | 查 `.env` 的 `MEDIAFLOW_KEY_{PID}`；用 §4 步骤 4 的探针看 `has_key` |
| 「不是视频生成模型」 | 模型 category 非 video | 注册时写 `category: video` 或 id 含 video/sora/veo/kling/wan |
| Veo/Kling 轮询没反应 | 轮询端点写错（LRO 用 operation name，Kling 用 task_id） | 按 §3.3 / §3.4 修正 |
| 画面比例不对 | 传了首帧图（万相/Kling 尾帧场景 ratio 随首帧） | 首帧素材宽高比与目标一致 |

---

*调研来源：OpenAI Sora 官方文档（含 Azure Foundry 镜像）、Google Gemini API 视频生成文档、Kling AI Open Platform API 参考（2.6 新协议 + 旧版字段）、阿里云百炼万相 2.7 API 参考。各档位随官方迭代变动，接入前以供应商最新文档为准。*
