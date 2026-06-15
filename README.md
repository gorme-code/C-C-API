# Calendars & Closures — Python API

The Python API layer between the Member Center (React on Azure) and Salesforce
Service Cloud. **This API is the only thing that talks to Salesforce** — React
never calls Salesforce directly.

On every request the API:

1. **Validates** the Entra ID bearer token the React app sends.
2. **Resolves** the user's email/UPN to a Salesforce Contact (`Reported_By`).
3. **Scopes** all queries to that user's district (`Contact.AccountId`).

## Stack

Python 3.11 · FastAPI · simple-salesforce · MSAL / Entra ID · Azure

## Project layout

```
calendars-closures-api/
  app/
    main.py            # FastAPI app, CORS, router registration
    config.py          # settings from env (pydantic-settings)
    errors.py          # standard error shape + handlers
    routers/
      schools.py       # GET /api/schools, GET /api/closure-reasons
      closures.py      # POST/GET /api/closures, GET /{id}, POST /{id}/cancel
      makeup.py        # POST /api/makeup
      waivers.py       # GET/PATCH /api/waivers
    services/
      salesforce.py    # SF connection + shared query helpers (sf singleton)
      auth.py          # Entra token validation, Contact resolver
    models/
      closure_models.py
      makeup_models.py
      waiver_models.py
  tests/
    conftest.py        # mock SF connection + mock auth fixtures
    test_closures.py
    test_makeup.py
    test_waivers.py
  .env.example
  .gitignore
  requirements.txt
  README.md
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt

cp .env.example .env          # then fill in real values — never commit .env
```

## Run

```bash
uvicorn app.main:app --reload
```

Interactive docs at <http://localhost:8000/docs>.

## Test

```bash
pytest
```

## Endpoints

| # | Method | Path | Purpose |
|---|--------|------|---------|
| 1 | GET   | `/api/schools`             | Schools in the user's district |
| 2 | GET   | `/api/closure-reasons`     | Active reasons from CMDT (cached 1h) |
| 3 | POST  | `/api/closures`            | Submit a closure |
| 4 | GET   | `/api/closures`            | List closure events |
| 5 | GET   | `/api/closures/{id}`       | Single closure event detail |
| 6 | POST  | `/api/closures/{id}/cancel`| Cancel a closure event |
| 7 | POST  | `/api/makeup`              | Submit makeup day(s) |
| 8 | GET   | `/api/waivers`             | List waiver cases |
| 9 | PATCH | `/api/waivers/{id}`        | Update / submit a waiver case |

## Error shape

```json
{ "error": "DISTRICT_SCOPE_VIOLATION", "message": "...", "status_code": 403 }
```

| Code | HTTP | When |
|------|------|------|
| `UNAUTHORIZED` | 401 | Missing or invalid Entra token |
| `CONTACT_NOT_FOUND` | 403 | Entra user has no matching Contact |
| `DISTRICT_SCOPE_VIOLATION` | 403 | Accessing another district's data |
| `VALIDATION_ERROR` | 422 | Request body fails validation |
| `DUPLICATE_SUBMISSION` | 409 | External_Id already exists |
| `SALESFORCE_ERROR` | 502 | Salesforce REST API error |
| `NOT_FOUND` | 404 | Closure, waiver, or makeup day not found |
```
