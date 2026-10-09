from fastapi import FastAPI

from freight_intel.api.routes import auth, health, users


def create_app() -> FastAPI:
    """App factory: tests and uvicorn both build the app the same way."""
    app = FastAPI(title="FreightLens API")
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    return app


app = create_app()
