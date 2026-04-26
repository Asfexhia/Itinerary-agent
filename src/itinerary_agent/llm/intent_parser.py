from __future__ import annotations

import math
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import requests

from ..models import ParsedIntent, UserRequest

# Canonical place type vocabulary: can extend as needed
PLACE_TYPE_KEYWORDS = [
    "coffee shop", "supermarket", "restaurant", "bar", "museum", "park",
    "cafe", "bakery", "hotel", "pharmacy", "library", "home", "school", "store",
    "mall", "university", "campus", "airport", "station", "gym", "hospital",
    "theater", "cinema", "zoo", "art gallery", "gallery", "garden", "beach", "market",
    "train station", "bus station",
    # common variants that show up in user requests / LLM outputs
    "grocery", "grocery store", "groceries",
]
# Add singulars, plurals, and unique base words to keyword set for matching
def place_type_variants(keywords: list[str]) -> set[str]:
    kw_set = set()
    # Avoid overly-generic component words that cause false positives
    generic_words = {
        "shop", "store", "station", "market", "gallery", "garden",
        "university", "campus", "airport", "hospital", "school", "home",
        "train", "bus",
    }
    for kw in keywords:
        kw_set.add(kw)
        if not kw.endswith('s'):
            kw_set.add(kw + 's')
        for word in kw.split():
            if len(word) > 3:
                if word.lower() not in generic_words:
                    kw_set.add(word)
    return kw_set
_PLACE_TYPE_SET = place_type_variants(PLACE_TYPE_KEYWORDS)
# Longest-first for matching priority
_PLACE_TYPE_LIST = sorted(_PLACE_TYPE_SET, key=lambda x: -len(x))


def extract_place_types(text: str) -> list[str]:
    """
    Extract canonical place types from text in the order they appear,
    based strictly on PLACE_TYPE_KEYWORDS and obvious/close variants.
    Does not extract constraint words or actions.
    """
    lower = text.lower()
    found = []
    for kw in _PLACE_TYPE_LIST:
        # ex: \bcoffee shop\b or \bpharmacy\b, only as word/phrase boundaries
        if re.search(r'\b{}\b'.format(re.escape(kw)), lower) and kw not in found:
            found.append(kw)
    return found


class LLMClient:
    def complete(self, prompt: str) -> str:  # pragma: no cover
        raise NotImplementedError


@dataclass
class MockLLMClient(LLMClient):
    def complete(self, prompt: str) -> str:
        # Extract mock intent: ONLY place types for tasks, constraints separately.
        text = prompt.lower()
        tasks = extract_place_types(text)
        # Constraints
        rating = None
        rating_m = re.search(r"(?:rating|stars?)\s*(?:above|over|>=|at\s*least)?\s*([\d.]+)", text)
        if not rating_m:
            rating_m = re.search(r"\b([\d.]+)\s*(?:stars?|rating)\b", text)
        if rating_m:
            try:
                rating = float(rating_m.group(1))
            except Exception:
                rating = None
        deadline = None
        deadline_m = re.search(r"(?:before|by|until|no\s*later\s*than)\s+([0-9]{1,2}(?::[0-9]{2})?\s*(?:[ap]\.?\s*m\.?)?)", text)
        if deadline_m:
            deadline = deadline_m.group(1).strip()
        duration = None
        duration_m = re.search(r"(?:stay|for|within|in)\s*(\d+(?:\.\d+)?)\s*(hours?|minutes?)", text)
        if duration_m:
            n = float(duration_m.group(1))
            unit = duration_m.group(2)
            duration = int(round(n * 60 if 'hour' in unit else n))
        # strict JSON output (as string) for _parse_mock_format()
        return json.dumps({
            "tasks": tasks,
            "constraints": {
                "rating": rating,
                "deadline": deadline,
                "duration": duration
            }
        })


