from __future__ import annotations

import re
from collections import defaultdict, Counter
from typing import Any, Literal

from itinerary_agent.llm import intent_parser
from itinerary_agent.agent_loop import estimate_solver_total_minutes, run_agent

EvalFailureBucket = Literal["time_constraint_violation", "api_failure", "invalid_plan"]

# Wall-clock checks use a fixed day anchor (same as agent_loop._EVAL_DAY_START_MIN), not
# itinerary display times (which are "next hour" from runtime and break "before 8pm").
_EVAL_CLOCK_ANCHOR_MIN = 9 * 60


def _parse_hhmm(s: str | None) -> int | None:
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
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


def _solver_total_from_agent_output(output: dict[str, Any]) -> int | None:
    meta = output.get("plan_meta")
    if not isinstance(meta, dict):
        return None
    v = meta.get("solver_total_minutes")
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(round(v))
    return None


def _all_items_have_place_id(items: list[dict[str, Any]]) -> bool:
    for it in items:
        pid = it.get("place_id") if isinstance(it, dict) else None
        if not isinstance(pid, str) or not pid.strip():
            return False
    return True


def _constraint_min_rating(constraints: dict[str, Any]) -> float | None:
    r = constraints.get("rating")
    if r is None or isinstance(r, bool):
        return None
    try:
        v = float(r)
    except (TypeError, ValueError):
        return None
    return v if 0.0 <= v <= 5.0 else None


