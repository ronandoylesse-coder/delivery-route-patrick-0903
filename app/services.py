import csv
import io
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app import models, schemas

# statuses we accept on events
DELIVERY_STATUSES = ["picked_up", "in_transit", "delivered", "failed", "returned"]
CSV_HEADERS = ["driver_id", "name", "phone", "email", "region"]
MAX_DAYS = 31


def _day_start_end(d: date):
    """utc midnight bounds for one calendar day"""
    start = datetime.combine(d, time.min, tzinfo = timezone.utc)
    end = datetime.combine(d + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return start, end


def validate_date_range(start: date, end: date):
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    days = (end - start).days + 1
    if days < 1 or days > MAX_DAYS:
        raise ValueError(f"Date range must be between 1 and {MAX_DAYS} calendar days inclusive (got {days})")


def list_drivers(db: Session):
    q = select(models.Driver).order_by(models.Driver.id)
    return list(db.scalars(q))


def get_driver(db: Session, driver_id: int):
    return db.get(models.Driver, driver_id)


def create_driver(db: Session, payload: schemas.DriverCreate):
    if get_driver(db, payload.id):
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


def upsert_driver(db, driver_id, name, phone, email, region):
    region = region.strip().lower()
    existing = get_driver(db, driver_id)
    if existing is None:
        d = models.Driver(
            id=driver_id,
            name=name.strip(),
            phone=phone.strip(),
            email=email.strip(),
            region=region,
        )
        db.add(d)
        return "created", d
    # update in place if already there
    existing.name = name.strip()
    existing.phone = phone.strip()
    existing.email = email.strip()
    existing.region = region

    return "updated", existing


def ingest_drivers_csv(db: Session, fileobj):
    raw = fileobj.read()
    if not raw:
        raise ValueError("Empty file")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("CSV must be UTF-8 encoded")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")

    headers = []
    for h in reader.fieldnames:
        if h and h.strip():
            headers.append(h.strip().lower())

    needed = set(CSV_HEADERS)
    got = set(headers)
    if not needed.issubset(got):
        missing = needed - got
        raise ValueError(f"CSV header must include columns: {sorted(needed)}; missing: {sorted(missing)}")

    created = 0
    updated = 0
    skipped = 0
    errors = []

    row_num = 1
    for raw_row in reader:
        row_num += 1
        row = {}
        for k, v in raw_row.items():
            if not k or not str(k).strip():
                continue
            key = k.strip().lower()
            row[key] = "" if v is None else str(v).strip()

        try:
            sid = row.get("driver_id", "")
            if not sid:
                skipped += 1
                errors.append(f"Row {row_num}: missing driver_id")
                continue

            driver_id = int(sid)
            if driver_id < 1:
                skipped += 1
                errors.append(f"Row {row_num}: invalid driver_id")
                continue

            name = row.get("name", "")
            phone = row.get("phone", "")
            email = row.get("email", "")
            region = row.get("region", "")
            if not name or not phone or not email or not region:
                skipped += 1
                errors.append(f"Row {row_num}: missing required field(s)")
                continue

            action, _ = upsert_driver(db, driver_id, name, phone, email, region)
            if action == "created":
                created += 1
            else:
                updated += 1
        except ValueError as e:
            skipped += 1
            errors.append(f"Row {row_num}: {e}")

    db.commit()

    # cap error list so response doesnt get huge
    return schemas.DriverUploadResult(
        created=created, updated=updated, skipped=skipped, errors=errors[:50]
    )


def record_delivery_event(db: Session, payload: schemas.DeliveryEventCreate):
    driver = get_driver(db, payload.driver_id)
    if driver is None:
        raise ValueError(f"Driver {payload.driver_id} does not exist")

    if payload.timestamp is None:
        ts = datetime.now(timezone.utc)
    else:
        ts = payload.timestamp
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


def query_statistics(db, metric, driver_ids, regions, start_date, end_date):
    validate_date_range(start_date, end_date)

    range_start, _ = _day_start_end(start_date)
    _, range_end = _day_start_end(end_date)

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
        region_list = []
        for r in regions:
            if r and r.strip():
                region_list.append(r.strip().lower())
        if region_list:
            stmt = stmt.where(models.Driver.region.in_(region_list))

    row = db.execute(stmt).one()
    distinct_packages = int(row.distinct_packages or 0)
    total_events = int(row.total_events or 0)
    delivered_events = int(row.delivered_events or 0)
    failed_events = int(row.failed_events or 0)

    day_span = (end_date - start_date).days + 1

    # figure out the number based on metric type
    if metric == schemas.StatMetric.total_packages:
        value = float(distinct_packages)
    elif metric == schemas.StatMetric.delivery_rate:
        if total_events == 0:
            value = 0.0
        else:
            value = delivered_events / total_events
    elif metric == schemas.StatMetric.failure_rate:
        if total_events == 0:
            value = 0.0
        else:
            value = failed_events / total_events
    elif metric == schemas.StatMetric.average_deliveries_per_day:
        value = delivered_events / day_span if day_span else 0.0
    else:
        raise ValueError("Unknown metric")

    notes = (
        "Rates are computed as a fraction of all delivery events in the window "
        "(not deduplicated by package). "
        "total_packages counts distinct package_id values in the filtered window. "
        "average_deliveries_per_day divides delivered event count by inclusive calendar days."
    )

    out_regions = None
    if regions:
        out_regions = []
        for r in regions:
            if r and r.strip():
                out_regions.append(r.strip().lower())

    return schemas.StatisticsResponse(
        metric=metric,
        value=round(value, 6),
        start_date=start_date,
        end_date=end_date,
        driver_ids=driver_ids,
        regions=out_regions,
        notes=notes,
    )
