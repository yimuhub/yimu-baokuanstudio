# SPDX-License-Identifier: BUSL-1.1
"""商业化订阅、下单与卡密核销契约模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CreateOrderRequest(BaseModel):
    plan: str = Field(..., description="套餐代码：pro 或 studio")


class RedeemCodeRequest(BaseModel):
    code: str = Field("", description="卡密兑换码")
    cdkey: str = Field("", description="兼容字段 cdkey")


class CancelOrderRequest(BaseModel):
    reason: str = Field("用户主动取消", description="取消原因")
