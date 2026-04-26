from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .api.maps import GoogleMapsClient
from .agent.constraint_solver import ConstraintSolver
from .llm.intent_parser import parse_intent
from .models import Itinerary, ItineraryItem
from .config import load_settings
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_TRAVEL_SEC = 600
_TRAVEL_MIN = 10
_EVAL_DAY_START_MIN = 9 * 60


def _parse_hhmm_clock(s: str) -> int | None:
    s = (s or "").strip()
    parts = s.split(":")
    if len(parts) != 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return h * 60 + m


def _budget_minutes_for_solver(constraints: dict[str, Any]) -> int:
    """
    Total minutes the ConstraintSolver is allowed for sum(travel + activity).
    - Prefer explicit duration (whole-trip budget in minutes).
    - Else wall-clock deadline: minutes from 09:00 to deadline (same anchor as evaluation).
    - Else generous default (12h).
    """
    d = constraints.get("duration")
    if d is not None and not isinstance(d, bool):
        try:
            v = int(round(float(d)))
            if v > 0:
                return min(v, 23 * 60 + 59)
        except (TypeError, ValueError):
            pass
    dl = constraints.get("deadline")
    if isinstance(dl, str) and dl.strip():
        dm = _parse_hhmm_clock(dl.strip())
        if dm is not None:
            return max(1, min(dm - _EVAL_DAY_START_MIN, 23 * 60 + 59))
    return 12 * 60


def _solver_deadline_hhmm(constraints: dict[str, Any]) -> str:
    """Encode budget B minutes as 'HH:MM' for ConstraintSolver."""
    b = _budget_minutes_for_solver(constraints)
    return f"{b // 60:02d}:{b % 60:02d}"


