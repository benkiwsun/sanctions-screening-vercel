# 全球制裁合规筛查系统 — Sanctions Screening Tool

A Vercel-ready full-stack refactor of the original Streamlit app. The UI is now a
**Next.js (React)** frontend and the screening logic runs as **Python Serverless
Functions (FastAPI)** under `/api`.

## Architecture

```
Browser ──► Next.js (app/, components/)
                │  fetch /api/*
                ▼
        Vercel Python Function (api/index.py · FastAPI)
                │  imports
                ▼
        api/screening.py  ──► loads & caches the merged CSV database
```

- **Frontend** (`app/`, `components/`, `lib/`): replicates the original Streamlit
  flow — keyword input, similarity-tolerance slider, "开始筛查" button, conclusion
  banner, results table, and the JPG 留痕报告 (audit trail) download.
- **Backend** (`api/`): the 3-stage matching engine (exact IMO/MMSI → substring →
  `rapidfuzz` fuzzy match) extracted verbatim from `sanction.py`.
- **留痕报告**: regenerated client-side via `html2canvas` (Chinese renders natively
  in-browser), so the serverless bundle stays lean — no Pillow / 19 MB font.
- **Data pipeline** (`fetch_all_lists.py` + `.github/workflows`): unchanged. It still
  builds `global_sanctions_database.csv` on a daily cron and uses the root
  `requirements.txt`.

## API endpoints

| Method | Path          | Description                                  |
| ------ | ------------- | -------------------------------------------- |
| GET    | `/api/health` | DB load status + record count                |
| GET    | `/api/stats`  | Total records, per-source counts, sync time  |
| POST   | `/api/screen` | Body `{ query, threshold }` → screening result |

## Local development

The Python functions only run under the Vercel toolchain, so use `vercel dev` to run
the frontend and backend together:

```bash
npm install
pip install -r api/requirements.txt   # optional, for editor tooling
npx vercel dev
```

Frontend-only iteration (no `/api`) can use `npm run dev`.

## Deploy

```bash
npx vercel        # preview
npx vercel --prod # production
```

### Notes / constraints
- `global_sanctions_database.csv` is ~33 MB / ~100k rows. It is bundled into the
  function via `includeFiles` in `vercel.json` and loaded **once per warm instance**.
- Function memory is set to **2048 MB** in `vercel.json` to comfortably hold the
  DataFrame; reduce it if you are on a plan with lower limits (Hobby max is 1024 MB —
  lower the value accordingly).
- Expect a multi-second cold start on the first request while the CSV loads.
# sanctions-screening-vercel
# sanctions-screening-vercel
# sanctions-screening-vercel
# sanctions-screening-vercel
# sanctions-screening-vercel
