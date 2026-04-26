from __future__ import annotations

import json
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

# Optional: CORS (browser) + JSON API for the Vite dev server
_DEFAULT_CORS = "http://127.0.0.1:5173,http://localhost:5173"


def _cors_header(origin: str | None) -> str:
    if origin and (origin in _DEFAULT_CORS.split(",") or origin.startswith("http://localhost:")):
        return origin
    return "http://localhost:5173"


def _classify_error_reason(output: dict[str, Any] | None, exc: Exception | None) -> str:
    if exc is not None:
        s = f"{type(exc).__name__}: {exc}"
        if "key" in s.lower() or "google" in s.lower() or "maps" in s.lower() or "connection" in s.lower():
            return "api_failure"
        return "api_failure"
    if not output:
        return "invalid_plan"
    errs = output.get("last_errors") or []
    for e in errs:
        t = str(e)
        if "time_constraint_violation" in t or t == "time_constraint_violation":
            return "time_constraint_violation"
        if "invalid_plan" in t:
            return "invalid_plan"
    reason = str(output.get("reason", ""))
    if "time_constraint" in reason.lower() or "time_constraint_violation" in reason:
        return "time_constraint_violation"
    if "Intent parsing failed" in reason:
        return "api_failure"
    if not output.get("ok", False):
        return "invalid_plan"
    return "invalid_plan"


def _build_response_payload(agent_out: dict[str, Any]) -> dict[str, Any]:
    if not agent_out.get("ok", False):
        return {
            "success": False,
            "plan": [],
            "total_time": None,
            "error_reason": _classify_error_reason(agent_out, None),
        }
    itin = agent_out.get("itinerary") or {}
    items = itin.get("items") if isinstance(itin, dict) else None
    if not isinstance(items, list):
        items = []
    plan = [{"name": str(it.get("title", "Stop")), "duration": 60} for it in items if isinstance(it, dict)]
    meta = agent_out.get("plan_meta") or {}
    total = meta.get("solver_total_minutes")
    if total is None:
        total = len(plan) * 60
    return {
        "success": True,
        "plan": plan,
        "total_time": int(total),
        "error_reason": None,
    }


def _extract_min_rating(query: str, default: float = 4.0) -> float:
    q = query or ""
    patterns = [
        r"(?:rating|rated|score)\s*(?:over|above|>=|at least)?\s*([0-5](?:\.\d+)?)",
        r"(?:评分|評分)\s*(?:超过|超過|大于|高于|至少|>=)?\s*([0-5](?:\.\d+)?)",
    ]
    for pat in patterns:
        m = re.search(pat, q, flags=re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return default


def _rating_requested(query: str) -> bool:
    return bool(
        re.search(
            r"(rating|rated|score|评分|評分|星级|星級|stars?|over\s*[0-5]|above\s*[0-5]|大于\s*[0-5]|超过\s*[0-5]|高于\s*[0-5])",
            query or "",
            flags=re.IGNORECASE,
        )
    )


def _duration_for_activity(query: str, activity_words: tuple[str, ...], default_min: int) -> int:
    q = query or ""
    windows: list[str] = []
    for word in activity_words:
        start = 0
        while True:
            idx = q.lower().find(word.lower(), start)
            if idx < 0:
                break
            windows.append(q[max(0, idx - 40) : idx + len(word) + 40])
            start = idx + len(word)
    for text in windows or ([q] if any(word.lower() in q.lower() for word in activity_words) else []):
        low = text.lower()
        if "半个小时" in text or "半小时" in text or "half hour" in low:
            return 30
        if "一个小时" in text or "一小时" in text or "一個小時" in text:
            return 60
        hour_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|小时|小時)", text, flags=re.IGNORECASE)
        if hour_match:
            try:
                return max(1, int(round(float(hour_match.group(1)) * 60)))
            except ValueError:
                pass
        min_match = re.search(r"(\d+)\s*(?:minutes?|mins?|分钟|分鐘)", text, flags=re.IGNORECASE)
        if min_match:
            try:
                return max(1, int(min_match.group(1)))
            except ValueError:
                pass
    return default_min


def _query_has_any(query: str, words: tuple[str, ...]) -> bool:
    q = (query or "").lower()
    return any(word.lower() in q for word in words)


def _return_requested(query: str) -> bool:
    return _query_has_any(
        query,
        (
            "return",
            "back to",
            "go back",
            "come back",
            "回到",
            "返回",
            "再回",
            "最后再回",
        ),
    )


