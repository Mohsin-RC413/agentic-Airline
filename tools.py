# aroya_air/tools.py
from __future__ import annotations
from typing import Dict, Any, List, Optional
import datetime as dt  # ← single, unambiguous import

from .models import (
    ResponseEnvelope, SearchCriteria, BookingDetails, Reservation, Flight
)
from .utils import (
    now_utc, gen_reservation_id, load_flights, is_bookable,
    matches_cities, matches_date, validate_passenger_age_vs_dob,
    parse_date_flexible, facets_for, normalize
)
from .data import ACTIVE_DATASET


# In-memory "DB"
_RESERVATIONS: Dict[str, Reservation] = {}

def _envelope(ok: bool, code: str, message: str, data: Dict[str, Any]) -> Dict[str, Any]:
    # mode="json" ensures date/datetime are serialized as strings
    return ResponseEnvelope(ok=ok, code=code, message=message, data=data).model_dump(mode="json")

def _find_flight_by_id(flights: List[Flight], flight_id: str) -> Optional[Flight]:
    for f in flights:
        if f.flight_id == flight_id:
            return f
    return None


# -----------------------
# Date coercion utility
# -----------------------
def _coerce_date_to_iso(raw: Any) -> Optional[str]:
    """
    Convert various date-like inputs into 'YYYY-MM-DD' or return None.
    Accepts:
      - dt.datetime
      - dt.date
      - ISO strings with time/tz (e.g., '2025-11-26T22:00:00-05:00', '...Z')
      - Flexible strings ('26 Nov', '11/26/2025', 'tomorrow', etc.)
    """
    if raw is None:
        return None

    # dt.datetime ?
    if isinstance(raw, dt.datetime):
        return raw.date().isoformat()

    # dt.date ?
    if isinstance(raw, dt.date):
        return raw.isoformat()

    # string ?
    if isinstance(raw, str):
        s = raw.strip()
        # Try strict ISO-8601 with timezone first (matches your dataset)
        try:
            iso_dt = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
            return iso_dt.date().isoformat()
        except Exception:
            pass

        # Try flexible formats
        parsed = parse_date_flexible(s)
        return parsed.isoformat() if parsed else None

    return None


