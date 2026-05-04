# -*- coding: utf-8 -*-
"""
BaseWorker — resilient asyncio worker with DB-persisted error logging and backoff.

Subclass and implement _run_cycle(). The loop:
  1. Calls _run_cycle() in a thread (blocking-safe)
  2. On success → resets failure counter, sleeps interval
  3. On exception → logs ERROR to agent_logs, backs off exponentially up to 4×interval
"""
from __future__ import annotations

import asyncio
from services import sre_logger


class BaseWorker:
    name: str = "Worker"
    interval: int = 60
    _MAX_CONSECUTIVE: int = 5

    def __init__(self):
        self._failures = 0

    async def start(self) -> None:
        sre_logger.info(self.name, f"started — interval={self.interval}s")
        while True:
            try:
                await asyncio.to_thread(self._run_cycle)
                if self._failures > 0:
                    sre_logger.info(self.name, f"recovered after {self._failures} consecutive failures")
                self._failures = 0
            except Exception as exc:
                self._failures += 1
                sre_logger.error(
                    self.name,
                    f"cycle failed (consecutive={self._failures})",
                    exc,
                )
                if self._failures >= self._MAX_CONSECUTIVE:
                    backoff = min(self.interval * 4, 3600)
                    sre_logger.warn(
                        self.name,
                        f"too many consecutive failures — backing off {backoff}s",
                    )
                    await asyncio.sleep(backoff)
                    self._failures = 0
                    continue

            await asyncio.sleep(self.interval)

    def _run_cycle(self) -> None:
        raise NotImplementedError(f"{self.name}._run_cycle() must be implemented")
