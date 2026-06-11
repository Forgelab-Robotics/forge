"""运行时诊断计数与聚合日志。"""

from __future__ import annotations


class RuntimeDiagnostics:
    """按 tick 聚合遥操安全门控事件，避免高频日志刷屏。"""

    def __init__(self, enabled: bool, log_interval_ticks: int, logger) -> None:
        self.enabled = enabled
        self.log_interval_ticks = max(1, int(log_interval_ticks))
        self.logger = logger
        self.tick_count = 0
        self.counters: dict[str, int] = {}
        self.details: dict[str, str] = {}

    def inc(self, name: str, ctrl_id: str | None = None) -> None:
        if not self.enabled:
            return
        key = f"{ctrl_id}.{name}" if ctrl_id else name
        self.counters[key] = self.counters.get(key, 0) + 1

    def record_detail(self, name: str, detail: str, ctrl_id: str | None = None) -> None:
        if not self.enabled or not detail:
            return
        key = f"{ctrl_id}.{name}" if ctrl_id else name
        self.details[key] = detail

    def maybe_log(self) -> None:
        if not self.enabled:
            return
        self.tick_count += 1
        if self.tick_count % self.log_interval_ticks != 0 or not self.counters:
            return
        payload = ", ".join(
            f"{key}={value}" for key, value in sorted(self.counters.items())
        )
        if self.details:
            detail_payload = "; ".join(
                f"{key}: {value}" for key, value in sorted(self.details.items())
            )
            payload = f"{payload} | details: {detail_payload}"
        self.logger.info("[teleop_diagnostics] %s", payload)
        self.counters.clear()
        self.details.clear()
