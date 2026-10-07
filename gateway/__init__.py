# SPDX-License-Identifier: BUSL-1.1
"""YIMU Gateway：OpenAI 兼容的 API 中转站（独立 FastAPI 服务，WS-B 交付）。

挂载约定：WS-B 在此目录下落 gateway/main.py（uvicorn 启动，端口 8791）；
studio 侧通过 studio/gw_client（如有）或直连 http://127.0.0.1:8791 调用。
引用方一律 try/except ImportError 兜底，网关未就绪不得阻塞主服务启动。
"""
