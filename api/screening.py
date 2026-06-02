"""Core sanctions-screening logic extracted from the original Streamlit app.

This module is UI-agnostic: it loads/merges the sanction databases, normalizes
and enriches the data, and exposes a `screen()` function returning plain Python
dicts that any transport layer (FastAPI, CLI, tests) can serialize.

The DataFrame is loaded once at module import and cached for the lifetime of the
serverless instance (re-used across warm invocations).
"""

from __future__ import annotations

import os
import re
import threading
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
from rapidfuzz import fuzz, process

# =========================
# 0) 编号类识别正则 (ID-token regexes)
# =========================
IMO_ONLY_RE = re.compile(r"^\d{7}$")
MMSI_ONLY_RE = re.compile(r"^\d{9}$")
IMO_TOKEN_RE = re.compile(r"\bIMO\D*([0-9]{7})\b", re.I)
MMSI_TOKEN_RE = re.compile(r"\bMMSI\D*([0-9]{9})\b", re.I)

# Remote fallbacks (mirror the original Streamlit app).
GLOBAL_CSV_URL = "https://raw.githubusercontent.com/benkiwsun/sanctions-screening-tool/main/global_sanctions_database.csv"
CHINA_CSV_URL = "https://raw.githubusercontent.com/benkiwsun/sanctions-screening-tool/main/china_mfa_sanctions_database.csv"

GLOBAL_CSV_NAME = "global_sanctions_database.csv"
CHINA_CSV_NAME = "china_mfa_sanctions_database.csv"

# Columns we always guarantee exist on the working DataFrame.
ENSURE_COLS = ["Aliases", "Programs", "Country", "Source_Agency", "Type", "Details", "IMO", "MMSI"]
NORM_COLS = ["Name", "Aliases", "Programs", "Country", "Source_Agency", "Type", "Details", "IMO", "MMSI"]
OUTPUT_COLS = ["Score", "Name", "Aliases", "IMO", "MMSI", "Source_Agency", "Programs", "Country", "Type", "Details"]

BEIJING_TZ = timezone(timedelta(hours=8))


