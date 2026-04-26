from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from ..models import Itinerary


@dataclass(frozen=True)
class ConstraintResult:
    ok: bool
    errors: list[str]


def _parse_deadline_to_datetime(deadline: str) -> datetime | None:
    """
    Accepts:
    - ISO-8601 datetime/date (best-effort via fromisoformat)
    - "HH:MM" (interpreted as today local date)
    """
    s = (deadline or "").strip()
    if not s:
        return None
    # "HH:MM"
    if len(s) == 5 and s[2] == ":":
        try:
            hh = int(s[:2])
            mm = int(s[3:])
            today = datetime.now().date()
            return datetime.combine(today, time(hour=hh, minute=mm))
        except ValueError:
            return None
    try:
        # Accepts "YYYY-MM-DD" too (becomes midnight)
        return datetime.fromisoformat(s)
    except ValueError:
        return None


class ConstraintSolver:
    """
    Minimal constraint validator/solver for the new intent schema:
      constraints: { rating, deadline, duration }
    """

    def validate(self, intent: dict, itinerary: Itinerary) -> ConstraintResult:
        errors: list[str] = []
        constraints = intent.get("constraints") if isinstance(intent, dict) else None
        if not isinstance(constraints, dict):
            constraints = {}

        # rating constraint is checked during planning (filtering),
        # but also validate item notes contain rating if present.
        rating = constraints.get("rating", None)
        if rating is not None:
            try:
                min_rating = float(rating)
                if not (0.0 <= min_rating <= 5.0):
                    errors.append(f"constraints.rating out of range: {min_rating}")
            except (TypeError, ValueError):
                errors.append("constraints.rating must be a number between 0 and 5")

        # duration constraint: total planned duration in minutes
        duration = constraints.get("duration", None)
        if duration is not None:
            try:
                dur_min = int(duration)
                if dur_min <= 0:
                    errors.append("constraints.duration must be positive minutes")
            except (TypeError, ValueError):
                errors.append("constraints.duration must be integer minutes")

        # deadline constraint: must be parseable (we don't simulate schedule precisely yet)
        deadline = constraints.get("deadline", None)
        if deadline is not None:
            dl = _parse_deadline_to_datetime(str(deadline))
            if dl is None:
                errors.append("constraints.deadline must be ISO-8601 or HH:MM")

        # Basic itinerary sanity
        if not itinerary.items:
            errors.append("Itinerary has no items.")
        for it in itinerary.items:
            if not it.title.strip():
                errors.append("Itinerary item has empty title.")
            if not it.time.strip():
                errors.append(f"Item '{it.title}' missing time.")

        return ConstraintResult(ok=(len(errors) == 0), errors=errors)

