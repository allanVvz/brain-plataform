import asyncio
import logging
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from utils.env import get_backend_env, validate_backend_env
from utils.tls import configure_trust_store

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
except ImportError as exc:
    raise RuntimeError(
        "FastAPI nao instalado. Execute 'pip install -r requirements.txt' dentro de /api."
    ) from exc

load_dotenv()
configure_trust_store()

from middleware.auth import auth_middleware
from routes import auth, health, process, insights, leads, messages, kb, personas, integrations, logs, knowledge, pipeline, kb_intake, generation, wa_validator, graph, marketing, audiences
from workers.flow_validator_worker import FlowValidatorWorker
from workers.n8n_mirror_worker import N8nMirrorWorker
from workers.health_check_worker import HealthCheckWorker
from workers.kb_sync_worker import KbSyncWorker

logger = logging.getLogger("ai-brain.startup")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = validate_backend_env()
    if missing:
        msg = "Missing required backend envs: " + ", ".join(missing)
        logger.error(msg)
        raise RuntimeError(msg)
    logger.info("Backend env validation OK.")
    env = get_backend_env()
    tasks: list[asyncio.Task] = []
    if env["run_embedded_workers"]:
        workers = [
            FlowValidatorWorker(),
            N8nMirrorWorker(),
            HealthCheckWorker(),
            KbSyncWorker(),
        ]
        tasks = [asyncio.create_task(w.start()) for w in workers]
        logger.warning("RUN_EMBEDDED_WORKERS enabled; background workers started inside API process.")
    else:
        logger.info("RUN_EMBEDDED_WORKERS disabled; API booting without background workers.")
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Brain AI", version="1.0.0", lifespan=lifespan)

env = get_backend_env()
allowed_origins = env["allowed_origins"]
logger.info("CORS origins: %s", ", ".join(allowed_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(auth_middleware)

app.include_router(auth.router)
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
app.include_router(graph.router)
app.include_router(marketing.router)
app.include_router(audiences.router)
