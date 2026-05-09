from __future__ import annotations

import argparse
import asyncio

from workers.flow_validator_worker import FlowValidatorWorker
from workers.health_check_worker import HealthCheckWorker
from workers.kb_sync_worker import KbSyncWorker
from workers.n8n_mirror_worker import N8nMirrorWorker


WORKERS = {
    "flow_validator": FlowValidatorWorker,
    "n8n_mirror": N8nMirrorWorker,
    "health_check": HealthCheckWorker,
    "kb_sync": KbSyncWorker,
}


async def _run(selected: list[str]) -> None:
    tasks = [asyncio.create_task(WORKERS[name]().start()) for name in selected]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Brain AI background workers.")
    parser.add_argument("--all", action="store_true", help="Run all workers.")
    parser.add_argument(
        "--worker",
        action="append",
        choices=sorted(WORKERS.keys()),
        help="Run one or more specific workers.",
    )
    args = parser.parse_args()

    selected = sorted(WORKERS.keys()) if args.all or not args.worker else args.worker
    asyncio.run(_run(selected))


if __name__ == "__main__":
    main()
