# aroya_air/utils.py
from __future__ import annotations
from typing import List, Tuple, Iterable, Optional, Dict, Any, Set
from datetime import datetime, timezone, date, timedelta
from .models import Flight, SearchCriteria, FlightStatus, Passenger
import uuid

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def gen_reservation_id() -> str:
    return f"RSV-{uuid.uuid4().hex[:8].upper()}"

def normalize(s: str) -> str:
    return " ".join(s.strip().lower().split())

def load_flights(raw: Iterable[dict]) -> List[Flight]:
    return [Flight(**row) for row in raw]

def is_bookable(f: Flight) -> bool:
    return f.status not in {FlightStatus.CANCELLED, FlightStatus.LANDED}

def matches_cities(f: Flight, c: SearchCriteria) -> bool:
    if c.departure_city and normalize(f.departure_city) != normalize(c.departure_city):
        return False
    if c.arrival_city and normalize(f.arrival_city) != normalize(c.arrival_city):
        return False
    return True

def matches_date(f: Flight, d: Optional[date]) -> bool:
    return True if d is None else (f.departure_time.date() == d)

# ---- Flexible date parsing ----
_DATE_PATTERNS = [
    "%Y-%m-%d", "%Y/%m/%d",
    "%d-%m-%Y", "%d/%m/%Y",
    "%m-%d-%Y", "%m/%d/%Y",
    "%d %b %Y", "%d %B %Y",
    "%b %d, %Y", "%B %d, %Y",
    "%d %b", "%d %B", "%b %d", "%B %d",
]

def parse_date_flexible(value: str, today: Optional[date] = None) -> Optional[date]:
    """
    Accepts many forms:
      - '2025-11-14' / '14-11-2025' / '11/14/2025' / 'Nov 14, 2025' / '26 Nov'
      - 'today', 'tomorrow'
      - FULL ISO with time and tz: '2025-11-14T18:30:00+00:00', '2025-11-14T18:30:00Z'
    Returns a date (local to the timestamp’s own tz if provided).
    """
    if not value or not isinstance(value, str):
        return None

    v = value.strip()
    today = today or datetime.today().date()
    low = v.lower()

    # Relative
    if low == "today":
        return today
    if low == "tomorrow":
        return today + timedelta(days=1)

    # 1) Try strict ISO-8601 datetime (with or without 'Z'/offset)
    try:
        iso_v = v.replace("z", "+00:00") if v.endswith(("Z", "z")) else v
        dt = datetime.fromisoformat(iso_v)
        return dt.date()
    except Exception:
        pass

    # 2) Try supported strptime patterns
    for fmt in _DATE_PATTERNS:
        try:
            dt = datetime.strptime(v, fmt)
            if "%Y" not in fmt:  # year omitted -> assume current year
                dt = dt.replace(year=today.year)
            return dt.date()
        except ValueError:
            continue

    # 3) Try plain ISO date (YYYY-MM-DD) if missed above
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        return None

# ---- Facets for interactive exploration ----
def facets_for(flights: List[Flight], c: SearchCriteria) -> Dict[str, Any]:
    dests: Set[str] = set()
    dates: Set[str] = set()
    for f in flights:
        if c.departure_city and normalize(f.departure_city) != normalize(c.departure_city):
            continue
        if c.arrival_city and normalize(f.arrival_city) != normalize(c.arrival_city):
            continue
        dests.add(f.arrival_city)
        dates.add(f.departure_time.date().isoformat())
    return {
        "available_destinations": sorted(dests),
        "available_dates": sorted(dates)
    }

# ---- Passenger validation helpers ----
def approx_age_from_dob(dob: date, at: datetime) -> int:
    today = at.date()
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return max(0, years)

def validate_passenger_age_vs_dob(p: Passenger, at: datetime):
    calc_age = approx_age_from_dob(p.dob, at)
    return (abs(calc_age - p.age) <= 1, calc_age)