# =========================
# helpers
# =========================
def _norm_series(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.strip()


def _safe_upper(x: str) -> str:
    return (x or "").strip().upper()


def extract_imo(text: str) -> str:
    if not text:
        return ""
    m = IMO_TOKEN_RE.search(str(text))
    return m.group(1) if m else ""


def extract_mmsi(text: str) -> str:
    if not text:
        return ""
    m = MMSI_TOKEN_RE.search(str(text))
    return m.group(1) if m else ""


def _candidate_paths(file_name: str) -> List[Path]:
    """Return likely on-disk locations for a bundled CSV.

    Vercel places `includeFiles` relative to the project root, but the function's
    CWD is not guaranteed, so we probe several sensible locations.
    """
    here = Path(__file__).resolve()
    roots = [
        Path.cwd(),
        here.parent,            # /api
        here.parent.parent,     # project root
        Path("/var/task"),      # Vercel lambda task root
        Path("/var/task/api"),
    ]
    seen: set[str] = set()
    out: List[Path] = []
    for r in roots:
        p = (r / file_name)
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _local_path(file_name: str) -> Optional[Path]:
    for p in _candidate_paths(file_name):
        if p.exists():
            return p
    return None


# =========================
# 1) Data loading (local file first, GitHub fallback)
# =========================
def _fetch_csv(file_name: str, url: str) -> pd.DataFrame:
    local = _local_path(file_name)
    if local is not None:
        try:
            return pd.read_csv(local, dtype=str, low_memory=False)
        except Exception:
            pass
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        head = resp.text[:200].lstrip().lower()
        if head.startswith("<!doctype html") or head.startswith("<html"):
            return pd.DataFrame()
        from io import BytesIO

        return pd.read_csv(BytesIO(resp.content), dtype=str, low_memory=False)
    except Exception:
        return pd.DataFrame()


def _build_dataframe() -> pd.DataFrame:
    df_global = _fetch_csv(GLOBAL_CSV_NAME, GLOBAL_CSV_URL)
    df_china = _fetch_csv(CHINA_CSV_NAME, CHINA_CSV_URL)

    frames = [d for d in (df_global, df_china) if not d.empty]
    if not frames:
        return pd.DataFrame(columns=NORM_COLS + ["__search_text"])

    df = pd.concat(frames, ignore_index=True)

    # Ensure required columns exist.
    for c in ENSURE_COLS:
        if c not in df.columns:
            df[c] = ""

    # Normalize text columns.
    for c in NORM_COLS:
        df[c] = _norm_series(df[c])

    df["Name"] = df["Name"].str.upper()

    # Backfill IMO / MMSI from a combined text blob where missing.
    blob_for_id = (df["Name"] + " ; " + df["Aliases"] + " ; " + df["Details"]).astype(str)
    df.loc[df["IMO"].eq(""), "IMO"] = blob_for_id[df["IMO"].eq("")].apply(extract_imo)
    df.loc[df["MMSI"].eq(""), "MMSI"] = blob_for_id[df["MMSI"].eq("")].apply(extract_mmsi)

    df["__search_text"] = (
        df["Name"] + " ; " + df["Aliases"] + " ; " + df["Details"]
    ).astype(str).str.upper()

    return df


_DF: Optional[pd.DataFrame] = None
_DF_LOCK = threading.Lock()


def get_dataframe() -> pd.DataFrame:
    """Lazily build & cache the merged DataFrame (thread-safe)."""
    global _DF
    if _DF is None:
        with _DF_LOCK:
            if _DF is None:
                _DF = _build_dataframe()
    return _DF


@lru_cache(maxsize=1)
def get_source_counts() -> Dict[str, int]:
    df = get_dataframe()
    if df.empty or "Source_Agency" not in df.columns:
        return {}
    return {str(k): int(v) for k, v in df["Source_Agency"].value_counts().to_dict().items()}


def get_sync_time() -> str:
    """Beijing-time mtime of the global DB (falls back to now)."""
    local = _local_path(GLOBAL_CSV_NAME)
    try:
        if local is not None:
            mtime = os.path.getmtime(local)
            return datetime.fromtimestamp(mtime, tz=BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")


# =========================
# 2) Conclusion rating (shared with UI)
# =========================
def rate_conclusion(max_score: Optional[float], hit_count: int) -> Dict[str, str]:
    """Map the top score to a rating level + human-readable conclusion."""
    if max_score is None:
        return {
            "level": "clear",
            "conclusion": "系统结论：未命中，建议放行",
        }
    if max_score == 100:
        return {
            "level": "hit",
            "conclusion": "系统结论：命中制裁，限制交易，请注意！",
        }
    if max_score >= 90:
        return {
            "level": "suspected",
            "conclusion": f"系统结论：发现 {hit_count} 条疑似命中，需要进一步排查",
        }
    if max_score >= 80:
        return {
            "level": "low",
            "conclusion": f"系统结论：发现 {hit_count} 条低度相关，请进一步检查",
        }
    return {
        "level": "below_threshold",
        "conclusion": "系统结论：未发现疑似命中，相似度均低于设定阈值。建议放行交易。",
    }


# =========================
# 3) Screening engine (3-stage match)
# =========================
def _rows_to_records(results_df: pd.DataFrame) -> List[Dict[str, Any]]:
    cols = [c for c in OUTPUT_COLS if c in results_df.columns]
    records: List[Dict[str, Any]] = []
    for _, row in results_df[cols].iterrows():
        rec: Dict[str, Any] = {}
        for c in cols:
            val = row.get(c, "")
            if c == "Score":
                rec[c] = float(val)
            else:
                sval = "" if val is None else str(val)
                rec[c] = "" if sval.lower() in ("nan", "none") else sval
        records.append(rec)
    return records


def screen(query: str, threshold: int = 90) -> Dict[str, Any]:
    """Run the 3-stage screening and return a JSON-serializable result."""
    df = get_dataframe()
    total_records = int(len(df))
    source_counts = get_source_counts()
    sync_time = get_sync_time()

    base: Dict[str, Any] = {
        "query": query,
        "threshold": threshold,
        "total_records": total_records,
        "source_counts": source_counts,
        "sync_time": sync_time,
    }

    if df.empty:
        return {
            **base,
            "level": "error",
            "conclusion": "数据库为空：请先确认已生成并提供数据库文件。",
            "max_score": None,
            "hit_count": 0,
            "results": [],
        }

    q = (query or "").strip()
    if not q:
        return {
            **base,
            "level": "empty_query",
            "conclusion": "请输入筛查关键词。",
            "max_score": None,
            "hit_count": 0,
            "results": [],
        }

    q_up = _safe_upper(q)
    results_df = pd.DataFrame()

    # ----- Engine 1: strong logical match (pure numeric IMO/MMSI & exact) -----
    if IMO_ONLY_RE.match(q) and "IMO" in df.columns:
        hit = df[_norm_series(df["IMO"]) == q]
        if not hit.empty:
            results_df = hit.copy()
            results_df["Score"] = 100.0

    if results_df.empty and MMSI_ONLY_RE.match(q) and "MMSI" in df.columns:
        hit = df[_norm_series(df["MMSI"]) == q]
        if not hit.empty:
            results_df = hit.copy()
            results_df["Score"] = 100.0

    if results_df.empty:
        imo = extract_imo(q)
        if imo and "IMO" in df.columns:
            hit = df[_norm_series(df["IMO"]) == imo]
            if not hit.empty:
                results_df = hit.copy()
                results_df["Score"] = 100.0

    # ----- Engine 2: name "contains + fuzzy" dual track -----
    if results_df.empty:
        matched_rows: List[pd.Series] = []
        existing_indices: set = set()

        # Track 1: substring (contains) match
        mask_contains = df["__search_text"].astype(str).str.contains(re.escape(q_up), na=False)
        hit_contains = df[mask_contains]
        if not hit_contains.empty:
            for idx, row in hit_contains.iterrows():
                row_copy = row.copy()
                exact_name = str(row.get("Name", "")).strip()
                aliases = [a.strip() for a in str(row.get("Aliases", "")).split(";")]
                if q_up == exact_name or q_up in aliases:
                    row_copy["Score"] = 100.0
                else:
                    row_copy["Score"] = 99.0
                matched_rows.append(row_copy)
                existing_indices.add(idx)

        # Track 2: rapidfuzz fuzzy match
        candidates = df["__search_text"].astype(str).tolist()
        matches = process.extract(
            q_up,
            candidates,
            scorer=fuzz.WRatio,
            limit=15,
            score_cutoff=threshold,
        )
        if matches:
            for m in matches:
                row_index = m[2]
                if row_index not in existing_indices:
                    row_copy = df.iloc[row_index].copy()
                    row_copy["Score"] = round(m[1], 1)
                    matched_rows.append(row_copy)
                    existing_indices.add(row_index)

        if matched_rows:
            results_df = pd.DataFrame(matched_rows)
            results_df = results_df.sort_values(by="Score", ascending=False).head(10)

    # ----- Result assembly -----
    if results_df.empty:
        rating = rate_conclusion(None, 0)
        return {
            **base,
            "level": rating["level"],
            "conclusion": rating["conclusion"],
            "max_score": None,
            "hit_count": 0,
            "results": [],
        }

    # Cap displayed rows to 10 (matches original UI).
    results_df = results_df.head(10)
    max_score = float(results_df["Score"].max())
    hit_count = int(len(results_df))
    rating = rate_conclusion(max_score, hit_count)

    return {
        **base,
        "level": rating["level"],
        "conclusion": rating["conclusion"],
        "max_score": max_score,
        "hit_count": hit_count,
        "results": _rows_to_records(results_df),
    }
