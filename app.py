"""Application entrypoint forwarding to the backend FastAPI app."""

from backend.app import app

__all__ = ["app"]

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=True)
