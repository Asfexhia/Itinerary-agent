from __future__ import annotations

from ..models import Itinerary, ItineraryItem, ParsedIntent


class Planner:
    def plan(self, intent: ParsedIntent) -> Itinerary:
        # Minimal template plan: a morning/afternoon/evening slot per day.
        items: list[ItineraryItem] = []
        for day in range(1, intent.days + 1):
            items.extend(
                [
                    ItineraryItem(
                        day=day,
                        time="09:00",
                        title="Breakfast spot",
                        place_id="mock_place_breakfast",
                        notes="Start the day with something local.",
                    ),
                    ItineraryItem(
                        day=day,
                        time="11:00",
                        title="Main attraction",
                        place_id="mock_place_attraction",
                        notes="A top-rated sight based on your interests.",
                    ),
                    ItineraryItem(
                        day=day,
                        time="15:00",
                        title="Coffee / break",
                        place_id="mock_place_coffee",
                        notes="Recharge.",
                    ),
                    ItineraryItem(
                        day=day,
                        time="19:00",
                        title="Dinner",
                        place_id="mock_place_dinner",
                        notes="Try a well-reviewed restaurant.",
                    ),
                ]
            )

        return Itinerary(city=intent.city, days=intent.days, items=items)
