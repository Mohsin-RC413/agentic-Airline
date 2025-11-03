# aroya_air/models.py  (only the Flight class changed: add CLASS_MULTIPLIER + prices in to_public)
from __future__ import annotations
from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field, EmailStr
from datetime import datetime, date
from enum import Enum

class FlightStatus(str, Enum):
    ON_TIME = "On Time"
    DELAYED = "Delayed"
    CANCELLED = "Cancelled"
    LANDED = "Landed"

class Gender(str, Enum):
    MALE = "Male"
    FEMALE = "Female"
    OTHER = "Other"

# 👇 You can tweak these multipliers any time
CLASS_MULTIPLIER: Dict[str, float] = {
    "Economy": 1.00,
    "Business": 1.60,
    "First": 2.25,
}

class Flight(BaseModel):
    flight_id: str
    airline: str
    flight_number: str
    departure_city: str
    arrival_city: str
    departure_airport: str
    arrival_airport: str
    departure_airport_code: str
    arrival_airport_code: str
    departure_time: datetime
    arrival_time: datetime
    duration: str
    aircraft_type: str
    baggage_allowance: str
    available_classes: List[Literal["Economy","Business","First"]]
    price_usd: float  # base price (Economy baseline)
    seats_available: int
    wifi_available: bool
    inflight_entertainment: bool
    status: FlightStatus

    def _derived_class_prices(self) -> Dict[str, float]:
        prices: Dict[str, float] = {}
        for c in self.available_classes:
            m = CLASS_MULTIPLIER.get(c, 1.0)
            prices[c] = round(float(self.price_usd) * m, 2)
        return prices

    def to_public(self) -> Dict[str, Any]:
        return {
            "flight_id": self.flight_id,
            "airline": self.airline,
            "flight_number": self.flight_number,
            "from": {
                "city": self.departure_city,
                "airport": self.departure_airport,
                "code": self.departure_airport_code,
                "departure_time": self.departure_time.isoformat(),
            },
            "to": {
                "city": self.arrival_city,
                "airport": self.arrival_airport,
                "code": self.arrival_airport_code,
                "arrival_time": self.arrival_time.isoformat(),
            },
            "duration": self.duration,
            "aircraft_type": self.aircraft_type,
            "baggage_allowance": self.baggage_allowance,
            "available_classes": self.available_classes,
            "prices_usd": self._derived_class_prices(),   # 👈 per-class prices
            "base_price_usd": round(float(self.price_usd), 2),
            "seats_available": self.seats_available,
            "amenities": {
                "wifi": self.wifi_available,
                "inflight_entertainment": self.inflight_entertainment,
            },
            "status": self.status.value,
        }

class SearchCriteria(BaseModel):
    departure_city: Optional[str] = Field(None, description="Exact departure city name")
    arrival_city: Optional[str]   = Field(None, description="Exact arrival city name")
    departure_date: Optional[date] = None
    passengers: int = Field(1, ge=1, le=9)
    class_preference: Optional[Literal["Economy","Business","First"]] = None

class Passenger(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    age: int = Field(..., ge=0, le=120)
    gender: Gender
    dob: date
    email: EmailStr

class BookingDetails(BaseModel):
    flight_id: str
    passengers: List[Passenger]
    seat_class: Literal["Economy","Business","First"] = "Economy"
    confirm: bool = False

class Reservation(BaseModel):
    reservation_id: str
    flight_id: str
    passengers: List[Passenger]
    passenger_count: int
    seat_class: Literal["Economy","Business","First"]
    total_price_usd: float
    booked_at: datetime
    flight_details: Flight

class ResponseEnvelope(BaseModel):
    ok: bool
    code: str
    message: str
    data: Dict[str, Any]
