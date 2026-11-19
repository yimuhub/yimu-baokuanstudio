# ============================================================
#  一幕·YIMU 爆款工作室 — 服务器容器化运行镜像
#  构建: docker build -t yimu-studio .
#  运行: 见 docker-compose.yml 与 deploy/cloud/README.md
#  说明: ffmpeg 由 requirements.txt 的 imageio-ffmpeg 内置提供,
#        无需 apt 安装;CJK 字体为小红书卡片/封面离线压制所需,
#        缺字体会把中文渲染成方框,必须保留。
# ============================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl 仅供排障;fonts-noto-cjk 为 Pillow 离线图形引擎渲染中文所必需
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 运行期可写目录:配置遮蔽层(config.local.yaml)/草稿产物/日志/任务
RUN mkdir -p /app/data /app/logs /app/runs \
    && useradd -m -u 10001 yimu \
    && chown -R yimu:yimu /app

USER yimu

EXPOSE 8790
VOLUME ["/app/data", "/app/logs", "/app/runs"]

# 默认仅容器内监听;对外暴露由 docker compose ports 控制。
# 网关 /v1 已内嵌于主应用,单容器即可提供 OpenAI 兼容接口。
CMD ["python", "-m", "uvicorn", "web.admin:app", "--host", "0.0.0.0", "--port", "8790"]
