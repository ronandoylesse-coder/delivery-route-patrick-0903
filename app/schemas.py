from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


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
    id: int = Field(..., ge=1, description="Business driver id (matches CSV)")
    name: str = Field(..., min_length=1, max_length=255)
    phone: str = Field(..., min_length=3, max_length=64)
    email: EmailStr
    region: str = Field(..., min_length=1, max_length=64)

    @field_validator("region")
    @classmethod
    def region_lower(cls, v: str) -> str:
        return v.strip().lower()


class DriverRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str
    email: str
    region: str


class DeliveryEventCreate(BaseModel):
    package_id: str = Field(..., min_length=1, max_length=128)
    driver_id: int = Field(..., ge=1)
    status: DeliveryStatus
    timestamp: datetime | None = Field(
        default=None,
        description="Event time in UTC; defaults to server time if omitted",
    )


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
    notes: str | None = Field(
        default=None,
        description="How the metric is computed for this API version",
    )
