# Calendars & Closures — Python API

The Python API layer that sits between the **Member Center (React on Azure)** and
**Salesforce Service Cloud**. It is the *only* thing that talks to Salesforce —
React never calls Salesforce directly.

```
District User
   │
   ▼
Member Center (React on Azure)
   │  passes Entra ID token  (Authorization: Bearer <token>)
   ▼
Python API (FastAPI on Azure)  ← THIS PROJECT
   │  OAuth 2.0 client credentials
   ▼
Salesforce Service Cloud
```

On **every** request the API does three things (API guide §1):

1. **Validates the Entra ID token** — confirms the caller is authenticated.
2. **Resolves identity to a Salesforce Contact** — `Contact WHERE Email = {entra_email}`
   so `Reported_By_Contact__c` is always a real person.
3. **Scopes every query to that user's district** — derived from `Contact.AccountId`;
   a district user can never read or write another district's data.

Stack: **Python 3.11+ · FastAPI · simple-salesforce · python-jose / MSAL · Azure**

---

## Quick start

```powershell
# from the project root
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env        # then fill in real values (see "Configuration")
uvicorn app.main:app --reload # http://localhost:8000/docs
```

> On this machine, run `sf` CLI commands and any live-network Python through
> **PowerShell**, not Git Bash — Bash here is network-sandboxed (DNS fails) and
> trips on the `sf` wrapper's `C:\Program Files` path.

### Run the tests (no credentials needed)

```powershell
.venv\Scripts\python.exe -m pytest -v        # 21 tests, fully mocked
```

### Check the live Salesforce connection

```powershell
.venv\Scripts\python.exe scripts\check_connection.py    # AUTH OK + 1 query
.venv\Scripts\python.exe scripts\smoke_endpoints.py     # all GET endpoints, live
```

---

## Project layout

```
calendars-closures-api/
├─ app/
│  ├─ main.py                  FastAPI app: CORS, router registration, error handlers, /health
│  ├─ config.py                pydantic-settings — loads all env vars (SF, Entra, dev bypass)
│  ├─ errors.py                Standard error shape + handlers (app / validation / catch-all)
│  ├─ routers/
│  │  ├─ schools.py            GET /api/schools, GET /api/closure-reasons (1h cache)
│  │  ├─ closures.py           POST/GET /api/closures, GET /{id}, POST /{id}/cancel
│  │  ├─ makeup.py             POST /api/makeup
│  │  └─ waivers.py            GET /api/waivers, PATCH /api/waivers/{id}
│  ├─ services/
│  │  ├─ salesforce.py         SF connection (client-creds / username-pw / JWT) + query helpers
│  │  └─ auth.py               Entra token validation + Contact/district resolution
│  └─ models/
│     ├─ closure_models.py     Pydantic request/response models (schools, reasons, closures)
│     ├─ makeup_models.py      Pydantic models for makeup
│     └─ waiver_models.py      Pydantic models for waivers
├─ tests/
│  ├─ conftest.py              Shared fixtures: mock Salesforce + mock auth
│  ├─ test_auth.py             401 on missing/bad token
│  ├─ test_schools.py          schools + closure-reasons
│  ├─ test_closures.py         create / list / detail / cancel / idempotency / validation
│  ├─ test_makeup.py           makeup happy path + cross-district 403
│  └─ test_waivers.py          list + submit (Tier 3 cert enforcement)
├─ scripts/
│  ├─ check_connection.py      Live auth + 1 query against the org
│  └─ smoke_endpoints.py       Live in-process test of every GET endpoint
├─ .env.example                Environment variable template
├─ .gitignore                  Excludes .env, venvs, caches
├─ requirements.txt            Dependencies
└─ README.md                   This file
```

---

## Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `SF_CLIENT_ID` / `SF_CLIENT_SECRET` | Connected-app credentials (client-credentials flow) |
| `SF_INSTANCE_URL` | Org My-Domain URL, e.g. `https://scde--devmemberc.sandbox.my.salesforce.com` |
| `SF_API_VERSION` | Salesforce REST API version (`62.0`) |
| `SF_AUTH_FLOW` | `auto` (default) / `client_credentials` / `username_password` / `jwt` |
| `SF_USERNAME` / `SF_PASSWORD` / `SF_SECURITY_TOKEN` | Only for the username/password flow |
| `SF_JWT_KEY_FILE` / `SF_JWT_KEY` | Only for the connected-app JWT flow |
| `ENTRA_TENANT_ID` / `ENTRA_CLIENT_ID` / `ENTRA_AUTHORITY` | Azure Entra ID app registration (token validation) |
| `API_ENV` | `development` / `production` |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins (React app URLs) |
| `AUTH_DISABLED` + `DEV_*` | Local-dev auth bypass (see below) — only honored when `API_ENV=development` |

Never commit `.env` — it's git-ignored. Secrets live in `.env` locally and Azure
Key Vault in production.

---

## How it works

### Salesforce connection (`app/services/salesforce.py`)

A single `sf` singleton wraps a cached `simple_salesforce.Salesforce` client.
`get_sf_connection()` picks the auth flow from `SF_AUTH_FLOW` (or auto-detects):

- **client_credentials** *(production / current)* — POSTs to
  `{instance_url}/services/oauth2/token` with the connected-app key+secret, then
  builds a session-based client. Requires a **"Run As" user** configured on the
  connected app (Setup → App Manager → Manage → Edit Policies → Client Credentials Flow).
- **username_password** — SOAP login with username + password + security token.
- **jwt** — connected-app JWT bearer (key from file or inline).

The wrapper exposes `query`, `query_one`, `create`, `update`, and `record_type_id`
(cached RecordType lookups — you set a record type on insert via its 18-char Id,
not its developer name). All calls auto-refresh once on an expired-session error.

### Auth + district scoping (`app/services/auth.py`)

`get_current_user()` is the FastAPI dependency every protected route injects:

1. Reads the `Authorization: Bearer` token.
2. `validate_token()` verifies the RS256 signature against the tenant JWKS,
   `aud` against `ENTRA_CLIENT_ID`, `iss` against `ENTRA_TENANT_ID`. Bad/expired → **401**.
3. `resolve_contact()` runs `Contact WHERE Email = {entra_email}`; no match → **403
   CONTACT_NOT_FOUND**. Returns a `CurrentUser` with `contact_id` + `account_id`
   (the district).

Every router then filters by `user.account_id` — the client can never supply its
own district.

**Local-dev bypass:** with `AUTH_DISABLED=true` and `API_ENV=development`,
`get_current_user` returns a stubbed `DEV_*` user — no Entra, no token — so you can
exercise endpoints before Azure/React exist. It refuses to activate outside
development.

### Error handling (`app/errors.py`)

Every error returns the same shape so React can display it reliably:

```json
{ "error": "DISTRICT_SCOPE_VIOLATION", "message": "...", "status_code": 403 }
```

| Code | HTTP | When |
|---|---|---|
| `UNAUTHORIZED` | 401 | Missing or invalid Entra token |
| `CONTACT_NOT_FOUND` | 403 | Entra user has no matching Contact |
| `DISTRICT_SCOPE_VIOLATION` | 403 | Accessing another district's data |
| `VALIDATION_ERROR` | 422 | Body validation (missing fields, bad dates, cert required) |
| `DUPLICATE_SUBMISSION` | 409 | *Defined but not raised — idempotency returns the existing record instead* |
| `SALESFORCE_ERROR` | 502 | SF REST error — detail logged, safe message to client |
| `NOT_FOUND` | 404 | Closure / waiver / makeup day not found |

Handlers cover app errors, FastAPI/Pydantic body-validation errors, and any
unexpected exception, so the frontend never sees a non-standard payload.

---

## Endpoints

| # | Method | Path | Purpose |
|---|---|---|---|
| 1 | GET | `/api/schools` | Schools in the user's district |
| 2 | GET | `/api/closure-reasons` | Active reasons from `Closure_Reason__mdt` (cached 1h) |
| 3 | POST | `/api/closures` | Submit a closure (creates a `Closure_Submission` Case → Flow expands to events) |
| 4 | GET | `/api/closures` | List closure events (filters: status, school_id, start/end date, school_year) |
| 5 | GET | `/api/closures/{id}` | Single event detail (+ makeup days, waiver), 403 if wrong district |
| 6 | POST | `/api/closures/{id}/cancel` | Set `Status=Cancelled` + create amendment Case |
| 7 | POST | `/api/makeup` | Create `Makeup_Day__c` + `Closure_Makeup_Link__c` per event |
| 8 | GET | `/api/waivers` | Waiver cases for the district |
| 9 | PATCH | `/api/waivers/{id}` | Update / submit a waiver (Tier 3+ requires superintendent cert) |

