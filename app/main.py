from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AnyHttpUrl, BaseModel

from .crawler import crawl_page
from .db import (
    create_monitored_page,
    get_meeting,
    get_meeting_history,
    get_monitored_page,
    get_page_by_url,
    init_db,
    list_meetings,
    list_monitored_pages,
)

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

APP_ROOT = Path(__file__).resolve().parent
STATIC_DIR = APP_ROOT / "static"
DEFAULT_TIMEZONE = "Asia/Shanghai"

app = FastAPI(title="Auto Academic Info")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class PageCreate(BaseModel):
    url: AnyHttpUrl


def run_crawl_for_page(page: Dict[str, Any]) -> Dict[str, int]:
    results = crawl_page(page["id"], page["url"])
    created = sum(1 for result in results if result.created)
    changed = sum(1 for result in results if result.changed)
    return {"total": len(results), "created": created, "changed": changed}


def run_crawl_all_pages() -> Dict[str, int]:
    pages = list_monitored_pages()
    summary = {"pages": len(pages), "total": 0, "created": 0, "changed": 0}
    for page in pages:
        counts = run_crawl_for_page(page)
        summary["total"] += counts["total"]
        summary["created"] += counts["created"]
        summary["changed"] += counts["changed"]
    return summary


def seconds_until_midnight(tz_name: str) -> float:
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    now = datetime.now(tz)
    next_run = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=5, microsecond=0
    )
    return max((next_run - now).total_seconds(), 0)


async def daily_scheduler() -> None:
    while True:
        delay = seconds_until_midnight(DEFAULT_TIMEZONE)
        LOGGER.info("Next scheduled crawl in %s seconds", int(delay))
        await asyncio.sleep(delay)
        LOGGER.info("Starting scheduled crawl")
        await asyncio.to_thread(run_crawl_all_pages)


@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    asyncio.create_task(daily_scheduler())


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/add")
def add_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "add.html")


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/pages")
def get_pages() -> List[Dict[str, Any]]:
    return list_monitored_pages()


@app.post("/api/pages")
def add_page(payload: PageCreate) -> Dict[str, Any]:
    url = str(payload.url)
    try:
        return create_monitored_page(url)
    except sqlite3.IntegrityError:
        page = get_page_by_url(url)
        if not page:
            raise HTTPException(status_code=409, detail="URL already exists")
        return page


@app.post("/api/pages/{page_id}/fetch")
def fetch_page(page_id: int, background_tasks: BackgroundTasks) -> Dict[str, str]:
    page = get_monitored_page(page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    background_tasks.add_task(crawl_page, page["id"], page["url"])
    return {"status": "queued"}


@app.post("/api/crawl")
def fetch_all(background_tasks: BackgroundTasks) -> Dict[str, str]:
    background_tasks.add_task(run_crawl_all_pages)
    return {"status": "queued"}


@app.get("/api/meetings")
def get_meetings(limit: int = 200) -> List[Dict[str, Any]]:
    return list_meetings(limit=limit)


@app.get("/api/meetings/{meeting_id}")
def get_meeting_details(meeting_id: int) -> Dict[str, Any]:
    meeting = get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


@app.get("/api/meetings/{meeting_id}/history")
def meeting_history(meeting_id: int) -> List[Dict[str, Any]]:
    return get_meeting_history(meeting_id)