# ---------------------------
# get_available_flights  (FLAT SIGNATURE – ADK-friendly)
# ---------------------------
def get_available_flights(
    # canonical fields
    departure_city: Optional[str] = None,
    arrival_city: Optional[str] = None,
    departure_date: Optional[str] = None,
    passengers: Optional[int] = 1,
    class_preference: Optional[str] = None,
    # common synonyms ADK/LLMs might send
    date: Optional[str] = None,         # keep for compatibility
    travel_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Flexible search:
    - Only departure city -> returns destinations & dates (facets)
    - City pair           -> returns route-matched flights + available dates
    - Any date format (e.g., '26 Nov', '11/26/2025', 'tomorrow', or full ISO with tz)
    """

    # 1) Normalize date input to ISO YYYY-MM-DD (or None)
    raw_date = departure_date or travel_date or date
    parsed_iso = _coerce_date_to_iso(raw_date)

    # 2) Build Pydantic criteria (all fields optional)
    crit = {
        "departure_city": departure_city,
        "arrival_city": arrival_city,
        "departure_date": parsed_iso,  # Pydantic coerces ISO->date
        "passengers": passengers or 1,
        "class_preference": class_preference,
    }

    try:
        c = SearchCriteria(**{k: v for k, v in crit.items() if v is not None})
    except Exception as e:
        return _envelope(False, "FLIGHT_SEARCH_INVALID_INPUT", "Invalid search criteria.", {
            "error": str(e),
            "criteria": crit
        })

    flights = load_flights(ACTIVE_DATASET.get("flights", []))

    # 3) STRICT route filter once both cities are known
    if c.departure_city and c.arrival_city:
        filtered_city = [
            f for f in flights
            if normalize(f.departure_city) == normalize(c.departure_city)
            and normalize(f.arrival_city) == normalize(c.arrival_city)
            and is_bookable(f)
        ]
    else:
        # partial exploration
        filtered_city = [f for f in flights if matches_cities(f, c) and is_bookable(f)]

    # 4) Optional exact-date filter
    filtered = [f for f in filtered_city if matches_date(f, c.departure_date)]

    # 5) Facets for “show me dates/destinations”
    facet_info = facets_for(flights, c)

    # 6) Sort & shape
    results = sorted(filtered, key=lambda x: (x.price_usd, -x.seats_available))
    public = [f.to_public() for f in results]

    needs: List[str] = []
    if not c.departure_city:
        needs.append("departure_city")
    if c.departure_city and not c.arrival_city:
        needs.append("arrival_city")
    if c.departure_city and c.arrival_city and not c.departure_date:
        needs.append("departure_date")

    if c.departure_city and c.arrival_city:
        if public:
            code = "FLIGHT_SEARCH_OK"
            msg  = f"Found {len(public)} flight(s) from {c.departure_city} to {c.arrival_city}."
        else:
            code = "FLIGHT_SEARCH_PARTIAL_OK"
            msg  = (f"No exact-date results yet for {c.departure_city} → {c.arrival_city}. "
                    "Here are available dates you can pick.")
    else:
        code = "FLIGHT_SEARCH_EXPLORE"
        msg  = "Select a destination and/or date from the available options."

    return _envelope(True, code, msg, {
        "criteria": c.model_dump(mode="json"),
        "flights": public,
        "facets": facet_info,    # { available_destinations:[...], available_dates:[...] }
        "needs": needs
    })


# ------------------------
# create_reservation  (FLAT SIGNATURE – ADK-friendly)
# ------------------------
# ------------------------
# create_reservation
# ------------------------
def create_reservation(
    flight_id: str,
    seat_class: str = "Economy",
    confirm: bool = False,
    # passenger fields flattened for ADK
    passenger_name: Optional[str] = None,
    passenger_age: Optional[int] = None,
    passenger_gender: Optional[str] = None,
    passenger_dob: Optional[str] = None,      # "YYYY-MM-DD"
    passenger_email: Optional[str] = None,
) -> Dict[str, Any]:
    passenger_payload = {
        "name": passenger_name,
        "age": passenger_age,
        "gender": passenger_gender,
        "dob": passenger_dob,
        "email": passenger_email,
    }
    payload = {
        "flight_id": flight_id,
        "seat_class": seat_class,
        "confirm": confirm,
        "passenger": passenger_payload
    }

    try:
        req = BookingDetails(**payload)
    except Exception as e:
        return _envelope(False, "RESERVATION_INVALID_INPUT", "Invalid booking details.", {"error": str(e)})

    flights = load_flights(ACTIVE_DATASET.get("flights", []))
    f = _find_flight_by_id(flights, req.flight_id)
    if not f:
        return _envelope(False, "RESERVATION_FLIGHT_NOT_FOUND", "Flight not found.", {"flight_id": req.flight_id})

    if not is_bookable(f):
        return _envelope(False, "RESERVATION_UNBOOKABLE", f"Flight status is '{f.status.value}'. Not bookable.", {"flight": f.to_public()})

    if req.seat_class not in f.available_classes:
        return _envelope(False, "RESERVATION_CLASS_NOT_AVAILABLE",
                         f"Seat class '{req.seat_class}' not available for this flight.", {"available": f.available_classes})

    ok_age, calc_age = validate_passenger_age_vs_dob(req.passenger, now_utc())
    issues = []
    if not ok_age:
        issues.append({"field": "age", "message": f"Age does not match DOB; expected approximately {calc_age}."})

    # ---- Preview step (no booking yet)
    if not req.confirm:
        return _envelope(True, "RESERVATION_PREVIEW", "Preview generated. Ask user for final confirmation.", {
            "flight": f.to_public(),                               # concise flight view for preview
            "passenger": req.passenger.model_dump(mode="json"),
            "seat_class": req.seat_class,
            "validation": {"ok": len(issues) == 0, "issues": issues},
            "quote": {"currency": "USD", "base_price": round(float(f.price_usd), 2), "passengers": 1, "total_price": round(float(f.price_usd), 2)},
            "next_action": "ask_confirmation"
        })

    # ---- Confirmation path
    if issues:
        return _envelope(False, "RESERVATION_VALIDATION_FAILED", "Passenger details failed validation. Correct them before confirming.", {"issues": issues})

    reservation_id = gen_reservation_id()
    reservation = Reservation(
        reservation_id=reservation_id,
        flight_id=f.flight_id,
        passenger=req.passenger,
        seat_class=req.seat_class,
        total_price_usd=round(float(f.price_usd), 2),
        booked_at=now_utc(),
        flight_details=f,                        # 👈 include full Flight model
    )
    _RESERVATIONS[reservation_id] = reservation

    return _envelope(True, "RESERVATION_CONFIRMED", "Your reservation is confirmed.", {
        "reservation": reservation.model_dump(mode="json")         # 👈 JSON-safe (datetimes → strings)
    })
