import os
import time
import httpx
from datetime import datetime, timezone
from workers.base_worker import BaseWorker
from services import supabase_client, n8n_client, sre_logger


class HealthCheckWorker(BaseWorker):
    name = "HealthCheckWorker"
    interval = int(os.environ.get("HEALTH_CHECK_INTERVAL", 120))

    def _run_cycle(self):
        checks = [
            ("supabase",  self._check_supabase),
            ("n8n",       self._check_n8n),
            ("airtable",  self._check_airtable),
            ("anthropic", self._check_anthropic),
        ]
        results = {}
        for service, fn in checks:
            try:
                ok, ms = fn()
                status = "healthy" if ok else "down"
                err = None if ok else "connection failed"
            except Exception as exc:
                ok, ms, status = False, -1, "down"
                err = str(exc)
                sre_logger.error(self.name, f"{service} check raised: {exc}", exc)

            results[service] = status
            try:
                supabase_client.upsert_integration_status({
                    "service": service,
                    "status": status,
                    "response_ms": ms,
                    "last_check": datetime.now(timezone.utc).isoformat(),
                    "error_message": err,
                })
            except Exception as exc:
                sre_logger.error(self.name, f"failed to persist {service} health status: {exc}", exc)

        summary = " | ".join(f"{s}={v}" for s, v in results.items())
        sre_logger.info(self.name, f"health: {summary}")

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
            return r.status_code == 200, int((time.monotonic() - t0) * 1000)

    def _check_anthropic(self) -> tuple[bool, int]:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return False, -1
        t0 = time.monotonic()
        with httpx.Client(timeout=5) as client:
            r = client.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            )
            return r.status_code == 200, int((time.monotonic() - t0) * 1000)
