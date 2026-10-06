# SPDX-License-Identifier: BUSL-1.1
"""YIMU Gateway：OpenAI 兼容的 API 中转站（独立 FastAPI 服务）。
多上游路由 / 熔断保护 / 按 Key 配额限速 / 调用账本。
工作室自身的所有模型调用都经网关 SDK 发出（dogfooding）。"""
