"""FastAPI application factory for The Catalyst backend."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_database
from .routers import register_routers


@asynccontextmanager
async def lifespan(app: FastAPI):  # pragma: no cover - startup/shutdown glue
    init_database()
    print("🔥 The Catalyst is online - FastAPI backend ready")
    yield
    print("The Catalyst backend shutting down...")


app = FastAPI(title="The Catalyst", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_routers(app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=True)
