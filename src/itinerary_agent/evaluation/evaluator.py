from __future__ import annotations

from ..models import Itinerary, ParsedIntent


class Evaluator:
    def evaluate(
        self, intent: ParsedIntent, itinerary: Itinerary, validation_errors: list[str]
    ) -> dict[str, float]:
        # Toy metrics meant to be easy to extend.
        total_items = float(len(itinerary.items))
        days = float(max(1, itinerary.days))
        items_per_day = total_items / days

        valid = 1.0 if not validation_errors else 0.0
        coverage = self._interest_coverage(intent, itinerary)

        return {
            "valid": valid,
            "items_per_day": items_per_day,
            "interest_coverage": coverage,
        }

    def _interest_coverage(self, intent: ParsedIntent, itinerary: Itinerary) -> float:
        if not intent.interests:
            return 1.0
        text = " ".join([it.title + " " + (it.notes or "") for it in itinerary.items]).lower()
        hit = sum(1 for interest in intent.interests if interest.lower() in text)
        return float(hit) / float(len(intent.interests))
