# SPDX-License-Identifier: BUSL-1.1
"""V10.0.0 架构健康度与版本单一真源探针路由。"""
from __future__ import annotations

import importlib
from fastapi import APIRouter
import version

router = APIRouter(prefix="/api/v10", tags=["v10-architecture"])


@router.get("/health")
def v10_architecture_health() -> dict:
    importlib.reload(version)
    return {
        "ok": True,
        "version": version.__version__,
        "codename": getattr(version, "__codename__", "鸿蒙始"),
        "codename_en": getattr(version, "__codename_en__", "Primordial Dawn"),
        "layers": ["app", "domain", "infra", "web"],
    }