class IntentParser:
    def __init__(self, llm: LLMClient):
        self._llm = llm

    def parse(self, req: UserRequest) -> ParsedIntent:
        prompt = f"""
You are an intent extraction engine for a travel assistant.

[STRICT JSON SCHEMA, NO EXTRAS]
{{
    "tasks": ["List ONLY place types the user wants to visit (e.g., 'coffee shop', 'supermarket', 'home'). Constraints must NOT appear here. No locations, actions, or descriptors."],
    "constraints": {{
        "rating": float or null, // Minimum Google Maps rating (e.g., 4.5)
        "deadline": "string (HH:MM) or null", // Time to finish (e.g., '18:00')
        "duration": int or null // Minutes stay, or null
    }}
}}

[RULES]
- In 'tasks', include ONLY place types. DO NOT include constraints, ratings, durations, locations, or actions.
- Constraints like rating, deadline, or duration must NOT appear in 'tasks'. Instead, put them under 'constraints'.
- Do not explain. Only strict JSON.

[USER QUERY]
{req.text}
"""
        raw = self._llm.complete(prompt)
        return self._parse_mock_format(raw, fallback_text=req.text)

    def _parse_mock_format(self, raw: str, fallback_text: str) -> ParsedIntent:
        """Parse LLM output which should be a JSON string with strict 'tasks' and 'constraints',
        but fallback to regex extraction if format is wrong.
        """
        try:
            obj = json.loads(raw)
        except Exception:
            obj = None
        if not isinstance(obj, dict):
            # fallback: heuristically extract from text
            tasks = extract_place_types(fallback_text)
            rating = _extract_rating(fallback_text)
            deadline = _extract_deadline_text(fallback_text)
            duration = _extract_duration_text(fallback_text)
            return ParsedIntent(
                city="",
                days=1,
                interests=tasks,
                pace="",
                tasks=tasks,
                constraints={
                    "rating": _normalize_rating(rating),
                    "deadline": deadline,
                    "duration": _normalize_duration_minutes(duration),
                }
            )  # type: ignore[arg-type]

        # Normalize tasks: drop any non-place-type, dedup, keep order
        tasks = []
        raw_tasks = obj.get("tasks", [])
        if isinstance(raw_tasks, list):
            for t in raw_tasks:
                if isinstance(t, str):
                    pts = extract_place_types(t)
                    for pt in pts:
                        if pt not in tasks:
                            tasks.append(pt)
        if not tasks:
            # fallback: try to extract from fallback_text
            tasks = extract_place_types(fallback_text)

        # Only pass the allowed and normalized constraints
        constraints_raw = obj.get("constraints", {}) if isinstance(obj.get("constraints"), dict) else {}
        rating = _normalize_rating(constraints_raw.get("rating"))
        deadline = constraints_raw.get("deadline")
        duration = _normalize_duration_minutes(constraints_raw.get("duration"))
        # fallback from text
        if rating is None:
            rating = _extract_rating(fallback_text)
            rating = _normalize_rating(rating)
        if not deadline:
            deadline = _extract_deadline_text(fallback_text)
        if duration is None:
            duration = _extract_duration_text(fallback_text)
            duration = _normalize_duration_minutes(duration)

        return ParsedIntent(
            city="",
            days=1,
            interests=tasks,
            pace="",
            tasks=tasks,
            constraints={
                "rating": rating,
                "deadline": deadline,
                "duration": duration,
            }
        )  # type: ignore[arg-type]


def parse_intent(
    query: str,
    *,
    model: str = "llama3.1:8b",
    host: str = "http://127.0.0.1:11434",
    timeout_s: float = 20.0,
    max_attempts: int = 2,
) -> dict[str, Any]:
    """
    Call local Ollama/LLM and return strictly separated intent:
    - tasks: only place types (e.g., ['coffee shop', 'supermarket'])
    - constraints: no place types, only rating/deadline/duration

    Output:
      {
        "tasks": [place_type, ...],
        "constraints": {
          "rating": float | null,
          "deadline": str | null,
          "duration": int | null
        }
      }
    """
    url = f"{host.rstrip('/')}/api/generate"
    # Fast fail if Ollama is not reachable, so evaluation/agent loop doesn't hang on long read timeouts.
    try:
        requests.get(f"{host.rstrip('/')}/api/tags", timeout=2.0).raise_for_status()
    except Exception as e:
        return _fallback_intent_from_query(query, now=datetime.now(), reason=f"Ollama unreachable: {type(e).__name__}: {e}")

    base_prompt = (
        "Extract structured intent from a user query.\n"
        "Return STRICT JSON (no extra keys, no markdown, no locations or actions):\n"
        '{ "tasks": [string], "constraints": { "rating": number|null, "deadline": string|null, "duration": number|null } }\n'
        "- In 'tasks', INCLUDE ONLY place types mentioned (e.g., 'coffee shop', 'supermarket', 'home') and nothing else.\n"
        "- Constraints (rating, deadline, duration) must appear only under 'constraints' and NOT in 'tasks'.\n"
        f"User query: {query}\n"
    )

    last_error: str | None = None
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        prompt = base_prompt
        if last_error:
            prompt += (
                "\nYour previous output was invalid.\n"
                f"Reason: {last_error}\n"
                "Try again and output ONLY strict JSON matching the schema.\n"
            )
        try:
            # Ollama supports forcing JSON output via "format": "json" on newer versions.
            # If unsupported, it is ignored server-side and we still fall back to robust extraction.
            resp = requests.post(
                url,
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0},
                },
                timeout=timeout_s,
            )
            resp.raise_for_status()
            data = resp.json()
            text = (data.get("response") or "").strip()
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            # network / server / model errors: don't block evaluation by retrying;
            # fall back to heuristic parsing from the user query.
            break

        try:
            parsed = _safe_json_from_text(text)
            normalized = _normalize_and_validate_intent_dict(parsed, now=datetime.now())
            # If the model returns an empty tasks list (common when it over-filters),
            # fall back to deterministic place-type extraction from the user query.
            if not normalized.get("tasks"):
                normalized["tasks"] = extract_place_types(query) or _infer_count_based_tasks(query)
            return normalized
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            continue

    # Last-resort fallback: satisfy schema with strictly separated types/constraints
    return _fallback_intent_from_query(query, now=datetime.now(), reason=last_error)


