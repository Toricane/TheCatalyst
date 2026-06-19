"""Router registration for The Catalyst API."""

from __future__ import annotations

from fastapi import FastAPI

from . import chat, conversations, goals, memory, system


def register_routers(app: FastAPI) -> None:
    app.include_router(system.router)
    app.include_router(chat.router)
    app.include_router(goals.router)
    app.include_router(memory.router)
    app.include_router(conversations.router)
