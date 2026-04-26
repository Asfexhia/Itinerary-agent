from __future__ import annotations

from dataclasses import dataclass


class GoogleMapsClient:
    def get_place_details(self, place_id: str) -> dict | None:  # pragma: no cover
        raise NotImplementedError


@dataclass
class MockGoogleMapsClient(GoogleMapsClient):
    city: str = "Seoul"

    def get_place_details(self, place_id: str) -> dict | None:
        # Deterministic, local-only mock data.
        mock_db = {
            "mock_place_breakfast": {
                "name": f"{self.city} Breakfast Cafe",
                "address": f"1 Morning St, {self.city}",
                "rating": 4.5,
            },
            "mock_place_attraction": {
                "name": f"{self.city} Landmark",
                "address": f"99 Central Ave, {self.city}",
                "rating": 4.7,
            },
            "mock_place_coffee": {
                "name": f"{self.city} Coffee Bar",
                "address": f"5 Espresso Rd, {self.city}",
                "rating": 4.6,
            },
            "mock_place_dinner": {
                "name": f"{self.city} Dinner House",
                "address": f"8 Sunset Blvd, {self.city}",
                "rating": 4.4,
            },
        }
        return mock_db.get(place_id)