def _normalize_and_validate_intent_dict(obj: Any, *, now: datetime) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise ValueError("Top-level output must be a JSON object")
    allowed_top = {"tasks", "constraints"}
    extra_top = set(obj.keys()) - allowed_top
    if extra_top:
        raise ValueError(f"Extra top-level keys not allowed: {sorted(extra_top)}")
    if "tasks" not in obj or "constraints" not in obj:
        raise ValueError("Missing required keys: 'tasks' and 'constraints'")

    tasks_raw = obj.get("tasks")
    if not isinstance(tasks_raw, list):
        raise ValueError("'tasks' must be a list")
    tasks: list[str] = []
    # Only valid place types in tasks, dedup and preserve order
    for t in tasks_raw:
        if isinstance(t, str):
            pts = extract_place_types(t)
            for pt in pts:
                if pt not in tasks:
                    tasks.append(pt)
    constraints_raw = obj.get("constraints")
    if not isinstance(constraints_raw, dict):
        raise ValueError("'constraints' must be an object")
    allowed_constraints = {"rating", "deadline", "duration"}
    extra_constraints = set(constraints_raw.keys()) - allowed_constraints
    if extra_constraints:
        raise ValueError(f"Extra constraint keys not allowed: {sorted(extra_constraints)}")

    rating = _normalize_rating(constraints_raw.get("rating"))
    deadline = _normalize_deadline(constraints_raw.get("deadline"), now=now)
    duration = _normalize_duration_minutes(constraints_raw.get("duration"))

    return {"tasks": tasks, "constraints": {"rating": rating, "deadline": deadline, "duration": duration}}


def _fallback_intent_from_query(query: str, *, now: datetime, reason: str | None) -> dict[str, Any]:
    text = (query or "").strip()
    tasks = extract_place_types(text)
    if not tasks:
        tasks = _infer_count_based_tasks(text)
    rating = _extract_rating(text)
    deadline_raw = _extract_deadline_text(text)
    duration_raw = _extract_duration_text(text)

    deadline: str | None
    try:
        deadline = _normalize_deadline(deadline_raw, now=now) if deadline_raw is not None else None
    except Exception:
        deadline = None

    duration: int | None
    try:
        duration = _normalize_duration_minutes(duration_raw) if duration_raw is not None else None
    except Exception:
        duration = None

    return {"tasks": tasks, "constraints": {"rating": rating, "deadline": deadline, "duration": duration}}


_RE_COUNT_TASKS = re.compile(r"\b(\d{1,2})\s*(?:stops?|places?)\b", re.IGNORECASE)
_RE_COUNT_TASKS_WITHIN = re.compile(r"\b(?:find|visit)\s*(\d{1,2})\s*(?:stops?|places?)\b", re.IGNORECASE)


def _infer_count_based_tasks(text: str) -> list[str]:
    """
    If the user asks for N "places/stops" without specifying types, synthesize N generic tasks.
    This keeps the rest of the pipeline working (mapping/solver) while still being faithful.
    """
    if not text:
        return []
    m = _RE_COUNT_TASKS_WITHIN.search(text) or _RE_COUNT_TASKS.search(text)
    if not m:
        return []
    try:
        n = int(m.group(1))
    except Exception:
        return []
    if n <= 0:
        return []
    # Use a neutral default that maps to something searchable.
    return ["place"] * min(n, 10)


