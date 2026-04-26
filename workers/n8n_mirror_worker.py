import asyncio
import os
from services import n8n_client, supabase_client
from datetime import datetime, timezone


class N8nMirrorWorker:
    interval = int(os.environ.get("N8N_MIRROR_INTERVAL", 300))  # 5min default

    async def start(self):
        print(f"[N8nMirrorWorker] started — interval={self.interval}s")
        while True:
            try:
                await asyncio.to_thread(self._sync)
            except Exception as e:
                print(f"[N8nMirrorWorker] error: {e}")
            await asyncio.sleep(self.interval)

    def _sync(self):
        executions = n8n_client.get_executions(limit=50)
        for ex in executions:
            try:
                started = ex.get("startedAt") or ex.get("started_at")
                finished = ex.get("stoppedAt") or ex.get("finished_at")
                duration = None
                if started and finished:
                    try:
                        s = datetime.fromisoformat(started.replace("Z", "+00:00"))
                        f = datetime.fromisoformat(finished.replace("Z", "+00:00"))
                        duration = int((f - s).total_seconds() * 1000)
                    except Exception:
                        pass

                node_errors = []
                data = ex.get("data", {})
                if isinstance(data, dict):
                    for node_name, node_data in data.get("resultData", {}).get("runData", {}).items():
                        for run in (node_data or []):
                            if run.get("error"):
                                node_errors.append({"node": node_name, "error": run["error"]})

                supabase_client.upsert_n8n_execution({
                    "n8n_id": str(ex["id"]),
                    "workflow_name": ex.get("workflowData", {}).get("name") or ex.get("workflow", {}).get("name", ""),
                    "status": ex.get("status", "unknown"),
                    "started_at": started,
                    "finished_at": finished,
                    "duration_ms": duration,
                    "node_errors": node_errors,
                })
            except Exception as e:
                print(f"[N8nMirrorWorker] execution sync error: {e}")

        print(f"[N8nMirrorWorker] synced {len(executions)} executions")
