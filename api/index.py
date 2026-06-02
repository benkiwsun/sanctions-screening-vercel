"""FastAPI backend for the sanctions-screening tool (Vercel Python Function).

Exposed under /api/* via the rewrite in vercel.json. The heavy DataFrame is
loaded lazily and cached for the lifetime of the warm serverless instance.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from screening import (
    get_dataframe,
    get_source_counts,
    get_sync_time,
    screen,
)

app = FastAPI(title="Sanctions Screening API", version="1.0.0")

# Same-origin in production; permissive for local `vercel dev` / Next dev proxy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/api/health")
def health() -> Dict[str, Any]:
    df = get_dataframe()
    return {
        "status": "ok",
        "db_loaded": not df.empty,
        "total_records": int(len(df)),
    }


@app.get("/api/stats")
def stats() -> Dict[str, Any]:
    df = get_dataframe()
    return {
        "total_records": int(len(df)),
        "source_counts": get_source_counts(),
        "sync_time": get_sync_time(),
    }


@app.post("/api/screen", response_model=ScreenResult)
def screen_endpoint(req: ScreenRequest) -> Dict[str, Any]:
    return screen(req.query, req.threshold)


# Convenience root so a bare GET /api doesn't 404.
@app.get("/api")
def root() -> Dict[str, str]:
    return {"service": "sanctions-screening-api", "docs": "/api/health, /api/stats, POST /api/screen"}
