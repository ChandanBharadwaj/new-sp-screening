import logging
import time

import structlog

from app.config import settings


def configure_logging() -> None:
    logging.basicConfig(level=settings.log_level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.log_level)),
    )


log = structlog.get_logger()


class StageTimer:
    def __init__(self) -> None:
        self._start = time.perf_counter()
        self._last = self._start
        self.stages: dict[str, int] = {}

    def mark(self, name: str) -> None:
        now = time.perf_counter()
        self.stages[name] = int((now - self._last) * 1000)
        self._last = now

    def snapshot(self) -> dict[str, int]:
        total_ms = int((time.perf_counter() - self._start) * 1000)
        out = dict(self.stages)
        out["total"] = total_ms
        return out
