from fastapi import FastAPI
from middleware.auth import auth_middleware
from routes import (agents, conversations, health, insights, leads, logs,
                    process, wa_validator)

app = FastAPI(title="Brain Conversation Runtime", version="1.0.0")
app.middleware("http")(auth_middleware)
for router in (health.router, conversations.router, agents.router,
               agents.internal_router, insights.router, leads.router,
               leads.internal_router,
               process.router,
               wa_validator.router, logs.router):
    app.include_router(router)
