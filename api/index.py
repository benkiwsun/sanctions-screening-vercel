"""FastAPI backend for the sanctions-screening tool (Vercel Python Function).

Exposed under /api/* via the rewrite in vercel.json. The heavy DataFrame is
loaded lazily and cached for the lifetime of the warm serverless instance.
"""

from __future__ import annotations

import os
import sys

# Ensure this file's directory (the `api/` folder) is importable regardless of
# how the runtime loads the entrypoint. On Vercel the module is imported as a
# package, so a bare `import screening` would otherwise raise ModuleNotFoundError
# and return HTTP 500 on every request.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from screening import (
    get_dataframe,
    get_source_counts,
    get_sync_time,
    screen,
)

app = FastAPI(title="Sanctions Screening API", version="1.0.0")

# Same-origin in production; permissive for local dev / proxy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter()


class ScreenRequest(BaseModel):
    query: str = Field(..., description="Counterparty name / IMO / MMSI to screen")
    threshold: int = Field(90, ge=60, le=100, description="Fuzzy match tolerance (%)")


class ScreenResult(BaseModel):
    query: str
    threshold: int
    level: str
    conclusion: str
    max_score: Optional[float] = None
    hit_count: int
    results: List[Dict[str, Any]]
    total_records: int
    source_counts: Dict[str, int]
    sync_time: str


@router.get("/health")
def health() -> Dict[str, Any]:
    df = get_dataframe()
    return {
        "status": "ok",
        "db_loaded": not df.empty,
        "total_records": int(len(df)),
    }


@router.get("/stats")
def stats() -> Dict[str, Any]:
    df = get_dataframe()
    return {
        "total_records": int(len(df)),
        "source_counts": get_source_counts(),
        "sync_time": get_sync_time(),
    }


@router.post("/screen", response_model=ScreenResult)
def screen_endpoint(req: ScreenRequest) -> Dict[str, Any]:
    return screen(req.query, req.threshold)


@router.get("/")
def root() -> Dict[str, str]:
    return {
        "service": "sanctions-screening-api",
        "docs": "GET /api/health, GET /api/stats, POST /api/screen",
    }


# Mount the routes both under /api/* (matches the frontend + vercel.json rewrite)
# and at the root, so the function works whether or not the platform strips the
# /api prefix before invoking it.
app.include_router(router, prefix="/api")
app.include_router(router)
