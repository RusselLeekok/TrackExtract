from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import exports, media, subtitles, tasks
from app.config import get_settings
from app.database import init_db

settings = get_settings()

app = FastAPI(title="Video Audio Subtitle Track Extractor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(media.router)
app.include_router(tasks.router)
app.include_router(exports.router)
app.include_router(subtitles.router)