def _extract_rating(text: str) -> float | None:
    m = re.search(r"(?:rating|stars?)\s*(?:above|over|>=|at\s*least)?\s*(\d(?:\.\d+)?)", text, flags=re.IGNORECASE)
    if not m:
        m = re.search(r"\b(\d(?:\.\d+)?)\s*(?:stars?|rating)\b", text, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return _normalize_rating(float(m.group(1)))
    except Exception:
        return None

def _extract_deadline_text(text: str) -> str | None:
    m = re.search(r"\b(?:before|by|until|no\s*later\s*than)\s+([0-9]{1,2}(?::[0-9]{2})?\s*(?:[ap]\.?\s*m\.?)?)\b", text, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"\b([0-9]{1,2}:[0-9]{2})\b", text)
    if m:
        return m.group(1).strip()
    m = re.search(r"\b([0-9]{1,2}\s*(?:[ap]\.?\s*m\.?))\b", text, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None

def _extract_duration_text(text: str) -> str | None:
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(hours?|minutes?)\b", text, flags=re.IGNORECASE)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    return None

def _normalize_rating(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    try:
        r = float(v)
    except (TypeError, ValueError):
        return None
    if not (0.0 <= r <= 5.0):
        return None
    return float(r)

_RE_HHMM = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")
_RE_AMPM = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\.?\s*$", re.IGNORECASE)
_RE_IN_HOURS = re.compile(r"^\s*(?:in\s*)?(\d+(?:\.\d+)?)\s*hours?\s*$", re.IGNORECASE)
_RE_IN_MINUTES = re.compile(r"^\s*(?:in\s*)?(\d+(?:\.\d+)?)\s*minutes?\s*$", re.IGNORECASE)

def _normalize_deadline(v: Any, *, now: datetime) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        raise ValueError("deadline must be a time string or null")
    s = str(v).strip()
    if not s or s.lower() in {"null", "none", "n/a", "na"}:
        return None

    m = _RE_HHMM.match(s)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError(f"deadline out of range: {s!r}")
        return f"{hh:02d}:{mm:02d}"

    m = _RE_AMPM.match(s)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2) or "0")
        ap = m.group(3).lower()
        if not (1 <= hh <= 12 and 0 <= mm <= 59):
            raise ValueError(f"deadline out of range: {s!r}")
        hh = hh % 12
        if ap == "p":
            hh += 12
        return f"{hh:02d}:{mm:02d}"

    m = _RE_IN_HOURS.match(s)
    if m:
        hours = float(m.group(1))
        if not math.isfinite(hours) or hours <= 0:
            raise ValueError(f"invalid relative deadline: {s!r}")
        dt = now + timedelta(seconds=int(round(hours * 3600)))
        return dt.strftime("%H:%M")

    m = _RE_IN_MINUTES.match(s)
    if m:
        mins = float(m.group(1))
        if not math.isfinite(mins) or mins <= 0:
            raise ValueError(f"invalid relative deadline: {s!r}")
        dt = now + timedelta(seconds=int(round(mins * 60)))
        return dt.strftime("%H:%M")
    raise ValueError(f"Unrecognized deadline format (expected HH:MM or am/pm): {s!r}")

_RE_NUMBER = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*$")
_RE_HOURS = re.compile(r"(\d+(?:\.\d+)?)\s*hours?", re.IGNORECASE)
_RE_MINUTES = re.compile(r"(\d+(?:\.\d+)?)\s*minutes?", re.IGNORECASE)

def _normalize_duration_minutes(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        raise ValueError("duration must be minutes or null")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if isinstance(v, float):
            if not math.isfinite(v):
                raise ValueError("duration must be finite")
            if abs(v - int(v)) < 1e-9:
                v = int(v)
        if isinstance(v, int):
            if v < 0:
                raise ValueError("duration must be non-negative")
            return int(v)
    s = str(v).strip()
    if not s or s.lower() in {"null", "none", "n/a", "na"}:
        return None

    m = _RE_NUMBER.match(s)
    if m:
        mins = float(m.group(1))
        if not math.isfinite(mins) or mins < 0:
            raise ValueError(f"invalid duration: {s!r}")
        return int(round(mins))

    hours_match = _RE_HOURS.search(s)
    mins_match = _RE_MINUTES.search(s)
    total = 0.0
    if hours_match:
        h = float(hours_match.group(1))
        if not math.isfinite(h) or h < 0:
            raise ValueError(f"invalid duration hours: {s!r}")
        total += h * 60.0
    if mins_match:
        m_ = float(mins_match.group(1))
        if not math.isfinite(m_) or m_ < 0:
            raise ValueError(f"invalid duration minutes: {s!r}")
        total += m_
    if hours_match or mins_match:
        return int(round(total))
    raise ValueError(f"Unrecognized duration format (expected minutes or hours): {s!r}")

def _safe_json_from_text(text: str) -> Any:
    """
    Attempt to extract JSON from a string - no markdown, no commentary.
    """
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Remove code fences if present
    unfenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    if unfenced != text:
        try:
            return json.loads(unfenced)
        except json.JSONDecodeError:
            pass
    # Try to find JSON dict or array in the text
    obj_match = re.search(r"\{[\s\S]*\}", text)
    if obj_match:
        candidate = obj_match.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    arr_match = re.search(r"\[[\s\S]*\]", text)
    if arr_match:
        candidate = arr_match.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    return None

if __name__ == "__main__":
    test_query = "I want to find a coffee shop with a rating of 4.5 near Duke to stay for 1 hour."
    result = parse_intent(test_query)
    print("--- Parsed Intent ---")
    print(result)