import asyncio
import os
from agents.flow_validator.orchestrator import run


class FlowValidatorWorker:
    interval = int(os.environ.get("FLOW_VALIDATOR_INTERVAL", 900))  # 15min default

    async def start(self):
        print(f"[FlowValidatorWorker] started — interval={self.interval}s")
        while True:
            try:
                await asyncio.to_thread(run)
            except Exception as e:
                print(f"[FlowValidatorWorker] error: {e}")
            await asyncio.sleep(self.interval)