def _rating_from_item_notes(notes: Any) -> float | None:
    if not isinstance(notes, str):
        return None
    m = re.search(r"Rating:\s*([\d.]+)", notes, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _duration_cap_minutes(constraints: dict[str, Any]) -> int | None:
    d = constraints.get("duration")
    if d is None or isinstance(d, bool):
        return None
    try:
        v = int(round(float(d)))
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


def evaluate_strict_success(
    *,
    plan_items: list[dict[str, Any]] | None,
    intent: dict[str, Any] | None,
    solver_total_minutes: int | None = None,
    enforce_time_constraints: bool = True,
) -> tuple[bool, float | None, str | None, str | None]:
    """
    Success iff:
    - plan exists (non-empty list of steps)
    - total_time (solver-consistent trip minutes) is not None
    - if ``enforce_time_constraints`` (e.g. agent_with_solver):
      - wall-clock: trip end (09:00 anchor + total_time) <= intent deadline when set
      - duration: total_time <= intent duration minutes when set
      - require a time constraint in intent (deadline or duration) when both absent
    - if ``not enforce_time_constraints`` (e.g. agent_no_solver ablation):
      - skip all time vs deadline / duration checks (may succeed with time-infeasible plans)
    - each step has a non-empty place_id
    - if intent requests a minimum rating, each item's notes must show Rating: >= that

    Returns (success, total_time_minutes, deadline_hhmm_or_none, error_reason).
    """
    items = plan_items if isinstance(plan_items, list) else []
    if not items:
        return False, None, None, "no_plan"

    constraints = intent.get("constraints", {}) if isinstance(intent, dict) else {}
    if not isinstance(constraints, dict):
        constraints = {}

    n = len(items)
    if solver_total_minutes is not None:
        eff_total = int(solver_total_minutes)
    else:
        eff_total = int(estimate_solver_total_minutes(n, constraints))
    if eff_total <= 0:
        return False, None, None, "no_total_time"

    total_time_f = float(eff_total)

    deadline_raw = constraints.get("deadline")
    deadline_m = _parse_hhmm(deadline_raw) if deadline_raw is not None else None
    deadline_str = deadline_raw.strip() if isinstance(deadline_raw, str) else None

    duration_cap = _duration_cap_minutes(constraints)

    if enforce_time_constraints:
        if deadline_m is not None:
            end_m = _EVAL_CLOCK_ANCHOR_MIN + eff_total
            if end_m > deadline_m:
                return False, total_time_f, deadline_str, "exceeds_deadline"
        if duration_cap is not None:
            if eff_total > int(duration_cap):
                return False, total_time_f, deadline_str, "exceeds_deadline"

        if deadline_m is None and duration_cap is None:
            return False, total_time_f, deadline_str, "missing_deadline"

    min_rating = _constraint_min_rating(constraints)
    if min_rating is not None and min_rating > 0:
        for it in items:
            got = _rating_from_item_notes(it.get("notes") if isinstance(it, dict) else None)
            if got is None or got + 1e-6 < min_rating:
                return False, total_time_f, deadline_str, "constraint_rating_unmet"

    if not _all_items_have_place_id(items):
        return False, total_time_f, deadline_str, "invalid_place_id"

    return True, total_time_f, deadline_str, None


def classify_failure_bucket(
    error_reason: str | None,
    raw_output: Any,
    *,
    method: str,
) -> EvalFailureBucket:
    """
    Map fine-grained errors into three evaluation buckets.
    """
    r = (error_reason or "").strip()
    msg = str(raw_output or "").lower()
    combined = (r + " " + msg).lower()

    if r in ("exceeds_deadline", "missing_deadline", "no_total_time"):
        return "time_constraint_violation"
    if r == "time_constraint_violation" or "time_constraint_violation" in combined:
        return "time_constraint_violation"

    if (
        "intent parsing failed" in combined
        or "readtimeout" in combined
        or "connectionerror" in combined
        or "googl" in combined
        or "api" in combined
        or "network" in combined
        or "429" in combined
        or "403" in combined
    ):
        return "api_failure"

    return "invalid_plan"


def _map_agent_failure_reason(output: dict[str, Any]) -> str:
    errs = output.get("last_errors") or []
    if isinstance(errs, list):
        if any(str(e) == "time_constraint_violation" for e in errs):
            return "time_constraint_violation"
        if any(str(e) == "invalid_plan" for e in errs):
            return "invalid_plan"
    msg = (
        output.get("reason")
        or output.get("last_error")
        or output.get("error")
        or output.get("message")
        or output.get("result", {}).get("reason")
        or ""
    )
    if "time_constraint_violation" in msg:
        return "time_constraint_violation"
    if "invalid_plan" in msg:
        return "invalid_plan"
    if "Intent parsing failed" in msg:
        return "api_failure"
    if "deadline" in msg or "exceeds" in msg or "time" in msg:
        return "time_constraint_violation"
    if "API" in msg or "googlemaps" in msg or "network" in msg:
        return "api_failure"
    if "plan" in msg or "steps" in msg:
        return "invalid_plan"
    return "invalid_plan"


def baseline_llm(query):
    """
    Real baseline: parses intent only (no Maps / no solver).
    - ``success``: lenient — any parsed tasks count as "success" (optimistic, often wrong).
    - ``strict_success``: constraint-valid itinerary (always False here — no real plan).
    """
    # Keep evaluation runs snappy even if local Ollama is slow/unavailable.
    intent = intent_parser.parse_intent(query, timeout_s=5.0, max_attempts=1)
    tasks = intent.get("tasks", [])
    num_stops = len(tasks)
    lenient_success = bool(num_stops)
    strict_ok, total_time, deadline_str, strict_err = evaluate_strict_success(
        plan_items=[],
        intent=intent if isinstance(intent, dict) else {},
    )
    err_reason = None if lenient_success else "no_tasks_parsed"
    return {
        "success": lenient_success,
        "strict_success": strict_ok,
        "time_check_skipped": False,
        "total_time": total_time,
        "deadline": deadline_str,
        "num_stops": num_stops,
        "number_of_retries": 0,
        "error_reason": err_reason,
        "raw_output": intent,
        "query": query,
    }


def agent_with_solver(query):
    """
    Uses full agent system (with constraint solver).
    """
    output = run_agent(query)
    # run_agent() returns { "ok": bool, "itinerary": {...}, "intent": {...}, ... }
    agent_ok = bool(output.get("ok", output.get("success", False)))
    itinerary = output.get("itinerary") if isinstance(output.get("itinerary"), dict) else {}
    items = itinerary.get("items", []) if isinstance(itinerary.get("items"), list) else []
    num_stops = len(items)
    retries = 0

    intent_dict = output.get("intent") if isinstance(output.get("intent"), dict) else {}
    plan_items = items if agent_ok else []
    solver_m = _solver_total_from_agent_output(output) if agent_ok else None
    strict_ok, total_time, deadline_str, strict_err = evaluate_strict_success(
        plan_items=plan_items,
        intent=intent_dict,
        solver_total_minutes=solver_m,
    )
    success = strict_ok
    if success:
        err_reason = None
    elif not agent_ok:
        err_reason = _map_agent_failure_reason(output)
    else:
        err_reason = strict_err or "criteria_not_met"

    return {
        "success": success,
        "strict_success": strict_ok,
        "time_check_skipped": False,
        "total_time": total_time,
        "deadline": deadline_str,
        "num_stops": num_stops,
        "number_of_retries": retries,
        "error_reason": err_reason,
        "raw_output": output,
        "query": query,
    }


def agent_no_solver(query):
    """
    Uses agent system but skips constraint solver validation step (ablation).
    Assumes run_agent accepts a disable_solver argument.
    """
    output = run_agent(query, disable_solver=True)
    agent_ok = bool(output.get("ok", output.get("success", False)))
    itinerary = output.get("itinerary") if isinstance(output.get("itinerary"), dict) else {}
    items = itinerary.get("items", []) if isinstance(itinerary.get("items"), list) else []
    num_stops = len(items)
    retries = 0

    intent_dict = output.get("intent") if isinstance(output.get("intent"), dict) else {}
    plan_items = items if agent_ok else []
    solver_m = _solver_total_from_agent_output(output) if agent_ok else None
    # Ablation: no constraint solver in the agent; evaluation also skips time vs deadline/duration
    # so infeasible-in-time plans still count as success (higher success rate, may be invalid w.r.t. time).
    strict_ok, total_time, deadline_str, strict_err = evaluate_strict_success(
        plan_items=plan_items,
        intent=intent_dict,
        solver_total_minutes=solver_m,
        enforce_time_constraints=False,
    )
    success = strict_ok
    if success:
        err_reason = None
    elif not agent_ok:
        err_reason = _map_agent_failure_reason(output)
    else:
        err_reason = strict_err or "criteria_not_met"

    return {
        "success": success,
        "strict_success": strict_ok,
        "time_check_skipped": True,
        "total_time": total_time,
        "deadline": deadline_str,
        "num_stops": num_stops,
        "number_of_retries": retries,
        "error_reason": err_reason,
        "raw_output": output,
        "query": query,
    }


def eval_methods(queries):
    methods = {
        "baseline_llm": baseline_llm,
        "agent_no_solver": agent_no_solver,
        "agent_with_solver": agent_with_solver,
    }
    results = defaultdict(list)
    for method, func in methods.items():
        for q in queries:
            res = func(q)
            results[method].append(res)
    return results

def print_results(results, queries):
    print(
        "{:<28} | {:<18} | {:<8} | {:<7} | {:<12} | {:<7} | {:<10}".format(
            "Query", "Method", "Success", "Strict", "Total Time", "Stops", "Retries"
        )
    )
    print('-'*105)
    stats = defaultdict(list)
    for i, q in enumerate(queries):
        for method in results:
            res = results[method][i]
            strict_s = res.get("strict_success", res["success"])
            print(
                "{:<28} | {:<18} | {:<8} | {:<7} | {:<12} | {:<7} | {:<10}".format(
                    q[:28],
                    method,
                    str(res["success"]),
                    str(strict_s),
                    str(res["total_time"]),
                    str(res["num_stops"]),
                    res["number_of_retries"],
                )
            )
            stats[method].append(res)
    print('\nSummary (Success): baseline=lenient(parsed tasks); agent_with_solver=strict (time+places+rating);')
    print('  agent_no_solver=strict except time vs deadline/duration (ablation, may be time-infeasible).')
    print("{:<18} | {:<12} | {:<14} | {:<12}".format("Method", "Success Rate", "Strict valid", "Avg Retries"))
    print('-'*60)
    for method, items in stats.items():
        n = len(items)
        succ = sum(1 for x in items if x["success"])
        strict_ok = sum(1 for x in items if x.get("strict_success", False))
        avg_retries = sum(x["number_of_retries"] for x in items) / n
        print(
            f"{method:<18} | {succ}/{n} ({succ/n*100:.0f}%)   | "
            f"{strict_ok}/{n} ({strict_ok/n*100:.0f}%)     | {avg_retries:.2f}"
        )

    print('\nAblation Comparison (reported Success rate):')
    print("Success Rate: agent_with_solver vs agent_no_solver vs baseline_llm")
    print("{:<22} {:>10} {:>10} {:>10}".format("Metric", "with_solver", "no_solver", "baseline"))
    def s_rate(ds): return sum(1 for x in ds if x["success"]) / len(ds)
    def mean_ret(ds): return sum(x["number_of_retries"] for x in ds) / len(ds)
    methods = ["agent_with_solver", "agent_no_solver", "baseline_llm"]
    srates = [s_rate(stats[m]) for m in methods]
    aretries = [mean_ret(stats[m]) for m in methods]
    print("{:<22} {:>10.0%} {:>10.0%} {:>10.0%}".format("Success Rate", *srates))
    print("{:<22} {:>10.2f} {:>10.2f} {:>10.2f}".format("Avg Retries", *aretries))

def error_analysis(results, queries):
    print("\nError Analysis")
    print("=" * 80)
    method_names = {
        "baseline_llm": "Baseline LLM",
        "agent_no_solver": "Agent No Solver",
        "agent_with_solver": "Agent With Solver",
    }

    failures_by_bucket: dict[tuple[str, EvalFailureBucket], list] = defaultdict(list)
    failure_details: list[tuple[str, str, str, EvalFailureBucket, Any]] = []
    for method, runlist in results.items():
        for i, res in enumerate(runlist):
            if not res["success"]:
                reason = res.get("error_reason", "unknown") or "unknown"
                bucket = classify_failure_bucket(reason, res.get("raw_output"), method=method)
                failures_by_bucket[(method, bucket)].append(res)
                failure_details.append((method, queries[i], reason, bucket, res.get("raw_output")))

    print("\nAll Failed Queries (fine-grained reason + bucket):\n")
    line = "{:<18} | {:<28} | {:<22} | {:<26}".format("Method", "Query", "Bucket", "Detail")
    print(line)
    print('-'*100)
    for method, query, reason, bucket, _ in failure_details:
        print(
            "{:<18} | {:<28} | {:<22} | {:<26}".format(
                method_names.get(method, method),
                query[:28],
                bucket,
                (reason or "")[:26],
            )
        )
    print()

    print("Failure Breakdown by Method & Bucket (time_constraint_violation | api_failure | invalid_plan):")
    line = "{:<18} | {:<26} | {:>7}".format("Method", "Bucket", "Count")
    print(line)
    print('-'*55)
    summary_counts = Counter()
    for (method, bucket), vals in failures_by_bucket.items():
        summary_counts[(method, bucket)] = len(vals)
        print("{:<18} | {:<26} | {:>7}".format(method_names.get(method, method), bucket, len(vals)))
    print()

    print("Aggregate Failure Buckets (All Methods):")
    agg_bucket_counts = Counter()
    for (_, bucket), count in summary_counts.items():
        agg_bucket_counts[bucket] += count
    line = "{:<26} | {:>7}".format("Bucket", "Count")
    print(line)
    print('-'*36)
    for bucket in ("time_constraint_violation", "api_failure", "invalid_plan"):
        c = agg_bucket_counts.get(bucket, 0)
        print("{:<26} | {:>7}".format(bucket, c))
    print()

    # Baseline: lenient success never proves a real itinerary
    baseline_items = results.get("baseline_llm", [])
    false_conf = sum(1 for r in baseline_items if r.get("success") and not r.get("strict_success"))
    if baseline_items:
        print(
            f"Baseline optimistic successes without strict proof: {false_conf}/{len(baseline_items)} "
            "(strict_success is always False — no mapped plan).\n"
        )

    print(
        "Summary:\n"
        f"  Total failed rows (by reported Success): {len(failure_details)}\n"
        "  Buckets: time_constraint_violation | api_failure | invalid_plan\n"
    )

if __name__ == "__main__":
    # Mix of feasible routes and deliberately infeasible time windows (solver should reject).
    queries = [
        # Feasible if APIs return places: modest stops, generous duration
        "Find a coffee shop near Duke with rating above 4.5, stay 1 hour, go home before 8pm",
        "Go to a cafe and supermarket then return before 7pm",
        # Tight but possible with good APIs (2 stops, 2h budget vs ~140m solver model)
        "Visit 2 museums in 2 hours before 6pm",
        # Infeasible under default step model: 4 * (60+10) min >> 40 min
        "Visit coffee shop, museum, park, and restaurant in 40 minutes",
        # Infeasible: 3 heavy stops in 25 minutes
        "Museum then library then gym in 25 minutes",
        # Infeasible: three errands in 18 minutes
        "Supermarket, pharmacy, and gym in 18 minutes",
        # Duration-only tight window (2 stops need ~140m)
        "Find 2 stops within 45 minutes",
        # Clock + many stops (duration cap if parser fills it; else high bar)
        "Coffee shop, bar, restaurant, and home before 5pm in 90 minutes total",
    ]
    results = eval_methods(queries)
    print_results(results, queries)
    error_analysis(results, queries)