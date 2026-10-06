# SPDX-License-Identifier: BUSL-1.1
"""统一异步任务队列：排队 / 进度 / 取消 / 重试 / 超时约束。
所有长任务（采集/生图/短剧渲染）一律走队列，超时标 failed 不许永久 running。"""
