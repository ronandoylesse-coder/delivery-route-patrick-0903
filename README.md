# Delivery tracking API

REST API for drivers (CSV upload), delivery events, and filtered statistics. Built with **FastAPI**, **SQLAlchemy 2**, and **SQLite** by default (`DATABASE_URL` can point to another SQLAlchemy-supported database).

## Prerequisites

- Python 3.10+

## Setup

**Windows (PowerShell)**

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**macOS / Linux**

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

If PowerShell blocks activation, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

## Run

Activate the virtual environment first (see Setup). Your prompt should show `(venv)`.

**Windows (PowerShell)**

```powershell
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

Or without activating (works if `uvicorn` is not on PATH):

```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

**macOS / Linux**

```bash
source venv/bin/activate
uvicorn app.main:app --reload
```

- OpenAPI docs: `http://127.0.0.1:8000/docs`
- Health: `GET /health`

## Data model

- **Driver**: `id` (integer, business id from CSV), `name`, `phone`, `email`, `region` (e.g. `north`, `south`).
- **Delivery event**: `package_id`, `driver_id` (must exist), `status` (`picked_up`, `in_transit`, `delivered`, `failed`, `returned`), `timestamp` (optional; defaults to current UTC).

## CSV upload

`POST /drivers/upload` with multipart field `file` (`.csv`, UTF-8).

Header row must include: `driver_id`, `name`, `phone`, `email`, `region`. Existing `driver_id` rows are updated.

## Statistics

`GET /statistics`

Query parameters:

| Parameter | Description |
|-----------|-------------|
| `metric` | `total_packages`, `delivery_rate`, `failure_rate`, `average_deliveries_per_day` |
| `driver_ids` | Optional; repeat or list (e.g. `driver_ids=7&driver_ids=8`). Omit for all drivers. |
| `regions` | Optional; e.g. `north`. Omit for all regions. |
| `start_date`, `end_date` | Inclusive UTC dates (`YYYY-MM-DD`). Omit both to use **today** (UTC). If one is set, both are required. Range: **1–31** calendar days. |

Metric notes (see response `notes` as well):

- **total_packages**: distinct `package_id` in the window after filters.
- **delivery_rate** / **failure_rate**: share of **events** with status `delivered` / `failed` over all events in the window.
- **average_deliveries_per_day**: count of `delivered` events divided by inclusive day count.

## Example test data

drivers.csv (upload to POST /drivers/upload):

```
driver_id,name,phone,email,region
7,Ada Lovelace,+15555550100,ada@example.com,north
```

delivery event (POST /deliveries/events):

```json
{"package_id":"PKG-1","driver_id":7,"status":"delivered","timestamp":"2026-05-10T12:00:00+00:00"}
```

stats example:

```
GET /statistics?metric=total_packages&driver_ids=7&start_date=2026-05-01&end_date=2026-05-31
```

same stuff as tests/test_api.py basically

## Tests

With the venv activated:

```bash
pytest
```

Or on Windows without activating:

```powershell
.\venv\Scripts\python.exe -m pytest
```
