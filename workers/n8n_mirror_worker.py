import os
from datetime import datetime, timezone
from workers.base_worker import BaseWorker
from services import n8n_client, supabase_client, sre_logger


class N8nMirrorWorker(BaseWorker):
    name = "N8nMirrorWorker"
    interval = int(os.environ.get("N8N_MIRROR_INTERVAL", 300))

    def _run_cycle(self):
        executions = n8n_client.get_executions(limit=50)
        synced = 0
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
                data = ex.get("data") or {}
                if isinstance(data, dict):
                    for node_name, node_data in data.get("resultData", {}).get("runData", {}).items():
                        for run in (node_data or []):
                            if run.get("error"):
                                node_errors.append({"node": node_name, "error": run["error"]})

                supabase_client.upsert_n8n_execution({
                    "n8n_id": str(ex["id"]),
                    "workflow_name": (ex.get("workflowData") or {}).get("name") or (ex.get("workflow") or {}).get("name", ""),
                    "status": ex.get("status", "unknown"),
                    "started_at": started,
                    "finished_at": finished,
                    "duration_ms": duration,
                    "node_errors": node_errors,
                })
                synced += 1
            except Exception as exc:
                sre_logger.error(self.name, f"failed to mirror execution id={ex.get('id')}", exc)

        sre_logger.info(self.name, f"synced {synced}/{len(executions)} executions")