Interactive docs while running: <http://localhost:8000/docs>.

### Submission → Salesforce flow (write path)

`POST /api/closures` creates a `Closure_Submission` Case with `Submission_Status__c='Submitted'`,
which fires the Salesforce **`Create_Closure_Events`** Flow → one `Closure_Event__c`
per (school × date). Crossing a tier boundary fires **`Tier_Boundary_Check`** →
auto-creates a Draft waiver Case and emails the district contact. The API reads
the district's `Total_Missed_Days_YTD__c` to return YTD + tier in the response.

---

## How the React frontend will connect (eventually)

1. **Member Center (React)** authenticates the district user via **Entra ID (MSAL.js)**
   and obtains an access token scoped to this API's app registration.
2. Every call includes `Authorization: Bearer <token>` and targets this API
   (e.g. `https://<api-host>/api/...`), never Salesforce.
3. The API validates the token, resolves the Contact/district, calls Salesforce,
   and returns clean JSON (or the standard error shape).
4. React's origin must be listed in `ALLOWED_ORIGINS` for CORS.

Until the Azure app registration and React app exist, develop against the
`AUTH_DISABLED` bypass and the mocked test suite.

---

## Salesforce data model (companion repo)

The objects/fields/flows this API targets live in the separate Salesforce metadata
repo (`Calendars-Closures`, deployed to the `scde-sandbox` org). Key API names this
code depends on — verified against that org:

- **Case (Closure_Submission):** `Submission_Scope__c`, `Affected_School_IDs__c`,
  `Hours_Missed_Per_Day__c`, `Submission_District__c`, `Reported_By_Contact__c`,
  `Submission_Status__c`, `External_Id__c`.
- **Case (Closure_Waiver_Request):** `Waiver_District__c`, `Tier__c`,
  `Total_Missed_Days__c`, `Days_Already_Made_Up__c`, `Days_Requested_For_Waiver__c`,
  `Justification__c`, `Board_Minutes_Attached__c`, `Superintendent_Certification__c`,
  `Waiver_Status__c`.
- **Closure_Event__c:** `School__c`, `District__c`, `Closure_Date__c`, `Hours_Missed__c`,
  `Status__c`, `Make_Up_Required__c`, `Make_Up_Method__c`, `Reported_By__c`,
  `Source_Case__c`, `Waiver_Request_Case__c`, `School_Year__c`.
- **Makeup_Day__c:** `Makeup_Date__c`, `Method__c`, `Status__c`, `External_Id__c`.
- **Junctions:** `Closure_Makeup_Link__c` (`Hours_Covered__c` lives here),
  `Waiver_Closure_Link__c`.

> **Note:** `Account` has no `SIDN` field in the org, so `GET /api/schools` returns
> `sidn: null`. Flip `SCHOOL_SIDN_FIELD` in `schools.py` if one is added.

---

## Notable deviations from the original guide (and why)

- **Client-credentials auth flow** was added back (the Step-4 prompt only asked for
  username/password OR JWT, but the connected app uses client credentials — the
  documented production flow). All three flows are supported.
- **`SIDN__c` removed from the schools query** — the field doesn't exist on Account
  in the org; selecting it would error the whole query.
- **`current_tier`** is computed from YTD + the 3/6/9 thresholds rather than read
  from a `Current_Tier__c` field (which doesn't exist).
- **`waiver_case_id`** uses the direct `Closure_Event__c.Waiver_Request_Case__c`
  lookup instead of a junction subquery.
- **`DUPLICATE_SUBMISSION` (409) is intentionally unused** — idempotency returns the
  existing record (HTTP 200) for safe retries, per Endpoint 3.
- **`python-jose`** added for JWT signature verification (MSAL acquires tokens; it
  doesn't validate inbound ones).
- **Dev auth bypass** (`AUTH_DISABLED`) added so endpoints can be tested before
  Entra/React exist.
```
