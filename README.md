# auto-academic-info

FastAPI-based monitor for academic meeting pages. Add a URL, crawl daily at midnight,
extract meeting details, and track history of edits.

## Features

- Add meeting list or detail URLs to monitor.
- Daily crawl (midnight local time) plus manual crawl.
- Extract time, location, speaker, topic, abstract, and online link.
- Filter meetings to today or later (based on parsed date).
- Online search enrichment for speaker introduction (best-effort).
- History tracking when meeting details change.

## Quick Start

1. Install dependencies:
   - `pip install -r requirements.txt`
2. Start the API + dashboard:
   - `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
3. Open the dashboard:
   - `http://localhost:8000`

## API Endpoints

- `GET /api/pages` list monitored pages
- `POST /api/pages` add a URL
- `POST /api/pages/{page_id}/fetch` crawl a single page now
- `POST /api/crawl` crawl all monitored pages now
- `GET /api/meetings` list tracked meetings (use `upcoming_only=false` to show all)
- `GET /api/meetings/{meeting_id}` meeting details
- `GET /api/meetings/{meeting_id}/history` change history

## Data Storage

SQLite database is stored at `app/data/auto_academic.db`. Records are updated when
content changes, and previous snapshots are stored in the history table.

## Notes

- Speaker intro search uses DuckDuckGo HTML results and may fail if blocked.
- Extraction is heuristic and may require tuning per site.
- Meetings without a parseable date are hidden when `upcoming_only=true`.
