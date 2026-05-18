import io
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import database, models, schemas, services



@asynccontextmanager
async def lifespan(_: FastAPI):
    # make sure tables exist on startup
    models.Base.metadata.create_all(bind=database.engine)
    yield


app = FastAPI(title="Delivery API", lifespan=lifespan)


@app.exception_handler(ValueError)
def value_error_handler(_, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
def validation_handler(_, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/drivers", response_model=list[schemas.DriverRead])
def list_drivers(db: Session = Depends(get_db)):
    return services.list_drivers(db)


@app.get("/drivers/{driver_id}", response_model=schemas.DriverRead)
def get_driver(driver_id: int, db: Session = Depends(get_db)):
    driver = services.get_driver(db, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    return driver


@app.post("/drivers", response_model=schemas.DriverRead, status_code=201)
def create_driver(payload: schemas.DriverCreate, db: Session = Depends(get_db)):
    try:
        return services.create_driver(db, payload)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/drivers/upload", response_model=schemas.DriverUploadResult)
async def upload_drivers(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload a .csv file")
    data = await file.read()
    try:
        return services.ingest_drivers_csv(db, io.BytesIO(data))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/deliveries/events", response_model=schemas.DeliveryEventRead, status_code=201)
def create_delivery_event(payload: schemas.DeliveryEventCreate, db: Session = Depends(get_db)):
    # pydantic already checks enum but keeping this anyway
    if payload.status.value not in services.DELIVERY_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    try:
        return services.record_delivery_event(db, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/statistics", response_model=schemas.StatisticsResponse)
def statistics(
    metric: schemas.StatMetric,
    driver_ids: list[int] | None = Query(default=None),
    regions: list[str] | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    today = datetime.now(timezone.utc).date()

    # if no dates passed use today only
    if start_date is None and end_date is None:
        start_date = today
        end_date = today
    elif start_date is None or end_date is None:
        raise HTTPException(status_code=400, detail="Provide both start_date and end_date, or neither")

    try:
        return services.query_statistics(db, metric, driver_ids, regions, start_date, end_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
