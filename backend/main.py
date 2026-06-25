"""FastAPI application: chat API + static frontend.

Run with:  uvicorn backend.main:app --reload
or:        python -m backend.main
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent, config, db, lmstudio_client, tools
from .lmstudio_client import LMStudioError

app = FastAPI(title="PETIT", description="Personal AI Assistant (MVP)")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] | None = None


class ChatResponse(BaseModel):
    reply: str
    used_tools: list[dict[str, Any]] = []
    error: str | None = None


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "tools": tools.registered_names(),
        "lm_studio": lmstudio_client.health(),
    }


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    message = (req.message or "").strip()
    if not message:
        return ChatResponse(reply="", error="メッセージが空です。")

    try:
        result = agent.run(message, history=req.history)
    except LMStudioError as exc:
        return ChatResponse(reply="", error=str(exc))

    db.save_conversation(
        user_text=message,
        assistant_text=result["reply"],
        used_tools=", ".join(t["name"] for t in result["used_tools"]) or None,
    )
    return ChatResponse(reply=result["reply"], used_tools=result["used_tools"])


@app.get("/api/conversations")
def conversations(limit: int = 20) -> dict[str, Any]:
    return {"conversations": db.recent_conversations(limit=limit)}


# --- Static frontend ---------------------------------------------------------
# Mount assets under /static and serve index.html at the root.
if config.FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")

    @app.get("/")
    def index() -> Any:
        index_file = config.FRONTEND_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return JSONResponse({"detail": "frontend not built"}, status_code=404)


def main() -> None:
    import uvicorn

    uvicorn.run("backend.main:app", host=config.HOST, port=config.PORT, reload=False)


if __name__ == "__main__":
    main()
