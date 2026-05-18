from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

STR_NAME_MAX_LENGTH: int = 255
STR_PHONE_MAX_LENGTH: int = 64
STR_EMAIL_MAX_LENGTH: int = 255
STR_REGION_MAX_LENGTH: int = 64

STR_PACKAGE_ID_MAX_LENGTH: int = 128

STR_DRIVER_ID_MAX_LENGTH: int = 1000000

STR_STATUS_MAX_LENGTH: int = 32

class DeliveryStatus(str, Enum):
    picked_up = "picked_up"
    in_transit = "in_transit"
    delivered = "delivered"
    failed = "failed"
    returned = "returned"


class StatMetric(str, Enum):
    total_packages = "total_packages"
    delivery_rate = "delivery_rate"
    failure_rate = "failure_rate"
    average_deliveries_per_day = "average_deliveries_per_day"


class DriverCreate(BaseModel):
    id: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=STR_NAME_MAX_LENGTH)
    phone: str = Field(..., min_length=3, max_length=STR_PHONE_MAX_LENGTH)
    email: EmailStr
    region: str = Field(..., min_length=1, max_length=STR_REGION_MAX_LENGTH)

    @field_validator("region")
    @classmethod
    def region_lower(cls, v: str) -> str:
        # store regions lowercase so stats filter works
        return v.strip().lower()


class DriverRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str
    email: str
    region: str


class DeliveryEventCreate(BaseModel):
    package_id: str = Field(..., min_length=1, max_length=STR_PACKAGE_ID_MAX_LENGTH)
    driver_id: int = Field(..., ge=1, le=STR_DRIVER_ID_MAX_LENGTH)
    status: DeliveryStatus
    # status: DeliveryStatus = Field(..., min_length=1, max_length=STR_STATUS_MAX_LENGTH, default=DeliveryStatus.picked_up)
    timestamp: datetime | None = None  # optional, server fills in utc now


class DeliveryEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    package_id: str
    driver_id: int
    status: str
    event_time: datetime


class DriverUploadResult(BaseModel):
    created: int
    updated: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class StatisticsResponse(BaseModel):
    metric: StatMetric
    value: float
    start_date: date
    end_date: date
    driver_ids: list[int] | None = None
    regions: list[str] | None = None
    notes: str | None = None