def _restaurant_keyword(query: str) -> str:
    q = (query or "").lower()
    cuisine_map = [
        (("中餐", "中国菜", "中國菜", "chinese"), "Chinese restaurant"),
        (("日料", "日本菜", "寿司", "壽司", "sushi", "japanese"), "Japanese restaurant"),
        (("韩餐", "韓餐", "韩国菜", "韓國菜", "korean"), "Korean restaurant"),
        (("意大利", "義大利", "italian", "pizza", "pasta"), "Italian restaurant"),
        (("墨西哥", "mexican", "taco"), "Mexican restaurant"),
        (("印度", "indian"), "Indian restaurant"),
        (("泰国", "泰國", "thai"), "Thai restaurant"),
        (("越南", "vietnamese", "pho"), "Vietnamese restaurant"),
        (("素食", "vegan", "vegetarian"), "vegetarian restaurant"),
    ]
    for needles, keyword in cuisine_map:
        if any(n.lower() in q for n in needles):
            return keyword
    return "restaurant"


def _task_specs_from_query(query: str) -> list[dict[str, Any]]:
    """Small deterministic parser for demo queries near a start location."""
    specs: list[dict[str, Any]] = []
    min_rating = _extract_min_rating(query) if _rating_requested(query) else 0.0
    catalog = [
        {
            "category": "restaurant",
            "place_type": "restaurant",
            "keyword": _restaurant_keyword(query),
            "words": (
                "餐厅",
                "餐廳",
                "饭",
                "飯",
                "restaurant",
                "dinner",
                "lunch",
                "中餐",
                "中国菜",
                "中國菜",
                "chinese",
                "sushi",
                "japanese",
                "korean",
                "italian",
                "mexican",
                "indian",
                "thai",
            ),
            "default_duration": 30,
            "min_rating": min_rating,
        },
        {
            "category": "cafe",
            "place_type": "cafe",
            "keyword": "coffee",
            "words": ("coffee", "cafe", "café", "咖啡"),
            "default_duration": 30,
            "min_rating": min_rating,
        },
        {
            "category": "museum",
            "place_type": "museum",
            "keyword": "museum",
            "words": ("museum", "博物馆", "博物館"),
            "default_duration": 60,
            "min_rating": min_rating,
        },
        {
            "category": "park",
            "place_type": "park",
            "keyword": "park",
            "words": ("park", "公园", "公園", "playground", "garden", "花园", "花園"),
            "default_duration": 60,
            "min_rating": min_rating,
        },
        {
            "category": "library",
            "place_type": "library",
            "keyword": "library",
            "words": ("library", "图书馆", "圖書館"),
            "default_duration": 45,
            "min_rating": min_rating,
        },
        {
            "category": "supermarket",
            "place_type": "supermarket",
            "keyword": "supermarket",
            "words": ("supermarket", "grocery", "market", "超市"),
            "default_duration": 30,
            "min_rating": min_rating,
        },
        {
            "category": "gym",
            "place_type": "gym",
            "keyword": "gym",
            "words": ("gym", "fitness", "健身房"),
            "default_duration": 60,
            "min_rating": min_rating,
        },
        {
            "category": "aquarium",
            "place_type": "aquarium",
            "keyword": "aquarium",
            "words": ("aquarium", "oceanarium", "海洋馆", "海洋館", "水族馆", "水族館"),
            "default_duration": 90,
            "min_rating": min_rating,
        },
        {
            "category": "zoo",
            "place_type": "zoo",
            "keyword": "zoo",
            "words": ("zoo", "动物园", "動物園"),
            "default_duration": 90,
            "min_rating": min_rating,
        },
        {
            "category": "movie_theater",
            "place_type": "movie_theater",
            "keyword": "movie theater",
            "words": ("movie", "cinema", "theater", "theatre", "电影院", "電影院", "影院"),
            "default_duration": 120,
            "min_rating": min_rating,
        },
        {
            "category": "shopping_mall",
            "place_type": "shopping_mall",
            "keyword": "shopping mall",
            "words": ("mall", "shopping", "商场", "商場", "购物中心", "購物中心"),
            "default_duration": 90,
            "min_rating": min_rating,
        },
        {
            "category": "book_store",
            "place_type": "book_store",
            "keyword": "bookstore",
            "words": ("bookstore", "book store", "书店", "書店"),
            "default_duration": 45,
            "min_rating": min_rating,
        },
        {
            "category": "tourist_attraction",
            "place_type": "tourist_attraction",
            "keyword": "tourist attraction",
            "words": ("attraction", "landmark", "sightseeing", "景点", "景點", "地标", "地標"),
            "default_duration": 60,
            "min_rating": min_rating,
        },
        {
            "category": "art_gallery",
            "place_type": "art_gallery",
            "keyword": "art gallery",
            "words": ("gallery", "art gallery", "美术馆", "美術館", "画廊", "畫廊"),
            "default_duration": 60,
            "min_rating": min_rating,
        },
        {
            "category": "bar",
            "place_type": "bar",
            "keyword": "bar",
            "words": ("bar", "pub", "酒吧"),
            "default_duration": 60,
            "min_rating": min_rating,
        },
        {
            "category": "bakery",
            "place_type": "bakery",
            "keyword": "bakery",
            "words": ("bakery", "bread", "pastry", "面包店", "麵包店", "甜品"),
            "default_duration": 30,
            "min_rating": min_rating,
        },
        {
            "category": "pharmacy",
            "place_type": "pharmacy",
            "keyword": "pharmacy",
            "words": ("pharmacy", "drugstore", "药店", "藥店"),
            "default_duration": 20,
            "min_rating": min_rating,
        },
        {
            "category": "hospital",
            "place_type": "hospital",
            "keyword": "hospital",
            "words": ("hospital", "clinic", "医院", "醫院", "诊所", "診所"),
            "default_duration": 60,
            "min_rating": min_rating,
        },
        {
            "category": "train_station",
            "place_type": "train_station",
            "keyword": "train station",
            "words": ("train station", "station", "subway", "transit", "火车站", "火車站", "地铁站", "地鐵站", "车站", "車站"),
            "default_duration": 15,
            "min_rating": min_rating,
        },
        {
            "category": "university",
            "place_type": "university",
            "keyword": "university",
            "words": ("university", "college", "campus", "大学", "大學", "学院", "學院"),
            "default_duration": 60,
            "min_rating": min_rating,
        },
    ]

    # Preserve the user's written order by locating the first mention of each supported activity.
    found: list[tuple[int, dict[str, Any]]] = []
    q_lower = (query or "").lower()
    for item in catalog:
        positions = [q_lower.find(word.lower()) for word in item["words"] if q_lower.find(word.lower()) >= 0]
        if not positions:
            continue
        found.append((min(positions), item))

    for _, item in sorted(found, key=lambda x: x[0]):
        specs.append(
            {
                "category": item["category"],
                "place_type": item["place_type"],
                "keyword": item["keyword"],
                "min_rating": item["min_rating"],
                "duration": _duration_for_activity(query, item["words"], item["default_duration"]),
            }
        )

    if specs:
        return specs

    # Fallback: search the whole text as one nearby point of interest instead of reusing defaults.
    return [
        {
            "category": "place",
            "place_type": "point_of_interest",
            "keyword": query,
            "min_rating": min_rating,
            "duration": 60,
        }
    ]


