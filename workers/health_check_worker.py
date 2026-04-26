import asyncio
import os
import time
import httpx
from services import supabase_client, n8n_client
from datetime import datetime, timezone


class HealthCheckWorker:
    interval = int(os.environ.get("HEALTH_CHECK_INTERVAL", 120))  # 2min default

    async def start(self):
        print(f"[HealthCheckWorker] started — interval={self.interval}s")
        while True:
            try:
                await asyncio.to_thread(self._check_all)
            except Exception as e:
                print(f"[HealthCheckWorker] error: {e}")
            await asyncio.sleep(self.interval)

    def _check_all(self):
        checks = [
            ("supabase", self._check_supabase),
            ("n8n", self._check_n8n),
            ("airtable", self._check_airtable),
            ("openai", self._check_openai),
        ]
        for service, fn in checks:
            try:
                status, ms = fn()
                supabase_client.upsert_integration_status({
                    "service": service,
                    "status": "healthy" if status else "down",
                    "response_ms": ms,
                    "last_check": datetime.now(timezone.utc).isoformat(),
                    "error_message": None if status else "connection failed",
                })
            except Exception as e:
                supabase_client.upsert_integration_status({
                    "service": service,
                    "status": "down",
                    "response_ms": -1,
                    "last_check": datetime.now(timezone.utc).isoformat(),
                    "error_message": str(e),
                })

    def _check_supabase(self) -> tuple[bool, int]:
        t0 = time.monotonic()
        supabase_client.get_personas()
        return True, int((time.monotonic() - t0) * 1000)

    def _check_n8n(self) -> tuple[bool, int]:
        return n8n_client.ping()

    def _check_airtable(self) -> tuple[bool, int]:
        airtable_key = os.environ.get("AIRTABLE_API_KEY", "")
        base_id = os.environ.get("AIRTABLE_BASE_ID", "")
        if not airtable_key or not base_id:
            return False, -1
        t0 = time.monotonic()
        with httpx.Client(timeout=5) as client:
            r = client.get(
                f"https://api.airtable.com/v0/{base_id}/Leads",
                headers={"Authorization": f"Bearer {airtable_key}"},
                params={"maxRecords": 1},
            )
            ms = int((time.monotonic() - t0) * 1000)
            return r.status_code == 200, ms

    def _check_openai(self) -> tuple[bool, int]:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return False, -1
        t0 = time.monotonic()
        with httpx.Client(timeout=5) as client:
            r = client.get("https://api.anthropic.com/v1/models", headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"})
            ms = int((time.monotonic() - t0) * 1000)
            return r.status_code == 200, ms
