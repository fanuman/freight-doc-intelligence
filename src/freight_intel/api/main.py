from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from freight_intel.api.routes import auth, documents, health, users
from freight_intel.pipeline.checkpoint import close_checkpointer


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    close_checkpointer()  # at shutdown: close the connections that hold paused reviews


def create_app() -> FastAPI:
    """App factory: tests and uvicorn both build the app the same way."""
    app = FastAPI(title="FreightLens API", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(documents.router)
    return app


app = create_app()
