import asyncio
import os
from services import supabase_client
from services.knowledge_service import sync_from_sheets


class KbSyncWorker:
    interval = int(os.environ.get("KB_SYNC_INTERVAL", 3600))  # 1h default

    async def start(self):
        print(f"[KbSyncWorker] started — interval={self.interval}s")
        while True:
            try:
                await asyncio.to_thread(self._sync)
            except Exception as e:
                print(f"[KbSyncWorker] error: {e}")
            await asyncio.sleep(self.interval)

    def _sync(self):
        personas = supabase_client.get_personas()
        for persona in personas:
            # Only sync if this persona has an explicit spreadsheet_id configured
            spreadsheet_id = persona.get("config", {}).get("kb_spreadsheet_id")
            if not spreadsheet_id:
                continue
            try:
                count = sync_from_sheets(
                    persona_id=persona["id"],
                    spreadsheet_id=spreadsheet_id,
                )
                print(f"[KbSyncWorker] persona={persona['slug']} synced={count} entries")
            except Exception as e:
                print(f"[KbSyncWorker] persona={persona['slug']} error: {e}")
