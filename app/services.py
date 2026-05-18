import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from typing import BinaryIO

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app import models, schemas

DELIVERY_STATUSES = frozenset(s.value for s in schemas.DeliveryStatus)
CSV_EXPECTED_HEADERS = {"driver_id", "name", "phone", "email", "region"}
MAX_DATE_RANGE_DAYS = 31
MIN_DATE_RANGE_DAYS = 1


def _utc_day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time.min, tzinfo=timezone.utc)
    end = datetime.combine(d + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return start, end


def validate_date_range(start: date, end: date) -> None:
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    span = (end - start).days + 1
    if span < MIN_DATE_RANGE_DAYS or span > MAX_DATE_RANGE_DAYS:
        raise ValueError(
            f"Date range must be between {MIN_DATE_RANGE_DAYS} and {MAX_DATE_RANGE_DAYS} "
            f"calendar days inclusive (got {span})"
        )


def list_drivers(db: Session) -> list[models.Driver]:
    return list(db.scalars(select(models.Driver).order_by(models.Driver.id)))


def get_driver(db: Session, driver_id: int) -> models.Driver | None:
    return db.get(models.Driver, driver_id)


def create_driver(db: Session, payload: schemas.DriverCreate) -> models.Driver:
    existing = get_driver(db, payload.id)
    if existing is not None:
        raise ValueError(f"Driver id {payload.id} already exists; use CSV upload to update")
    row = models.Driver(
        id=payload.id,
        name=payload.name,
        phone=payload.phone,
        email=str(payload.email),
        region=payload.region,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def upsert_driver(
    db: Session,
    driver_id: int,
    name: str,
    phone: str,
    email: str,
    region: str,
) -> tuple[str, models.Driver]:
    """Returns ('created'|'updated', driver)."""
    region_norm = region.strip().lower()
    existing = get_driver(db, driver_id)
    if existing is None:
        d = models.Driver(
            id=driver_id,
            name=name.strip(),
            phone=phone.strip(),
            email=email.strip(),
            region=region_norm,
        )
        db.add(d)
        return "created", d
    existing.name = name.strip()
    existing.phone = phone.strip()
    existing.email = email.strip()
    existing.region = region_norm
    return "updated", existing


def ingest_drivers_csv(db: Session, fileobj: BinaryIO) -> schemas.DriverUploadResult:
    raw = fileobj.read()
    if not raw:
        raise ValueError("Empty file")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ValueError("CSV must be UTF-8 encoded") from e

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")

    headers = {h.strip().lower() for h in reader.fieldnames if h and h.strip()}
    if not CSV_EXPECTED_HEADERS.issubset(headers):
        missing = CSV_EXPECTED_HEADERS - headers
        raise ValueError(f"CSV header must include columns: {sorted(CSV_EXPECTED_HEADERS)}; missing: {sorted(missing)}")

    created = updated = skipped = 0
    errors: list[str] = []
    for i, raw_row in enumerate(reader, start=2):
        row = {
            (k.strip().lower() if k else ""): ("" if v is None else str(v).strip())
            for k, v in raw_row.items()
            if k and str(k).strip()
        }
        try:
            sid = row.get("driver_id", "")
            if not sid:
                skipped += 1
                errors.append(f"Row {i}: missing driver_id")
                continue
            driver_id = int(sid)
            if driver_id < 1:
                skipped += 1
                errors.append(f"Row {i}: invalid driver_id")
                continue
            name = row.get("name", "")
            phone = row.get("phone", "")
            email = row.get("email", "")
            region = row.get("region", "")
            if not name or not phone or not email or not region:
                skipped += 1
                errors.append(f"Row {i}: missing required field(s)")
                continue
            action, _ = upsert_driver(db, driver_id, name, phone, email, region)
            if action == "created":
                created += 1
            else:
                updated += 1
        except ValueError as e:
            skipped += 1
            errors.append(f"Row {i}: {e}")

    db.commit()
    return schemas.DriverUploadResult(created=created, updated=updated, skipped=skipped, errors=errors[:50])


def record_delivery_event(db: Session, payload: schemas.DeliveryEventCreate) -> models.DeliveryEvent:
    driver = get_driver(db, payload.driver_id)
    if driver is None:
        raise ValueError(f"Driver {payload.driver_id} does not exist")
    ts = payload.timestamp if payload.timestamp is not None else datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    ev = models.DeliveryEvent(
        package_id=payload.package_id.strip(),
        driver_id=payload.driver_id,
        status=payload.status.value,
        event_time=ts,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


def query_statistics(
    db: Session,
    metric: schemas.StatMetric,
    driver_ids: list[int] | None,
    regions: list[str] | None,
    start_date: date,
    end_date: date,
) -> schemas.StatisticsResponse:
    validate_date_range(start_date, end_date)
    range_start, _ = _utc_day_bounds(start_date)
    _, range_end = _utc_day_bounds(end_date)

    stmt = (
        select(
            func.count(func.distinct(models.DeliveryEvent.package_id)).label("distinct_packages"),
            func.count(models.DeliveryEvent.id).label("total_events"),
            func.coalesce(
                func.sum(case((models.DeliveryEvent.status == "delivered", 1), else_=0)),
                0,
            ).label("delivered_events"),
            func.coalesce(
                func.sum(case((models.DeliveryEvent.status == "failed", 1), else_=0)),
                0,
            ).label("failed_events"),
        )
        .select_from(models.DeliveryEvent)
        .join(models.Driver, models.DeliveryEvent.driver_id == models.Driver.id)
        .where(
            models.DeliveryEvent.event_time >= range_start,
            models.DeliveryEvent.event_time < range_end,
        )
    )
    if driver_ids:
        stmt = stmt.where(models.Driver.id.in_(driver_ids))
    if regions:
        norm = [r.strip().lower() for r in regions if r.strip()]
        if norm:
            stmt = stmt.where(models.Driver.region.in_(norm))

    row = db.execute(stmt).one()
    distinct_packages = int(row.distinct_packages or 0)
    total_events = int(row.total_events or 0)
    delivered_events = int(row.delivered_events or 0)
    failed_events = int(row.failed_events or 0)

    day_span = (end_date - start_date).days + 1
    notes_parts = [
        "Rates are computed as a fraction of all delivery events in the window "
        "(not deduplicated by package).",
        "total_packages counts distinct package_id values in the filtered window.",
        "average_deliveries_per_day divides delivered event count by inclusive calendar days.",
    ]
    notes = " ".join(notes_parts)

    if metric == schemas.StatMetric.total_packages:
        value = float(distinct_packages)
    elif metric == schemas.StatMetric.delivery_rate:
        value = (delivered_events / total_events) if total_events else 0.0
    elif metric == schemas.StatMetric.failure_rate:
        value = (failed_events / total_events) if total_events else 0.0
    elif metric == schemas.StatMetric.average_deliveries_per_day:
        value = delivered_events / day_span if day_span else 0.0
    else:
        raise ValueError("Unknown metric")

    return schemas.StatisticsResponse(
        metric=metric,
        value=round(value, 6),
        start_date=start_date,
        end_date=end_date,
        driver_ids=driver_ids,
        regions=[r.strip().lower() for r in regions] if regions else None,
        notes=notes,
    )