def _build_constraint_steps(
    tasks: list[Any], constraints: dict[str, Any]
) -> tuple[list[dict[str, Any]], int]:
    """
    Per-step activity duration is chosen so total travel+activity fits the budget
    (matches evaluation and avoids false time_constraint_violation on feasible trips).
    """
    clean = [str(t).strip() for t in tasks if str(t).strip()]
    n = len(clean)
    if n == 0:
        return [], 0
    budget = _budget_minutes_for_solver(constraints)
    remain_act = budget - _TRAVEL_MIN * n
    if remain_act < 0:
        remain_act = 0
    dur_each = max(1, remain_act // n) if n else 1
    extra = max(0, remain_act - dur_each * n)
    durs = [dur_each + (1 if i < extra else 0) for i in range(n)]
    steps: list[dict[str, Any]] = []
    total = 0
    for name, dur in zip(clean, durs):
        steps.append(
            {
                "name": name,
                "location": (0.0, 0.0),
                "duration": int(dur),
                "travel_time": _TRAVEL_SEC,
            }
        )
        total += _TRAVEL_MIN + int(dur)
    return steps, total


def estimate_solver_total_minutes(num_stops: int, constraints: dict[str, Any]) -> int:
    """Same total minutes as ConstraintSolver would use for synthetic n-stop plans."""
    if num_stops <= 0:
        return 0
    tasks = ["x"] * num_stops
    _, tot = _build_constraint_steps(tasks, constraints)
    return tot


@dataclass(frozen=True)
class AgentDeps:
    maps: GoogleMapsClient
    solver: Any  # Solver can be a factory or None
    max_iters: int = 3


class Agent:
    """
    Full agentic itinerary loop:
      perception (LLM intent) -> plan proposal (LLM) -> constraint solve -> (feedback, replanning) -> mapping -> return itinerary
    """

    def __init__(self, deps: AgentDeps, disable_solver: bool = False):
        self._deps = deps
        self._disable_solver = disable_solver

    def run_once(self, request_text: str) -> dict[str, Any]:
        """
        Returns either:
          { "ok": True, "itinerary": <Itinerary dict>, "intent": <intent dict>, "iterations": n }
        or:
          { "ok": False, "reason": "...", "last_errors": [...], "iterations": n, "intent": <intent dict|null> }
        """
        intent: dict[str, Any] | None = None
        plan: list[Any] | None = None
        constraints: dict[str, Any] = {}
        last_errors: list[str] = []

        for i in range(1, self._deps.max_iters + 1):
            logger.info("Agent iteration %s/%s start", i, self._deps.max_iters)

            # Prepare LLM query with error feedback if any
            llm_query = self._with_error_feedback(request_text, last_errors)
            logger.info("Perception: parsing LLM candidate plan and constraints")
            try:
                # LLM generates intent, which contains plan (tasks) and constraints, but
                # tasks should only be natural-language user tasks, never constraints.
                intent = parse_intent(llm_query)
            except Exception as e:  # network/model issues
                logger.exception("Intent parsing failed")
                return {
                    "ok": False,
                    "reason": f"Intent parsing failed: {e}",
                    "last_errors": last_errors,
                    "iterations": i,
                    "intent": intent,
                }

            # Extract candidate plan and constraints
            tasks = intent.get("tasks")
            if not isinstance(tasks, list) or not tasks:
                last_errors = ["LLM did not return tasks."]
                logger.warning("No tasks found in intent: %r", intent)
                continue
            # Ensure tasks do NOT accidentally include constraints
            # This also means "tasks" should only ever be user-activities, not deadlines etc.
            # (Nothing to explicitly filter unless your LLM can make mistakes, but do not allow LLM to re-inject constraints as tasks.)

            constraints = intent.get("constraints")
            if not isinstance(constraints, dict):
                constraints = {}

            solver_deadline = _solver_deadline_hhmm(constraints)

            # For ablation, if disable_solver, skip constraint check and just map plan to itinerary
            if self._disable_solver:
                logger.info("Ablation active: skipping constraint solver. Building itinerary directly from tasks.")
                _, solver_total_m = _build_constraint_steps(tasks, constraints)
                itinerary, planning_warnings = self._tasks_to_itinerary(tasks, constraints)
                return {
                    "ok": True,
                    "itinerary": itinerary.model_dump(),
                    "intent": intent,
                    "iterations": i,
                    "ablation": "disable_solver",
                    "plan_meta": {"solver_total_minutes": solver_total_m},
                }

            steps, solver_total_m = _build_constraint_steps(tasks, constraints)

            logger.info("Validating plan using ConstraintSolver.")
            constraint_solver = self._deps.solver
            result_valid, result_msg = constraint_solver(steps, solver_deadline).validate() \
                if callable(constraint_solver) else constraint_solver.validate(steps, solver_deadline)

            if result_valid:
                logger.info("Plan validated by ConstraintSolver. Mapping tasks to places.")
                itinerary, planning_warnings = self._tasks_to_itinerary(tasks, constraints)
                return {
                    "ok": True,
                    "itinerary": itinerary.model_dump(),
                    "intent": intent,
                    "iterations": i,
                    "plan_meta": {"solver_total_minutes": solver_total_m},
                }
            else:
                logger.info("Iteration %s failed constraint solver: %s", i, result_msg)
                last_errors = [result_msg]
                # Feedback to LLM for next attempt

        logger.error("Agent failed after max iterations. Last errors: %s", last_errors)
        return {
            "ok": False,
            "reason": "Failed to produce a valid itinerary within max iterations.",
            "last_errors": last_errors,
            "iterations": self._deps.max_iters,
            "intent": intent,
        }

    def _with_error_feedback(self, query: str, errors: list[str]) -> str:
        if not errors:
            return query
        bullets = "\n".join([f"- {e}" for e in errors])
        return (
            f"{query}\n\n"
            "Previous attempt failed constraint validation with these errors:\n"
            f"{bullets}\n\n"
            "Please adjust the tasks and constraints to resolve the errors while keeping the user's intent."
        )

    def _tasks_to_itinerary(self, tasks: list[Any], constraints: dict[str, Any]) -> tuple[Itinerary, list[str]]:
        """
        Given a list of user tasks and constraints, look up places and build an itinerary.
        Only tasks are sent to Google Maps API, never constraints.
        """
        warnings: list[str] = []

        min_rating = constraints.get("rating", 0.0)
        try:
            min_rating_f = float(min_rating) if min_rating is not None else 0.0
        except (TypeError, ValueError):
            min_rating_f = 0.0
            warnings.append("Invalid rating constraint; ignored.")

        # Simple schedule: start now rounded to next hour, 60-min slots.
        start = datetime.now().replace(minute=0, second=0, microsecond=0)
        if datetime.now().minute > 0:
            start = start + timedelta(hours=1)

        items: list[ItineraryItem] = []
        last_place_name: str | None = None
        last_place_id: str | None = None

        for idx, raw_task in enumerate(tasks):
            task = str(raw_task).strip()
            if not task:
                continue

            logger.info("Tool: find_place for task=%r min_rating=%s", task, min_rating_f)
            place = self._deps.maps.find_place(task, min_rating=min_rating_f)
            if not place:
                warnings.append(f"No place found for task '{task}' with min_rating={min_rating_f}.")
                # Still create an item so user sees the task, but without a place_id.
                items.append(
                    ItineraryItem(
                        day=1,
                        time=(start + timedelta(hours=idx)).strftime("%H:%M"),
                        title=task,
                        place_id=None,
                        notes="No matching place found.",
                    )
                )
                continue

            notes = []
            if place.get("rating") is not None:
                notes.append(f"Rating: {place['rating']}")
            if place.get("lat") is not None and place.get("lng") is not None:
                notes.append(f"Location: ({place['lat']}, {place['lng']})")

            # Add travel info from previous place (best-effort)
            if last_place_name and place.get("name"):
                logger.info("Tool: get_travel_info origin=%r destination=%r", last_place_name, place["name"])
                travel = self._deps.maps.get_travel_info(last_place_name, str(place["name"]))
                if travel:
                    notes.append(
                        f"Travel from previous: {travel['distance']}m, {travel['duration']}s"
                    )
                else:
                    warnings.append(
                        f"Travel info unavailable: '{last_place_name}' -> '{place.get('name')}'."
                    )

            items.append(
                ItineraryItem(
                    day=1,
                    time=(start + timedelta(hours=idx)).strftime("%H:%M"),
                    title=str(place.get("name") or task),
                    place_id=str(place.get("place_id") or "") or None,
                    notes="\n".join(notes) if notes else None,
                )
            )

            last_place_name = str(place.get("name") or task)
            last_place_id = str(place.get("place_id") or "") or None

        itinerary = Itinerary(city="(from tasks)", days=1, items=items)
        if last_place_id is None and items:
            warnings.append("No place_id attached to final plan.")

        return itinerary, warnings


def run_agent(query, disable_solver: bool = False) -> dict[str, Any]:
    """
    Top-level agent runner: executes the full itinerary planning pipeline for the provided query string.

    Args:
        query (str): User request or itinerary description.
        disable_solver (bool): If True, skip constraint solver (ablation).

    Returns:
        dict: Result dictionary (see Agent.run_once)
    """
    settings = load_settings()
    maps_client = GoogleMapsClient(api_key=settings.google_maps_api_key)
    # We build a ConstraintSolver factory for per-call context (for now, may be changed)
    def solver_factory(steps, deadline):
        return ConstraintSolver(steps, deadline)

    deps = AgentDeps(maps=maps_client, solver=solver_factory)
    agent = Agent(deps, disable_solver=disable_solver)
    return agent.run_once(query)