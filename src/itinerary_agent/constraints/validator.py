from __future__ import annotations

from ..models import Itinerary, ParsedIntent


class ConstraintValidator:
    def validate(self, intent: ParsedIntent, itinerary: Itinerary) -> list[str]:
        errors: list[str] = []

        if itinerary.days != intent.days:
            errors.append(
                f"Days mismatch: intent={intent.days} itinerary={itinerary.days}"
            )

        if itinerary.city.strip().lower() != intent.city.strip().lower():
            errors.append(
                f"City mismatch: intent='{intent.city}' itinerary='{itinerary.city}'"
            )

        # Simple pace constraint: cap items per day.
        max_items = {"relaxed": 3, "balanced": 5, "packed": 7}[intent.pace]
        for day in range(1, intent.days + 1):
            count = sum(1 for it in itinerary.items if it.day == day)
            if count > max_items:
                errors.append(
                    f"Too many items on day {day}: {count} (max {max_items} for {intent.pace})"
                )

        # Basic field sanity.
        for it in itinerary.items:
            if not it.title.strip():
                errors.append("Itinerary item has empty title.")
            if not it.time.strip():
                errors.append(f"Item '{it.title}' missing time.")

        return errors
