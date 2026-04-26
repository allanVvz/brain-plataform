import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from api.routes import health, process, insights, leads, messages, kb, personas, integrations, logs, knowledge, pipeline, kb_intake, generation, wa_validator
from workers.flow_validator_worker import FlowValidatorWorker
from workers.n8n_mirror_worker import N8nMirrorWorker
from workers.health_check_worker import HealthCheckWorker
from workers.kb_sync_worker import KbSyncWorker


@asynccontextmanager
async def lifespan(app: FastAPI):
    workers = [
        FlowValidatorWorker(),
        N8nMirrorWorker(),
        HealthCheckWorker(),
        KbSyncWorker(),
    ]
    tasks = [asyncio.create_task(w.start()) for w in workers]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="AI Brain", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(process.router)
app.include_router(insights.router)
app.include_router(leads.router)
app.include_router(messages.router)
app.include_router(kb.router)
app.include_router(personas.router)
app.include_router(integrations.router)
app.include_router(logs.router)
app.include_router(knowledge.router)
app.include_router(pipeline.router)
app.include_router(kb_intake.router)
app.include_router(generation.router)
app.include_router(wa_validator.router)
