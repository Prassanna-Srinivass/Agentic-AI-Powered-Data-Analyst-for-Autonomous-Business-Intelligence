# Agentic AI-Powered Data Analyst for Autonomous Business Intelligence

A conversational analytics system that plans and executes bounded multi-step investigations over uploaded data, adapts to findings, and presents verified, explainable business insights.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (React + Vite)                  │
│  Chat workspace · Dataset profile · Analysis progress · Charts  │
└──────────────────────────────┬──────────────────────────────────┘
                               │ REST API
┌──────────────────────────────▼──────────────────────────────────┐
│                     Backend (FastAPI + Python)                   │
│                                                                  │
│  ┌──────────┐  ┌───────────────┐  ┌───────────────────────────┐ │
│  │ API Layer│  │ Orchestrator  │  │   Analytics Tools         │ │
│  │ datasets │  │ LangGraph     │  │ profiling · comparisons   │ │
│  │ analysis │  │ state machine │  │ data_quality · anomalies  │ │
│  └──────────┘  └───────────────┘  └───────────────────────────┘ │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────────────────────────┐ │
│  │ Verification     │  │ Reporting                            │ │
│  │ reconciliation   │  │ charts · summaries · export          │ │
│  └──────────────────┘  └──────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Defining Features

1. **Evidence-backed analytics** — Every important number traces to a deterministic calculation.
2. **Adaptive investigation** — The next analytical step depends on earlier findings.
3. **One-week scope discipline** — A single orchestrator and small set of reliable tools.

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React + TypeScript + Vite |
| UI & Charts | Tailwind CSS + Plotly |
| API | Python + FastAPI + Pydantic |
| Orchestrator | LangGraph |
| LLM | One tool-calling model (e.g., GPT-4o) |
| Analytics | Pandas + NumPy |
| Testing | Pytest + HTTPX |
| Storage | SQLite (MVP) → PostgreSQL (production) |

## Repository Structure

```
project/
├── frontend/
│   └── src/
│       ├── components/      # Reusable UI components
│       ├── pages/            # Page-level views
│       └── api/              # API client functions
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI entry point
│   │   ├── api/
│   │   │   ├── datasets.py   # Dataset upload & profile endpoints
│   │   │   └── analysis.py   # Analysis job endpoints
│   │   ├── orchestration/
│   │   │   ├── graph.py      # LangGraph workflow definition
│   │   │   └── state.py      # Agent state management
│   │   ├── analytics/
│   │   │   ├── profiling.py      # Dataset profiling tools
│   │   │   ├── comparisons.py    # Period comparison tools
│   │   │   └── data_quality.py   # Data quality checks
│   │   ├── verification/
│   │   │   └── reconciliation.py # Value reconciliation checks
│   │   └── reporting/            # Report generation & export
│   └── tests/
│       ├── test_profiling.py
│       ├── test_comparisons.py
│       └── test_workflow.py
├── .env.example
├── Dockerfile (optional)
└── README.md
```

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- An LLM API key (OpenAI, Azure, or Anthropic)

### Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example ../.env  # Edit with your API key
uvicorn app.main:app --reload
```

### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/datasets/upload` | Upload and validate CSV/XLSX file (201; 400 bad type/content, 413 too large, 422 unreadable or empty) |
| GET | `/datasets` | List uploaded datasets, newest first |
| GET | `/datasets/{id}/profile` | Return schema and quality summary |
| POST | `/analysis` | Start analysis and return job ID (202; 404 unknown dataset, 422 bad question, 429 too many running jobs) |
| GET | `/analysis/{id}` | Return status, steps, findings, answer, chart specs, and limitations |
| GET | `/analysis/{id}/events` | SSE stream with `Accept: text/event-stream` (`status`, `step`, `done` events); JSON snapshot otherwise |
| GET | `/analysis/{id}/report` | JSON report, or Markdown download with `?format=md` (409 until the job has completed) |

Job status: `pending` → `profiling` → `planning` → `executing` → `verifying` → `completed` or `failed`.
Interactive docs are served at `http://localhost:8000/docs`.

## Analytics Tools

| Tool | Purpose |
|---|---|
| `profile_dataset` | Schema, nulls, duplicates, numeric summaries |
| `compare_periods` | Compare metric values between two periods |
| `group_metric_change` | Break down change by a categorical dimension |
| `test_data_quality` | Flag missing, duplicate, or inconsistent records |
| `detect_anomalies` | Apply a simple, documented statistical rule |
| `validate_reconciliation` | Check that subgroup totals align with overall totals |
| `create_chart` | Return a chart specification from verified results |

## Environment Variables

See [`.env.example`](.env.example) for the full list of configuration options. The API also reads these optional settings (defaults shown):

| Variable | Default | Purpose |
|---|---|---|
| `UPLOAD_DIR` | `backend/data/uploads` | Where uploaded files are stored |
| `DATABASE_PATH` | `backend/data/app.db` | SQLite metadata (datasets and jobs) |
| `MAX_UPLOAD_MB` | `50` | Maximum upload size |
| `MAX_QUESTION_CHARS` | `1000` | Maximum question length |
| `MAX_JOB_SECONDS` | `120` | Time limit for one analysis job |
| `MAX_ACTIVE_JOBS` | `3` | Concurrent analysis jobs allowed |
| `CORS_ORIGINS` | local Vite dev servers | Comma-separated allowed browser origins |

## Security Notes

- Upload size and file types are restricted
- Spreadsheet cell text is treated as untrusted data
- No arbitrary LLM-generated code execution — approved deterministic functions only
- API keys stored in environment variables only
- Row limits, processing time limits, and tool call limits enforced

## License

MIT
