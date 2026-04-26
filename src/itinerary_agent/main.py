from __future__ import annotations

import argparse
import json

from .agent_loop import Agent, AgentDeps
from .config import load_settings
from .constraints.validator import ConstraintValidator
from .evaluation.evaluator import Evaluator
from .integrations.google_maps.client import MockGoogleMapsClient
from .llm.intent_parser import IntentParser, MockLLMClient
from .planning.planner import Planner


def build_agent() -> Agent:
    load_settings()

    # All deps are currently local mocks / simple implementations.
    llm = MockLLMClient()
    intent_parser = IntentParser(llm=llm)
    planner = Planner()
    maps = MockGoogleMapsClient(city="Seoul")
    validator = ConstraintValidator()
    evaluator = Evaluator()

    deps = AgentDeps(
        intent_parser=intent_parser,
        planner=planner,
        maps=maps,
        validator=validator,
        evaluator=evaluator,
    )
    return Agent(deps)


def run(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Itinerary Agent (skeleton)")
    parser.add_argument(
        "--request",
        default="Plan a 2 day trip to Seoul focused on food and museums, balanced pace.",
        help="User request text",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full agent state as JSON",
    )
    args = parser.parse_args(argv)

    agent = build_agent()
    state = agent.run_once(args.request)

    if args.json:
        print(state.model_dump_json(indent=2))
        return

    print(f"Intent: city={state.intent.city} days={state.intent.days} pace={state.intent.pace} interests={state.intent.interests}")
    print("")
    print("Itinerary:")
    for item in state.enriched_itinerary.items:
        line = f"  Day {item.day} {item.time} - {item.title}"
        print(line)
        if item.notes:
            print("    " + item.notes.replace("\n", "\n    "))

    print("")
    if state.validation_errors:
        print("Validation errors:")
        for e in state.validation_errors:
            print(f"  - {e}")
    else:
        print("Validation: OK")

    print("")
    print("Evaluation:")
    print(json.dumps(state.evaluation, indent=2))


if __name__ == "__main__":
    run()