def _travel_minutes(travel: dict[str, int] | None) -> int:
    if not travel:
        return 0
    return max(1, round(int(travel.get("duration", 0)) / 60))


def _distance_text(travel: dict[str, int] | None) -> str | None:
    if not travel:
        return None
    meters = int(travel.get("distance", 0))
    if meters >= 1000:
        return f"{meters / 1000:.1f} km"
    return f"{meters} m"


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _plan_stop(
    place: dict[str, Any],
    *,
    duration: int,
    category: str,
    travel: dict[str, int] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    return {
        "name": str(place.get("name") or "Stop"),
        "lat": _float_or_none(place.get("lat")),
        "lng": _float_or_none(place.get("lng")),
        "duration": int(duration),
        "category": category,
        "rating": place.get("rating"),
        "place_id": place.get("place_id"),
        "travel_time": _travel_minutes(travel),
        "travel_distance": _distance_text(travel),
        "note": note,
    }


def _build_origin_based_plan(origin_text: str, query: str) -> dict[str, Any]:
    from .api.maps import GoogleMapsClient
    from .config import load_settings

    settings = load_settings()
    maps = GoogleMapsClient(api_key=settings.google_maps_api_key)

    origin = maps.geocode_place(origin_text)
    if not origin:
        return {
            "success": False,
            "plan": [],
            "total_time": None,
            "error_reason": "invalid_plan",
            "message": f"Could not resolve start location: {origin_text}",
        }

    task_specs = _task_specs_from_query(query)
    stops = [_plan_stop(origin, duration=0, category="start", note="Start point")]
    places: list[dict[str, Any]] = [origin]
    current = origin

    for spec in task_specs:
        sys.stderr.write(
            f"Nearby search category={spec['category']!r} keyword={spec['keyword']!r} "
            f"min_rating={spec.get('min_rating')!r} center=({current.get('lat')}, {current.get('lng')})\n"
        )
        place = maps.find_nearby(
            center_lat=float(current["lat"]),
            center_lng=float(current["lng"]),
            place_type=str(spec["place_type"]),
            keyword=str(spec["keyword"]),
            min_rating=float(spec.get("min_rating") or 0.0),
            radius_m=3500,
        )
        if not place:
            return {
                "success": False,
                "plan": [],
                "total_time": None,
                "error_reason": "invalid_plan",
                "message": f"No nearby {spec['category']} found for this request.",
            }
        travel = maps.get_travel_info_between_places(current, place)
        stops.append(
            _plan_stop(
                place,
                duration=int(spec["duration"]),
                category=str(spec["category"]),
                travel=travel,
            )
        )
        places.append(place)
        current = place

    if _return_requested(query):
        travel = maps.get_travel_info_between_places(current, origin)
        stops.append(
            _plan_stop(origin, duration=0, category="return", travel=travel, note="Return to start")
        )
        places.append(origin)

    total = sum((stop.get("duration", 0) or 0) + (stop.get("travel_time", 0) or 0) for stop in stops)
    return {
        "success": True,
        "plan": stops,
        "total_time": int(total),
        "error_reason": None,
        "origin": origin_text,
        "interpreted_tasks": task_specs,
    }


class PlanRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        sys.stderr.write(f"{self.client_address[0]} - {format % args}\n")

    def _send(
        self,
        status: int,
        body: bytes,
        content_type: str = "application/json; charset=utf-8",
    ) -> None:
        origin = self.headers.get("Origin")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", _cors_header(origin))
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, b"")

    def do_GET(self) -> None:  # noqa: N802
        p = urlparse(self.path)
        if p.path == "/plan" or p.path == "/":
            msg = json.dumps(
                {
                    "message": "Itinerary API — POST /plan with JSON { \"query\": \"...\" }",
                    "ok": True,
                }
            ).encode("utf-8")
            self._send(200, msg)
        else:
            self._send(404, b'{"error":"not found"}')

    def do_POST(self) -> None:  # noqa: N802
        p = urlparse(self.path)
        if p.path != "/plan":
            self._send(404, b'{"error":"not found"}')
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send(400, b'{"error":"invalid json"}')
            return
        query = (data.get("query") or "").strip()
        origin = (data.get("origin") or data.get("start_location") or "").strip()
        if not query:
            self._send(
                400,
                json.dumps(
                    {
                        "success": False,
                        "plan": [],
                        "total_time": None,
                        "error_reason": "invalid_plan",
                    }
                ).encode("utf-8"),
            )
            return

        try:
            if origin:
                sys.stderr.write(f"Origin-based plan request origin={origin!r} query={query!r}\n")
                payload = _build_origin_based_plan(origin, query)
            else:
                from .agent_loop import run_agent

                out = run_agent(query, disable_solver=False)
                payload = _build_response_payload(out)
            if isinstance(payload.get("plan"), list):
                sys.stderr.write(
                    "Plan response stops="
                    + json.dumps(
                        [
                            {"name": p.get("name"), "lat": p.get("lat"), "lng": p.get("lng")}
                            for p in payload["plan"]
                            if isinstance(p, dict)
                        ],
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(traceback.format_exc())
            payload = {
                "success": False,
                "plan": [],
                "total_time": None,
                "error_reason": _classify_error_reason(None, e),
            }
        self._send(200, json.dumps(payload).encode("utf-8"))


def main(host: str = "0.0.0.0", port: int = 8000) -> None:
    print(f"Listening on http://{host}:{port}  (POST /plan)")
    print("Set GOOGLE_MAPS_API_KEY in .env for real place lookup.")
    httpd = ThreadingHTTPServer((host, port), PlanRequestHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        httpd.server_close()


if __name__ == "__main__":
    main()
