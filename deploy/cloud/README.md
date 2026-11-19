# 云端 / 服务器容器化部署说明

本目录提供一幕·YIMU 的 Docker 部署配套文件,与仓库根目录的 `Dockerfile`、`docker-compose.yml`、`.dockerignore` 配套使用。

## 快速开始

```bash
# 1. 准备环境变量(必填管理口令)
cp deploy/cloud/env.example .env
vim .env          # 修改 YIMU_ADMIN_PASSWORD 为强口令

# 2. 构建并启动
docker compose up -d --build

# 3. 查看日志 / 健康状态
docker compose logs -f
docker compose ps          # healthcheck 通过即为 healthy

# 4. 浏览器访问
open http://<服务器IP>:8790/
```

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `YIMU_ADMIN_PASSWORD` | ✅ | 管理口令,至少 8 位;未设置时管理接口 fail-closed 不开放 |
| `YIMU_ADMIN_SESSION_SECRET` | 建议 | 会话签名密钥,`openssl rand -hex 32` 生成 |
| `YIMU_MULTIUSER` | — | `1`=多用户模式(服务器默认,环回免密关闭);`0`=单机自用 |
| `YIMU_PORT` | — | 对外端口,默认 8790 |

## 数据持久化与备份

| 卷 | 内容 |
|---|---|
| `/app/data` | SQLite 数据库、运行时配置遮蔽层 `config.local.yaml`、草稿产物、密钥文件 |
| `/app/logs` | 运行日志 |
| `/app/runs` | 任务运行产物 |

备份示例:

```bash
docker run --rm -v yimu-studio_yimu_data:/data -v "$PWD":/backup alpine \
  tar czf /backup/yimu-data-$(date +%F).tgz -C /data .
```

> 卷名以 `docker volume ls` 实际输出为准(compose 项目名会影响前缀)。

## 升级

```bash
git pull
docker compose up -d --build
```

运行时配置存于数据卷 `config.local.yaml`,升级镜像不会覆盖;出厂 `config.yaml` 更新时按仓库的配置遮蔽机制生效。

## 安全基线

- 管理口令必填,弱口令会被 fail-closed 拒绝(`core/auth.py`);
- 多用户模式下环回免密自动关闭,且 SSRF 出站防护强制拒绝私网地址(`core/outbound_guard.py`);
- 建议在生产前置 Nginx/Caddy 反向代理并启用 TLS,容器端口仅绑定 `127.0.0.1:8790:8790`(修改 compose `ports` 为 `"127.0.0.1:8790:8790"`);

## 常见问题

- **绑定挂载权限报错**:镜像默认以非 root 用户(uid 10001)运行,若把卷改为宿主机目录绑定挂载,请 `chown -R 10001:10001 <目录>` 或临时在 compose 中加 `user: "0:0"`。
- **中文卡片字体方框**:镜像已内置 `fonts-noto-cjk`,请勿基于精简基础镜像自行重构 Dockerfile 时删掉它。
- **OpenAI 兼容网关**:`/v1/*` 已内嵌主应用,无需第二个容器;如需独立网关进程监听 8791,参考 `gateway/main.py` 自行增加 service。
