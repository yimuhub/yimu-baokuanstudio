# SPDX-License-Identifier: BUSL-1.1
"""大厂级结构化日志与链路追踪组件（支持 request_id / user_id / 耗时度量）。"""
from __future__ import annotations

import contextvars
import json
import logging
import time
from typing import Any

TRACE_ID_VAR: contextvars.ContextVar[str] = contextvars.ContextVar("yimu_trace_id", default="-")
USER_ID_VAR: contextvars.ContextVar[str] = contextvars.ContextVar("yimu_log_user_id", default="-")


class StructuredLogger:
    """结构化业务日志器：输出统一键值对与 JSON 事件流，便于 ELK / SLS 采集。"""

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def _format(self, event: str, **fields: Any) -> str:
        payload = {
            "ts": round(time.time(), 3),
            "event": event,
            "trace_id":TRACE_ID_VAR.get(),
            "user_id":USER_ID_VAR.get(),
            **fields,
        }
        return json.dumps(payload, ensure_ascii=False)

    def info(self, event: str, **fields: Any) -> None:
        self._logger.info(self._format(event, **fields))

    def warning(self, event: str, **fields: Any) -> None:
        self._logger.warning(self._format(event, **fields))

    def error(self, event: str, **fields: Any) -> None:
        self._logger.error(self._format(event, **fields))


def get_logger(name: str) -> StructuredLogger:
    return StructuredLogger(name)
