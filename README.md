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

## Example API test data

With the server running at `http://127.0.0.1:8000`, you can seed and exercise the API using the samples below (also mirrored in `tests/test_api.py`).

### Sample driver CSV

Save as `drivers.csv` (UTF-8):

```csv
driver_id,name,phone,email,region
7,Ada Lovelace,+15555550100,ada@example.com,north
8,Grace Hopper,+15555550200,grace@example.com,south
```

Upload:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/drivers/upload" -F "file=@drivers.csv"
```

```bash
curl -X POST "http://127.0.0.1:8000/drivers/upload" -F "file=@drivers.csv"
```

Example response:

```json
{
  "created": 2,
  "updated": 0,
  "skipped": 0,
  "errors": []
}
```

Re-uploading the same file with changed names increments `updated` instead of `created`.

### Create a driver (JSON)

`POST /drivers`

```json
{
  "id": 9,
  "name": "Katherine Johnson",
  "phone": "+15555550300",
  "email": "katherine@example.com",
  "region": "North"
}
```

Example response (`201`):

```json
{
  "id": 9,
  "name": "Katherine Johnson",
  "phone": "+15555550300",
  "email": "katherine@example.com",
  "region": "north"
}
```

`region` is stored lowercased. Duplicate `id` returns `409`.

### List / get drivers

- `GET /health` → `{"status": "ok"}`
- `GET /drivers` → array of driver objects
- `GET /drivers/7` → single driver or `404`

### Delivery events

`POST /deliveries/events` — `driver_id` must exist.

```json
{
  "package_id": "PKG-1",
  "driver_id": 7,
  "status": "delivered",
  "timestamp": "2026-05-10T12:00:00+00:00"
}
```

`status` must be one of: `picked_up`, `in_transit`, `delivered`, `failed`, `returned`. Omit `timestamp` to use the server’s current UTC time.

Example response (`201`):

```json
{
  "id": 1,
  "package_id": "PKG-1",
  "driver_id": 7,
  "status": "delivered",
  "event_time": "2026-05-10T12:00:00Z"
}
```

Additional sample events for statistics:

```json
{"package_id": "PKG-2", "driver_id": 7, "status": "picked_up", "timestamp": "2026-05-11T09:00:00+00:00"}
{"package_id": "PKG-2", "driver_id": 7, "status": "delivered", "timestamp": "2026-05-11T14:00:00+00:00"}
{"package_id": "PKG-3", "driver_id": 8, "status": "failed", "timestamp": "2026-05-12T10:00:00+00:00"}
```

Unknown `driver_id` (e.g. `99`) returns `400`.

### Statistics queries

After seeding drivers and events above, for May 2026:

```http
GET /statistics?metric=total_packages&driver_ids=7&regions=north&start_date=2026-05-01&end_date=2026-05-31
```

Example response:

```json
{
  "metric": "total_packages",
  "value": 2.0,
  "start_date": "2026-05-01",
  "end_date": "2026-05-31",
  "driver_ids": [7],
  "regions": ["north"],
  "notes": "Rates are computed as a fraction of all delivery events in the window (not deduplicated by package). total_packages counts distinct package_id values in the filtered window. average_deliveries_per_day divides delivered event count by inclusive calendar days."
}
```

Other metrics (same date range):

| Request | Expected `value` (with sample data above) |
|---------|-------------------------------------------|
| `metric=delivery_rate` (all drivers, no filters) | `0.5` (2 delivered / 4 events) |
| `metric=failure_rate` | `0.25` (1 failed / 4 events) |
| `metric=average_deliveries_per_day` | `2.0 / 31` ≈ `0.0645` (2 `delivered` events over 31 days) |

Today only (omit both dates):

```http
GET /statistics?metric=total_packages
```

Returns `value: 0.0` if no events were recorded today (UTC).

Invalid range (> 31 days), e.g. `start_date=2026-01-01&end_date=2026-03-01`, returns `400`.

## Tests

With the venv activated:

```bash
pytest
```

Or on Windows without activating:

```powershell
.\venv\Scripts\python.exe -m pytest
```

## Submission note

Use a **neutral public repo name** (random string) when publishing, per hiring instructions.
