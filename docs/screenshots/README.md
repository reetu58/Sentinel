# Screenshots

`dashboard-schematic.svg` is a **schematic** of the dashboard (not a real
capture) used in the top-level README so the layout reads at a glance.

To add **real** screenshots / a GIF, run the app locally and capture these
views, saving them here with the filenames the README references:

| File | What to capture |
|------|-----------------|
| `dashboard.png` | The full dashboard on load — RED breach banner, health tiles, band-wise PSI chart. |
| `memo.png` | The copilot panel after triggering, showing the four-part cited memo. |
| `audit.png` | The audit trail after approving, with the highlighted human-decision row. |
| `loop.gif` *(optional)* | A short recording of trigger → memo → approve → audit updating. |

Capture steps:

```bash
SENTINEL_BACKEND_MODE=demo python -m uvicorn backend.app:app --port 8000
cd frontend && npm install && npm run dev     # http://localhost:5173
```

Then screenshot the browser (or record with e.g. Kap / ScreenToGif / `ffmpeg`).
Real captures are not committed by default because they're large binaries; add
them intentionally.
