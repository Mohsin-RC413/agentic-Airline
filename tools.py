# aroya_air/tools.py
from __future__ import annotations
from typing import Dict, Any, List, Optional
import json
import datetime as dt

from .models import (
    ResponseEnvelope, SearchCriteria, BookingDetails, Reservation, Flight, Passenger, CLASS_MULTIPLIER
)
from .utils import (
    now_utc, gen_reservation_id, load_flights, is_bookable,
    matches_cities, matches_date, validate_passenger_age_vs_dob,
    parse_date_flexible, facets_for, normalize
)
from .data import ACTIVE_DATASET

_RESERVATIONS: Dict[str, Reservation] = {}

def _envelope(ok: bool, code: str, message: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return ResponseEnvelope(ok=ok, code=code, message=message, data=data).model_dump(mode="json")

def _find_flight_by_id(flights: List[Flight], flight_id: str) -> Optional[Flight]:
    for f in flights:
        if f.flight_id == flight_id:
            return f
    return None

# -------- date coercion (unchanged from prior fix) --------
def _coerce_date_to_iso(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    if isinstance(raw, dt.datetime):
        return raw.date().isoformat()
    if isinstance(raw, dt.date):
        return raw.isoformat()
    if isinstance(raw, str):
        s = raw.strip()
        try:
            iso_dt = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
            return iso_dt.date().isoformat()
        except Exception:
            pass
        parsed = parse_date_flexible(s)
        return parsed.isoformat() if parsed else None
    return None

# -------- helper: parse passengers flexibly --------
def _parse_passengers(
    passenger_count: Optional[int],
    passengers: Optional[List[Dict[str, Any]]],
    passengers_json: Optional[str],
    # single-passenger fallback fields:
    passenger_name: Optional[str],
    passenger_age: Optional[int],
    passenger_gender: Optional[str],
    passenger_dob: Optional[str],
    passenger_email: Optional[str],
) -> Dict[str, Any]:
    """
    Returns:
      {
        "passenger_dicts": List[dict],    # raw dicts (may be incomplete)
        "count": int,                     # inferred or provided
        "errors": List[str]               # fatal parse errors (e.g., bad JSON)
      }
    """
    errors: List[str] = []
    plist: List[Dict[str, Any]] = []

    if isinstance(passengers, list) and passengers:
        plist = passengers
    elif passengers_json:
        try:
            loaded = json.loads(passengers_json)
            if isinstance(loaded, list):
                plist = loaded
            else:
                errors.append("passengers_json must be a JSON array.")
        except Exception as e:
            errors.append(f"Invalid passengers_json: {e}")
    elif any([passenger_name, passenger_age, passenger_gender, passenger_dob, passenger_email]):
        # Build a single-passenger list from flattened fields
        plist = [{
            "name": passenger_name,
            "age": passenger_age,
            "gender": passenger_gender,
            "dob": passenger_dob,
            "email": passenger_email,
        }]

    # Infer count if not provided
    inferred_count = passenger_count if passenger_count and passenger_count > 0 else (len(plist) if plist else 1)

    # If provided count mismatches provided list length, do not fail immediately; report as issue in preview.
    return {"passenger_dicts": plist, "count": inferred_count, "errors": errors}

# ---------------------------
# get_available_flights (unchanged except seat check uses c.passengers)
# ---------------------------
def get_available_flights(
    departure_city: Optional[str] = None,
    arrival_city: Optional[str] = None,
    departure_date: Optional[str] = None,
    passengers: Optional[int] = 1,
    class_preference: Optional[str] = None,
    date: Optional[str] = None,         # synonyms accepted
    travel_date: Optional[str] = None,
) -> Dict[str, Any]:
    raw_date = departure_date or travel_date or date
    parsed_iso = _coerce_date_to_iso(raw_date)

    crit = {
        "departure_city": departure_city,
        "arrival_city": arrival_city,
        "departure_date": parsed_iso,
        "passengers": passengers or 1,
        "class_preference": class_preference,
    }
    try:
        c = SearchCriteria(**{k: v for k, v in crit.items() if v is not None})
    except Exception as e:
        return _envelope(False, "FLIGHT_SEARCH_INVALID_INPUT", "Invalid search criteria.", {"error": str(e), "criteria": crit})

    flights = load_flights(ACTIVE_DATASET.get("flights", []))

    # strict route filter when both cities present
    if c.departure_city and c.arrival_city:
        filtered_city = [
            f for f in flights
            if normalize(f.departure_city) == normalize(c.departure_city)
            and normalize(f.arrival_city) == normalize(c.arrival_city)
            and is_bookable(f)
            and (f.seats_available >= (c.passengers or 1))  # seat check
            and (not c.class_preference or c.class_preference in f.available_classes)
        ]
    else:
        filtered_city = [
            f for f in flights
            if matches_cities(f, c)
            and is_bookable(f)
            and (f.seats_available >= (c.passengers or 1))
            and (not c.class_preference or c.class_preference in f.available_classes)
        ]

    # optional exact-date filter
    filtered = [f for f in filtered_city if matches_date(f, c.departure_date)]

    facet_info = facets_for(flights, c)
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
            msg = f"Found {len(public)} flight(s) from {c.departure_city} to {c.arrival_city}."
        else:
            code = "FLIGHT_SEARCH_PARTIAL_OK"
            msg  = (f"No exact-date results yet for {c.departure_city} → {c.arrival_city}. "
                    "Here are available dates you can pick.")
    else:
        code = "FLIGHT_SEARCH_EXPLORE"
        msg = "Select a destination and/or date from the available options."

    return _envelope(True, code, msg, {
        "criteria": c.model_dump(mode="json"),
        "flights": public,
        "facets": facet_info,
        "needs": needs
    })

def _unit_price_for_class(f: Flight, seat_class: str) -> float:
    """Return per-passenger unit price for the chosen class (derived from base)."""
    mul = CLASS_MULTIPLIER.get(seat_class, 1.0)
    return round(float(f.price_usd) * mul, 2)

# ------------------------
# create_reservation  — MULTI‑PASSENGER
# ------------------------
def create_reservation(
    flight_id: str,
    seat_class: str = "Economy",
    confirm: bool = False,
    # multi-passenger inputs
    passenger_count: Optional[int] = None,
    passengers: Optional[List[Dict[str, Any]]] = None,
    passengers_json: Optional[str] = None,
    # single-passenger fallback
    passenger_name: Optional[str] = None,
    passenger_age: Optional[int] = None,
    passenger_gender: Optional[str] = None,
    passenger_dob: Optional[str] = None,
    passenger_email: Optional[str] = None,
) -> Dict[str, Any]:

    flights = load_flights(ACTIVE_DATASET.get("flights", []))
    f = _find_flight_by_id(flights, flight_id)
    if not f:
        return _envelope(False, "RESERVATION_FLIGHT_NOT_FOUND", "Flight not found.", {"flight_id": flight_id})

    if not is_bookable(f):
        return _envelope(False, "RESERVATION_UNBOOKABLE", f"Flight status is '{f.status.value}'. Not bookable.", {"flight": f.to_public()})

    if seat_class not in f.available_classes:
        return _envelope(False, "RESERVATION_CLASS_NOT_AVAILABLE",
                         f"Seat class '{seat_class}' not available for this flight.", {"available": f.available_classes})

    parsed = _parse_passengers(
        passenger_count=passenger_count,
        passengers=passengers,
        passengers_json=passengers_json,
        passenger_name=passenger_name,
        passenger_age=passenger_age,
        passenger_gender=passenger_gender,
        passenger_dob=passenger_dob,
        passenger_email=passenger_email,
    )
    raw_list = parsed["passenger_dicts"]
    pax_count = parsed["count"]
    parse_errors = parsed["errors"]

    if f.seats_available < pax_count:
        return _envelope(False, "RESERVATION_NO_SEATS",
                         f"Only {f.seats_available} seat(s) left; requested {pax_count}.",
                         {"flight": f.to_public(), "requested_passengers": pax_count})

    issues: List[Dict[str, Any]] = []
    validated_passengers: List[Passenger] = []

    def _missing(field, idx): return {"index": idx, "field": field, "message": "Required field is missing."}

    if not raw_list and pax_count > 0:
        raw_list = [{} for _ in range(pax_count)]

    for idx in range(max(pax_count, len(raw_list))):
        entry = raw_list[idx] if idx < len(raw_list) else {}
        name = entry.get("name")
        age = entry.get("age")
        gender = entry.get("gender")
        dob = entry.get("dob")
        email = entry.get("email")

        missing = []
        if not name:   missing.append(_missing("name", idx))
        if age is None: missing.append(_missing("age", idx))
        if not gender: missing.append(_missing("gender", idx))
        if not dob:    missing.append(_missing("dob", idx))
        if not email:  missing.append(_missing("email", idx))

        if missing:
            issues.extend(missing)
            continue

        if isinstance(dob, str):
            dob_iso = _coerce_date_to_iso(dob)
            dob = dob_iso or dob

        try:
            p_obj = Passenger(name=name, age=int(age), gender=gender, dob=dob, email=email)
        except Exception as e:
            issues.append({"index": idx, "field": "passenger", "message": str(e)})
            continue

        ok_age, calc_age = validate_passenger_age_vs_dob(p_obj, now_utc())
        if not ok_age:
            issues.append({"index": idx, "field": "age", "message": f"Age does not match DOB; expected approximately {calc_age}."})

        validated_passengers.append(p_obj)

    # 💰 Pricing
    unit_price = _unit_price_for_class(f, seat_class)
    total = round(unit_price * max(1, pax_count), 2)
    bill = {
        "currency": "USD",
        "unit_price": unit_price,
        "passengers": max(1, pax_count),
        "subtotal": total,   # if you want taxes/fees later, add them here
        "total": total
    }

    # Preview
    if not confirm:
        return _envelope(True, "RESERVATION_PREVIEW",
                         "Preview generated. Provide any missing/invalid passenger details, then confirm to book.",
                         {
                             "flight": f.to_public(),
                             "seat_class": seat_class,
                             "passenger_count": pax_count,
                             "passengers": [p.model_dump(mode='json') for p in validated_passengers],
                             "pending_entries": raw_list,
                             "validation": {"ok": len(issues) == 0 and len(parse_errors) == 0,
                                            "issues": issues,
                                            "parse_errors": parse_errors},
                             "bill": bill,               # 👈 show per-class unit price & total
                             "next_action": "ask_confirmation" if not issues and not parse_errors else "collect_missing_passenger_details"
                         })

    # Confirm: require all passengers valid & counts match
    if issues or parse_errors or len(validated_passengers) != pax_count:
        return _envelope(False, "RESERVATION_VALIDATION_FAILED",
                         "Passenger details failed validation. Please correct before confirming.",
                         {
                             "passenger_count": pax_count,
                             "provided_valid": len(validated_passengers),
                             "validation": {"ok": False, "issues": issues, "parse_errors": parse_errors}
                         })

    reservation_id = gen_reservation_id()
    reservation = Reservation(
        reservation_id=reservation_id,
        flight_id=f.flight_id,
        passengers=validated_passengers,
        passenger_count=pax_count,
        seat_class=seat_class,
        total_price_usd=total,       # 👈 per-class total
        booked_at=now_utc(),
        flight_details=f,
    )
    _RESERVATIONS[reservation_id] = reservation

    return _envelope(True, "RESERVATION_CONFIRMED", "Your reservation is confirmed.", {
        "reservation": reservation.model_dump(mode="json"),
        "bill": bill                    # 👈 return bill alongside reservation
    })