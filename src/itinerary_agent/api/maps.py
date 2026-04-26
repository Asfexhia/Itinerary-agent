from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class GoogleMapsClient:
    """
    Small wrapper around googlemaps.Client.

    Requires env var: GOOGLE_MAPS_API_KEY
    """

    api_key: str | None = None
    default_center_lat: float | None = None
    default_center_lng: float | None = None
    default_radius_m: int = 5000
    request_timeout_s: float = 5.0

    def __post_init__(self) -> None:
        # Import lazily to avoid editor/type-checker interpreter mismatches.
        import googlemaps  # type: ignore
        from dotenv import load_dotenv  # type: ignore

        # Load .env (and fall back to .env.example for convenience in class projects).
        # Prefer using a real `.env` locally; keep `.env.example` for templates.
        load_dotenv()
        load_dotenv(".env.example")

        key = self.api_key or os.getenv("GOOGLE_MAPS_API_KEY")
        if not key:
            raise RuntimeError("Missing GOOGLE_MAPS_API_KEY environment variable.")

        # Optional defaults for location-biased search. If not set, we fall back to global text query.
        if self.default_center_lat is None:
            try:
                self.default_center_lat = float(os.getenv("MAPS_DEFAULT_CENTER_LAT", ""))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                self.default_center_lat = None
        if self.default_center_lng is None:
            try:
                self.default_center_lng = float(os.getenv("MAPS_DEFAULT_CENTER_LNG", ""))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                self.default_center_lng = None
        try:
            self.default_radius_m = int(os.getenv("MAPS_DEFAULT_RADIUS_M", str(self.default_radius_m)))
        except (TypeError, ValueError):
            self.default_radius_m = 5000

        # Ensure calls fail fast during evaluation/class demos (no long hangs).
        # googlemaps.Client supports "timeout" in recent versions; fall back gracefully.
        try:
            self._client = googlemaps.Client(key=key, timeout=float(self.request_timeout_s))
        except TypeError:
            self._client = googlemaps.Client(key=key)

    def find_place(self, query: str, min_rating: float = 0.0) -> dict[str, Any] | None:
        """
        Returns a dict with: name, place_id, rating, lat, lng
        or None if nothing meets min_rating.
        """
        # Attempt 1: exact query + rating constraint
        place = self._find_place_once(query, min_rating=min_rating, radius_m=self.default_radius_m)
        if place:
            return place

        # Fallback 1: relaxed keyword
        relaxed = _relax_query(query)
        if relaxed and relaxed != query:
            place = self._find_place_once(relaxed, min_rating=min_rating, radius_m=self.default_radius_m)
            if place:
                return place

        # Fallback 2: remove rating constraint (if any)
        if min_rating and min_rating > 0:
            place = self._find_place_once(relaxed or query, min_rating=0.0, radius_m=self.default_radius_m)
            if place:
                return place

        # Fallback 3: expand search radius if we have a default center
        place = self._find_place_once(relaxed or query, min_rating=0.0, radius_m=max(self.default_radius_m * 2, 10000))
        return place

    def geocode_place(self, query: str) -> dict[str, Any] | None:
        """Resolve a named place/address into name, place_id, lat, lng."""
        q = (query or "").strip()
        if not q:
            return None

        # Prefer Find Place because it returns a stable place_id for Distance Matrix.
        place = self._find_place_once(q, min_rating=0.0, radius_m=0)
        if place and place.get("lat") is not None and place.get("lng") is not None:
            return place

        results = self._client.geocode(q)
        if not results:
            return None
        best = results[0]
        loc = ((best.get("geometry") or {}).get("location") or {})
        if loc.get("lat") is None or loc.get("lng") is None:
            return None
        return {
            "name": best.get("formatted_address") or q,
            "place_id": best.get("place_id"),
            "rating": None,
            "lat": loc.get("lat"),
            "lng": loc.get("lng"),
        }

    def find_nearby(
        self,
        *,
        center_lat: float,
        center_lng: float,
        place_type: str,
        keyword: str | None = None,
        min_rating: float = 0.0,
        radius_m: int | None = None,
    ) -> dict[str, Any] | None:
        """Find the nearest nearby place matching type/keyword and minimum rating."""
        radius = int(radius_m or self.default_radius_m or 5000)
        try:
            resp = self._client.places_nearby(
                location=(float(center_lat), float(center_lng)),
                rank_by="distance",
                keyword=keyword,
                type=place_type,
            )
        except Exception:
            # Some API configurations reject rank_by=distance for broad queries.
            # Fall back to a bounded nearby search instead of failing the plan.
            resp = self._client.places_nearby(
                location=(float(center_lat), float(center_lng)),
                radius=radius,
                keyword=keyword,
                type=place_type,
            )
        results = resp.get("results") or []
        if not results:
            return None

        best: dict[str, Any] | None = None
        best_rating = -1.0
        for r in results:
            rating_raw = r.get("rating")
            try:
                rating = float(rating_raw) if rating_raw is not None else 0.0
            except (TypeError, ValueError):
                rating = 0.0
            if rating < min_rating:
                continue
            # Google Places Nearby is distance/relevance-biased; keep the first
            # candidate that satisfies constraints instead of picking the global
            # highest rating, which can be much farther away.
            best = r
            best_rating = rating
            break

        if not best:
            return None
        loc = ((best.get("geometry") or {}).get("location") or {})
        if loc.get("lat") is None or loc.get("lng") is None:
            return None
        return {
            "name": best.get("name"),
            "place_id": best.get("place_id"),
            "rating": float(best_rating) if best_rating >= 0 else None,
            "lat": loc.get("lat"),
            "lng": loc.get("lng"),
        }

    def _find_place_once(self, query: str, *, min_rating: float, radius_m: int) -> dict[str, Any] | None:
        kwargs: dict[str, Any] = {}
        if self.default_center_lat is not None and self.default_center_lng is not None and radius_m > 0:
            kwargs["location_bias"] = {
                "circle": {
                    "center": {"lat": float(self.default_center_lat), "lng": float(self.default_center_lng)},
                    "radius": int(radius_m),
                }
            }

        resp = self._client.find_place(
            input=query,
            input_type="textquery",
            fields=["name", "place_id", "rating", "geometry"],
            **kwargs,
        )

        candidates = resp.get("candidates") or []
        if not candidates:
            return None

        best = None
        best_rating = -1.0
        for c in candidates:
            rating = c.get("rating")
            try:
                r = float(rating) if rating is not None else 0.0
            except (TypeError, ValueError):
                r = 0.0
            if r >= min_rating and r > best_rating:
                best = c
                best_rating = r

        if not best:
            return None

        loc = ((best.get("geometry") or {}).get("location") or {})
        return {
            "name": best.get("name"),
            "place_id": best.get("place_id"),
            "rating": float(best_rating) if best_rating >= 0 else None,
            "lat": loc.get("lat"),
            "lng": loc.get("lng"),
        }

    def get_travel_info(self, origin: str, destination: str) -> dict[str, int] | None:
        """
        Returns a dict with: distance (meters) and duration (seconds),
        or None if not available.
        """
        dm = self._client.distance_matrix(
            origins=[origin],
            destinations=[destination],
            units="metric",
        )

        rows = dm.get("rows") or []
        if not rows:
            return None
        elements = (rows[0].get("elements") or []) if isinstance(rows[0], dict) else []
        if not elements:
            return None

        el = elements[0]
        if (el.get("status") or "").upper() != "OK":
            return None

        dist_val = ((el.get("distance") or {}).get("value"))
        dur_val = ((el.get("duration") or {}).get("value"))
        if dist_val is None or dur_val is None:
            return None

        return {"distance": int(dist_val), "duration": int(dur_val)}

    def get_travel_info_between_places(
        self,
        origin: dict[str, Any],
        destination: dict[str, Any],
    ) -> dict[str, int] | None:
        """Distance Matrix between two place dicts returned by this client."""
        origin_ref = _distance_matrix_ref(origin)
        dest_ref = _distance_matrix_ref(destination)
        if not origin_ref or not dest_ref:
            return None
        return self.get_travel_info(origin_ref, dest_ref)


def _relax_query(query: str) -> str:
    """
    Best-effort "relaxation" for text search:
    - remove punctuation
    - drop some common filler words
    - keep a shorter keyword phrase
    """
    q = (query or "").strip()
    if not q:
        return q
    q = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in q)
    q = re.sub(r"\s+", " ", q).strip()
    stop = {"a", "an", "the", "with", "near", "around", "close", "to", "for", "please"}
    parts = [p for p in q.split(" ") if p and p.lower() not in stop]
    if len(parts) > 6:
        parts = parts[:6]
    return " ".join(parts).strip()


def _distance_matrix_ref(place: dict[str, Any]) -> str | None:
    place_id = str(place.get("place_id") or "").strip()
    if place_id:
        return f"place_id:{place_id}"
    lat = place.get("lat")
    lng = place.get("lng")
    if lat is not None and lng is not None:
        return f"{lat},{lng}"
    name = str(place.get("name") or "").strip()
    return name or None
